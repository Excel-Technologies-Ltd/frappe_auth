/**
 * Authentication middleware for frappe_auth Socket.IO server.
 *
 * Validates the bearer token from:
 *   1. socket.handshake.auth.token  — browser WebSocket connections
 *   2. Authorization header         — polling or proxied requests
 *
 * On success, sets socket.user, socket.user_type, and socket.frappe_request.
 */
function authenticate(socket, next) {
	// Derive site name from namespace or handshake auth
	let namespace = socket.nsp.name.slice(1); // strip leading "/"
	let site_name = socket.handshake.auth?.site || namespace;

	// Handle custom app namespace: /frappe_auth/{site_name}
	if (namespace.startsWith("frappe_auth/")) {
		const parts = namespace.split("/");
		if (parts.length >= 2) {
			site_name = parts[1];
		}
	}

	// Resolve bearer token (handshake auth takes priority)
	let bearer_token = null;

	if (socket.handshake.auth?.token) {
		bearer_token = socket.handshake.auth.token;
		if (!bearer_token.toLowerCase().startsWith("bearer ")) {
			bearer_token = `Bearer ${bearer_token}`;
		}
	} else if (socket.request.headers.authorization) {
		bearer_token = socket.request.headers.authorization;
	}

	if (!bearer_token) {
		next(new Error("Authentication required. Provide token via auth option or Authorization header."));
		return;
	}

	if (!/^Bearer\s+.+$/i.test(bearer_token)) {
		next(new Error("Invalid token format. Expected: 'Bearer <token>'"));
		return;
	}

	socket.authorization_header = bearer_token;
	socket.site_name = site_name;

	// Helper for calling the Frappe API from this socket's context
	socket.frappe_request = (path, args = {}, opts = {}) => {
		let query_args = new URLSearchParams(args);
		if (query_args.toString()) {
			path = path + "?" + query_args.toString();
		}
		const baseUrl = `https://${socket.site_name}`;
		return fetch(baseUrl + path, {
			...opts,
			headers: { Authorization: socket.authorization_header },
		});
	};

	// Verify token via Frappe's get_user_info endpoint
	socket
		.frappe_request("/api/method/frappe.realtime.get_user_info")
		.then((res) => {
			if (!res.ok) {
				throw new Error(`Authentication failed: ${res.status} ${res.statusText}`);
			}
			return res.json();
		})
		.then(({ message }) => {
			if (!message || !message.user) {
				throw new Error("Invalid user info response from server");
			}
			socket.user = message.user;
			socket.user_type = message.user_type;
			socket.installed_apps = message.installed_apps || [];
			next();
		})
		.catch((e) => {
			console.error("Authentication error:", e);
			next(new Error(`Unauthorized: ${e.message || e}`));
		});
}

module.exports = authenticate;
