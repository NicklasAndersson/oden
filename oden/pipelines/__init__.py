"""Pipeline interfaces and built-in pipeline implementations."""

from __future__ import annotations

from typing import Any, Protocol


class MessagePipeline(Protocol):
    """Protocol for message pipelines executed by PipelineOrchestrator."""

    name: str

    async def run(
        self,
        *,
        msg_data: dict[str, Any],
        reader: Any,
        writer: Any,
    ) -> None:
        """Execute pipeline logic for one message."""
