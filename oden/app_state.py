"""
Shared application state for cross-module communication.

Provides a singleton to share the signal-cli writer between watcher and web server.
"""

import asyncio
from dataclasses import dataclass, field


@dataclass
class AppState:
    """Shared application state."""

    writer: asyncio.StreamWriter | None = None
    reader: asyncio.StreamReader | None = None
    _request_id: int = field(default=0, repr=False)
    # Cached groups list, updated by the main watcher loop
    groups: list[dict] = field(default_factory=list)

    def get_next_request_id(self) -> str:
        """Generate a unique request ID for JSON-RPC calls."""
        self._request_id += 1
        return f"web-{self._request_id}"

    def update_groups(self, groups: list[dict]) -> None:
        """Update the cached groups list."""
        self.groups = groups

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


# Global singleton instance
_app_state: AppState | None = None


def get_app_state() -> AppState:
    """Get or create the global app state singleton."""
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state
