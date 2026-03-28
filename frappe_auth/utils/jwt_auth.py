import frappe
from frappe import _
import jwt
from datetime import datetime, timedelta
from functools import wraps
import hashlib


def get_jwt_secret():
	"""Get JWT secret from site config or generate one"""
	secret = frappe.conf.get("jwt_secret_key")
	if not secret:
		frappe.throw(_("JWT secret key not configured. Please add 'jwt_secret_key' to site_config.json"))
	return secret


def generate_access_token(user, expires_in_hours=24):
	"""
	Generate JWT access token for user

	Args:
		user: User email/username
		expires_in_hours: Token expiry time in hours (default 24)

	Returns:
		JWT token string
	"""
	payload = {
		"user": user,
		"exp": datetime.utcnow() + timedelta(hours=expires_in_hours),
		"iat": datetime.utcnow(),
		"type": "access"
	}

	token = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")
	return token


def generate_refresh_token(user, expires_in_days=30):
	"""
	Generate JWT refresh token for user

	Args:
		user: User email/username
		expires_in_days: Token expiry time in days (default 30)

	Returns:
		JWT refresh token string
	"""
	payload = {
		"user": user,
		"exp": datetime.utcnow() + timedelta(days=expires_in_days),
		"iat": datetime.utcnow(),
		"type": "refresh"
	}

	token = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")
	return token


def get_token_hash(token):
	"""Generate SHA256 hash of token for blacklist storage"""
	return hashlib.sha256(token.encode()).hexdigest()


def is_token_blacklisted(token):
	"""Check if token is in blacklist"""
	try:
		if not frappe.db.table_exists("Token Blacklist"):
			return False

		token_hash = get_token_hash(token)
		return frappe.db.exists("Token Blacklist", {"token_hash": token_hash})
	except Exception as e:
		frappe.logger().debug(f"Token blacklist check skipped: {str(e)}")
		return False


def verify_token(token, token_type="access"):
	"""
	Verify and decode JWT token

	Args:
		token: JWT token string
		token_type: Expected token type ('access' or 'refresh')

	Returns:
		dict: Decoded token payload

	Raises:
		frappe.AuthenticationError: If token is invalid or expired
	"""
	try:
		if is_token_blacklisted(token):
			frappe.throw(_("Token has been revoked"), frappe.AuthenticationError)

		if is_token_revoked(token):
			frappe.throw(_("Token has been revoked due to new login"), frappe.AuthenticationError)

		if is_session_revoked(token):
			frappe.throw(_("Session has been revoked due to exceeding simultaneous session limit"), frappe.AuthenticationError)

		payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])

		if payload.get("type") != token_type:
			frappe.throw(_("Invalid token type"), frappe.AuthenticationError)

		return payload

	except jwt.ExpiredSignatureError:
		frappe.throw(_("Token has expired"), frappe.AuthenticationError)
	except jwt.InvalidTokenError:
		frappe.throw(_("Invalid token"), frappe.AuthenticationError)


def jwt_required(fn):
	"""
	Decorator to protect API endpoints with JWT authentication

	Usage:
		@frappe.whitelist(allow_guest=True)
		@jwt_required
		def my_protected_endpoint():
			user = frappe.session.user
			# ... endpoint logic
	"""
	@wraps(fn)
	def wrapper(*args, **kwargs):
		auth_header = frappe.get_request_header("Authorization")

		if not auth_header:
			frappe.throw(_("Authorization header missing"), frappe.AuthenticationError)

		parts = auth_header.split()
		if len(parts) != 2 or parts[0].lower() != "bearer":
			frappe.throw(_("Invalid authorization header format. Use: Bearer <token>"), frappe.AuthenticationError)

		token = parts[1]

		payload = verify_token(token, token_type="access")
		user = payload.get("user")

		if not user:
			frappe.throw(_("Invalid token payload"), frappe.AuthenticationError)

		frappe.set_user(user)

		return fn(*args, **kwargs)

	return wrapper


def get_user_from_token(token):
	"""Extract user from JWT token without setting session"""
	payload = verify_token(token, token_type="access")
	return payload.get("user")


def blacklist_token(token, user, token_type="refresh"):
	"""Add token to blacklist"""
	try:
		payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
		expires_at = datetime.fromtimestamp(payload.get("exp"))

		token_hash = get_token_hash(token)

		if frappe.db.exists("Token Blacklist", {"token_hash": token_hash}):
			return True

		blacklist_doc = frappe.get_doc({
			"doctype": "Token Blacklist",
			"token_hash": token_hash,
			"user": user,
			"token_type": token_type,
			"expires_at": expires_at,
			"revoked_at": datetime.now()
		})
		blacklist_doc.insert(ignore_permissions=True)
		frappe.db.commit()

		return True

	except Exception as e:
		frappe.log_error(f"Failed to blacklist token: {str(e)}", "Token Blacklist Error")
		return False


def cleanup_expired_blacklist():
	"""Remove expired tokens from blacklist. Run periodically via scheduled job."""
	try:
		cutoff_date = datetime.now() - timedelta(days=7)

		frappe.db.sql("""
			DELETE FROM `tabToken Blacklist`
			WHERE expires_at < %s
		""", (cutoff_date,))

		frappe.db.commit()
		return True

	except Exception as e:
		frappe.log_error(f"Failed to cleanup blacklist: {str(e)}", "Blacklist Cleanup Error")
		return False


def revoke_all_user_tokens(user):
	"""
	Revoke all active JWT tokens for a user (single session enforcement).
	Stores revocation timestamp in Redis — tokens issued before this time are invalid.
	"""
	try:
		revocation_time = int(datetime.utcnow().timestamp())
		cache_key = f"jwt_revoke_before:{user}"
		frappe.cache().set_value(cache_key, revocation_time, expires_in_sec=30 * 24 * 60 * 60)
		return True

	except Exception as e:
		frappe.log_error(f"Failed to revoke user tokens: {str(e)}", "Token Revocation Error")
		return False


def is_token_revoked(token):
	"""Check if token was issued before user's revocation timestamp"""
	try:
		payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"], options={"verify_signature": False})
		user = payload.get("user")
		issued_at = payload.get("iat")

		if not user or not issued_at:
			return False

		cache_key = f"jwt_revoke_before:{user}"
		revoke_before = frappe.cache().get_value(cache_key)

		if not revoke_before:
			return False

		return issued_at < revoke_before

	except Exception as e:
		frappe.log_error(f"Error checking token revocation: {str(e)}", "Token Revocation Check Error")
		return False


def get_active_sessions_key(user):
	"""Get Redis key for user's active sessions list"""
	return f"jwt_active_sessions:{user}"


def add_user_session(user, token_identifier, max_sessions=None):
	"""
	Add a new session for the user and maintain session limit (FIFO).
	If limit is exceeded, the oldest session is revoked.

	Returns:
		list: Token identifiers that were revoked (if any)
	"""
	try:
		if max_sessions is None:
			max_sessions = int(frappe.db.get_value("User", user, "simultaneous_sessions") or 0)

		frappe.logger().info(f"add_user_session: user={user}, max_sessions={max_sessions}, token_iat={token_identifier}")

		cache_key = get_active_sessions_key(user)
		active_sessions = frappe.cache().get_value(cache_key) or []

		if max_sessions == 0:
			return []

		revoked_sessions = []

		while len(active_sessions) >= max_sessions:
			oldest = active_sessions.pop(0)
			revoked_sessions.append(oldest)

		active_sessions.append(token_identifier)
		frappe.cache().set_value(cache_key, active_sessions, expires_in_sec=30 * 24 * 60 * 60)

		if revoked_sessions:
			revoke_specific_sessions(user, revoked_sessions)

		return revoked_sessions

	except Exception as e:
		frappe.log_error(f"Failed to add user session: {str(e)}", "Session Tracking Error")
		return []


def revoke_specific_sessions(user, token_identifiers):
	"""Revoke specific sessions by their token identifiers (iat timestamps)"""
	try:
		if not token_identifiers:
			return

		revoked_key = f"jwt_revoked_sessions:{user}"
		revoked_sessions = frappe.cache().get_value(revoked_key) or []

		for token_id in token_identifiers:
			if token_id not in revoked_sessions:
				revoked_sessions.append(token_id)

		frappe.cache().set_value(revoked_key, revoked_sessions, expires_in_sec=30 * 24 * 60 * 60)

	except Exception as e:
		frappe.log_error(f"Failed to revoke specific sessions: {str(e)}", "Session Revocation Error")


def is_session_revoked(token):
	"""Check if a specific session (token) has been revoked"""
	try:
		payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"], options={"verify_signature": False})
		user = payload.get("user")
		issued_at = payload.get("iat")

		if not user or not issued_at:
			return False

		revoked_key = f"jwt_revoked_sessions:{user}"
		revoked_sessions = frappe.cache().get_value(revoked_key) or []

		return issued_at in revoked_sessions

	except Exception as e:
		frappe.log_error(f"Error checking session revocation: {str(e)}", "Session Revocation Check Error")
		return False


def remove_user_session(user, token_identifier):
	"""Remove a session from user's active sessions (e.g., on logout)"""
	try:
		cache_key = get_active_sessions_key(user)
		active_sessions = frappe.cache().get_value(cache_key) or []

		if token_identifier in active_sessions:
			active_sessions.remove(token_identifier)
			frappe.cache().set_value(cache_key, active_sessions, expires_in_sec=30 * 24 * 60 * 60)

	except Exception as e:
		frappe.log_error(f"Failed to remove user session: {str(e)}", "Session Removal Error")
