"""
In-memory log buffer for web GUI display.

Provides a logging handler that stores recent log entries in a circular buffer.
"""

import logging
from collections import deque
from datetime import datetime


class LogBuffer(logging.Handler):
    """A logging handler that stores log entries in a circular buffer.

    The buffer holds a maximum number of entries (default 500).
    Oldest entries are discarded when the buffer is full.
    """

    def __init__(self, max_entries: int = 500) -> None:
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=max_entries)
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Store a log record in the buffer."""
        try:
            formatted = self.format(record)
            self._buffer.append(
                {
                    "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                    "level": record.levelname,
                    "name": record.name,
                    "message": formatted.split(" - ", 3)[-1] if " - " in formatted else record.getMessage(),
                }
            )
        except Exception:
            self.handleError(record)

    def get_entries(self, limit: int | None = None) -> list[dict]:
        entries = list(self._buffer)
        if limit:
            entries = entries[-limit:]
        return entries

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
