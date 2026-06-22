"""Generic template pipeline.

Wraps current processing behavior so the orchestrator can run it as a named
pipeline while we transition to a multi-pipeline architecture.
"""

from __future__ import annotations

import asyncio
from typing import Any

from oden.processing import process_message


class GenericTemplatePipeline:
    """Pipeline wrapper around the legacy process_message flow."""

    name = "generic_template"
    display_name = "Generisk mall-pipeline"
    description = "Standardflödet som skriver meddelanden till markdown enligt rapport/append-mallar."
    selection_criteria = "Fallback: körs för alla meddelanden som inte redan hanterats av tidigare pipeline."

    async def run(
        self,
        *,
        msg_data: dict[str, Any],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        await process_message(msg_data, reader, writer)
        return True
