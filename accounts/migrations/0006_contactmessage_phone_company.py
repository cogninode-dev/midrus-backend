from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_user_is_email_verified_emailotp'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactmessage',
            name='phone',
            field=models.CharField(max_length=20, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='contactmessage',
            name='company',
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
