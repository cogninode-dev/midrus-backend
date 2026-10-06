"""The in-app admin can create, read, update and delete like the Django admin."""
import tempfile

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import (
    ContactMessage, Invoice, InvoiceItem, Service, ServiceDocument, User,
)

BASE = '/api/auth/admin'
PDF = b'%PDF-1.4 test'

LOCAL_STORAGE = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), STORAGES=LOCAL_STORAGE)
class AdminCrudBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            'admin@example.com', 'pw-admin-123', 'Admin',
            is_staff=True, is_email_verified=True, is_approved=True,
        )
        self.other_admin = User.objects.create_user(
            'boss@example.com', 'pw-boss-123', 'Boss',
            is_staff=True, is_superuser=True, is_email_verified=True,
        )
        self.client_user = User.objects.create_user(
            'client@example.com', 'pw-client-123', 'Client One',
            company='Acme', is_email_verified=True, is_approved=True,
        )
        self.client.force_authenticate(self.admin)


class AccessTests(AdminCrudBase):
    def test_customers_cannot_use_any_write_endpoint(self):
        self.client.force_authenticate(self.client_user)
        s = Service.objects.create(user=self.client_user, name='GST')
        for method, url in [
            ('post', f'{BASE}/users/'),
            ('patch', f'{BASE}/users/{self.client_user.pk}/'),
            ('delete', f'{BASE}/users/{self.client_user.pk}/'),
            ('post', f'{BASE}/services/'),
            ('delete', f'{BASE}/services/{s.pk}/'),
            ('post', f'{BASE}/documents/'),
            ('patch', f'{BASE}/invoices/1/'),
            ('delete', f'{BASE}/invoices/1/'),
            ('delete', f'{BASE}/messages/1/'),
        ]:
            r = getattr(self.client, method)(url, {}, format='json')
            self.assertEqual(r.status_code, 403, f'{method} {url}')

    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'{BASE}/users/', {}, format='json').status_code, 401)


class ClientTests(AdminCrudBase):
    def test_create_client(self):
        r = self.client.post(f'{BASE}/users/', {
            'email': 'New@Example.com', 'password': 'secret1', 'name': '  New   Person ',
            'phone': '9999999999', 'company': 'Neo', 'website': 'neo.in',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        user = User.objects.get(email='new@example.com')
        self.assertEqual(user.name, 'New Person')
        self.assertEqual(user.website, 'https://neo.in')
        self.assertTrue(user.is_email_verified and user.is_approved and user.is_active)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password('secret1'))

    def test_create_client_validation(self):
        base = {'email': 'x@example.com', 'password': 'secret1', 'name': 'X'}
        for bad in [
            {**base, 'email': 'nope'},
            {**base, 'email': 'client@example.com'},
            {**base, 'email': 'CLIENT@example.com'},
            {**base, 'password': '123'},
            {**base, 'name': ''},
            {**base, 'phone': '1' * 40},
            {**base, 'is_approved': 'yes'},
        ]:
            r = self.client.post(f'{BASE}/users/', bad, format='json')
            self.assertEqual(r.status_code, 400, bad)

    def test_cannot_create_staff_through_the_app(self):
        r = self.client.post(f'{BASE}/users/', {
            'email': 'sneaky@example.com', 'password': 'secret1', 'name': 'S',
            'is_staff': True, 'is_superuser': True,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(email='sneaky@example.com')
        self.assertFalse(u.is_staff or u.is_superuser)

    def test_update_client(self):
        r = self.client.patch(f'{BASE}/users/{self.client_user.pk}/', {
            'name': 'Renamed', 'company': 'New Co', 'gst_number': '29ABCDE1234F1Z5',
            'address': 'Line 1\nLine 2',
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.client_user.refresh_from_db()
        self.assertEqual(self.client_user.name, 'Renamed')
        self.assertEqual(self.client_user.company, 'New Co')
        self.assertEqual(self.client_user.address, 'Line 1\nLine 2')

    def test_update_rejects_bad_values(self):
        url = f'{BASE}/users/{self.client_user.pk}/'
        self.assertEqual(self.client.patch(url, {'name': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'email': 'broken'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'email': 'boss@example.com'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'password': '1'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'is_active': 'no'}, format='json').status_code, 400)

    def test_change_email_and_password(self):
        url = f'{BASE}/users/{self.client_user.pk}/'
        r = self.client.patch(url, {'email': 'Fresh@Example.com', 'password': 'brand-new-1'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.client_user.refresh_from_db()
        self.assertEqual(self.client_user.email, 'fresh@example.com')
        self.assertTrue(self.client_user.check_password('brand-new-1'))

    def test_deactivate_hides_from_list_and_can_be_reactivated(self):
        url = f'{BASE}/users/{self.client_user.pk}/'
        self.client.patch(url, {'is_active': False}, format='json')
        emails = [u['email'] for u in self.client.get(f'{BASE}/users/').data['results']]
        self.assertNotIn('client@example.com', emails)
        inactive = [u['email'] for u in self.client.get(f'{BASE}/users/?filter=inactive').data['results']]
        self.assertEqual(inactive, ['client@example.com'])
        self.assertFalse(self.client.get(url).data['user']['is_active'])
        self.client.patch(url, {'is_active': True}, format='json')
        self.assertTrue(User.objects.get(pk=self.client_user.pk).is_active)

    def test_self_erased_accounts_stay_out_of_the_inactive_list(self):
        User.objects.create_user('deleted-9@deleted.invalid', 'x', 'Deleted user', is_active=False)
        inactive = [u['email'] for u in self.client.get(f'{BASE}/users/?filter=inactive').data['results']]
        self.assertEqual(inactive, [])

    def test_delete_client_removes_everything_of_theirs(self):
        service = Service.objects.create(user=self.client_user, name='GST')
        doc = ServiceDocument.objects.create(service=service, file_name='a.pdf')
        doc.file.save('a.pdf', ContentFile(PDF), save=True)
        invoice = Invoice.objects.create(user=self.client_user)
        self.client_user.photo.save('me.png', ContentFile(b'\x89PNG\r\n\x1a\n'), save=True)
        path = doc.file.path
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.delete(f'{BASE}/users/{self.client_user.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.client_user.pk).exists())
        self.assertFalse(Service.objects.filter(pk=service.pk).exists())
        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())
        import os
        self.assertFalse(os.path.exists(path))

    def test_staff_accounts_cannot_be_edited_or_deleted_from_the_app(self):
        for target in (self.other_admin, self.admin):
            url = f'{BASE}/users/{target.pk}/'
            self.assertEqual(self.client.patch(url, {'name': 'Hacked'}, format='json').status_code, 404)
            self.assertEqual(self.client.delete(url).status_code, 404)
            self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_unknown_client_is_404(self):
        self.assertEqual(self.client.delete(f'{BASE}/users/99999/').status_code, 404)


class ServiceTests(AdminCrudBase):
    def test_create_service_for_a_client(self):
        r = self.client.post(f'{BASE}/services/', {
            'client_id': self.client_user.pk, 'name': 'GST Return Filing',
            'charge': '₹1,500', 'due_date': '2026-11-20', 'description': 'Monthly',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        s = Service.objects.get()
        self.assertEqual((s.user_id, s.status, str(s.due_date)), (self.client_user.pk, 'Active', '2026-11-20'))

    def test_create_service_validation(self):
        ok = {'client_id': self.client_user.pk, 'name': 'X'}
        for bad in [
            {**ok, 'client_id': 99999},
            {**ok, 'client_id': self.admin.pk},  # staff are not clients
            {'name': 'X'},
            {**ok, 'name': ''},
            {**ok, 'name': 'n' * 201},
            {**ok, 'status': 'Bogus'},
            {**ok, 'due_date': '31-12-2026'},
            {**ok, 'charge': 'c' * 51},
        ]:
            self.assertEqual(self.client.post(f'{BASE}/services/', bad, format='json').status_code, 400, bad)

    def test_delete_service_removes_its_documents(self):
        s = Service.objects.create(user=self.client_user, name='GST')
        ServiceDocument.objects.create(service=s, file_name='a.pdf')
        r = self.client.delete(f'{BASE}/services/{s.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(Service.objects.count(), 0)
        self.assertEqual(ServiceDocument.objects.count(), 0)


class DocumentTests(AdminCrudBase):
    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(user=self.client_user, name='GST')

    def test_upload_on_behalf_of_a_client(self):
        r = self.client.post(f'{BASE}/documents/', {
            'service_id': self.service.pk,
            'file': SimpleUploadedFile('return.pdf', PDF, content_type='application/pdf'),
        }, format='multipart')
        self.assertEqual(r.status_code, 201)
        doc = ServiceDocument.objects.get()
        self.assertEqual((doc.service_id, doc.file_name, doc.status), (self.service.pk, 'return.pdf', 'active'))
        self.assertTrue(r.data['file_url'])

    def test_upload_rules(self):
        def post(**kw):
            return self.client.post(f'{BASE}/documents/', kw, format='multipart')
        good = SimpleUploadedFile('a.pdf', PDF, content_type='application/pdf')
        self.assertEqual(post(file=good).status_code, 400)  # no service
        self.assertEqual(post(service_id=99999, file=SimpleUploadedFile('a.pdf', PDF)).status_code, 400)
        self.assertEqual(post(service_id=self.service.pk).status_code, 400)  # no file
        fake = SimpleUploadedFile('evil.pdf', b'MZ not a pdf', content_type='application/pdf')
        self.assertEqual(post(service_id=self.service.pk, file=fake).status_code, 400)
        exe = SimpleUploadedFile('run.exe', b'MZ', content_type='application/octet-stream')
        self.assertEqual(post(service_id=self.service.pk, file=exe).status_code, 400)
        self.assertEqual(ServiceDocument.objects.count(), 0)

    def test_delete_document_removes_the_file(self):
        doc = ServiceDocument.objects.create(service=self.service, file_name='a.pdf')
        doc.file.save('a.pdf', ContentFile(PDF), save=True)
        path = doc.file.path
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.delete(f'{BASE}/documents/{doc.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(ServiceDocument.objects.count(), 0)
        import os
        self.assertFalse(os.path.exists(path))


class MessageTests(AdminCrudBase):
    def test_delete_message(self):
        m = ContactMessage.objects.create(name='V', email='v@example.com', phone='1', message='Hi')
        self.assertEqual(self.client.delete(f'{BASE}/messages/{m.pk}/').status_code, 204)
        self.assertEqual(ContactMessage.objects.count(), 0)
        self.assertEqual(self.client.delete(f'{BASE}/messages/{m.pk}/').status_code, 404)


class InvoiceTests(AdminCrudBase):
    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(user=self.client_user, gst_rate=18)
        InvoiceItem.objects.create(invoice=self.invoice, service_name='GST', month=4, year=2026, amount=1000)
        self.invoice.recalculate()
        self.invoice.save()

    def test_get_one(self):
        r = self.client.get(f'{BASE}/invoices/{self.invoice.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['invoice_number'], self.invoice.invoice_number)

    def test_edit_lines_and_gst_recalculates(self):
        r = self.client.patch(f'{BASE}/invoices/{self.invoice.pk}/', {
            'gst_rate': 12, 'notes': 'Updated',
            'items': [
                {'service_name': 'TDS', 'month': 5, 'year': 2026, 'amount': '2000'},
                {'service_name': 'ROC', 'month': 5, 'year': 2026, 'amount': '500.50', 'quantity': 2},
            ],
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.items.count(), 2)
        self.assertEqual(str(self.invoice.subtotal), '2500.50')
        self.assertEqual(str(self.invoice.gst_amount), '300.06')
        self.assertEqual(str(self.invoice.total), '2800.56')
        self.assertEqual(self.invoice.notes, 'Updated')

    def test_editing_a_line_by_id_keeps_its_quantity_and_unit(self):
        line = self.invoice.items.get()
        line.quantity, line.per = 3, 'Quarter'
        line.save()
        r = self.client.patch(f'{BASE}/invoices/{self.invoice.pk}/', {'items': [
            {'id': line.pk, 'service_name': 'GST (revised)', 'month': 4, 'year': 2026, 'amount': '1200'},
            {'service_name': 'New line', 'month': 5, 'year': 2026, 'amount': '300'},
        ]}, format='json')
        self.assertEqual(r.status_code, 200)
        line.refresh_from_db()
        self.assertEqual((line.service_name, str(line.amount), str(line.quantity), line.per),
                         ('GST (revised)', '1200.00', '3.00', 'Quarter'))
        self.assertEqual(self.invoice.items.count(), 2)

    def test_lines_left_out_of_an_edit_are_removed(self):
        keep = self.invoice.items.get()
        extra = InvoiceItem.objects.create(invoice=self.invoice, service_name='Old', month=1, year=2026, amount=50)
        self.client.patch(f'{BASE}/invoices/{self.invoice.pk}/', {'items': [
            {'id': keep.pk, 'service_name': 'GST', 'month': 4, 'year': 2026, 'amount': '1000'},
        ]}, format='json')
        self.assertEqual(list(self.invoice.items.values_list('pk', flat=True)), [keep.pk])
        self.assertFalse(InvoiceItem.objects.filter(pk=extra.pk).exists())

    def test_cannot_hijack_another_invoices_line_by_id(self):
        other = Invoice.objects.create(user=self.client_user)
        foreign = InvoiceItem.objects.create(invoice=other, service_name='Theirs', month=1, year=2026, amount=77)
        self.client.patch(f'{BASE}/invoices/{self.invoice.pk}/', {'items': [
            {'id': foreign.pk, 'service_name': 'Mine now', 'month': 1, 'year': 2026, 'amount': '5'},
        ]}, format='json')
        foreign.refresh_from_db()
        self.assertEqual((foreign.service_name, foreign.invoice_id), ('Theirs', other.pk))

    def test_edit_without_items_keeps_lines_and_recalculates_gst(self):
        self.client.patch(f'{BASE}/invoices/{self.invoice.pk}/', {'gst_rate': 5}, format='json')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.items.count(), 1)
        self.assertEqual(str(self.invoice.total), '1050.00')

    def test_bad_edit_changes_nothing(self):
        before = (self.invoice.total, self.invoice.items.count())
        for bad in [
            {'gst_rate': 99},
            {'items': []},
            {'items': [{'service_name': '', 'month': 1, 'year': 2026, 'amount': 5}]},
            {'items': [{'service_name': 'x', 'month': 13, 'year': 2026, 'amount': 5}]},
            {'items': [{'service_name': 'x', 'month': 1, 'year': 2026, 'amount': -5}]},
        ]:
            self.assertEqual(
                self.client.patch(f'{BASE}/invoices/{self.invoice.pk}/', bad, format='json').status_code, 400, bad,
            )
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.total, self.invoice.items.count()), before)

    def test_delete_invoice(self):
        r = self.client.delete(f'{BASE}/invoices/{self.invoice.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(InvoiceItem.objects.count(), 0)

    def test_deleting_the_newest_invoice_frees_its_number(self):
        first = self.invoice.invoice_number
        self.client.delete(f'{BASE}/invoices/{self.invoice.pk}/')
        again = Invoice.objects.create(user=self.client_user)
        self.assertEqual(again.invoice_number, first)  # numbering continues from the highest remaining
