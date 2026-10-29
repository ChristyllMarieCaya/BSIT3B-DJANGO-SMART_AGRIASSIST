"""Management command to create or reset the administrator account."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = 'Create or reset the default administrator account for Smart AgriAssist'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='admin', help='Admin username')
        parser.add_argument('--email', default='admin@smartagri.local', help='Admin email address')
        parser.add_argument('--password', default='SmartFarm@Admin2026', help='Admin password')

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']

        user, created = User.objects.get_or_create(username=username, defaults={'email': email})
        user.email = email
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()

        action = 'Created new' if created else 'Updated existing'
        self.stdout.write(self.style.SUCCESS(f'Successfully {action.lower()} admin account:'))
        self.stdout.write(f'  Username : {username}')
        self.stdout.write(f'  Email    : {email}')
        self.stdout.write(f'  Password : {password}')
        self.stdout.write(f'  Staff/Superuser : True')

