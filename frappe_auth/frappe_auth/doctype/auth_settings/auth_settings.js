// Copyright (c) 2026, Shaid Azmin and contributors
// For license information, please see license.txt

frappe.ui.form.on("Auth Settings", {
	refresh(frm) {
		frm.set_intro(
			__(
				"Configure token expiry, default user role, and email templates for " +
				"registration, password reset, and two-factor authentication."
			),
			"blue"
		);
	},
});
