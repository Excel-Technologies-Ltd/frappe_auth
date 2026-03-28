"""
Helper functions for publishing events to the frappe_auth Socket.IO server via Redis.

Usage:
    from frappe_auth.realtime.utils import publish_event, publish_to_room, publish_to_user
"""

import json
import frappe
from frappe.utils.background_jobs import get_redis_connection_without_auth


def publish_event(event, message, room=None, namespace="/frappe_auth/default"):
    """
    Publish an event to the frappe_auth Socket.IO server.

    Args:
        event (str): Event name, e.g. "order:updated"
        message (dict): Payload to send to clients
        room (str, optional): Target room — omit to broadcast to the whole namespace
        namespace (str): Socket.IO namespace (default: /frappe_auth/default)
    """
    try:
        redis_client = get_redis_connection_without_auth()
        data = {
            "namespace": namespace,
            "room": room,
            "event": event,
            "message": message,
        }
        redis_client.publish("frappe_auth_events", json.dumps(data))
    except Exception as e:
        frappe.log_error(f"Failed to publish socket event: {str(e)}", "Socket Event Error")


def publish_to_user(user, event, message, namespace="/frappe_auth/default"):
    """
    Publish an event to a specific user's room.

    Args:
        user (str): Username / email
        event (str): Event name
        message (dict): Payload
        namespace (str): Socket.IO namespace
    """
    publish_event(event, message, room=f"user:{user}", namespace=namespace)


def publish_to_room(room, event, message, namespace="/frappe_auth/default"):
    """
    Publish an event to a named room.

    Args:
        room (str): Room name, e.g. "notifications" or "order:123"
        event (str): Event name
        message (dict): Payload
        namespace (str): Socket.IO namespace
    """
    publish_event(event, message, room=room, namespace=namespace)
