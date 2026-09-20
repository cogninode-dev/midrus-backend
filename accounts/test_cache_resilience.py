"""A missing/broken cache table must never take logins down."""
from django.core import mail
from django.db import connection
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import EmailOTP, User

API = '/api/auth'

# The exact production failure: the cache table was never created.
BROKEN_CACHE = {
    'default': {
        'BACKEND': 'accounts.cache.ResilientDatabaseCache',
        'LOCATION': 'table_that_was_never_created',
    }
}


@override_settings(CACHES=BROKEN_CACHE, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MissingCacheTableTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'client@example.com', 'Pw-client-123', 'Client', is_email_verified=True,
        )

    def test_the_cache_table_really_is_missing(self):
        self.assertNotIn('table_that_was_never_created', connection.introspection.table_names())

    def test_login_still_works_instead_of_returning_500(self):
        with self.assertLogs('accounts.cache', level='ERROR') as logs:
            r = self.client.post(
                f'{API}/login/', {'email': 'client@example.com', 'password': 'Pw-client-123'}, format='json',
            )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data['otp_required'])
        # ...and the operator is told exactly how to fix it.
        self.assertIn('createcachetable', '\n'.join(logs.output))

    def test_wrong_credentials_are_a_401_not_a_500(self):
        r = self.client.post(f'{API}/login/', {'email': 'client@example.com', 'password': 'nope'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_the_full_otp_login_flow_survives(self):
        self.client.post(f'{API}/login/', {'email': 'client@example.com', 'password': 'Pw-client-123'}, format='json')
        code = EmailOTP.objects.filter(user=self.user).latest('created_at').otp
        r = self.client.post(f'{API}/verify-login-otp/', {'email': 'client@example.com', 'otp': code}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn('tokens', r.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_wrong_otp_is_a_clean_401(self):
        self.client.post(f'{API}/login/', {'email': 'client@example.com', 'password': 'Pw-client-123'}, format='json')
        real = EmailOTP.objects.filter(user=self.user).latest('created_at').otp
        bad = '000000' if real != '000000' else '111111'
        r = self.client.post(f'{API}/verify-login-otp/', {'email': 'client@example.com', 'otp': bad}, format='json')
        self.assertEqual(r.status_code, 401)


class CacheTableMigrationTests(APITestCase):
    def test_migrations_create_the_cache_table(self):
        # The test database is built by running migrations, so the table exists
        # without anyone calling createcachetable by hand.
        self.assertIn('django_cache', connection.introspection.table_names())
