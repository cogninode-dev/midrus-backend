"""Excel (.xls, .xlsx) and CSV uploads: accepted when they really are that kind
of file, refused when they are something else wearing the extension."""
import io
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .files import UPLOAD_TYPES_LABEL, make_file_url, validate_upload
from .models import Service, ServiceDocument, User

API = '/api/auth'

XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
OLE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def make_xlsx(with_workbook=True) -> bytes:
    """A minimal but genuine-looking workbook: a zip holding xl/workbook.xml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        if with_workbook:
            z.writestr('xl/workbook.xml', '<workbook/>')
        else:
            z.writestr('word/document.xml', '<document/>')  # a .docx, in fact
    return buf.getvalue()


XLSX = make_xlsx()
XLS = OLE + b'\x00' * 512
CSV = 'Date,Service,Amount\n2026-09-01,GST Return,"2,500"\n'.encode()


@override_settings()
class SpreadsheetUploadTests(APITestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)

        original_get = self.client.get

        def get(*args, **kwargs):
            response = original_get(*args, **kwargs)
            self.addCleanup(response.close)
            return response

        self.client.get = get

        self.user = User.objects.create_user(
            'client@example.com', 'Pw-client-123', 'Client One',
            is_email_verified=True, is_approved=True,
        )
        self.service = Service.objects.create(user=self.user, name='GST Return', charge='1')
        self.client.force_authenticate(self.user)

    def upload(self, name, content, ctype):
        return self.client.post(
            f'{API}/services/{self.service.pk}/invoices/',
            {'file': SimpleUploadedFile(name, content, content_type=ctype)},
            format='multipart',
        )

    # ── accepted ─────────────────────────────────────────────────────────────

    def test_real_spreadsheets_are_accepted(self):
        cases = [
            ('accounts.xlsx', XLSX, XLSX_TYPE),
            ('old-format.xls', XLS, 'application/vnd.ms-excel'),
            ('ledger.csv', CSV, 'text/csv'),
        ]
        for name, content, ctype in cases:
            r = self.upload(name, content, ctype)
            self.assertEqual(r.status_code, 201, f'{name}: {r.data}')
            self.assertEqual(r.data['file_name'], name)
        self.assertEqual(ServiceDocument.objects.count(), 3)

    def test_the_mobile_app_sends_a_generic_type_and_that_works_too(self):
        for name, content in [('a.xlsx', XLSX), ('b.xls', XLS), ('c.csv', CSV)]:
            r = self.upload(name, content, 'application/octet-stream')
            self.assertEqual(r.status_code, 201, f'{name}: {r.data}')

    def test_windows_reports_csv_as_ms_excel_and_that_is_fine(self):
        self.assertEqual(self.upload('ledger.csv', CSV, 'application/vnd.ms-excel').status_code, 201)

    def test_csv_in_the_encodings_indian_users_actually_have(self):
        samples = {
            'utf8.csv': 'नाम,राशि\nराम,₹1,000\n'.encode('utf-8'),
            'excel-bom.csv': b'\xef\xbb\xbf' + 'Name,Amount\nAsha,100\n'.encode('utf-8'),
            # Bytes above 0x7F (é, curly quotes) are normal in a Windows CSV.
            'windows-1252.csv': 'Name,Note\nAsha,café “quoted”\n'.encode('cp1252'),
            'crlf-and-tabs.csv': b'a\tb\r\n1\t2\r\n',
        }
        for name, content in samples.items():
            r = self.upload(name, content, 'text/csv')
            self.assertEqual(r.status_code, 201, f'{name}: {r.data}')

    def test_extensions_are_case_insensitive(self):
        for name, content in [('A.XLSX', XLSX), ('B.Xls', XLS), ('C.CSV', CSV)]:
            self.assertEqual(self.upload(name, content, 'application/octet-stream').status_code, 201, name)

    # ── refused ──────────────────────────────────────────────────────────────

    def test_a_zip_or_word_file_renamed_to_xlsx_is_refused(self):
        for label, content in [
            ('a .docx renamed', make_xlsx(with_workbook=False)),
            ('a random zip', b'PK\x03\x04' + b'\x00' * 40),
            ('a truncated xlsx', XLSX[: len(XLSX) // 2]),
        ]:
            r = self.upload('accounts.xlsx', content, XLSX_TYPE)
            self.assertEqual(r.status_code, 400, label)
            self.assertIn('does not match', r.data['error'], label)

    def test_programs_and_binaries_renamed_to_csv_are_refused(self):
        for label, content in [
            ('a Windows program', b'MZ\x90\x00\x03\x00\x00\x00'),
            ('a PDF', b'%PDF-1.4\n\x00\x01\x02'),
            ('an Excel file', XLS),
            ('UTF-16 text (full of NULs)', 'a,b\n'.encode('utf-16')),
            ('control characters', b'a,b\x01\x02\x03\n'),
        ]:
            r = self.upload('data.csv', content, 'text/csv')
            self.assertEqual(r.status_code, 400, label)

    def test_a_pdf_or_picture_renamed_to_xls_is_refused(self):
        self.assertEqual(self.upload('a.xls', b'%PDF-1.4 x', 'application/vnd.ms-excel').status_code, 400)
        self.assertEqual(self.upload('a.xls', CSV, 'application/vnd.ms-excel').status_code, 400)

    def test_the_claimed_type_must_agree_with_the_extension(self):
        self.assertEqual(self.upload('a.xlsx', XLSX, 'image/png').status_code, 400)
        self.assertEqual(self.upload('a.csv', CSV, 'application/pdf').status_code, 400)
        self.assertEqual(self.upload('a.xls', XLS, XLSX_TYPE).status_code, 400)

    def test_an_empty_file_is_refused(self):
        r = self.upload('empty.csv', b'', 'text/csv')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['error'], 'The file is empty.')

    def test_other_spreadsheet_formats_are_still_not_allowed(self):
        # Macro-enabled and binary workbooks can carry code; ODS is not needed.
        for name in ['macros.xlsm', 'big.xlsb', 'sheet.ods', 'data.tsv', 'notes.txt']:
            r = self.upload(name, XLSX, 'application/octet-stream')
            self.assertEqual(r.status_code, 400, name)
            self.assertIn('Unsupported file type', r.data['error'], name)
        self.assertEqual(ServiceDocument.objects.count(), 0)

    def test_the_error_lists_what_is_allowed(self):
        r = self.upload('shell.exe', b'MZ\x90\x00', 'application/octet-stream')
        self.assertEqual(
            r.data['error'], f'Unsupported file type. Allowed: {UPLOAD_TYPES_LABEL}.',
        )
        for kind in ('XLS', 'XLSX', 'CSV'):
            self.assertIn(kind, r.data['error'])

    def test_existing_types_still_work_and_still_reject_disguises(self):
        pdf = b'%PDF-1.4 real'
        self.assertEqual(self.upload('a.pdf', pdf, 'application/pdf').status_code, 201)
        self.assertEqual(self.upload('a.docx', b'PK\x03\x04' + b'\x00' * 20,
                                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                                     ).status_code, 201)
        self.assertEqual(self.upload('fake.pdf', b'<html>', 'application/pdf').status_code, 400)

    def test_replacing_a_rejected_document_uses_the_same_rules(self):
        ok = self.client.post(
            f'{API}/services/{self.service.pk}/invoices/',
            {'file': SimpleUploadedFile('fix.xlsx', XLSX, content_type=XLSX_TYPE), 'is_reupload': 'true'},
            format='multipart',
        )
        self.assertEqual(ok.status_code, 201)
        self.assertTrue(ok.data['is_reupload'])
        bad = self.client.post(
            f'{API}/services/{self.service.pk}/invoices/',
            {'file': SimpleUploadedFile('fix.xlsx', b'PK\x03\x04junk', content_type=XLSX_TYPE), 'is_reupload': 'true'},
            format='multipart',
        )
        self.assertEqual(bad.status_code, 400)

    # ── how they are served ──────────────────────────────────────────────────

    def test_spreadsheets_only_ever_download_and_are_never_shown_in_the_browser(self):
        self.client.force_authenticate(None)
        for name, content, ctype in [
            ('accounts.xlsx', XLSX, XLSX_TYPE),
            ('old.xls', XLS, 'application/vnd.ms-excel'),
            ('ledger.csv', CSV, 'text/csv'),
        ]:
            doc = ServiceDocument(service=self.service, file_name=name)
            doc.file.save(name, io.BytesIO(content), save=True)
            r = self.client.get(make_file_url(None, 'doc', doc.pk))
            self.assertEqual(r.status_code, 200, name)
            self.assertIn('attachment', r['Content-Disposition'], name)
            self.assertIn(name, r['Content-Disposition'], name)
            self.assertEqual(r['Content-Type'], 'application/octet-stream', name)
            self.assertEqual(r['X-Content-Type-Options'], 'nosniff', name)
            self.assertEqual(b''.join(r.streaming_content), content, name)

    def test_html_disguised_as_csv_can_never_run_in_the_browser(self):
        """Plain text passes the CSV check, so the guarantee is in how it is
        served: as an opaque download, with sniffing switched off."""
        page = b'<html><script>alert(1)</script></html>'
        self.assertEqual(self.upload('page.csv', page, 'text/csv').status_code, 201)
        doc = ServiceDocument.objects.get(file_name='page.csv')
        self.client.force_authenticate(None)
        r = self.client.get(make_file_url(None, 'doc', doc.pk))
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertEqual(r['Content-Type'], 'application/octet-stream')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')


class ValidateUploadUnitTests(APITestCase):
    def check(self, name, content, ctype='application/octet-stream'):
        return validate_upload(SimpleUploadedFile(name, content, content_type=ctype))

    def test_the_file_position_is_left_at_the_start_for_saving(self):
        f = SimpleUploadedFile('a.xlsx', XLSX, content_type=XLSX_TYPE)
        self.assertIsNone(validate_upload(f))
        self.assertEqual(f.read(), XLSX)  # nothing was consumed by the checks
        f = SimpleUploadedFile('a.csv', CSV, content_type='text/csv')
        self.assertIsNone(validate_upload(f))
        self.assertEqual(f.read(), CSV)

    def test_a_large_valid_csv_is_only_sampled(self):
        big = b'a,b\n' + b'1,2\n' * 500_000
        self.assertIsNone(self.check('big.csv', big, 'text/csv'))
        # A binary byte far past the sample is not looked for (cheap check).
        self.assertIsNone(self.check('late.csv', b'a,b\n' * 5000 + b'\x00', 'text/csv'))
