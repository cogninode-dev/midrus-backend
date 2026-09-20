import datetime

from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import ContactMessage, Invoice, Service, ServiceDocument, User

BASE = '/api/auth/admin'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AdminApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            'admin@example.com', 'pw-admin-123', 'Admin',
            is_staff=True, is_email_verified=True, is_approved=True,
        )
        self.client_user = User.objects.create_user(
            'client@example.com', 'pw-client-123', 'Client One',
            company='Acme Traders', is_email_verified=True,
        )
        self.unverified = User.objects.create_user(
            'new@example.com', 'pw-new-123', 'New Person',
        )
        self.service = Service.objects.create(
            user=self.client_user, name='GST Return', charge='₹2,500/month',
            status='Requested',
        )
        self.doc = ServiceDocument.objects.create(
            service=self.service, file_name='sales.pdf',
        )
        self.msg = ContactMessage.objects.create(
            name='Visitor', email='v@example.com', phone='9999999999',
            message='Hello',
        )

    def as_admin(self):
        self.client.force_authenticate(self.admin)

    # ── permissions ─────────────────────────────────────────────────────────

    def test_requires_authentication(self):
        for path in ('overview', 'users', 'services', 'documents', 'messages', 'invoices'):
            self.assertEqual(self.client.get(f'{BASE}/{path}/').status_code, 401, path)

    def test_non_staff_forbidden(self):
        self.client.force_authenticate(self.client_user)
        for path in ('overview', 'users', 'services', 'documents', 'messages', 'invoices'):
            self.assertEqual(self.client.get(f'{BASE}/{path}/').status_code, 403, path)
        r = self.client.post(f'{BASE}/users/{self.unverified.pk}/approval/', {'approved': True}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_me_exposes_is_staff(self):
        self.as_admin()
        self.assertTrue(self.client.get('/api/auth/me/').data['is_staff'])
        self.client.force_authenticate(self.client_user)
        self.assertFalse(self.client.get('/api/auth/me/').data['is_staff'])

    def test_is_staff_not_writable_via_profile(self):
        self.client.force_authenticate(self.client_user)
        self.client.patch('/api/auth/profile/update/', {'is_staff': True}, format='json')
        self.client_user.refresh_from_db()
        self.assertFalse(self.client_user.is_staff)

    # ── overview / users ────────────────────────────────────────────────────

    def test_overview_counts(self):
        self.as_admin()
        d = self.client.get(f'{BASE}/overview/').data
        self.assertEqual(d['users_total'], 2)
        self.assertEqual(d['users_pending_approval'], 1)
        self.assertEqual(d['services_requested'], 1)
        self.assertEqual(d['documents_to_review'], 1)
        self.assertEqual(d['messages_unread'], 1)

    def test_users_list_filter_search_excludes_staff(self):
        self.as_admin()
        r = self.client.get(f'{BASE}/users/').data
        self.assertEqual(r['count'], 2)
        self.assertNotIn('admin@example.com', [u['email'] for u in r['results']])
        r = self.client.get(f'{BASE}/users/', {'filter': 'pending'}).data
        self.assertEqual([u['email'] for u in r['results']], ['client@example.com'])
        r = self.client.get(f'{BASE}/users/', {'q': 'acme'}).data
        self.assertEqual(r['count'], 1)
        r = self.client.get(f'{BASE}/users/', {'limit': 1}).data
        self.assertEqual(len(r['results']), 1)
        self.assertEqual(r['next_offset'], 1)

    def test_approve_and_revoke(self):
        self.as_admin()
        url = f'{BASE}/users/{self.client_user.pk}/approval/'
        r = self.client.post(url, {'approved': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['is_approved'])
        self.assertEqual(len(mail.outbox), 1)
        # approving again does not re-send the email
        self.client.post(url, {'approved': True}, format='json')
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(url, {'approved': False}, format='json')
        self.assertFalse(r.data['is_approved'])

    def test_cannot_approve_unverified_or_send_bad_body(self):
        self.as_admin()
        r = self.client.post(f'{BASE}/users/{self.unverified.pk}/approval/', {'approved': True}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f'{BASE}/users/{self.client_user.pk}/approval/', {'approved': 'yes'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_cannot_revoke_staff(self):
        self.as_admin()
        r = self.client.post(f'{BASE}/users/{self.admin.pk}/approval/', {'approved': False}, format='json')
        self.assertEqual(r.status_code, 400)

    # ── services ────────────────────────────────────────────────────────────

    def test_services_list_and_update(self):
        self.as_admin()
        r = self.client.get(f'{BASE}/services/', {'status': 'Requested'}).data
        self.assertEqual(r['results'][0]['client_email'], 'client@example.com')
        r = self.client.patch(
            f'{BASE}/services/{self.service.pk}/',
            {'status': 'Active', 'charge': '₹3,000/month', 'due_date': '2026-10-20'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.status, 'Active')
        self.assertEqual(self.service.due_date, datetime.date(2026, 10, 20))
        r = self.client.patch(f'{BASE}/services/{self.service.pk}/', {'due_date': None}, format='json')
        self.service.refresh_from_db()
        self.assertIsNone(self.service.due_date)

    def test_service_update_validation(self):
        self.as_admin()
        url = f'{BASE}/services/{self.service.pk}/'
        self.assertEqual(self.client.patch(url, {'status': 'Nope'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'due_date': '20-10-2026'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'name': '  '}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'charge': 'x' * 51}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'{BASE}/services/9999/', {}, format='json').status_code, 404)

    # ── documents ───────────────────────────────────────────────────────────

    def test_document_flow(self):
        self.as_admin()
        r = self.client.get(f'{BASE}/documents/', {'filter': 'pending'}).data
        self.assertEqual(r['count'], 1)
        self.assertEqual(r['results'][0]['client_name'], 'Client One')
        r = self.client.post(f'{BASE}/documents/{self.doc.pk}/reject/')
        self.assertEqual(r.data['status'], 'rejected')
        self.assertEqual(self.client.get(f'{BASE}/documents/', {'filter': 'rejected'}).data['count'], 1)
        r = self.client.post(f'{BASE}/documents/{self.doc.pk}/restore/')
        self.assertEqual(r.data['status'], 'active')
        r = self.client.post(f'{BASE}/documents/{self.doc.pk}/downloaded/')
        self.assertTrue(r.data['is_downloaded'])
        self.assertEqual(self.client.get(f'{BASE}/documents/', {'filter': 'pending'}).data['count'], 0)

    # ── messages ────────────────────────────────────────────────────────────

    def test_messages(self):
        self.as_admin()
        self.assertEqual(self.client.get(f'{BASE}/messages/', {'filter': 'unread'}).data['count'], 1)
        r = self.client.patch(f'{BASE}/messages/{self.msg.pk}/', {'is_read': True}, format='json')
        self.assertTrue(r.data['is_read'])
        self.assertEqual(self.client.get(f'{BASE}/messages/', {'filter': 'unread'}).data['count'], 0)
        self.assertEqual(
            self.client.patch(f'{BASE}/messages/{self.msg.pk}/', {'is_read': 'x'}, format='json').status_code, 400)

    # ── invoices ────────────────────────────────────────────────────────────

    def _invoice_body(self, **over):
        body = {
            'user_id': self.client_user.pk,
            'gst_rate': 18,
            'notes': 'Thanks',
            'items': [
                {'service_name': 'GST Return', 'month': 9, 'year': 2026, 'amount': '2500'},
                {'service_name': 'TDS Return', 'month': 9, 'year': 2026, 'amount': 1200.5},
            ],
        }
        body.update(over)
        return body

    def test_create_invoice_totals_and_email(self):
        self.as_admin()
        r = self.client.post(f'{BASE}/invoices/', self._invoice_body(), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['subtotal'], '3700.50')
        self.assertEqual(r.data['gst_amount'], '666.09')
        self.assertEqual(r.data['total'], '4366.59')
        self.assertTrue(r.data['invoice_number'].startswith('MAPL/'))
        self.assertEqual(len(r.data['items']), 2)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.created_by, self.admin)
        self.assertIn('Client One'.upper(), inv.bill_to)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(r.data['email_sent'])
        listed = self.client.get(f'{BASE}/invoices/').data
        self.assertEqual(listed['count'], 1)

    def test_invoice_numbers_increment(self):
        self.as_admin()
        a = self.client.post(f'{BASE}/invoices/', self._invoice_body(), format='json').data
        b = self.client.post(f'{BASE}/invoices/', self._invoice_body(), format='json').data
        self.assertNotEqual(a['invoice_number'], b['invoice_number'])

    def test_invoice_validation(self):
        self.as_admin()
        post = lambda **o: self.client.post(f'{BASE}/invoices/', self._invoice_body(**o), format='json')
        self.assertEqual(post(user_id=None).status_code, 400)
        self.assertEqual(post(user_id='abc').status_code, 400)
        self.assertEqual(post(user_id=9999).status_code, 400)
        self.assertEqual(post(gst_rate=7).status_code, 400)
        self.assertEqual(post(items=[]).status_code, 400)
        self.assertEqual(post(items='nope').status_code, 400)
        bad = lambda **o: post(items=[{'service_name': 'X', 'month': 9, 'year': 2026, 'amount': 10, **o}])
        self.assertEqual(bad(service_name=' ').status_code, 400)
        self.assertEqual(bad(month=13).status_code, 400)
        self.assertEqual(bad(year=1900).status_code, 400)
        self.assertEqual(bad(amount=0).status_code, 400)
        self.assertEqual(bad(amount=-5).status_code, 400)
        self.assertEqual(bad(amount='abc').status_code, 400)
        self.assertEqual(bad(amount='NaN').status_code, 400)
        self.assertEqual(bad(amount='1e20').status_code, 400)
        self.assertEqual(bad(quantity=0).status_code, 400)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_invoice_still_created_if_email_fails(self):
        self.as_admin()
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'):
            from unittest import mock
            with mock.patch('accounts.admin_api.send_invoice_email', side_effect=RuntimeError('smtp down')):
                r = self.client.post(f'{BASE}/invoices/', self._invoice_body(), format='json')
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.data['email_sent'])
        self.assertEqual(Invoice.objects.count(), 1)
