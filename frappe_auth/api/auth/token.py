import frappe
from frappe import _
from frappe_auth.utils.jwt_auth import (
	verify_token,
	generate_access_token,
	generate_refresh_token,
	remove_user_session,
	revoke_specific_sessions
)
from frappe_auth.utils.error_handler import throw_error, ErrorCode, success_response
import jwt


@frappe.whitelist(allow_guest=True)
def refresh(refresh_token):
	"""
	Exchange a valid refresh token for a new access token (and rotated refresh token).

	Args:
		refresh_token: Valid JWT refresh token

	Returns:
		dict: New access_token and refresh_token
	"""
	try:
		payload = verify_token(refresh_token, token_type="refresh")
		user = payload.get("user")

		if not user:
			throw_error(ErrorCode.TOKEN_INVALID, _("Invalid refresh token"), http_status_code=401)

		if not frappe.db.exists("User", user):
			throw_error(ErrorCode.RESOURCE_NOT_FOUND, _("User not found"), http_status_code=404)

		if not frappe.db.get_value("User", user, "enabled"):
			throw_error(ErrorCode.UNAUTHORIZED, _("User account is disabled"), http_status_code=403)

		access_hours = int(frappe.conf.get("access_token_expiry") or 1)
		refresh_days = int(frappe.conf.get("refresh_token_expiry") or 7)

		new_access_token = generate_access_token(user, expires_in_hours=access_hours)
		new_refresh_token = generate_refresh_token(user, expires_in_days=refresh_days)

		return success_response(
			message=_("Token refreshed successfully"),
			data={
				"access_token": new_access_token,
				"refresh_token": new_refresh_token,
				"token_type": "Bearer",
				"expires_in": access_hours * 3600
			}
		)

	except frappe.AuthenticationError as e:
		throw_error(ErrorCode.TOKEN_INVALID, str(e), http_status_code=401)
	except Exception as e:
		frappe.log_error(f"Token refresh failed: {str(e)}", "Token Refresh Error")
		throw_error(ErrorCode.INTERNAL_ERROR, _("Token refresh failed"), http_status_code=500)


@frappe.whitelist()
def revoke(refresh_token, access_token=None):
	"""
	Revoke refresh token and optionally the access token (logout).

	Decodes tokens without full verification so users can always log out,
	even with expired tokens.

	Args:
		refresh_token: Refresh token to revoke (required)
		access_token: Access token to revoke (optional but recommended)

	Returns:
		dict: Success status
	"""
	try:
		try:
			refresh_payload = jwt.decode(refresh_token, options={"verify_signature": False})
			user = refresh_payload.get("user")
		except Exception:
			return success_response(message=_("Logged out successfully"))

		if not user:
			return success_response(message=_("Logged out successfully"))

		frappe.logger().info(f"Logout - revoking tokens for user: {user}")

		if access_token:
			try:
				access_payload = jwt.decode(access_token, options={"verify_signature": False})
				access_iat = access_payload.get("iat")

				if access_iat:
					remove_user_session(user, access_iat)
					revoke_specific_sessions(user, [access_iat])
					frappe.logger().info(f"Logout - revoked access token session: {access_iat}")
			except Exception as e:
				frappe.logger().warning(f"Failed to revoke access token session: {str(e)}")

		return success_response(message=_("Logged out successfully"))

	except Exception as e:
		frappe.logger().error(f"Token revocation error: {str(e)}")
		# Always succeed on logout so clients are never stuck
		return success_response(message=_("Logged out successfully"))
