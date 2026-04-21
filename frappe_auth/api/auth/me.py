import frappe
from frappe import _

# Uncomment the line below if you want to use your custom response wrappers
from frappe_auth.utils.error_handler import throw_error, ErrorCode, success_response

@frappe.whitelist()
def get_details() -> dict:
    """
    Authenticated API — Get current user profile and their associated customer details.
    
    Endpoint:
        GET /api/method/your_app.api.me.get_details
    """
    current_user = frappe.session.user

    # Double check to ensure guests cannot access this endpoint
    if current_user == "Guest":
        frappe.throw(_("Authentication required"), frappe.PermissionError)
        # If using your custom error handler:
        # throw_error(ErrorCode.UNAUTHORIZED, _("Authentication required"), http_status_code=401)

    # 1. Fetch User Data
    user_doc = frappe.get_doc("User", current_user)
    
    user_data = {
        "first_name": user_doc.first_name,
        "last_name": user_doc.last_name,
        "full_name": user_doc.full_name,
        "email": current_user,
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
        "permissions": frappe.get_roles(current_user),
    }

    # 2. Fetch Customer Data
    # In standard ERPNext, the user's email is linked to the 'email_id' field in the Customer DocType
    customer_data = None
    customer_name = frappe.db.get_value("Customer", {"email_id": current_user}, "name")

    if customer_name:
        # Fetching specific commonly used customer fields. Add or remove fields as needed for your app.
        customer_doc = frappe.get_doc("Customer", customer_name)
        customer_data = {
            "name": customer_doc.name,
            "customer_name": customer_doc.customer_name,
            "customer_group": customer_doc.customer_group,
            "territory": customer_doc.territory,
            "customer_type": customer_doc.customer_type,
            "primary_address": customer_doc.primary_address,
            "mobile_no": customer_doc.mobile_no,
            "email_id": customer_doc.email_id,
            "tax_id": customer_doc.tax_id,
            "status": "Active" if customer_doc.disabled == 0 else "Disabled"
        }

    # 3. Return the structured payload
    # Standard Frappe response will wrap this in a {"message": { ... }} JSON object
    # return {
    #     "user": user_data,
    #     "customer": customer_data
    # }

    # If you prefer to strictly follow your existing success_response wrapper pattern, 
    # replace the 'return' above with:
    return success_response(
        message=_("User details fetched successfully"),
        data={
            "user": user_data,
            "customer": customer_data
        }
    )