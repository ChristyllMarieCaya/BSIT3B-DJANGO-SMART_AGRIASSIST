"""Standalone script to create or update the Smart AgriAssist administrator account."""

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

ADMIN_USERNAME = os.environ.get('AGRI_ADMIN_USER', 'admin')
ADMIN_EMAIL = os.environ.get('AGRI_ADMIN_EMAIL', 'admin@smartagri.local')
ADMIN_PASSWORD = os.environ.get('AGRI_ADMIN_PASSWORD', 'SmartFarm@Admin2026')


def create_or_update_admin():
    user, created = User.objects.get_or_create(username=ADMIN_USERNAME, defaults={'email': ADMIN_EMAIL})
    user.email = ADMIN_EMAIL
    user.set_password(ADMIN_PASSWORD)
    user.is_staff = True
    user.is_superuser = True
    user.save()

    status = 'Created new' if created else 'Updated existing'
    print(f'[SUCCESS] {status} Administrator Account:')
    print(f'  Username : {ADMIN_USERNAME}')
    print(f'  Email    : {ADMIN_EMAIL}')
    print(f'  Password : {ADMIN_PASSWORD}')
    print(f'  Role     : Staff & Superuser (Full Admin Access)')
    return user


if __name__ == '__main__':
    create_or_update_admin()

