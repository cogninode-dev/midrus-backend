"""Staff-only REST API powering the in-app admin panel.

Mirrors what the Django admin site does (approve users, manage services,
review documents, read contact messages, create invoices) so the mobile
app's admin section never needs the web admin. Every view requires an
authenticated, active staff user.
"""
import datetime
import logging
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from .emails import send_approved_email, send_invoice_email
from .files import make_file_url
from .models import (
    ContactMessage, Invoice, InvoiceItem, Service, ServiceDocument, User,
)
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


def _user_row(u):
    return {
        'id': u.id,
        'email': u.email,
        'name': u.name,
        'company': u.company,
        'phone': u.phone,
        'address': u.address,
        'gst_number': u.gst_number,
        'is_approved': u.is_approved,
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
    })


# ─── users ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def users(request):
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
    return _paginated(request, qs.order_by('-created_at'), _user_row)


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
    return Response(_user_row(user))


# ─── services ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def services(request):
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


@api_view(['PATCH'])
@permission_classes(STAFF)
def service_update(request, pk):
    service = get_object_or_404(Service.objects.select_related('user'), pk=pk)
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

@api_view(['GET'])
@permission_classes(STAFF)
def documents(request):
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


@api_view(['PATCH'])
@permission_classes(STAFF)
def message_update(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
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


def _dec(value, field, minimum=Decimal('0')):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{field} must be a number.')
    if not d.is_finite() or d <= minimum:
        raise ValueError(f'{field} must be greater than {minimum}.')
    return d


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

    raw_items = data.get('items')
    if not isinstance(raw_items, list) or not raw_items:
        return _err('Add at least one service line.')
    if len(raw_items) > 50:
        return _err('An invoice can have at most 50 lines.')

    items = []
    for idx, raw in enumerate(raw_items, start=1):
        label = f'Line {idx}'
        if not isinstance(raw, dict):
            return _err(f'{label} is invalid.')
        name = str(raw.get('service_name', '')).strip()
        if not name:
            return _err(f'{label}: service name is required.')
        if len(name) > 200:
            return _err(f'{label}: service name is too long (max 200).')
        try:
            month = int(raw.get('month'))
            year = int(raw.get('year'))
        except (TypeError, ValueError):
            return _err(f'{label}: month and year are required.')
        if not 1 <= month <= 12:
            return _err(f'{label}: month must be between 1 and 12.')
        if not 2000 <= year <= 2100:
            return _err(f'{label}: year must be between 2000 and 2100.')
        try:
            amount = _dec(raw.get('amount'), f'{label}: amount')
            quantity = _dec(raw.get('quantity', 1), f'{label}: quantity')
        except ValueError as exc:
            return _err(str(exc))
        if amount >= Decimal('10') ** 10:
            return _err(f'{label}: amount is too large.')
        items.append(InvoiceItem(
            service_name=name, month=month, year=year,
            hsn_code=str(raw.get('hsn_code') or '998311').strip()[:20],
            quantity=quantity,
            per=str(raw.get('per') or 'Month').strip()[:20],
            amount=amount,
        ))

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
