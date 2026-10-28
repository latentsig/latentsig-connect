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
        'INITIAL_ADMIN_EMAILS': ','.join(ADMINS), 'OCR_ENABLED': 'false',
        'OPENROUTER_API_KEY': '', 'CONSENT_NOTICE_VERSION': '2026-10-21-v1',
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
    else:
        raise SystemExit('Expected environment, domain, admins, or check-dns.')
