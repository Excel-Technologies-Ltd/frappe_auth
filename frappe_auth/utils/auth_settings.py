import frappe

_SETTINGS_CACHE_KEY = "frappe_auth_settings"
_SETTINGS_TTL = 300  # 5 minutes


def get_auth_settings() -> dict:
    """
    Return Auth Settings with fallbacks:
      1. Auth Settings DocType (DB / single)
      2. site_config / frappe.conf
      3. hardcoded defaults

    Result is cached in Redis for 5 minutes so every request does not hit the DB.
    """
    cached = frappe.cache().get_value(_SETTINGS_CACHE_KEY)
    if cached:
        return cached

    try:
        doc = frappe.get_single("Auth Settings")
        settings = {
            "access_token_expiry": int(doc.access_token_expiry or 0)
                or int(frappe.conf.get("access_token_expiry") or 0)
                or 1,
            "refresh_token_expiry": int(doc.refresh_token_expiry or 0)
                or int(frappe.conf.get("refresh_token_expiry") or 0)
                or 7,
            "default_role": doc.default_role
                or frappe.conf.get("signup_default_role")
                or "Customer",
            "registration_template": doc.registration_template or None,
            "forgot_password_template": doc.forgot_password_template or None,
            "two_factor_auth_template": doc.two_factor_auth_template or None,
        }
    except Exception:
        # DocType may not exist yet (before migrate) — fall back gracefully
        settings = {
            "access_token_expiry": int(frappe.conf.get("access_token_expiry") or 1),
            "refresh_token_expiry": int(frappe.conf.get("refresh_token_expiry") or 7),
            "default_role": frappe.conf.get("signup_default_role") or "Customer",
            "registration_template": None,
            "forgot_password_template": None,
            "two_factor_auth_template": None,
        }

    frappe.cache().set_value(_SETTINGS_CACHE_KEY, settings, expires_in_sec=_SETTINGS_TTL)
    return settings


def invalidate_settings_cache(doc, method):
    """Called by doc_events on Auth Settings save — clears the cached settings."""
    frappe.cache().delete_value(_SETTINGS_CACHE_KEY)


def send_with_template_or_fallback(
    recipients,
    subject,
    template_name,
    template_args,
    fallback_html,
    header=None,
):
    """
    Send an email using a configured Frappe Email Template doctype when available,
    otherwise fall back to the provided inline HTML.

    Args:
        recipients (str | list): Recipient email(s).
        subject (str): Email subject (used only for the fallback path; the
                       Email Template's own subject overrides this).
        template_name (str | None): Name of a Frappe Email Template doc.
        template_args (dict): Jinja context passed to the template.
        fallback_html (str): Raw HTML used when no template is configured.
        header (list | None): [title, colour] banner for frappe.sendmail.
    """
    if template_name and frappe.db.exists("Email Template", template_name):
        try:
            email_template = frappe.get_doc("Email Template", template_name)
            rendered = email_template.get_formatted_email(template_args)
            frappe.sendmail(
                recipients=recipients,
                subject=rendered.get("subject") or subject,
                message=rendered.get("message") or fallback_html,
                delayed=False,
                retry=3,
                now=True,
            )
            return
        except Exception:
            frappe.log_error(
                f"Failed to render Email Template '{template_name}', falling back to static HTML",
                "frappe_auth send_with_template_or_fallback",
            )

    frappe.sendmail(
        recipients=recipients,
        subject=subject,
        message=fallback_html,
        header=header or [],
        delayed=False,
        retry=3,
        now=True,
    )
