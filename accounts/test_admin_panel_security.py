"""Regression tests for the Django admin panel security fixes:

1. Customer-editable profile fields (name/company/address/gst_number/phone)
   must be HTML-escaped everywhere the admin renders them, or a poisoned
   profile runs script in a staff member's browser (stored XSS).
2. The approve/reject/mark-downloaded admin actions must require POST, since
   Django's CSRF middleware does not protect GET and a crafted link could
   otherwise trigger them just from an admin clicking it.
"""
from django.contrib import admin as django_admin
from django.test import Client, TestCase

from .admin import InvoiceAdmin
from .models import Invoice, Service, ServiceDocument, User

XSS = '<script>alert(1)</script>'


class AdminXSSEscapingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'client@example.com', 'pw-client-123', XSS,
            company=XSS, address=XSS, gst_number=XSS, phone=XSS,
            is_email_verified=True, is_approved=True,
        )
        self.invoice = Invoice.objects.create(user=self.user)

    def test_customer_info_escapes_every_profile_field(self):
        html = str(InvoiceAdmin(Invoice, django_admin.site).customer_info(self.invoice))
        self.assertNotIn(XSS, html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)


class AdminActionsRequirePostTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            'admin@example.com', 'pw-admin-123', 'Admin', is_email_verified=True,
        )
        self.user = User.objects.create_user(
            'client@example.com', 'pw-client-123', 'Client One',
            is_email_verified=True, is_approved=False,
        )
        self.service = Service.objects.create(user=self.user, name='GST')
        self.doc = ServiceDocument.objects.create(service=self.service, file_name='a.pdf', status='active')
        self.client = Client()
        self.client.force_login(self.admin)

    def test_get_does_not_approve_user(self):
        resp = self.client.get(f'/admin/accounts/user/{self.user.pk}/approve/')
        self.assertEqual(resp.status_code, 405)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_approved)

    def test_post_approves_user(self):
        resp = self.client.post(f'/admin/accounts/user/{self.user.pk}/approve/')
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_approved)

    def test_get_does_not_reject_document(self):
        resp = self.client.get(f'/admin/accounts/servicedocument/{self.doc.pk}/reject/')
        self.assertEqual(resp.status_code, 405)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'active')

    def test_post_rejects_document(self):
        resp = self.client.post(f'/admin/accounts/servicedocument/{self.doc.pk}/reject/')
        self.assertEqual(resp.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, 'rejected')

    def test_get_does_not_mark_downloaded(self):
        resp = self.client.get(f'/admin/accounts/servicedocument/{self.doc.pk}/download/')
        self.assertEqual(resp.status_code, 405)
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.is_downloaded)
