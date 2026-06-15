import secrets
from django.core.mail import send_mail, EmailMultiAlternatives
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


def send_admin_signup_notification(user) -> None:
    admin_url = f"{settings.BACKEND_URL}/admin/accounts/user/?q={user.email}"
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


def send_invoice_email(invoice, pdf_bytes: bytes | None = None) -> None:
    MONTHS = ['January','February','March','April','May','June',
              'July','August','September','October','November','December']

    user        = invoice.user
    payment_url = f"{settings.FRONTEND_URL}/dashboard/payment"
    items       = list(invoice.items.all())

    # Build service summary rows for email
    service_rows = ''
    for item in items:
        period = f'{MONTHS[item.month - 1]} {item.year}'
        service_rows += f'''
      <tr>
        <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;">{item.service_name}</td>
        <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#6b7280;text-align:center;">{period}</td>
        <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;text-align:right;">&#8377; {float(item.amount):,.2f}</td>
      </tr>'''

    body = f"""
    <p style="font-size:28px;margin:0 0 16px;">🧾</p>
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">New Invoice from MIDRUS</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 24px;">
      Hi {user.name}, a new invoice has been raised for your account.
      The invoice PDF is attached. Please review and complete the payment at your earliest convenience.
    </p>

    <table style="width:100%;border-collapse:collapse;margin:0 0 6px;font-size:14px;">
      <tr style="background:#f9fafb;">
        <th style="padding:8px 12px;border:1px solid #e5e7eb;text-align:left;color:#374151;">Service</th>
        <th style="padding:8px 12px;border:1px solid #e5e7eb;text-align:center;color:#374151;">Period</th>
        <th style="padding:8px 12px;border:1px solid #e5e7eb;text-align:right;color:#374151;">Amount</th>
      </tr>
      {service_rows}
    </table>

    <table style="width:100%;border-collapse:collapse;margin:0 0 24px;font-size:14px;">
      <tr>
        <td style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;font-weight:600;color:#374151;width:50%;">Subtotal</td>
        <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#111827;text-align:right;">&#8377; {float(invoice.subtotal):,.2f}</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;font-weight:600;color:#374151;">GST ({invoice.gst_rate}%)</td>
        <td style="padding:8px 12px;border:1px solid #e5e7eb;color:#6b7280;text-align:right;">&#8377; {float(invoice.gst_amount):,.2f}</td>
      </tr>
      <tr style="background:#1A1A2E;">
        <td style="padding:12px 14px;font-weight:700;color:#fff;border:1px solid #1A1A2E;">Total Payable</td>
        <td style="padding:12px 14px;font-weight:800;color:#fff;border:1px solid #1A1A2E;font-size:16px;text-align:right;">&#8377; {float(invoice.total):,.2f}</td>
      </tr>
    </table>

    <p style="color:#6b7280;font-size:13px;margin:0 0 8px;">
      Invoice No: <strong style="color:#111;">{invoice.invoice_number}</strong>
      &nbsp;|&nbsp; Ref: <code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;">{invoice.invoice_number}</code>
    </p>

    <p style="color:#6b7280;font-size:14px;line-height:1.6;margin:0 0 24px;">
      Log in to your MIDRUS portal to view the invoice online and pay via UPI.
    </p>

    <a href="{payment_url}"
       style="display:inline-block;background:#1A1A2E;color:#fff;text-decoration:none;
              padding:14px 32px;border-radius:8px;font-weight:700;font-size:15px;">
      View Invoice &amp; Pay &#8594;
    </a>

    <p style="color:#9ca3af;font-size:12px;margin:24px 0 0;">
      Questions? Contact us at
      <a href="mailto:info@midrusindia.com" style="color:#374151;">info@midrusindia.com</a>
    </p>"""

    plain = (
        f'Hi {user.name},\n\n'
        f'Invoice {invoice.invoice_number} has been raised.\n'
        f'Total: Rs. {float(invoice.total):,.2f}\n\n'
        f'View & pay: {payment_url}'
    )

    email = EmailMultiAlternatives(
        subject=f'MIDRUS Invoice {invoice.invoice_number} — ₹{float(invoice.total):,.2f}',
        body=plain,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach_alternative(_base(body), 'text/html')
    if pdf_bytes:
        email.attach(f'{invoice.invoice_number}.pdf', pdf_bytes, 'application/pdf')
    email.send(fail_silently=True)


def send_password_reset_email(user, otp: str) -> None:
    body = f"""
    <p style="font-size:28px;margin:0 0 16px;">🔐</p>
    <h2 style="color:#1A1A2E;font-size:20px;font-weight:700;margin:0 0 12px;">Reset Your Password</h2>
    <p style="color:#6b7280;font-size:15px;line-height:1.6;margin:0 0 24px;">
      Hi {user.name}, use the OTP below to reset your MIDRUS account password.
      It expires in <strong>10 minutes</strong>.
    </p>
    <div style="background:#f9fafb;border:2px dashed #e5e7eb;border-radius:12px;padding:24px;text-align:center;margin:0 0 24px;">
      <p style="color:#9ca3af;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin:0 0 8px;">Password Reset OTP</p>
      <p style="color:#1A1A2E;font-size:42px;font-weight:800;letter-spacing:14px;margin:0;">{otp}</p>
    </div>
    <p style="color:#9ca3af;font-size:13px;margin:0;">
      If you didn't request a password reset, ignore this email — your password won't change.
    </p>"""
    send_mail(
        subject='MIDRUS — Password reset OTP',
        message=f'Your MIDRUS password reset OTP is: {otp}\n\nIt expires in 10 minutes.',
        html_message=_base(body),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
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
