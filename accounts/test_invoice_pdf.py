"""Downloading an invoice as a PDF."""
import tempfile
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.files.base import ContentFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .files import make_file_url
from .models import Invoice, InvoiceItem, User
from .pdf import _render_html

API = '/api/auth'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InvoicePdfTests(APITestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)

        # Streamed files stay open until the response closes; Windows can't
        # delete an open file when the temp dir is removed.
        original_get = self.client.get

        def get(*args, **kwargs):
            response = original_get(*args, **kwargs)
            self.addCleanup(response.close)
            return response

        self.client.get = get

        self.owner = User.objects.create_user(
            'owner@example.com', 'Pw-owner-123', 'Owner Person', company='Owner Co',
            address='1 Main Road', gst_number='07AAAAA0000A1Z5', is_email_verified=True,
        )
        self.stranger = User.objects.create_user(
            'stranger@example.com', 'Pw-stranger-123', 'Stranger', is_email_verified=True,
        )
        self.invoice = Invoice.objects.create(user=self.owner, gst_rate=18)
        InvoiceItem.objects.create(
            invoice=self.invoice, service_name='GST Return Filing', month=9, year=2026, amount=2500,
        )
        self.invoice.recalculate()
        self.invoice.save()

    def _pdf_url(self, user=None):
        self.client.force_authenticate(user or self.owner)
        rows = self.client.get(f'{API}/proforma-invoices/').data
        self.client.force_authenticate(None)
        return rows[0]['pdf_url'] if rows else None

    def _body(self, response):
        return b''.join(response.streaming_content) if response.streaming else response.content

    # ── the link ────────────────────────────────────────────────────────────

    def test_invoice_list_includes_a_signed_pdf_link(self):
        url = self._pdf_url()
        self.assertIn('/api/auth/files/', url)
        self.assertNotIn('/media/', url)

    def test_link_downloads_a_real_generated_pdf(self):
        r = self.client.get(self._pdf_url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        body = self._body(r)
        self.assertTrue(body.startswith(b'%PDF-'), body[:20])
        self.assertGreater(len(body), 1500)

    def test_response_is_a_named_attachment(self):
        r = self.client.get(self._pdf_url())
        disposition = r['Content-Disposition']
        self.assertIn('attachment', disposition)
        # "MAPL/26-27/0001" must not put a slash in the file name.
        expected = self.invoice.invoice_number.replace('/', '-') + '.pdf'
        self.assertIn(expected, disposition)
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('no-store', r['Cache-Control'])

    def test_an_uploaded_pdf_is_preferred_over_generating_one(self):
        self.invoice.uploaded_pdf.save('mine.pdf', ContentFile(b'%PDF-1.4 uploaded-by-admin'), save=True)
        r = self.client.get(self._pdf_url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._body(r), b'%PDF-1.4 uploaded-by-admin')
        self.assertIn('attachment', r['Content-Disposition'])

    def test_missing_uploaded_file_falls_back_to_generating(self):
        self.invoice.uploaded_pdf.save('gone.pdf', ContentFile(b'%PDF-1.4 x'), save=True)
        Path(self.invoice.uploaded_pdf.path).unlink()
        r = self.client.get(self._pdf_url())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._body(r).startswith(b'%PDF-'))
        self.assertNotEqual(self._body(r), b'%PDF-1.4 x')

    def test_generation_failure_is_a_clean_503_not_a_crash(self):
        url = self._pdf_url()
        with mock.patch('accounts.pdf.generate_invoice_pdf', side_effect=RuntimeError('boom')):
            with self.assertLogs('accounts.files', level='ERROR'):
                r = self.client.get(url)
        self.assertEqual(r.status_code, 503)

    # ── access control ──────────────────────────────────────────────────────

    def test_users_only_ever_get_links_for_their_own_invoices(self):
        self.assertIsNone(self._pdf_url(self.stranger))  # stranger has no invoices
        other = Invoice.objects.create(user=self.stranger)
        self.client.force_authenticate(self.stranger)
        ids = [row['id'] for row in self.client.get(f'{API}/proforma-invoices/').data]
        self.assertEqual(ids, [other.pk])

    def test_forged_expired_or_unknown_links_are_404(self):
        url = self._pdf_url()
        self.assertEqual(self.client.get(url[:-3] + 'abc/').status_code, 404)
        with override_settings(FILE_URL_TTL_SECONDS=-1):
            self.assertEqual(self.client.get(url).status_code, 404)
        missing = make_file_url(None, 'invoice-pdf', self.invoice.pk + 999)
        self.assertEqual(self.client.get(missing).status_code, 404)

    # ── admin API ───────────────────────────────────────────────────────────

    def test_admin_invoice_endpoints_expose_the_pdf_link(self):
        staff = User.objects.create_user('s@example.com', 'Pw-staff-123', 'Staff', is_staff=True, is_email_verified=True)
        self.client.force_authenticate(staff)
        listed = self.client.get(f'{API}/admin/invoices/').data['results'][0]
        self.assertIn('/api/auth/files/', listed['pdf_url'])
        created = self.client.post(f'{API}/admin/invoices/', {
            'user_id': self.owner.pk, 'gst_rate': 18,
            'items': [{'service_name': 'TDS', 'month': 9, 'year': 2026, 'amount': '100'}],
        }, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertIn('/api/auth/files/', created.data['pdf_url'])
        self.client.force_authenticate(None)
        r = self.client.get(created.data['pdf_url'])
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self._body(r).startswith(b'%PDF-'))
        self.assertEqual(len(mail.outbox), 1)  # creating still emails the invoice

    # ── template ────────────────────────────────────────────────────────────

    def test_template_avoids_the_rupee_glyph_the_pdf_font_cannot_draw(self):
        # Helvetica has no U+20B9, so a rupee sign prints as a black box.
        html = _render_html(self.invoice)
        self.assertNotIn('&#8377;', html)
        self.assertNotIn('₹', html)
        self.assertIn('INR ', html)

    def test_tax_summary_has_no_spanning_cells_that_misalign_the_columns(self):
        html = _render_html(self.invoice)
        tax = html[html.index('<!-- Tax Summary -->'):html.index('<!-- Declaration')]
        self.assertNotIn('rowspan', tax)
        self.assertNotIn('colspan', tax)
