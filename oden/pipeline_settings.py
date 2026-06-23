"""Helpers for pipeline-specific settings."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_GROUP_FILTER_SETTINGS: dict[str, Any] = {
    "mode": "blacklist",
    "groups": [],
}

DEFAULT_GENERIC_TEMPLATE_SETTINGS: dict[str, Any] = {
    "templates": {
        "report_md": "",
        "append_md": "",
    },
    "regex_patterns": {},
    "auto_reaction_enabled": False,
    "auto_reaction_emoji": "✅",
    "auto_read_receipt_enabled": False,
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
        "generic_template": normalize_generic_template_settings(value.get("generic_template")),
    }


def normalize_generic_template_settings(value: Any) -> dict[str, Any]:
    """Normalize generic_template pipeline settings to a safe structure."""
    settings = dict(DEFAULT_GENERIC_TEMPLATE_SETTINGS)
    if not isinstance(value, dict):
        return settings

    # Normalize templates
    templates_raw = value.get("templates", {})
    if isinstance(templates_raw, dict):
        templates = dict(DEFAULT_GENERIC_TEMPLATE_SETTINGS["templates"])
        if "report_md" in templates_raw and isinstance(templates_raw["report_md"], str):
            templates["report_md"] = templates_raw["report_md"]
        if "append_md" in templates_raw and isinstance(templates_raw["append_md"], str):
            templates["append_md"] = templates_raw["append_md"]
        settings["templates"] = templates

    # Normalize regex_patterns
    patterns_raw = value.get("regex_patterns", {})
    if isinstance(patterns_raw, dict):
        patterns = {}
        for name, pattern in patterns_raw.items():
            if isinstance(name, str) and isinstance(pattern, str):
                name_str = name.strip()
                pattern_str = pattern.strip()
                if name_str and pattern_str:
                    # Validate regex
                    try:
                        re.compile(pattern_str)
                        patterns[name_str] = pattern_str
                    except re.error:
                        pass  # Skip invalid patterns
        settings["regex_patterns"] = patterns

    # Normalize auto_reaction settings
    if "auto_reaction_enabled" in value and isinstance(value["auto_reaction_enabled"], bool):
        settings["auto_reaction_enabled"] = value["auto_reaction_enabled"]
    if "auto_reaction_emoji" in value and isinstance(value["auto_reaction_emoji"], str):
        emoji_str = value["auto_reaction_emoji"].strip()
        if emoji_str:
            settings["auto_reaction_emoji"] = emoji_str

    # Normalize auto_read_receipt
    if "auto_read_receipt_enabled" in value and isinstance(value["auto_read_receipt_enabled"], bool):
        settings["auto_read_receipt_enabled"] = value["auto_read_receipt_enabled"]

    return settings


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
