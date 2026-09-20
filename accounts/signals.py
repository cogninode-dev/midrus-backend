"""Housekeeping signals."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Invoice, ServiceDocument


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


@receiver(post_delete, sender=Invoice)
def delete_invoice_pdf(sender, instance, **kwargs):
    _delete_file_after_commit(instance.uploaded_pdf)
