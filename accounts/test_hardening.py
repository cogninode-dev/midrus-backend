"""Regression tests for the production-hardening pass."""
import io
import tempfile
from datetime import timedelta
from pathlib import Path
from smtplib import SMTPException
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .emails import send_invoice_email
from .files import make_file_url
from .models import EmailOTP, Invoice, InvoiceItem, Service, ServiceDocument, User
from .pdf import _render_html

API = '/api/auth'
LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'
PDF = b'%PDF-1.4\n%fake\n'


def latest_otp(user):
    return EmailOTP.objects.filter(user=user).order_by('-created_at').first().otp


def wrong_code(real):
    return '000000' if real != '000000' else '111111'


@override_settings(EMAIL_BACKEND=LOCMEM)
class HardeningBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'client@example.com', 'Pw-client-123', 'Client One',
            is_email_verified=True, is_approved=True,
        )
        self.other = User.objects.create_user(
            'other@example.com', 'Pw-other-123', 'Other Person',
            is_email_verified=True,
        )
        self.service = Service.objects.create(user=self.user, name='GST', status='Active')


# ─── Rate limiting ───────────────────────────────────────────────────────────

class ThrottleTests(HardeningBase):
    def _login(self, ip):
        return self.client.post(
            f'{API}/login/', {'email': 'nobody@example.com', 'password': 'x'},
            format='json', HTTP_X_FORWARDED_FOR=ip,
        )

    def test_login_limit_is_per_client_ip_not_per_proxy(self):
        for _ in range(10):
            self.assertEqual(self._login('1.1.1.1').status_code, 401)
        self.assertEqual(self._login('1.1.1.1').status_code, 429)
        # A different real client behind the same proxy is unaffected. Before
        # the NUM_PROXIES fix, this returned 429 for the whole site.
        self.assertEqual(self._login('2.2.2.2').status_code, 401)

    def test_contact_form_is_throttled_and_capped(self):
        body = {'name': 'A', 'email': 'a@b.com', 'phone': '999', 'message': 'hi'}
        for _ in range(10):
            self.assertEqual(
                self.client.post(f'{API}/contact/', body, format='json', HTTP_X_FORWARDED_FOR='9.9.9.9').status_code,
                201,
            )
        self.assertEqual(
            self.client.post(f'{API}/contact/', body, format='json', HTTP_X_FORWARDED_FOR='9.9.9.9').status_code,
            429,
        )
        huge = {**body, 'message': 'x' * 5001}
        self.assertEqual(
            self.client.post(f'{API}/contact/', huge, format='json', HTTP_X_FORWARDED_FOR='8.8.8.8').status_code,
            400,
        )


# ─── Accounts & OTP ──────────────────────────────────────────────────────────

class AuthTests(HardeningBase):
    def _register(self, **over):
        body = {'email': 'New@Example.COM', 'password': 'Pw-new-123', 'name': 'New Person', **over}
        return self.client.post(f'{API}/register/', body, format='json')

    def test_email_is_stored_lowercase_and_duplicates_blocked_case_insensitively(self):
        self.assertEqual(self._register().status_code, 201)
        self.assertTrue(User.objects.filter(email='new@example.com').exists())
        self.assertEqual(self._register(email='NEW@example.com').status_code, 400)

    def test_legacy_mixed_case_account_can_still_log_in_and_reset(self):
        legacy = User.objects.create_user(
            'Legacy@Example.com', 'Pw-legacy-123', 'Legacy', is_email_verified=True,
        )
        r = self.client.post(
            f'{API}/login/', {'email': 'legacy@example.com', 'password': 'Pw-legacy-123'}, format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['otp_required'])
        mail.outbox.clear()
        self.client.post(f'{API}/password-reset/', {'email': 'LEGACY@EXAMPLE.COM'}, format='json')
        self.assertEqual(len(mail.outbox), 1, 'reset for a mixed-case account must send the code')
        self.assertIsNotNone(latest_otp(legacy))

    def test_duplicate_case_variants_do_not_crash_login(self):
        User.objects.create_user('Dup@example.com', 'Pw-dup-one-1', 'Dup A', is_email_verified=True)
        User.objects.create_user('dup@example.com', 'Pw-dup-two-2', 'Dup B', is_email_verified=True)
        r = self.client.post(
            f'{API}/login/', {'email': 'DUP@example.com', 'password': 'Pw-dup-one-1'}, format='json',
        )
        self.assertIn(r.status_code, (200, 401))  # never a 500

    def test_names_are_collapsed_to_one_line(self):
        self._register(name='Evil\nBcc: x@y.com\r\nName')
        self.assertEqual(User.objects.get(email='new@example.com').name, 'Evil Bcc: x@y.com Name')

    def test_login_otp_locks_after_repeated_wrong_guesses(self):
        creds = {'email': 'client@example.com', 'password': 'Pw-client-123'}
        self.assertEqual(self.client.post(f'{API}/login/', creds, format='json').status_code, 200)
        real = latest_otp(self.user)
        bad = {'email': 'client@example.com', 'otp': wrong_code(real)}
        for _ in range(5):
            r = self.client.post(f'{API}/verify-login-otp/', bad, format='json')
            self.assertEqual(r.status_code, 401)
        # Even the correct code is now refused...
        r = self.client.post(f'{API}/verify-login-otp/', {**bad, 'otp': real}, format='json')
        self.assertEqual(r.status_code, 401)
        self.assertIn('Too many', str(r.data))
        # ...until a fresh code is requested.
        self.client.post(f'{API}/login/', creds, format='json')
        r = self.client.post(
            f'{API}/verify-login-otp/', {'email': 'client@example.com', 'otp': latest_otp(self.user)}, format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn('tokens', r.data)

    def test_otp_cannot_be_reused(self):
        self.client.post(f'{API}/login/', {'email': 'client@example.com', 'password': 'Pw-client-123'}, format='json')
        code = latest_otp(self.user)
        body = {'email': 'client@example.com', 'otp': code}
        self.assertEqual(self.client.post(f'{API}/verify-login-otp/', body, format='json').status_code, 200)
        self.assertEqual(self.client.post(f'{API}/verify-login-otp/', body, format='json').status_code, 401)

    def test_expired_otp_is_rejected(self):
        self.client.post(f'{API}/login/', {'email': 'client@example.com', 'password': 'Pw-client-123'}, format='json')
        EmailOTP.objects.filter(user=self.user).update(created_at=timezone.now() - timedelta(minutes=11))
        r = self.client.post(
            f'{API}/verify-login-otp/', {'email': 'client@example.com', 'otp': latest_otp(self.user)}, format='json',
        )
        self.assertEqual(r.status_code, 401)
        self.assertIn('expired', str(r.data).lower())

    def test_resend_otp_does_not_reveal_whether_an_account_exists(self):
        unverified = User.objects.create_user('half@example.com', 'Pw-half-123', 'Half')
        real = self.client.post(f'{API}/resend-otp/', {'email': 'half@example.com'}, format='json')
        fake = self.client.post(f'{API}/resend-otp/', {'email': 'ghost@example.com'}, format='json')
        self.assertEqual(real.status_code, fake.status_code)
        self.assertEqual(set(real.data), set(fake.data))
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(EmailOTP.objects.filter(user=unverified).exists())

    def test_password_reset_confirm_does_not_reveal_accounts(self):
        r = self.client.post(
            f'{API}/password-reset/confirm/',
            {'email': 'ghost@example.com', 'otp': '123456', 'new_password': 'Newpass-123'}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('No account', str(r.data))

    def test_password_reset_signs_out_every_existing_session(self):
        stolen = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.client.post(f'{API}/token/refresh/', {'refresh': stolen}, format='json').status_code, 200)
        stolen = str(RefreshToken.for_user(self.user))  # fresh, unused
        self.client.post(f'{API}/password-reset/', {'email': 'client@example.com'}, format='json')
        r = self.client.post(
            f'{API}/password-reset/confirm/',
            {'email': 'client@example.com', 'otp': latest_otp(self.user), 'new_password': 'Brand-new-pw-9'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.post(f'{API}/token/refresh/', {'refresh': stolen}, format='json').status_code, 401)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-new-pw-9'))

    def test_logout_requires_the_callers_own_refresh_token(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(f'{API}/logout/', {}, format='json').status_code, 400)
        others = str(RefreshToken.for_user(self.other))
        self.assertEqual(self.client.post(f'{API}/logout/', {'refresh': others}, format='json').status_code, 400)
        mine = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.client.post(f'{API}/logout/', {'refresh': mine}, format='json').status_code, 200)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'{API}/token/refresh/', {'refresh': mine}, format='json').status_code, 401)

    def test_admin_user_lookup_survives_junk_ids(self):
        staff = User.objects.create_user('s@example.com', 'Pw-staff-123', 'Staff', is_staff=True, is_email_verified=True)
        self.client.force_authenticate(staff)
        for junk in ('abc', '1;drop', '9' * 40, ''):
            r = self.client.get(f'{API}/admin/user-lookup/', {'id': junk})
            self.assertEqual(r.status_code, 200, junk)
            self.assertFalse(r.data['found'])
        found = self.client.get(f'{API}/admin/user-lookup/', {'email': 'CLIENT@example.com'})
        self.assertTrue(found.data['found'])


# ─── Files ───────────────────────────────────────────────────────────────────

class FileTests(HardeningBase):
    def setUp(self):
        super().setUp()
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)

        # Streamed downloads keep the file open until the response is closed,
        # and Windows cannot delete an open file when the temp dir is removed.
        original_get = self.client.get

        def get(*args, **kwargs):
            response = original_get(*args, **kwargs)
            self.addCleanup(response.close)
            return response

        self.client.get = get

    def _doc(self, name='sales.pdf', content=PDF):
        doc = ServiceDocument(service=self.service, file_name=name)
        doc.file.save(name, ContentFile(content), save=True)
        return doc

    def _upload(self, name='a.pdf', content=PDF, ctype='application/pdf'):
        self.client.force_authenticate(self.user)
        return self.client.post(
            f'{API}/services/{self.service.pk}/invoices/',
            {'file': SimpleUploadedFile(name, content, content_type=ctype)},
            format='multipart',
        )

    def test_signed_link_serves_the_file_with_safe_headers(self):
        doc = self._doc()
        r = self.client.get(make_file_url(None, 'doc', doc.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('inline', r['Content-Disposition'])
        self.assertEqual(b''.join(r.streaming_content), PDF)

    def test_tampered_expired_or_unknown_links_are_404(self):
        doc = self._doc()
        url = make_file_url(None, 'doc', doc.pk)
        self.assertEqual(self.client.get(url[:-3] + 'abc/').status_code, 404)
        self.assertEqual(self.client.get(f'{API}/files/garbage/').status_code, 404)
        with override_settings(FILE_URL_TTL_SECONDS=-1):
            self.assertEqual(self.client.get(url).status_code, 404)
        gone = make_file_url(None, 'doc', doc.pk + 999)
        self.assertEqual(self.client.get(gone).status_code, 404)

    def test_hostile_content_is_forced_to_download_not_rendered(self):
        doc = self._doc('evil.html', b'<script>alert(document.cookie)</script>')
        r = self.client.get(make_file_url(None, 'doc', doc.pk))
        self.assertEqual(r['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment', r['Content-Disposition'])
        svg = self._doc('evil.svg', b'<svg onload=alert(1)/>')
        r = self.client.get(make_file_url(None, 'doc', svg.pk))
        self.assertIn('attachment', r['Content-Disposition'])

    def test_images_are_served_under_a_sandbox_policy(self):
        png = self._doc('pic.png', b'\x89PNG\r\n\x1a\n....')
        r = self.client.get(make_file_url(None, 'doc', png.pk))
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertIn('sandbox', r['Content-Security-Policy'])

    def test_api_responses_carry_signed_urls_never_media_paths(self):
        self._doc()
        self.client.force_authenticate(self.user)
        url = self.client.get(f'{API}/services/').data[0]['invoices'][0]['file_url']
        self.assertIn('/api/auth/files/', url)
        self.assertNotIn('/media/', url)
        staff = User.objects.create_user('s@example.com', 'Pw-staff-123', 'Staff', is_staff=True, is_email_verified=True)
        self.client.force_authenticate(staff)
        admin_url = self.client.get(f'{API}/admin/documents/').data['results'][0]['file_url']
        self.assertIn('/api/auth/files/', admin_url)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(admin_url).status_code, 200)

    def test_invoice_pdf_link(self):
        inv = Invoice.objects.create(user=self.user)
        inv.uploaded_pdf.save('inv.pdf', ContentFile(PDF), save=True)
        r = self.client.get(make_file_url(None, 'invoice', inv.pk))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    # uploads
    def test_valid_pdf_upload_is_accepted(self):
        r = self._upload()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn('/api/auth/files/', r.data['file_url'])

    def test_upload_rejects_disallowed_extensions_and_spoofed_content(self):
        cases = [
            ('shell.exe', b'MZ\x90\x00', 'application/pdf'),          # bad extension
            ('page.html', b'<html>', 'text/html'),                     # bad extension + type
            ('fake.pdf', b'<html><script>x</script></html>', 'application/pdf'),  # wrong magic bytes
            ('pic.png', PDF, 'image/png'),                             # PDF pretending to be PNG
            ('a.pdf', PDF, 'image/png'),                               # type disagrees with extension
        ]
        for name, content, ctype in cases:
            r = self._upload(name, content, ctype)
            self.assertEqual(r.status_code, 400, name)
        self.assertEqual(ServiceDocument.objects.count(), 0)

    def test_upload_size_limit(self):
        with mock.patch('accounts.files.MAX_UPLOAD_BYTES', 10):
            self.assertEqual(self._upload().status_code, 400)

    def test_upload_filename_is_sanitised(self):
        r = self._upload('..\\..\\etc\\passwd.pdf')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['file_name'], 'passwd.pdf')

    def test_reupload_flag_accepts_json_booleans_without_crashing(self):
        self.client.force_authenticate(self.user)
        r = self.client.post(
            f'{API}/services/{self.service.pk}/invoices/',
            {'file_name': 'note.pdf', 'is_reupload': True}, format='json',
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['is_reupload'])

    def test_deleting_a_document_removes_the_file_from_disk(self):
        doc = self._doc()
        path = Path(doc.file.path)
        self.assertTrue(path.exists())
        with self.captureOnCommitCallbacks(execute=True):
            doc.delete()
        self.assertFalse(path.exists())


# ─── Invoices ────────────────────────────────────────────────────────────────

class InvoiceTests(HardeningBase):
    def test_numbers_are_not_reissued_after_a_delete(self):
        a, b, c = (Invoice.objects.create(user=self.user) for _ in range(3))
        self.assertTrue(a.invoice_number.endswith('/0001'))
        self.assertTrue(c.invoice_number.endswith('/0003'))
        b.delete()
        d = Invoice.objects.create(user=self.user)  # used to collide with #3 and crash
        self.assertTrue(d.invoice_number.endswith('/0004'), d.invoice_number)

    def test_numbering_retries_on_a_concurrent_collision(self):
        first = Invoice.objects.create(user=self.user)
        prefix = first.invoice_number.rsplit('/', 1)[0]
        with mock.patch.object(
            Invoice, '_next_invoice_number', side_effect=[first.invoice_number, f'{prefix}/0009'],
        ):
            second = Invoice.objects.create(user=self.user)
        self.assertEqual(second.invoice_number, f'{prefix}/0009')

    def _hostile_invoice(self):
        evil = '<img src="http://169.254.169.254/latest/meta-data/"><script>x</script>'
        user = User.objects.create_user(
            'evil@example.com', 'Pw-evil-123', evil, company=evil, address=evil,
            gst_number=evil, is_email_verified=True,
        )
        inv = Invoice.objects.create(user=user, notes=evil, ship_to='', bill_to='')
        InvoiceItem.objects.create(
            invoice=inv, service_name=evil, month=9, year=2026, amount=100, hsn_code=evil, per=evil,
        )
        inv.recalculate()
        inv.save()
        return inv

    def test_pdf_html_escapes_user_supplied_text(self):
        html = _render_html(self._hostile_invoice())
        self.assertNotIn('<img src="http://169.254', html)
        self.assertNotIn('<script>x', html)
        self.assertIn('&lt;img src=', html)

    def test_invoice_email_escapes_user_supplied_text(self):
        inv = self._hostile_invoice()
        send_invoice_email(inv, PDF)
        html = mail.outbox[-1].alternatives[0][0]
        self.assertNotIn('<img src="http://169.254', html)
        self.assertNotIn('<script>x', html)
        self.assertIn('&lt;img src=', html)

    def test_invoice_email_failure_is_reported_not_swallowed(self):
        inv = Invoice.objects.create(user=self.user)
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=SMTPException('down')):
            with self.assertRaises(SMTPException):
                send_invoice_email(inv, PDF)

    def test_admin_api_reports_email_failure_honestly(self):
        staff = User.objects.create_user('s@example.com', 'Pw-staff-123', 'Staff', is_staff=True, is_email_verified=True)
        self.client.force_authenticate(staff)
        body = {
            'user_id': self.user.pk, 'gst_rate': 18,
            'items': [{'service_name': 'GST', 'month': 9, 'year': 2026, 'amount': '100'}],
        }
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=SMTPException('down')):
            r = self.client.post(f'{API}/admin/invoices/', body, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.data['email_sent'])  # used to always say True
        self.assertEqual(Invoice.objects.count(), 1)


# ─── Operations ──────────────────────────────────────────────────────────────

class OperationsTests(HardeningBase):
    def test_health_check(self):
        r = self.client.get('/healthz/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'status': 'ok'})

    def test_purge_expired_removes_old_otps_only(self):
        old = EmailOTP.objects.create(user=self.user, otp='111111')
        fresh = EmailOTP.objects.create(user=self.user, otp='222222')
        EmailOTP.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        out = io.StringIO()
        call_command('purge_expired', stdout=out)
        self.assertFalse(EmailOTP.objects.filter(pk=old.pk).exists())
        self.assertTrue(EmailOTP.objects.filter(pk=fresh.pk).exists())

    def test_static_files_use_the_django_6_storages_setting(self):
        from django.conf import settings
        self.assertIn('CompressedStaticFilesStorage', settings.STORAGES['staticfiles']['BACKEND'])
