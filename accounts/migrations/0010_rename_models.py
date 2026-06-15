from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0009_alter_proformainvoice_options_and_more'),
    ]

    operations = [
        # Rename the service-document model so the billing invoice can claim 'Invoice'
        migrations.RenameModel('Invoice', 'ServiceDocument'),
        # Rename billing invoice models
        migrations.RenameModel('ProformaInvoice', 'Invoice'),
        migrations.RenameModel('ProformaInvoiceItem', 'InvoiceItem'),
    ]
