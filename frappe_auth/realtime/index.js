/**
 * frappe_auth — Custom Socket.IO server with bearer token authentication.
 *
 * Features:
 *  - Bearer token authentication (no cookies required)
 *  - Subscribes to Frappe's standard "events" Redis channel (receives ALL Frappe realtime events)
 *  - Subscribes to "frappe_auth_events" for custom app events
 *  - Dual namespace support: Frappe site namespaces + /frappe_auth/{site} namespaces
 *  - Port is configurable via frappe_auth_socketio_port in bench/config.json (default: 9001)
 */

const path = require("path");
const frappePath = path.resolve(__dirname, "../../../frappe");
const { Server } = require(path.join(frappePath, "node_modules/socket.io"));
const http = require("node:http");
const { get_conf, get_redis_subscriber } = require(path.join(frappePath, "node_utils"));
const authenticate = require("./middlewares/authenticate");
const conf = get_conf();

const server = http.createServer();

const io = new Server(server, {
	cors: {
		origin: true,
		credentials: false,
		methods: ["GET", "POST"],
	},
	cleanupEmptyChildNamespaces: true,
	allowEIO3: true,
	transports: ["websocket", "polling"],
});

// All Frappe site namespaces (e.g. /site1.localhost)
const frappeNamespace = io.of(/^\/.*$/);

// frappe_auth custom namespaces (e.g. /frappe_auth/site1.localhost)
const appNamespace = io.of(/^\/frappe_auth\/.*$/);

frappeNamespace.use(authenticate);
appNamespace.use(authenticate);

frappeNamespace.on("connection", (socket) => {
	console.log(`[Frappe NS] Connected: ${socket.id}, user: ${socket.user}, ns: ${socket.nsp.name}`);

	const handlers = require("./handlers");
	if (typeof handlers === "function") {
		handlers(socket);
	}

	socket.on("disconnect", (reason) => {
		console.log(`[Frappe NS] Disconnected: ${socket.id}, reason: ${reason}`);
	});

	socket.on("error", (error) => {
		console.error(`[Frappe NS] Error for ${socket.id}:`, error);
	});
});

appNamespace.on("connection", (socket) => {
	console.log(`[App NS] Connected: ${socket.id}, user: ${socket.user}, ns: ${socket.nsp.name}`);

	const handlers = require("./handlers");
	if (typeof handlers === "function") {
		handlers(socket);
	}

	socket.on("disconnect", (reason) => {
		console.log(`[App NS] Disconnected: ${socket.id}, reason: ${reason}`);
	});

	socket.on("error", (error) => {
		console.error(`[App NS] Error for ${socket.id}:`, error);
	});
});

// Redis pub-sub — receive events from Python and forward to connected clients
const subscriber = get_redis_subscriber();

subscriber.on("message", function (_channel, message) {
	try {
		const data = JSON.parse(message);
		const { room, event, message: payload } = data;

		// Resolve namespace: Frappe omits namespace but encodes site in the room
		let namespace = data.namespace;
		if (!namespace && room) {
			const roomParts = room.split(":");
			if (roomParts.length >= 2) {
				namespace = roomParts[0]; // e.g. "site1.localhost"
			}
		}

		const namespacePath = "/" + (namespace || "");
		console.log(`[Redis] event: ${event}, ns: ${namespacePath}, room: ${room || "broadcast"}`);

		// Forward to Frappe site namespace
		const targetNs = io.of(namespacePath);
		if (room) {
			targetNs.to(room).emit(event, payload);
		} else {
			targetNs.emit(event, payload);
		}

		// Also forward to the frappe_auth custom namespace
		if (namespace) {
			const appNs = io.of(`/frappe_auth/${namespace}`);
			if (room) {
				appNs.to(room).emit(event, payload);
			} else {
				appNs.emit(event, payload);
			}
		}
	} catch (err) {
		console.error("[Redis] Error processing message:", err);
	}
});

// Subscribe to Frappe's standard realtime channel
subscriber.subscribe("events");
console.log("[Redis] Subscribed to 'events' channel");

// Subscribe to frappe_auth custom events channel
subscriber.subscribe("frappe_auth_events");
console.log("[Redis] Subscribed to 'frappe_auth_events' channel");

// Start HTTP server
const port = conf.frappe_auth_socketio_port || conf.socketio_port || 9001;
const uds = conf.frappe_auth_socketio_uds;

server.listen(uds || port, () => {
	if (uds) {
		console.log(`[frappe_auth] Socket.IO listening on UDS: ${uds}`);
	} else {
		console.log(`[frappe_auth] Socket.IO listening on: ws://0.0.0.0:${port}`);
	}
});

// Graceful shutdown
process.on("SIGTERM", () => {
	console.log("[frappe_auth] SIGTERM received, shutting down gracefully");
	server.close(() => {
		subscriber.quit();
		process.exit(0);
	});
});

process.on("SIGINT", () => {
	console.log("[frappe_auth] SIGINT received, shutting down gracefully");
	server.close(() => {
		subscriber.quit();
		process.exit(0);
	});
});

module.exports = { io, appNamespace };
