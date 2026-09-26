"""The signed-in customer's notifications and push device registration."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DeviceToken, Notification

DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def _row(n):
    return {
        'id': n.pk,
        'kind': n.kind,
        'title': n.title,
        'body': n.body,
        'ref_id': n.ref_id,
        'is_read': n.is_read,
        'created_at': n.created_at,
    }


def _unread(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).count()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    qs = Notification.objects.filter(user=request.user)
    if request.GET.get('unread') in ('1', 'true'):
        qs = qs.filter(is_read=False)
    try:
        limit = max(1, min(int(request.GET.get('limit', DEFAULT_LIMIT)), MAX_LIMIT))
        offset = max(0, int(request.GET.get('offset', 0)))
    except ValueError:
        limit, offset = DEFAULT_LIMIT, 0
    total = qs.count()
    rows = list(qs[offset:offset + limit])
    return Response({
        'count': total,
        'unread_count': _unread(request.user),
        'next_offset': offset + limit if offset + limit < total else None,
        'results': [_row(n) for n in rows],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_unread_count(request):
    """Cheap enough to poll for the bell badge."""
    return Response({'unread_count': _unread(request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=['is_read'])
    return Response({'unread_count': _unread(request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_read_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'unread_count': 0})


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def device(request):
    """Register (POST) or forget (DELETE) this phone's push token.

    A token belongs to whoever registered it last, so a phone that changes
    hands never keeps pushing the previous user's notifications.
    """
    token = str(request.data.get('token') or '').strip()
    if not 20 <= len(token) <= 512:
        return Response({'error': 'A valid device token is required.'}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'DELETE':
        DeviceToken.objects.filter(token=token, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    platform = request.data.get('platform')
    if platform not in {p for p, _ in DeviceToken.PLATFORM_CHOICES}:
        return Response({'error': 'Platform must be android or ios.'}, status=status.HTTP_400_BAD_REQUEST)
    DeviceToken.objects.update_or_create(
        token=token, defaults={'user': request.user, 'platform': platform},
    )
    return Response({'registered': True}, status=status.HTTP_201_CREATED)
