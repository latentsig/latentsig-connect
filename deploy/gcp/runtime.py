"""Keep deployment credentials on the VM and provision only unset passwords."""
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

SECRETS = Path('/srv/latentsig-connect/secrets')
ADMINS = ['bharat@latentsig.com', 'bhoomika@latentsig.com']


def save(path, value):
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb' if isinstance(value, bytes) else 'w') as stream:
        stream.write(value)
    temporary.chmod(0o600)
    temporary.replace(path)


def validate_domain(domain):
    labels = domain.split('.')
    if len(domain) > 253 or len(labels) < 2 or labels[-1].isdigit() or any(
        not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
        for label in labels
    ):
        raise SystemExit('Provide a valid DNS hostname without a scheme, path, or port.')


def change_domain(domain):
    validate_domain(domain)
    path = SECRETS / 'production.env'
    if not path.is_file():
        raise SystemExit('Existing production.env is required for domain migration.')
    replacements = {
        b'PUBLIC_DOMAIN': domain.encode(),
        b'FRONTEND_URL': f'https://{domain}'.encode(),
        b'FRONTEND_URLS': f'https://{domain}'.encode(),
        b'GOOGLE_REDIRECT_URI': f'https://{domain}/api/v1/auth/google/callback'.encode(),
    }
    counts = dict.fromkeys(replacements, 0)
    updated = []
    for line in path.read_bytes().splitlines(keepends=True):
        content = line.rstrip(b'\r\n')
        key, separator, _ = content.partition(b'=')
        if separator and key in replacements:
            counts[key] += 1
            line = key + b'=' + replacements[key] + line[len(content):]
        updated.append(line)
    if any(count != 1 for count in counts.values()):
        raise SystemExit('Expected exactly one entry for each public origin setting. Environment unchanged.')
    save(path, b''.join(updated))
    print('Public origin settings updated. Rebuild the frontend and issue TLS before public use.')


def env_value_literal(value):
    """Read a literal Compose env value without expanding it."""
    stripped = value.strip()
    if stripped[:1] in {b'"', b"'"}:
        quote = stripped[:1]
        escaped = False
        closing = None
        for index in range(1, len(stripped)):
            character = stripped[index:index + 1]
            if character == quote and not escaped:
                closing = index
                break
            if character == b'\\' and not escaped:
                escaped = True
            else:
                escaped = False
        if closing is None:
            return None
        literal = stripped[1:closing].strip()
        trailing = stripped[closing + 1:]
        if trailing:
            if not trailing.startswith((b' ', b'\t')) or not trailing.strip().startswith(b'#'):
                return None
    else:
        if re.match(rb'^\s+#', value):
            literal = b''
        else:
            literal = re.split(rb'\s+#', value, maxsplit=1)[0].strip()
    if b'$' in literal:
        return None
    return literal


def select_ocr_provider(provider, project_id=None):
    """Select an OCR provider without changing unrelated environment settings."""
    if provider not in {'ollama', 'openrouter', 'vertex'}:
        raise SystemExit('OCR provider must be ollama, openrouter, or vertex.')
    if project_id is not None and provider != 'vertex':
        raise SystemExit('A project ID can only be supplied when selecting vertex.')
    path = SECRETS / 'production.env'
    if not path.is_file():
        raise SystemExit('Existing production.env is required to select an OCR provider.')

    original = path.read_bytes()
    lines = original.splitlines(keepends=True)
    values = {}
    counts = {}
    for line in lines:
        content = line.rstrip(b'\r\n')
        name, separator, _ = content.partition(b'=')
        if separator:
            counts[name] = counts.get(name, 0) + 1
            values[name] = content.partition(b'=')[2]

    touched = [b'OCR_ENABLED', b'OCR_PROVIDER']
    replacements = {b'OCR_ENABLED': b'true', b'OCR_PROVIDER': provider.encode()}
    if provider == 'ollama':
        touched.extend([
            b'OLLAMA_BASE_URL', b'OLLAMA_MODEL',
            b'OCR_TIMEOUT_SECONDS', b'OCR_MAX_RETRIES',
        ])
    elif provider == 'vertex':
        touched.extend([b'GOOGLE_CLOUD_PROJECT', b'VERTEX_AI_MODEL'])
    if any(counts.get(name, 0) > 1 for name in touched):
        raise SystemExit('Duplicate OCR setting in production.env; environment unchanged.')

    if provider == 'ollama':
        defaults = {
            b'OLLAMA_BASE_URL': b'http://ollama:11434',
            b'OLLAMA_MODEL': b'openbmb/minicpm-ocr1.0',
            b'OCR_TIMEOUT_SECONDS': b'85',
            b'OCR_MAX_RETRIES': b'0',
        }
        for name, default in defaults.items():
            value = values.get(name, b'').strip()
            sensible = bool(value)
            if name in {b'OCR_TIMEOUT_SECONDS', b'OCR_MAX_RETRIES'}:
                try:
                    number = int(value)
                except ValueError:
                    sensible = False
                else:
                    lower, upper = (1, 120) if name == b'OCR_TIMEOUT_SECONDS' else (0, 5)
                    sensible = lower <= number <= upper
            if not sensible:
                replacements[name] = default
    elif provider == 'openrouter':
        if counts.get(b'OPENROUTER_API_KEY', 0) > 1:
            raise SystemExit('Duplicate OPENROUTER_API_KEY in production.env; environment unchanged.')
        if not env_value_literal(values.get(b'OPENROUTER_API_KEY', b'')):
            raise SystemExit('OPENROUTER_API_KEY must already contain a nonempty literal value before selecting openrouter. Environment unchanged.')
    if provider == 'vertex':
        configured_project = env_value_literal(values.get(b'GOOGLE_CLOUD_PROJECT', b''))
        supplied_project = project_id.encode() if project_id is not None else None
        if supplied_project is not None and not re.fullmatch(rb'[a-z][a-z0-9-]{4,61}[a-z0-9]', supplied_project):
            raise SystemExit('Provide a valid literal Google Cloud project ID. Environment unchanged.')
        if counts.get(b'GOOGLE_CLOUD_PROJECT', 0):
            if configured_project is None or not re.fullmatch(rb'[a-z][a-z0-9-]{4,61}[a-z0-9]', configured_project):
                raise SystemExit('Existing GOOGLE_CLOUD_PROJECT must contain a valid literal project ID. Environment unchanged.')
            if supplied_project is not None and configured_project != supplied_project:
                raise SystemExit('Existing GOOGLE_CLOUD_PROJECT differs from the supplied project ID. Environment unchanged.')
        elif supplied_project is not None:
            replacements[b'GOOGLE_CLOUD_PROJECT'] = supplied_project
        else:
            raise SystemExit('Supply a project ID with ocr-provider vertex PROJECT_ID. Environment unchanged.')

        configured_model = env_value_literal(values.get(b'VERTEX_AI_MODEL', b''))
        raw_model = values.get(b'VERTEX_AI_MODEL', b'').strip()
        if counts.get(b'VERTEX_AI_MODEL', 0) and configured_model is None and raw_model:
            raise SystemExit('Existing VERTEX_AI_MODEL must contain a literal model ID. Environment unchanged.')
        if not configured_model:
            replacements[b'VERTEX_AI_MODEL'] = b'gemini-3.5-flash-lite'

    updated = []
    for line in lines:
        content = line.rstrip(b'\r\n')
        name, separator, _ = content.partition(b'=')
        if separator and name in replacements:
            line = name + b'=' + replacements[name] + line[len(content):]
        updated.append(line)
    newline = b'\r\n' if b'\r\n' in original else b'\n'
    for name in touched:
        if counts.get(name, 0) == 0:
            if updated and not updated[-1].endswith((b'\n', b'\r')):
                updated[-1] += newline
            updated.append(name + b'=' + replacements.get(name, values.get(name, b'')) + newline)
    save(path, b''.join(updated))
    print(f'OCR provider selected: {provider}; card scanning enabled.')


def environment(domain):
    validate_domain(domain)
    SECRETS.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = SECRETS / 'production.env'
    if path.exists():
        values = dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#'))
        if values.get('PUBLIC_DOMAIN') != domain:
            raise SystemExit('Existing domain differs. Update production.env deliberately and rebuild.')
        path.chmod(0o600)
        print('Preserved production environment.')
        return
    existing_database = subprocess.run(
        ['docker', 'volume', 'inspect', 'latentsig-connect_postgres_data'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if existing_database.returncode == 0:
        raise SystemExit('Database volume exists without production.env. Restore the environment backup before deploying.')
    values = {
        'APP_ENV': 'production', 'APP_SECRET': secrets.token_hex(48),
        'POSTGRES_PASSWORD': secrets.token_hex(32), 'PUBLIC_DOMAIN': domain,
        'CERTBOT_EMAIL': 'bhoomika@latentsig.com', 'FRONTEND_URL': f'https://{domain}',
        'FRONTEND_URLS': f'https://{domain}',
        'GOOGLE_REDIRECT_URI': f'https://{domain}/api/v1/auth/google/callback',
        'ADMIN_EMAIL_ALLOWLIST': 'raksha@latentsig.com,bhoomika@latentsig.com,bharat@latentsig.com,info@latentsig.com,shauryasharthak@latentsig.com',
        'INITIAL_ADMIN_EMAILS': ','.join(ADMINS), 'OCR_ENABLED': 'true',
        'OCR_PROVIDER': 'vertex', 'GOOGLE_CLOUD_PROJECT': 'refined-outlet-249712',
        'VERTEX_AI_MODEL': 'gemini-3.5-flash-lite',
        'OLLAMA_BASE_URL': 'http://ollama:11434',
        'OLLAMA_MODEL': 'openbmb/minicpm-ocr1.0', 'OCR_TIMEOUT_SECONDS': '85',
        'OCR_MAX_RETRIES': '0', 'CONSENT_NOTICE_VERSION': '2026-11-02-v1',
        'OPENROUTER_API_KEY': '',
    }
    save(path, ''.join(f'{key}={value}\n' for key, value in values.items()))
    print('Created private production environment.')


def compose(*arguments, input=None):
    result = subprocess.run(['docker', 'compose', '--profile', 'production', *arguments],
                            input=input, text=True, capture_output=True, check=False)
    if result.returncode:
        raise SystemExit('Admin bootstrap command failed. Credentials remain private; inspect container status.')
    return result.stdout.strip()


def admins():
    path = SECRETS / 'admin-passwords.json'
    credentials = json.loads(path.read_text()) if path.exists() else {}
    for email in ADMINS:
        code = ('from sqlalchemy import select; from app.db.models import User; '
                'from app.db.session import SessionLocal; '
                f'db=SessionLocal(); u=db.scalar(select(User).where(User.email=={email!r})); '
                'print("set" if u and u.password_hash else "unset")')
        state = compose('exec', '-T', 'backend', 'python', '-c', code)
        if state == 'unset':
            password = credentials.setdefault(email, secrets.token_urlsafe(24))
            save(path, json.dumps(credentials) + '\n')
            compose('exec', '-T', 'backend', 'python', '-m', 'app.cli', 'set-password', email,
                    input=f'{password}\n{password}\n')
        elif state != 'set':
            raise SystemExit('Unexpected account state; stopped admin bootstrap.')
        # Existing passwords never change. Role assignment is explicit for initial admins.
        compose('exec', '-T', 'backend', 'python', '-m', 'app.cli', 'grant-admin', email)
    print('Initial admins provisioned; existing passwords preserved.')


def check_dns():
    values = dict(line.split('=', 1) for line in (SECRETS / 'production.env').read_text().splitlines() if line and not line.startswith('#'))
    request = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip',
        headers={'Metadata-Flavor': 'Google'})
    with urllib.request.urlopen(request, timeout=10) as response:
        address = response.read().decode().strip()
    records = {item[4][0] for item in socket.getaddrinfo(values['PUBLIC_DOMAIN'], 80, type=socket.SOCK_STREAM)}
    if records != {address}:
        raise SystemExit('DNS must resolve only to this VM before issuing TLS.')


if __name__ == '__main__':
    os.umask(0o077)
    if sys.argv[1] == 'environment':
        environment(sys.argv[2])
    elif sys.argv[1] == 'domain':
        change_domain(sys.argv[2])
    elif sys.argv[1] == 'admins':
        admins()
    elif sys.argv[1] == 'check-dns':
        check_dns()
    elif sys.argv[1] == 'ocr-provider' and len(sys.argv) in {3, 4}:
        select_ocr_provider(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else None)
    else:
        raise SystemExit('Expected environment, domain, admins, check-dns, or ocr-provider ollama|openrouter|vertex [PROJECT_ID].')
