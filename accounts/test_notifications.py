"""Customer notifications: what creates them, the API that serves them, and the
push hook."""
from unittest import mock

from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import (
    DeviceToken, Invoice, InvoiceItem, Notification, Service, ServiceDocument, User,
)
from .notifications import notify
from . import push

API = '/api/auth'


def make_invoice(user, amount=1000):
    invoice = Invoice.objects.create(user=user, gst_rate=18)
    InvoiceItem.objects.create(
        invoice=invoice, service_name='GST Return', month=9, year=2026, amount=amount,
    )
    invoice.recalculate()
    invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])
    return invoice


class NotificationTestCase(APITestCase):
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

    def mine(self, user=None):
        return list(Notification.objects.filter(user=user or self.customer).order_by('id'))


# ─── what creates notifications ──────────────────────────────────────────────

class PaymentStatusEvents(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.invoice = make_invoice(self.customer, 1000)  # total 1180.00
        Notification.objects.all().delete()

    def set_status(self, value):
        self.invoice.payment_status = value
        self.invoice.save(update_fields=['payment_status'])

    def test_each_status_change_tells_the_customer(self):
        expected = {
            'processing': 'Payment being verified',
            'success': 'Payment received',
            'failed': 'Payment failed',
            'pending': 'Payment pending',
        }
        for status, title in expected.items():
            Notification.objects.all().delete()
            self.invoice.refresh_from_db()
            if self.invoice.payment_status == status:
                self.set_status('processing' if status != 'processing' else 'failed')
                Notification.objects.all().delete()
            self.set_status(status)
            (n,) = self.mine()
            self.assertEqual(n.kind, 'payment', status)
            self.assertTrue(n.title.startswith(title), n.title)
            self.assertIn(self.invoice.invoice_number, n.title)
            self.assertEqual(n.ref_id, self.invoice.pk)
            self.assertFalse(n.is_read)

    def test_success_message_carries_the_amount(self):
        self.set_status('success')
        (n,) = self.mine()
        self.assertIn('₹1,180.00', n.body)

    def test_saving_without_a_status_change_stays_quiet(self):
        self.invoice.notes = 'edited'
        self.invoice.save()
        self.invoice.save(update_fields=['notes'])
        self.set_status('pending')  # already pending
        self.assertEqual(self.mine(), [])

    def test_recalculating_totals_does_not_notify(self):
        self.invoice.recalculate()
        self.invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])
        self.assertEqual(self.mine(), [])

    def test_only_the_invoice_owner_is_notified(self):
        self.set_status('success')
        self.assertEqual(len(self.mine()), 1)
        self.assertEqual(self.mine(self.other), [])
        self.assertEqual(self.mine(self.admin), [])

    def test_the_staff_api_and_the_django_admin_paths_both_notify(self):
        # Staff API
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            f'{API}/admin/invoices/{self.invoice.pk}/payment-status/',
            {'payment_status': 'failed'}, format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual([n.title.split(' ·')[0] for n in self.mine()], ['Payment failed'])
        # Any other code path that saves the model (Django admin, shell...)
        inv = Invoice.objects.get(pk=self.invoice.pk)
        inv.payment_status = 'success'
        inv.save()
        self.assertEqual(len(self.mine()), 2)


class InvoiceCreatedEvent(NotificationTestCase):
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_creating_an_invoice_notifies_with_its_real_total(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post(f'{API}/admin/invoices/', {
            'user_id': self.customer.pk, 'gst_rate': 18,
            'items': [{'service_name': 'TDS', 'month': 9, 'year': 2026, 'amount': '1000'}],
        }, format='json')
        self.assertEqual(r.status_code, 201)
        (n,) = self.mine()
        self.assertEqual(n.kind, 'invoice')
        self.assertIn(r.data['invoice_number'], n.title)
        self.assertIn('₹1,180.00', n.body)  # not ₹0.00: lines exist by now
        self.assertEqual(n.ref_id, r.data['id'])
        self.assertEqual(len(mail.outbox), 1)  # the email still goes out too

    def test_a_failed_email_does_not_lose_the_notification(self):
        with mock.patch('accounts.admin_api.send_invoice_email', side_effect=RuntimeError('smtp down')):
            self.client.force_authenticate(self.admin)
            r = self.client.post(f'{API}/admin/invoices/', {
                'user_id': self.customer.pk, 'gst_rate': 18,
                'items': [{'service_name': 'TDS', 'month': 9, 'year': 2026, 'amount': '10'}],
            }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.mine()), 1)


class ServiceEvents(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(
            user=self.customer, name='GST Return', charge='', status='Requested',
        )
        Notification.objects.all().delete()

    def test_a_new_request_is_not_a_notification(self):
        Service.objects.create(user=self.customer, name='Audit', charge='')
        self.assertEqual(self.mine(), [])

    def test_status_change_notifies(self):
        self.service.status = 'Active'
        self.service.save()
        (n,) = self.mine()
        self.assertEqual(n.kind, 'service')
        self.assertEqual(n.title, 'GST Return · Active')
        self.assertIn('now active', n.body)
        self.assertEqual(n.ref_id, self.service.pk)

    def test_status_and_charge_together_are_one_notification(self):
        self.service.status = 'Active'
        self.service.charge = '₹2,500/month'
        self.service.save()
        (n,) = self.mine()
        self.assertIn('₹2,500/month', n.body)

    def test_a_charge_change_alone_notifies(self):
        self.service.charge = '₹3,000'
        self.service.save()
        (n,) = self.mine()
        self.assertEqual(n.title, 'GST Return · updated')
        self.assertIn('₹3,000', n.body)

    def test_editing_other_fields_stays_quiet(self):
        self.service.description = 'new text'
        self.service.save()
        self.assertEqual(self.mine(), [])

    def test_the_staff_api_path_notifies(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            f'{API}/admin/services/{self.service.pk}/',
            {'status': 'Active', 'charge': '₹100'}, format='json',
        )
        self.assertEqual(r.status_code, 200, r.content)
        (n,) = self.mine()
        self.assertEqual(n.title, 'GST Return · Active')
        self.assertIn('₹100', n.body)


class DocumentEvents(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(user=self.customer, name='GST', charge='1')
        self.doc = ServiceDocument.objects.create(service=self.service, file_name='sales.pdf')
        Notification.objects.all().delete()

    def test_uploading_is_not_a_notification(self):
        ServiceDocument.objects.create(service=self.service, file_name='b.pdf')
        self.assertEqual(self.mine(), [])

    def test_rejection_and_restore_notify(self):
        self.doc.status = 'rejected'
        self.doc.save()
        self.doc.status = 'active'
        self.doc.save()
        rejected, restored = self.mine()
        self.assertEqual(rejected.title, 'Document rejected · sales.pdf')
        self.assertIn('corrected version', rejected.body)
        self.assertEqual(restored.title, 'Document restored · sales.pdf')
        self.assertEqual(rejected.ref_id, self.service.pk)

    def test_staff_opening_the_document_notifies_once(self):
        self.doc.is_downloaded = True
        self.doc.save(update_fields=['is_downloaded'])
        self.doc.save(update_fields=['is_downloaded'])
        (n,) = self.mine()
        self.assertEqual(n.title, 'Document received · sales.pdf')

    def test_the_staff_api_actions_notify(self):
        self.client.force_authenticate(self.admin)
        self.client.post(f'{API}/admin/documents/{self.doc.pk}/reject/')
        self.assertEqual([n.title.split(' ·')[0] for n in self.mine()], ['Document rejected'])


class AccountEvents(NotificationTestCase):
    def test_approval_and_revocation_notify(self):
        new = User.objects.create_user(
            'new@example.com', 'Pw-new-123', 'New Person', is_email_verified=True,
        )
        self.assertEqual(self.mine(new), [])
        self.client.force_authenticate(self.admin)
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.client.post(f'{API}/admin/users/{new.pk}/approval/', {'approved': True}, format='json')
        self.client.post(f'{API}/admin/users/{new.pk}/approval/', {'approved': False}, format='json')
        approved, revoked = self.mine(new)
        self.assertEqual(approved.kind, 'account')
        self.assertEqual(approved.title, 'Your account is approved')
        self.assertEqual(revoked.title, 'Your access was updated')

    def test_signing_up_or_changing_a_password_stays_quiet(self):
        new = User.objects.create_user('n2@example.com', 'Pw-new-123', 'N2')
        new.set_password('another-pass-1')
        new.save()
        new.name = 'Renamed'
        new.save()
        self.assertEqual(self.mine(new), [])


# ─── the API ─────────────────────────────────────────────────────────────────

class NotificationApi(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.n1 = notify(self.customer, 'payment', 'First', 'a', ref_id=1)
        self.n2 = notify(self.customer, 'invoice', 'Second', 'b', ref_id=2)
        self.n3 = notify(self.customer, 'service', 'Third', 'c', ref_id=3)
        self.theirs = notify(self.other, 'payment', 'Not yours', 'x')
        self.client.force_authenticate(self.customer)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        for path in ('notifications/', 'notifications/unread-count/'):
            self.assertEqual(self.client.get(f'{API}/{path}').status_code, 401, path)
        self.assertEqual(self.client.post(f'{API}/notifications/read-all/').status_code, 401)

    def test_lists_only_my_notifications_newest_first(self):
        data = self.client.get(f'{API}/notifications/').json()
        self.assertEqual([r['title'] for r in data['results']], ['Third', 'Second', 'First'])
        self.assertEqual(data['count'], 3)
        self.assertEqual(data['unread_count'], 3)
        self.assertIsNone(data['next_offset'])
        row = data['results'][0]
        self.assertEqual(
            set(row), {'id', 'kind', 'title', 'body', 'ref_id', 'is_read', 'created_at'},
        )
        self.assertEqual((row['kind'], row['ref_id']), ('service', 3))

    def test_pagination(self):
        page = self.client.get(f'{API}/notifications/', {'limit': 2}).json()
        self.assertEqual([r['title'] for r in page['results']], ['Third', 'Second'])
        self.assertEqual(page['next_offset'], 2)
        rest = self.client.get(f'{API}/notifications/', {'limit': 2, 'offset': 2}).json()
        self.assertEqual([r['title'] for r in rest['results']], ['First'])
        self.assertIsNone(rest['next_offset'])
        # Junk paging values fall back to the defaults instead of erroring.
        self.assertEqual(self.client.get(f'{API}/notifications/', {'limit': 'x'}).status_code, 200)

    def test_unread_filter_and_counts(self):
        self.client.post(f'{API}/notifications/{self.n2.pk}/read/')
        unread = self.client.get(f'{API}/notifications/', {'unread': '1'}).json()
        self.assertEqual([r['title'] for r in unread['results']], ['Third', 'First'])
        self.assertEqual(unread['unread_count'], 2)
        everything = self.client.get(f'{API}/notifications/').json()
        self.assertEqual(everything['count'], 3)
        self.assertEqual(
            self.client.get(f'{API}/notifications/unread-count/').json(), {'unread_count': 2},
        )

    def test_mark_one_read_is_idempotent(self):
        for _ in range(2):
            r = self.client.post(f'{API}/notifications/{self.n1.pk}/read/')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {'unread_count': 2})
        self.n1.refresh_from_db()
        self.assertTrue(self.n1.is_read)

    def test_mark_all_read_only_touches_my_own(self):
        r = self.client.post(f'{API}/notifications/read-all/')
        self.assertEqual(r.json(), {'unread_count': 0})
        self.assertFalse(Notification.objects.filter(user=self.customer, is_read=False).exists())
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_read)

    def test_cannot_read_or_mark_someone_elses(self):
        r = self.client.post(f'{API}/notifications/{self.theirs.pk}/read/')
        self.assertEqual(r.status_code, 404)
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_read)
        self.assertEqual(self.client.post(f'{API}/notifications/999999/read/').status_code, 404)

    def test_query_count_does_not_grow_with_notifications(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(f'{API}/notifications/').status_code, 200)
            return len(ctx)

        before = queries()
        for i in range(20):
            notify(self.customer, 'payment', f'More {i}')
        self.assertEqual(queries(), before)


# ─── push ────────────────────────────────────────────────────────────────────

TOKEN_A = 'a' * 40
TOKEN_B = 'b' * 40


class DeviceRegistration(NotificationTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.customer)

    def register(self, token=TOKEN_A, platform='android'):
        return self.client.post(f'{API}/devices/', {'token': token, 'platform': platform}, format='json')

    def test_registers_a_device(self):
        r = self.register()
        self.assertEqual(r.status_code, 201)
        d = DeviceToken.objects.get(token=TOKEN_A)
        self.assertEqual((d.user, d.platform), (self.customer, 'android'))

    def test_registering_twice_does_not_duplicate(self):
        self.register()
        self.register(platform='ios')
        self.assertEqual(DeviceToken.objects.count(), 1)
        self.assertEqual(DeviceToken.objects.get().platform, 'ios')

    def test_a_phone_that_changes_hands_follows_the_new_user(self):
        self.register()
        self.client.force_authenticate(self.other)
        self.register()
        self.assertEqual(DeviceToken.objects.get(token=TOKEN_A).user, self.other)

    def test_unregistering_removes_only_my_own_token(self):
        self.register()
        self.client.force_authenticate(self.other)
        r = self.client.delete(f'{API}/devices/', {'token': TOKEN_A}, format='json')
        self.assertEqual(r.status_code, 204)
        self.assertTrue(DeviceToken.objects.filter(token=TOKEN_A).exists())  # not theirs
        self.client.force_authenticate(self.customer)
        self.client.delete(f'{API}/devices/', {'token': TOKEN_A}, format='json')
        self.assertFalse(DeviceToken.objects.filter(token=TOKEN_A).exists())

    def test_validation(self):
        self.assertEqual(self.register(token='short').status_code, 400)
        self.assertEqual(self.register(token='x' * 600).status_code, 400)
        self.assertEqual(self.register(platform='windows').status_code, 400)
        self.assertEqual(self.client.post(f'{API}/devices/', {}, format='json').status_code, 400)
        self.client.force_authenticate(None)
        self.assertEqual(self.register().status_code, 401)


class RecordingBackend(push.PushBackend):
    calls = []
    invalid = []

    def send(self, tokens, title, body, data):
        RecordingBackend.calls.append((sorted(tokens), title, body, data))
        return list(RecordingBackend.invalid)


@override_settings(PUSH_BACKEND='accounts.test_notifications.RecordingBackend')
class PushDelivery(NotificationTestCase):
    def setUp(self):
        super().setUp()
        RecordingBackend.calls = []
        RecordingBackend.invalid = []
        DeviceToken.objects.create(user=self.customer, token=TOKEN_A, platform='android')
        DeviceToken.objects.create(user=self.customer, token=TOKEN_B, platform='ios')
        DeviceToken.objects.create(user=self.other, token='c' * 40, platform='android')

    def test_a_new_notification_is_pushed_to_all_of_that_users_devices_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            n = notify(self.customer, 'payment', 'Payment received · X', 'Thanks', ref_id=7)
        (tokens, title, body, data), = RecordingBackend.calls
        self.assertEqual(tokens, [TOKEN_A, TOKEN_B])  # not the other user's phone
        self.assertEqual((title, body), ('Payment received · X', 'Thanks'))
        self.assertEqual(data, {'kind': 'payment', 'notification_id': str(n.pk), 'ref_id': '7'})

    def test_real_events_reach_push_too(self):
        invoice = make_invoice(self.customer)
        with self.captureOnCommitCallbacks(execute=True):
            invoice.payment_status = 'success'
            invoice.save(update_fields=['payment_status'])
        self.assertEqual(len(RecordingBackend.calls), 1)
        self.assertTrue(RecordingBackend.calls[0][1].startswith('Payment received'))

    def test_no_devices_means_nothing_is_sent(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.admin, 'account', 'Hello')
        self.assertEqual(RecordingBackend.calls, [])

    def test_tokens_the_provider_rejects_are_forgotten(self):
        RecordingBackend.invalid = [TOKEN_B]
        with self.captureOnCommitCallbacks(execute=True):
            notify(self.customer, 'payment', 'x')
        self.assertEqual(
            list(DeviceToken.objects.filter(user=self.customer).values_list('token', flat=True)),
            [TOKEN_A],
        )

    def test_a_push_outage_never_breaks_the_request_or_loses_the_notification(self):
        with mock.patch.object(RecordingBackend, 'send', side_effect=RuntimeError('FCM down')):
            with self.captureOnCommitCallbacks(execute=True):
                notify(self.customer, 'payment', 'still stored')
        self.assertTrue(Notification.objects.filter(title='still stored').exists())

    def test_the_default_backend_sends_nothing_and_is_safe(self):
        with override_settings(PUSH_BACKEND='accounts.push.LoggingPushBackend'):
            with self.captureOnCommitCallbacks(execute=True):
                notify(self.customer, 'payment', 'logged only')
        self.assertEqual(RecordingBackend.calls, [])
