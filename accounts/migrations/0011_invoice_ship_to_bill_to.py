from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0010_rename_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='ship_to',
            field=models.TextField(
                blank=True,
                verbose_name='Consignee / Ship To',
                help_text='Leave blank to auto-populate from customer profile.',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='bill_to',
            field=models.TextField(
                blank=True,
                verbose_name='Buyer / Bill To',
                help_text='Leave blank to auto-populate from customer profile.',
            ),
        ),
    ]
