"""Helpers for pipeline-specific settings."""

from __future__ import annotations

from typing import Any

DEFAULT_GROUP_FILTER_SETTINGS: dict[str, Any] = {
    "mode": "blacklist",
    "groups": [],
}


def normalize_group_filter_settings(value: Any) -> dict[str, Any]:
    """Normalize group filter settings to a safe structure."""
    settings = dict(DEFAULT_GROUP_FILTER_SETTINGS)
    if not isinstance(value, dict):
        return settings

    mode = value.get("mode", "blacklist")
    if isinstance(mode, str) and mode in {"blacklist", "whitelist"}:
        settings["mode"] = mode

    groups_raw = value.get("groups", [])
    if isinstance(groups_raw, list):
        groups: list[str] = []
        for item in groups_raw:
            if isinstance(item, str):
                group = item.strip()
                if group:
                    groups.append(group)
        settings["groups"] = list(dict.fromkeys(groups))

    return settings


def normalize_pipeline_settings(value: Any) -> dict[str, Any]:
    """Normalize the full pipeline settings dictionary."""
    if not isinstance(value, dict):
        value = {}

    return {
        "group_filter": normalize_group_filter_settings(value.get("group_filter")),
    }


def get_group_filter_settings(pipeline_settings: Any) -> dict[str, Any]:
    """Extract normalized group filter settings from pipeline settings."""
    normalized = normalize_pipeline_settings(pipeline_settings)
    return normalize_group_filter_settings(normalized.get("group_filter"))


def is_group_filtered(group_title: str | None, pipeline_settings: Any) -> bool:
    """Return True when message from the group should be filtered out."""
    settings = get_group_filter_settings(pipeline_settings)
    groups = settings.get("groups", [])

    if not group_title or not groups:
        return False

    mode = settings.get("mode", "blacklist")
    if mode == "whitelist":
        return group_title not in groups

    return group_title in groups
