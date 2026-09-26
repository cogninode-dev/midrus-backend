"""Creating customer notifications.

Everything that should tell a customer "something changed" goes through
``notify``: it stores the notification (shown by the bell in the app) and, once
the surrounding transaction commits, offers it to the push backend.
"""
from django.db import transaction

from . import push
from .models import Notification


def notify(user, kind, title, body='', ref_id=None):
    notification = Notification.objects.create(
        user=user, kind=kind, title=title[:140], body=body[:300], ref_id=ref_id,
    )
    transaction.on_commit(lambda: push.dispatch(notification))
    return notification


def money(amount) -> str:
    return f'₹{amount:,.2f}'


def notify_invoice_created(invoice):
    """Call once the invoice's lines and totals are in place."""
    return notify(
        invoice.user, 'invoice',
        f'New invoice {invoice.invoice_number}',
        f'{money(invoice.total)} · open it to view, download or pay.',
        ref_id=invoice.pk,
    )
