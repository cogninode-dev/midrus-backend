"""Push delivery, kept behind a tiny interface.

Notifications are always stored (that is what the in-app bell shows). This
module additionally hands each new one to a *push backend* so it can reach a
phone that is not running the app.

The default backend only logs. To send real pushes, add a class with a
``send`` method and point ``PUSH_BACKEND`` at it (see settings), for example
one built on Firebase Cloud Messaging. Nothing else in the codebase changes.
"""
import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class PushBackend:
    def send(self, tokens, title, body, data):
        """Deliver to the given device tokens.

        Returns the tokens the provider says are no longer valid, so they can
        be forgotten; anything else the caller does not need to know about.
        """
        raise NotImplementedError


class LoggingPushBackend(PushBackend):
    """Default: records what would have been sent. Sends nothing."""

    def send(self, tokens, title, body, data):
        logger.info('PUSH (not sent, no backend configured) to %d device(s): %s', len(tokens), title)
        return []


class FirebaseCloudMessagingBackend(PushBackend):
    """Real push via Firebase Cloud Messaging.

    Needs FCM_CREDENTIALS_PATH (a service-account JSON downloaded from
    Firebase Console → Project Settings → Service Accounts → Generate new
    private key) set in settings/.env. The app is created lazily and once,
    since initializing it twice raises.
    """

    _app = None

    @classmethod
    def _get_app(cls):
        import firebase_admin
        from firebase_admin import credentials

        if cls._app is None:
            cred = credentials.Certificate(settings.FCM_CREDENTIALS_PATH)
            cls._app = firebase_admin.initialize_app(cred)
        return cls._app

    def send(self, tokens, title, body, data):
        from firebase_admin import messaging
        from firebase_admin.exceptions import FirebaseError

        app = self._get_app()
        # FCM data payloads must be flat string -> string maps.
        str_data = {k: str(v) for k, v in data.items()}

        invalid = []
        for token in tokens:
            message = messaging.Message(
                token=token,
                notification=messaging.Notification(title=title, body=body),
                data=str_data,
                android=messaging.AndroidConfig(priority='high'),
            )
            try:
                messaging.send(message, app=app)
            except messaging.UnregisteredError:
                invalid.append(token)
            except FirebaseError:
                logger.exception('FCM send failed for one device token.')
        return invalid


def get_backend() -> PushBackend:
    path = getattr(settings, 'PUSH_BACKEND', 'accounts.push.LoggingPushBackend')
    return import_string(path)()


def dispatch(notification) -> None:
    """Push one stored notification to all of its user's registered devices.

    Never raises: a push outage must not break the request that caused the
    notification, and the notification is already saved for the in-app bell.
    """
    from .models import DeviceToken

    try:
        tokens = list(
            DeviceToken.objects.filter(user_id=notification.user_id).values_list('token', flat=True)
        )
        if not tokens:
            return
        data = {'kind': notification.kind, 'notification_id': str(notification.pk)}
        if notification.ref_id is not None:
            data['ref_id'] = str(notification.ref_id)
        invalid = get_backend().send(tokens, notification.title, notification.body, data) or []
        if invalid:
            DeviceToken.objects.filter(token__in=invalid).delete()
    except Exception:
        logger.exception('Push delivery failed for notification %s', getattr(notification, 'pk', None))
