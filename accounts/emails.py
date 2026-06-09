import secrets
from django.core.mail import send_mail
from django.conf import settings


def generate_otp(user):
    from .models import EmailOTP
    EmailOTP.objects.filter(user=user, is_used=False).update(is_used=True)
    otp = str(secrets.randbelow(900000) + 100000)
    EmailOTP.objects.create(user=user, otp=otp)
    return otp


def _base(content: str) -> str:
    return f"""
<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
  <div style="background:#1A1A2E;padding:28px 32px;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;letter-spacing:1px;">MIDRUS</h1>
    <p style="color:#9ca3af;margin:6px 0 0;font-size:12px;">Accounting, Tax &amp; Compliance Portal</p>
  </div>
  <div style="padding:36px 32px;">{content}</div>
  <div style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:14px 32px;text-align:center;">
    <p style="color:#9ca3af;font-size:11px;margin:0;">© 2026 MIDRUS. All rights reserved.</p>
  </div>
</div>"""


def send_otp_email(user, otp: str) -> None:
    body = f"""
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">Verify Your Email</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 24px;">
      Hi {user.name}, use the OTP below to verify your email address.
      It expires in <strong>10 minutes</strong>.
    </p>
    <div style="background:#f9fafb;border:2px dashed #e5e7eb;border-radius:12px;padding:24px;text-align:center;margin:0 0 24px;">
      <p style="color:#9ca3af;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Your OTP</p>
      <p style="color:#1A1A2E;font-size:42px;font-weight:800;letter-spacing:14px;margin:0;">{otp}</p>
    </div>
    <p style="color:#9ca3af;font-size:13px;margin:0;">
      If you didn't create a MIDRUS account, you can safely ignore this email.
    </p>"""
    send_mail(
        subject='Verify your MIDRUS account — OTP inside',
        message=f'Your MIDRUS verification OTP is: {otp}\n\nIt expires in 10 minutes.',
        html_message=_base(body),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_login_otp_email(user, otp: str) -> None:
    body = f"""
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">Login Verification</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 24px;">
      Hi {user.name}, use the OTP below to complete your sign-in.
      It expires in <strong>10 minutes</strong>.
    </p>
    <div style="background:#f9fafb;border:2px dashed #e5e7eb;border-radius:12px;padding:24px;text-align:center;margin:0 0 24px;">
      <p style="color:#9ca3af;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Your OTP</p>
      <p style="color:#1A1A2E;font-size:42px;font-weight:800;letter-spacing:14px;margin:0;">{otp}</p>
    </div>
    <p style="color:#9ca3af;font-size:13px;margin:0;">
      If you didn't attempt to log in, please ignore this email and your account remains secure.
    </p>"""
    send_mail(
        subject='MIDRUS login OTP',
        message=f'Your MIDRUS login OTP is: {otp}\n\nIt expires in 10 minutes.',
        html_message=_base(body),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_pending_email(user) -> None:
    body = f"""
    <p style="font-size:28px;margin:0 0 16px;">⏳</p>
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">Account Under Review</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 12px;">
      Hi {user.name}, your email has been verified successfully!
    </p>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0;">
      Your account is now <strong style="color:#d97706;">pending admin approval</strong>.
      Our team will review your details and you'll receive another email once approved.
    </p>"""
    send_mail(
        subject='MIDRUS — Account received, pending approval',
        message=f'Hi {user.name}, your email is verified. Your MIDRUS account is pending admin approval.',
        html_message=_base(body),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


def send_admin_signup_notification(user) -> None:
    admin_url = f"{settings.FRONTEND_URL.replace('3000', '8000')}/admin/accounts/user/?q={user.email}"
    body = f"""
    <p style="font-size:28px;margin:0 0 16px;">🔔</p>
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">New User Signed Up</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 16px;">
      A new user has verified their email and is waiting for service request access.
    </p>
    <table style="width:100%;border-collapse:collapse;margin:0 0 24px;">
      <tr><td style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;font-weight:600;width:30%;color:#374151;">Name</td>
          <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;">{user.name}</td></tr>
      <tr><td style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;font-weight:600;color:#374151;">Email</td>
          <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;">{user.email}</td></tr>
      <tr><td style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;font-weight:600;color:#374151;">Company</td>
          <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;">{user.company or '—'}</td></tr>
      <tr><td style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;font-weight:600;color:#374151;">Phone</td>
          <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;">{user.phone or '—'}</td></tr>
    </table>
    <a href="{admin_url}"
       style="display:inline-block;background:#1A1A2E;color:#fff;text-decoration:none;
              padding:14px 32px;border-radius:8px;font-weight:700;font-size:15px;">
      Review &amp; Approve in Admin →
    </a>"""
    admin_email = getattr(settings, 'ADMIN_EMAIL', settings.EMAIL_HOST_USER)
    if not admin_email:
        return
    send_mail(
        subject=f'MIDRUS — New signup: {user.name} ({user.email})',
        message=f'New user signed up: {user.name} ({user.email}). Review in admin panel.',
        html_message=_base(body),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[admin_email],
        fail_silently=True,
    )


def send_approved_email(user) -> None:
    login_url = f"{settings.FRONTEND_URL}/login"
    body = f"""
    <p style="font-size:28px;margin:0 0 16px;">✅</p>
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">Account Approved!</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 12px;">
      Hi {user.name}, great news — your MIDRUS account has been
      <strong style="color:#16a34a;">approved</strong>!
    </p>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 32px;">
      You can now log in to access your dashboard, view your services, and manage your invoices.
    </p>
    <a href="{login_url}"
       style="display:inline-block;background:#1A1A2E;color:#fff;text-decoration:none;
              padding:14px 32px;border-radius:8px;font-weight:700;font-size:15px;">
      Log In to Dashboard →
    </a>"""
    send_mail(
        subject='MIDRUS — Your account has been approved!',
        message=f'Hi {user.name}, your MIDRUS account has been approved. Log in at: {login_url}',
        html_message=_base(body),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
