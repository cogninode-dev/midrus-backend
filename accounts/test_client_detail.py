"""The admin's one-screen view of a client: profile, services, documents,
invoices and payment totals."""
from django.core.files.base import ContentFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from .models import Invoice, InvoiceItem, Service, ServiceDocument, User

API = '/api/auth'


def make_invoice(user, amount, status):
    invoice = Invoice.objects.create(user=user, gst_rate=0, payment_status=status)
    InvoiceItem.objects.create(
        invoice=invoice, service_name='GST Return', month=4, year=2026, amount=amount,
    )
    invoice.recalculate()
    invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])
    return invoice


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ClientDetailTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            'admin@example.com', 'Pw-admin-123', 'Admin',
            is_staff=True, is_email_verified=True, is_approved=True,
        )
        self.client_user = User.objects.create_user(
            'client@example.com', 'Pw-client-123', 'Client One',
            company='Acme Traders', phone='9876543210', address='1 Main Road',
            gst_number='29ABCDE1234F1Z5', is_email_verified=True,
        )
        self.other = User.objects.create_user(
            'other@example.com', 'Pw-other-123', 'Other Person', is_email_verified=True,
        )
        self.service = Service.objects.create(
            user=self.client_user, name='GST Return', charge='₹2,500/month', status='Active',
        )
        self.doc = ServiceDocument.objects.create(
            service=self.service, file_name='sales.pdf',
            file=ContentFile(b'%PDF-1.4 x', name='sales.pdf'),
        )
        make_invoice(self.client_user, 1000, 'success')
        make_invoice(self.client_user, 400, 'pending')
        make_invoice(self.client_user, 250, 'failed')
        make_invoice(self.client_user, 100, 'processing')
        # Someone else's invoice and service must never leak in.
        make_invoice(self.other, 9999, 'success')
        Service.objects.create(user=self.other, name='Audit', charge='1')
        self.url = f'{API}/admin/users/{self.client_user.pk}/'
        self.client.force_authenticate(self.admin)

    def test_returns_profile_services_documents_and_invoices(self):
        data = self.client.get(self.url).json()
        self.assertEqual(data['user']['email'], 'client@example.com')
        self.assertEqual(data['user']['company'], 'Acme Traders')
        self.assertEqual(data['user']['gst_number'], '29ABCDE1234F1Z5')

        self.assertEqual([s['name'] for s in data['services']], ['GST Return'])
        docs = data['services'][0]['documents']
        self.assertEqual([d['file_name'] for d in docs], ['sales.pdf'])
        self.assertIn('/api/auth/files/', docs[0]['file_url'])

        self.assertEqual(len(data['invoices']), 4)
        self.assertEqual(
            {i['payment_status'] for i in data['invoices']},
            {'success', 'pending', 'failed', 'processing'},
        )
        self.assertTrue(all(i['pdf_url'] for i in data['invoices']))

    def test_payment_totals(self):
        s = self.client.get(self.url).json()['summary']
        self.assertEqual(s['invoices_count'], 4)
        self.assertEqual(s['billed'], '1750.00')
        self.assertEqual(s['paid'], '1000.00')
        self.assertEqual(s['processing'], '100.00')
        # Pending and failed invoices are what the client still has to pay.
        self.assertEqual(s['outstanding'], '650.00')
        self.assertEqual(s['documents_count'], 1)

    def test_a_client_with_nothing_yet(self):
        blank = User.objects.create_user(
            'blank@example.com', 'Pw-blank-123', 'Blank', is_email_verified=True,
        )
        data = self.client.get(f'{API}/admin/users/{blank.pk}/').json()
        self.assertEqual(data['services'], [])
        self.assertEqual(data['invoices'], [])
        self.assertEqual(data['summary']['billed'], '0.00')
        self.assertEqual(data['summary']['outstanding'], '0.00')

    def test_status_change_is_reflected_in_totals(self):
        pending = Invoice.objects.get(payment_status='pending')
        self.client.post(
            f'{API}/admin/invoices/{pending.pk}/payment-status/',
            {'payment_status': 'success'}, format='json',
        )
        s = self.client.get(self.url).json()['summary']
        self.assertEqual(s['paid'], '1400.00')
        self.assertEqual(s['outstanding'], '250.00')

    def test_staff_accounts_and_unknown_ids_are_404(self):
        self.assertEqual(self.client.get(f'{API}/admin/users/{self.admin.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'{API}/admin/users/999999/').status_code, 404)

    def test_only_staff_can_read_it(self):
        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_query_count_does_not_grow_with_data(self):
        def queries():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(self.url).status_code, 200)
            return len(ctx)

        before = queries()
        for _ in range(5):
            make_invoice(self.client_user, 10, 'pending')
            svc = Service.objects.create(user=self.client_user, name='Extra', charge='1')
            ServiceDocument.objects.create(service=svc, file_name='a.pdf')
        # Far more rows, same number of queries: no per-row lookups.
        self.assertEqual(queries(), before)
