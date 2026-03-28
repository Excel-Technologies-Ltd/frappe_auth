# Frappe Auth

Frappe Auth modernizes legacy Frappe authentication by replacing cookie-based sessions with secure **Bearer token (JWT)** session management. It also ships a standalone Socket.IO server that authenticates via Bearer tokens, enabling seamless real-time connectivity for any Frappe application without cookies.

---

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Authentication API](#authentication-api)
  - [Sign Up](#1-sign-up)
  - [Verify Signup OTP](#2-verify-signup-otp)
  - [Resend Signup OTP](#3-resend-signup-otp)
  - [Login](#4-login)
  - [Verify 2FA and Login](#5-verify-2fa-and-login)
  - [Refresh Token](#6-refresh-token)
  - [Logout / Revoke Token](#7-logout--revoke-token)
  - [Forgot Password — Send OTP](#8-forgot-password--send-otp)
  - [Forgot Password — Verify OTP](#9-forgot-password--verify-otp)
  - [Forgot Password — Reset Password](#10-forgot-password--reset-password)
  - [Forgot Password — Resend OTP](#11-forgot-password--resend-otp)
- [Socket.IO](#socketio)
  - [Architecture](#architecture)
  - [Starting the Server](#starting-the-server)
  - [Client Connection](#client-connection)
  - [Socket Events](#socket-events)
  - [Publishing Events from Python](#publishing-events-from-python)
- [Error Codes](#error-codes)
- [License](#license)

---

## Installation

```bash
bench get-app https://github.com/Excel-Technologies-Ltd/frappe_auth.git
bench --site your-site.localhost install-app frappe_auth
```

---

## Configuration

Add the following keys to your site's `site_config.json`:

```json
{
  "jwt_secret_key": "your-strong-random-secret",
  "access_token_expiry": 1,
  "refresh_token_expiry": 7,
  "signup_default_role": "Customer"
}
```

Add the following key to `common_site_config.json` (bench-level):

```json
{
  "frappe_auth_socketio_port": 9001
}
```

| Key | Type | Default | Description |
|---|---|---|---|
| `jwt_secret_key` | string | **required** | Secret used to sign JWT tokens |
| `access_token_expiry` | int (hours) | `1` | Access token lifetime in hours |
| `refresh_token_expiry` | int (days) | `7` | Refresh token lifetime in days |
| `signup_default_role` | string | `Customer` | Role assigned to new users on signup |
| `frappe_auth_socketio_port` | int | `9001` | Port for the Socket.IO server |

### Procfile entry (Socket.IO server)

Add this line to your bench `Procfile` so the socket server starts with `bench start`:

```
frappe_auth: node {bench_path}/apps/frappe_auth/frappe_auth/realtime/socketio.js
```

---

## Authentication API

All endpoints are called via Frappe's standard API path:

```
POST /api/method/{endpoint}
```

Authenticated endpoints require the header:

```
Authorization: Bearer <access_token>
```

---

### 1. Sign Up

Registers a new user. Sends a 6-character OTP to the provided email. The account is only created after OTP verification.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.signup.sign_up
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | string | Yes | User's email address |
| `full_name` | string | Yes | Full name |
| `password` | string | Yes | Desired password |
| `mobile_no` | string | No | Mobile number |
| `redirect_to` | string | No | URL to redirect after verification |

```json
{
  "email": "user@example.com",
  "full_name": "John Doe",
  "password": "SecurePass123",
  "mobile_no": "+8801700000000",
  "redirect_to": "/dashboard"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "OTP sent to your email. Please verify within 5 minutes.",
  "verification_key": "a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5"
}
```

**Error Responses**

| Condition | Response |
|---|---|
| User already exists and is enabled | `{ "success": false, "message": "User already registered" }` |
| User exists but is disabled | `{ "success": false, "message": "User registered but not active. Please contact the administrator." }` |
| Too many sign-ups in last hour | `{ "success": false, "message": "Too many sign-ups recently. Please try again later." }` |

---

### 2. Verify Signup OTP

Verifies the OTP and creates the user account.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.signup.verify_otp
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `verification_key` | string | Yes | Key returned from `sign_up` |
| `otp` | string | Yes | 6-character OTP sent to email |

```json
{
  "verification_key": "a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5",
  "otp": "AB12CD"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "Account verified successfully. You can now login.",
  "email": "user@example.com",
  "redirect_to": "/dashboard"
}
```

**Error Responses**

| Condition | Response |
|---|---|
| Session expired / invalid key | `{ "success": false, "message": "Verification session expired or invalid. Please sign up again." }` |
| Wrong OTP | `{ "success": false, "message": "Invalid OTP. Please try again." }` |
| User creation failed | `{ "success": false, "message": "Failed to create account. Please try again or contact support." }` |

---

### 3. Resend Signup OTP

Generates a new OTP and resends it for an active verification session.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.signup.resend_otp
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `verification_key` | string | Yes | Key returned from `sign_up` |

```json
{
  "verification_key": "a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "New OTP sent to your email."
}
```

**Error Responses**

| Condition | Response |
|---|---|
| Session expired | `{ "success": false, "message": "Verification session expired. Please sign up again." }` |

---

### 4. Login

Authenticates a user and returns JWT access and refresh tokens.
If 2FA is enabled for the user, a temporary ID is returned instead of tokens.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.login.login
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `user` | string | Yes | Email, username, or mobile number |
| `pwd` | string | Yes | Password |

```json
{
  "user": "user@example.com",
  "pwd": "SecurePass123"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "Logged in successfully",
  "data": {
    "user": {
      "first_name": "John",
      "last_name": "Doe",
      "full_name": "John Doe",
      "email": "user@example.com",
      "gender": "Male",
      "mobile_no": "+8801700000000",
      "username": "johndoe",
      "birth_date": "1990-01-01",
      "location": "Dhaka",
      "interests": null,
      "bio": null,
      "language": "en",
      "last_login": "2025-01-01 10:00:00",
      "user_image": "/files/profile.jpg"
    },
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 3600,
    "permissions": ["System Manager", "Customer"]
  }
}
```

**2FA Required Response** `200`
```json
{
  "success": true,
  "message": "Two-factor authentication required",
  "data": {
    "requires_2fa": true,
    "tmp_id": "tmp_abc123",
    "verification": { "method": "email", "prompt": "Enter OTP sent to your email" },
    "email": "user@example.com"
  }
}
```

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 401 | Invalid credentials | `1001` |
| 403 | User is disabled | `1005` |

---

### 5. Verify 2FA and Login

Completes the login flow after a successful 2FA OTP verification.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.login.verify_2fa_and_login
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `otp` | string | Yes | OTP from the 2FA method |
| `tmp_id` | string | Yes | Temporary ID returned from `login` |

```json
{
  "otp": "123456",
  "tmp_id": "tmp_abc123"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "Logged in successfully",
  "data": {
    "user": {
      "full_name": "John Doe",
      "email": "user@example.com"
    },
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 3600,
    "permissions": ["Customer"]
  }
}
```

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 400 | Missing OTP or tmp_id | `2001` |
| 401 | Session expired (tmp_id invalid) | `1002` |
| 401 | Invalid or expired OTP | `1001` |
| 403 | User is disabled | `1005` |

---

### 6. Refresh Token

Exchanges a valid refresh token for a new access token and a rotated refresh token.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.token.refresh
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `refresh_token` | string | Yes | Valid JWT refresh token |

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 3600
  }
}
```

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 401 | Invalid or revoked refresh token | `1004` |
| 403 | User account disabled | `1005` |
| 404 | User not found | `3001` |
| 500 | Internal error | `6001` |

---

### 7. Logout / Revoke Token

Revokes the session. Accepts expired tokens so a user can always log out.

**Endpoint** *(requires `Authorization: Bearer <access_token>` header)*
```
POST /api/method/frappe_auth.api.auth.token.revoke
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `refresh_token` | string | Yes | Refresh token to invalidate |
| `access_token` | string | No | Access token to invalidate (recommended) |

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Success Response** `200` *(always succeeds)*
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

---

### 8. Forgot Password — Send OTP

Sends a password-reset OTP to the user's email. Rate-limited to **3 requests per hour**.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.forgot.send_forgot_password_otp
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | string | Yes | Account email address |

```json
{
  "email": "user@example.com"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "An OTP has been sent to your email address. Please check your inbox.",
  "data": {
    "token": "b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6",
    "expires_in": 600
  }
}
```

> If the email does not exist, the response is identical (security — prevents email enumeration).

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 400 | Email field missing | `2001` |
| 403 | Administrator account | `1005` |
| 500 | Email send failure | `5001` |

---

### 9. Forgot Password — Verify OTP

Verifies the OTP without resetting the password. Must be called before `reset_password_with_otp`. Rate-limited to **6 requests per hour**.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.forgot.verify_forgot_password_otp
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | string | Yes | Account email address |
| `otp` | string | Yes | OTP received in email |
| `token` | string | Yes | Token returned from `send_forgot_password_otp` |

```json
{
  "email": "user@example.com",
  "otp": "482931",
  "token": "b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "OTP verified successfully. You can now reset your password.",
  "data": {
    "verified": true
  }
}
```

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 400 | Missing fields | `2001` |
| 400 | Email does not match token | `2002` |
| 401 | Token revoked / blacklisted | `1003` |
| 401 | Token expired / not found | `1002` |
| 401 | OTP already used | `1003` |
| 401 | Wrong OTP | `1001` |
| 403 | Max attempts (5) exceeded | `1005` |

---

### 10. Forgot Password — Reset Password

Resets the password after a verified OTP. Rate-limited to **3 requests per hour**.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.forgot.reset_password_with_otp
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | string | Yes | Account email address |
| `otp` | string | Yes | OTP received in email |
| `token` | string | Yes | Token returned from `send_forgot_password_otp` |
| `new_password` | string | Yes | New password |

```json
{
  "email": "user@example.com",
  "otp": "482931",
  "token": "b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6",
  "new_password": "NewSecurePass456"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "Password reset successful. You can now login with your new password.",
  "data": {
    "redirect_url": "/"
  }
}
```

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 400 | Missing fields | `2001` |
| 400 | Email does not match token | `2002` |
| 400 | Password policy violation | `2002` |
| 401 | Token revoked / blacklisted | `1003` |
| 401 | Token expired / not found | `1002` |
| 401 | OTP already used | `1003` |
| 401 | Wrong OTP | `1001` |
| 403 | OTP not verified first | `1005` |
| 404 | User not found or disabled | `3001` |
| 500 | Internal error | `5001` |

---

### 11. Forgot Password — Resend OTP

Resends the existing OTP for an active (non-expired, non-used) reset token.

**Endpoint**
```
POST /api/method/frappe_auth.api.auth.forgot.resend_forgot_password_otp
```

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | string | Yes | Token returned from `send_forgot_password_otp` |

```json
{
  "token": "b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6"
}
```

**Success Response** `200`
```json
{
  "success": true,
  "message": "OTP has been resent to your email address."
}
```

**Error Responses**

| HTTP | Condition | `error_code` |
|---|---|---|
| 401 | Token revoked | `1003` |
| 401 | Token expired / not found | `1002` |
| 401 | OTP already used | `1003` |
| 500 | Email send failure | `5001` |

---

## Socket.IO

### Architecture

```
Client (Bearer Token)
        │
        ▼
frappe_auth Socket.IO Server (port 9001)
        │
        ▼
Authentication Middleware
  └─ Calls /api/method/frappe.realtime.get_user_info with Bearer token
        │
        ▼
Event Handlers (handlers.js)
        ▲
        │
Redis ──┤── "events"              (all standard Frappe realtime events)
        └── "frappe_auth_events"  (custom app events published from Python)
```

### Starting the Server

**Manually:**
```bash
node apps/frappe_auth/frappe_auth/realtime/socketio.js
```

**Via Procfile** (recommended — starts automatically with `bench start`):
```
frappe_auth: node {bench_path}/apps/frappe_auth/frappe_auth/realtime/socketio.js
```

### Client Connection

The server exposes two namespace patterns:

| Namespace | Receives |
|---|---|
| `/{site_name}` | All standard Frappe realtime events |
| `/frappe_auth/{site_name}` | Frappe events + custom `frappe_auth_events` |

#### JavaScript / TypeScript

**Connect to the Frappe site namespace** (receives all Frappe realtime events):
```javascript
import { io } from 'socket.io-client';

const socket = io('http://your-site:9001/site1.localhost', {
  auth: {
    token: 'your-jwt-access-token'   // no "Bearer" prefix needed here
  }
});

// Standard Frappe events
socket.on('list_update',   (data) => console.log('List update:', data));
socket.on('docinfo_update',(data) => console.log('Doc update:', data));
socket.on('task_progress', (data) => console.log('Task progress:', data));
socket.on('msgprint',      (data) => console.log('Message:', data));
```

**Connect to the frappe_auth custom namespace** (Frappe events + custom events):
```javascript
const socket = io('http://your-site:9001/frappe_auth/site1.localhost', {
  auth: {
    token: 'your-jwt-access-token'
  }
});

// Standard Frappe events are forwarded here too
socket.on('list_update', (data) => console.log('List update:', data));

// Custom events published from Python
socket.on('custom:event', (data) => console.log('Custom event:', data));

socket.on('connect', () => console.log('Connected'));
socket.on('connect_error', (err) => console.error('Auth error:', err.message));
```

**Using the Authorization header** (polling / server-side connections):
```javascript
const socket = io('http://your-site:9001/site1.localhost', {
  extraHeaders: {
    'Authorization': 'Bearer your-jwt-access-token'
  },
  withCredentials: false
});
```

### Socket Events

#### Client → Server events

| Event | Payload | Description |
|---|---|---|
| `room:join` | `"room-name"` | Join a named room to receive targeted broadcasts |
| `room:leave` | `"room-name"` | Leave a room |
| `ping` | *(none)* | Health check — server replies with `pong` |

**Join a room:**
```javascript
socket.emit('room:join', 'notifications');
socket.on('room:joined', ({ room }) => console.log('Joined:', room));
```

**Leave a room:**
```javascript
socket.emit('room:leave', 'notifications');
socket.on('room:left', ({ room }) => console.log('Left:', room));
```

**Ping / Pong:**
```javascript
socket.emit('ping');
socket.on('pong', ({ timestamp }) => console.log('Pong at:', timestamp));
```

#### Server → Client events

| Event | Description |
|---|---|
| `room:joined` | Confirmation after joining a room — `{ room: "room-name" }` |
| `room:left` | Confirmation after leaving a room — `{ room: "room-name" }` |
| `pong` | Reply to `ping` — `{ timestamp: 1700000000000 }` |
| `list_update` | Frappe list view realtime update |
| `docinfo_update` | Frappe document info update |
| `task_progress` | Frappe background job progress |
| `msgprint` | Frappe server-side print message |
| *(any custom event)* | Events published from Python via `publish_event()` |

### Publishing Events from Python

```python
from frappe_auth.realtime.utils import publish_event, publish_to_room, publish_to_user

# Broadcast to all clients in the default namespace
publish_event('notification:new', {
    'title': 'New order received',
    'order_id': 'ORD-2025-0001'
})

# Send to all clients in a named room
publish_to_room('order:ORD-0001', 'order:status_changed', {
    'order_id': 'ORD-2025-0001',
    'status': 'Confirmed'
})

# Send to a specific user
publish_to_user('user@example.com', 'notification:personal', {
    'message': 'Your order has been shipped'
})

# Publish to a custom namespace (e.g. site-specific)
publish_event('data:sync', {'key': 'value'}, namespace='/frappe_auth/site1.localhost')
```

---

## Error Codes

All error responses include an `error_code` field for programmatic handling.

### Authentication (1000–1999)

| Code | Name | Description |
|---|---|---|
| `1001` | `INVALID_CREDENTIALS` | Wrong username or password |
| `1002` | `TOKEN_EXPIRED` | Access/refresh token has expired |
| `1003` | `TOKEN_REVOKED` | Token has been revoked or already used |
| `1004` | `TOKEN_INVALID` | Token is malformed or has an invalid signature |
| `1005` | `UNAUTHORIZED` | User is disabled or action is not permitted |
| `1006` | `SESSION_EXPIRED` | Session has expired |

### Validation (2000–2999)

| Code | Name | Description |
|---|---|---|
| `2001` | `MISSING_REQUIRED_FIELD` | A required field is absent |
| `2002` | `INVALID_INPUT` | Field value is invalid |
| `2003` | `DUPLICATE_ENTRY` | Record already exists |
| `2004` | `INVALID_FORMAT` | Value format is incorrect |

### Resource (3000–3999)

| Code | Name | Description |
|---|---|---|
| `3001` | `RESOURCE_NOT_FOUND` | Requested resource does not exist |
| `3002` | `RESOURCE_ALREADY_EXISTS` | Resource already exists |
| `3003` | `RESOURCE_LOCKED` | Resource is locked |

### Permission (4000–4999)

| Code | Name | Description |
|---|---|---|
| `4001` | `PERMISSION_DENIED` | Insufficient permissions |
| `4002` | `INSUFFICIENT_PRIVILEGES` | More privileges required |

### Business Logic (5000–5999)

| Code | Name | Description |
|---|---|---|
| `5001` | `OPERATION_FAILED` | Operation could not be completed |
| `5002` | `INVALID_STATE` | Resource is in an invalid state |
| `5003` | `TRANSACTION_FAILED` | Transaction failed |

### System (6000–6999)

| Code | Name | Description |
|---|---|---|
| `6001` | `INTERNAL_ERROR` | Unexpected server error |
| `6002` | `SERVICE_UNAVAILABLE` | Service is temporarily unavailable |
| `6003` | `DATABASE_ERROR` | Database operation failed |

### Error Response Shape

```json
{
  "exc_type": "AuthenticationError",
  "error_data": {
    "error_code": 1001,
    "message": "Invalid username or password"
  }
}
```

Some errors include additional context fields, e.g.:

```json
{
  "error_data": {
    "error_code": 1001,
    "message": "Invalid OTP. 3 attempts remaining.",
    "remaining_attempts": 3
  }
}
```

---

## License

MIT
