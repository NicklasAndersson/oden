"""
Web server for Oden GUI.

Provides a web interface for viewing config, logs, and sending commands.
"""

import asyncio
import json
import logging

from aiohttp import web

from oden import __version__
from oden.app_state import get_app_state
from oden.config import (
    APPEND_WINDOW_MINUTES,
    DISPLAY_NAME,
    IGNORED_GROUPS,
    LOG_LEVEL,
    PLUS_PLUS_ENABLED,
    REGEX_PATTERNS,
    SIGNAL_CLI_HOST,
    SIGNAL_CLI_LOG_FILE,
    SIGNAL_CLI_PATH,
    SIGNAL_CLI_PORT,
    SIGNAL_NUMBER,
    STARTUP_MESSAGE,
    TIMEZONE,
    UNMANAGED_SIGNAL_CLI,
    VAULT_PATH,
    WEB_ACCESS_LOG,
    WEB_ENABLED,
    WEB_PORT,
)
from oden.log_buffer import get_log_buffer

logger = logging.getLogger(__name__)

# HTML template for the web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Oden - Web GUI</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #333;
        }
        h1 {
            color: #4fc3f7;
            font-size: 2em;
        }
        .version {
            color: #888;
            font-size: 0.9em;
        }
        .status {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #4caf50;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }
        .card {
            background: #16213e;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #333;
        }
        .card h2 {
            color: #4fc3f7;
            margin-bottom: 15px;
            font-size: 1.2em;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .card.full-width {
            grid-column: 1 / -1;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            text-align: left;
            padding: 8px 12px;
            border-bottom: 1px solid #333;
        }
        th {
            color: #888;
            font-weight: normal;
            width: 40%;
        }
        td {
            color: #fff;
            word-break: break-all;
        }
        .logs {
            max-height: 400px;
            overflow-y: auto;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.85em;
            background: #0d1421;
            border-radius: 4px;
            padding: 10px;
        }
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid #1a1a2e;
            display: flex;
            gap: 10px;
        }
        .log-entry:last-child {
            border-bottom: none;
        }
        .log-time {
            color: #666;
            white-space: nowrap;
        }
        .log-level {
            min-width: 60px;
            font-weight: bold;
        }
        .log-level.INFO { color: #4fc3f7; }
        .log-level.WARNING { color: #ffb74d; }
        .log-level.ERROR { color: #ef5350; }
        .log-level.DEBUG { color: #888; }
        .log-name {
            color: #888;
            min-width: 120px;
        }
        .log-message {
            color: #ddd;
            flex: 1;
        }
        .refresh-info {
            text-align: center;
            color: #666;
            font-size: 0.85em;
            margin-top: 10px;
        }
        .empty-state {
            text-align: center;
            color: #666;
            padding: 40px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            color: #888;
        }
        .form-group input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #333;
            border-radius: 4px;
            background: #0d1421;
            color: #fff;
            font-size: 0.95em;
        }
        .form-group input:focus {
            outline: none;
            border-color: #4fc3f7;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.95em;
            transition: background 0.2s;
        }
        .btn-primary {
            background: #4fc3f7;
            color: #1a1a2e;
        }
        .btn-primary:hover {
            background: #81d4fa;
        }
        .btn-primary:disabled {
            background: #555;
            cursor: not-allowed;
        }
        .message {
            padding: 10px 15px;
            border-radius: 4px;
            margin-top: 15px;
            display: none;
        }
        .message.success {
            background: rgba(76, 175, 80, 0.2);
            border: 1px solid #4caf50;
            color: #4caf50;
            display: block;
        }
        .message.error {
            background: rgba(239, 83, 80, 0.2);
            border: 1px solid #ef5350;
            color: #ef5350;
            display: block;
        }
        .invitation-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .invitation-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 15px;
            background: #0d1421;
            border-radius: 4px;
            border: 1px solid #333;
        }
        .invitation-info {
            flex: 1;
        }
        .invitation-name {
            font-weight: 500;
            color: #fff;
        }
        .invitation-meta {
            font-size: 0.85em;
            color: #888;
            margin-top: 4px;
        }
        .invitation-actions {
            display: flex;
            gap: 8px;
        }
        .btn-sm {
            padding: 6px 12px;
            font-size: 0.85em;
        }
        .btn-success {
            background: #4caf50;
            color: #fff;
        }
        .btn-success:hover {
            background: #66bb6a;
        }
        .btn-danger {
            background: #ef5350;
            color: #fff;
        }
        .btn-danger:hover {
            background: #e57373;
        }
        .btn-secondary {
            background: #555;
            color: #fff;
        }
        .btn-secondary:hover {
            background: #666;
        }
        .group-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .group-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 15px;
            background: #0d1421;
            border-radius: 4px;
            border: 1px solid #333;
        }
        .group-item.ignored {
            opacity: 0.6;
            background: #1a1520;
        }
        .group-info {
            flex: 1;
        }
        .group-name {
            font-weight: 500;
            color: #fff;
        }
        .group-meta {
            font-size: 0.85em;
            color: #888;
            margin-top: 2px;
        }
        .toggle-ignore {
            padding: 4px 10px;
            font-size: 0.8em;
            border-radius: 3px;
            cursor: pointer;
            border: 1px solid #555;
            background: transparent;
            color: #888;
            transition: all 0.2s;
        }
        .toggle-ignore:hover {
            border-color: #ef5350;
            color: #ef5350;
        }
        .toggle-ignore.ignored {
            border-color: #4caf50;
            color: #4caf50;
        }
        .toggle-ignore.ignored:hover {
            background: rgba(76, 175, 80, 0.1);
        }
        .warning-banner {
            background: rgba(255, 183, 77, 0.2);
            border: 1px solid #ffb74d;
            color: #ffb74d;
            padding: 12px 15px;
            border-radius: 4px;
            margin-bottom: 15px;
            display: none;
            align-items: center;
            gap: 10px;
        }
        .warning-banner.show {
            display: flex;
        }
        .warning-banner .icon {
            font-size: 1.2em;
        }
        .config-editor {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .config-editor textarea {
            width: 100%;
            min-height: 300px;
            padding: 12px;
            border: 1px solid #333;
            border-radius: 4px;
            background: #0d1421;
            color: #fff;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
            resize: vertical;
        }
        .config-editor textarea:focus {
            outline: none;
            border-color: #4fc3f7;
        }
        .config-actions {
            display: flex;
            gap: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>🛡️ Oden</h1>
                <span class="version">v{{version}}</span>
            </div>
            <div class="status">
                <div class="status-dot"></div>
                <span>Lyssnar</span>
            </div>
        </header>

        <div class="grid">
            <div class="card">
                <h2>📱 Signal</h2>
                <table>
                    <tr><th>Nummer</th><td id="signal-number">-</td></tr>
                    <tr><th>Visningsnamn</th><td id="display-name">-</td></tr>
                    <tr><th>signal-cli host</th><td id="signal-host">-</td></tr>
                    <tr><th>signal-cli port</th><td id="signal-port">-</td></tr>
                    <tr><th>Ohanterad</th><td id="unmanaged">-</td></tr>
                </table>
            </div>

            <div class="card">
                <h2>📁 Vault</h2>
                <table>
                    <tr><th>Sökväg</th><td id="vault-path">-</td></tr>
                    <tr><th>Tidszon</th><td id="timezone">-</td></tr>
                    <tr><th>Append-fönster</th><td id="append-window">-</td></tr>
                    <tr><th>Startup-meddelande</th><td id="startup-message">-</td></tr>
                    <tr><th>Ignorerade grupper</th><td id="ignored-groups">-</td></tr>
                </table>
            </div>

            <div class="card full-width">
                <h2>� Grupper</h2>
                <div id="groups-container" class="group-list">
                    <div class="empty-state">Laddar grupper...</div>
                </div>
                <div class="refresh-info">Klicka på "Ignorera" för att dölja gruppen. Kräver omstart.</div>
            </div>

            <div class="card full-width">
                <h2>�🔗 Gå med i grupp</h2>
                <form id="join-group-form">
                    <div class="form-group">
                        <label for="group-link">Grupplänk</label>
                        <input type="text" id="group-link" name="link"
                               placeholder="https://signal.group/#..." required>
                    </div>
                    <button type="submit" class="btn btn-primary" id="join-btn">Gå med i grupp</button>
                </form>
                <div id="join-message" class="message"></div>
            </div>

            <div class="card full-width">
                <h2>💾 Gruppinbjudningar</h2>
                <div id="invitations-container" class="invitation-list">
                    <div class="empty-state">Laddar inbjudningar...</div>
                </div>
                <div class="refresh-info">Uppdateras automatiskt var 10:e sekund</div>
            </div>

            <div class="card full-width">
                <h2>⚙️ Redigera config.ini</h2>
                <div id="config-warning" class="warning-banner">
                    <span class="icon">⚠️</span>
                    <span>Konfigurationen har ändrats. Starta om Oden för att ändringarna ska börja gälla.</span>
                </div>
                <div class="config-editor">
                    <textarea id="config-content" placeholder="Laddar config.ini..."></textarea>
                    <div class="config-actions">
                        <button class="btn btn-primary" id="save-config-btn" onclick="saveConfig()">Spara config</button>
                        <button class="btn btn-secondary" onclick="loadConfig()">Återställ</button>
                    </div>
                </div>
                <div id="config-message" class="message"></div>
            </div>

            <div class="card full-width">
                <h2>�📜 Logg</h2>
                <div class="logs" id="log-container">
                    <div class="empty-state">Laddar loggar...</div>
                </div>
                <div class="refresh-info">Uppdateras automatiskt var 3:e sekund</div>
            </div>
        </div>
    </div>

    <script>
        const version = '{{version}}';

        async function fetchConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();

                document.getElementById('signal-number').textContent = config.signal_number || '-';
                document.getElementById('display-name').textContent = config.display_name || '(ej satt)';
                document.getElementById('signal-host').textContent = config.signal_cli_host || '-';
                document.getElementById('signal-port').textContent = config.signal_cli_port || '-';
                document.getElementById('unmanaged').textContent = config.unmanaged_signal_cli ? 'Ja' : 'Nej';

                document.getElementById('vault-path').textContent = config.vault_path || '-';
                document.getElementById('timezone').textContent = config.timezone || '-';
                document.getElementById('append-window').textContent = (config.append_window_minutes || 30) + ' minuter';
                document.getElementById('startup-message').textContent = config.startup_message || '-';
                document.getElementById('ignored-groups').textContent =
                    config.ignored_groups && config.ignored_groups.length > 0
                        ? config.ignored_groups.join(', ')
                        : '(inga)';
            } catch (error) {
                console.error('Error fetching config:', error);
            }
        }

        async function fetchLogs() {
            try {
                const response = await fetch('/api/logs');
                const logs = await response.json();
                const container = document.getElementById('log-container');

                if (logs.length === 0) {
                    container.innerHTML = '<div class="empty-state">Inga loggar ännu</div>';
                    return;
                }

                container.innerHTML = logs.map(log => `
                    <div class="log-entry">
                        <span class="log-time">${log.timestamp.split(' ')[1]}</span>
                        <span class="log-level ${log.level}">${log.level}</span>
                        <span class="log-name">${log.name.split('.').pop()}</span>
                        <span class="log-message">${escapeHtml(log.message)}</span>
                    </div>
                `).join('');

                // Auto-scroll to bottom
                container.scrollTop = container.scrollHeight;
            } catch (error) {
                console.error('Error fetching logs:', error);
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Initial fetch
        fetchConfig();
        fetchLogs();

        // Polling - refresh logs every 3 seconds
        setInterval(fetchLogs, 3000);

        // Join group form handling
        document.getElementById('join-group-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const linkInput = document.getElementById('group-link');
            const submitBtn = document.getElementById('join-btn');
            const messageDiv = document.getElementById('join-message');
            const link = linkInput.value.trim();

            if (!link) return;

            submitBtn.disabled = true;
            submitBtn.textContent = 'Går med...';
            messageDiv.className = 'message';
            messageDiv.textContent = '';

            try {
                const response = await fetch('/api/join-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ link })
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    messageDiv.className = 'message success';
                    messageDiv.textContent = result.message || 'Gick med i gruppen!';
                    linkInput.value = '';
                } else {
                    messageDiv.className = 'message error';
                    messageDiv.textContent = result.error || 'Kunde inte gå med i gruppen';
                }
            } catch (error) {
                messageDiv.className = 'message error';
                messageDiv.textContent = 'Nätverksfel: ' + error.message;
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Gå med i grupp';
            }
        });

        // Fetch and display group invitations
        async function fetchInvitations() {
            try {
                const response = await fetch('/api/invitations');
                const invitations = await response.json();
                const container = document.getElementById('invitations-container');

                if (!invitations || invitations.length === 0) {
                    container.innerHTML = '<div class="empty-state">Inga väntande inbjudningar</div>';
                    return;
                }

                container.innerHTML = invitations.map(inv => `
                    <div class="invitation-item" data-group-id="${escapeHtml(inv.id)}">
                        <div class="invitation-info">
                            <div class="invitation-name">${escapeHtml(inv.name || 'Okänd grupp')}</div>
                            <div class="invitation-meta">${inv.memberCount || '?'} medlemmar</div>
                        </div>
                        <div class="invitation-actions">
                            <button class="btn btn-sm btn-success" onclick="handleInvitation('${escapeHtml(inv.id)}', 'accept')">Acceptera</button>
                            <button class="btn btn-sm btn-danger" onclick="handleInvitation('${escapeHtml(inv.id)}', 'decline')">Avböj</button>
                        </div>
                    </div>
                `).join('');
            } catch (error) {
                console.error('Error fetching invitations:', error);
            }
        }

        async function handleInvitation(groupId, action) {
            const item = document.querySelector(`[data-group-id="${groupId}"]`);
            const buttons = item.querySelectorAll('button');
            buttons.forEach(btn => btn.disabled = true);

            try {
                const response = await fetch(`/api/invitations/${action}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ groupId })
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    item.style.opacity = '0.5';
                    item.innerHTML = `<div class="invitation-info"><div class="invitation-name">${result.message}</div></div>`;
                    setTimeout(() => fetchInvitations(), 2000);
                } else {
                    alert(result.error || 'Något gick fel');
                    buttons.forEach(btn => btn.disabled = false);
                }
            } catch (error) {
                alert('Nätverksfel: ' + error.message);
                buttons.forEach(btn => btn.disabled = false);
            }
        }

        // Initial fetch
        fetchInvitations();

        // Polling - refresh invitations every 10 seconds
        setInterval(fetchInvitations, 10000);

        // Fetch and display groups
        let currentIgnoredGroups = [];

        async function fetchGroups() {
            try {
                const response = await fetch('/api/groups');
                const data = await response.json();
                const container = document.getElementById('groups-container');
                currentIgnoredGroups = data.ignoredGroups || [];

                if (!data.groups || data.groups.length === 0) {
                    container.innerHTML = '<div class="empty-state">Inga grupper hittades</div>';
                    return;
                }

                container.innerHTML = data.groups.map(group => {
                    const isIgnored = currentIgnoredGroups.includes(group.name);
                    return `
                        <div class="group-item ${isIgnored ? 'ignored' : ''}" data-group-name="${escapeHtml(group.name)}">
                            <div class="group-info">
                                <div class="group-name">${escapeHtml(group.name)}</div>
                                <div class="group-meta">${group.memberCount} medlemmar</div>
                            </div>
                            <button class="toggle-ignore ${isIgnored ? 'ignored' : ''}"
                                    onclick="toggleIgnoreGroup('${escapeHtml(group.name)}')"
                                    title="${isIgnored ? 'Sluta ignorera' : 'Ignorera grupp'}">
                                ${isIgnored ? '✓ Ignorerad' : 'Ignorera'}
                            </button>
                        </div>
                    `;
                }).join('');
            } catch (error) {
                console.error('Error fetching groups:', error);
            }
        }

        async function toggleIgnoreGroup(groupName) {
            try {
                const response = await fetch('/api/toggle-ignore-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ groupName })
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    // Show restart warning
                    document.getElementById('config-warning').classList.add('show');
                    // Refresh groups list
                    await fetchGroups();
                    // Refresh config editor
                    await loadConfig();
                } else {
                    alert(result.error || 'Något gick fel');
                }
            } catch (error) {
                alert('Nätverksfel: ' + error.message);
            }
        }

        // Config editor functions
        async function loadConfig() {
            try {
                const response = await fetch('/api/config-file');
                const data = await response.json();
                document.getElementById('config-content').value = data.content || '';
            } catch (error) {
                console.error('Error loading config:', error);
                document.getElementById('config-content').value = '# Kunde inte ladda config.ini';
            }
        }

        async function saveConfig() {
            const content = document.getElementById('config-content').value;
            const messageDiv = document.getElementById('config-message');
            const saveBtn = document.getElementById('save-config-btn');

            saveBtn.disabled = true;
            saveBtn.textContent = 'Sparar...';

            try {
                const response = await fetch('/api/config-file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    messageDiv.className = 'message success';
                    messageDiv.textContent = 'Config sparad! Starta om Oden för att ändringarna ska börja gälla.';
                    document.getElementById('config-warning').classList.add('show');
                    // Refresh groups in case ignored_groups changed
                    await fetchGroups();
                } else {
                    messageDiv.className = 'message error';
                    messageDiv.textContent = result.error || 'Kunde inte spara config';
                }
            } catch (error) {
                messageDiv.className = 'message error';
                messageDiv.textContent = 'Nätverksfel: ' + error.message;
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Spara config';
            }
        }

        // Initial fetch for groups and config
        fetchGroups();
        loadConfig();

        // Polling - refresh groups every 30 seconds
        setInterval(fetchGroups, 30000);
    </script>
</body>
</html>
"""


async def index_handler(request: web.Request) -> web.Response:
    """Serve the main HTML page."""
    html = HTML_TEMPLATE.replace("{{version}}", __version__)
    return web.Response(text=html, content_type="text/html")


async def config_handler(request: web.Request) -> web.Response:
    """Return current config as JSON."""
    config_data = {
        "signal_number": SIGNAL_NUMBER,
        "display_name": DISPLAY_NAME,
        "signal_cli_host": SIGNAL_CLI_HOST,
        "signal_cli_port": SIGNAL_CLI_PORT,
        "signal_cli_path": SIGNAL_CLI_PATH,
        "signal_cli_log_file": SIGNAL_CLI_LOG_FILE,
        "unmanaged_signal_cli": UNMANAGED_SIGNAL_CLI,
        "vault_path": VAULT_PATH,
        "timezone": str(TIMEZONE),
        "append_window_minutes": APPEND_WINDOW_MINUTES,
        "startup_message": STARTUP_MESSAGE,
        "ignored_groups": IGNORED_GROUPS,
        "plus_plus_enabled": PLUS_PLUS_ENABLED,
        "regex_patterns": REGEX_PATTERNS,
        "log_level": logging.getLevelName(LOG_LEVEL),
        "web_enabled": WEB_ENABLED,
        "web_port": WEB_PORT,
        "web_access_log": WEB_ACCESS_LOG,
    }
    return web.json_response(config_data)


async def logs_handler(request: web.Request) -> web.Response:
    """Return buffered log entries as JSON."""
    log_buffer = get_log_buffer()
    entries = log_buffer.get_entries()
    return web.json_response(entries)


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
            return web.json_response({"success": False, "error": "Ingen grupp-ID angiven"}, status=400)

        app_state = get_app_state()
        if not app_state.writer:
            return web.json_response(
                {"success": False, "error": "Inte ansluten till signal-cli"},
                status=503,
            )

        # Accept invitation by calling updateGroup with the group ID
        request_id = app_state.get_next_request_id()
        json_request = {
            "jsonrpc": "2.0",
            "method": "updateGroup",
            "params": {"groupId": group_id},
            "id": request_id,
        }

        logger.info(f"Accepting group invitation: {group_id[:20]}...")
        app_state.writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
        await app_state.writer.drain()

        return web.json_response(
            {
                "success": True,
                "message": "Inbjudan accepterad",
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
            return web.json_response({"success": False, "error": "Ingen grupp-ID angiven"}, status=400)

        app_state = get_app_state()
        if not app_state.writer:
            return web.json_response(
                {"success": False, "error": "Inte ansluten till signal-cli"},
                status=503,
            )

        # Decline invitation by calling quitGroup with the group ID
        request_id = app_state.get_next_request_id()
        json_request = {
            "jsonrpc": "2.0",
            "method": "quitGroup",
            "params": {"groupId": group_id},
            "id": request_id,
        }

        logger.info(f"Declining group invitation: {group_id[:20]}...")
        app_state.writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
        await app_state.writer.drain()

        return web.json_response(
            {
                "success": True,
                "message": "Inbjudan avböjd",
            }
        )

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error declining invitation: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


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
    return web.json_response({"groups": groups, "ignoredGroups": IGNORED_GROUPS})


async def toggle_ignore_group_handler(request: web.Request) -> web.Response:
    """Toggle ignore status for a group by updating config.ini."""
    try:
        data = await request.json()
        group_name = data.get("groupName", "").strip()

        if not group_name:
            return web.json_response({"success": False, "error": "Inget gruppnamn angivet"}, status=400)

        # Read current config
        try:
            with open("config.ini", encoding="utf-8") as f:
                config_content = f.read()
        except FileNotFoundError:
            return web.json_response({"success": False, "error": "config.ini hittades inte"}, status=404)

        # Parse to get current ignored groups
        import configparser

        config = configparser.RawConfigParser()
        config.read_string(config_content)

        ignored_groups = []
        if config.has_section("Settings") and config.has_option("Settings", "ignored_groups"):
            ignored_str = config.get("Settings", "ignored_groups")
            ignored_groups = [g.strip() for g in ignored_str.split(",") if g.strip()]

        # Toggle the group
        if group_name in ignored_groups:
            ignored_groups.remove(group_name)
            action = "removed from"
        else:
            ignored_groups.append(group_name)
            action = "added to"

        # Update config
        if not config.has_section("Settings"):
            config.add_section("Settings")
        config.set("Settings", "ignored_groups", ", ".join(ignored_groups))

        # Write back
        with open("config.ini", "w", encoding="utf-8") as f:
            config.write(f)

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


async def config_file_get_handler(request: web.Request) -> web.Response:
    """Return the raw content of config.ini."""
    try:
        with open("config.ini", encoding="utf-8") as f:
            content = f.read()
        return web.json_response({"content": content})
    except FileNotFoundError:
        return web.json_response({"content": "", "error": "config.ini hittades inte"}, status=404)
    except Exception as e:
        return web.json_response({"content": "", "error": str(e)}, status=500)


async def config_file_save_handler(request: web.Request) -> web.Response:
    """Save new content to config.ini."""
    try:
        data = await request.json()
        content = data.get("content", "")

        if not content.strip():
            return web.json_response({"success": False, "error": "Config kan inte vara tom"}, status=400)

        # Validate by trying to parse it
        import configparser

        config = configparser.RawConfigParser()
        try:
            config.read_string(content)
        except configparser.Error as e:
            return web.json_response({"success": False, "error": f"Ogiltig INI-syntax: {e}"}, status=400)

        # Check required sections
        if not config.has_section("Vault") or not config.has_section("Signal"):
            return web.json_response(
                {"success": False, "error": "Config måste ha [Vault] och [Signal] sektioner"},
                status=400,
            )

        # Write to file
        with open("config.ini", "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("config.ini updated via web GUI")
        return web.json_response({"success": True, "message": "Config sparad"})

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/config", config_handler)
    app.router.add_get("/api/logs", logs_handler)
    app.router.add_post("/api/join-group", join_group_handler)
    app.router.add_get("/api/invitations", invitations_handler)
    app.router.add_post("/api/invitations/accept", accept_invitation_handler)
    app.router.add_post("/api/invitations/decline", decline_invitation_handler)
    app.router.add_get("/api/groups", groups_handler)
    app.router.add_post("/api/toggle-ignore-group", toggle_ignore_group_handler)
    app.router.add_get("/api/config-file", config_file_get_handler)
    app.router.add_post("/api/config-file", config_file_save_handler)
    return app


async def start_web_server(port: int = 8080) -> web.AppRunner:
    """Start the web server on the specified port.

    Args:
        port: Port to listen on (default 8080).

    Returns:
        The AppRunner instance (for cleanup).
    """
    app = create_app()

    # Configure access logger to write to file instead of terminal
    access_log: logging.Logger | None = None
    if WEB_ACCESS_LOG:
        access_log = logging.getLogger("aiohttp.access")
        access_log.setLevel(logging.INFO)
        # Remove any existing handlers to avoid duplicate output
        access_log.handlers.clear()
        access_log.propagate = False
        # Add file handler
        file_handler = logging.FileHandler(WEB_ACCESS_LOG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        access_log.addHandler(file_handler)

    runner = web.AppRunner(app, access_log=access_log)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info(f"Web GUI started at http://127.0.0.1:{port}")
    return runner


async def run_web_server(port: int = 8080) -> None:
    """Run the web server indefinitely.

    This function starts the web server and waits forever.
    Use this with asyncio.gather() to run alongside other tasks.
    """
    runner = await start_web_server(port)
    try:
        # Wait forever
        await asyncio.sleep(float("inf"))
    finally:
        await runner.cleanup()
