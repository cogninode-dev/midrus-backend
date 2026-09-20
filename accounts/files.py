"""Safe handling of client-uploaded files.

Uploads (tax documents, invoice PDFs) are private, so they are never served
from a public /media/ path. Instead every API response carries a short-lived
signed URL, and files are streamed with headers that stop the browser from
executing anything an attacker managed to upload.
"""
import os
import re

from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils.http import content_disposition_header
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

SIGNING_SALT = 'midrus.file-download'

# extension -> (content types the browser may claim, magic-byte prefixes)
_ALLOWED_UPLOADS = {
    '.pdf':  ({'application/pdf'}, (b'%PDF-',)),
    '.png':  ({'image/png'}, (b'\x89PNG\r\n\x1a\n',)),
    '.jpg':  ({'image/jpeg'}, (b'\xff\xd8\xff',)),
    '.jpeg': ({'image/jpeg'}, (b'\xff\xd8\xff',)),
    '.doc':  ({'application/msword'}, (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',)),
    '.docx': (
        {'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},
        (b'PK\x03\x04',),
    ),
}

# Types that are safe to render inline in a browser.
_INLINE_TYPES = {
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


def clean_filename(name: str) -> str:
    """Drop any path, control characters and over-long names."""
    name = os.path.basename((name or '').replace('\\', '/'))
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()
    stem, ext = os.path.splitext(name)
    return (stem[:200] + ext[:20]) if name else ''


def validate_upload(uploaded_file) -> str | None:
    """Return an error message for a bad upload, or None if it looks fine.

    The browser-supplied Content-Type is trivially spoofable, so the extension
    must be allowed, agree with the claimed type, and match the file's magic
    bytes.
    """
    if uploaded_file.size > MAX_UPLOAD_BYTES:
        return 'File too large. Maximum size is 20 MB.'
    ext = os.path.splitext(uploaded_file.name or '')[1].lower()
    rule = _ALLOWED_UPLOADS.get(ext)
    if rule is None or uploaded_file.content_type not in rule[0]:
        return 'Unsupported file type. Allowed: PDF, DOC, DOCX, JPG, PNG.'
    uploaded_file.seek(0)
    head = uploaded_file.read(8)
    uploaded_file.seek(0)
    if not any(head.startswith(magic) for magic in rule[1]):
        return 'The file content does not match its type.'
    return None


def safe_file_response(fieldfile, filename: str = '') -> FileResponse:
    """Stream a stored file with headers that neutralise hostile content."""
    filename = clean_filename(filename) or os.path.basename(fieldfile.name)
    ext = os.path.splitext(filename)[1].lower()
    inline_type = _INLINE_TYPES.get(ext)

    response = FileResponse(
        fieldfile.open('rb'),
        content_type=inline_type or 'application/octet-stream',
    )
    response['Content-Disposition'] = content_disposition_header(
        as_attachment=inline_type is None, filename=filename,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    if inline_type and inline_type != 'application/pdf':
        # Images: nothing but the picture itself may run. (Chrome's PDF viewer
        # does not work under a sandbox policy, so PDFs skip this.)
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


# ─── Signed download links ───────────────────────────────────────────────────

def make_file_url(request, kind: str, pk: int) -> str:
    """A time-limited absolute URL for a stored file (kind: 'doc' | 'invoice')."""
    token = signing.dumps({'k': kind, 'id': pk}, salt=SIGNING_SALT)
    path = reverse('file-download', args=[token])
    return request.build_absolute_uri(path) if request else path


class FileThrottle(AnonRateThrottle):
    scope = 'files'


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([FileThrottle])
def file_download(request, token):
    from .models import Invoice, ServiceDocument

    try:
        data = signing.loads(
            token, salt=SIGNING_SALT, max_age=settings.FILE_URL_TTL_SECONDS,
        )
    except signing.BadSignature:  # includes SignatureExpired
        raise Http404('This link is invalid or has expired.')

    if data.get('k') == 'doc':
        doc = ServiceDocument.objects.filter(pk=data.get('id')).first()
        fieldfile, name = (doc.file, doc.file_name) if doc else (None, '')
    elif data.get('k') == 'invoice':
        inv = Invoice.objects.filter(pk=data.get('id')).first()
        fieldfile, name = (
            (inv.uploaded_pdf, f'{inv.invoice_number.replace("/", "-")}.pdf')
            if inv else (None, '')
        )
    else:
        raise Http404

    if not fieldfile:
        raise Http404
    try:
        return safe_file_response(fieldfile, name)
    except FileNotFoundError:
        raise Http404
