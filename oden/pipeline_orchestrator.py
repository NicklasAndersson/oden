"""Pipeline orchestration for Oden 3.0.

Initial implementation runs the existing generic processing flow as the first
pipeline while recording pipeline run status and events in SQLite.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from oden.messages_db import (
    STATUS_FAILED,
    STATUS_PROCESSED,
    STATUS_PROCESSING,
    get_message_detail,
    update_message_status,
)
from oden.pipelines.generic_template import GenericTemplatePipeline
from oden.pipelines_db import (
    append_pipeline_event,
    complete_pipeline_run,
    fail_pipeline_run,
    start_pipeline_run,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Execute one or more pipelines for stored raw messages."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._generic_pipeline = GenericTemplatePipeline()

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
        - Runs the legacy processing flow as pipeline `generic_template`
        - Tracks run state/events in pipeline tables
        - Updates raw message status to processed/failed
        """
        update_message_status(self._db_path, message_id, STATUS_PROCESSING)

        run_id = start_pipeline_run(self._db_path, message_id, self._generic_pipeline.name)
        append_pipeline_event(
            self._db_path,
            run_id,
            "pipeline_started",
            {"pipeline": self._generic_pipeline.name},
        )

        try:
            await self._generic_pipeline.run(
                msg_data=msg_data,
                reader=reader,
                writer=writer,
            )
            complete_pipeline_run(self._db_path, run_id)
            append_pipeline_event(
                self._db_path,
                run_id,
                "pipeline_completed",
                {"pipeline": self._generic_pipeline.name},
            )
            update_message_status(self._db_path, message_id, STATUS_PROCESSED)
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
                    "pipeline": self._generic_pipeline.name,
                    "error": repr(exc),
                },
            )
            update_message_status(self._db_path, message_id, STATUS_FAILED)
            raise

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
