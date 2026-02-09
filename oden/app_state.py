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
    # System tray icon controller (set by main if available)
    tray: Any = None  # OdenTray | None

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

    def update_groups(self, groups: list[dict]) -> None:
        """Update the cached groups list."""
        self.groups = groups
        logger.info("Updated cached groups list (%d groups)", len(groups))

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
