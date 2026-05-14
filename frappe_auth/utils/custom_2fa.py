import frappe
import pyotp
from frappe import _
from frappe_auth.utils.auth_settings import get_auth_settings


def send_token_via_email(user, token, otp_secret, otp_issuer, subject=None, message=None):
    """Override of frappe.twofactor.send_token_via_email — returns immediately, sends in background."""
    user_email = frappe.db.get_value("User", user, "email")
    if not user_email:
        return False

    # QR code setup path — subject and message are pre-built by Frappe
    if subject and message:
        _enqueue_2fa_email(user_email, subject, message)
        return True

    hotp = pyotp.HOTP(otp_secret)
    otp = hotp.at(int(token))

    user_doc = frappe.db.get_value("User", user, ["first_name", "last_name"], as_dict=True)
    args = {
        "first_name": (user_doc and user_doc.first_name) or "",
        "last_name": (user_doc and user_doc.last_name) or "",
        "otp": otp,
        "otp_issuer": otp_issuer,
    }

    email_subject = _("Login Verification Code from {0}").format(otp_issuer)
    html_content = None

    settings = get_auth_settings()
    template_name = settings.get("two_factor_auth_template")
    if template_name and frappe.db.exists("Email Template", template_name):
        try:
            tmpl = frappe.get_doc("Email Template", template_name)
            html_content = frappe.render_template(tmpl.response_html, args)
            email_subject = frappe.render_template(tmpl.subject, args) or email_subject
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"frappe_auth: failed to render 2FA Email Template '{template_name}'",
            )

    if not html_content:
        html_content = f"""
            <p>Dear {args['first_name']},</p>
            <p>Enter this code to complete your login:</p>
            <h2 style="font-size: 24px; letter-spacing: 4px;">{otp}</h2>
            <p>This code will expire shortly.</p>
            <p>If you did not request this code, please ignore this email.</p>
        """

    _enqueue_2fa_email(user_email, email_subject, html_content)
    return True


def _enqueue_2fa_email(user_email, subject, message):
    """Enqueue 2FA email so the login response returns without waiting for the send."""
    try:
        frappe.enqueue(
            "frappe_auth.utils.custom_2fa._send_2fa_email",
            queue="short",
            timeout=60,
            user_email=user_email,
            subject=subject,
            message=message,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "frappe_auth 2FA email: enqueue failed, sending synchronously")
        _send_2fa_email(user_email, subject, message)


def _send_2fa_email(user_email, subject, message):
    frappe.sendmail(
        recipients=user_email,
        subject=subject,
        message=message,
        delayed=False,
        retry=3,
    )
