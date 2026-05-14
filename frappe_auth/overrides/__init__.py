import frappe.twofactor
from frappe_auth.utils.custom_2fa import send_token_via_email

frappe.twofactor.send_token_via_email = send_token_via_email
