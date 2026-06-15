from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password, name, **extra):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, name, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(email, password, name, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email       = models.EmailField(unique=True)
    name        = models.CharField(max_length=150)
    phone       = models.CharField(max_length=20, blank=True)
    company     = models.CharField(max_length=150, blank=True)
    address     = models.TextField(blank=True)
    website     = models.URLField(blank=True)
    tax_id      = models.CharField(max_length=50, blank=True)
    gst_number  = models.CharField(max_length=50, blank=True)
    is_active          = models.BooleanField(default=True)
    is_staff           = models.BooleanField(default=False)
    is_email_verified  = models.BooleanField(default=False)
    is_approved        = models.BooleanField(default=False)  # admin approves service request access
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['name']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.email})'


class EmailOTP(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    otp        = models.CharField(max_length=6)
    is_used    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_otps'
        ordering = ['-created_at']

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and (timezone.now() - self.created_at).total_seconds() < 600

    def __str__(self):
        return f'OTP for {self.user.email}'


class Service(models.Model):
    STATUS_CHOICES = [
        ('Requested', 'Requested'),
        ('Active',    'Active'),
        ('Pending',   'Pending'),
        ('Inactive',  'Inactive'),
    ]

    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='services')
    name        = models.CharField(max_length=200)
    charge      = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    due_date    = models.DateField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'services'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.user.email}'


class ContactMessage(models.Model):
    name       = models.CharField(max_length=150)
    email      = models.EmailField()
    phone      = models.CharField(max_length=20)
    company    = models.CharField(max_length=150, blank=True)
    message    = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_read    = models.BooleanField(default=False)

    class Meta:
        db_table = 'contact_messages'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.name} ({self.email})'


class ServiceDocument(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('rejected', 'Rejected')]

    service       = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='invoices')
    file_name     = models.CharField(max_length=255)
    file          = models.FileField(upload_to='invoices/%Y/%m/', null=True, blank=True)
    uploaded_at   = models.DateTimeField(auto_now_add=True)
    is_downloaded = models.BooleanField(default=False, verbose_name='Downloaded')
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name='Status')
    is_reupload   = models.BooleanField(default=False, verbose_name='Re-uploaded')

    class Meta:
        db_table            = 'invoices'
        ordering            = ['-uploaded_at']
        verbose_name        = 'Document'
        verbose_name_plural = 'Documents'

    def __str__(self):
        return f'{self.file_name} ({self.service.name})'


class Invoice(models.Model):
    GST_CHOICES = [(0, '0%'), (5, '5%'), (12, '12%'), (18, '18%')]

    invoice_number = models.CharField(max_length=30, unique=True, blank=True)
    user           = models.ForeignKey(User, on_delete=models.CASCADE, related_name='billing_invoices')
    gst_rate       = models.IntegerField(choices=GST_CHOICES, default=18, verbose_name='GST Rate (%)')
    subtotal       = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    gst_amount     = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    total          = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    ship_to        = models.TextField(
        blank=True, verbose_name='Consignee / Ship To',
        help_text='Leave blank to auto-populate from customer profile.',
    )
    bill_to        = models.TextField(
        blank=True, verbose_name='Buyer / Bill To',
        help_text='Leave blank to auto-populate from customer profile.',
    )
    uploaded_pdf   = models.FileField(
        upload_to='invoices/uploaded/%Y/%m/', null=True, blank=True,
        verbose_name='Upload Existing Invoice (PDF)',
        help_text='Upload a ready-made PDF. If provided it will be sent instead of auto-generating.',
    )
    notes          = models.TextField(blank=True, verbose_name='Notes / Remarks')
    created_at     = models.DateTimeField(auto_now_add=True)
    created_by     = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_billing_invoices', editable=False,
    )

    class Meta:
        db_table            = 'proforma_invoices'
        ordering            = ['-created_at']
        verbose_name        = 'Invoice'
        verbose_name_plural = 'Invoices'

    def _financial_year(self):
        from django.utils import timezone
        now = timezone.now()
        y   = now.year
        return f'{str(y)[2:]}-{str(y+1)[2:]}' if now.month >= 4 else f'{str(y-1)[2:]}-{str(y)[2:]}'

    def _next_invoice_number(self):
        fy    = self._financial_year()
        count = Invoice.objects.filter(invoice_number__contains=f'/{fy}/').count() + 1
        return f'MAPL/{fy}/{str(count).zfill(4)}'

    def recalculate(self):
        from decimal import Decimal
        self.subtotal   = sum((i.amount for i in self.items.all()), Decimal('0'))
        self.gst_amount = (self.subtotal * Decimal(self.gst_rate) / Decimal(100)).quantize(Decimal('0.01'))
        self.total      = self.subtotal + self.gst_amount

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._next_invoice_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.invoice_number} — {self.user.name}'


class InvoiceItem(models.Model):
    MONTH_CHOICES = [
        (1, 'January'), (2, 'February'), (3, 'March'),    (4, 'April'),
        (5, 'May'),     (6, 'June'),     (7, 'July'),     (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
    ]

    invoice      = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    service_name = models.CharField(max_length=200, verbose_name='Service Name')
    month        = models.IntegerField(choices=MONTH_CHOICES)
    year         = models.IntegerField()
    hsn_code     = models.CharField(max_length=20, default='998311', verbose_name='HSN / SAC')
    quantity     = models.DecimalField(max_digits=10, decimal_places=2, default=1, verbose_name='Qty')
    per          = models.CharField(max_length=20, default='Month', verbose_name='Per')
    amount       = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Amount (₹)')

    class Meta:
        db_table            = 'proforma_invoice_items'
        verbose_name        = 'Service'
        verbose_name_plural = 'Services'

    def __str__(self):
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        return f'{self.service_name} ({months[self.month - 1]} {self.year})'
