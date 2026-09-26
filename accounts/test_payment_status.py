"""Staff record the outcome of a customer's UPI payment on an invoice."""
from rest_framework.test import APITestCase

from .models import Invoice, InvoiceItem, User

API = '/api/auth'


class InvoicePaymentStatusTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            'admin@example.com', 'Pw-admin-123', 'Admin',
            is_staff=True, is_email_verified=True, is_approved=True,
        )
        self.customer = User.objects.create_user(
            'client@example.com', 'Pw-client-123', 'Client One',
            is_email_verified=True, is_approved=True,
        )
        self.other = User.objects.create_user(
            'other@example.com', 'Pw-other-123', 'Other Person',
            is_email_verified=True, is_approved=True,
        )
        self.invoice = Invoice.objects.create(user=self.customer, gst_rate=18)
        InvoiceItem.objects.create(
            invoice=self.invoice, service_name='GST Return', month=4, year=2026, amount=1000,
        )
        self.invoice.recalculate()
        self.invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])
        self.url = f'{API}/admin/invoices/{self.invoice.pk}/payment-status/'

    def test_new_invoice_is_pending_and_customer_sees_it(self):
        self.client.force_authenticate(self.customer)
        row = self.client.get(f'{API}/proforma-invoices/').json()[0]
        self.assertEqual(row['payment_status'], 'pending')
        self.assertEqual(row['payment_status_label'], 'Pending')
        self.assertEqual(row['total'], '1180.00')

    def test_staff_can_set_each_status_and_customer_sees_it(self):
        for value, label in [('processing', 'Processing'), ('success', 'Success'), ('failed', 'Failed')]:
            self.client.force_authenticate(self.admin)
            r = self.client.post(self.url, {'payment_status': value}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(r.json()['payment_status'], value)
            self.client.force_authenticate(self.customer)
            row = self.client.get(f'{API}/proforma-invoices/').json()[0]
            self.assertEqual((row['payment_status'], row['payment_status_label']), (value, label))

    def test_staff_list_includes_status(self):
        self.client.force_authenticate(self.admin)
        rows = self.client.get(f'{API}/admin/invoices/').json()['results']
        self.assertEqual(rows[0]['payment_status'], 'pending')

    def test_invalid_status_is_rejected(self):
        self.client.force_authenticate(self.admin)
        for bad in ('paid', '', None, 'SUCCESS'):
            r = self.client.post(self.url, {'payment_status': bad}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'pending')

    def test_customers_cannot_change_status(self):
        for user in (self.customer, self.other):
            self.client.force_authenticate(user)
            r = self.client.post(self.url, {'payment_status': 'success'}, format='json')
            self.assertEqual(r.status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.post(self.url, {'payment_status': 'success'}, format='json').status_code, (401, 403))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, 'pending')

    def test_unknown_invoice_is_404(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post(f'{API}/admin/invoices/999999/payment-status/',
                             {'payment_status': 'success'}, format='json')
        self.assertEqual(r.status_code, 404)
