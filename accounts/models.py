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
    is_email_verified  = models.BooleanField(default=True)  # False for new API registrations
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
    phone      = models.CharField(max_length=20, blank=True)
    company    = models.CharField(max_length=150, blank=True)
    message    = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_read    = models.BooleanField(default=False)

    class Meta:
        db_table = 'contact_messages'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.name} ({self.email})'


class Invoice(models.Model):
    service     = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='invoices')
    file_name   = models.CharField(max_length=255)
    file        = models.FileField(upload_to='invoices/%Y/%m/', null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'invoices'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.file_name} ({self.service.name})'
