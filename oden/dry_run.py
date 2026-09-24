"""Testruta: what would happen to a message — vägval, each step and its reason,
and the file that would be written — without anything happening.

Nothing is written to the vault, sent to Signal or TAK, or stored in the
database. The steps are fresh pipeline instances, so a test never disturbs the
``last_*`` state of the ones handling real messages.
"""

from __future__ import annotations

import os
import time
from typing import Any

from oden import config as cfg
from oden.processing import preview_message
from oden.routing import (
    FALLBACK,
    SIDE_EFFECT,
    branch_steps,
    load_routing,
    reset_step_config,
    resolve_branch_detail,
    set_step_config,
)

TEST_SENDER = "+46700000000"


def build_test_message(text: str, source: str, *, group_id: str | None = None) -> dict[str, Any]:
    """An envelope like a real one from ``source`` (``source:tak``, ``source:direct`` or ``group:<name>``)."""
    envelope: dict[str, Any] = {
        "sourceNumber": "tak:testruta" if source == "source:tak" else TEST_SENDER,
        "sourceName": "Testruta",
        "sourceUuid": "testruta",
        "timestamp": int(time.time() * 1000),
        "dataMessage": {"message": text},
    }
    if source == "source:tak":
        envelope["_source"] = "tak"
    elif source.startswith("group:"):
        name = source.removeprefix("group:")
        envelope["dataMessage"]["groupV2"] = {"id": group_id or f"testruta-{name}", "name": name}
    return {"envelope": envelope}


def publish_to_tak() -> bool:
    from oden.tak.bridge import get_tak_bridge

    bridge = get_tak_bridge()
    return bridge is not None and bool(getattr(bridge, "settings", {}).get("publish_reports"))


def _fresh_pipelines() -> dict[str, Any]:
    from oden.pipelines.fors import ForsPipeline
    from oden.pipelines.pedars import PedarsPipeline
    from oden.pipelines.scrim import ScrimPipeline
    from oden.pipelines.seven_s import SevenSPipeline

    return {p.name: p for p in (SevenSPipeline(), ForsPipeline(), PedarsPipeline(), ScrimPipeline())}


def _relative(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return os.path.relpath(path, cfg.VAULT_PATH)
    except (TypeError, ValueError):
        return path


def _warnings(raw: Any) -> list[str]:
    return [w.get("message", str(w)) if isinstance(w, dict) else str(w) for w in raw or []]


async def dry_run(msg_data: dict[str, Any], routing: dict[str, Any] | None = None) -> dict[str, Any]:
    """The route a message would take now. Steps after the one that takes it are ``notrun``."""
    routing = routing or load_routing(cfg)
    branch, reason, key = resolve_branch_detail(routing, msg_data)
    result: dict[str, Any] = {
        "branch": branch["id"],
        "branch_name": branch["name"],
        "ignore": bool(branch.get("ignore")),
        "route_reason": reason,
        "assigned": key is not None,
        "steps": [],
        "handled_by": None,
        "output_file": None,
        "content": None,
    }
    if result["ignore"]:
        return result

    pipelines = _fresh_pipelines()
    for step in branch_steps(branch, publish_to_tak=publish_to_tak()):
        name = step["pipeline"]
        if result["handled_by"]:
            result["steps"].append(
                {"pipeline": name, "outcome": "notrun", "reason": "Körs inte – ett tidigare steg tog meddelandet"}
            )
            continue
        if name == SIDE_EFFECT:
            result["steps"].append(
                {"pipeline": name, "outcome": "side", "reason": "Skulle publiceras till TAK (görs inte i Testrutan)"}
            )
            continue

        token = set_step_config(step.get("config"))
        try:
            if name == FALLBACK:
                outcome, content = preview_message(msg_data)
                entry = {
                    "pipeline": name,
                    "outcome": "handled" if outcome.action in ("wrote", "command") else "skipped",
                    "reason": outcome.reason,
                    "output_file": _relative(outcome.path),
                }
            elif name in pipelines:
                preview = await pipelines[name].preview(msg_data)
                content = preview.get("content")
                entry = {
                    "pipeline": name,
                    "outcome": "failed" if preview.get("failed") else ("handled" if preview["handled"] else "skipped"),
                    "reason": preview.get("reason"),
                    "output_file": _relative(preview.get("output_file")),
                    "warnings": _warnings(preview.get("warnings")),
                }
            else:
                continue
        finally:
            reset_step_config(token)

        result["steps"].append(entry)
        # The fallback always ends the branch; its "skipped" still ends the run.
        if entry["outcome"] == "handled" or name == FALLBACK:
            result["handled_by"] = name
            result["output_file"] = entry.get("output_file")
            result["content"] = content
    return result
