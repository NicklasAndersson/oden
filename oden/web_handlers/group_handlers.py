"""
Group-related handlers for Oden web GUI.
"""

import json
import logging

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.config import CONFIG_DB, reload_config
from oden.config_db import get_config_value, set_config_value

logger = logging.getLogger(__name__)


async def groups_handler(request: web.Request) -> web.Response:
    """Return list of groups the account is a member of."""
    app_state = get_app_state()
    groups = []
    for group in app_state.groups:
        # Only include groups where user is actually a member
        if group.get("isMember", True) and not group.get("invitedToGroup", False):
            groups.append(
                {
                    "id": group.get("id"),
                    "name": group.get("name", "Okänd grupp"),
                    "memberCount": len(group.get("members", [])),
                }
            )
    return web.json_response(
        {"groups": groups, "ignoredGroups": cfg.IGNORED_GROUPS, "whitelistGroups": cfg.WHITELIST_GROUPS}
    )


async def toggle_ignore_group_handler(request: web.Request) -> web.Response:
    """Toggle ignore status for a group."""
    try:
        data = await request.json()
        group_name = data.get("groupName", "").strip()

        if not group_name:
            return web.json_response({"success": False, "error": "Inget gruppnamn angivet"}, status=400)

        # Read current ignored groups from config_db
        ignored_groups = get_config_value(CONFIG_DB, "ignored_groups") or []

        # Toggle the group
        if group_name in ignored_groups:
            ignored_groups.remove(group_name)
            action = "borttagen från"
        else:
            ignored_groups.append(group_name)
            action = "tillagd i"

        # Persist to config_db and reload
        set_config_value(CONFIG_DB, "ignored_groups", ignored_groups)
        reload_config()

        logger.info(f"Group '{group_name}' {action} ignored_groups")
        return web.json_response(
            {
                "success": True,
                "message": f"Grupp '{group_name}' {action} ignorerade grupper",
                "ignoredGroups": ignored_groups,
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error toggling ignore group: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def toggle_whitelist_group_handler(request: web.Request) -> web.Response:
    """Toggle whitelist status for a group."""
    try:
        data = await request.json()
        group_name = data.get("groupName", "").strip()

        if not group_name:
            return web.json_response({"success": False, "error": "Inget gruppnamn angivet"}, status=400)

        # Read current whitelist groups from config_db
        whitelist_groups = get_config_value(CONFIG_DB, "whitelist_groups") or []

        # Toggle the group
        if group_name in whitelist_groups:
            whitelist_groups.remove(group_name)
            action = "borttagen från"
        else:
            whitelist_groups.append(group_name)
            action = "tillagd i"

        # Persist to config_db and reload
        set_config_value(CONFIG_DB, "whitelist_groups", whitelist_groups)
        reload_config()

        logger.info(f"Group '{group_name}' {action} whitelist_groups")
        return web.json_response(
            {
                "success": True,
                "message": f"Grupp '{group_name}' {action} whitelist",
                "whitelistGroups": whitelist_groups,
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error toggling whitelist group: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def join_group_handler(request: web.Request) -> web.Response:
    """Handle request to join a Signal group via invite link."""
    try:
        data = await request.json()
        link = data.get("link", "").strip()

        if not link:
            return web.json_response({"success": False, "error": "Ingen länk angiven"}, status=400)

        if not link.startswith("https://signal.group/"):
            return web.json_response(
                {"success": False, "error": "Ogiltig länk. Måste börja med https://signal.group/"},
                status=400,
            )

        app_state = get_app_state()
        if not app_state.writer:
            return web.json_response(
                {"success": False, "error": "Inte ansluten till signal-cli"},
                status=503,
            )

        # Send joinGroup request via JSON-RPC
        request_id = app_state.get_next_request_id()
        json_request = {
            "jsonrpc": "2.0",
            "method": "joinGroup",
            "params": {"uri": link},
            "id": request_id,
        }

        logger.info(f"Joining group via link: {link[:50]}...")
        app_state.writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
        await app_state.writer.drain()

        # We don't wait for response since it comes async through the main listener
        # Just return success that the request was sent
        return web.json_response(
            {
                "success": True,
                "message": "Förfrågan skickad. Kontrollera loggen för resultat.",
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error joining group: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def invitations_handler(request: web.Request) -> web.Response:
    """Return list of pending group invitations from cached groups."""
    app_state = get_app_state()
    invitations = app_state.get_pending_invitations()
    return web.json_response(invitations)


async def accept_invitation_handler(request: web.Request) -> web.Response:
    """Accept a group invitation."""
    try:
        data = await request.json()
        group_id = data.get("groupId", "").strip()

        if not group_id:
            return web.json_response({"success": False, "error": "Inget grupp-ID angivet"}, status=400)

        app_state = get_app_state()
        if not app_state.writer:
            return web.json_response(
                {"success": False, "error": "Inte ansluten till signal-cli"},
                status=503,
            )

        # Find the group to get the invite link
        group = next((g for g in app_state.groups if g.get("id") == group_id), None)
        if not group:
            return web.json_response({"success": False, "error": "Gruppen hittades inte"}, status=404)

        invite_link = group.get("groupInviteLink")
        if not invite_link:
            return web.json_response({"success": False, "error": "Ingen inbjudningslänk hittades"}, status=400)

        # Send acceptInvitation request via JSON-RPC
        request_id = app_state.get_next_request_id()
        json_request = {
            "jsonrpc": "2.0",
            "method": "joinGroup",
            "params": {"uri": invite_link},
            "id": request_id,
        }

        logger.info(f"Accepting invitation for group: {group.get('name', group_id)}")
        app_state.writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
        await app_state.writer.drain()

        return web.json_response(
            {
                "success": True,
                "message": "Inbjudan accepterad. Kontrollera loggen för resultat.",
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error accepting invitation: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def decline_invitation_handler(request: web.Request) -> web.Response:
    """Decline a group invitation."""
    try:
        data = await request.json()
        group_id = data.get("groupId", "").strip()

        if not group_id:
            return web.json_response({"success": False, "error": "Inget grupp-ID angivet"}, status=400)

        app_state = get_app_state()
        if not app_state.writer:
            return web.json_response(
                {"success": False, "error": "Inte ansluten till signal-cli"},
                status=503,
            )

        # Send quitGroup request via JSON-RPC to decline the invitation
        request_id = app_state.get_next_request_id()
        json_request = {
            "jsonrpc": "2.0",
            "method": "quitGroup",
            "params": {"groupId": group_id},
            "id": request_id,
        }

        # Find the group name for logging
        group = next((g for g in app_state.groups if g.get("id") == group_id), None)
        group_name = group.get("name", group_id) if group else group_id

        logger.info(f"Declining invitation for group: {group_name}")
        app_state.writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
        await app_state.writer.drain()

        return web.json_response(
            {
                "success": True,
                "message": "Inbjudan avböjd.",
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error declining invitation: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
