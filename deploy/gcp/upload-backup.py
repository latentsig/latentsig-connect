#!/usr/bin/env python3
"""Upload a root-only snapshot using the attached VM identity, without key files."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request


def upload(bucket, name, filename):
    path = Path(filename)
    digest = hashlib.md5(usedforsecurity=False)
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    request = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'})
    with urllib.request.urlopen(request, timeout=20) as response:
        token = json.load(response)['access_token']
    query = urllib.parse.urlencode({'uploadType': 'media', 'name': name, 'ifGenerationMatch': '0'})
    url = f'https://storage.googleapis.com/upload/storage/v1/b/{urllib.parse.quote(bucket, safe="")}/o?{query}'
    with path.open('rb') as source:
        request = urllib.request.Request(url, data=source, method='POST', headers={
            'Authorization': f'Bearer {token}', 'Content-Type': 'application/octet-stream',
            'Content-Length': str(path.stat().st_size)})
        with urllib.request.urlopen(request, timeout=1200) as response:
            result = json.load(response)
    if int(result['size']) != path.stat().st_size or result.get('md5Hash') != base64.b64encode(digest.digest()).decode():
        raise SystemExit('GCS upload verification failed.')
    print(f'Verified GCS backup: gs://{bucket}/{name}')


if __name__ == '__main__':
    upload(*sys.argv[1:])
