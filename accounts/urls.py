from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # Public
    path('contact/',         views.contact,         name='contact'),

    # Auth
    path('register/',        views.register,        name='register'),
    path('login/',           views.login,           name='login'),
    path('logout/',          views.logout,          name='logout'),
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

    # Invoices
    path('services/<int:service_pk>/invoices/',                        views.invoice_add,    name='invoice-add'),
    path('services/<int:service_pk>/invoices/<int:invoice_pk>/',       views.invoice_delete, name='invoice-delete'),
]
