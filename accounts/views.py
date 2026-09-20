from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
import logging
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from .files import clean_filename, validate_upload
from .security import get_user_by_email, revoke_all_tokens

logger = logging.getLogger(__name__)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.shortcuts import get_object_or_404

from .models import User, Service, ServiceDocument, Invoice
from .serializers import (
    RegisterSerializer, LoginSerializer, UserSerializer,
    ChangePasswordSerializer, ServiceSerializer, InvoiceSerializer,
    ServiceRequestSerializer, ContactMessageSerializer,
    VerifyEmailSerializer, VerifyLoginOTPSerializer,
    BillingInvoiceSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
)
from .emails import (
    generate_otp, send_otp_email,
    send_login_otp_email, send_admin_signup_notification,
    send_password_reset_email,
)


class AuthThrottle(AnonRateThrottle):
    scope = 'auth'


class ContactThrottle(AnonRateThrottle):
    scope = 'contact'


def get_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


# ─── Auth ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    s = RegisterSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
    user = s.save()
    try:
        otp = generate_otp(user)
        send_otp_email(user, otp)
    except Exception as exc:
        logger.error('Failed to send verification OTP to %s: %s', user.email, exc)
        user.delete()
        return Response(
            {'error': 'Failed to send verification email. Please try again.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({'otp_required': True}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def verify_email(request):
    s = VerifyEmailSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
    user = s.validated_data['user']
    user.is_email_verified = True
    user.save()
    # Notify admin of new signup (non-blocking)
    try:
        send_admin_signup_notification(user)
    except Exception as exc:
        logger.warning('Admin signup notification failed for %s: %s', user.email, exc)
    # Log user in immediately — return tokens so they reach the dashboard now
    return Response({
        'message': 'Email verified successfully.',
        'user': UserSerializer(user).data,
        'tokens': get_tokens(user),
    })


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def resend_otp(request):
    user = get_user_by_email(str(request.data.get('email', '')), is_email_verified=False)
    if user is None:
        # Same reply as success, so this can't be used to probe for accounts.
        return Response({'message': 'If an unverified account exists, a new OTP has been sent.'})
    try:
        otp = generate_otp(user)
        send_otp_email(user, otp)
    except Exception:
        return Response({'error': 'Failed to send email. Please try again.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({'message': 'New OTP sent to your email.'})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    s = LoginSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_401_UNAUTHORIZED)
    user = s.validated_data['user']
    try:
        otp = generate_otp(user)
        send_login_otp_email(user, otp)
    except Exception:
        return Response(
            {'error': 'Failed to send OTP email. Please try again.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({'otp_required': True})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def verify_login_otp(request):
    s = VerifyLoginOTPSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_401_UNAUTHORIZED)
    user = s.validated_data['user']
    return Response({
        'message': 'Login successful.',
        'user': UserSerializer(user).data,
        'tokens': get_tokens(user),
    })


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def resend_login_otp(request):
    user = get_user_by_email(
        str(request.data.get('email', '')), is_active=True, is_email_verified=True,
    )
    if user is None:
        return Response({'message': 'If an account exists, a new OTP has been sent.'})
    try:
        otp = generate_otp(user)
        send_login_otp_email(user, otp)
    except Exception:
        return Response({'error': 'Failed to send email. Please try again.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({'message': 'New OTP sent to your email.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    refresh = request.data.get('refresh')
    if not refresh:
        # RefreshToken(None) would happily mint and blacklist a *new* token,
        # reporting success while the caller's real token stays valid.
        return Response({'error': 'refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        token = RefreshToken(refresh)
        if str(token.get('user_id')) != str(request.user.pk):
            raise TokenError('Token does not belong to this user.')
        token.blacklist()
    except TokenError:
        return Response({'error': 'Invalid or already-expired token.'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'message': 'Logged out successfully.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    s = UserSerializer(request.user, data=request.data, partial=True)
    if s.is_valid():
        s.save()
        return Response({'message': 'Profile updated.', 'user': s.data})
    return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    s = ChangePasswordSerializer(data=request.data, context={'request': request})
    if s.is_valid():
        request.user.set_password(s.validated_data['new_password'])
        request.user.save()
        return Response({'message': 'Password changed successfully.'})
    return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


# ─── Dashboard stats ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    services = request.user.services.all()
    return Response({
        'total_services':   services.count(),
        'active_services':  services.filter(status='Active').count(),
        'pending_services': services.filter(status__in=['Pending', 'Requested']).count(),
        'total_invoices':   ServiceDocument.objects.filter(service__user=request.user).count(),
    })


# ─── Services ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def service_list(request):
    services = request.user.services.prefetch_related('invoices').all()
    return Response(ServiceSerializer(services, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def service_detail(request, pk):
    service = get_object_or_404(Service, pk=pk, user=request.user)
    return Response(ServiceSerializer(service).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def service_request(request):
    if not request.user.is_approved:
        return Response(
            {'error': 'Your account is pending admin approval. You will be notified once approved.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    s = ServiceRequestSerializer(data=request.data)
    if s.is_valid():
        Service.objects.create(
            user=request.user,
            name=s.validated_data['name'],
            description=s.validated_data.get('description', ''),
            status='Requested',
            charge='',
        )
        return Response({'message': 'Service request submitted. Admin will review and set pricing.'}, status=status.HTTP_201_CREATED)
    return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


# ─── Invoices ─────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invoice_add(request, service_pk):
    service = get_object_or_404(Service, pk=service_pk, user=request.user)
    uploaded_file = request.FILES.get('file')
    file_name = clean_filename(uploaded_file.name if uploaded_file else str(request.data.get('file_name', '')))
    if not file_name:
        return Response({'error': 'file is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if uploaded_file:
        problem = validate_upload(uploaded_file)
        if problem:
            return Response({'error': problem}, status=status.HTTP_400_BAD_REQUEST)
    is_reupload = str(request.data.get('is_reupload', 'false')).lower() in ('true', '1')
    doc = ServiceDocument.objects.create(service=service, file_name=file_name, file=uploaded_file, is_reupload=is_reupload)
    return Response(InvoiceSerializer(doc, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([ContactThrottle])
def contact(request):
    s = ContactMessageSerializer(data=request.data)
    if s.is_valid():
        s.save()
        return Response({'message': 'Thank you! We will get back to you shortly.'}, status=status.HTTP_201_CREATED)
    return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def invoice_delete(request, service_pk, invoice_pk):
    service = get_object_or_404(Service, pk=service_pk, user=request.user)
    doc     = get_object_or_404(ServiceDocument, pk=invoice_pk, service=service)
    doc.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Proforma Invoices ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def proforma_invoice_list(request):
    invoices = Invoice.objects.filter(user=request.user).prefetch_related('items').order_by('-created_at')
    return Response(BillingInvoiceSerializer(invoices, many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def password_reset_request(request):
    s = PasswordResetRequestSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
    try:
        user = get_user_by_email(
            s.validated_data['email'], is_active=True, is_email_verified=True,
        )
        if user is not None:
            otp = generate_otp(user)
            send_password_reset_email(user, otp)
    except Exception as exc:
        # Silent to the caller — never reveal whether the email exists — but
        # visible to operators, unlike a bare `pass`.
        logger.warning('Password reset email failed: %s', exc)
    return Response({'message': 'If an account exists with this email, a reset OTP has been sent.'})


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def password_reset_confirm(request):
    s = PasswordResetConfirmSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
    s._otp_obj.is_used = True
    s._otp_obj.save()
    s._user.set_password(s.validated_data['new_password'])
    s._user.save()
    # Whoever held the old password (or a stolen refresh token) loses access.
    revoke_all_tokens(s._user)
    return Response({'message': 'Password reset successfully. You can now log in with your new password.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([UserRateThrottle])
def admin_user_lookup(request):
    if not request.user.is_staff:
        return Response({'found': False}, status=status.HTTP_403_FORBIDDEN)
    user_id = request.GET.get('id', '').strip()
    email   = request.GET.get('email', '').strip()
    try:
        if user_id:
            if not user_id.isdigit():
                return Response({'found': False})
            u = User.objects.get(pk=int(user_id))
        elif email:
            u = get_user_by_email(email)
            if u is None:
                return Response({'found': False})
        else:
            return Response({'found': False})
        return Response({
            'found':      True,
            'name':       u.name,
            'company':    u.company or '',
            'gst_number': u.gst_number or '',
            'address':    u.address or '',
            'phone':      u.phone or '',
        })
    except User.DoesNotExist:
        return Response({'found': False})
