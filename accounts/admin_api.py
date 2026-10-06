"""Staff-only REST API powering the in-app admin panel.

Mirrors what the Django admin site does (approve users, manage services,
review documents, read contact messages, create invoices) so the mobile
app's admin section never needs the web admin. Every view requires an
authenticated, active staff user.
"""
import datetime
import logging
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from .emails import send_approved_email, send_invoice_email
from .files import clean_filename, make_file_url, validate_upload
from .notifications import notify_invoice_created
from .models import (
    ContactMessage, Invoice, InvoiceItem, Service, ServiceDocument, User,
)
from .security import get_user_by_email
from .serializers import BillingInvoiceSerializer

logger = logging.getLogger(__name__)

STAFF = [IsAuthenticated, IsAdminUser]

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


# ─── helpers ─────────────────────────────────────────────────────────────────

def _page(request):
    try:
        limit = max(1, min(int(request.GET.get('limit', DEFAULT_LIMIT)), MAX_LIMIT))
        offset = max(0, int(request.GET.get('offset', 0)))
    except ValueError:
        limit, offset = DEFAULT_LIMIT, 0
    return limit, offset


def _paginated(request, queryset, serialize):
    limit, offset = _page(request)
    total = queryset.count()
    rows = list(queryset[offset:offset + limit])
    return Response({
        'count': total,
        'next_offset': offset + limit if offset + limit < total else None,
        'results': [serialize(r) for r in rows],
    })


def _err(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'error': message}, status=code)


def _user_row(u, request=None):
    return {
        'id': u.id,
        'email': u.email,
        'name': u.name,
        'company': u.company,
        'phone': u.phone,
        'address': u.address,
        'website': u.website,
        'tax_id': u.tax_id,
        'gst_number': u.gst_number,
        'photo_url': make_file_url(request, 'avatar', u.pk) if u.photo else None,
        'is_approved': u.is_approved,
        'is_active': u.is_active,
        'is_staff': u.is_staff,
        'is_email_verified': u.is_email_verified,
        'services_count': getattr(u, 'services_count', None),
        'created_at': u.created_at,
    }


def _service_row(s):
    return {
        'id': s.id,
        'name': s.name,
        'description': s.description,
        'charge': s.charge,
        'status': s.status,
        'due_date': s.due_date,
        'client_id': s.user_id,
        'client_name': s.user.name,
        'client_email': s.user.email,
        'client_company': s.user.company,
        'created_at': s.created_at,
    }


def _document_row(d, request):
    return {
        'id': d.id,
        'file_name': d.file_name,
        'file_url': make_file_url(request, 'doc', d.pk) if d.file else None,
        'uploaded_at': d.uploaded_at,
        'is_downloaded': d.is_downloaded,
        'status': d.status,
        'is_reupload': d.is_reupload,
        'service_id': d.service_id,
        'service_name': d.service.name,
        'client_name': d.service.user.name,
        'client_email': d.service.user.email,
    }


def _message_row(m):
    return {
        'id': m.id,
        'name': m.name,
        'email': m.email,
        'phone': m.phone,
        'company': m.company,
        'message': m.message,
        'is_read': m.is_read,
        'submitted_at': m.submitted_at,
    }


# ─── overview ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def overview(request):
    return Response({
        'users_total': User.objects.filter(is_staff=False, is_active=True).count(),
        'users_pending_approval': User.objects.filter(
            is_staff=False, is_active=True, is_email_verified=True, is_approved=False,
        ).count(),
        'services_requested': Service.objects.filter(status='Requested').count(),
        'services_active': Service.objects.filter(status='Active').count(),
        'services_pending': Service.objects.filter(status='Pending').count(),
        'documents_to_review': ServiceDocument.objects.filter(
            status='active', is_downloaded=False,
        ).count(),
        'documents_reuploaded': ServiceDocument.objects.filter(
            status='active', is_reupload=True,
        ).count(),
        'messages_unread': ContactMessage.objects.filter(is_read=False).count(),
        'invoices_total': Invoice.objects.count(),
        'invoices_unpaid': Invoice.objects.filter(payment_status='pending').count(),
    })


# ─── users ───────────────────────────────────────────────────────────────────

CLIENT_TEXT_FIELDS = {
    'name': 150, 'phone': 20, 'company': 150, 'address': 2000,
    'website': 200, 'tax_id': 50, 'gst_number': 50,
}


def _clean_client_fields(data, *, require_name):
    """Validated profile fields from a request, or an error string."""
    out = {}
    for field, limit in CLIENT_TEXT_FIELDS.items():
        if field not in data:
            continue
        value = ' '.join(str(data[field] or '').split()) if field != 'address' else str(data[field] or '').strip()
        if len(value) > limit:
            return None, f'{field.replace("_", " ").capitalize()} is too long (max {limit} characters).'
        out[field] = value
    if require_name and not out.get('name'):
        return None, 'Name is required.'
    if 'name' in out and not out['name']:
        return None, 'Name cannot be empty.'
    if out.get('website') and not out['website'].lower().startswith(('http://', 'https://')):
        out['website'] = 'https://' + out['website']
    return out, None


def _staff_target(pk):
    """A client account the app may change. Staff accounts are managed in the
    web admin only, so a phone can never edit or delete another admin."""
    return get_object_or_404(User, pk=pk, is_staff=False, is_superuser=False)


def _create_user(request):
    data = request.data
    email = str(data.get('email') or '').strip().lower()
    try:
        validate_email(email)
    except DjangoValidationError:
        return _err('Enter a valid email address.')
    if get_user_by_email(email) is not None:
        return _err('An account with this email already exists.')
    password = data.get('password')
    if not isinstance(password, str) or len(password) < 6:
        return _err('Password must be at least 6 characters.')
    fields, problem = _clean_client_fields(data, require_name=True)
    if problem:
        return _err(problem)
    approved = data.get('is_approved', True)
    if not isinstance(approved, bool):
        return _err('"is_approved" must be true or false.')
    user = User.objects.create_user(
        email=email, password=password,
        is_active=True, is_email_verified=True, is_approved=approved,
        **fields,
    )
    return Response(_user_row(user, request), status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes(STAFF)
def users(request):
    if request.method == 'POST':
        return _create_user(request)
    if request.GET.get('filter') == 'inactive':
        # Deactivated clients (so they can be switched back on). Accounts the
        # customer erased themselves are anonymised and stay hidden.
        qs = User.objects.filter(is_staff=False, is_active=False).exclude(
            email__endswith='@deleted.invalid',
        ).annotate(services_count=Count('services'))
        return _paginated(request, qs.order_by('-created_at'), lambda u: _user_row(u, request))
    qs = User.objects.filter(is_staff=False, is_active=True).annotate(services_count=Count('services'))
    flt = request.GET.get('filter', 'all')
    if flt == 'pending':
        qs = qs.filter(is_email_verified=True, is_approved=False)
    elif flt == 'approved':
        qs = qs.filter(is_approved=True)
    elif flt == 'unverified':
        qs = qs.filter(is_email_verified=False)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(company__icontains=q),
        )
    return _paginated(request, qs.order_by('-created_at'), lambda u: _user_row(u, request))


@api_view(['POST'])
@permission_classes(STAFF)
def user_approval(request, pk):
    user = get_object_or_404(User, pk=pk)
    approved = request.data.get('approved')
    if not isinstance(approved, bool):
        return _err('"approved" must be true or false.')
    if approved:
        if not user.is_email_verified:
            return _err('This user has not verified their email yet.')
        was_approved = user.is_approved
        user.is_approved = True
        user.save(update_fields=['is_approved'])
        if not was_approved:
            try:
                send_approved_email(user)
            except Exception as exc:  # approval must not fail on SMTP trouble
                logger.error('Approval email to %s failed: %s', user.email, exc)
    else:
        if user.is_staff:
            return _err('Staff accounts cannot have approval revoked.')
        user.is_approved = False
        user.save(update_fields=['is_approved'])
    return Response(_user_row(user, request))


def _update_user(request, pk):
    user = _staff_target(pk)
    data = request.data
    fields, problem = _clean_client_fields(data, require_name=False)
    if problem:
        return _err(problem)
    for field, value in fields.items():
        setattr(user, field, value)
    changed = list(fields)
    if 'is_active' in data:
        if not isinstance(data['is_active'], bool):
            return _err('"is_active" must be true or false.')
        user.is_active = data['is_active']
        changed.append('is_active')
    if 'email' in data:
        email = str(data['email'] or '').strip().lower()
        try:
            validate_email(email)
        except DjangoValidationError:
            return _err('Enter a valid email address.')
        other = get_user_by_email(email)
        if other is not None and other.pk != user.pk:
            return _err('An account with this email already exists.')
        user.email = email
        changed.append('email')
    if 'password' in data:
        password = data['password']
        if not isinstance(password, str) or len(password) < 6:
            return _err('Password must be at least 6 characters.')
        user.set_password(password)
        changed.append('password')
    if changed:
        user.save(update_fields=[*changed, 'updated_at'])
    return Response(_user_row(user, request))


def _delete_user(request, pk):
    """Permanently removes the client with their services, documents and
    invoices (what the Django admin does too). Files are cleaned up after the
    database commit."""
    user = _staff_target(pk)
    with transaction.atomic():
        user.delete()  # post_delete signals remove the photo, documents and PDFs
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes(STAFF)
def user_detail(request, pk):
    """Everything about one client on a single screen: profile, services with
    their documents, invoices with payment status, and payment totals. PATCH
    edits the profile; DELETE removes the client."""
    if request.method == 'PATCH':
        return _update_user(request, pk)
    if request.method == 'DELETE':
        return _delete_user(request, pk)
    user = get_object_or_404(
        User.objects.annotate(services_count=Count('services', distinct=True)),
        pk=pk, is_staff=False,
    )
    services = list(
        Service.objects.filter(user=user)
        .select_related('user')
        .prefetch_related('invoices')  # the related name for a service's documents
    )
    invoices = list(
        Invoice.objects.filter(user=user)
        .select_related('user')
        .prefetch_related('items')
        .order_by('-created_at')
    )

    def money(statuses):
        total = sum((i.total for i in invoices if i.payment_status in statuses), Decimal('0'))
        return f'{total:.2f}'

    documents = 0
    service_rows = []
    for svc in services:
        docs = list(svc.invoices.all())
        documents += len(docs)
        service_rows.append({
            **_service_row(svc),
            'documents': [_document_row(d, request) for d in docs],
        })

    return Response({
        'user': _user_row(user, request),
        'summary': {
            'invoices_count': len(invoices),
            'billed': money({'pending', 'processing', 'success', 'failed'}),
            'paid': money({'success'}),
            'processing': money({'processing'}),
            'outstanding': money({'pending', 'failed'}),
            'documents_count': documents,
        },
        'services': service_rows,
        'invoices': [_invoice_json(i, request) for i in invoices],
    })


# ─── services ────────────────────────────────────────────────────────────────

def _create_service(request):
    data = request.data
    try:
        client = User.objects.filter(pk=int(data.get('client_id')), is_staff=False).first()
    except (TypeError, ValueError):
        client = None
    if client is None:
        return _err('Choose a client for this service.')
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 200:
        return _err('Name is required (max 200 characters).')
    charge = str(data.get('charge') or '').strip()
    if len(charge) > 50:
        return _err('Charge is too long (max 50 characters).')
    allowed = {c[0] for c in Service.STATUS_CHOICES}
    state = data.get('status', 'Active')
    if state not in allowed:
        return _err(f'Status must be one of: {", ".join(sorted(allowed))}.')
    due = None
    if data.get('due_date') not in (None, ''):
        try:
            due = datetime.date.fromisoformat(str(data['due_date']))
        except ValueError:
            return _err('Due date must be YYYY-MM-DD.')
    service = Service.objects.create(
        user=client, name=name, charge=charge, status=state, due_date=due,
        description=str(data.get('description') or '').strip(),
    )
    return Response(_service_row(service), status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes(STAFF)
def services(request):
    if request.method == 'POST':
        return _create_service(request)
    qs = Service.objects.select_related('user')
    st = request.GET.get('status', '')
    if st:
        qs = qs.filter(status=st)
    client = request.GET.get('client', '').strip()
    if client.isdigit():
        qs = qs.filter(user_id=int(client))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(user__name__icontains=q)
            | Q(user__email__icontains=q) | Q(user__company__icontains=q),
        )
    return _paginated(request, qs.order_by('-created_at'), _service_row)


@api_view(['PATCH', 'DELETE'])
@permission_classes(STAFF)
def service_update(request, pk):
    service = get_object_or_404(Service.objects.select_related('user'), pk=pk)
    if request.method == 'DELETE':
        service.delete()  # its documents go with it; files are removed after commit
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = request.data
    allowed = {c[0] for c in Service.STATUS_CHOICES}

    if 'status' in data:
        if data['status'] not in allowed:
            return _err(f'Status must be one of: {", ".join(sorted(allowed))}.')
        service.status = data['status']
    if 'charge' in data:
        charge = str(data['charge']).strip()
        if len(charge) > 50:
            return _err('Charge is too long (max 50 characters).')
        service.charge = charge
    if 'name' in data:
        name = str(data['name']).strip()
        if not name or len(name) > 200:
            return _err('Name is required (max 200 characters).')
        service.name = name
    if 'description' in data:
        service.description = str(data['description']).strip()
    if 'due_date' in data:
        raw = data['due_date']
        if raw in (None, ''):
            service.due_date = None
        else:
            try:
                service.due_date = datetime.date.fromisoformat(str(raw))
            except ValueError:
                return _err('Due date must be YYYY-MM-DD.')
    service.save()
    return Response(_service_row(service))


# ─── documents ───────────────────────────────────────────────────────────────

def _upload_document(request):
    try:
        service = Service.objects.select_related('user').filter(
            pk=int(request.data.get('service_id')),
        ).first()
    except (TypeError, ValueError):
        service = None
    if service is None:
        return _err('Choose a service for this document.')
    uploaded = request.FILES.get('file')
    if uploaded is None:
        return _err('file is required.')
    problem = validate_upload(uploaded)
    if problem:
        return _err(problem)
    name = clean_filename(uploaded.name)
    if not name:
        return _err('file is required.')
    doc = ServiceDocument.objects.create(service=service, file_name=name, file=uploaded)
    return Response(_document_row(doc, request), status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes(STAFF)
def documents(request):
    if request.method == 'POST':
        return _upload_document(request)
    qs = ServiceDocument.objects.select_related('service', 'service__user')
    flt = request.GET.get('filter', 'all')
    if flt == 'pending':
        qs = qs.filter(status='active', is_downloaded=False)
    elif flt == 'downloaded':
        qs = qs.filter(status='active', is_downloaded=True)
    elif flt == 'rejected':
        qs = qs.filter(status='rejected')
    elif flt == 'reupload':
        qs = qs.filter(is_reupload=True)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(file_name__icontains=q) | Q(service__name__icontains=q)
            | Q(service__user__email__icontains=q) | Q(service__user__name__icontains=q),
        )
    return _paginated(request, qs.order_by('-uploaded_at'), lambda d: _document_row(d, request))


@api_view(['DELETE'])
@permission_classes(STAFF)
def document_delete(request, pk):
    get_object_or_404(ServiceDocument, pk=pk).delete()  # file removed after commit
    return Response(status=status.HTTP_204_NO_CONTENT)


def _document_action(request, pk, **fields):
    doc = get_object_or_404(
        ServiceDocument.objects.select_related('service', 'service__user'), pk=pk,
    )
    for k, v in fields.items():
        setattr(doc, k, v)
    doc.save(update_fields=list(fields))
    return Response(_document_row(doc, request))


@api_view(['POST'])
@permission_classes(STAFF)
def document_reject(request, pk):
    return _document_action(request, pk, status='rejected')


@api_view(['POST'])
@permission_classes(STAFF)
def document_restore(request, pk):
    return _document_action(request, pk, status='active')


@api_view(['POST'])
@permission_classes(STAFF)
def document_mark_downloaded(request, pk):
    return _document_action(request, pk, is_downloaded=True)


# ─── contact messages ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def messages(request):
    qs = ContactMessage.objects.all()
    flt = request.GET.get('filter', 'all')
    if flt == 'unread':
        qs = qs.filter(is_read=False)
    elif flt == 'read':
        qs = qs.filter(is_read=True)
    return _paginated(request, qs.order_by('-submitted_at'), _message_row)


@api_view(['PATCH', 'DELETE'])
@permission_classes(STAFF)
def message_update(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    if request.method == 'DELETE':
        msg.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    is_read = request.data.get('is_read')
    if not isinstance(is_read, bool):
        return _err('"is_read" must be true or false.')
    msg.is_read = is_read
    msg.save(update_fields=['is_read'])
    return Response(_message_row(msg))


# ─── invoices ────────────────────────────────────────────────────────────────

def _format_address(user):
    parts = [user.name.upper()]
    if user.company:
        parts.append(user.company)
    if user.address:
        parts.append(user.address)
    if user.gst_number:
        parts.append(f'GSTIN/UIN : {user.gst_number}')
    return '\n'.join(p for p in parts if p)


def _invoice_json(invoice, request):
    return BillingInvoiceSerializer(invoice, context={'request': request}).data


@api_view(['GET', 'POST'])
@permission_classes(STAFF)
def invoices(request):
    if request.method == 'GET':
        qs = Invoice.objects.select_related('user').prefetch_related('items')
        payment = request.GET.get('payment_status', 'all')
        if payment in {value for value, _ in Invoice.PAYMENT_STATUS_CHOICES}:
            qs = qs.filter(payment_status=payment)
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(invoice_number__icontains=q) | Q(user__name__icontains=q)
                | Q(user__email__icontains=q) | Q(user__company__icontains=q),
            )
        return _paginated(
            request, qs.order_by('-created_at'), lambda i: _invoice_json(i, request),
        )
    return _invoice_create(request)


@api_view(['POST'])
@permission_classes(STAFF)
def invoice_payment_status(request, pk):
    """Staff records the outcome of a customer's UPI payment; the customer
    sees it on the Payments page."""
    invoice = get_object_or_404(
        Invoice.objects.select_related('user').prefetch_related('items'), pk=pk,
    )
    new_status = request.data.get('payment_status')
    valid = {value for value, _ in Invoice.PAYMENT_STATUS_CHOICES}
    if new_status not in valid:
        return _err(f'Payment status must be one of: {", ".join(sorted(valid))}.')
    invoice.payment_status = new_status
    invoice.save(update_fields=['payment_status'])
    return Response(_invoice_json(invoice, request))


def _dec(value, field, minimum=Decimal('0')):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{field} must be a number.')
    if not d.is_finite() or d <= minimum:
        raise ValueError(f'{field} must be greater than {minimum}.')
    return d


def _parse_invoice_items(raw_items):
    """Validated InvoiceItem objects (unsaved) from request data, or an error."""
    if not isinstance(raw_items, list) or not raw_items:
        return None, 'Add at least one service line.'
    if len(raw_items) > 50:
        return None, 'An invoice can have at most 50 lines.'

    items = []
    for idx, raw in enumerate(raw_items, start=1):
        label = f'Line {idx}'
        if not isinstance(raw, dict):
            return None, f'{label} is invalid.'
        name = str(raw.get('service_name', '')).strip()
        if not name:
            return None, f'{label}: service name is required.'
        if len(name) > 200:
            return None, f'{label}: service name is too long (max 200).'
        try:
            month = int(raw.get('month'))
            year = int(raw.get('year'))
        except (TypeError, ValueError):
            return None, f'{label}: month and year are required.'
        if not 1 <= month <= 12:
            return None, f'{label}: month must be between 1 and 12.'
        if not 2000 <= year <= 2100:
            return None, f'{label}: year must be between 2000 and 2100.'
        try:
            amount = _dec(raw.get('amount'), f'{label}: amount')
            quantity = _dec(raw.get('quantity', 1), f'{label}: quantity')
        except ValueError as exc:
            return None, str(exc)
        if amount >= Decimal('10') ** 10:
            return None, f'{label}: amount is too large.'
        item = InvoiceItem(
            service_name=name, month=month, year=year,
            hsn_code=str(raw.get('hsn_code') or '998311').strip()[:20],
            quantity=quantity,
            per=str(raw.get('per') or 'Month').strip()[:20],
            amount=amount,
        )
        # Editing: a line that names an existing id is updated in place, and
        # keeps its quantity / unit unless the request sets them.
        item.existing_id = raw.get('id') if isinstance(raw.get('id'), int) else None
        item.sets_quantity = 'quantity' in raw
        item.sets_per = 'per' in raw
        items.append(item)
    return items, None


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes(STAFF)
def invoice_detail(request, pk):
    # No prefetch: an edit changes the lines and then re-totals them, which
    # must read the rows as they are now, not a cached copy.
    invoice = get_object_or_404(Invoice.objects.select_related('user'), pk=pk)
    if request.method == 'GET':
        return Response(_invoice_json(invoice, request))
    if request.method == 'DELETE':
        invoice.delete()  # its items go with it; an uploaded PDF is removed after commit
        return Response(status=status.HTTP_204_NO_CONTENT)

    data = request.data
    changed = []
    if 'gst_rate' in data:
        valid_gst = {c[0] for c in Invoice.GST_CHOICES}
        if data['gst_rate'] not in valid_gst:
            return _err(f'GST rate must be one of: {", ".join(str(g) for g in sorted(valid_gst))}.')
        invoice.gst_rate = data['gst_rate']
        changed.append('gst_rate')
    for field in ('ship_to', 'bill_to', 'notes'):
        if field in data:
            setattr(invoice, field, str(data[field] or '').strip())
            changed.append(field)
    items = None
    if 'items' in data:
        items, problem = _parse_invoice_items(data['items'])
        if problem:
            return _err(problem)
    with transaction.atomic():
        if items is not None:
            current = {i.pk: i for i in invoice.items.all()}
            keep, new = set(), []
            for item in items:
                existing = current.get(item.existing_id)
                if existing is None or existing.pk in keep:
                    item.invoice = invoice
                    new.append(item)
                    continue
                keep.add(existing.pk)
                existing.service_name, existing.month = item.service_name, item.month
                existing.year, existing.amount = item.year, item.amount
                existing.hsn_code = item.hsn_code
                fields = ['service_name', 'month', 'year', 'amount', 'hsn_code']
                if item.sets_quantity:
                    existing.quantity = item.quantity
                    fields.append('quantity')
                if item.sets_per:
                    existing.per = item.per
                    fields.append('per')
                existing.save(update_fields=fields)
            invoice.items.exclude(pk__in=keep).delete()
            InvoiceItem.objects.bulk_create(new)
        invoice.recalculate()
        invoice.save(update_fields=[*changed, 'subtotal', 'gst_amount', 'total'])
    invoice = Invoice.objects.select_related('user').prefetch_related('items').get(pk=invoice.pk)
    return Response(_invoice_json(invoice, request))


def _invoice_create(request):
    data = request.data
    try:
        user = User.objects.filter(pk=int(data.get('user_id'))).first()
    except (TypeError, ValueError):
        user = None
    if user is None:
        return _err('Choose a customer for this invoice.')

    valid_gst = {c[0] for c in Invoice.GST_CHOICES}
    gst_rate = data.get('gst_rate', 18)
    if gst_rate not in valid_gst:
        return _err(f'GST rate must be one of: {", ".join(str(g) for g in sorted(valid_gst))}.')

    items, problem = _parse_invoice_items(data.get('items'))
    if problem:
        return _err(problem)

    address = _format_address(user)
    invoice = Invoice.objects.create(
        user=user,
        gst_rate=gst_rate,
        ship_to=str(data.get('ship_to') or '').strip() or address,
        bill_to=str(data.get('bill_to') or '').strip() or address,
        notes=str(data.get('notes') or '').strip(),
        created_by=request.user,
    )
    for item in items:
        item.invoice = invoice
    InvoiceItem.objects.bulk_create(items)
    invoice.recalculate()
    invoice.save(update_fields=['subtotal', 'gst_amount', 'total'])

    notify_invoice_created(invoice)

    email_sent = True
    try:
        from .pdf import generate_invoice_pdf
        send_invoice_email(invoice, generate_invoice_pdf(invoice))
    except Exception as exc:
        email_sent = False
        logger.error('Invoice email to %s failed: %s', user.email, exc)

    payload = _invoice_json(invoice, request)
    return Response(
        {**payload, 'email_sent': email_sent}, status=status.HTTP_201_CREATED,
    )
