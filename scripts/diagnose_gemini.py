"""Safely diagnose local Gemini DNS/TLS and optionally make a live request."""

import argparse
import importlib.metadata
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import django
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
load_dotenv(PROJECT_ROOT / '.env', override=False)
django.setup()

from apps.core import gemini


HOST = 'generativelanguage.googleapis.com'


def check_dns():
    started = time.monotonic()
    try:
        addresses = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        print(f'DNS failed: {type(exc).__name__} ({time.monotonic() - started:.2f}s)')
        return False
    print(f'DNS resolved {len(addresses)} address(es) in {time.monotonic() - started:.2f}s')
    return True


def check_tls():
    started = time.monotonic()
    request = urllib.request.Request(f'https://{HOST}/', method='GET')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:
        print(f'HTTPS/TLS failed: {type(exc).__name__} ({time.monotonic() - started:.2f}s)')
        return False
    print(f'HTTPS/TLS established (HTTP {status}) in {time.monotonic() - started:.2f}s')
    return True


def check_live_generation():
    started = time.monotonic()
    try:
        status = gemini.connection_status(force=True)
        if status['state'] != 'connected':
            print(f"Gemini status: {status['state']} ({time.monotonic() - started:.2f}s)")
            print(status['message'])
            return False
        client = gemini.get_client()
        response = gemini._generate_with_retries(
            client,
            'Reply with the word OK.',
            gemini.types.GenerateContentConfig(temperature=0),
        )
    except Exception as exc:
        print(f'Gemini request failed: {type(exc).__name__} ({time.monotonic() - started:.2f}s)')
        return False
    if not response.text:
        print(f'Gemini returned no text ({time.monotonic() - started:.2f}s)')
        return False
    print(f'Gemini generated a text response in {time.monotonic() - started:.2f}s')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--live-generation',
        action='store_true',
        help='Send a minimal authenticated prompt to the configured Gemini model.',
    )
    args = parser.parse_args()

    print(f'Python: {sys.version.split()[0]}')
    print(f'OpenSSL: {ssl.OPENSSL_VERSION}')
    try:
        print(f'google-genai: {importlib.metadata.version("google-genai")}')
    except importlib.metadata.PackageNotFoundError:
        print('google-genai: not installed')
        return 1
    print(f'Model: {gemini.model_name()}')
    print(f'API key configured: {gemini.api_key_configured()}')
    print(f'Request timeout: {gemini.request_timeout_seconds()} seconds')
    print(f'Connect timeout: {gemini.connect_timeout_seconds()} seconds')
    print(f'Retries: {gemini.max_retries()}')

    dns_ok = check_dns()
    tls_ok = check_tls() if dns_ok else False
    if not dns_ok or not tls_ok:
        return 1
    if args.live_generation:
        if not gemini.api_key_configured():
            print('Live generation skipped: GEMINI_API_KEY is not configured.')
            return 1
        return 0 if check_live_generation() else 1
    print('Live generation not run. Pass --live-generation to verify the API key and model.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
