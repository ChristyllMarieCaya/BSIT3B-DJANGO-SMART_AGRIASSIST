"""
PythonAnywhere WSGI configuration template for SMART AGRIASSIST.
"""

import os
import sys

# ---------------------------------------------------------------------------
# EDIT THESE VALUES
# ---------------------------------------------------------------------------
PROJECT_HOME = '/home/CayaMae12/smart-agriassist'
SITE_HOST = 'cayamae12.pythonanywhere.com'

# ---------------------------------------------------------------------------
# Do not edit below this line
# ---------------------------------------------------------------------------
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

os.environ['DJANGO_SETTINGS_MODULE'] = 'mysite.settings'
os.environ['DJANGO_DEBUG'] = 'False'
os.environ['DJANGO_ALLOWED_HOSTS'] = SITE_HOST
os.environ['DJANGO_CSRF_TRUSTED_ORIGINS'] = f'https://{SITE_HOST}'
os.environ['SITE_URL'] = f'https://{SITE_HOST}'

# PythonAnywhere terminates TLS at its proxy; keep Django's HTTPS behaviour on.
os.environ.setdefault('DJANGO_SECURE_SSL_REDIRECT', 'True')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
