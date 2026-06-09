from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.shortcuts import get_object_or_404

from .models import Service, Invoice, ContactMessage
from .serializers import (
    RegisterSerializer, LoginSerializer, UserSerializer,
    ChangePasswordSerializer, ServiceSerializer, InvoiceSerializer,
    ServiceRequestSerializer, ContactMessageSerializer,
    VerifyEmailSerializer, VerifyLoginOTPSerializer,
)
from .emails import generate_otp, send_otp_email, send_pending_email, send_login_otp_email, send_admin_signup_notification


class AuthThrottle(AnonRateThrottle):
    scope = 'auth'


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
    except Exception:
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
    except Exception:
        pass
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
    from .models import User
    email = request.data.get('email', '').strip()
    try:
        user = User.objects.get(email=email, is_email_verified=False)
    except User.DoesNotExist:
        return Response({'error': 'No unverified account found with this email.'}, status=status.HTTP_400_BAD_REQUEST)
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
    from .models import User
    email = request.data.get('email', '').strip()
    try:
        user = User.objects.get(email=email, is_active=True, is_email_verified=True)
    except User.DoesNotExist:
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
    try:
        RefreshToken(request.data.get('refresh')).blacklist()
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
        'total_invoices':   Invoice.objects.filter(service__user=request.user).count(),
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
    file_name = (uploaded_file.name if uploaded_file else request.data.get('file_name', '')).strip()
    if not file_name:
        return Response({'error': 'file is required.'}, status=status.HTTP_400_BAD_REQUEST)
    invoice = Invoice.objects.create(service=service, file_name=file_name, file=uploaded_file)
    return Response(InvoiceSerializer(invoice, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
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
    invoice = get_object_or_404(Invoice, pk=invoice_pk, service=service)
    invoice.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
