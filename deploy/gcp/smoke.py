#!/usr/bin/env python3
"""Check production access and an admin session, with optional synthetic lead cleanup."""
import argparse
import http.cookiejar
import json
import mimetypes
from pathlib import Path
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid


def multipart_form(fields, file_field, filename, mime_type, file_data, boundary=None):
    boundary = boundary or f'LatentSigConnect-{uuid.uuid4().hex}'
    safe_filename = Path(filename).name.replace('"', '').replace('\r', '').replace('\n', '')
    parts = []
    for name, value in fields.items():
        parts.extend([
            f'--{boundary}\r\n'.encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode(),
            b'\r\n',
        ])
    parts.extend([
        f'--{boundary}\r\n'.encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_filename}"\r\n'.encode(),
        f'Content-Type: {mime_type}\r\n\r\n'.encode(),
        file_data,
        b'\r\n',
        f'--{boundary}--\r\n'.encode(),
    ])
    return f'multipart/form-data; boundary={boundary}', b''.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin')
    parser.add_argument('--credentials', type=Path,
                        default=Path('/srv/latentsig-connect/secrets/admin-passwords.json'))
    parser.add_argument('--public-only', action='store_true')
    parser.add_argument('--local', action='store_true', help='Allow only the VM loopback frontend before DNS is ready')
    parser.add_argument('--expected-public-origin', help='Verify the frontend JS contains its configured HTTPS QR origin')
    parser.add_argument('--synthetic', action='store_true', help='Create, retry, read, and delete one synthetic lead')
    parser.add_argument('--synthetic-card', type=Path, help='Upload, verify, search, and clean up a synthetic card capture')
    args = parser.parse_args()
    if args.public_only and (args.synthetic or args.synthetic_card):
        raise SystemExit('Public-only smoke cannot run authenticated synthetic checks.')
    origin = args.origin.rstrip('/')
    parsed = urllib.parse.urlsplit(origin)
    local = args.local and origin == 'http://127.0.0.1:8080'
    if (parsed.scheme != 'https' and not local) or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit('Provide an HTTPS origin without a path or credentials.')
    cookies = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    local_cookie = None

    def request(path, payload=None, method=None, extra_headers=None):
        if payload is None:
            data = None
        elif isinstance(payload, bytes):
            data = payload
        else:
            data = json.dumps(payload).encode()
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
    if args.synthetic_card:
        if not args.synthetic_card.is_file():
            raise SystemExit('Synthetic business-card image does not exist.')
        card_data = args.synthetic_card.read_bytes()
        if not card_data or len(card_data) > 10 * 1024 * 1024:
            raise SystemExit('Synthetic business-card image must be non-empty and no larger than 10 MB.')
        mime_type = mimetypes.guess_type(args.synthetic_card.name)[0]
        if mime_type not in {'image/jpeg', 'image/png', 'image/webp'}:
            raise SystemExit('Synthetic business-card image must be JPG, PNG, or WEBP.')

        policy_body, _ = expect('/api/v1/admin/card-capture-policy')
        policy = json.loads(policy_body)
        if not policy.get('ocr_enabled'):
            raise SystemExit('Business-card OCR is disabled; no synthetic image was uploaded.')
        if policy.get('external_ai_requires_consent') and not policy.get('staff_card_processing_rules_approved'):
            raise SystemExit('External card-processing rules are not approved; no synthetic image was uploaded.')

        events_body, _ = expect('/api/v1/admin/events')
        events = json.loads(events_body)
        bts = next((event for event in events if event.get('slug') == 'bts-2026' and event.get('is_active')), None)
        if bts is None:
            raise SystemExit('Active BTS 2026 event was not found; no synthetic image was uploaded.')

        extension = mimetypes.guess_extension(mime_type) or '.img'
        filename = f'latentsig-jhon-michai-smoke-{uuid.uuid4().hex}{extension}'
        fields = {
            'event_id': bts['id'],
            'synthetic_test': 'true',
            'external_ai_consent': 'false',
        }
        content_type, form_data = multipart_form(fields, 'file', filename, mime_type, card_data)
        status, body, _ = request(
            '/api/v1/admin/card-captures', form_data, method='POST',
            extra_headers={'Content-Type': content_type},
        )
        if status != 201:
            raise SystemExit(f'Synthetic business-card upload returned {status}; no capture was verified.')
        capture = json.loads(body)
        capture_id = capture['id']
        try:
            ocr = capture.get('ocr') or {}
            if capture.get('status') != 'template_detected' or not ocr.get('is_template'):
                raise SystemExit('Synthetic JHON MICHAI sample was not detected as a card template.')
            if capture.get('event_id') != bts['id']:
                raise SystemExit('Synthetic card capture was not attributed to BTS 2026.')
            if not capture.get('synthetic_test') or not capture.get('exclude_from_analytics'):
                raise SystemExit('Synthetic card capture was not excluded from event analytics.')
            if capture.get('external_ai_consent_recorded'):
                raise SystemExit('Synthetic card capture incorrectly recorded visitor AI consent.')
            if capture.get('lead_id'):
                raise SystemExit('Designed sample unexpectedly created a person lead.')

            detail_body, _ = expect(f'/api/v1/admin/card-captures/{capture_id}')
            detail = json.loads(detail_body)
            if detail.get('status') != 'template_detected' or not (detail.get('ocr') or {}).get('is_template'):
                raise SystemExit('Stored card capture did not preserve its template review state.')
            saved_image, _ = expect(f'/api/v1/admin/card-captures/{capture_id}/image')
            if saved_image != card_data:
                raise SystemExit('Stored synthetic card image did not match the uploaded sample.')
            search_query = urllib.parse.urlencode({
                'search': filename, 'event_id': bts['id'], 'include_synthetic': 'true', 'page_size': 100,
            })
            search_body, _ = expect(f'/api/v1/admin/card-captures?{search_query}')
            results = json.loads(search_body).get('items', [])
            if not any(item.get('id') == capture_id for item in results):
                raise SystemExit('Synthetic card capture was not found in admin search.')
        finally:
            cleanup_status, _, _ = request(f'/api/v1/admin/card-captures/{capture_id}', method='DELETE')
            if cleanup_status != 204:
                raise SystemExit(f'Synthetic card cleanup returned {cleanup_status}.')
            removed_status, _, _ = request(f'/api/v1/admin/card-captures/{capture_id}')
            if removed_status != 404:
                raise SystemExit('Synthetic card capture remained accessible after cleanup.')
        print('Synthetic business-card OCR, template guard, event attribution, admin search, storage, and cleanup passed.')
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
