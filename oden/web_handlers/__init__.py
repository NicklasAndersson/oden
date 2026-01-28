"""
Web handlers for Oden GUI.

This package contains the HTTP request handlers for the web interface,
organized by functionality.
"""

from oden.web_handlers.config_handlers import (
    config_file_get_handler,
    config_file_save_handler,
    config_handler,
    config_save_handler,
)
from oden.web_handlers.group_handlers import (
    accept_invitation_handler,
    decline_invitation_handler,
    groups_handler,
    invitations_handler,
    join_group_handler,
    toggle_ignore_group_handler,
    toggle_whitelist_group_handler,
)
from oden.web_handlers.setup_handlers import (
    setup_cancel_link_handler,
    setup_handler,
    setup_save_config_handler,
    setup_start_link_handler,
    setup_status_handler,
)

__all__ = [
    # Config handlers
    "config_handler",
    "config_file_get_handler",
    "config_file_save_handler",
    "config_save_handler",
    # Group handlers
    "groups_handler",
    "toggle_ignore_group_handler",
    "toggle_whitelist_group_handler",
    "join_group_handler",
    "invitations_handler",
    "accept_invitation_handler",
    "decline_invitation_handler",
    # Setup handlers
    "setup_handler",
    "setup_status_handler",
    "setup_start_link_handler",
    "setup_cancel_link_handler",
    "setup_save_config_handler",
]
