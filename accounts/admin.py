import datetime
import mimetypes
import os
from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import FileResponse, Http404
from django.shortcuts import redirect, get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html, mark_safe

from .models import User, Service, ServiceDocument, ContactMessage, Invoice, InvoiceItem
from .emails import send_approved_email, send_invoice_email

admin.site.site_header = 'MIDRUS Administration'
admin.site.site_title  = 'MIDRUS Admin'
admin.site.index_title = 'Dashboard'


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _reupload_badge_html(is_reupload: bool) -> str:
    if is_reupload:
        return (
            '<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
            'background:#f59e0b;color:#fff;font-size:11px;font-weight:700;">🔄 Re-uploaded</span>'
        )
    return '<span style="color:#ccc;">—</span>'

class InvoiceInline(admin.TabularInline):
    model               = ServiceDocument
    verbose_name        = 'Document'
    verbose_name_plural = 'Documents'
    extra               = 1
    readonly_fields     = ['uploaded_at', 'reupload_badge', 'download_link']
    fields              = ['file_name', 'file', 'status', 'uploaded_at', 'reupload_badge', 'download_link']

    @admin.display(description='Re-upload')
    def reupload_badge(self, obj):
        return mark_safe(_reupload_badge_html(obj.is_reupload))

    @admin.display(description='Actions')
    def download_link(self, obj):
        if obj.file and obj.pk:
            view_url = reverse('admin:accounts_doc_view', args=[obj.pk])
            dl_url   = reverse('admin:accounts_doc_download', args=[obj.pk])
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer" style="color:#1976d2;font-weight:600;margin-right:10px">👁 View</a>'
                '<a href="{}" style="color:#388e3c;font-weight:600">⬇ Download</a>',
                view_url, dl_url,
            )
        return mark_safe('<span style="color:#aaa;font-size:12px">No file</span>')


class ServiceInline(admin.TabularInline):
    model            = Service
    extra            = 1
    fields           = ['name', 'charge', 'status', 'due_date']
    show_change_link = True


# ─── User ────────────────────────────────────────────────────────────────────

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display    = ['email', 'name', 'company', 'phone', 'approval_status', 'quick_actions', 'created_at']
    list_filter     = ['is_approved', 'is_active', 'is_staff', 'created_at']
    search_fields   = ['email', 'name', 'phone', 'company']
    ordering        = ['is_approved', '-created_at']
    readonly_fields = ['created_at', 'updated_at']
    inlines         = [ServiceInline]
    actions         = ['approve_users', 'revoke_approval']

    fieldsets = (
        ('Login',        {'fields': ('email', 'password')}),
        ('Personal',     {'fields': ('name', 'phone', 'company', 'address', 'website')}),
        ('Tax & Legal',  {'fields': ('tax_id', 'gst_number')}),
        ('Permissions',  {'fields': ('is_approved', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'), 'classes': ('collapse',)}),
        ('Timestamps',   {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields':  ('email', 'name', 'password1', 'password2'),
        }),
    )

    class Media:
        js = ('accounts/js/admin_confirm.js',)

    # ── Per-row approve / reject URLs ─────────────────────────────────────────

    def get_urls(self):
        custom = [
            path('<int:pk>/approve/', self.admin_site.admin_view(self._approve_view), name='accounts_user_approve'),
            path('<int:pk>/reject/',  self.admin_site.admin_view(self._reject_view),  name='accounts_user_reject'),
        ]
        return custom + super().get_urls()

    def _approve_view(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if not user.is_staff:
            user.is_approved = True
            user.save(update_fields=['is_approved'])
            try:
                send_approved_email(user)
            except Exception:
                pass
            self.message_user(request, f'✔ {user.name} ({user.email}) approved and notified.', messages.SUCCESS)
        return redirect(reverse('admin:accounts_user_changelist'))

    def _reject_view(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if not user.is_staff:
            user.is_approved = False
            user.save(update_fields=['is_approved'])
            self.message_user(request, f'✖ {user.name} ({user.email}) approval revoked.', messages.WARNING)
        return redirect(reverse('admin:accounts_user_changelist'))

    # ── List columns ──────────────────────────────────────────────────────────

    @admin.display(description='Status')
    def approval_status(self, obj):
        s = ('display:inline-block;padding:3px 11px;border-radius:20px;'
             'font-size:11px;font-weight:600;white-space:nowrap;color:#fff;')
        if obj.is_staff:
            return mark_safe(f'<span style="{s}background:#6366f1;">&#9670; Staff</span>')
        if obj.is_approved:
            return mark_safe(f'<span style="{s}background:#16a34a;">&#10003; Approved</span>')
        if not obj.is_email_verified:
            return mark_safe(f'<span style="{s}background:#6b7280;">&#9711; Unverified</span>')
        return mark_safe(f'<span style="{s}background:#d97706;">&#9203; Pending</span>')

    @admin.display(description='Actions')
    def quick_actions(self, obj):
        if obj.is_staff:
            return mark_safe('<span style="color:#6b7280;">—</span>')

        approve_url = reverse('admin:accounts_user_approve', args=[obj.pk])
        reject_url  = reverse('admin:accounts_user_reject',  args=[obj.pk])

        s = ('padding:3px 12px;border-radius:20px;font-size:11px;font-weight:600;'
             'text-decoration:none;white-space:nowrap;color:#fff;')

        if obj.is_approved:
            return format_html(
                '<a href="{}" style="' + s + 'background:#b45309" '
                'data-msg="Revoke approval for {}?" '
                'onclick="adminConfirm(this.dataset.msg,this.href,\'revoke\');return false;">&#10005; Revoke</a>',
                reject_url, obj.name,
            )
        return format_html(
            '<span style="display:inline-flex;gap:5px;align-items:center;">'
            '<a href="{}" style="' + s + 'background:#16a34a" '
            'data-msg="Approve {} and send notification email?" '
            'onclick="adminConfirm(this.dataset.msg,this.href,\'approve\');return false;">&#10003; Approve</a>'
            '<a href="{}" style="' + s + 'background:#dc2626" '
            'data-msg="Reject {}? They will not be able to access services." '
            'onclick="adminConfirm(this.dataset.msg,this.href,\'reject\');return false;">&#10007; Reject</a>'
            '</span>',
            approve_url, obj.name, reject_url, obj.name,
        )

    # ── Bulk actions ──────────────────────────────────────────────────────────

    @admin.action(description='✔ Approve selected users (grant service access)')
    def approve_users(self, request, queryset):
        to_approve = list(queryset.filter(is_approved=False, is_email_verified=True))
        updated    = queryset.filter(is_approved=False, is_email_verified=True).update(is_approved=True)
        for user in to_approve:
            send_approved_email(user)
        self.message_user(request, f'{updated} user(s) approved and notified by email.', messages.SUCCESS)

    @admin.action(description='✖ Revoke approval (restrict service requests)')
    def revoke_approval(self, request, queryset):
        updated = queryset.filter(is_approved=True, is_staff=False).update(is_approved=False)
        self.message_user(request, f'{updated} user(s) approval revoked.', messages.WARNING)


# ─── Service ─────────────────────────────────────────────────────────────────

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display       = ['name', 'user', 'charge', 'status_display', 'due_date', 'created_at']
    list_filter        = ['status', 'created_at']
    list_display_links = ['name']
    search_fields      = ['name', 'user__email', 'user__name']
    ordering           = ['status', '-created_at']
    readonly_fields    = ['created_at', 'updated_at']
    inlines            = [InvoiceInline]

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


@admin.register(ServiceDocument)
class DocumentAdmin(admin.ModelAdmin):
    list_display    = ['file_name', 'service', 'client_email', 'doc_status', 'reupload_flag', 'doc_file', 'doc_actions', 'uploaded_at']
    list_filter     = ['status', 'is_reupload', 'is_downloaded', 'uploaded_at']
    search_fields   = ['file_name', 'service__name', 'service__user__email']
    ordering        = ['-uploaded_at']
    readonly_fields = ['uploaded_at', 'is_downloaded', 'status']

    class Media:
        js = ('accounts/js/doc_row_color.js', 'accounts/js/admin_confirm.js')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('service', 'service__user')

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('<int:pk>/download/', self.admin_site.admin_view(self._mark_download_view), name='accounts_doc_download'),
            path('<int:pk>/view/',     self.admin_site.admin_view(self._view_file_view),      name='accounts_doc_view'),
            path('<int:pk>/reject/',   self.admin_site.admin_view(self._reject_view),         name='accounts_doc_reject'),
            path('<int:pk>/restore/',  self.admin_site.admin_view(self._restore_view),        name='accounts_doc_restore'),
        ]
        return custom + urls

    def _view_file_view(self, request, pk):
        doc = get_object_or_404(ServiceDocument, pk=pk)
        if not doc.file:
            raise Http404('No file attached.')
        filename = doc.file_name or os.path.basename(doc.file.name)
        mime, _ = mimetypes.guess_type(filename)
        response = FileResponse(doc.file.open('rb'), content_type=mime or 'application/octet-stream')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        return response

    def _mark_download_view(self, request, pk):
        doc = get_object_or_404(ServiceDocument, pk=pk)
        if not doc.file:
            messages.error(request, 'No file attached to this document.')
            return redirect(reverse('admin:accounts_servicedocument_changelist'))
        doc.is_downloaded = True
        doc.save(update_fields=['is_downloaded'])
        filename = doc.file_name or os.path.basename(doc.file.name)
        return FileResponse(doc.file.open('rb'), as_attachment=True, filename=filename)

    def _reject_view(self, request, pk):
        doc = get_object_or_404(ServiceDocument, pk=pk)
        doc.status = 'rejected'
        doc.save(update_fields=['status'])
        messages.warning(request, f'Document "{doc.file_name}" has been rejected.')
        return redirect(reverse('admin:accounts_servicedocument_changelist'))

    def _restore_view(self, request, pk):
        doc = get_object_or_404(ServiceDocument, pk=pk)
        doc.status = 'active'
        doc.save(update_fields=['status'])
        messages.success(request, f'Document "{doc.file_name}" has been restored to active.')
        return redirect(reverse('admin:accounts_servicedocument_changelist'))

    @admin.display(description='Client')
    def client_email(self, obj):
        return obj.service.user.email

    @admin.display(description='Re-upload')
    def reupload_flag(self, obj):
        return mark_safe(_reupload_badge_html(obj.is_reupload))

    @admin.display(description='Status')
    def doc_status(self, obj):
        base = ('display:inline-block;white-space:nowrap;padding:3px 12px;'
                'border-radius:20px;font-size:11px;font-weight:700;')
        if obj.status == 'rejected':
            badge = (f'<span data-badge-type="rejected" '
                     f'style="{base}background:#fee2e2;color:#b91c1c;">🚫 Rejected</span>')
            status_attr = 'rejected'
        elif obj.is_downloaded:
            badge = (f'<span data-badge-type="downloaded" '
                     f'style="{base}background:#dcfce7;color:#15803d;">✅ Downloaded</span>')
            status_attr = 'downloaded'
        else:
            badge = (f'<span data-badge-type="pending" '
                     f'style="{base}background:#e0e7ff;color:#3730a3;">⏳ Pending</span>')
            status_attr = 'pending'
        return format_html(
            '<span data-doc-status="{}" style="white-space:nowrap">{}</span>',
            status_attr, mark_safe(badge),
        )

    @admin.display(description='File')
    def doc_file(self, obj):
        if not obj.file:
            return mark_safe('<span style="color:#aaa;font-size:12px">No file</span>')
        view_url     = reverse('admin:accounts_doc_view',     args=[obj.pk])
        download_url = reverse('admin:accounts_doc_download', args=[obj.pk])
        s = 'padding:3px 10px;border-radius:16px;font-size:11px;font-weight:600;text-decoration:none;white-space:nowrap;'
        view_link = format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer" '
            'style="{}color:#1d4ed8;background:#dbeafe;margin-right:5px">👁 View</a>',
            view_url, s,
        )
        if obj.is_downloaded:
            dl_link = format_html(
                '<a href="{}" style="{}color:#fff;background:#16a34a">🔄 Re-download</a>',
                download_url, s,
            )
        else:
            dl_link = format_html(
                '<a href="{}" style="{}color:#fff;background:#2563eb">⬇ Download</a>',
                download_url, s,
            )
        return format_html('{}{}', view_link, dl_link)

    @admin.display(description='Actions')
    def doc_actions(self, obj):
        s = 'padding:3px 12px;border-radius:16px;font-size:11px;font-weight:600;text-decoration:none;white-space:nowrap;color:#fff;'
        if obj.status == 'rejected':
            restore_url = reverse('admin:accounts_doc_restore', args=[obj.pk])
            return format_html(
                '<a href="{}" style="{}background:#6b7280" '
                'data-msg="Restore \'{}\'?" '
                'onclick="adminConfirm(this.dataset.msg,this.href,\'approve\');return false;">↩ Restore</a>',
                restore_url, s, obj.file_name,
            )
        reject_url = reverse('admin:accounts_doc_reject', args=[obj.pk])
        return format_html(
            '<a href="{}" style="{}background:#dc2626" '
            'data-msg="Reject document \'{}\'? This cannot be undone easily." '
            'onclick="adminConfirm(this.dataset.msg,this.href,\'reject\');return false;">✕ Reject</a>',
            reject_url, s, obj.file_name,
        )


# ─── Proforma / Generated Invoices ───────────────────────────────────────────

def _format_customer_address(user):
    parts = [user.name.upper()]
    if user.company:    parts.append(user.company)
    if user.address:    parts.append(user.address)
    if user.gst_number: parts.append(f'GSTIN/UIN : {user.gst_number}')
    return '\n'.join(p for p in parts if p)


class InvoiceAdminForm(forms.ModelForm):
    class Meta:
        model   = Invoice
        exclude = ['subtotal', 'gst_amount', 'total', 'created_by']
        widgets = {
            'ship_to': forms.Textarea(attrs={
                'rows': 5,
                'style': 'width:100%;font-family:monospace;font-size:12px;resize:vertical;',
                'placeholder': 'Auto-filled from customer profile when a customer is selected.',
            }),
            'bill_to': forms.Textarea(attrs={
                'rows': 5,
                'style': 'width:100%;font-family:monospace;font-size:12px;resize:vertical;',
                'placeholder': 'Auto-filled from customer profile when a customer is selected.',
            }),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def save(self, commit=True):
        obj = super().save(commit=False)
        # Auto-populate ship_to / bill_to from user profile if still blank
        if getattr(obj, 'user_id', None):
            addr = _format_customer_address(obj.user)
            if not obj.ship_to:
                obj.ship_to = addr
            if not obj.bill_to:
                obj.bill_to = addr
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class InvoiceItemInline(admin.TabularInline):
    model               = InvoiceItem
    extra               = 1
    min_num             = 0
    fields              = ['service_name', 'month', 'year', 'hsn_code', 'quantity', 'per', 'amount']
    verbose_name        = 'Service Line'
    verbose_name_plural = 'Service Lines'

    def get_formset(self, request, obj=None, **kwargs):
        fs = super().get_formset(request, obj, **kwargs)
        fs.form.base_fields['year'].initial    = datetime.date.today().year
        fs.form.base_fields['month'].initial   = datetime.date.today().month
        fs.form.base_fields['quantity'].initial = 1
        fs.form.base_fields['per'].initial     = 'Month'
        return fs


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    form                = InvoiceAdminForm
    autocomplete_fields = ['user']
    inlines             = [InvoiceItemInline]
    list_display    = ['invoice_number', 'customer_col', 'services_col', 'subtotal_col', 'gst_col', 'total_col', 'created_at']
    list_filter     = ['gst_rate', 'created_at']
    search_fields   = ['invoice_number', 'user__email', 'user__name', 'user__company']
    ordering        = ['-created_at']

    class Media:
        js = ('accounts/js/invoice_lookup.js',)

    def get_readonly_fields(self, request, obj=None):
        base = ['subtotal', 'gst_amount', 'total', 'created_at', 'customer_info']
        if obj is None:
            base.append('invoice_number')  # auto-generated on add; editable on change form
        return base

    def get_fieldsets(self, request, obj=None):
        address_section = ('Ship To / Bill To', {
            'description': 'Auto-filled from the customer profile when a customer is selected. Edit freely to customise the addresses on the printed invoice.',
            'fields': (('ship_to', 'bill_to'),),
        })
        billing_section = ('Billing', {
            'description': 'Add service lines in the table below — totals recalculate when you save.',
            'fields': ('gst_rate', 'subtotal', 'gst_amount', 'total'),
        })
        notes_section = ('Attachment & Notes', {
            'fields': ('uploaded_pdf', 'notes'),
            'classes': ('collapse',),
            'description': (
                'Upload a ready-made PDF to send instead of auto-generating. '
                'Notes are printed at the bottom of the generated invoice.'
            ),
        })
        if obj is None:
            return [
                ('Customer', {
                    'description': 'Search and select a registered customer. Their profile details will appear below.',
                    'fields': ('user', 'customer_info'),
                }),
                address_section,
                billing_section,
                notes_section,
            ]
        return [
            ('Customer', {
                'description': 'Search and select a registered customer. Their profile details will appear below.',
                'fields': ('user', 'customer_info'),
            }),
            ('Invoice Reference', {
                'fields': (('invoice_number', 'created_at'),),
            }),
            address_section,
            billing_section,
            notes_section,
        ]

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        obj.recalculate()
        obj.save(update_fields=['subtotal', 'gst_amount', 'total'])

        if not change:
            try:
                from .pdf import generate_invoice_pdf
                if obj.uploaded_pdf:
                    obj.uploaded_pdf.open('rb')
                    pdf_bytes = obj.uploaded_pdf.read()
                    obj.uploaded_pdf.close()
                else:
                    pdf_bytes = generate_invoice_pdf(obj)
                send_invoice_email(obj, pdf_bytes)
            except Exception as exc:
                messages.warning(
                    request,
                    f'Invoice saved, but the notification email to {obj.user.email} could not be sent: {exc}. '
                    'Check your SMTP settings.',
                )

    # ── List display ─────────────────────────────────────────────────────────

    @admin.display(description='Customer')
    def customer_col(self, obj):
        return format_html(
            '<strong>{}</strong><br><small style="color:#888">{}</small>',
            obj.user.name, obj.user.email,
        )

    @admin.display(description='Services')
    def services_col(self, obj):
        items = list(obj.items.all())
        if not items:
            return mark_safe('<span style="color:#aaa;font-style:italic">—</span>')
        names = [i.service_name for i in items[:2]]
        if len(items) > 2:
            names.append(f'+{len(items) - 2} more')
        return ', '.join(names)

    @admin.display(description='Subtotal')
    def subtotal_col(self, obj):
        return format_html('<span style="font-family:monospace">₹ {}</span>', f'{obj.subtotal:,.2f}')

    @admin.display(description='GST')
    def gst_col(self, obj):
        return format_html('<span style="font-family:monospace;color:#777">₹ {}</span>', f'{obj.gst_amount:,.2f}')

    @admin.display(description='Total')
    def total_col(self, obj):
        return format_html('<strong style="font-family:monospace">₹ {}</strong>', f'{obj.total:,.2f}')

    # ── Readonly detail ───────────────────────────────────────────────────────

    @admin.display(description='Customer Details')
    def customer_info(self, obj):
        if not obj or not getattr(obj, 'user_id', None):
            return mark_safe(
                '<span style="color:#9ca3af;font-style:italic;font-size:12px;">'
                'Select a customer above ↑ — details appear here after you save.'
                '</span>'
            )
        u     = obj.user
        lines = [f'<strong>{u.name}</strong>']
        if u.company:
            lines.append(u.company)
        if u.gst_number:
            lines.append(f'GSTIN: <strong>{u.gst_number}</strong>')
        if u.address:
            lines.append(u.address.replace('\n', '<br>'))
        if u.phone:
            lines.append(f'📞 {u.phone}')
        return mark_safe(
            '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;'
            'padding:10px 14px;line-height:1.9;font-size:13px;margin-top:4px;">'
            + '<br>'.join(lines) + '</div>'
        )


# ─── Contact Messages ─────────────────────────────────────────────────────────

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display    = ['name', 'email', 'phone', 'company', 'short_message', 'read_status', 'submitted_at']
    list_filter     = ['is_read', 'submitted_at']
    search_fields   = ['name', 'email', 'phone', 'company', 'message']
    ordering        = ['-submitted_at']
    readonly_fields = ['name', 'email', 'phone', 'company', 'message', 'submitted_at']
    actions         = ['mark_read', 'mark_unread']

    fieldsets = (
        ('Contact Details', {'fields': ('name', 'email', 'phone', 'company', 'submitted_at')}),
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
        return False
