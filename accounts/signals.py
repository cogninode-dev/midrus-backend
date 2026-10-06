"""Housekeeping signals, and the ones that tell customers something changed."""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Invoice, Service, ServiceDocument, User
from .notifications import money, notify


def _delete_file_after_commit(fieldfile) -> None:
    """Remove a stored file once the row deletion has actually committed."""
    if not fieldfile:
        return
    storage, name = fieldfile.storage, fieldfile.name
    transaction.on_commit(lambda: storage.delete(name))


@receiver(post_delete, sender=ServiceDocument)
def delete_document_file(sender, instance, **kwargs):
    # Django never removes the file behind a FileField on its own, so deleted
    # client documents would otherwise stay on disk forever.
    _delete_file_after_commit(instance.file)


@receiver(post_delete, sender=User)
def delete_user_photo(sender, instance, **kwargs):
    _delete_file_after_commit(instance.photo)


@receiver(post_delete, sender=Invoice)
def delete_invoice_pdf(sender, instance, **kwargs):
    _delete_file_after_commit(instance.uploaded_pdf)


# ─── customer notifications ──────────────────────────────────────────────────
#
# Signals (rather than calls sprinkled through views) mean a change is noticed
# whether staff made it in the app, in the Django admin site, or from a shell.

def _remember(instance, *fields):
    """Stash the stored values so post_save can tell what actually changed."""
    row = None
    if instance.pk:
        row = type(instance).objects.filter(pk=instance.pk).values(*fields).first()
    instance._before = row


def _changed(instance, field, update_fields):
    """(old, new) if `field` really changed in this save, else None."""
    before = getattr(instance, '_before', None)
    if before is None:  # a brand-new row: creation has its own messages
        return None
    if update_fields is not None and field not in update_fields:
        return None
    old, new = before[field], getattr(instance, field)
    return (old, new) if old != new else None


@receiver(pre_save, sender=Invoice)
def remember_invoice(sender, instance, **kwargs):
    _remember(instance, 'payment_status')


@receiver(post_save, sender=Invoice)
def notify_payment_status(sender, instance, created, update_fields=None, **kwargs):
    change = None if created else _changed(instance, 'payment_status', update_fields)
    if not change:
        return
    number = instance.invoice_number
    text = {
        'processing': (f'Payment being verified · {number}',
                       'We are checking your payment. This can take a little while.'),
        'success':    (f'Payment received · {number}',
                       f'Thank you! {money(instance.total)} has been received.'),
        'failed':     (f'Payment failed · {number}',
                       'Your payment did not go through. Open the invoice to try again.'),
        'pending':    (f'Payment pending · {number}',
                       f'{money(instance.total)} is due. Open the invoice to pay.'),
    }[change[1]]
    notify(instance.user, 'payment', *text, ref_id=instance.pk)


@receiver(pre_save, sender=Service)
def remember_service(sender, instance, **kwargs):
    _remember(instance, 'status', 'charge')


@receiver(post_save, sender=Service)
def notify_service_change(sender, instance, created, update_fields=None, **kwargs):
    if created:
        return
    status = _changed(instance, 'status', update_fields)
    charge = _changed(instance, 'charge', update_fields)
    if not (status or charge):
        return
    parts = []
    if status:
        parts.append({
            'Active':    'Your service is now active.',
            'Pending':   'Work on your service is under way.',
            'Inactive':  'Your service is now inactive.',
            'Requested': 'Your request has been received.',
        }.get(status[1], f'Status: {status[1]}.'))
    if charge and instance.charge:
        parts.append(f'Charge: {instance.charge}.')
    title = f'{instance.name} · {status[1]}' if status else f'{instance.name} · updated'
    notify(instance.user, 'service', title, ' '.join(parts), ref_id=instance.pk)


@receiver(pre_save, sender=ServiceDocument)
def remember_document(sender, instance, **kwargs):
    _remember(instance, 'status', 'is_downloaded')


@receiver(post_save, sender=ServiceDocument)
def notify_document_change(sender, instance, created, update_fields=None, **kwargs):
    if created:
        return
    user = instance.service.user
    status = _changed(instance, 'status', update_fields)
    if status and status[1] == 'rejected':
        notify(user, 'document', f'Document rejected · {instance.file_name}',
               'Please upload a corrected version.', ref_id=instance.service_id)
    elif status and status[1] == 'active':
        notify(user, 'document', f'Document restored · {instance.file_name}',
               'The rejection was withdrawn. No action needed.', ref_id=instance.service_id)
    elif _changed(instance, 'is_downloaded', update_fields) == (False, True):
        notify(user, 'document', f'Document received · {instance.file_name}',
               'MIDRUS has opened your document.', ref_id=instance.service_id)


@receiver(pre_save, sender=User)
def remember_user(sender, instance, **kwargs):
    _remember(instance, 'is_approved')


@receiver(post_save, sender=User)
def notify_approval(sender, instance, created, update_fields=None, **kwargs):
    if created or instance.is_staff:
        return
    change = _changed(instance, 'is_approved', update_fields)
    if not change:
        return
    if change[1]:
        notify(instance, 'account', 'Your account is approved',
               'You can now request services.')
    else:
        notify(instance, 'account', 'Your access was updated',
               'You can no longer request new services. Contact us if this is unexpected.')
