import frappe
from frappe import _
from frappe.utils import now_datetime, today
from frappe.utils.password import update_password as frappe_update_password
from frappe.rate_limiter import rate_limit
from frappe_auth.utils.error_handler import throw_error, ErrorCode, success_response
from frappe_auth.utils.auth_settings import get_auth_settings, send_with_template_or_fallback
import pyotp
from base64 import b32encode
import os
import hashlib


# Configuration
OTP_EXPIRY_SECONDS = 600   # 10 minutes
MAX_OTP_ATTEMPTS = 20  # 5
RATE_LIMIT_REQUESTS = 20 # 3
RATE_LIMIT_WINDOW = 3600   # 1 hour


def _cache_key(token, prefix="frappe_auth_forgot_otp"):
	return f"{prefix}:{token}"


def _blacklist_key(token):
	token_hash = hashlib.sha256(token.encode()).hexdigest()
	return f"frappe_auth_forgot_blacklist:{token_hash}"


def _is_token_blacklisted(token):
	return frappe.cache().get_value(_blacklist_key(token)) is not None


def _blacklist_token(token, ttl_seconds=None):
	frappe.cache().set_value(
		_blacklist_key(token),
		"1",
		expires_in_sec=ttl_seconds or OTP_EXPIRY_SECONDS
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=RATE_LIMIT_REQUESTS, seconds=RATE_LIMIT_WINDOW)
def send_forgot_password_otp(email):
	"""Send a one-time password to the user's email to initiate a password reset."""

	if not email:
		throw_error(ErrorCode.MISSING_REQUIRED_FIELD, _("Email is required"), http_status_code=400)

	user = frappe.db.get_value("User", {"email": email, "enabled": 1}, ["name", "email"], as_dict=True)

	if not user:
		# Security: don't reveal whether the email exists
		return success_response(
			message=_("If this email exists in our system, you will receive an OTP shortly.")
		)

	if user.name == "Administrator":
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("Password reset is not allowed for Administrator"),
			http_status_code=403
		)

	otp_secret = b32encode(os.urandom(10)).decode("utf-8")
	hotp = pyotp.HOTP(otp_secret)
	counter = int(now_datetime().timestamp())
	otp = hotp.at(counter)

	token = frappe.generate_hash(length=32)

	otp_data = {
		"email": user.email,
		"otp": otp,
		"otp_secret": otp_secret,
		"counter": counter,
		"attempts": 0,
		"created_at": str(now_datetime()),
		"used": False
	}

	frappe.cache().set_value(_cache_key(token), otp_data, expires_in_sec=OTP_EXPIRY_SECONDS)

	_enqueue_forgot_otp_email(user.email, otp)

	return success_response(
		message=_(
			"If this email exists in our system, you will receive an OTP shortly. "
			"Please check your inbox."
		),
		data={"token": token, "expires_in": OTP_EXPIRY_SECONDS},
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=RATE_LIMIT_REQUESTS * 2, seconds=RATE_LIMIT_WINDOW)
def verify_forgot_password_otp(email, otp, token):
	"""Verify the OTP to authorise a password reset (does not reset the password yet)."""

	if not email or not otp or not token:
		throw_error(
			ErrorCode.MISSING_REQUIRED_FIELD,
			_("Email, OTP, and token are required"),
			http_status_code=400
		)

	if _is_token_blacklisted(token):
		throw_error(ErrorCode.TOKEN_REVOKED, _("This token has been revoked. Please request a new OTP."), http_status_code=401)

	otp_data = frappe.cache().get_value(_cache_key(token))

	if not otp_data:
		throw_error(ErrorCode.TOKEN_EXPIRED, _("Invalid or expired token. Please request a new OTP."), http_status_code=401)

	if otp_data.get("email") != email:
		throw_error(ErrorCode.INVALID_INPUT, _("Invalid token for this email address"), http_status_code=400)

	if otp_data.get("used"):
		throw_error(ErrorCode.TOKEN_REVOKED, _("This OTP has already been used. Please request a new one."), http_status_code=401)

	if otp_data.get("attempts", 0) >= MAX_OTP_ATTEMPTS:
		frappe.cache().delete_value(_cache_key(token))
		_blacklist_token(token)
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("Maximum verification attempts exceeded. Please request a new OTP."),
			http_status_code=403
		)

	otp_data["attempts"] = otp_data.get("attempts", 0) + 1
	frappe.cache().set_value(_cache_key(token), otp_data, expires_in_sec=OTP_EXPIRY_SECONDS)

	if str(otp_data.get("otp")) != str(otp):
		remaining = MAX_OTP_ATTEMPTS - otp_data["attempts"]
		throw_error(
			ErrorCode.INVALID_CREDENTIALS,
			_("Invalid OTP. {0} attempts remaining.").format(remaining),
			http_status_code=401,
			remaining_attempts=remaining
		)

	otp_data["verified"] = True
	otp_data["verified_at"] = str(now_datetime())
	frappe.cache().set_value(_cache_key(token), otp_data, expires_in_sec=OTP_EXPIRY_SECONDS)

	return success_response(
		message=_("OTP verified successfully. You can now reset your password."),
		data={"verified": True}
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=RATE_LIMIT_REQUESTS, seconds=RATE_LIMIT_WINDOW)
def reset_password_with_otp(email, otp, token, new_password):
	"""Reset the user's password after a successful OTP verification."""

	if not email or not otp or not token or not new_password:
		throw_error(ErrorCode.MISSING_REQUIRED_FIELD, _("All fields are required"), http_status_code=400)

	if _is_token_blacklisted(token):
		throw_error(ErrorCode.TOKEN_REVOKED, _("This token has been revoked. Please request a new OTP."), http_status_code=401)

	otp_data = frappe.cache().get_value(_cache_key(token))

	if not otp_data:
		throw_error(ErrorCode.TOKEN_EXPIRED, _("Invalid or expired token. Please request a new OTP."), http_status_code=401)

	if otp_data.get("email") != email:
		throw_error(ErrorCode.INVALID_INPUT, _("Invalid token for this email address"), http_status_code=400)

	if otp_data.get("used"):
		throw_error(ErrorCode.TOKEN_REVOKED, _("This OTP has already been used. Please request a new one."), http_status_code=401)

	if not otp_data.get("verified"):
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("OTP not verified. Please verify the OTP first."),
			http_status_code=403
		)

	if str(otp_data.get("otp")) != str(otp):
		throw_error(ErrorCode.INVALID_CREDENTIALS, _("Invalid OTP"), http_status_code=401)

	user = frappe.db.get_value("User", {"email": email, "enabled": 1}, "name")
	if not user:
		throw_error(ErrorCode.RESOURCE_NOT_FOUND, _("User not found or disabled"), http_status_code=404)

	try:
		frappe_update_password(user, new_password, logout_all_sessions=1)
		frappe.db.set_value("User", user, "last_password_reset_date", today())
		frappe.db.commit()

		otp_data["used"] = True
		otp_data["used_at"] = str(now_datetime())
		frappe.cache().set_value(_cache_key(token), otp_data, expires_in_sec=60)

		_blacklist_token(token, ttl_seconds=OTP_EXPIRY_SECONDS)

		frappe.logger().info(f"Password reset successful for user: {user}")

		user_doc = frappe.get_doc("User", user)
		redirect_url = "/app" if user_doc.user_type == "System User" else "/"

		return success_response(
			message=_("Password reset successful. You can now login with your new password."),
			data={"redirect_url": redirect_url}
		)

	except frappe.exceptions.ValidationError as e:
		throw_error(ErrorCode.INVALID_INPUT, str(e), http_status_code=400)
	except Exception as e:
		frappe.log_error(f"Password reset error: {str(e)}", "Forgot Password Reset Error")
		throw_error(ErrorCode.OPERATION_FAILED, _("Failed to reset password. Please try again."), http_status_code=500)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def resend_forgot_password_otp(token):
	"""Resend the OTP for an existing (non-expired, non-used) reset token."""

	if _is_token_blacklisted(token):
		throw_error(ErrorCode.TOKEN_REVOKED, _("This token has been revoked. Please request a new OTP."), http_status_code=401)

	otp_data = frappe.cache().get_value(_cache_key(token))

	if not otp_data:
		throw_error(ErrorCode.TOKEN_EXPIRED, _("Invalid or expired token. Please request a new OTP."), http_status_code=401)

	if otp_data.get("used"):
		throw_error(ErrorCode.TOKEN_REVOKED, _("This OTP has already been used. Please request a new one."), http_status_code=401)

	_enqueue_forgot_otp_email(otp_data.get("email"), otp_data.get("otp"))

	return success_response(
		message=_("A new OTP is being sent to your email address."),
	)


def _enqueue_forgot_otp_email(email, otp):
	"""Enqueue forgot-password OTP email so the API response returns immediately."""
	if not email or not otp:
		return
	try:
		frappe.enqueue(
			"frappe_auth.api.auth.forgot._send_otp_email",
			queue="short",
			timeout=120,
			email=email,
			otp=otp,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "frappe_auth forgot OTP: enqueue failed, sending synchronously")
		_send_otp_email(email, otp)


def _send_otp_email(email, otp):
	"""Send the password-reset OTP to the user's email (request or background worker)."""
	try:
		user = frappe.db.get_value(
			"User",
			{"email": email},
			["first_name", "last_name"],
			as_dict=True,
		)
		first_name = user.first_name if user else ""
		last_name = user.last_name if user else ""
		expiry_minutes = int(OTP_EXPIRY_SECONDS / 60)

		settings = get_auth_settings()
		template_name = settings.get("forgot_password_template") or settings.get("two_factor_auth_template")

		fallback_html = f"""
	<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
		<p>Dear {first_name} {last_name},</p>
		<p>You have requested to reset your password. Your One-Time Password (OTP) is:</p>
		<div style="background: #f5f5f5; padding: 20px; text-align: center; margin: 20px 0;">
			<h1 style="color: #667eea; letter-spacing: 5px; margin: 0;">{otp}</h1>
		</div>
		<p>This OTP is valid for the next {expiry_minutes} minutes.</p>
		<p>If you did not request a password reset, please ignore this email.</p>
	</div>
	"""

		send_with_template_or_fallback(
			recipients=email,
			subject=_("Password Reset OTP"),
			template_name=template_name,
			template_args={
				"first_name": first_name,
				"last_name": last_name,
				"otp": otp,
				"expiry_minutes": expiry_minutes,
			},
			fallback_html=fallback_html,
			header=[_("Password Reset OTP"), "blue"],
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"frappe_auth forgot OTP email send failed",
		)
