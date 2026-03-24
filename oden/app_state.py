"""
Shared application state for cross-module communication.

Provides a singleton to share the signal-cli writer between watcher and web server.
Also holds lifecycle events (stop/start/quit) used to coordinate between the
pystray thread, the web server, and the asyncio watcher loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Shared application state."""

    writer: asyncio.StreamWriter | None = None
    reader: asyncio.StreamReader | None = None
    _request_id: int = field(default=0, repr=False)
    # Cached groups list, updated by the main watcher loop
    groups: list[dict] = field(default_factory=list)
    # Cached contacts dict (keyed by phone number), updated at startup + manual refresh
    contacts: dict[str, dict] = field(default_factory=dict)
    # System tray icon controller (set by main if available)
    tray: Any = None  # OdenTray | None

    # --- JSON-RPC dispatcher state ---
    # Pending RPC responses: request_id → Future
    rpc_pending: dict[str, asyncio.Future] = field(default_factory=dict, repr=False)
    # Queue for incoming receive notifications (consumed by listener loop)
    notification_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)

    # --- Account linking state (set by account_handlers) ---
    link_status: str = "idle"  # idle, waiting, linked, error
    link_uri: str | None = None
    linked_number: str | None = None
    link_error: str | None = None

    # --- Lifecycle fields (set by _run_lifecycle) ---
    loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    stop_event: asyncio.Event | None = field(default=None, repr=False)
    start_event: asyncio.Event | None = field(default=None, repr=False)
    quit_event: asyncio.Event | None = field(default=None, repr=False)
    signal_manager: Any = field(default=None, repr=False)  # SignalManager | None

    def get_next_request_id(self) -> str:
        """Generate a unique request ID for JSON-RPC calls."""
        self._request_id += 1
        return f"web-{self._request_id}"

    async def send_jsonrpc(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict | None:
        """Send a JSON-RPC request and await the response via the central dispatcher.

        The reader dispatcher (run in subscribe_and_listen) routes responses
        by matching request id to a Future stored in rpc_pending.

        Returns the parsed response dict, or None on timeout/error.
        """
        import json

        if not self.writer:
            return None

        request_id = self.get_next_request_id()
        request = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params:
            request["params"] = params

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        self.rpc_pending[request_id] = future

        try:
            self.writer.write((json.dumps(request) + "\n").encode("utf-8"))
            await self.writer.drain()
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for %s response (id=%s)", method, request_id)
            return None
        except (OSError, ConnectionError) as e:
            logger.error("Error in JSON-RPC call %s: %s", method, e)
            return None
        finally:
            self.rpc_pending.pop(request_id, None)

    def dispatch_line(self, data: dict) -> None:
        """Route a parsed JSON line to the correct consumer.

        Called by the single reader loop in subscribe_and_listen().
        - If 'id' matches a pending RPC Future → resolve it.
        - If it's a receive notification → put on notification_queue.
        - Otherwise log and discard.
        """
        response_id = data.get("id")
        if response_id and response_id in self.rpc_pending:
            future = self.rpc_pending.pop(response_id)
            if not future.done():
                future.set_result(data)
            return

        if data.get("method") == "receive":
            self.notification_queue.put_nowait(data)
            return

        # Log fire-and-forget responses (e.g. updateProfile, send) at debug level
        if response_id:
            logger.debug("Received unmatched RPC response id=%s", response_id)
        else:
            logger.debug("Received non-message data: %s", data)

    def update_groups(self, groups: list[dict]) -> None:
        """Update the cached groups list."""
        self.groups = groups
        logger.info("Updated cached groups list (%d groups)", len(groups))

    def update_contacts(self, contacts_list: list[dict]) -> None:
        """Update the cached contacts dict (keyed by phone number)."""
        self.contacts = {}
        for contact in contacts_list:
            number = contact.get("number")
            if number:
                self.contacts[number] = contact
        logger.info("Updated cached contacts (%d contacts)", len(self.contacts))

    def resolve_contact_name(self, source_number: str | None, envelope_name: str | None) -> str:
        """Resolve a display name for a sender, falling back to contact cache.

        Priority:
        1. envelope sourceName (Signal profile name set by sender)
        2. Contact name from listContacts cache (set by Oden user)
        3. "Okänd" as last resort
        """
        if envelope_name and envelope_name != source_number:
            return envelope_name
        if source_number and source_number in self.contacts:
            contact = self.contacts[source_number]
            name = contact.get("name") or contact.get("nickName")
            if name:
                return name
        return envelope_name or "Okänd"

    def get_pending_invitations(self) -> list[dict]:
        """Get groups where the user has a pending invitation."""
        invitations = []
        for group in self.groups:
            # Check if user is a pending member (invited but not yet accepted)
            if group.get("isMember") is False or group.get("invitedToGroup") is True:
                invitations.append(
                    {
                        "id": group.get("id"),
                        "name": group.get("name", "Okänd grupp"),
                        "memberCount": len(group.get("members", [])),
                    }
                )
        return invitations

    # --- Thread-safe lifecycle helpers ---
    # These are called from the pystray thread or web handlers and
    # safely signal the asyncio event loop.

    def request_stop(self) -> None:
        """Signal the asyncio loop to stop the signal-cli listener.

        The web server stays running. Called from the tray "Stoppa" button.
        """
        if self.loop is not None and self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)

    def request_start(self) -> None:
        """Signal the asyncio loop to (re-)start the signal-cli listener.

        Called from the tray "Starta" button.
        """
        if self.loop is not None and self.start_event is not None:
            self.loop.call_soon_threadsafe(self.start_event.set)
        # Also update the tray icon so _wait logic can unblock
        if self.tray is not None:
            self.tray.running = True

    def request_quit(self) -> None:
        """Signal the asyncio loop to shut down everything.

        Called from tray "Avsluta" button or the web /api/shutdown endpoint.
        """
        if self.loop is not None:
            if self.quit_event is not None:
                self.loop.call_soon_threadsafe(self.quit_event.set)
            # Also set stop_event so the listener task is cancelled
            if self.stop_event is not None:
                self.loop.call_soon_threadsafe(self.stop_event.set)


# Global singleton instance
_app_state: AppState | None = None


def get_app_state() -> AppState:
    """Get or create the global app state singleton."""
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state
