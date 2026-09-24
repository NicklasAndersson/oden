"""Pipeline orchestration for Oden 3.0.

Initial implementation runs the existing generic processing flow as the first
pipeline while recording pipeline run status and events in SQLite.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from oden.pipelines.pedars import PedarsPipeline
from oden.pipelines.scrim import ScrimPipeline
from oden.pipelines.seven_s import SevenSPipeline
from oden.pipelines.tak_publish import TakPublishPipeline
from oden.pipelines_db import (
    append_pipeline_event,
    complete_pipeline_run,
    fail_pipeline_run,
    skip_pipeline_run,
    start_pipeline_run,
)
from oden.processing import process_message
from oden.routing import (
    ROUTER,
    branch_by_id,
    branch_steps,
    load_routing,
    reset_step_config,
    resolve_branch,
    set_step_config,
)
from oden.tak.bridge import get_tak_bridge

logger = logging.getLogger(__name__)

# Per-run attributes a pipeline may set to explain itself in the Flöde view.
# The orchestrator clears them before every run so a reused pipeline instance
# never reports the previous message's reason.
#   last_reason       — why it handled or skipped the message (Swedish, one line)
#   last_side_effect  — what a non-consuming pipeline did anyway (e.g. TAK publish)
#   last_output_file  — the vault file it wrote or appended to
_RUN_ATTRS = ("last_reason", "last_side_effect", "last_output_file")


def _reset_run_attrs(pipeline: Any) -> None:
    for attr in _RUN_ATTRS:
        with contextlib.suppress(AttributeError):
            setattr(pipeline, attr, None)


def _details(pipeline: Any, **extra: Any) -> dict[str, Any]:
    details: dict[str, Any] = {"pipeline": pipeline.name, **extra}
    reason = getattr(pipeline, "last_reason", None)
    if reason:
        details["reason"] = reason
    return details


class _GenericPipeline:
    name = "generic_template"
    display_name = "Generisk mall-pipeline"
    description = "Standardflödet som skriver meddelanden till markdown enligt rapport/append-mallar."
    selection_criteria = "Fallback: körs för alla meddelanden som inte redan hanterats av tidigare pipeline."

    async def run(self, *, msg_data: dict, reader: Any, writer: Any) -> bool:
        outcome = await process_message(msg_data, reader, writer)
        if outcome is None:
            return True
        if outcome.action == "error":
            raise OSError(outcome.reason)
        self.last_reason = outcome.reason
        self.last_output_file = outcome.path
        return True


class PipelineOrchestrator:
    """Execute one or more pipelines for stored raw messages."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._pipeline_map: dict[str, Any] = {
            "tak_publish": TakPublishPipeline(),
            "group_filter": GroupFilterPipeline(),
            "seven_s": SevenSPipeline(),
            "fors": ForsPipeline(),
            "pedars": PedarsPipeline(),
            "scrim": ScrimPipeline(),
            "generic_template": _GenericPipeline(),
        }
        self._step_configs: dict[str, dict[str, Any]] = {}

    def _publish_to_tak(self) -> bool:
        # tak_publish writes to TAK; Oden collects by default, so it only runs
        # when the operator turned on publish_reports in the TAK tab.
        bridge = get_tak_bridge()
        return bridge is not None and bool(getattr(bridge, "settings", {}).get("publish_reports"))

    def _build_pipelines(self, branch: dict[str, Any] | None = None) -> list[Any]:
        """The pipelines that run in ``branch`` (default: the routing's standard branch), in order.

        Also records each step's config overrides in ``self._step_configs`` for run_message.
        """
        if branch is None:
            routing = load_routing(cfg)
            branch = branch_by_id(routing, routing["default"]) or routing["branches"][0]
        steps = branch_steps(branch, publish_to_tak=self._publish_to_tak())
        self._step_configs = {s["pipeline"]: s.get("config") or {} for s in steps}
        return [self._pipeline_map[s["pipeline"]] for s in steps if s["pipeline"] in self._pipeline_map]

    def _record_route(self, message_id: int, branch: dict[str, Any], reason: str) -> None:
        """The vägval as the first run of the attempt, so Flöde and stats see it like any step."""
        run_id = start_pipeline_run(self._db_path, message_id, ROUTER)
        complete_pipeline_run(self._db_path, run_id)
        append_pipeline_event(
            self._db_path,
            run_id,
            "pipeline_completed",
            {
                "pipeline": ROUTER,
                "reason": reason,
                "branch": branch["id"],
                "branch_name": branch["name"],
                "ignore": bool(branch.get("ignore")),
            },
        )

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
        - Vägval first: the message's source picks a branch (recorded as a
          ``router`` run); an ignore branch stops here with status ignored
        - Then the branch's enabled steps in order, each with its own config
          overrides (routing.step_settings); first pipeline that handles it wins
        - Tracks run state/events in pipeline tables
        - Updates raw message status to processed/failed
        """
        update_message_status(self._db_path, message_id, STATUS_PROCESSING)

        routing = load_routing(cfg)
        branch, route_reason = resolve_branch(routing, msg_data)
        self._record_route(message_id, branch, route_reason)
        if branch.get("ignore"):
            update_message_status(self._db_path, message_id, STATUS_IGNORED)
            return

        # Each step sets its own config overrides; the outer token puts the
        # caller's context back however the steps end.
        token = set_step_config({})
        try:
            await self._run_steps(message_id, msg_data, reader, writer, branch)
        finally:
            reset_step_config(token)

    async def _run_steps(
        self,
        message_id: int,
        msg_data: dict[str, Any],
        reader: Any,
        writer: Any,
        branch: dict[str, Any],
    ) -> None:
        """Run the branch's steps; first one that handles the message wins."""
        had_pipeline_failure = False
        self._step_configs: dict[str, dict[str, Any]] = {}
        for pipeline in self._build_pipelines(branch):
            _reset_run_attrs(pipeline)
            set_step_config(self._step_configs.get(pipeline.name))
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

                side_effect = getattr(pipeline, "last_side_effect", None)
                if side_effect:
                    append_pipeline_event(
                        self._db_path,
                        run_id,
                        "pipeline_side_effect",
                        {"pipeline": pipeline.name, "message": side_effect},
                    )

                output_file = getattr(pipeline, "last_output_file", None)
                if handled:
                    complete_pipeline_run(self._db_path, run_id, output_file=output_file)
                    append_pipeline_event(
                        self._db_path,
                        run_id,
                        "pipeline_completed",
                        _details(pipeline, output_file=output_file) if output_file else _details(pipeline),
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
                    _details(pipeline),
                )
            except Exception as exc:
                had_pipeline_failure = True
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
                logger.warning(
                    "Pipeline %s failed for message %s; continuing with next pipeline. Error: %r",
                    pipeline.name,
                    message_id,
                    exc,
                )
                continue

        # If no pipeline handled the message, mark failed if any pipeline crashed,
        # otherwise keep the legacy processed fallback for all-skipped chains.
        if had_pipeline_failure:
            update_message_status(self._db_path, message_id, STATUS_FAILED)
            return

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
