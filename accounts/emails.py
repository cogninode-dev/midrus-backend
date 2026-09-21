import secrets
from datetime import date
from urllib.parse import quote

from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from django.utils.html import escape as esc

SUPPORT_EMAIL = 'info@midrusindia.com'

# Palette (mirrors the mobile app).
BRAND = '#5B45E0'
BRAND_DARK = '#3F2FB8'
INK = '#1E1B3A'
TEXT = '#3B3760'
MUTED = '#6E6A8F'
LINE = '#E7E5F4'
CANVAS = '#F3F2FA'
TINT = '#F0EEFF'
CYAN = '#4CC9F0'
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


def generate_otp(user):
    from .models import EmailOTP
    EmailOTP.objects.filter(user=user, is_used=False).update(is_used=True)
    otp = str(secrets.randbelow(900000) + 100000)
    EmailOTP.objects.create(user=user, otp=otp)
    # A fresh code starts with a clean slate of wrong-guess attempts.
    from .security import clear_otp_failures
    clear_otp_failures(user)
    return otp


# ── Building blocks ─────────────────────────────────────────────────────────
# Email clients (Outlook, Gmail) ignore most modern CSS, so everything is
# table-based with inline styles. Gradients are progressive enhancement over a
# solid fallback colour. Every dynamic value must be passed through esc().

def _base(content: str, preheader: str = '') -> str:
    year = date.today().year
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>MIDRUS</title>
<style>
  @media only screen and (max-width:620px) {{
    .container {{ width:100% !important; }}
    .px {{ padding-left:22px !important; padding-right:22px !important; }}
    .otp {{ font-size:34px !important; letter-spacing:8px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{CANVAS};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{CANVAS};font-size:1px;line-height:1px;">
  {esc(preheader)}&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{CANVAS}" style="background:{CANVAS};">
<tr><td align="center" style="padding:32px 12px;">

  <table role="presentation" class="container" width="560" cellpadding="0" cellspacing="0" border="0" style="width:560px;max-width:560px;">

    <!-- Header -->
    <tr><td class="px" align="center" bgcolor="{BRAND}"
        style="background:{BRAND};background-image:linear-gradient(135deg,#7A5CFF 0%,{BRAND} 48%,{BRAND_DARK} 100%);
               border-radius:20px 20px 0 0;padding:34px 32px 30px;font-family:{FONT};">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:middle;padding-right:10px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
            <td width="34" height="34" align="center" style="width:34px;height:34px;background:#ffffff;border-radius:10px;
                font-family:{FONT};font-size:19px;font-weight:800;color:{BRAND};line-height:34px;">M</td>
          </tr></table>
        </td>
        <td style="vertical-align:middle;font-family:{FONT};font-size:24px;font-weight:800;letter-spacing:3px;color:#ffffff;">MIDRUS</td>
      </tr></table>
      <p style="margin:10px 0 0;font-family:{FONT};font-size:13px;letter-spacing:.4px;color:#D9D3FF;">Accounting, Tax &amp; Compliance</p>
    </td></tr>

    <!-- Accent line -->
    <tr><td height="4" style="height:4px;line-height:4px;font-size:0;background:{CYAN};background-image:linear-gradient(90deg,{CYAN},#8B7BFF);">&nbsp;</td></tr>

    <!-- Body -->
    <tr><td class="px" bgcolor="#ffffff" style="background:#ffffff;padding:38px 40px 34px;font-family:{FONT};color:{TEXT};">
      {content}
    </td></tr>

    <!-- Footer -->
    <tr><td class="px" bgcolor="#FAF9FE" align="center"
        style="background:#FAF9FE;border-top:1px solid {LINE};border-radius:0 0 20px 20px;padding:22px 32px;font-family:{FONT};">
      <p style="margin:0 0 6px;font-size:12px;line-height:1.6;color:{MUTED};">
        Need help? Write to
        <a href="mailto:{SUPPORT_EMAIL}" style="color:{BRAND};text-decoration:none;font-weight:600;">{SUPPORT_EMAIL}</a>
      </p>
      <p style="margin:0;font-size:11px;line-height:1.6;color:#9C98B8;">
        &copy; {year} MIDRUS. All rights reserved.<br>
        This is an automated message &mdash; please don&rsquo;t reply directly.
      </p>
    </td></tr>

  </table>

</td></tr>
</table>
</body>
</html>"""


def _heading(icon: str, title: str, tint: str = TINT) -> str:
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 20px;"><tr>
        <td width="56" height="56" align="center" style="width:56px;height:56px;background:{tint};border-radius:18px;
            font-size:26px;line-height:56px;">{icon}</td>
      </tr></table>
      <h1 style="margin:0 0 12px;font-family:{FONT};font-size:26px;line-height:1.25;font-weight:800;color:{INK};letter-spacing:-.3px;">{title}</h1>"""


def _p(html: str, size: int = 15, color: str = TEXT, bottom: int = 20) -> str:
    return (f'<p style="margin:0 0 {bottom}px;font-family:{FONT};font-size:{size}px;'
            f'line-height:1.7;color:{color};">{html}</p>')


def _button(url: str, label: str) -> str:
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 4px;"><tr>
        <td align="center" bgcolor="{BRAND}" style="background:{BRAND};background-image:linear-gradient(135deg,#7A5CFF,{BRAND_DARK});border-radius:14px;">
          <a href="{esc(url)}" style="display:inline-block;padding:15px 34px;font-family:{FONT};font-size:15px;font-weight:700;
             color:#ffffff;text-decoration:none;border-radius:14px;">{label}</a>
        </td>
      </tr></table>"""


def _otp_block(label: str, otp: str, minutes: int = 10) -> str:
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 22px;"><tr>
        <td align="center" bgcolor="{TINT}" style="background:{TINT};border:1px solid #DDD8FF;border-radius:18px;padding:26px 16px 22px;">
          <p style="margin:0 0 10px;font-family:{FONT};font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{BRAND};">{esc(label)}</p>
          <p class="otp" style="margin:0;font-family:'SF Mono',Menlo,Consolas,'Courier New',monospace;font-size:44px;font-weight:800;
             letter-spacing:12px;color:{INK};line-height:1.1;">{esc(otp)}</p>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:16px auto 0;"><tr>
            <td style="background:#ffffff;border:1px solid #DDD8FF;border-radius:20px;padding:5px 14px;font-family:{FONT};font-size:12px;color:{MUTED};">
              &#9201; Expires in <strong style="color:{INK};">{minutes} minutes</strong>
            </td>
          </tr></table>
        </td>
      </tr></table>"""


def _notice(html: str, color: str = '#B45309', bg: str = '#FFF7E6', border: str = '#F8DFA8') -> str:
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 6px;"><tr>
        <td bgcolor="{bg}" style="background:{bg};border:1px solid {border};border-radius:12px;padding:12px 16px;
            font-family:{FONT};font-size:13px;line-height:1.6;color:{color};">{html}</td>
      </tr></table>"""


def _fineprint(html: str) -> str:
    return _p(html, size=13, color=MUTED, bottom=0)


def _kv_table(rows) -> str:
    """rows: list of (label, already-escaped value html)."""
    out = ''
    for i, (label, value) in enumerate(rows):
        border = f'border-top:1px solid {LINE};' if i else ''
        out += f"""
        <tr>
          <td style="{border}padding:12px 0;font-family:{FONT};font-size:13px;color:{MUTED};width:32%;vertical-align:top;">{label}</td>
          <td style="{border}padding:12px 0;font-family:{FONT};font-size:14px;font-weight:600;color:{INK};vertical-align:top;">{value}</td>
        </tr>"""
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin:4px 0 26px;background:#FAF9FE;border:1px solid {LINE};border-radius:14px;">
        <tr><td style="padding:6px 18px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{out}
          </table>
        </td></tr>
      </table>"""


# ── Emails ──────────────────────────────────────────────────────────────────

def send_otp_email(user, otp: str) -> None:
    body = (
        _heading('&#9993;&#65039;', 'Verify your email')
        + _p(f'Hi {esc(user.name)}, welcome to MIDRUS! Enter this code in the app to confirm your email address.')
        + _otp_block('Verification code', otp)
        + _notice('&#128274; <strong>Never share this code</strong> with anyone. MIDRUS staff will never ask for it.')
        + '<div style="height:16px;line-height:16px;">&nbsp;</div>'
        + _fineprint("If you didn't create a MIDRUS account, you can safely ignore this email.")
    )
    send_mail(
        subject='Verify your MIDRUS account — OTP inside',
        message=f'Your MIDRUS verification OTP is: {otp}\n\nIt expires in 10 minutes.',
        html_message=_base(body, f'Your MIDRUS verification code is {otp}'),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_login_otp_email(user, otp: str) -> None:
    body = (
        _heading('&#128272;', 'Confirm your sign-in')
        + _p(f'Hi {esc(user.name)}, use this code to finish signing in to your MIDRUS account.')
        + _otp_block('Sign-in code', otp)
        + _notice('&#128274; <strong>Never share this code</strong> with anyone. MIDRUS staff will never ask for it.')
        + '<div style="height:16px;line-height:16px;">&nbsp;</div>'
        + _fineprint("If this wasn't you, ignore this email — your account stays secure. "
                     "Consider changing your password if you keep receiving these.")
    )
    send_mail(
        subject='MIDRUS login OTP',
        message=f'Your MIDRUS login OTP is: {otp}\n\nIt expires in 10 minutes.',
        html_message=_base(body, f'Your MIDRUS sign-in code is {otp}'),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_password_reset_email(user, otp: str) -> None:
    body = (
        _heading('&#128273;', 'Reset your password', tint='#FFF1E6')
        + _p(f'Hi {esc(user.name)}, we received a request to reset your MIDRUS password. '
             'Enter this code in the app to choose a new one.')
        + _otp_block('Password reset code', otp)
        + _notice('&#128274; <strong>Never share this code</strong> with anyone. MIDRUS staff will never ask for it.')
        + '<div style="height:16px;line-height:16px;">&nbsp;</div>'
        + _fineprint("If you didn't request a reset, ignore this email — your password won't change.")
    )
    send_mail(
        subject='MIDRUS — Password reset OTP',
        message=f'Your MIDRUS password reset OTP is: {otp}\n\nIt expires in 10 minutes.',
        html_message=_base(body, f'Your MIDRUS password reset code is {otp}'),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_admin_signup_notification(user) -> None:
    admin_url = f"{settings.BACKEND_URL}/admin/accounts/user/?q={quote(user.email)}"
    body = (
        _heading('&#128276;', 'New user signed up')
        + _p('A new user has verified their email and is waiting for access to service requests.')
        + _kv_table([
            ('Name', esc(user.name)),
            ('Email', esc(user.email)),
            ('Company', esc(user.company or '—')),
            ('Phone', esc(user.phone or '—')),
        ])
        + _button(admin_url, 'Review &amp; approve &rarr;')
    )
    admin_email = getattr(settings, 'ADMIN_EMAIL', settings.EMAIL_HOST_USER)
    if not admin_email:
        return
    send_mail(
        subject=f'MIDRUS — New signup: {user.name} ({user.email})',
        message=f'New user signed up: {user.name} ({user.email}). Review in admin panel.',
        html_message=_base(body, f'{user.name} ({user.email}) is waiting for approval'),
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
    number      = esc(invoice.invoice_number)

    rows = ''
    for i, item in enumerate(items):
        period = f'{MONTHS[item.month - 1]} {item.year}'
        border = f'border-top:1px solid {LINE};' if i else ''
        rows += f"""
        <tr>
          <td style="{border}padding:13px 0;font-family:{FONT};font-size:14px;color:{INK};font-weight:600;">
            {esc(item.service_name)}<br>
            <span style="font-size:12px;font-weight:400;color:{MUTED};">{period}</span>
          </td>
          <td align="right" style="{border}padding:13px 0;font-family:{FONT};font-size:14px;color:{INK};white-space:nowrap;vertical-align:top;">
            &#8377;&nbsp;{float(item.amount):,.2f}
          </td>
        </tr>"""

    summary = f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 24px;"><tr>
        <td bgcolor="{BRAND}" align="center" style="background:{BRAND};background-image:linear-gradient(135deg,#7A5CFF,{BRAND_DARK});
            border-radius:18px;padding:24px 16px;">
          <p style="margin:0 0 6px;font-family:{FONT};font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#D9D3FF;">Total payable</p>
          <p style="margin:0 0 8px;font-family:{FONT};font-size:38px;font-weight:800;color:#ffffff;letter-spacing:-.5px;">&#8377;&nbsp;{float(invoice.total):,.2f}</p>
          <p style="margin:0;font-family:{FONT};font-size:13px;color:#E6E1FF;">Invoice <strong>{number}</strong></p>
        </td>
      </tr></table>"""

    breakdown = f"""
      <p style="margin:0 0 4px;font-family:{FONT};font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{MUTED};">Services</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 6px;border-top:2px solid {INK};">{rows}
      </table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin:0 0 26px;border-top:1px solid {LINE};">
        <tr>
          <td style="padding:12px 0 4px;font-family:{FONT};font-size:13px;color:{MUTED};">Subtotal</td>
          <td align="right" style="padding:12px 0 4px;font-family:{FONT};font-size:13px;color:{TEXT};">&#8377;&nbsp;{float(invoice.subtotal):,.2f}</td>
        </tr>
        <tr>
          <td style="padding:4px 0;font-family:{FONT};font-size:13px;color:{MUTED};">GST ({esc(str(invoice.gst_rate))}%)</td>
          <td align="right" style="padding:4px 0;font-family:{FONT};font-size:13px;color:{TEXT};">&#8377;&nbsp;{float(invoice.gst_amount):,.2f}</td>
        </tr>
        <tr>
          <td style="padding:10px 0 0;border-top:1px solid {LINE};font-family:{FONT};font-size:15px;font-weight:800;color:{INK};">Total</td>
          <td align="right" style="padding:10px 0 0;border-top:1px solid {LINE};font-family:{FONT};font-size:15px;font-weight:800;color:{INK};">&#8377;&nbsp;{float(invoice.total):,.2f}</td>
        </tr>
      </table>"""

    body = (
        _heading('&#129534;', 'You have a new invoice', tint='#E8F8FE')
        + _p(f'Hi {esc(user.name)}, a new invoice has been raised for your account. '
             'The PDF is attached — please review it and complete the payment at your earliest convenience.')
        + summary
        + breakdown
        + _button(payment_url, 'View invoice &amp; pay &rarr;')
        + '<div style="height:18px;line-height:18px;">&nbsp;</div>'
        + _fineprint('You can pay securely by UPI from the Payment section of the app.')
    )

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
    email.attach_alternative(
        _base(body, f'Invoice {invoice.invoice_number} — ₹{float(invoice.total):,.2f} due'),
        'text/html',
    )
    if pdf_bytes:
        email.attach(f'{invoice.invoice_number}.pdf', pdf_bytes, 'application/pdf')
    email.send(fail_silently=False)


def send_account_deleted_email(email: str, name: str) -> None:
    body = (
        _heading('&#128075;', 'Your account has been deleted', tint='#F1F0F7')
        + _p(f'Hi {esc(name)}, as you requested, your MIDRUS account and personal details have been deleted.')
        + _p('Invoices and tax records already issued to you are kept for the period required by '
             'Indian tax and company law, but they are no longer linked to a login.', size=14, color=MUTED)
        + _notice(f'<strong>Didn&rsquo;t request this?</strong> Contact us immediately at '
                  f'<a href="mailto:{SUPPORT_EMAIL}" style="color:#B91C1C;font-weight:700;">{SUPPORT_EMAIL}</a>.',
                  color='#991B1B', bg='#FEF2F2', border='#FBCACA')
        + '<div style="height:16px;line-height:16px;">&nbsp;</div>'
        + _fineprint('Thank you for using MIDRUS. You are always welcome to sign up again.')
    )
    send_mail(
        subject='MIDRUS — Your account has been deleted',
        message=f'Hi {name}, your MIDRUS account and personal details have been deleted. '
                f'If you did not request this, contact {SUPPORT_EMAIL} immediately.',
        html_message=_base(body, 'Your MIDRUS account and personal details have been deleted'),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=True,
    )


def send_approved_email(user) -> None:
    login_url = f"{settings.FRONTEND_URL}/login"
    perks = ''.join(
        f'<tr><td width="26" style="vertical-align:top;padding:5px 0;font-size:14px;color:#16A34A;">&#10003;</td>'
        f'<td style="padding:5px 0;font-family:{FONT};font-size:14px;color:{TEXT};">{t}</td></tr>'
        for t in ('Upload and track your compliance documents',
                  'Request accounting, tax and compliance services',
                  'View invoices and pay securely by UPI')
    )
    body = (
        _heading('&#127881;', 'You&rsquo;re approved!', tint='#E7F8EE')
        + _p(f'Hi {esc(user.name)}, great news — your MIDRUS account has been '
             '<strong style="color:#16A34A;">approved</strong>. Here&rsquo;s what you can do now:')
        + f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 26px;">{perks}</table>'
        + _button(login_url, 'Log in to your dashboard &rarr;')
    )
    send_mail(
        subject='MIDRUS — Your account has been approved!',
        message=f'Hi {user.name}, your MIDRUS account has been approved. Log in at: {login_url}',
        html_message=_base(body, 'Your MIDRUS account is approved — log in to get started'),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
