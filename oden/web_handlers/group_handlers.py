"""
Group-related handlers for Oden web GUI.
"""

import json
import logging

from aiohttp import web

from oden import config as cfg
from oden.app_state import get_app_state
from oden.config import CONFIG_DB
from oden.config_db import get_config_value
from oden.groups_db import get_all_groups, upsert_groups_bulk
from oden.web_handlers._helpers import (
    handle_errors,
    parse_json_body,
    require_writer,
    update_config_and_reload,
)

logger = logging.getLogger(__name__)


async def groups_handler(request: web.Request) -> web.Response:
    """Return list of groups the account is a member of.

    Merges the in-memory cache (from listGroups RPC) with the database
    so groups discovered from incoming messages are always visible.
    """
    app_state = get_app_state()

    # Start with DB groups (keyed by id)
    db_groups = get_all_groups(CONFIG_DB)
    merged: dict[str, dict] = {}
    for g in db_groups:
        if g.get("isMember", True):
            merged[g["id"]] = {
                "id": g["id"],
                "name": g["name"],
                "memberCount": g.get("memberCount", 0),
            }

    # Overlay in-memory groups (fresher data from signal-cli)
    for group in app_state.groups:
        if group.get("isMember", True) and not group.get("invitedToGroup", False):
            gid = group.get("id")
            if gid:
                members_raw = group.get("members", [])
                members = []
                is_admin = False
                for m in members_raw:
                    if isinstance(m, dict):
                        num = m.get("number", "")
                        role = m.get("role", "DEFAULT")
                    elif isinstance(m, str):
                        num = m
                        role = "DEFAULT"
                    else:
                        continue
                    display = app_state.resolve_contact_name(num, None)
                    members.append({"number": num, "name": display, "role": role})
                    if num == cfg.SIGNAL_NUMBER and role == "ADMINISTRATOR":
                        is_admin = True
                merged[gid] = {
                    "id": gid,
                    "name": group.get("name", "Okänd grupp"),
                    "memberCount": len(members_raw),
                    "members": members,
                    "description": group.get("description", ""),
                    "permissionAddMember": group.get("permissionAddMember", "every-member"),
                    "permissionEditDetails": group.get("permissionEditDetails", "every-member"),
                    "permissionSendMessages": group.get("permissionSendMessages", "every-member"),
                    "groupInviteLink": group.get("groupInviteLink", ""),
                    "messageExpirationTime": group.get("messageExpirationTime", 0),
                    "isAdmin": is_admin,
                }

    groups = sorted(merged.values(), key=lambda g: g.get("name", ""))
    return web.json_response(
        {"groups": groups, "ignoredGroups": cfg.IGNORED_GROUPS, "whitelistGroups": cfg.WHITELIST_GROUPS}
    )


@handle_errors("toggle ignore group")
@parse_json_body
async def toggle_ignore_group_handler(request: web.Request) -> web.Response:
    """Toggle ignore status for a group."""
    data = request["json_body"]
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
    update_config_and_reload("ignored_groups", ignored_groups)

    logger.info(f"Group '{group_name}' {action} ignored_groups")
    return web.json_response(
        {
            "success": True,
            "message": f"Grupp '{group_name}' {action} ignorerade grupper",
            "ignoredGroups": ignored_groups,
        }
    )


@handle_errors("toggle whitelist group")
@parse_json_body
async def toggle_whitelist_group_handler(request: web.Request) -> web.Response:
    """Toggle whitelist status for a group."""
    data = request["json_body"]
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
    update_config_and_reload("whitelist_groups", whitelist_groups)

    logger.info(f"Group '{group_name}' {action} whitelist_groups")
    return web.json_response(
        {
            "success": True,
            "message": f"Grupp '{group_name}' {action} whitelist",
            "whitelistGroups": whitelist_groups,
        }
    )


@handle_errors("join group")
@parse_json_body
@require_writer
async def join_group_handler(request: web.Request) -> web.Response:
    """Handle request to join a Signal group via invite link."""
    data = request["json_body"]
    link = data.get("link", "").strip()

    if not link:
        return web.json_response({"success": False, "error": "Ingen länk angiven"}, status=400)

    if not link.startswith("https://signal.group/"):
        return web.json_response(
            {"success": False, "error": "Ogiltig länk. Måste börja med https://signal.group/"},
            status=400,
        )

    app_state = get_app_state()

    # Send joinGroup request via JSON-RPC
    request_id = app_state.get_next_request_id()
    json_request = {
        "jsonrpc": "2.0",
        "method": "joinGroup",
        "params": {"account": cfg.SIGNAL_NUMBER, "uri": link},
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


async def invitations_handler(request: web.Request) -> web.Response:
    """Return list of pending group invitations from cached groups."""
    app_state = get_app_state()
    invitations = app_state.get_pending_invitations()
    return web.json_response(invitations)


@handle_errors("accept invitation")
@parse_json_body
@require_writer
async def accept_invitation_handler(request: web.Request) -> web.Response:
    """Accept a group invitation."""
    data = request["json_body"]
    group_id = data.get("groupId", "").strip()

    if not group_id:
        return web.json_response({"success": False, "error": "Inget grupp-ID angivet"}, status=400)

    app_state = get_app_state()

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
        "params": {"account": cfg.SIGNAL_NUMBER, "uri": invite_link},
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


@handle_errors("decline invitation")
@parse_json_body
@require_writer
async def decline_invitation_handler(request: web.Request) -> web.Response:
    """Decline a group invitation."""
    data = request["json_body"]
    group_id = data.get("groupId", "").strip()

    if not group_id:
        return web.json_response({"success": False, "error": "Inget grupp-ID angivet"}, status=400)

    app_state = get_app_state()

    # Send quitGroup request via JSON-RPC to decline the invitation
    request_id = app_state.get_next_request_id()
    json_request = {
        "jsonrpc": "2.0",
        "method": "quitGroup",
        "params": {"account": cfg.SIGNAL_NUMBER, "groupId": group_id},
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


@handle_errors("update group")
@parse_json_body
async def update_group_handler(request: web.Request) -> web.Response:
    """Update group settings via signal-cli updateGroup RPC."""
    data = request["json_body"]
    group_id = data.get("groupId", "").strip()

    if not group_id:
        return web.json_response({"success": False, "error": "Inget grupp-ID angivet"}, status=400)

    params: dict = {"account": cfg.SIGNAL_NUMBER, "groupId": group_id}

    # Pass through scalar fields
    for field in (
        "name",
        "description",
        "link",
        "setPermissionAddMember",
        "setPermissionEditDetails",
        "setPermissionSendMessages",
    ):
        if field in data:
            params[field] = data[field]

    if "expiration" in data:
        try:
            params["expiration"] = int(data["expiration"])
        except (TypeError, ValueError):
            return web.json_response(
                {"success": False, "error": "Ogiltigt värde för expiration; måste vara ett heltal"},
                status=400,
            )

    # Pass through list fields
    for list_field in ("member", "removeMember", "admin", "removeAdmin", "ban", "unban"):
        if list_field in data and data[list_field]:
            params[list_field] = data[list_field]

    # Reject no-op updates (only account + groupId, no actual changes)
    if len(params) <= 2:
        return web.json_response(
            {"success": False, "error": "Inga uppdateringsbara fält angavs"},
            status=400,
        )

    # Check writer after validation so missing fields return 400, not 503
    app_state = get_app_state()
    if not app_state.writer:
        return web.json_response(
            {"success": False, "error": "Inte ansluten till signal-cli"},
            status=503,
        )

    result = await app_state.send_jsonrpc("updateGroup", params=params)

    if result is None:
        return web.json_response(
            {"success": False, "error": "Inget svar från signal-cli"},
            status=502,
        )

    # Refresh groups cache after update
    refresh = await app_state.send_jsonrpc(
        "listGroups",
        params={"account": cfg.SIGNAL_NUMBER},
        timeout=10.0,
    )
    if refresh and "result" in refresh:
        app_state.update_groups(refresh["result"])
        upsert_groups_bulk(cfg.CONFIG_DB, refresh["result"])

    logger.info("Group %s updated", group_id)
    return web.json_response({"success": True})


@handle_errors("refresh groups")
@require_writer
async def refresh_groups_handler(request: web.Request) -> web.Response:
    """Re-fetch groups from signal-cli and update the database."""
    app_state = get_app_state()

    response = await app_state.send_jsonrpc(
        "listGroups",
        params={"account": cfg.SIGNAL_NUMBER},
        timeout=10.0,
    )
    if response and "result" in response:
        groups = response["result"]
        app_state.update_groups(groups)
        count = upsert_groups_bulk(CONFIG_DB, groups)
        logger.info("Refreshed %d groups from signal-cli", count)
        return web.json_response({"success": True, "count": count})

    return web.json_response(
        {"success": False, "error": "Inget svar från signal-cli"},
        status=502,
    )
