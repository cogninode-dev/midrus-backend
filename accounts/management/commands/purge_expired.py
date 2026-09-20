"""Delete expired one-time codes and JWT bookkeeping rows.

Run daily (cron / systemd timer / scheduler):

    python manage.py purge_expired
"""
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import EmailOTP


class Command(BaseCommand):
    help = 'Remove old OTP rows and expired JWT outstanding/blacklisted tokens.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=1)
        deleted, _ = EmailOTP.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(f'Deleted {deleted} expired OTP row(s).')
        call_command('flushexpiredtokens')
        self.stdout.write(self.style.SUCCESS('Expired tokens flushed.'))
