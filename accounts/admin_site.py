"""Two-step sign-in for the web admin panel (/admin/).

Step 1 is the usual email + password. A correct password does NOT log anyone
in: it emails a one-time code (the same code system the apps use, including
its 10-minute expiry and wrong-guess lockout) and only entering that code
starts the session. Turn it off for local development with
ADMIN_REQUIRE_OTP=False.
"""
import logging
import time

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import REDIRECT_FIELD_NAME, login as auth_login
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers

logger = logging.getLogger(__name__)

PENDING_KEY = 'admin_otp_pending'
RESEND_COOLDOWN_SECONDS = 30


def _mask(email: str) -> str:
    name, _, domain = email.partition('@')
    return f'{name[:2]}{"*" * max(len(name) - 2, 1)}@{domain}'


class MidrusAdminSite(admin.AdminSite):
    site_header = 'MIDRUS administration'

    @method_decorator(never_cache)
    @method_decorator(csrf_protect)
    def login(self, request, extra_context=None):
        if not getattr(settings, 'ADMIN_REQUIRE_OTP', True):
            return super().login(request, extra_context)
        # Already signed in as staff: the stock view just redirects onward.
        if request.method == 'GET' and request.user.is_active and request.user.is_staff:
            return super().login(request, extra_context)

        if request.method == 'POST':
            step = request.POST.get('step')
            if step == 'otp':
                return self._verify_code(request, extra_context)
            if step == 'resend':
                return self._resend_code(request, extra_context)
            if step == 'back':
                request.session.pop(PENDING_KEY, None)
                return HttpResponseRedirect(request.get_full_path())
            return self._check_password(request, extra_context)

        request.session.pop(PENDING_KEY, None)
        return super().login(request, extra_context)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _next_url(self, request):
        target = request.POST.get(REDIRECT_FIELD_NAME) or request.GET.get(REDIRECT_FIELD_NAME)
        if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            return target
        return reverse('admin:index', current_app=self.name)

    def _code_page(self, request, user, extra_context, *, error='', info=''):
        context = {
            **self.each_context(request),
            'title': 'Verify your sign-in',
            'masked_email': _mask(user.email),
            'error': error,
            'info': info,
            'app_path': request.get_full_path(),
            REDIRECT_FIELD_NAME: self._next_url(request),
            **(extra_context or {}),
        }
        return TemplateResponse(request, 'admin/otp_login.html', context)

    def _pending_user(self, request):
        from .models import User

        pending = request.session.get(PENDING_KEY)
        if not pending:
            return None
        if time.time() - pending['at'] > settings.OTP_TTL_SECONDS:
            request.session.pop(PENDING_KEY, None)
            return None
        return User.objects.filter(pk=pending['uid'], is_active=True, is_staff=True).first()

    def _send_code(self, user):
        from .emails import generate_otp, send_login_otp_email

        send_login_otp_email(user, generate_otp(user))

    # ── steps ────────────────────────────────────────────────────────────────

    def _check_password(self, request, extra_context):
        form = AdminAuthenticationForm(request, data=request.POST)
        if not form.is_valid():
            # Wrong password / not staff: the stock view shows the usual errors
            # (it re-checks and, being invalid, never logs anyone in).
            return super().login(request, extra_context)
        user = form.get_user()
        try:
            self._send_code(user)
        except Exception:
            logger.exception('Admin sign-in code to %s failed', user.email)
            form.add_error(None, 'We could not email your sign-in code. Please try again.')
            context = {
                **self.each_context(request),
                'title': 'Log in',
                'app_path': request.get_full_path(),
                'form': form,
                REDIRECT_FIELD_NAME: self._next_url(request),
                **(extra_context or {}),
            }
            return TemplateResponse(request, self.login_template or 'admin/login.html', context)
        now = time.time()
        request.session[PENDING_KEY] = {'uid': user.pk, 'at': now, 'sent': now}
        return self._code_page(
            request, user, extra_context, info='We emailed a 6-digit code to your address.',
        )

    def _verify_code(self, request, extra_context):
        from .security import consume_otp

        user = self._pending_user(request)
        if user is None:
            request.session.pop(PENDING_KEY, None)
            return HttpResponseRedirect(request.get_full_path())
        try:
            consume_otp(user, (request.POST.get('otp') or '').strip())
        except serializers.ValidationError as exc:
            return self._code_page(request, user, extra_context, error=str(exc.detail[0]))
        request.session.pop(PENDING_KEY, None)
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        auth_login(request, user)  # also rotates the session key
        return HttpResponseRedirect(self._next_url(request))

    def _resend_code(self, request, extra_context):
        user = self._pending_user(request)
        if user is None:
            request.session.pop(PENDING_KEY, None)
            return HttpResponseRedirect(request.get_full_path())
        pending = request.session[PENDING_KEY]
        wait = RESEND_COOLDOWN_SECONDS - (time.time() - pending.get('sent', 0))
        if wait > 0:
            return self._code_page(
                request, user, extra_context,
                error=f'Please wait {int(wait) + 1}s before asking for a new code.',
            )
        try:
            self._send_code(user)
        except Exception:
            logger.exception('Admin sign-in code resend to %s failed', user.email)
            return self._code_page(
                request, user, extra_context,
                error='We could not email a new code. Please try again.',
            )
        pending['sent'] = time.time()
        request.session[PENDING_KEY] = pending
        return self._code_page(request, user, extra_context, info='A new code is on its way.')
