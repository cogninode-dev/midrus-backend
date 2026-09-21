"""Terms-of-service consent and self-service account deletion."""
import tempfile
from pathlib import Path

from django.core import mail
from django.core.files.base import ContentFile
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import ContactMessage, EmailOTP, Invoice, InvoiceItem, Service, ServiceDocument, User

API = '/api/auth'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ConsentTests(APITestCase):
    def _register(self, **over):
        body = {'email': 'new@example.com', 'password': 'Pw-new-123', 'name': 'New Person', **over}
        return self.client.post(f'{API}/register/', body, format='json')

    def test_acceptance_is_recorded_with_the_terms_version(self):
        self.assertEqual(self._register(accepted_terms=True).status_code, 201)
        user = User.objects.get(email='new@example.com')
        self.assertIsNotNone(user.terms_accepted_at)
        self.assertTrue(user.terms_version)

    def test_older_clients_without_the_checkbox_still_work_by_default(self):
        self.assertEqual(self._register().status_code, 201)
        self.assertIsNone(User.objects.get(email='new@example.com').terms_accepted_at)

    @override_settings(REQUIRE_TERMS_ACCEPTANCE=True)
    def test_can_be_made_mandatory(self):
        r = self._register()
        self.assertEqual(r.status_code, 400)
        self.assertIn('accepted_terms', r.data)
        r = self._register(accepted_terms=False)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._register(accepted_terms=True).status_code, 201)

    def test_the_flag_cannot_be_set_through_the_profile_endpoint(self):
        self._register(accepted_terms=True)
        user = User.objects.get(email='new@example.com')
        self.client.force_authenticate(user)
        self.client.patch(f'{API}/profile/update/', {'terms_version': 'hacked'}, format='json')
        user.refresh_from_db()
        self.assertNotEqual(user.terms_version, 'hacked')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AccountDeletionTests(APITestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)

        self.user = User.objects.create_user(
            'asha@example.com', 'Pw-asha-123', 'Asha Kapoor', company='Kapoor Textiles',
            phone='9810011223', address='12 Ring Road', gst_number='07AABCK1234F1Z5',
            website='https://kapoor.example', tax_id='ABCDE1234F',
            is_email_verified=True, is_approved=True,
        )
        self.service = Service.objects.create(
            user=self.user, name='GST Return', status='Active', description='private notes about my business',
        )
        self.doc = ServiceDocument(service=self.service, file_name='sales.pdf')
        self.doc.file.save('sales.pdf', ContentFile(b'%PDF-1.4 x'), save=True)
        self.doc_path = Path(self.doc.file.path)
        self.invoice = Invoice.objects.create(user=self.user, gst_rate=18)
        InvoiceItem.objects.create(
            invoice=self.invoice, service_name='GST Return', month=9, year=2026, amount=1000,
        )
        self.invoice.recalculate()
        self.invoice.save()
        ContactMessage.objects.create(
            name='Asha', email='ASHA@example.com', phone='1', message='hello',
        )
        ContactMessage.objects.create(name='Other', email='other@example.com', phone='1', message='keep')
        EmailOTP.objects.create(user=self.user, otp='123456')

    def _delete(self, password='Pw-asha-123', user=None):
        self.client.force_authenticate(user or self.user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f'{API}/account/delete/', {'password': password}, format='json')

    # ── guards ──────────────────────────────────────────────────────────────

    def test_requires_authentication(self):
        r = self.client.post(f'{API}/account/delete/', {'password': 'x'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_wrong_or_missing_password_deletes_nothing(self):
        for body in ({'password': 'wrong'}, {}, {'password': None}, {'password': 123}):
            self.client.force_authenticate(self.user)
            r = self.client.post(f'{API}/account/delete/', body, format='json')
            self.assertEqual(r.status_code, 400, body)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.email, 'asha@example.com')
        self.assertTrue(self.doc_path.exists())

    def test_staff_accounts_cannot_delete_themselves(self):
        staff = User.objects.create_user(
            'admin@example.com', 'Pw-admin-123', 'Admin', is_staff=True, is_email_verified=True,
        )
        r = self._delete('Pw-admin-123', user=staff)
        self.assertEqual(r.status_code, 403)
        staff.refresh_from_db()
        self.assertTrue(staff.is_active)

    # ── what is erased ──────────────────────────────────────────────────────

    def test_personal_data_is_erased_and_the_account_locked(self):
        r = self._delete()
        self.assertEqual(r.status_code, 200, r.data)
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(u.is_active)
        self.assertFalse(u.is_approved)
        self.assertFalse(u.is_email_verified)
        self.assertFalse(u.has_usable_password())
        self.assertEqual(u.name, 'Deleted user')
        self.assertEqual(u.email, f'deleted-{u.pk}@deleted.invalid')
        for field in ('phone', 'company', 'address', 'website', 'tax_id', 'gst_number'):
            self.assertEqual(getattr(u, field), '', field)

    def test_uploaded_documents_and_their_files_are_removed(self):
        self.assertTrue(self.doc_path.exists())
        self._delete()
        self.assertFalse(ServiceDocument.objects.filter(pk=self.doc.pk).exists())
        self.assertFalse(self.doc_path.exists(), 'the file must be gone from disk too')

    def test_otps_and_matching_contact_messages_are_removed_others_kept(self):
        self._delete()
        self.assertFalse(EmailOTP.objects.filter(user=self.user).exists())
        remaining = list(ContactMessage.objects.values_list('email', flat=True))
        self.assertEqual(remaining, ['other@example.com'])

    def test_service_notes_are_cleared_but_the_record_is_kept(self):
        self._delete()
        service = Service.objects.get(pk=self.service.pk)
        self.assertEqual(service.description, '')
        self.assertEqual(service.name, 'GST Return')

    # ── what must survive (statutory record-keeping) ────────────────────────

    def test_issued_invoices_are_retained_intact(self):
        total = self.invoice.total
        number = self.invoice.invoice_number
        self._delete()
        inv = Invoice.objects.get(pk=self.invoice.pk)
        self.assertEqual(inv.invoice_number, number)
        self.assertEqual(inv.total, total)
        self.assertEqual(inv.items.count(), 1)

    # ── sessions & re-registration ──────────────────────────────────────────

    def test_existing_sessions_and_logins_stop_working(self):
        refresh = str(RefreshToken.for_user(self.user))
        self._delete()
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'{API}/token/refresh/', {'refresh': refresh}, format='json').status_code, 401)
        r = self.client.post(f'{API}/login/', {'email': 'asha@example.com', 'password': 'Pw-asha-123'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_the_email_address_can_be_used_to_sign_up_again(self):
        self._delete()
        self.client.force_authenticate(None)
        r = self.client.post(f'{API}/register/', {
            'email': 'asha@example.com', 'password': 'Pw-asha-456', 'name': 'Asha Again',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_a_confirmation_email_goes_to_the_original_address(self):
        mail.outbox.clear()
        self._delete()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['asha@example.com'])
        self.assertIn('deleted', mail.outbox[0].subject.lower())

    def test_deleted_accounts_disappear_from_the_admin_lists(self):
        staff = User.objects.create_user('s@example.com', 'Pw-staff-123', 'Staff', is_staff=True, is_email_verified=True)
        self._delete()
        self.client.force_authenticate(staff)
        emails = [u['email'] for u in self.client.get(f'{API}/admin/users/').data['results']]
        self.assertNotIn(f'deleted-{self.user.pk}@deleted.invalid', emails)
        self.assertEqual(self.client.get(f'{API}/admin/overview/').data['users_total'], 0)
