from unittest import mock

from django.core.checks import Warning
from django.test import SimpleTestCase

from .checks import pdf_engine_installed


class PdfEngineCheckTests(SimpleTestCase):
    def test_no_warning_when_xhtml2pdf_is_installed(self):
        self.assertEqual(pdf_engine_installed(None), [])

    def test_warns_with_the_fix_when_it_is_missing(self):
        with mock.patch('accounts.checks.importlib.util.find_spec', return_value=None):
            found = pdf_engine_installed(None)
        self.assertEqual(len(found), 1)
        self.assertIsInstance(found[0], Warning)
        self.assertEqual(found[0].id, 'accounts.W001')
        self.assertIn('pip install -r requirements.txt', found[0].hint)

    def test_the_check_is_registered_with_django(self):
        from django.core.checks.registry import registry
        self.assertIn(pdf_engine_installed, registry.get_checks())
