"""The web admin panel asks for an emailed code after the password."""
import re
import time

from django.core import mail
from django.test import Client, TestCase, override_settings

from .admin_site import PENDING_KEY
from .models import EmailOTP, User

LOGIN = '/admin/login/'
EMAIL = 'admin@example.com'
PASSWORD = 'pw-admin-123'


def _last_code():
    match = re.search(r'OTP is: (\d{6})', mail.outbox[-1].body)
    return match.group(1)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    ADMIN_REQUIRE_OTP=True,
)
class AdminOtpLoginTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            EMAIL, PASSWORD, 'Admin', is_email_verified=True,
        )
        self.customer = User.objects.create_user(
            'client@example.com', 'pw-client-123', 'Client', is_email_verified=True,
        )
        self.http = Client()

    def _password_step(self, email=EMAIL, password=PASSWORD, **extra):
        return self.http.post(
            LOGIN, {'username': email, 'password': password, 'next': '/admin/', **extra},
        )

    def _is_logged_in(self):
        return '_auth_user_id' in self.http.session

    # ── password step ────────────────────────────────────────────────────────

    def test_correct_password_alone_does_not_log_in(self):
        r = self._password_step()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Enter the 6-digit code')
        self.assertFalse(self._is_logged_in())
        self.assertEqual(self.http.get('/admin/').status_code, 302)  # still bounced to login

    def test_code_is_emailed_to_the_admin(self):
        self._password_step()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [EMAIL])

    def test_wrong_password_sends_no_code(self):
        r = self._password_step(password='nope')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self._is_logged_in())
        self.assertEqual(len(mail.outbox), 0)

    def test_customers_cannot_start_an_admin_login(self):
        r = self._password_step(email='client@example.com', password='pw-client-123')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Enter the 6-digit code')
        self.assertFalse(self._is_logged_in())
        self.assertEqual(len(mail.outbox), 0)

    # ── code step ────────────────────────────────────────────────────────────

    def test_correct_code_logs_in_and_redirects(self):
        self._password_step()
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': _last_code(), 'next': '/admin/'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], '/admin/')
        self.assertTrue(self._is_logged_in())
        self.assertEqual(self.http.get('/admin/').status_code, 200)

    def test_wrong_code_is_rejected(self):
        self._password_step()
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': '000000'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Invalid OTP')
        self.assertFalse(self._is_logged_in())

    def test_code_cannot_be_reused(self):
        self._password_step()
        code = _last_code()
        self.http.post(LOGIN, {'step': 'otp', 'otp': code})
        other = Client()
        other.post(LOGIN, {'username': EMAIL, 'password': PASSWORD})
        r = other.post(LOGIN, {'step': 'otp', 'otp': code})
        self.assertNotIn('_auth_user_id', other.session)
        self.assertEqual(r.status_code, 200)

    def test_locks_after_too_many_wrong_codes(self):
        self._password_step()
        for _ in range(5):
            self.http.post(LOGIN, {'step': 'otp', 'otp': '000000'})
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': _last_code()})
        self.assertContains(r, 'Too many incorrect attempts')
        self.assertFalse(self._is_logged_in())

    def test_code_step_without_a_password_step_does_nothing(self):
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': '123456'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self._is_logged_in())

    def test_someone_elses_valid_code_does_not_help(self):
        # A live code for the customer must not log an admin-pending session in.
        self._password_step()
        EmailOTP.objects.create(user=self.customer, otp='654321')
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': '654321'})
        self.assertContains(r, 'Invalid OTP')
        self.assertFalse(self._is_logged_in())

    def test_pending_login_expires(self):
        self._password_step()
        session = self.http.session
        session[PENDING_KEY]['at'] = time.time() - 3600
        session.save()
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': _last_code()})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self._is_logged_in())

    def test_open_redirect_is_ignored(self):
        self._password_step()
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': _last_code(), 'next': 'https://evil.example/'})
        self.assertEqual(r['Location'], '/admin/')

    # ── resend / back ────────────────────────────────────────────────────────

    def test_resend_is_rate_limited_then_works(self):
        self._password_step()
        r = self.http.post(LOGIN, {'step': 'resend'})
        self.assertContains(r, 'Please wait')
        self.assertEqual(len(mail.outbox), 1)

        session = self.http.session
        session[PENDING_KEY]['sent'] = time.time() - 60
        session.save()
        r = self.http.post(LOGIN, {'step': 'resend'})
        self.assertContains(r, 'new code is on its way')
        self.assertEqual(len(mail.outbox), 2)
        r = self.http.post(LOGIN, {'step': 'otp', 'otp': _last_code()})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self._is_logged_in())

    def test_back_clears_the_pending_login(self):
        self._password_step()
        self.http.post(LOGIN, {'step': 'back'})
        self.assertNotIn(PENDING_KEY, self.http.session)

    # ── switch ───────────────────────────────────────────────────────────────

    @override_settings(ADMIN_REQUIRE_OTP=False)
    def test_can_be_turned_off_for_development(self):
        r = self._password_step()
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self._is_logged_in())
        self.assertEqual(len(mail.outbox), 0)

    def test_email_failure_does_not_log_in(self):
        from unittest import mock
        with mock.patch('accounts.emails.send_login_otp_email', side_effect=OSError('smtp down')):
            r = self._password_step()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'could not email')
        self.assertFalse(self._is_logged_in())
