"""Every MIDRUS email carries the logo inside the message itself."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from . import emails
from .models import Invoice, InvoiceItem, User

PNG = b'\x89PNG\r\n\x1a\n'


def parts(message):
    """The MIME parts of a message as (content_type, content_id, disposition)."""
    found = []
    for part in message.walk():
        found.append((
            part.get_content_type(),
            part.get('Content-ID'),
            part.get_content_disposition(),
        ))
    return found


def html_of(message):
    return message.alternatives[0][0]


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailLogoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'asha@example.com', 'Pw-asha-123', 'Asha Rao',
            company='Rao Traders', phone='9876543210', is_email_verified=True,
        )
        self.invoice = Invoice.objects.create(user=self.user, gst_rate=18)
        InvoiceItem.objects.create(
            invoice=self.invoice, service_name='GST Return', month=9, year=2026, amount=1000,
        )
        self.invoice.recalculate()
        self.invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])
        mail.outbox.clear()

    # every kind of email the app sends
    def send_all(self):
        emails.send_otp_email(self.user, '123456')
        emails.send_login_otp_email(self.user, '234567')
        emails.send_password_reset_email(self.user, '345678')
        emails.send_admin_signup_notification(self.user)
        emails.send_invoice_email(self.invoice, b'%PDF-1.4 the invoice')
        emails.send_account_deleted_email('asha@example.com', 'Asha Rao')
        emails.send_approved_email(self.user)

    @override_settings(ADMIN_EMAIL='boss@example.com')
    def test_all_seven_emails_are_sent(self):
        self.send_all()
        self.assertEqual(len(mail.outbox), 7)

    @override_settings(ADMIN_EMAIL='boss@example.com')
    def test_every_email_shows_the_logo_from_inside_the_message(self):
        self.send_all()
        for m in mail.outbox:
            msg = m.message()
            html = html_of(m)
            self.assertIn(f'cid:{emails.LOGO_CID}', html, m.subject)
            self.assertIn('alt="MIDRUS"', html, m.subject)  # readable if images are off
            images = [p for p in parts(msg) if p[0] == 'image/png']
            self.assertEqual(len(images), 1, m.subject)
            self.assertEqual(images[0][1], f'<{emails.LOGO_CID}>', m.subject)
            self.assertEqual(images[0][2], 'inline', m.subject)

    def test_the_embedded_image_is_the_real_logo_png(self):
        emails.send_otp_email(self.user, '123456')
        msg = mail.outbox[0].message()
        (image,) = [p for p in msg.walk() if p.get_content_type() == 'image/png']
        data = image.get_payload(decode=True)
        self.assertTrue(data.startswith(PNG))
        self.assertEqual(data, emails._logo_bytes())
        self.assertLess(len(data), 40_000, 'keep emails light')

    def test_the_logo_is_bundled_with_the_html_as_multipart_related(self):
        """text | (html + logo): the logo belongs to the HTML version only."""
        emails.send_otp_email(self.user, '123456')
        msg = mail.outbox[0].message()
        self.assertEqual(msg.get_content_type(), 'multipart/alternative')
        text, related = msg.get_payload()
        self.assertEqual(text.get_content_type(), 'text/plain')
        self.assertEqual(related.get_content_type(), 'multipart/related')
        self.assertEqual(
            [p.get_content_type() for p in related.get_payload()],
            ['text/html', 'image/png'],
        )

    def test_the_invoice_pdf_is_still_a_real_attachment_outside_the_logo_bundle(self):
        emails.send_invoice_email(self.invoice, b'%PDF-1.4 the invoice')
        msg = mail.outbox[0].message()
        self.assertEqual(msg.get_content_type(), 'multipart/mixed')
        top = [p.get_content_type() for p in msg.get_payload()]
        self.assertEqual(top, ['multipart/alternative', 'application/pdf'])
        pdf = msg.get_payload()[1]
        self.assertEqual(pdf.get_content_disposition(), 'attachment')
        self.assertIn(self.invoice.invoice_number, pdf.get_filename())
        self.assertEqual(pdf.get_payload(decode=True), b'%PDF-1.4 the invoice')
        # The logo is inside the HTML part, and the PDF is not.
        types = [p.get_content_type() for p in msg.walk()]
        self.assertEqual(types.count('image/png'), 1)
        self.assertLess(types.index('multipart/related'), types.index('application/pdf'))
        # ...and the usual accessors still see exactly one attachment.
        self.assertEqual(len(mail.outbox[0].attachments), 1)
        self.assertEqual(mail.outbox[0].attachments[0][2], 'application/pdf')

    def test_an_invoice_email_without_a_pdf_has_no_attachment(self):
        emails.send_invoice_email(self.invoice, None)
        self.assertEqual(mail.outbox[0].attachments, [])
        msg = mail.outbox[0].message()
        self.assertEqual(msg.get_content_type(), 'multipart/alternative')
        self.assertNotIn('application/pdf', [p.get_content_type() for p in msg.walk()])

    def test_a_plain_text_version_is_always_included(self):
        emails.send_otp_email(self.user, '123456')
        emails.send_login_otp_email(self.user, '234567')
        self.assertIn('123456', mail.outbox[0].body)
        self.assertIn('234567', mail.outbox[1].body)

    def test_the_header_keeps_its_brand_text_and_tagline(self):
        emails.send_otp_email(self.user, '123456')
        html = html_of(mail.outbox[0])
        self.assertIn('MIDRUS', html)
        self.assertIn('Accounting, Tax &amp; Compliance', html)
        self.assertNotIn('>M</td>', html)  # the old placeholder lettermark is gone

    def test_content_is_still_escaped(self):
        hostile = User.objects.create_user(
            'x@example.com', 'Pw-x-123456', '<script>alert(1)</script>', is_email_verified=True,
        )
        emails.send_otp_email(hostile, '123456')
        html = html_of(mail.outbox[0])
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_the_subject_and_recipient_are_unchanged(self):
        emails.send_otp_email(self.user, '123456')
        m = mail.outbox[0]
        self.assertEqual(m.subject, 'Verify your MIDRUS account — OTP inside')
        self.assertEqual(m.to, ['asha@example.com'])

    # ── if the logo file is ever missing ────────────────────────────────────

    def test_a_missing_logo_file_never_stops_an_email(self):
        with mock.patch.object(emails, '_logo_bytes', return_value=None):
            self.send_all_safely()
        self.assertEqual(len(mail.outbox), 6)  # admin notice needs ADMIN_EMAIL
        for m in mail.outbox:
            html = html_of(m)
            self.assertNotIn('cid:', html, m.subject)  # no broken image
            self.assertNotIn('image/png', [p[0] for p in parts(m.message())], m.subject)
            self.assertIn('>M</span>', html, m.subject)  # lettermark stands in

    def send_all_safely(self):
        emails.send_otp_email(self.user, '123456')
        emails.send_login_otp_email(self.user, '234567')
        emails.send_password_reset_email(self.user, '345678')
        emails.send_invoice_email(self.invoice, b'%PDF-1.4 x')
        emails.send_account_deleted_email('asha@example.com', 'Asha Rao')
        emails.send_approved_email(self.user)

    def test_the_logo_file_is_shipped_with_the_code(self):
        self.assertTrue(emails._LOGO_PATH.is_file())
        self.assertTrue(emails._LOGO_PATH.read_bytes().startswith(PNG))

    def test_a_preview_data_uri_is_available_for_browsers(self):
        uri = emails.logo_data_uri()
        self.assertTrue(uri.startswith('data:image/png;base64,'))
        with mock.patch.object(emails, '_logo_bytes', return_value=None):
            self.assertIsNone(emails.logo_data_uri())

    def test_failures_still_raise_or_stay_quiet_as_before(self):
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=RuntimeError('smtp down')):
            with self.assertRaises(RuntimeError):
                emails.send_otp_email(self.user, '123456')         # fail_silently=False
        # ...while the notice-style emails never raise (fail_silently=True).
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'):
            emails.send_approved_email(self.user)
