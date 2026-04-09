import frappe
from frappe import _
from frappe.utils import random_string, now
from frappe_auth.utils.error_handler import success_response
from frappe_auth.utils.auth_settings import get_auth_settings, send_with_template_or_fallback
import json


@frappe.whitelist(allow_guest=True)
def sign_up(email, full_name, password, mobile_no=None, redirect_to=None):
	"""
	Register a new user with OTP email verification.

	Step 1: Sends an OTP to the provided email and returns a verification_key.
	Step 2: Call verify_otp(verification_key, otp) to confirm and create the account.
	"""

	if frappe.db.exists("User", email):
		user = frappe.db.get_value("User", email, ["enabled"], as_dict=True)
		if user.enabled:
			return {"success": False, "message": _("User already registered")}
		else:
			return {
				"success": False,
				"message": _("User registered but not active. Please contact the administrator.")
			}

	# Check mobile number uniqueness before sending OTP
	if mobile_no:
		existing = frappe.db.get_value("User", {"mobile_no": mobile_no}, "name")
		if existing:
			return {"success": False, "message": _("An account with this mobile number already exists.")}

	# Basic rate-limiting: no more than 300 sign-ups in the last hour
	if frappe.db.sql("""
		SELECT COUNT(*) FROM tabUser
		WHERE HOUR(TIMEDIFF(CURRENT_TIMESTAMP, TIMESTAMP(modified))) < 1
	""")[0][0] > 300:
		return {"success": False, "message": _("Too many sign-ups recently. Please try again later.")}

	verification_key = frappe.generate_hash(length=32)
	otp = str(random_string(6)).upper()

	cache_data = {
		"email": email,
		"full_name": full_name,
		"mobile_no": mobile_no,
		"password": password,
		"redirect_to": redirect_to,
		"otp": otp,
		"created_at": now()
	}

	cache_key = f"signup_verification:{verification_key}"
	frappe.cache().set_value(cache_key, json.dumps(cache_data), expires_in_sec=300)

	_send_signup_otp_email(email, full_name, otp)

	return {
		"success": True,
		"message": _("OTP sent to your email. Please verify within 5 minutes."),
		"verification_key": verification_key
	}


@frappe.whitelist(allow_guest=True)
def verify_otp(verification_key, otp):
	"""
	Verify the OTP and create the user account.

	The default role assigned is configurable via site_config 'signup_default_role'
	(falls back to 'Customer'). Override this in your app if needed.
	"""

	cache_key = f"signup_verification:{verification_key}"
	cached_data = frappe.cache().get_value(cache_key)

	if not cached_data:
		return {
			"success": False,
			"message": _("Verification session expired or invalid. Please sign up again.")
		}

	try:
		user_data = json.loads(cached_data)
	except Exception:
		return {"success": False, "message": _("Invalid verification data. Please sign up again.")}

	if user_data.get("otp", "").upper() != otp.upper():
		return {"success": False, "message": _("Invalid OTP. Please try again.")}

	try:
		user = frappe.get_doc({
			"doctype": "User",
			"email": user_data["email"],
			"first_name": user_data["full_name"],
			"mobile_no": user_data.get("mobile_no"),
			"enabled": 1,
			"new_password": user_data["password"],
			"user_type": "Website User"
		})
		user.flags.ignore_permissions = True
		user.flags.ignore_password_policy = True
		user.flags.no_welcome_mail = True
		user.insert()

		# Assign configurable default role
		default_role = get_auth_settings()["default_role"]
		user.add_roles(default_role)

		# Create a Customer linked to this user if one doesn't exist yet
		customer_name = _ensure_customer(user.email, user_data["full_name"], user_data.get("mobile_no"))

		frappe.cache().delete_value(cache_key)

		redirect_url = user_data.get("redirect_to") or "/"

		return {
			"success": True,
			"message": _("Account verified successfully. You can now login."),
			"email": user.email,
			"customer": customer_name,
			"redirect_to": redirect_url
		}

	except Exception as e:
		frappe.log_error(f"User creation failed: {str(e)}", "OTP Verification Error")
		return {"success": False, "message": _("Failed to create account. Please try again or contact support.")}


@frappe.whitelist(allow_guest=True)
def resend_otp(verification_key):
	"""Resend the signup OTP for an active verification session."""

	cache_key = f"signup_verification:{verification_key}"
	cached_data = frappe.cache().get_value(cache_key)

	if not cached_data:
		return {
			"success": False,
			"message": _("Verification session expired. Please sign up again.")
		}

	try:
		user_data = json.loads(cached_data)
	except Exception:
		return {"success": False, "message": _("Invalid verification data. Please sign up again.")}

	new_otp = str(random_string(6)).upper()
	user_data["otp"] = new_otp
	user_data["created_at"] = now()

	frappe.cache().set_value(cache_key, json.dumps(user_data), expires_in_sec=300)

	_send_signup_otp_email(user_data["email"], user_data["full_name"], new_otp)

	return {"success": True, "message": _("New OTP sent to your email.")}


def _ensure_customer(email: str, full_name: str, mobile_no: str = None) -> str:
	"""
	Create a Customer + Contact for the newly registered user if one doesn't
	already exist. Returns the Customer name (existing or newly created).
	"""
	# Check via Customer.email_id directly first (fastest path)
	existing = frappe.db.get_value("Customer", {"email_id": email}, "name")
	if existing:
		return existing

	# Also check via Contact → Dynamic Link (covers customers created through charge)
	result = frappe.db.sql(
		"""
		SELECT dl.link_name
		FROM   `tabContact`      c
		JOIN   `tabDynamic Link` dl
		       ON  dl.parent       = c.name
		       AND dl.parenttype   = 'Contact'
		       AND dl.link_doctype = 'Customer'
		WHERE  c.email_id = %s
		LIMIT  1
		""",
		email,
	)
	if result:
		return result[0][0]

	# No existing customer — create one
	try:
		original_user = frappe.session.user
		frappe.set_user("Administrator")

		try:
			customer_group = (
				frappe.db.get_single_value("Selling Settings", "customer_group")
				or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
				or "All Customer Groups"
			)
			territory = (
				frappe.db.get_single_value("Selling Settings", "territory")
				or frappe.db.get_value("Territory", {"is_group": 0}, "name")
				or "All Territories"
			)

			customer = frappe.get_doc({
				"doctype":        "Customer",
				"customer_name":  full_name,
				"customer_type":  "Individual",
				"customer_group": customer_group,
				"territory":      territory,
				"email_id":       email,
			})
			customer.insert(ignore_permissions=True)

			contact_data = {
				"doctype":    "Contact",
				"first_name": full_name,
				"email_id":   email,
				"email_ids":  [{"doctype": "Contact Email", "email_id": email, "is_primary": 1}],
				"links": [{
					"doctype":      "Dynamic Link",
					"link_doctype": "Customer",
					"link_name":    customer.name,
				}],
			}
			if mobile_no:
				contact_data["phone"] = mobile_no
				contact_data["phone_nos"] = [
					{"doctype": "Contact Phone", "phone": mobile_no, "is_primary_phone": 1}
				]

			frappe.get_doc(contact_data).insert(ignore_permissions=True)
			return customer.name

		finally:
			frappe.set_user(original_user)

	except Exception:
		# Non-fatal — log full traceback and continue.
		frappe.log_error(frappe.get_traceback(), "Signup Customer Creation Error")
		return None


def _send_signup_otp_email(email, full_name, otp):
	"""Send OTP verification email for signup."""
	first_name = full_name.split()[0] if full_name else email.split("@")[0]

	template_name = get_auth_settings().get("registration_template")

	fallback_html = f"""
	<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
		<p>Hi {first_name},</p>
		<p>Your OTP for email verification is:</p>
		<div style="background: #f5f5f5; padding: 20px; text-align: center; margin: 20px 0;">
			<h1 style="color: #667eea; letter-spacing: 5px; margin: 0;">{otp}</h1>
		</div>
		<p>This OTP will expire in 5 minutes.</p>
		<p>If you did not request this, please ignore this email.</p>
	</div>
	"""

	send_with_template_or_fallback(
		recipients=email,
		subject=_("Verify Your Email - OTP"),
		template_name=template_name,
		template_args={"first_name": first_name, "otp": otp},
		fallback_html=fallback_html,
		header=[_("Email Verification"), "blue"],
	)
