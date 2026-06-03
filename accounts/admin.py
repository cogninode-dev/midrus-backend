from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html, mark_safe
from django.contrib import messages
from .models import User, Service, Invoice, ContactMessage
from .emails import send_approved_email

admin.site.site_header = 'MIDRUS Administration'
admin.site.site_title  = 'MIDRUS Admin'
admin.site.index_title = 'Dashboard'


class InvoiceInline(admin.TabularInline):
    model           = Invoice
    extra           = 1
    readonly_fields = ['uploaded_at', 'download_link']
    fields          = ['file_name', 'file', 'uploaded_at', 'download_link']

    @admin.display(description='Actions')
    def download_link(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank" style="color:#1976d2;font-weight:600;margin-right:10px">👁 View</a>'
                '<a href="{}" download style="color:#388e3c;font-weight:600">⬇ Download</a>',
                obj.file.url, obj.file.url
            )
        return mark_safe('<span style="color:#aaa;font-size:12px">No file</span>')


class ServiceInline(admin.TabularInline):
    model            = Service
    extra            = 1
    fields           = ['name', 'charge', 'status', 'due_date']
    show_change_link = True


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display    = ['email', 'name', 'company', 'phone', 'approval_status', 'is_staff', 'created_at']
    list_filter     = ['is_active', 'is_staff', 'created_at']
    search_fields   = ['email', 'name', 'phone', 'company']
    ordering        = ['is_active', '-created_at']
    readonly_fields = ['created_at', 'updated_at']
    inlines         = [ServiceInline]
    actions         = ['approve_users', 'deactivate_users']

    fieldsets = (
        ('Login',        {'fields': ('email', 'password')}),
        ('Personal',     {'fields': ('name', 'phone', 'company', 'address', 'website')}),
        ('Tax & Legal',  {'fields': ('tax_id', 'gst_number')}),
        ('Permissions',  {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'), 'classes': ('collapse',)}),
        ('Timestamps',   {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields':  ('email', 'name', 'password1', 'password2'),
        }),
    )

    @admin.display(description='Status')
    def approval_status(self, obj):
        if obj.is_active:
            return mark_safe('<span style="color:green;font-weight:600">&#10004; Approved</span>')
        return mark_safe('<span style="color:orange;font-weight:600">&#9203; Pending Approval</span>')

    @admin.action(description='✔ Approve selected users')
    def approve_users(self, request, queryset):
        to_approve = list(queryset.filter(is_active=False))
        updated = queryset.filter(is_active=False).update(is_active=True)
        for user in to_approve:
            send_approved_email(user)
        self.message_user(request, f'{updated} user(s) approved and notified by email.', messages.SUCCESS)

    @admin.action(description='✖ Deactivate selected users')
    def deactivate_users(self, request, queryset):
        updated = queryset.filter(is_active=True, is_staff=False).update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated.', messages.WARNING)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display    = ['name', 'user', 'charge', 'status_display', 'due_date', 'created_at']
    list_filter     = ['status', 'created_at']
    list_display_links = ['name']
    search_fields   = ['name', 'user__email', 'user__name']
    ordering        = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    inlines         = [InvoiceInline]

    ordering = ['status', '-created_at']  # Requested first (alphabetically before Active)

    fieldsets = (
        ('Service Info', {'fields': ('user', 'name', 'description', 'charge', 'status', 'due_date')}),
        ('Timestamps',   {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='Status')
    def status_display(self, obj):
        colors = {
            'Requested': ('orange',  'Requested'),
            'Active':    ('green',   'Active'),
            'Pending':   ('#1976d2', 'Pending'),
            'Inactive':  ('red',     'Inactive'),
        }
        color, label = colors.get(obj.status, ('grey', obj.status))
        return format_html('<span style="color:{};font-weight:600">{}</span>', color, label)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display    = ['file_name', 'service', 'client_email', 'download_link', 'uploaded_at']
    list_filter     = ['uploaded_at']
    search_fields   = ['file_name', 'service__name', 'service__user__email']
    ordering        = ['-uploaded_at']
    readonly_fields = ['uploaded_at', 'download_link']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('service', 'service__user')

    @admin.display(description='Client')
    def client_email(self, obj):
        return obj.service.user.email

    @admin.display(description='File')
    def download_link(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank" style="color:#1976d2;font-weight:600;margin-right:8px">👁 View</a>'
                '<a href="{}" download style="color:#388e3c;font-weight:600">⬇ Download</a>',
                obj.file.url, obj.file.url
            )
        return mark_safe('<span style="color:#aaa;font-size:12px">No file uploaded</span>')


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display   = ['name', 'email', 'short_message', 'read_status', 'submitted_at']
    list_filter    = ['is_read', 'submitted_at']
    search_fields  = ['name', 'email', 'message']
    ordering       = ['-submitted_at']
    readonly_fields = ['name', 'email', 'message', 'submitted_at']
    actions        = ['mark_read', 'mark_unread']

    fieldsets = (
        ('Contact Details', {'fields': ('name', 'email', 'submitted_at')}),
        ('Message',         {'fields': ('message', 'is_read')}),
    )

    @admin.display(description='Message')
    def short_message(self, obj):
        return obj.message[:80] + '…' if len(obj.message) > 80 else obj.message

    @admin.display(description='Status')
    def read_status(self, obj):
        if obj.is_read:
            return mark_safe('<span style="color:green;font-weight:600">&#10004; Read</span>')
        return mark_safe('<span style="color:orange;font-weight:600">&#9679; Unread</span>')

    @admin.action(description='Mark selected as read')
    def mark_read(self, request, queryset):
        queryset.update(is_read=True)
        self.message_user(request, 'Messages marked as read.', messages.SUCCESS)

    @admin.action(description='Mark selected as unread')
    def mark_unread(self, request, queryset):
        queryset.update(is_read=False)
        self.message_user(request, 'Messages marked as unread.', messages.WARNING)

    def has_add_permission(self, request):
        return False  # Contact messages come from the website only
