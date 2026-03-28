"""
Standardized error responses with error codes and HTTP status support.
"""

import frappe
from frappe import _


class ErrorCode:
	"""Standard error codes"""

	# Authentication Errors (1000-1999)
	INVALID_CREDENTIALS = 1001
	TOKEN_EXPIRED = 1002
	TOKEN_REVOKED = 1003
	TOKEN_INVALID = 1004
	UNAUTHORIZED = 1005
	SESSION_EXPIRED = 1006

	# Validation Errors (2000-2999)
	MISSING_REQUIRED_FIELD = 2001
	INVALID_INPUT = 2002
	DUPLICATE_ENTRY = 2003
	INVALID_FORMAT = 2004

	# Resource Errors (3000-3999)
	RESOURCE_NOT_FOUND = 3001
	RESOURCE_ALREADY_EXISTS = 3002
	RESOURCE_LOCKED = 3003

	# Permission Errors (4000-4999)
	PERMISSION_DENIED = 4001
	INSUFFICIENT_PRIVILEGES = 4002

	# Business Logic Errors (5000-5999)
	OPERATION_FAILED = 5001
	INVALID_STATE = 5002
	TRANSACTION_FAILED = 5003

	# System Errors (6000-6999)
	INTERNAL_ERROR = 6001
	SERVICE_UNAVAILABLE = 6002
	DATABASE_ERROR = 6003


_DEFAULT_MESSAGES = {
	ErrorCode.INVALID_CREDENTIALS: _("Invalid username or password"),
	ErrorCode.TOKEN_EXPIRED: _("Authentication token has expired"),
	ErrorCode.TOKEN_REVOKED: _("Token has been revoked"),
	ErrorCode.TOKEN_INVALID: _("Invalid authentication token"),
	ErrorCode.UNAUTHORIZED: _("Unauthorized access"),
	ErrorCode.SESSION_EXPIRED: _("Session has expired. Please login again"),
	ErrorCode.MISSING_REQUIRED_FIELD: _("Required field is missing"),
	ErrorCode.INVALID_INPUT: _("Invalid input provided"),
	ErrorCode.DUPLICATE_ENTRY: _("Duplicate entry found"),
	ErrorCode.INVALID_FORMAT: _("Invalid format"),
	ErrorCode.RESOURCE_NOT_FOUND: _("Resource not found"),
	ErrorCode.RESOURCE_ALREADY_EXISTS: _("Resource already exists"),
	ErrorCode.RESOURCE_LOCKED: _("Resource is locked"),
	ErrorCode.PERMISSION_DENIED: _("Permission denied"),
	ErrorCode.INSUFFICIENT_PRIVILEGES: _("Insufficient privileges"),
	ErrorCode.OPERATION_FAILED: _("Operation failed"),
	ErrorCode.INVALID_STATE: _("Invalid state"),
	ErrorCode.TRANSACTION_FAILED: _("Transaction failed"),
	ErrorCode.INTERNAL_ERROR: _("Internal server error"),
	ErrorCode.SERVICE_UNAVAILABLE: _("Service unavailable"),
	ErrorCode.DATABASE_ERROR: _("Database error occurred"),
}

_DEFAULT_EXCEPTION_TYPES = {
	range(1000, 2000): frappe.AuthenticationError,
	range(2000, 3000): frappe.ValidationError,
	range(3000, 4000): frappe.DoesNotExistError,
	range(4000, 5000): frappe.PermissionError,
	range(5000, 6000): frappe.ValidationError,
	range(6000, 7000): frappe.ValidationError,
}


def throw_error(error_code, message=None, exception_type=None, http_status_code=None, **kwargs):
	"""
	Throw a standardized error with error code and message.

	Args:
		error_code (int): Error code from ErrorCode class
		message (str, optional): Custom error message
		exception_type (Exception, optional): Exception class to raise
		http_status_code (int, optional): HTTP status code
		**kwargs: Additional context to include in error response
	"""
	error_message = message or _DEFAULT_MESSAGES.get(error_code, _("An error occurred"))

	if not exception_type:
		for error_range, exc_type in _DEFAULT_EXCEPTION_TYPES.items():
			if error_code in error_range:
				exception_type = exc_type
				break
		if not exception_type:
			exception_type = frappe.ValidationError

	error_data = {"error_code": error_code, "message": error_message, **kwargs}

	if http_status_code:
		frappe.local.response["http_status_code"] = http_status_code

	frappe.local.response["error_data"] = error_data
	frappe.local.response.pop("exc", None)

	frappe.throw(error_message, exception_type)


def success_response(message="Success", data=None, **kwargs):
	"""Return a standardized success response dict."""
	response = {"success": True, "message": message}
	if data is not None:
		response["data"] = data
	response.update(kwargs)
	return response


def error_response(error_code, message=None, http_status_code=None, **kwargs):
	"""Return a standardized error response dict without raising an exception."""
	error_message = message or _DEFAULT_MESSAGES.get(error_code, _("An error occurred"))

	if http_status_code:
		frappe.local.response["http_status_code"] = http_status_code

	return {
		"success": False,
		"error_code": error_code,
		"message": error_message,
		**kwargs
	}
