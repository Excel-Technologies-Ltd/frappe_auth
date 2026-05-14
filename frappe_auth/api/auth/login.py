import frappe
from frappe import _
from frappe.utils import cint
from frappe.twofactor import should_run_2fa, authenticate_for_2factor, confirm_otp_token, get_cached_user_pass
import frappe_auth.overrides  # noqa: F401 — ensures send_token_via_email patch is applied
from frappe.sessions import clear_sessions
from frappe_auth.utils.jwt_auth import generate_access_token, generate_refresh_token, add_user_session
from frappe_auth.utils.error_handler import throw_error, ErrorCode, success_response


def _get_token_expiry():
	"""Read token expiry from site_config, falling back to sensible defaults."""
	access_hours = int(frappe.conf.get("access_token_expiry") or 1)
	refresh_days = int(frappe.conf.get("refresh_token_expiry") or 7)
	return access_hours, refresh_days


def _enforce_session_limit(user, user_doc, access_token):
	"""If deny_multiple_sessions is on, track and enforce simultaneous session limit."""
	deny_multiple = cint(frappe.db.get_single_value("System Settings", "deny_multiple_sessions"))
	if not deny_multiple:
		return

	simultaneous_sessions = int(user_doc.simultaneous_sessions or 0)
	if simultaneous_sessions > 0:
		import jwt as jwt_lib
		token_payload = jwt_lib.decode(access_token, options={"verify_signature": False})
		token_iat = token_payload.get("iat")
		revoked = add_user_session(user, token_iat, max_sessions=simultaneous_sessions)
		if revoked:
			frappe.logger().info(f"Revoked {len(revoked)} old session(s) for {user}")

	clear_sessions(user=user, force=True)


@frappe.whitelist(allow_guest=True)
def login(user, pwd):
	"""Authenticate user with email/username and password, returning JWT tokens."""

	frappe.set_user("Guest")

	from frappe.core.doctype.user.user import User
	user_info = User.find_by_credentials(user, pwd, validate_password=True)

	if not user_info or not user_info.get("is_authenticated"):
		throw_error(
			ErrorCode.INVALID_CREDENTIALS,
			_("Invalid username or password"),
			http_status_code=401
		)

	user = user_info.get("name")
	user_doc = frappe.get_doc("User", user)

	if user_doc.enabled == 0:
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("User is disabled. Please contact your System Manager."),
			http_status_code=403
		)

	# Two-factor authentication
	if should_run_2fa(user):
		import frappe.twofactor as _ft
		from frappe_auth.utils.custom_2fa import send_token_via_email as _custom_send
		_ft.send_token_via_email = _custom_send

		frappe.form_dict.pwd = pwd
		authenticate_for_2factor(user)
		verification_data = frappe.local.response.get("verification", {})
		tmp_id = frappe.local.response.get("tmp_id")

		return success_response(
			message=_("Two-factor authentication required"),
			data={
				"requires_2fa": True,
				"tmp_id": tmp_id,
				"verification": verification_data,
				"email": user
			}
		)

	access_hours, refresh_days = _get_token_expiry()
	access_token = generate_access_token(user, expires_in_hours=access_hours)
	refresh_token = generate_refresh_token(user, expires_in_days=refresh_days)

	_enforce_session_limit(user, user_doc, access_token)

	# Clear session cookies — this app uses bearer tokens only
	frappe.local.cookie_manager.set_cookie("sid", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")
	frappe.local.cookie_manager.set_cookie("system_user", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")

	user_permissions = frappe.get_roles(user)

	return success_response(
		message=_("Logged in successfully"),
		data={
			"user": {
				"first_name": user_doc.first_name,
				"last_name": user_doc.last_name,
				"full_name": user_doc.full_name,
				"email": user,
				"gender": user_doc.gender,
				"mobile_no": user_doc.mobile_no,
				"username": user_doc.username,
				"birth_date": user_doc.birth_date,
				"location": user_doc.location,
				"interests": user_doc.interest,
				"bio": user_doc.bio,
				"language": user_doc.language,
				"last_login": user_doc.last_login,
				"user_image": user_doc.user_image,
			},
			"access_token": access_token,
			"refresh_token": refresh_token,
			"token_type": "Bearer",
			"expires_in": access_hours * 3600,
			"permissions": user_permissions,
		}
	)


@frappe.whitelist(allow_guest=True)
def verify_2fa_and_login(otp, tmp_id):
	"""Verify 2FA OTP and complete login, returning JWT tokens."""

	frappe.set_user("Guest")

	if not otp or not tmp_id:
		throw_error(
			ErrorCode.MISSING_REQUIRED_FIELD,
			_("OTP and temporary ID are required"),
			http_status_code=400
		)

	frappe.form_dict.tmp_id = tmp_id
	frappe.form_dict.otp = otp

	user, pwd = get_cached_user_pass()

	if not user:
		throw_error(
			ErrorCode.TOKEN_EXPIRED,
			_("Session expired. Please login again."),
			http_status_code=401
		)

	if not frappe.db.exists("User", user):
		throw_error(
			ErrorCode.INVALID_CREDENTIALS,
			_("User does not exist"),
			http_status_code=401
		)

	class MockLoginManager:
		def __init__(self, user):
			self.user = user

		def fail(self, message, user):
			throw_error(ErrorCode.INVALID_CREDENTIALS, message, http_status_code=401)

	login_manager = MockLoginManager(user)

	try:
		if not confirm_otp_token(login_manager, otp=otp, tmp_id=tmp_id):
			throw_error(ErrorCode.INVALID_CREDENTIALS, _("Invalid OTP"), http_status_code=401)
	except Exception as e:
		frappe.log_error(f"2FA verification failed: {str(e)}", "2FA Verification Error")
		throw_error(
			ErrorCode.INVALID_CREDENTIALS,
			_("Invalid or expired OTP. Please try again."),
			http_status_code=401
		)

	user_doc = frappe.get_doc("User", user)

	if user_doc.enabled == 0:
		throw_error(
			ErrorCode.UNAUTHORIZED,
			_("User is disabled. Please contact your System Manager."),
			http_status_code=403
		)

	access_hours, refresh_days = _get_token_expiry()
	access_token = generate_access_token(user, expires_in_hours=access_hours)
	refresh_token = generate_refresh_token(user, expires_in_days=refresh_days)

	_enforce_session_limit(user, user_doc, access_token)

	frappe.local.cookie_manager.set_cookie("sid", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")
	frappe.local.cookie_manager.set_cookie("system_user", "", expires="Thu, 01 Jan 1970 00:00:00 GMT")

	# Clear cached 2FA credentials
	frappe.cache().delete(tmp_id + "_usr")
	frappe.cache().delete(tmp_id + "_pwd")
	frappe.cache().delete(tmp_id + "_otp_secret")

	user_permissions = frappe.get_roles(user)

	return success_response(
		message=_("Logged in successfully"),
		data={
			"user": {
				"full_name": user_doc.full_name,
				"email": user,
			},
			"access_token": access_token,
			"refresh_token": refresh_token,
			"token_type": "Bearer",
			"expires_in": access_hours * 3600,
			"permissions": user_permissions,
		}
	)
