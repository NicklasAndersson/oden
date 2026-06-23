"""Pipeline administration handlers for the web API.

Endpoints:
  GET /api/pipelines              - List all available and enabled pipelines
  PATCH /api/pipelines/{name}/enabled - Enable/disable a pipeline
  POST /api/pipelines/reorder     - Change execution order
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from aiohttp import web

from oden import config as cfg
from oden.config_db import set_config_value
from oden.pipeline_orchestrator import _GenericPipeline
from oden.pipeline_settings import normalize_group_filter_settings, normalize_pipeline_settings
from oden.pipelines.group_filter import GroupFilterPipeline
from oden.pipelines.seven_s import SevenSPipeline
from oden.web_handlers._helpers import handle_errors, parse_json_body

logger = logging.getLogger(__name__)

# Static pipeline metadata registry — update when adding new pipelines.
_AVAILABLE_PIPELINES: dict[str, dict[str, Any]] = {
    "group_filter": {
        "name": GroupFilterPipeline.name,
        "display_name": GroupFilterPipeline.display_name,
        "description": GroupFilterPipeline.description,
        "selection_criteria": GroupFilterPipeline.selection_criteria,
        "supports_config": True,
        "config_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["blacklist", "whitelist"]},
                "groups": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["mode", "groups"],
        },
    },
    "seven_s": {
        "name": SevenSPipeline.name,
        "display_name": SevenSPipeline.display_name,
        "description": SevenSPipeline.description,
        "selection_criteria": SevenSPipeline.selection_criteria,
        "supports_config": False,
        "config_schema": None,
    },
    "generic_template": {
        "name": _GenericPipeline.name,
        "display_name": _GenericPipeline.display_name,
        "description": _GenericPipeline.description,
        "selection_criteria": _GenericPipeline.selection_criteria,
        "supports_config": False,
        "config_schema": None,
    },
}


def _get_available_pipelines() -> dict[str, dict[str, Any]]:
    return _AVAILABLE_PIPELINES


def _get_pipeline_settings() -> dict[str, Any]:
    return normalize_pipeline_settings(cfg.PIPELINE_SETTINGS)


def _save_pipeline_settings(settings: dict[str, Any]) -> None:
    set_config_value(cfg.CONFIG_DB, "pipeline_settings", settings)
    cfg.PIPELINE_SETTINGS = settings


@handle_errors("listing pipelines")
async def list_pipelines(request: web.Request) -> web.Response:
    """List all available and enabled pipelines.

    GET /api/pipelines

    Response:
    {
      "available": [
        {
          "name": "seven_s",
          "display_name": "Seven S RAPPORT-pipeline",
          "description": "...",
          "selection_criteria": "...",
          "supports_config": false,
          "config_schema": null
        },
        ...
      ],
      "enabled": [
        {
          "order": 1,
          "name": "seven_s",
          "enabled": true,
          "config": {}
        },
        ...
      ],
      "stats": {
        "total_processed": 4768,
        "by_pipeline": {
          "seven_s": 247,
          "generic_template": 4521
        }
      }
    }
    """
    available = _get_available_pipelines()

    # Get enabled pipelines from config
    enabled_list: list[str] = cfg.ENABLED_PIPELINES or ["generic_template"]
    pipeline_settings = _get_pipeline_settings()
    enabled_pipelines = [
        {
            "order": i + 1,
            "name": name,
            "enabled": True,
            "config": pipeline_settings.get(name, {}),
        }
        for i, name in enumerate(enabled_list)
    ]

    # Get statistics from database
    stats = _get_pipeline_stats()

    return web.json_response(
        {
            "available": list(available.values()),
            "enabled": enabled_pipelines,
            "stats": stats,
        }
    )


@handle_errors("toggling pipeline")
@parse_json_body
async def toggle_pipeline(request: web.Request) -> web.Response:
    """Enable or disable a specific pipeline.

    PATCH /api/pipelines/{name}/enabled

    Request:
    {
      "enabled": true
    }

    Response:
    {
      "success": true,
      "updated_list": ["seven_s", "generic_template"]
    }
    """
    pipeline_name = request.match_info.get("name", "")
    if not pipeline_name:
        return web.json_response(
            {"error": "Pipeline name required"},
            status=400,
        )

    data = request["json_body"]
    enabled = data.get("enabled", False)

    # Get current enabled list
    current_list: list[str] = cfg.ENABLED_PIPELINES or ["generic_template"]

    # Update list
    if enabled and pipeline_name not in current_list:
        current_list.append(pipeline_name)
    elif not enabled and pipeline_name in current_list:
        current_list.remove(pipeline_name)

    # Ensure generic_template is always present as fallback
    if "generic_template" not in current_list:
        current_list.append("generic_template")

    # Save to config
    set_config_value(cfg.CONFIG_DB, "enabled_pipelines", current_list)

    # Update in-memory config
    cfg.ENABLED_PIPELINES = current_list

    logger.info("Pipeline %s %s", pipeline_name, "enabled" if enabled else "disabled")

    return web.json_response(
        {
            "success": True,
            "updated_list": current_list,
        }
    )


@handle_errors("reordering pipelines")
@parse_json_body
async def reorder_pipelines(request: web.Request) -> web.Response:
    """Change the execution order of pipelines.

    POST /api/pipelines/reorder

    Request:
    {
      "order": ["generic_template", "seven_s"]
    }

    Response:
    {
      "success": true,
      "updated_list": ["generic_template", "seven_s"]
    }
    """
    data = request["json_body"]
    new_order: list[str] = data.get("order", [])

    if not isinstance(new_order, list):
        return web.json_response(
            {"error": "order must be a list"},
            status=400,
        )

    # Validate all names are valid pipelines
    available = _get_available_pipelines()
    for name in new_order:
        if name not in available:
            return web.json_response(
                {"error": f"Unknown pipeline: {name}"},
                status=400,
            )

    # Ensure generic_template is present
    if "generic_template" not in new_order:
        new_order.append("generic_template")

    # Save to config
    set_config_value(cfg.CONFIG_DB, "enabled_pipelines", new_order)

    # Update in-memory config
    cfg.ENABLED_PIPELINES = new_order

    logger.info("Pipeline order changed to: %s", new_order)

    return web.json_response(
        {
            "success": True,
            "updated_list": new_order,
        }
    )


@handle_errors("updating pipeline config")
@parse_json_body
async def update_pipeline_config(request: web.Request) -> web.Response:
    """Update settings for a pipeline that supports configuration.

    PATCH /api/pipelines/{name}/config

    Request:
    {
      "config": {...}
    }
    """
    pipeline_name = request.match_info.get("name", "")
    available = _get_available_pipelines()
    pipeline_meta = available.get(pipeline_name)
    if not pipeline_meta:
        return web.json_response({"error": f"Unknown pipeline: {pipeline_name}"}, status=400)

    if not pipeline_meta.get("supports_config"):
        return web.json_response({"error": f"Pipeline does not support config: {pipeline_name}"}, status=400)

    data = request["json_body"]
    pipeline_config = data.get("config")
    if not isinstance(pipeline_config, dict):
        return web.json_response({"error": "config must be an object"}, status=400)

    if pipeline_name == "group_filter":
        normalized_config = normalize_group_filter_settings(pipeline_config)
    else:
        normalized_config = pipeline_config

    settings = _get_pipeline_settings()
    settings[pipeline_name] = normalized_config
    _save_pipeline_settings(settings)

    logger.info("Pipeline config updated for %s", pipeline_name)
    return web.json_response({"success": True, "config": normalized_config})


def _get_pipeline_stats() -> dict[str, Any]:
    """Get statistics about pipeline execution from the database.

    Currently returns basic counts. Can be enhanced to include
    success/failure rates, execution times, etc.
    """
    try:
        conn = sqlite3.connect(cfg.CONFIG_DB)
        try:
            cursor = conn.cursor()

            # Total processed messages
            cursor.execute("SELECT COUNT(*) FROM raw_messages WHERE status IN ('processed', 'failed', 'ignored')")
            total_processed = cursor.fetchone()[0] or 0

            # By pipeline
            cursor.execute(
                """
                SELECT pipeline_name, COUNT(*) as count
                FROM pipeline_runs
                GROUP BY pipeline_name
                """
            )
            by_pipeline = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "total_processed": total_processed,
                "by_pipeline": by_pipeline,
            }
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to get pipeline stats: %s", e)
        return {"total_processed": 0, "by_pipeline": {}}
