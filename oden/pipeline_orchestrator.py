"""Pipeline orchestration for Oden 3.0.

Initial implementation runs the existing generic processing flow as the first
pipeline while recording pipeline run status and events in SQLite.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from oden import config as cfg
from oden.messages_db import (
    STATUS_FAILED,
    STATUS_PROCESSED,
    STATUS_PROCESSING,
    get_message_detail,
    update_message_status,
)
from oden.pipelines.seven_s import SevenSPipeline
from oden.pipelines_db import (
    append_pipeline_event,
    complete_pipeline_run,
    fail_pipeline_run,
    skip_pipeline_run,
    start_pipeline_run,
)
from oden.processing import process_message

logger = logging.getLogger(__name__)


def _normalize_enabled_pipeline_names(value: Any) -> list[str]:
    names: list[str] = []

    if isinstance(value, list):
        names = [name for name in value if isinstance(name, str) and name]
    elif isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

            if isinstance(parsed, list):
                names = [name for name in parsed if isinstance(name, str) and name]
            else:
                names = [name.strip() for name in raw.split(",") if name.strip()]

    if not names:
        names = ["seven_s", "generic_template"]

    if "generic_template" not in names:
        names.append("generic_template")

    return list(dict.fromkeys(names))


class _GenericPipeline:
    name = "generic_template"
    display_name = "Generisk mall-pipeline"
    description = "Standardflödet som skriver meddelanden till markdown enligt rapport/append-mallar."
    selection_criteria = "Fallback: körs för alla meddelanden som inte redan hanterats av tidigare pipeline."

    async def run(self, *, msg_data: dict, reader: Any, writer: Any) -> bool:
        await process_message(msg_data, reader, writer)
        return True


class PipelineOrchestrator:
    """Execute one or more pipelines for stored raw messages."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._pipeline_map: dict[str, Any] = {
            "seven_s": SevenSPipeline(),
            "generic_template": _GenericPipeline(),
        }
        self._cached_pipeline_key: tuple[str, ...] | None = None
        self._cached_pipelines: list[Any] = []

    def _build_pipelines(self) -> list[Any]:
        names = _normalize_enabled_pipeline_names(cfg.ENABLED_PIPELINES)
        key = tuple(names)

        if key != self._cached_pipeline_key:
            selected = [self._pipeline_map[n] for n in names if n in self._pipeline_map]
            self._cached_pipelines = selected or [self._pipeline_map["generic_template"]]
            self._cached_pipeline_key = key
        return self._cached_pipelines

    async def run_message(
        self,
        *,
        message_id: int,
        msg_data: dict[str, Any],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Run configured pipelines for one message.

        Current behavior:
        - Runs configured pipelines in order from ENABLED_PIPELINES
        - First pipeline that handles the message ends the chain
        - Tracks run state/events in pipeline tables
        - Updates raw message status to processed/failed
        """
        update_message_status(self._db_path, message_id, STATUS_PROCESSING)
        for pipeline in self._build_pipelines():
            run_id = start_pipeline_run(self._db_path, message_id, pipeline.name)
            append_pipeline_event(
                self._db_path,
                run_id,
                "pipeline_started",
                {"pipeline": pipeline.name},
            )

            try:
                handled = await pipeline.run(
                    msg_data=msg_data,
                    reader=reader,
                    writer=writer,
                )

                if handled:
                    complete_pipeline_run(self._db_path, run_id)
                    append_pipeline_event(
                        self._db_path,
                        run_id,
                        "pipeline_completed",
                        {"pipeline": pipeline.name},
                    )
                    update_message_status(self._db_path, message_id, STATUS_PROCESSED)
                    return

                skip_pipeline_run(self._db_path, run_id)
                append_pipeline_event(
                    self._db_path,
                    run_id,
                    "pipeline_skipped",
                    {"pipeline": pipeline.name},
                )
            except Exception as exc:
                fail_pipeline_run(
                    self._db_path,
                    run_id,
                    error_code="pipeline_exception",
                    error_message=repr(exc),
                )
                append_pipeline_event(
                    self._db_path,
                    run_id,
                    "pipeline_failed",
                    {
                        "pipeline": pipeline.name,
                        "error": repr(exc),
                    },
                )
                update_message_status(self._db_path, message_id, STATUS_FAILED)
                raise

        # Defensive fallback if all configured pipelines skipped unexpectedly.
        update_message_status(self._db_path, message_id, STATUS_PROCESSED)

    async def reprocess(
        self,
        *,
        message_id: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        """Reprocess a stored message by id.

        Returns True if message exists and reprocessing was attempted.
        Returns False if message id is missing.
        """
        detail = get_message_detail(self._db_path, message_id)
        if not detail:
            return False

        raw_message = detail.get("envelope_raw")
        if not isinstance(raw_message, dict):
            logger.error("Cannot reprocess message %s: envelope_raw is not an object", message_id)
            return False

        await self.run_message(
            message_id=message_id,
            msg_data=raw_message,
            reader=reader,
            writer=writer,
        )
        return True
