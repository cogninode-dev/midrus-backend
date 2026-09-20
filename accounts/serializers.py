from rest_framework import serializers
from .files import make_file_url
from .models import User, Service, ServiceDocument, ContactMessage, Invoice, InvoiceItem
from .security import consume_otp, get_user_by_email, normalize_email


class SingleLineMixin:
    """Names end up in email subjects and PDFs: no line breaks or control chars."""

    @staticmethod
    def _single_line(value):
        return ' '.join(str(value).split())

    def validate_name(self, value):
        return self._single_line(value)

    def validate_company(self, value):
        return self._single_line(value)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email        = serializers.EmailField()
    otp          = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(min_length=6, write_only=True)

    def validate(self, data):
        # Same answer whether or not the account exists: the request endpoint
        # is deliberately silent, so this one must not reveal it either.
        user = get_user_by_email(data['email'], is_active=True, is_email_verified=True)
        if user is None:
            raise serializers.ValidationError({'otp': 'Invalid or expired OTP.'})
        try:
            otp_obj = consume_otp(
                user, data['otp'],
                invalid='Invalid or expired OTP.',
                expired='This OTP has expired. Request a new one.',
            )
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({'otp': exc.detail})
        self._user    = user
        self._otp_obj = otp_obj
        return data


class RegisterSerializer(SingleLineMixin, serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model  = User
        fields = ['email', 'password', 'name', 'phone', 'company']

    def validate_email(self, value):
        value = normalize_email(value)
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def create(self, validated_data):
        return User.objects.create_user(is_active=True, is_email_verified=False, is_approved=False, **validated_data)


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        # Check credentials manually to distinguish wrong password vs pending approval
        user = get_user_by_email(data['email'])
        if user is None:
            # Burn the same hashing time as a real login so response time
            # does not reveal which emails have accounts.
            User().set_password(data['password'])
            raise serializers.ValidationError('Invalid email or password.')

        if not user.check_password(data['password']):
            raise serializers.ValidationError('Invalid email or password.')

        if not user.is_email_verified:
            raise serializers.ValidationError(
                'Please verify your email first. Enter the OTP sent to your inbox.'
            )

        if not user.is_active:
            raise serializers.ValidationError(
                'Your account has been deactivated. Please contact support.'
            )

        data['user'] = user
        return data


class UserSerializer(SingleLineMixin, serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = [
            'id', 'email', 'name', 'phone', 'company',
            'address', 'website', 'tax_id', 'gst_number',
            'is_approved', 'is_staff', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'email', 'is_approved', 'is_staff', 'created_at', 'updated_at']


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password     = serializers.CharField(write_only=True, min_length=6)

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value


class InvoiceSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model  = ServiceDocument
        fields = ['id', 'file_name', 'file_url', 'uploaded_at', 'is_downloaded', 'status', 'is_reupload']

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get('request')
        return make_file_url(request, 'doc', obj.pk)


class ServiceSerializer(serializers.ModelSerializer):
    invoices = InvoiceSerializer(many=True, read_only=True)

    class Meta:
        model  = Service
        fields = [
            'id', 'name', 'charge', 'description',
            'status', 'due_date', 'invoices',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'invoices', 'charge', 'status', 'due_date', 'created_at', 'updated_at']


class ServiceRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Service
        fields = ['name', 'description']


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ContactMessage
        fields = ['name', 'email', 'phone', 'company', 'message']
        extra_kwargs = {'message': {'max_length': 5000}}


class VerifyLoginOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp   = serializers.CharField(max_length=6)

    def validate(self, data):
        user = get_user_by_email(data['email'], is_active=True, is_email_verified=True)
        if user is None:
            raise serializers.ValidationError('Invalid credentials.')
        consume_otp(user, data['otp'])
        data['user'] = user
        return data


class InvoiceItemSerializer(serializers.ModelSerializer):
    month_name = serializers.SerializerMethodField()

    class Meta:
        model  = InvoiceItem
        fields = ['id', 'service_name', 'month', 'month_name', 'year', 'hsn_code', 'amount']

    def get_month_name(self, obj):
        months = ['January','February','March','April','May','June',
                  'July','August','September','October','November','December']
        return months[obj.month - 1]


class BillingInvoiceSerializer(serializers.ModelSerializer):
    customer         = serializers.SerializerMethodField()
    customer_email   = serializers.SerializerMethodField()
    customer_address = serializers.SerializerMethodField()
    customer_gst     = serializers.SerializerMethodField()
    customer_company = serializers.SerializerMethodField()
    customer_phone   = serializers.SerializerMethodField()
    items            = InvoiceItemSerializer(many=True, read_only=True)
    uploaded_pdf_url = serializers.SerializerMethodField()

    class Meta:
        model  = Invoice
        fields = [
            'id', 'invoice_number',
            'customer', 'customer_email', 'customer_address',
            'customer_gst', 'customer_company', 'customer_phone',
            'items', 'gst_rate', 'subtotal', 'gst_amount', 'total',
            'uploaded_pdf_url', 'notes', 'created_at',
        ]

    def get_customer(self, obj):         return obj.user.name
    def get_customer_email(self, obj):   return obj.user.email
    def get_customer_address(self, obj): return obj.user.address or ''
    def get_customer_gst(self, obj):     return obj.user.gst_number or ''
    def get_customer_company(self, obj): return obj.user.company or ''
    def get_customer_phone(self, obj):   return obj.user.phone or ''

    def get_uploaded_pdf_url(self, obj):
        if not obj.uploaded_pdf:
            return None
        request = self.context.get('request')
        return make_file_url(request, 'invoice', obj.pk)


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp   = serializers.CharField(max_length=6)

    def validate(self, data):
        user = get_user_by_email(data['email'])
        if user is None:
            raise serializers.ValidationError('Invalid OTP.')

        if user.is_email_verified:
            raise serializers.ValidationError('Email is already verified.')

        consume_otp(user, data['otp'])
        data['user'] = user
        return data
