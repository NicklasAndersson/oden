"""
Template loader for Jinja2 report templates.

This module provides functions for loading and rendering Jinja2 templates
for Signal message reports. Templates are loaded from the config database,
with fallback to bundled resources directory (for PyInstaller builds)
or from the project templates/ directory.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from oden.bundle_utils import get_bundle_path

logger = logging.getLogger(__name__)

# Template directory name
TEMPLATES_DIR = "templates"

# Template file names
REPORT_TEMPLATE = "report.md.j2"
APPEND_TEMPLATE = "append.md.j2"

# Valid template names for validation
VALID_TEMPLATES = {REPORT_TEMPLATE, APPEND_TEMPLATE}


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
    template = get_template_with_db_fallback(REPORT_TEMPLATE)
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
    template = get_template_with_db_fallback(APPEND_TEMPLATE)
    return template.render(
        tnr=tnr,
        timestamp_iso=timestamp_iso,
        sender_display=sender_display,
        message=message,
        attachments=attachments or [],
    )


def load_template_from_file(template_name: str) -> str:
    """Load template content directly from file (ignoring database).

    Args:
        template_name: Name of the template file (e.g., 'report.md.j2').

    Returns:
        Raw template content string.

    Raises:
        FileNotFoundError: If the template file doesn't exist.
        ValueError: If the template name is not valid.
    """
    if template_name not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template name: {template_name}")

    templates_path = get_templates_path()
    template_file = templates_path / template_name

    if not template_file.exists():
        raise FileNotFoundError(f"Template file not found: {template_file}")

    return template_file.read_text(encoding="utf-8")


def get_template_content(template_name: str) -> str:
    """Get template content from database, falling back to file.

    Args:
        template_name: Name of the template (e.g., 'report.md.j2').

    Returns:
        Template content string.
    """
    if template_name not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template name: {template_name}")

    # Import here to avoid circular imports
    from oden.config import CONFIG_DB
    from oden.config_db import get_config_value

    # Map template name to config key
    config_key = "report_template" if template_name == REPORT_TEMPLATE else "append_template"

    # Try to get from database
    content = get_config_value(CONFIG_DB, config_key)

    # If database has content, use it
    if content:
        return content

    # Otherwise load from file
    return load_template_from_file(template_name)


def save_template_content(template_name: str, content: str) -> bool:
    """Save template content to database.

    Args:
        template_name: Name of the template (e.g., 'report.md.j2').
        content: Template content string.

    Returns:
        True if saved successfully, False otherwise.
    """
    if template_name not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template name: {template_name}")

    # Import here to avoid circular imports
    from oden.config import CONFIG_DB
    from oden.config_db import set_config_value

    # Map template name to config key
    config_key = "report_template" if template_name == REPORT_TEMPLATE else "append_template"

    # Clear the template cache since content changed
    clear_template_cache()

    return set_config_value(CONFIG_DB, config_key, content)


def clear_template_cache() -> None:
    """Clear the cached Jinja2 environment to reload templates."""
    _get_jinja_env.cache_clear()
    # Clear sandboxed environment cache if it exists
    if hasattr(_get_sandboxed_env, "cache_clear"):
        _get_sandboxed_env.cache_clear()
    # Clear _get_template_from_db cache if it exists (it may not be called yet)
    if hasattr(_get_template_from_db, "cache_clear"):
        _get_template_from_db.cache_clear()
    logger.debug("Template cache cleared")


@lru_cache(maxsize=1)
def _get_sandboxed_env() -> SandboxedEnvironment:
    """Get a cached sandboxed Jinja2 environment for user-provided templates."""
    # We use a separate environment for templates constructed from strings
    # (for example, user-edited templates) to avoid server-side template injection.
    return SandboxedEnvironment()


@lru_cache(maxsize=2)
def _get_template_from_db(template_name: str) -> Template:
    """Get a compiled template from database content (cached).

    Args:
        template_name: Name of the template.

    Returns:
        Compiled Jinja2 Template object.
    """
    content = get_template_content(template_name)
    env = _get_sandboxed_env()
    return env.from_string(content)


def validate_template(content: str) -> tuple[bool, str | None]:
    """Validate Jinja2 template syntax.

    Args:
        content: Template content string to validate.

    Returns:
        (True, None) if valid, (False, error_message) if invalid.
    """
    try:
        env = _get_sandboxed_env()
        env.parse(content)
        return True, None
    except TemplateSyntaxError as e:
        return False, f"Rad {e.lineno}: {e.message}"


def render_template_from_string(content: str, context: dict[str, Any]) -> str:
    """Render a template from string content with given context.

    Args:
        content: Jinja2 template content string.
        context: Dictionary of template variables.

    Returns:
        Rendered template string.

    Raises:
        jinja2.TemplateSyntaxError: If template syntax is invalid.
    """
    env = _get_sandboxed_env()
    template = env.from_string(content)
    return template.render(**context)


def get_template_with_db_fallback(template_name: str) -> Template:
    """Get template, preferring database content over file.

    This is the main entry point for getting templates during message processing.
    It checks the database first, then falls back to files.

    Args:
        template_name: Name of the template file.

    Returns:
        Compiled Jinja2 Template object.
    """
    return _get_template_from_db(template_name)
