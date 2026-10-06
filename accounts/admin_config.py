"""django.contrib.admin, but using our two-step (password + emailed code) sign-in."""
from django.contrib.admin.apps import AdminConfig


class MidrusAdminConfig(AdminConfig):
    default_site = 'accounts.admin_site.MidrusAdminSite'
