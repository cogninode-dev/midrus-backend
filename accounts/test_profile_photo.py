"""Customers can upload, replace and remove a profile photo."""
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import User

API = '/api/auth'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def _photo(name='me.png', data=PNG, content_type='image/png'):
    return SimpleUploadedFile(name, data, content_type=content_type)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class ProfilePhotoTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='c@example.com', password='Pw-123456', name='Cust',
            is_email_verified=True, is_approved=True,
        )
        self.client.force_authenticate(self.user)

    def test_upload_sets_a_photo_url(self):
        r = self.client.post(f'{API}/profile/photo/', {'photo': _photo()}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['user']['photo_url'])
        self.assertTrue(self.client.get(f'{API}/me/').data['photo_url'])

    def test_photo_link_serves_the_image(self):
        self.client.post(f'{API}/profile/photo/', {'photo': _photo()}, format='multipart')
        url = self.client.get(f'{API}/me/').data['photo_url']
        self.client.force_authenticate(None)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/png')

    def test_rejects_non_images(self):
        r = self.client.post(
            f'{API}/profile/photo/',
            {'photo': _photo('x.pdf', b'%PDF-1.4 hi', 'application/pdf')},
            format='multipart',
        )
        self.assertEqual(r.status_code, 400)

    def test_rejects_a_fake_image(self):
        r = self.client.post(
            f'{API}/profile/photo/',
            {'photo': _photo('x.png', b'not really a png at all')},
            format='multipart',
        )
        self.assertEqual(r.status_code, 400)

    def test_rejects_oversized_photo(self):
        r = self.client.post(
            f'{API}/profile/photo/',
            {'photo': _photo(data=PNG + b'\x00' * (5 * 1024 * 1024))},
            format='multipart',
        )
        self.assertEqual(r.status_code, 400)

    def test_requires_a_file(self):
        self.assertEqual(self.client.post(f'{API}/profile/photo/', {}, format='multipart').status_code, 400)

    def test_remove(self):
        self.client.post(f'{API}/profile/photo/', {'photo': _photo()}, format='multipart')
        r = self.client.delete(f'{API}/profile/photo/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['user']['photo_url'])

    def test_login_required(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'{API}/profile/photo/', {'photo': _photo()}, format='multipart').status_code, 401)

    def test_photo_cannot_be_set_through_profile_update(self):
        r = self.client.patch(f'{API}/profile/update/', {'photo_url': 'http://evil'}, format='json')
        self.assertIsNone(r.data['user']['photo_url'])
