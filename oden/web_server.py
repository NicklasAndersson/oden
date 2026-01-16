"""
Web server for Oden GUI.

Provides a simple read-only web interface for viewing config and logs.
"""

import logging

from aiohttp import web

from oden import __version__
from oden.config import (
    APPEND_WINDOW_MINUTES,
    DISPLAY_NAME,
    IGNORED_GROUPS,
    LOG_LEVEL,
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
                <h2>📜 Logg</h2>
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
        "regex_patterns": REGEX_PATTERNS,
        "log_level": logging.getLevelName(LOG_LEVEL),
        "web_port": WEB_PORT,
    }
    return web.json_response(config_data)


async def logs_handler(request: web.Request) -> web.Response:
    """Return buffered log entries as JSON."""
    log_buffer = get_log_buffer()
    entries = log_buffer.get_entries()
    return web.json_response(entries)


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/config", config_handler)
    app.router.add_get("/api/logs", logs_handler)
    return app


async def start_web_server(port: int = 8080) -> web.AppRunner:
    """Start the web server on the specified port.

    Args:
        port: Port to listen on (default 8080).

    Returns:
        The AppRunner instance (for cleanup).
    """
    app = create_app()
    runner = web.AppRunner(app)
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


# Need to import asyncio at module level for run_web_server
import asyncio  # noqa: E402
