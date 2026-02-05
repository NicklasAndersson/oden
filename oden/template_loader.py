"""
Template loader for Jinja2 report templates.

This module provides functions for loading and rendering Jinja2 templates
for Signal message reports. Templates are loaded from the bundled resources
directory (for PyInstaller builds) or from the project templates/ directory.
"""

import logging
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template

from oden.bundle_utils import get_bundle_path

logger = logging.getLogger(__name__)

# Template directory name
TEMPLATES_DIR = "templates"

# Template file names
REPORT_TEMPLATE = "report.md.j2"
APPEND_TEMPLATE = "append.md.j2"


def get_templates_path() -> Path:
    """Get the path to the templates directory.

    Returns:
        Path to the templates directory (bundled or source).
    """
    return get_bundle_path() / TEMPLATES_DIR


@lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """Get or create a cached Jinja2 environment.

    Returns:
        Configured Jinja2 Environment instance.
    """
    templates_path = get_templates_path()
    logger.debug(f"Loading templates from: {templates_path}")

    env = Environment(
        loader=FileSystemLoader(str(templates_path)),
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    return env


def get_template(template_name: str) -> Template:
    """Load a Jinja2 template by name.

    Args:
        template_name: Name of the template file (e.g., 'report.md.j2').

    Returns:
        Compiled Jinja2 Template object.

    Raises:
        jinja2.TemplateNotFound: If the template file doesn't exist.
    """
    env = _get_jinja_env()
    return env.get_template(template_name)


def render_report(
    fileid: str,
    group_title: str,
    group_id: str,
    tnr: str,
    timestamp_iso: str,
    sender_display: str,
    sender_name: str | None = None,
    sender_number: str | None = None,
    lat: str | None = None,
    lon: str | None = None,
    quote_formatted: str | None = None,
    message: str | None = None,
    attachments: list[str] | None = None,
) -> str:
    """Render a new report using the report template.

    Args:
        fileid: Unique file identifier (DDHHMM-phone-name).
        group_title: Signal group name.
        group_id: Signal group identifier.
        tnr: Timestamp in DDHHMM format.
        timestamp_iso: Full ISO 8601 timestamp.
        sender_display: Formatted sender display string.
        sender_name: Sender's display name (optional).
        sender_number: Sender's phone number (optional).
        lat: Latitude from Google Maps URL (optional).
        lon: Longitude from Google Maps URL (optional).
        quote_formatted: Pre-formatted quote block (optional).
        message: Message text with regex links applied (optional).
        attachments: List of Obsidian embed links (optional).

    Returns:
        Rendered markdown content string.
    """
    template = get_template(REPORT_TEMPLATE)
    return template.render(
        fileid=fileid,
        group_title=group_title,
        group_id=group_id,
        tnr=tnr,
        timestamp_iso=timestamp_iso,
        sender_display=sender_display,
        sender_name=sender_name,
        sender_number=sender_number,
        lat=lat,
        lon=lon,
        quote_formatted=quote_formatted,
        message=message,
        attachments=attachments or [],
    )


def render_append(
    tnr: str,
    timestamp_iso: str,
    sender_display: str,
    message: str | None = None,
    attachments: list[str] | None = None,
) -> str:
    """Render content to append to an existing report.

    Args:
        tnr: Timestamp in DDHHMM format.
        timestamp_iso: Full ISO 8601 timestamp.
        sender_display: Formatted sender display string.
        message: Message text with regex links applied (optional).
        attachments: List of Obsidian embed links (optional).

    Returns:
        Rendered markdown content string (without leading separator).
    """
    template = get_template(APPEND_TEMPLATE)
    return template.render(
        tnr=tnr,
        timestamp_iso=timestamp_iso,
        sender_display=sender_display,
        message=message,
        attachments=attachments or [],
    )
