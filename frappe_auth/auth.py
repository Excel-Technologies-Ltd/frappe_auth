import frappe
from frappe import _


def validate():
	"""
	Authentication hook to validate JWT Bearer tokens on every request.
	Runs before Frappe's own validate_auth so Bearer JWTs are accepted site-wide.
	"""
	if frappe.session.user != "Guest":
		# Already authenticated (session cookie, API key, etc.)
		return

	auth_header = frappe.get_request_header("Authorization")

	if not auth_header:
		return

	parts = auth_header.split()
	if len(parts) != 2 or parts[0].lower() != "bearer":
		return

	token = parts[1]

	try:
		from frappe_auth.utils.jwt_auth import verify_token

		payload = verify_token(token, token_type="access")
		user = payload.get("user")

		if not user:
			raise frappe.AuthenticationError(_("Invalid token payload"))

		if not frappe.db.exists("User", user):
			raise frappe.AuthenticationError(_("User does not exist"))

		user_doc = frappe.get_cached_doc("User", user)
		if user_doc.enabled == 0:
			raise frappe.AuthenticationError(_("User is disabled"))

		# Set user without calling frappe.set_user() to avoid clearing form_dict
		frappe.local.session.user = user
		frappe.local.session.sid = user
		frappe.local.user_type = user_doc.user_type

		frappe.local.role_permissions = {}
		frappe.local.new_doc_templates = {}
		frappe.local.user_perms = None

	except frappe.AuthenticationError:
		raise
	except Exception as e:
		frappe.log_error(f"JWT validation error: {str(e)}", "JWT Auth Error")
