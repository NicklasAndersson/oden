"""
In-memory log buffer for web GUI display.

Provides a logging handler that stores recent log entries in a circular buffer.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LogEntry:
    """A single log entry."""

    timestamp: str
    level: str
    name: str
    message: str


class LogBuffer(logging.Handler):
    """A logging handler that stores log entries in a circular buffer.

    The buffer holds a maximum number of entries (default 500).
    Oldest entries are discarded when the buffer is full.
    """

    def __init__(self, max_entries: int = 500) -> None:
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=max_entries)
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Store a log record in the buffer."""
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                level=record.levelname,
                name=record.name,
                message=self.format(record).split(" - ", 3)[-1]
                if " - " in self.format(record)
                else record.getMessage(),
            )
            self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_entries(self, limit: int | None = None) -> list[dict]:
        """Get log entries as a list of dictionaries.

        Args:
            limit: Maximum number of entries to return (newest first).
                   If None, returns all entries.

        Returns:
            List of log entry dictionaries.
        """
        entries = list(self._buffer)
        if limit:
            entries = entries[-limit:]
        return [
            {
                "timestamp": entry.timestamp,
                "level": entry.level,
                "name": entry.name,
                "message": entry.message,
            }
            for entry in entries
        ]

    def clear(self) -> None:
        """Clear all entries from the buffer."""
        self._buffer.clear()


# Global singleton instance
_log_buffer: LogBuffer | None = None


def get_log_buffer() -> LogBuffer:
    """Get or create the global log buffer singleton."""
    global _log_buffer
    if _log_buffer is None:
        _log_buffer = LogBuffer()
    return _log_buffer
