"""Pipeline orchestration for Oden 3.0.

Initial implementation runs the existing generic processing flow as the first
pipeline while recording pipeline run status and events in SQLite.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from oden import config as cfg
from oden.messages_db import (
    STATUS_FAILED,
    STATUS_IGNORED,
    STATUS_PROCESSED,
    STATUS_PROCESSING,
    get_message_detail,
    update_message_status,
)
from oden.pipelines.fors import ForsPipeline
from oden.pipelines.group_filter import GroupFilterPipeline
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
            "group_filter": GroupFilterPipeline(),
            "seven_s": SevenSPipeline(),
            "fors": ForsPipeline(),
            "generic_template": _GenericPipeline(),
        }
        self._cached_config: list | None = None
        self._cached_pipelines: list[Any] = []

    def _build_pipelines(self) -> list[Any]:
        config: list = cfg.ENABLED_PIPELINES or ["group_filter", "seven_s", "fors", "generic_template"]
        # ponytail: identity check detects cfg.ENABLED_PIPELINES = new_list reassignments
        if config is not self._cached_config:
            names = list(config)
            if "generic_template" not in names:
                names.append("generic_template")
            selected = [self._pipeline_map[n] for n in names if n in self._pipeline_map]
            self._cached_pipelines = selected or [self._pipeline_map["generic_template"]]
            self._cached_config = config
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

                for warning in getattr(pipeline, "last_warnings", []) or []:
                    append_pipeline_event(
                        self._db_path,
                        run_id,
                        "pipeline_warning",
                        {
                            "pipeline": pipeline.name,
                            **warning,
                        },
                    )

                if handled:
                    complete_pipeline_run(self._db_path, run_id)
                    append_pipeline_event(
                        self._db_path,
                        run_id,
                        "pipeline_completed",
                        {"pipeline": pipeline.name},
                    )
                    status_on_handle = getattr(pipeline, "status_on_handle", STATUS_PROCESSED)
                    if status_on_handle not in {STATUS_PROCESSED, STATUS_IGNORED}:
                        status_on_handle = STATUS_PROCESSED
                    update_message_status(self._db_path, message_id, status_on_handle)
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
