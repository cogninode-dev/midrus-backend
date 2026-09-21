"""Self-service account deletion (Play Store / App Store / DPDP Act requirement)."""
import logging

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .emails import send_account_deleted_email
from .models import ContactMessage, EmailOTP, Service, ServiceDocument, User
from .security import revoke_all_tokens

logger = logging.getLogger(__name__)


class AccountThrottle(UserRateThrottle):
    scope = 'account'


def erase_user(user: User) -> None:
    """Erase a customer's personal data and lock the account.

    What goes: profile details, login credentials, uploaded documents (and the
    files on disk), one-time codes, sessions, and contact-form messages sent
    from the same address. What stays: invoices and service records, because
    Indian tax/company law requires issued invoices to be retained — their
    buyer details were snapshotted onto the invoice, and they no longer link to
    a login. The row itself is kept (anonymised) so those records stay valid.
    """
    original_email = user.email
    with transaction.atomic():
        ServiceDocument.objects.filter(service__user=user).delete()  # files removed after commit
        Service.objects.filter(user=user).update(description='')
        EmailOTP.objects.filter(user=user).delete()
        ContactMessage.objects.filter(email__iexact=original_email).delete()
        revoke_all_tokens(user)

        user.email = f'deleted-{user.pk}@deleted.invalid'
        user.name = 'Deleted user'
        user.phone = ''
        user.company = ''
        user.address = ''
        user.website = ''
        user.tax_id = ''
        user.gst_number = ''
        user.is_active = False
        user.is_approved = False
        user.is_email_verified = False
        user.set_unusable_password()
        user.save()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([AccountThrottle])
def account_delete(request):
    user = request.user
    if user.is_staff or user.is_superuser:
        return Response(
            {'error': 'Staff accounts cannot be deleted from the app. Contact an administrator.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    password = request.data.get('password')
    if not isinstance(password, str) or not user.check_password(password):
        return Response({'error': 'Incorrect password.'}, status=status.HTTP_400_BAD_REQUEST)

    email, name = user.email, user.name
    erase_user(user)
    try:
        send_account_deleted_email(email, name)
    except Exception as exc:  # the deletion already happened; don't fail the request
        logger.warning('Account-deleted email to %s failed: %s', email, exc)
    return Response({'message': 'Your account has been deleted.'})
