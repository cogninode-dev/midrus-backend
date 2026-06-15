from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0011_invoice_ship_to_bill_to'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceitem',
            name='quantity',
            field=models.DecimalField(decimal_places=2, default=1, max_digits=10, verbose_name='Qty'),
        ),
        migrations.AddField(
            model_name='invoiceitem',
            name='per',
            field=models.CharField(default='Month', max_length=20, verbose_name='Per'),
        ),
    ]
