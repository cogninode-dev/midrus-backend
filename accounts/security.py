"""Small security helpers shared by the auth views and serializers."""
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers

from .models import EmailOTP, User


# ─── Email lookup ────────────────────────────────────────────────────────────

def normalize_email(value: str) -> str:
    return (value or '').strip().lower()


def get_user_by_email(email, **filters):
    """Case-insensitive user lookup.

    Emails are stored lower-cased from now on, but older accounts may contain
    capitals (and, rarely, two accounts that differ only by case). Prefer an
    exact match, then fall back to a case-insensitive one, and never raise
    MultipleObjectsReturned.
    """
    email = (email or '').strip()
    if not email:
        return None
    qs = User.objects.filter(**filters)
    return (
        qs.filter(email=email).first()
        or qs.filter(email__iexact=email).order_by('id').first()
    )


# ─── OTP attempt limiting ────────────────────────────────────────────────────
# A 6-digit code has only a million values, so per-IP throttling alone is not
# enough. Count wrong guesses per *user* (shared by login, email verification
# and password reset) and lock the code after OTP_MAX_ATTEMPTS misses.

def _fail_key(user) -> str:
    return f'otp-fails:{user.pk}'


def clear_otp_failures(user) -> None:
    cache.delete(_fail_key(user))


def _register_failure(user) -> None:
    key = _fail_key(user)
    try:
        cache.incr(key)
    except ValueError:  # key not set yet
        cache.set(key, 1, timeout=settings.OTP_TTL_SECONDS)


def consume_otp(user, code, *, invalid='Invalid OTP.', expired='OTP has expired. Please request a new one.'):
    """Validate and burn a one-time code, or raise a serializer ValidationError."""
    if cache.get(_fail_key(user), 0) >= settings.OTP_MAX_ATTEMPTS:
        raise serializers.ValidationError('Too many incorrect attempts. Please request a new code.')

    otp = (
        EmailOTP.objects.filter(user=user, otp=code, is_used=False)
        .order_by('-created_at')
        .first()
    )
    if otp is None:
        _register_failure(user)
        raise serializers.ValidationError(invalid)
    if not otp.is_valid():
        _register_failure(user)
        raise serializers.ValidationError(expired)

    otp.is_used = True
    otp.save(update_fields=['is_used'])
    clear_otp_failures(user)
    return otp


# ─── Token revocation ────────────────────────────────────────────────────────

def revoke_all_tokens(user) -> None:
    """Blacklist every outstanding refresh token (e.g. after a password reset)."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken, OutstandingToken,
    )
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
