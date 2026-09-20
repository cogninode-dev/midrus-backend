from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views, admin_api, files

urlpatterns = [
    # Signed, expiring file downloads (uploads are never served from /media/)
    path('files/<str:token>/', files.file_download, name='file-download'),

    # Public
    path('contact/',         views.contact,         name='contact'),

    # Auth
    path('register/',        views.register,        name='register'),
    path('verify-email/',    views.verify_email,    name='verify-email'),
    path('resend-otp/',      views.resend_otp,      name='resend-otp'),
    path('login/',              views.login,              name='login'),
    path('verify-login-otp/',   views.verify_login_otp,   name='verify-login-otp'),
    path('resend-login-otp/',   views.resend_login_otp,   name='resend-login-otp'),
    path('logout/',             views.logout,             name='logout'),
    path('me/',              views.me,              name='me'),
    path('profile/update/',  views.update_profile,  name='update-profile'),
    path('password/change/', views.change_password, name='change-password'),
    path('token/refresh/',   TokenRefreshView.as_view(), name='token-refresh'),

    # Dashboard
    path('dashboard/stats/', views.dashboard_stats, name='dashboard-stats'),

    # Services
    path('services/',             views.service_list,    name='service-list'),
    path('services/request/',     views.service_request, name='service-request'),
    path('services/<int:pk>/',    views.service_detail,  name='service-detail'),

    # Invoices (file documents)
    path('services/<int:service_pk>/invoices/',                        views.invoice_add,    name='invoice-add'),
    path('services/<int:service_pk>/invoices/<int:invoice_pk>/',       views.invoice_delete, name='invoice-delete'),

    # Proforma Invoices
    path('proforma-invoices/',  views.proforma_invoice_list, name='proforma-invoice-list'),
    path('admin/user-lookup/', views.admin_user_lookup,     name='admin-user-lookup'),

    # In-app admin panel (staff only)
    path('admin/overview/',                    admin_api.overview,               name='admin-overview'),
    path('admin/users/',                       admin_api.users,                  name='admin-users'),
    path('admin/users/<int:pk>/approval/',     admin_api.user_approval,          name='admin-user-approval'),
    path('admin/services/',                    admin_api.services,               name='admin-services'),
    path('admin/services/<int:pk>/',           admin_api.service_update,         name='admin-service-update'),
    path('admin/documents/',                   admin_api.documents,              name='admin-documents'),
    path('admin/documents/<int:pk>/reject/',   admin_api.document_reject,        name='admin-document-reject'),
    path('admin/documents/<int:pk>/restore/',  admin_api.document_restore,       name='admin-document-restore'),
    path('admin/documents/<int:pk>/downloaded/', admin_api.document_mark_downloaded, name='admin-document-downloaded'),
    path('admin/messages/',                    admin_api.messages,               name='admin-messages'),
    path('admin/messages/<int:pk>/',           admin_api.message_update,         name='admin-message-update'),
    path('admin/invoices/',                    admin_api.invoices,               name='admin-invoices'),

    # Self-service password reset
    path('password-reset/',         views.password_reset_request, name='password-reset-request'),
    path('password-reset/confirm/', views.password_reset_confirm, name='password-reset-confirm'),
]
