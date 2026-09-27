"""The Django admin site can download an invoice as a PDF."""
import tempfile
from unittest import mock

from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Invoice, InvoiceItem, User


class AdminInvoicePdfTests(TestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)

        self.admin = User.objects.create_superuser('root@example.com', 'Pw-root-123', 'Root')
        self.customer = User.objects.create_user(
            'client@example.com', 'Pw-client-123', 'Client One',
            company='Acme', is_email_verified=True,
        )
        self.invoice = Invoice.objects.create(user=self.customer, gst_rate=18)
        InvoiceItem.objects.create(
            invoice=self.invoice, service_name='GST Return', month=9, year=2026, amount=2500,
        )
        self.invoice.recalculate()
        self.invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])
        self.url = reverse('admin:accounts_invoice_pdf', args=[self.invoice.pk])

    def body(self, response):
        return b''.join(response.streaming_content) if response.streaming else response.content

    def test_staff_download_a_real_named_pdf(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn(self.invoice.invoice_number.replace('/', '-'), r['Content-Disposition'])
        self.assertTrue(self.body(r).startswith(b'%PDF-'))

    def test_an_uploaded_pdf_is_preferred(self):
        self.invoice.uploaded_pdf.save('mine.pdf', ContentFile(b'%PDF-1.4 uploaded-by-admin'), save=True)
        self.client.force_login(self.admin)
        r = self.client.get(self.url)
        self.assertEqual(self.body(r), b'%PDF-1.4 uploaded-by-admin')
        r.close()

    def test_the_list_and_the_change_form_link_to_it(self):
        self.client.force_login(self.admin)
        listing = self.client.get(reverse('admin:accounts_invoice_changelist'))
        self.assertContains(listing, self.url)
        self.assertContains(listing, '⬇ PDF')
        form = self.client.get(reverse('admin:accounts_invoice_change', args=[self.invoice.pk]))
        self.assertContains(form, self.url)
        self.assertContains(form, 'Download PDF')

    def test_the_add_form_says_the_pdf_comes_after_saving(self):
        self.client.force_login(self.admin)
        add = self.client.get(reverse('admin:accounts_invoice_add'))
        self.assertEqual(add.status_code, 200)

    def test_anonymous_visitors_are_sent_to_the_login_page(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])

    def test_a_customer_cannot_download_through_the_admin(self):
        self.client.force_login(self.customer)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)  # not staff: bounced to admin login
        self.assertIn('/admin/login/', r['Location'])

    def test_staff_without_invoice_access_are_refused(self):
        staff = User.objects.create_user(
            'staff@example.com', 'Pw-staff-123', 'Staff', is_staff=True, is_email_verified=True,
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        # ...until they are given view access.
        staff.user_permissions.add(Permission.objects.get(codename='view_invoice'))
        staff = User.objects.get(pk=staff.pk)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_unknown_invoice_is_a_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse('admin:accounts_invoice_pdf', args=[999999])).status_code, 404,
        )

    def test_a_pdf_engine_failure_is_a_clean_503(self):
        self.client.force_login(self.admin)
        with mock.patch('accounts.pdf.generate_invoice_pdf', side_effect=RuntimeError('boom')):
            r = self.client.get(self.url)
        self.assertEqual(r.status_code, 503)
