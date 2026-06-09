from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User, Service, Invoice, ContactMessage, EmailOTP


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model  = User
        fields = ['email', 'password', 'name', 'phone', 'company']

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def create(self, validated_data):
        return User.objects.create_user(is_active=True, is_email_verified=False, is_approved=False, **validated_data)


class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        # Check credentials manually to distinguish wrong password vs pending approval
        try:
            user = User.objects.get(email=data['email'])
        except User.DoesNotExist:
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


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = [
            'id', 'email', 'name', 'phone', 'company',
            'address', 'website', 'tax_id', 'gst_number',
            'is_approved', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'email', 'is_approved', 'created_at', 'updated_at']


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
        model  = Invoice
        fields = ['id', 'file_name', 'file_url', 'uploaded_at']

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


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


class VerifyLoginOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp   = serializers.CharField(max_length=6)

    def validate(self, data):
        try:
            user = User.objects.get(email=data['email'], is_active=True, is_email_verified=True)
        except User.DoesNotExist:
            raise serializers.ValidationError('Invalid credentials.')

        try:
            otp_obj = EmailOTP.objects.filter(
                user=user, otp=data['otp'], is_used=False
            ).latest('created_at')
        except EmailOTP.DoesNotExist:
            raise serializers.ValidationError('Invalid OTP.')

        if not otp_obj.is_valid():
            raise serializers.ValidationError('OTP has expired. Please request a new one.')

        otp_obj.is_used = True
        otp_obj.save()
        data['user'] = user
        return data


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp   = serializers.CharField(max_length=6)

    def validate(self, data):
        try:
            user = User.objects.get(email=data['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError('No account found with this email.')

        if user.is_email_verified:
            raise serializers.ValidationError('Email is already verified.')

        try:
            otp_obj = EmailOTP.objects.filter(
                user=user, otp=data['otp'], is_used=False
            ).latest('created_at')
        except EmailOTP.DoesNotExist:
            raise serializers.ValidationError('Invalid OTP.')

        if not otp_obj.is_valid():
            raise serializers.ValidationError('OTP has expired. Please request a new one.')

        otp_obj.is_used = True
        otp_obj.save()
        data['user'] = user
        return data
