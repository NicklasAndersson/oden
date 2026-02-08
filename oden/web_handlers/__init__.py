"""
Web handlers for Oden GUI.

This package contains the HTTP request handlers for the web interface,
organized by functionality.
"""

from oden.web_handlers.config_handlers import (
    config_export_handler,
    config_file_get_handler,
    config_file_save_handler,
    config_handler,
    config_reset_handler,
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
from oden.web_handlers.response_handlers import (
    response_create_handler,
    response_delete_handler,
    response_get_handler,
    response_save_handler,
    responses_list_handler,
)
from oden.web_handlers.setup_handlers import (
    setup_cancel_link_handler,
    setup_handler,
    setup_install_obsidian_template_handler,
    setup_oden_home_handler,
    setup_reset_config_handler,
    setup_save_config_handler,
    setup_start_link_handler,
    setup_start_register_handler,
    setup_status_handler,
    setup_validate_path_handler,
    setup_verify_code_handler,
)
from oden.web_handlers.template_handlers import (
    template_export_handler,
    template_get_handler,
    template_preview_handler,
    template_reset_handler,
    template_save_handler,
    templates_export_all_handler,
    templates_list_handler,
)

__all__ = [
    # Config handlers
    "config_handler",
    "config_file_get_handler",
    "config_file_save_handler",
    "config_save_handler",
    "config_export_handler",
    "config_reset_handler",
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
    "setup_start_register_handler",
    "setup_verify_code_handler",
    "setup_install_obsidian_template_handler",
    "setup_oden_home_handler",
    "setup_validate_path_handler",
    "setup_reset_config_handler",
    # Response handlers
    "responses_list_handler",
    "response_get_handler",
    "response_save_handler",
    "response_create_handler",
    "response_delete_handler",
    # Template handlers
    "templates_list_handler",
    "template_get_handler",
    "template_save_handler",
    "template_preview_handler",
    "template_reset_handler",
    "template_export_handler",
    "templates_export_all_handler",
]
