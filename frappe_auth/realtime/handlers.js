/**
 * Socket event handlers for frappe_auth.
 *
 * Add your application-specific socket event handlers here.
 * Each socket object already has `socket.user` populated by the auth middleware.
 */

function setupHandlers(socket) {
	console.log(`[frappe_auth] Setting up handlers for user: ${socket.user}`);

	// Join a room
	socket.on("room:join", (room) => {
		socket.join(room);
		socket.emit("room:joined", { room });
		console.log(`[frappe_auth] User ${socket.user} joined room: ${room}`);
	});

	// Leave a room
	socket.on("room:leave", (room) => {
		socket.leave(room);
		socket.emit("room:left", { room });
		console.log(`[frappe_auth] User ${socket.user} left room: ${room}`);
	});

	// Connection health check
	socket.on("ping", () => {
		socket.emit("pong", { timestamp: Date.now() });
	});

	// Add more handlers here as needed
}

module.exports = setupHandlers;
