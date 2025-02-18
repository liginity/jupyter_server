"""A Websocket Handler for emitting Jupyter server events.

.. versionadded:: 2.0
"""
import json
from datetime import datetime
from typing import Any, Dict, Optional

from jupyter_events import EventLogger
from tornado import web, websocket

from jupyter_server.auth import authorized
from jupyter_server.base.handlers import JupyterHandler

from ...base.handlers import APIHandler

AUTH_RESOURCE = "events"


class SubscribeWebsocket(
    JupyterHandler,
    websocket.WebSocketHandler,
):
    """Websocket handler for subscribing to events"""

    auth_resource = AUTH_RESOURCE

    def pre_get(self):
        """Handles authentication/authorization when
        attempting to subscribe to events emitted by
        Jupyter Server's eventbus.
        """
        # authenticate the request before opening the websocket
        user = self.current_user
        if user is None:
            self.log.warning("Couldn't authenticate WebSocket connection")
            raise web.HTTPError(403)

        # authorize the user.
        if not self.authorizer.is_authorized(self, user, "execute", "events"):
            raise web.HTTPError(403)

    async def get(self, *args, **kwargs):
        """Get an event socket."""
        self.pre_get()
        res = super().get(*args, **kwargs)
        if res is not None:
            await res

    async def event_listener(self, logger: EventLogger, schema_id: str, data: dict) -> None:
        """Write an event message."""
        capsule = dict(schema_id=schema_id, **data)
        self.write_message(json.dumps(capsule))

    def open(self):
        """Routes events that are emitted by Jupyter Server's
        EventBus to a WebSocket client in the browser.
        """
        self.event_logger.add_listener(listener=self.event_listener)

    def on_close(self):
        """Handle a socket close."""
        self.event_logger.remove_listener(listener=self.event_listener)


def validate_model(data: Dict[str, Any]) -> None:
    """Validates for required fields in the JSON request body"""
    required_keys = {"schema_id", "version", "data"}
    for key in required_keys:
        if key not in data:
            raise web.HTTPError(400, f"Missing `{key}` in the JSON request body.")


def get_timestamp(data: Dict[str, Any]) -> Optional[datetime]:
    """Parses timestamp from the JSON request body"""
    try:
        if "timestamp" in data:
            timestamp = datetime.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%S%zZ")
        else:
            timestamp = None
    except Exception as e:
        raise web.HTTPError(
            400,
            """Failed to parse timestamp from JSON request body,
            an ISO format datetime string with UTC offset is expected,
            for example, 2022-05-26T13:50:00+05:00Z""",
        ) from e

    return timestamp


class EventHandler(APIHandler):
    """REST api handler for events"""

    auth_resource = AUTH_RESOURCE

    @web.authenticated
    @authorized
    async def post(self):
        """Emit an event."""
        payload = self.get_json_body()
        if payload is None:
            raise web.HTTPError(400, "No JSON data provided")

        try:
            validate_model(payload)
            self.event_logger.emit(
                schema_id=payload.get("schema_id"),
                data=payload.get("data"),
                timestamp_override=get_timestamp(payload),
            )
            self.set_status(204)
            self.finish()
        except web.HTTPError:
            raise
        except Exception as e:
            raise web.HTTPError(500, str(e)) from e


default_handlers = [
    (r"/api/events", EventHandler),
    (r"/api/events/subscribe", SubscribeWebsocket),
]
