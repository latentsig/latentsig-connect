#!/usr/bin/env python3
"""Check production access and an admin session, with optional synthetic lead cleanup."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin')
    parser.add_argument('--credentials', type=Path,
                        default=Path('/srv/latentsig-connect/secrets/admin-passwords.json'))
    parser.add_argument('--public-only', action='store_true')
    parser.add_argument('--local', action='store_true', help='Allow only the VM loopback frontend before DNS is ready')
    parser.add_argument('--expected-public-origin', help='Verify the frontend JS contains its configured HTTPS QR origin')
    parser.add_argument('--synthetic', action='store_true', help='Create, retry, read, and delete one synthetic lead')
    args = parser.parse_args()
    origin = args.origin.rstrip('/')
    parsed = urllib.parse.urlsplit(origin)
    local = args.local and origin == 'http://127.0.0.1:8080'
    if (parsed.scheme != 'https' and not local) or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit('Provide an HTTPS origin without a path or credentials.')
    cookies = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    local_cookie = None

    def request(path, payload=None, method=None, extra_headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {'Content-Type': 'application/json', **(extra_headers or {})}
        if local_cookie:
            headers['Cookie'] = local_cookie
        query = urllib.request.Request(origin + path, data=data, method=method, headers=headers)
        try:
            with client.open(query, timeout=30) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def expect(path, status=200, payload=None, method=None, extra_headers=None):
        actual, body, headers = request(path, payload, method, extra_headers)
        if actual != status:
            raise SystemExit(f'Smoke failed: {path} returned {actual}, expected {status}.')
        return body, headers

    for path in ['/health/live', '/health/ready', '/connect', '/admin/login']:
        expect(path)
    if args.expected_public_origin:
        if not args.expected_public_origin.startswith('https://'):
            raise SystemExit('Expected public QR origin must use HTTPS.')
        html, _ = expect('/connect')
        assets = re.findall(rb'<script[^>]+src="([^"]+\.js)"', html)
        if not assets or not any(args.expected_public_origin.encode() in expect(asset.decode())[0] for asset in assets):
            raise SystemExit('Built frontend does not contain the expected public QR origin.')
    body, _ = expect('/api/v1/auth/providers')
    providers = json.loads(body)
    if providers.get('development_email_login') is not False or providers.get('password_login') is not True:
        raise SystemExit('Production authentication provider flags are incorrect.')
    expect('/api/v1/auth/email-login', 404, {'email': 'bharat@latentsig.com'})
    status, _, _ = request('/api/v1/admin/dashboard')
    if status not in (401, 403):
        raise SystemExit('Unauthenticated dashboard access was not rejected.')
    if args.public_only:
        print('Public HTTPS and authentication boundary checks passed.')
        return
    if args.credentials.stat().st_mode & 0o077:
        raise SystemExit('Credential file must have mode 0600 or stricter.')
    credentials = json.loads(args.credentials.read_text())
    if not credentials:
        raise SystemExit('No bootstrap credentials available. Supply a private credential file for an existing account.')
    email, password = next(iter(credentials.items()))
    body, headers = expect('/api/v1/auth/password-login', payload={'email': email, 'password': password})
    if json.loads(body).get('role') != 'ADMIN':
        raise SystemExit('Initial account does not have the ADMIN role.')
    session = headers.get('Set-Cookie', '').lower()
    if 'httponly' not in session or 'secure' not in session:
        raise SystemExit('Session cookie lacks production security attributes.')
    if local:
        # The production cookie stays Secure. Only the explicit loopback probe sends it manually.
        local_cookie = headers['Set-Cookie'].split(';', 1)[0]
    expect('/api/v1/auth/me')
    body, _ = expect('/api/v1/admin/dashboard')
    if not isinstance(json.loads(body).get('total_leads'), int):
        raise SystemExit('Dashboard response did not contain a lead count.')
    expect('/api/v1/admin/leads?page_size=1')
    if args.synthetic:
        suffix = uuid.uuid4().hex
        phone = f'+120255501{secrets.randbelow(100):02d}'
        existing, _ = expect('/api/v1/admin/leads?' + urllib.parse.urlencode({'search': phone}))
        if json.loads(existing).get('total'):
            raise SystemExit('Synthetic reserved phone already exists; rerun to select another.')
        payload = {'full_name': 'Deployment Smoke Test', 'company': 'Synthetic verification',
                   'job_title': 'Test', 'email': f'smoke-{suffix}@example.com', 'phone': phone,
                   'interest': ['Automation'], 'intent': 'Just connecting',
                   'data_processing_consent': True, 'follow_up_consent': False,
                   'source': 'deployment-smoke'}
        headers = {'Idempotency-Key': str(uuid.uuid4())}
        body, _ = expect('/api/v1/leads', 201, payload, extra_headers=headers)
        created = json.loads(body)
        if created.get('created') is not True:
            raise SystemExit('Synthetic request matched an existing lead. Refusing to delete it.')
        lead_id = created['id']
        try:
            body, _ = expect('/api/v1/leads', 201, payload, extra_headers=headers)
            if json.loads(body) != created:
                raise SystemExit('Lead retry was not idempotent.')
            expect(f'/api/v1/admin/leads/{lead_id}')
        finally:
            expect(f'/api/v1/admin/leads/{lead_id}', 204, method='DELETE')
        expect(f'/api/v1/admin/leads/{lead_id}', 404)
    expect('/api/v1/auth/logout', payload={})
    scope = 'VM loopback' if local else 'Public HTTPS'
    print(f'{scope}, production authentication, admin session, and dashboard checks passed.')


if __name__ == '__main__':
    main()
