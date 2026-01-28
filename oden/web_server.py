"""
Web server for Oden GUI.

Provides a web interface for viewing config, logs, sending commands,
and initial setup wizard for first-run configuration.
"""

import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path

import qrcode
import qrcode.image.svg
from aiohttp import web

from oden import __version__
from oden.app_state import get_app_state
from oden.config import (
    CONFIG_FILE,
    DEFAULT_VAULT_PATH,
    IGNORED_GROUPS,
    ODEN_HOME,
    WEB_ACCESS_LOG,
    get_bundle_path,
    get_config,
    reload_config,
    save_config,
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
        .warning-banner.success {
            background: rgba(76, 175, 80, 0.2);
            border: 1px solid #4caf50;
            color: #4caf50;
        }
        .warning-banner .icon {
            font-size: 1.2em;
        }
        .config-form {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .config-section {
            background: #0d1421;
            border-radius: 6px;
            padding: 15px;
            border: 1px solid #333;
        }
        .config-section h3 {
            color: #4fc3f7;
            font-size: 1em;
            margin-bottom: 15px;
            padding-bottom: 8px;
            border-bottom: 1px solid #333;
        }
        .config-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        @media (max-width: 600px) {
            .config-grid { grid-template-columns: 1fr; }
        }
        .config-field {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .config-field.full-width {
            grid-column: 1 / -1;
        }
        .config-field label {
            font-size: 0.85em;
            color: #888;
        }
        .config-field input,
        .config-field select {
            padding: 10px 12px;
            border: 1px solid #333;
            border-radius: 4px;
            background: #16213e;
            color: #fff;
            font-size: 0.95em;
        }
        .config-field input:focus,
        .config-field select:focus {
            outline: none;
            border-color: #4fc3f7;
        }
        .config-field input[type="checkbox"] {
            width: 20px;
            height: 20px;
            cursor: pointer;
        }
        .config-field .checkbox-wrapper {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .config-field .help-text {
            font-size: 0.8em;
            color: #666;
        }
        .config-actions {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }
        .config-actions .btn {
            flex: 1;
        }
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 15px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }
        .tab-btn {
            padding: 8px 16px;
            border: none;
            background: transparent;
            color: #888;
            cursor: pointer;
            border-radius: 4px 4px 0 0;
            transition: all 0.2s;
        }
        .tab-btn:hover {
            color: #fff;
            background: rgba(79, 195, 247, 0.1);
        }
        .tab-btn.active {
            color: #4fc3f7;
            background: rgba(79, 195, 247, 0.2);
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
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
                <h2>⚙️ Inställningar</h2>
                <div id="config-message" class="warning-banner">
                    <span class="icon">✓</span>
                    <span id="config-message-text"></span>
                </div>

                <div class="tabs">
                    <button class="tab-btn active" onclick="showTab('basic')">Grundläggande</button>
                    <button class="tab-btn" onclick="showTab('advanced')">Avancerat</button>
                    <button class="tab-btn" onclick="showTab('raw')">Rå config</button>
                </div>

                <div id="tab-basic" class="tab-content active">
                    <form id="config-form" class="config-form">
                        <div class="config-section">
                            <h3>📱 Signal</h3>
                            <div class="config-grid">
                                <div class="config-field">
                                    <label for="cfg-signal-number">Telefonnummer</label>
                                    <input type="text" id="cfg-signal-number" name="signal_number" placeholder="+46...">
                                </div>
                                <div class="config-field">
                                    <label for="cfg-display-name">Visningsnamn</label>
                                    <input type="text" id="cfg-display-name" name="display_name" placeholder="oden">
                                </div>
                            </div>
                        </div>

                        <div class="config-section">
                            <h3>📁 Vault</h3>
                            <div class="config-grid">
                                <div class="config-field full-width">
                                    <label for="cfg-vault-path">Sökväg till vault</label>
                                    <input type="text" id="cfg-vault-path" name="vault_path" placeholder="~/oden-vault">
                                </div>
                            </div>
                        </div>

                        <div class="config-section">
                            <h3>⏱️ Inställningar</h3>
                            <div class="config-grid">
                                <div class="config-field">
                                    <label for="cfg-timezone">Tidszon</label>
                                    <input type="text" id="cfg-timezone" name="timezone" placeholder="Europe/Stockholm">
                                </div>
                                <div class="config-field">
                                    <label for="cfg-append-window">Append-fönster (minuter)</label>
                                    <input type="number" id="cfg-append-window" name="append_window_minutes" min="1" max="1440">
                                </div>
                                <div class="config-field">
                                    <label for="cfg-startup-message">Startup-meddelande</label>
                                    <select id="cfg-startup-message" name="startup_message">
                                        <option value="self">Skicka till mig själv</option>
                                        <option value="all">Skicka till alla grupper</option>
                                        <option value="off">Av</option>
                                    </select>
                                </div>
                                <div class="config-field">
                                    <label>Funktioner</label>
                                    <div class="checkbox-wrapper">
                                        <input type="checkbox" id="cfg-plus-plus" name="plus_plus_enabled">
                                        <label for="cfg-plus-plus" style="color: #fff;">Aktivera ++ (append-läge)</label>
                                    </div>
                                </div>
                                <div class="config-field full-width">
                                    <label for="cfg-ignored-groups">Ignorerade grupper (kommaseparerade)</label>
                                    <input type="text" id="cfg-ignored-groups" name="ignored_groups" placeholder="Grupp1, Grupp2">
                                    <span class="help-text">Meddelanden från dessa grupper sparas inte</span>
                                </div>
                            </div>
                        </div>

                        <div class="config-actions">
                            <button type="submit" class="btn btn-primary" id="save-config-btn">
                                Spara och applicera
                            </button>
                            <button type="button" class="btn btn-secondary" onclick="loadConfigForm()">Återställ</button>
                        </div>
                    </form>
                </div>

                <div id="tab-advanced" class="tab-content">
                    <form id="config-form-advanced" class="config-form">
                        <div class="config-section">
                            <h3>🔧 signal-cli</h3>
                            <div class="config-grid">
                                <div class="config-field">
                                    <label for="cfg-signal-host">Host</label>
                                    <input type="text" id="cfg-signal-host" name="signal_cli_host" placeholder="127.0.0.1">
                                </div>
                                <div class="config-field">
                                    <label for="cfg-signal-port">Port</label>
                                    <input type="number" id="cfg-signal-port" name="signal_cli_port" placeholder="7583">
                                </div>
                                <div class="config-field full-width">
                                    <label for="cfg-signal-path">Sökväg till signal-cli (valfritt)</label>
                                    <input type="text" id="cfg-signal-path" name="signal_cli_path" placeholder="Lämna tomt för auto">
                                </div>
                                <div class="config-field">
                                    <label>Extern signal-cli</label>
                                    <div class="checkbox-wrapper">
                                        <input type="checkbox" id="cfg-unmanaged" name="unmanaged_signal_cli">
                                        <label for="cfg-unmanaged" style="color: #fff;">Ohanterad (startas inte av Oden)</label>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="config-section">
                            <h3>🌐 Webbserver</h3>
                            <div class="config-grid">
                                <div class="config-field">
                                    <label>Status</label>
                                    <div class="checkbox-wrapper">
                                        <input type="checkbox" id="cfg-web-enabled" name="web_enabled" checked>
                                        <label for="cfg-web-enabled" style="color: #fff;">Aktivera webbgränssnitt</label>
                                    </div>
                                </div>
                                <div class="config-field">
                                    <label for="cfg-web-port">Port</label>
                                    <input type="number" id="cfg-web-port" name="web_port" placeholder="8080">
                                </div>
                            </div>
                        </div>

                        <div class="config-section">
                            <h3>📝 Loggning</h3>
                            <div class="config-grid">
                                <div class="config-field">
                                    <label for="cfg-log-level">Loggnivå</label>
                                    <select id="cfg-log-level" name="log_level">
                                        <option value="DEBUG">DEBUG</option>
                                        <option value="INFO">INFO</option>
                                        <option value="WARNING">WARNING</option>
                                        <option value="ERROR">ERROR</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        <div class="config-actions">
                            <button type="submit" class="btn btn-primary" id="save-config-adv-btn">
                                Spara och applicera
                            </button>
                            <button type="button" class="btn btn-secondary" onclick="loadConfigForm()">Återställ</button>
                        </div>
                    </form>
                </div>

                <div id="tab-raw" class="tab-content">
                    <div class="config-section">
                        <h3>📄 config.ini (rå redigering)</h3>
                        <textarea id="config-content" style="width:100%;min-height:300px;padding:12px;border:1px solid #333;border-radius:4px;background:#16213e;color:#fff;font-family:Monaco,Menlo,monospace;font-size:0.9em;resize:vertical;" placeholder="Laddar config.ini..."></textarea>
                        <div class="config-actions" style="margin-top:15px;">
                            <button type="button" class="btn btn-primary" onclick="saveRawConfig()">Spara rå config</button>
                            <button type="button" class="btn btn-secondary" onclick="loadRawConfig()">Återställ</button>
                        </div>
                    </div>
                </div>
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
                    showConfigMessage('Grupp uppdaterad! Ändringen appliceras direkt.', 'success');
                    // Refresh groups list
                    await fetchGroups();
                    // Refresh config form
                    await loadConfigForm();
                } else {
                    alert(result.error || 'Något gick fel');
                }
            } catch (error) {
                alert('Nätverksfel: ' + error.message);
            }
        }

        // Tab switching
        function showTab(tabName) {
            // Hide all tabs
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

            // Show selected tab
            document.getElementById('tab-' + tabName).classList.add('active');
            event.target.classList.add('active');

            // Load raw config when switching to raw tab
            if (tabName === 'raw') {
                loadRawConfig();
            }
        }

        // Config message helper
        function showConfigMessage(message, type) {
            const msgDiv = document.getElementById('config-message');
            const msgText = document.getElementById('config-message-text');
            msgDiv.classList.remove('show', 'success');
            msgText.textContent = message;
            if (type === 'success') {
                msgDiv.classList.add('success');
                msgDiv.querySelector('.icon').textContent = '✓';
            } else {
                msgDiv.querySelector('.icon').textContent = '⚠️';
            }
            msgDiv.classList.add('show');
            setTimeout(() => msgDiv.classList.remove('show'), 5000);
        }

        // Load config into form fields
        async function loadConfigForm() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();

                // Basic tab
                document.getElementById('cfg-signal-number').value = config.signal_number || '';
                document.getElementById('cfg-display-name').value = config.display_name || '';
                document.getElementById('cfg-vault-path').value = config.vault_path || '';
                document.getElementById('cfg-timezone').value = config.timezone || 'Europe/Stockholm';
                document.getElementById('cfg-append-window').value = config.append_window_minutes || 30;
                document.getElementById('cfg-startup-message').value = config.startup_message || 'self';
                document.getElementById('cfg-plus-plus').checked = config.plus_plus_enabled || false;
                document.getElementById('cfg-ignored-groups').value = (config.ignored_groups || []).join(', ');

                // Advanced tab
                document.getElementById('cfg-signal-host').value = config.signal_cli_host || '127.0.0.1';
                document.getElementById('cfg-signal-port').value = config.signal_cli_port || 7583;
                document.getElementById('cfg-signal-path').value = config.signal_cli_path || '';
                document.getElementById('cfg-unmanaged').checked = config.unmanaged_signal_cli || false;
                document.getElementById('cfg-web-enabled').checked = config.web_enabled !== false;
                document.getElementById('cfg-web-port').value = config.web_port || 8080;
                document.getElementById('cfg-log-level').value = config.log_level || 'INFO';
            } catch (error) {
                console.error('Error loading config:', error);
            }
        }

        // Save config from form and trigger live reload
        async function saveConfigForm(event) {
            event.preventDefault();
            const btn = event.submitter || document.getElementById('save-config-btn');
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span>Sparar...';

            // Gather form data from both tabs
            const configData = {
                signal_number: document.getElementById('cfg-signal-number').value,
                display_name: document.getElementById('cfg-display-name').value,
                vault_path: document.getElementById('cfg-vault-path').value,
                timezone: document.getElementById('cfg-timezone').value,
                append_window_minutes: parseInt(document.getElementById('cfg-append-window').value) || 30,
                startup_message: document.getElementById('cfg-startup-message').value,
                plus_plus_enabled: document.getElementById('cfg-plus-plus').checked,
                ignored_groups: document.getElementById('cfg-ignored-groups').value
                    .split(',').map(s => s.trim()).filter(s => s),
                signal_cli_host: document.getElementById('cfg-signal-host').value,
                signal_cli_port: parseInt(document.getElementById('cfg-signal-port').value) || 7583,
                signal_cli_path: document.getElementById('cfg-signal-path').value || null,
                unmanaged_signal_cli: document.getElementById('cfg-unmanaged').checked,
                web_enabled: document.getElementById('cfg-web-enabled').checked,
                web_port: parseInt(document.getElementById('cfg-web-port').value) || 8080,
                log_level: document.getElementById('cfg-log-level').value
            };

            try {
                const response = await fetch('/api/config-save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(configData)
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    showConfigMessage('✓ Inställningar sparade och applicerade!', 'success');
                    // Refresh the config display
                    await fetchConfig();
                    await fetchGroups();
                } else {
                    showConfigMessage(result.error || 'Kunde inte spara', 'error');
                }
            } catch (error) {
                showConfigMessage('Nätverksfel: ' + error.message, 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        }

        // Raw config functions
        async function loadRawConfig() {
            try {
                const response = await fetch('/api/config-file');
                const data = await response.json();
                document.getElementById('config-content').value = data.content || '';
            } catch (error) {
                console.error('Error loading config:', error);
                document.getElementById('config-content').value = '# Kunde inte ladda config.ini';
            }
        }

        async function saveRawConfig() {
            const content = document.getElementById('config-content').value;
            try {
                const response = await fetch('/api/config-file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content, reload: true })
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    showConfigMessage('✓ Config sparad och applicerad!', 'success');
                    await fetchConfig();
                    await fetchGroups();
                    await loadConfigForm();
                } else {
                    showConfigMessage(result.error || 'Kunde inte spara config', 'error');
                }
            } catch (error) {
                showConfigMessage('Nätverksfel: ' + error.message, 'error');
            }
        }

        // Attach form handlers
        document.getElementById('config-form').addEventListener('submit', saveConfigForm);
        document.getElementById('config-form-advanced').addEventListener('submit', saveConfigForm);

        // Initial fetch for groups and config
        fetchGroups();
        loadConfigForm();

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
    """Return current config as JSON (reads live from disk)."""
    # Read config fresh from disk to support live reload
    config = get_config()
    config_data = {
        "signal_number": config["signal_number"],
        "display_name": config["display_name"],
        "signal_cli_host": config["signal_cli_host"],
        "signal_cli_port": config["signal_cli_port"],
        "signal_cli_path": config["signal_cli_path"],
        "signal_cli_log_file": config["signal_cli_log_file"],
        "unmanaged_signal_cli": config["unmanaged_signal_cli"],
        "vault_path": config["vault_path"],
        "timezone": str(config["timezone"]),
        "append_window_minutes": config["append_window_minutes"],
        "startup_message": config["startup_message"],
        "ignored_groups": config["ignored_groups"],
        "plus_plus_enabled": config["plus_plus_enabled"],
        "regex_patterns": config["regex_patterns"],
        "log_level": logging.getLevelName(config["log_level"]),
        "web_enabled": config["web_enabled"],
        "web_port": config["web_port"],
        "web_access_log": config["web_access_log"],
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
        if CONFIG_FILE.exists():
            content = CONFIG_FILE.read_text(encoding="utf-8")
        else:
            # Fallback to local config.ini
            with open("config.ini", encoding="utf-8") as f:
                content = f.read()
        return web.json_response({"content": content})
    except FileNotFoundError:
        return web.json_response({"content": "", "error": "config.ini hittades inte"}, status=404)
    except Exception as e:
        return web.json_response({"content": "", "error": str(e)}, status=500)


async def config_file_save_handler(request: web.Request) -> web.Response:
    """Save new content to config.ini and optionally trigger live reload."""
    try:
        data = await request.json()
        content = data.get("content", "")
        do_reload = data.get("reload", False)

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

        # Write to file (prefer ~/.oden/config.ini)
        config_path = CONFIG_FILE if CONFIG_FILE.exists() else "config.ini"
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"config.ini updated via web GUI (reload={do_reload})")

        # Trigger live reload if requested
        if do_reload:
            reload_config()
            logger.info("Configuration reloaded")

        return web.json_response({"success": True, "message": "Config sparad"})

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def config_save_handler(request: web.Request) -> web.Response:
    """Save configuration from structured form data and trigger live reload."""
    try:
        data = await request.json()

        # Build config dict
        config_dict = {
            "signal_number": data.get("signal_number", ""),
            "display_name": data.get("display_name", "oden"),
            "vault_path": data.get("vault_path", str(DEFAULT_VAULT_PATH)),
            "timezone": data.get("timezone", "Europe/Stockholm"),
            "append_window_minutes": data.get("append_window_minutes", 30),
            "startup_message": data.get("startup_message", "self"),
            "plus_plus_enabled": data.get("plus_plus_enabled", False),
            "ignored_groups": data.get("ignored_groups", []),
            "signal_cli_host": data.get("signal_cli_host", "127.0.0.1"),
            "signal_cli_port": data.get("signal_cli_port", 7583),
            "signal_cli_path": data.get("signal_cli_path"),
            "unmanaged_signal_cli": data.get("unmanaged_signal_cli", False),
            "web_enabled": data.get("web_enabled", True),
            "web_port": data.get("web_port", 8080),
            "log_level": data.get("log_level", "INFO"),
        }

        # Validate required fields
        if not config_dict["signal_number"] or config_dict["signal_number"] == "+46XXXXXXXXX":
            return web.json_response(
                {"success": False, "error": "Signal-nummer måste anges"},
                status=400,
            )

        # Save config
        save_config(config_dict)
        logger.info(f"Config saved via web GUI form to {CONFIG_FILE}")

        # Trigger live reload
        reload_config()
        logger.info("Configuration reloaded (live reload)")

        return web.json_response({
            "success": True,
            "message": "Konfiguration sparad och applicerad!",
        })

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving config via form: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


# =============================================================================
# Setup Wizard Handlers (for first-run configuration)
# =============================================================================

# Global state for the linking process
_linker = None
_link_task = None


async def setup_handler(request: web.Request) -> web.Response:
    """Serve the setup wizard HTML page."""
    # Try to load from static file first (bundled app)
    bundle_path = get_bundle_path()
    static_file = bundle_path / "static" / "setup.html"

    if static_file.exists():
        return web.FileResponse(static_file)

    # Fallback to inline HTML for development
    return web.Response(text=SETUP_HTML_TEMPLATE.replace("{{version}}", __version__), content_type="text/html")


async def setup_status_handler(request: web.Request) -> web.Response:
    """Return current setup/linking status."""
    global _linker

    # Only fetch accounts if explicitly requested (slow operation)
    include_accounts = request.query.get("accounts") == "true"
    existing_accounts = []

    if include_accounts:
        from oden.signal_manager import get_existing_accounts
        existing_accounts = get_existing_accounts()

    if _linker is None:
        return web.json_response({
            "status": "idle",
            "configured": False,
            "oden_home": str(ODEN_HOME),
            "default_vault": str(DEFAULT_VAULT_PATH),
            "existing_accounts": existing_accounts,
        })

    return web.json_response({
        "status": _linker.status,
        "link_uri": _linker.link_uri,
        "linked_number": _linker.linked_number,
        "error": _linker.error,
        "manual_instructions": _linker.get_manual_instructions() if _linker.status == "timeout" else None,
        "existing_accounts": existing_accounts,
    })


async def setup_start_link_handler(request: web.Request) -> web.Response:
    """Start the Signal account linking process."""
    global _linker, _link_task

    try:
        data = await request.json()
        device_name = data.get("device_name", "Oden")
    except (json.JSONDecodeError, TypeError):
        device_name = "Oden"

    # Import here to avoid circular imports
    from oden.signal_manager import SignalLinker

    # Cancel any existing linking process
    if _linker and _linker.process:
        await _linker.cancel()

    _linker = SignalLinker(device_name=device_name)

    try:
        uri = await _linker.start_link()
        if uri:
            # Generate QR code as SVG
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
            svg_buffer = io.BytesIO()
            img.save(svg_buffer)
            qr_svg = svg_buffer.getvalue().decode('utf-8')

            # Start waiting for link in background
            _link_task = asyncio.create_task(_wait_for_link_background())
            return web.json_response({
                "success": True,
                "link_uri": uri,
                "qr_svg": qr_svg,
                "status": "waiting",
            })
        else:
            return web.json_response({
                "success": False,
                "error": _linker.error or "Kunde inte starta länkning",
                "status": "error",
            }, status=500)

    except FileNotFoundError as e:
        return web.json_response({
            "success": False,
            "error": f"signal-cli hittades inte: {e}",
            "status": "error",
        }, status=500)
    except Exception as e:
        logger.error(f"Error starting link: {e}")
        return web.json_response({
            "success": False,
            "error": str(e),
            "status": "error",
        }, status=500)


async def _wait_for_link_background():
    """Background task to wait for linking to complete."""
    global _linker
    if _linker:
        await _linker.wait_for_link(timeout=60.0)


async def setup_cancel_link_handler(request: web.Request) -> web.Response:
    """Cancel the linking process."""
    global _linker, _link_task

    if _link_task:
        _link_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _link_task
        _link_task = None

    if _linker:
        await _linker.cancel()
        _linker = None

    return web.json_response({"success": True})


async def setup_save_config_handler(request: web.Request) -> web.Response:
    """Save the setup configuration."""
    global _linker

    try:
        data = await request.json()
        vault_path = data.get("vault_path", str(DEFAULT_VAULT_PATH))
        signal_number = data.get("signal_number", "")
        display_name = data.get("display_name", "oden")

        logger.info(f"Save config request: signal_number={signal_number}, vault_path={vault_path}")

        # Use linked number from _linker only if no number was provided
        if not signal_number and _linker and _linker.linked_number:
            signal_number = _linker.linked_number
            logger.info(f"Using linked number from _linker: {signal_number}")

        if not signal_number or signal_number == "+46XXXXXXXXX":
            return web.json_response({
                "success": False,
                "error": "Signal-nummer måste anges",
            }, status=400)

        # Expand and validate vault path
        vault_path = str(Path(vault_path).expanduser())

        # Create vault directory
        Path(vault_path).mkdir(parents=True, exist_ok=True)

        # Save config
        config_dict = {
            "vault_path": vault_path,
            "signal_number": signal_number,
            "display_name": display_name,
            "append_window_minutes": 30,
            "startup_message": "self",
            "plus_plus_enabled": False,
            "timezone": "Europe/Stockholm",
            "web_enabled": True,
            "web_port": 8080,
        }

        save_config(config_dict)
        logger.info(f"Setup complete. Config saved to {CONFIG_FILE}")

        return web.json_response({
            "success": True,
            "message": "Konfiguration sparad! Oden startar om...",
            "config_path": str(CONFIG_FILE),
        })

    except json.JSONDecodeError:
        return web.json_response({"success": False, "error": "Ogiltig JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error saving setup config: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


# Setup HTML template (fallback for development)
SETUP_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Oden - Setup</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .setup-container {
            background: #16213e;
            border-radius: 12px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }
        h1 { color: #4fc3f7; margin-bottom: 10px; text-align: center; }
        .version { color: #666; text-align: center; margin-bottom: 30px; }
        .step { display: none; }
        .step.active { display: block; }
        .step-indicator {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 30px;
        }
        .step-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #333;
            transition: background 0.3s;
        }
        .step-dot.active { background: #4fc3f7; }
        .step-dot.completed { background: #4caf50; }
        .form-group { margin-bottom: 20px; }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #aaa;
        }
        .form-group input {
            width: 100%;
            padding: 12px 15px;
            border: 1px solid #333;
            border-radius: 6px;
            background: #0d1421;
            color: #fff;
            font-size: 1em;
        }
        .form-group input:focus {
            outline: none;
            border-color: #4fc3f7;
        }
        .btn {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 6px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #4fc3f7;
            color: #1a1a2e;
            font-weight: 600;
        }
        .btn-primary:hover { background: #81d4fa; }
        .btn-primary:disabled {
            background: #555;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: transparent;
            border: 1px solid #555;
            color: #aaa;
            margin-top: 10px;
        }
        .btn-secondary:hover { border-color: #888; color: #fff; }
        .qr-container {
            text-align: center;
            padding: 20px;
            background: #fff;
            border-radius: 8px;
            margin: 20px 0;
        }
        .qr-container img, .qr-container canvas {
            max-width: 250px;
            height: auto;
        }
        .countdown {
            text-align: center;
            color: #888;
            margin: 15px 0;
            font-size: 0.9em;
        }
        .countdown.warning { color: #ffb74d; }
        .instructions {
            background: #0d1421;
            border-radius: 6px;
            padding: 15px;
            margin: 15px 0;
            font-size: 0.9em;
            line-height: 1.6;
        }
        .instructions ol {
            margin-left: 20px;
        }
        .instructions li {
            margin: 8px 0;
        }
        .error {
            background: rgba(239, 83, 80, 0.2);
            border: 1px solid #ef5350;
            color: #ef5350;
            padding: 12px;
            border-radius: 6px;
            margin: 15px 0;
        }
        .success {
            background: rgba(76, 175, 80, 0.2);
            border: 1px solid #4caf50;
            color: #4caf50;
            padding: 12px;
            border-radius: 6px;
            margin: 15px 0;
            text-align: center;
        }
        .manual-instructions {
            background: #0d1421;
            border: 1px solid #ffb74d;
            border-radius: 6px;
            padding: 15px;
            margin: 15px 0;
            white-space: pre-wrap;
            font-family: 'Monaco', monospace;
            font-size: 0.85em;
            line-height: 1.5;
        }
        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #333;
            border-top-color: #4fc3f7;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .hidden { display: none !important; }
    </style>
</head>
<body>
    <div class="setup-container">
        <h1>🛡️ Oden Setup</h1>
        <p class="version">v{{version}}</p>

        <div class="step-indicator">
            <div class="step-dot active" id="dot-1"></div>
            <div class="step-dot" id="dot-2"></div>
            <div class="step-dot" id="dot-3"></div>
        </div>

        <!-- Step 1: Vault Path -->
        <div class="step active" id="step-1">
            <h2 style="margin-bottom: 20px;">📁 Välj Vault-sökväg</h2>
            <p style="color: #888; margin-bottom: 20px;">
                Ange sökvägen där Oden ska spara markdown-filer från Signal.
            </p>
            <div class="form-group">
                <label for="vault-path">Vault-sökväg</label>
                <input type="text" id="vault-path" placeholder="~/oden-vault">
            </div>
            <button class="btn btn-primary" onclick="goToStep(2)">Nästa →</button>
        </div>

        <!-- Step 2: Signal Linking -->
        <div class="step" id="step-2">
            <h2 style="margin-bottom: 20px;">📱 Länka Signal-konto</h2>

            <!-- Loading indicator -->
            <div id="accounts-loading" style="text-align: center; padding: 40px;">
                <div class="spinner"></div>
                <p style="color: #888; margin-top: 15px;">Letar efter befintliga Signal-konton...</p>
            </div>

            <!-- Existing accounts section -->
            <div id="existing-accounts" class="hidden">
                <div style="background: #1a3a1a; border: 1px solid #2d5a2d; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #4ade80;">✓ Befintliga Signal-konton hittades</h3>
                    <p style="color: #888; margin-bottom: 15px;">Du har redan konfigurerade Signal-konton. Välj ett att använda eller länka ett nytt.</p>
                    <div id="accounts-list"></div>
                </div>
            </div>

            <div id="link-start" class="hidden">
                <p style="color: #888; margin-bottom: 20px;">
                    Klicka på knappen nedan för att starta länkningen. En QR-kod visas som du scannar med Signal-appen.
                </p>
                <div class="form-group">
                    <label for="device-name">Enhetsnamn</label>
                    <input type="text" id="device-name" value="Oden" placeholder="Oden">
                </div>
                <button class="btn btn-primary" onclick="startLinking()">Länka nytt konto</button>
                <button class="btn btn-secondary" onclick="goToStep(1)">← Tillbaka</button>
            </div>

            <div id="link-waiting" class="hidden">
                <div class="instructions">
                    <ol>
                        <li>Öppna <strong>Signal</strong> på din telefon</li>
                        <li>Gå till <strong>Inställningar → Länkade enheter</strong></li>
                        <li>Tryck på <strong>"+"</strong> eller <strong>"Länka ny enhet"</strong></li>
                        <li>Scanna QR-koden nedan</li>
                    </ol>
                </div>
                <div class="qr-container" id="qr-container">
                    <div class="spinner"></div>
                </div>
                <div class="countdown" id="countdown">Väntar på scan... 60s</div>
                <button class="btn btn-secondary" onclick="cancelLinking()">Avbryt</button>
            </div>

            <div id="link-success" class="hidden">
                <div class="success">
                    ✅ Länkning lyckades!<br>
                    <strong id="linked-number"></strong>
                </div>
                <button class="btn btn-primary" onclick="goToStep(3)">Nästa →</button>
            </div>

            <div id="link-timeout" class="hidden">
                <div class="error">
                    ⏱️ Länkningen tog för lång tid. Försök igen eller följ de manuella stegen nedan.
                </div>
                <div class="manual-instructions" id="manual-instructions"></div>
                <div class="form-group">
                    <label for="manual-number">Ange ditt Signal-nummer manuellt</label>
                    <input type="text" id="manual-number" placeholder="+46701234567">
                </div>
                <button class="btn btn-primary" onclick="useManualNumber()">Använd detta nummer</button>
                <button class="btn btn-secondary" onclick="retryLinking()">Försök igen</button>
            </div>

            <div id="link-error" class="hidden">
                <div class="error" id="error-message"></div>
                <button class="btn btn-secondary" onclick="retryLinking()">Försök igen</button>
                <button class="btn btn-secondary" onclick="goToStep(1)">← Tillbaka</button>
            </div>
        </div>

        <!-- Step 3: Confirmation -->
        <div class="step" id="step-3">
            <h2 style="margin-bottom: 20px;">✅ Bekräfta inställningar</h2>
            <div class="instructions">
                <table style="width: 100%;">
                    <tr><td style="color: #888;">Vault:</td><td id="confirm-vault">-</td></tr>
                    <tr><td style="color: #888;">Signal:</td><td id="confirm-number">-</td></tr>
                    <tr><td style="color: #888;">Enhetsnamn:</td><td id="confirm-device">-</td></tr>
                </table>
            </div>
            <button class="btn btn-primary" onclick="saveConfig()" id="save-btn">Spara och starta Oden</button>
            <button class="btn btn-secondary" onclick="goToStep(2)">← Tillbaka</button>
            <div id="save-message"></div>
        </div>
    </div>

    <script>
        let currentStep = 1;
        let linkedNumber = null;
        let countdownInterval = null;
        let pollInterval = null;
        let existingAccounts = [];

        // Set default vault path on page load (quick, no signal-cli needed)
        fetch('/api/setup/status')
            .then(r => r.json())
            .then(data => {
                document.getElementById('vault-path').value = data.default_vault || '~/oden-vault';
            });

        function showExistingAccounts(accounts) {
            const container = document.getElementById('existing-accounts');
            const list = document.getElementById('accounts-list');

            list.innerHTML = accounts.map((acc, i) => `
                <button class="btn btn-primary" style="margin: 5px; width: auto;"
                        onclick="useExistingAccount('${acc.number}')">
                    ${acc.number}
                </button>
            `).join('');

            container.classList.remove('hidden');
        }

        function useExistingAccount(number) {
            linkedNumber = number;
            document.getElementById('accounts-loading').classList.add('hidden');
            document.getElementById('link-start').classList.add('hidden');
            document.getElementById('existing-accounts').classList.add('hidden');
            document.getElementById('link-success').classList.remove('hidden');
            document.getElementById('linked-number').textContent = number;
        }

        async function loadExistingAccounts() {
            // Show loading, hide other sections
            document.getElementById('accounts-loading').classList.remove('hidden');
            document.getElementById('existing-accounts').classList.add('hidden');
            document.getElementById('link-start').classList.add('hidden');

            try {
                // Use ?accounts=true to trigger the slow listAccounts call
                const response = await fetch('/api/setup/status?accounts=true');
                const data = await response.json();

                // Hide loading
                document.getElementById('accounts-loading').classList.add('hidden');

                // Show existing accounts if any
                if (data.existing_accounts && data.existing_accounts.length > 0) {
                    existingAccounts = data.existing_accounts;
                    showExistingAccounts(data.existing_accounts);
                }

                // Always show the link form (either below accounts or alone)
                document.getElementById('link-start').classList.remove('hidden');

            } catch (error) {
                // On error, just show the link form
                document.getElementById('accounts-loading').classList.add('hidden');
                document.getElementById('link-start').classList.remove('hidden');
            }
        }

        function goToStep(step) {
            document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
            document.getElementById('step-' + step).classList.add('active');

            document.querySelectorAll('.step-dot').forEach((dot, i) => {
                dot.classList.remove('active', 'completed');
                if (i + 1 < step) dot.classList.add('completed');
                if (i + 1 === step) dot.classList.add('active');
            });

            currentStep = step;

            if (step === 2) {
                // Load existing accounts when entering step 2
                loadExistingAccounts();
            }

            if (step === 3) {
                document.getElementById('confirm-vault').textContent = document.getElementById('vault-path').value;
                document.getElementById('confirm-number').textContent = linkedNumber || '(ej länkad)';
                document.getElementById('confirm-device').textContent = document.getElementById('device-name').value;
            }
        }

        async function startLinking() {
            const deviceName = document.getElementById('device-name').value || 'Oden';

            document.getElementById('link-start').classList.add('hidden');
            document.getElementById('existing-accounts').classList.add('hidden');
            document.getElementById('link-waiting').classList.remove('hidden');
            document.getElementById('link-success').classList.add('hidden');
            document.getElementById('link-timeout').classList.add('hidden');
            document.getElementById('link-error').classList.add('hidden');

            try {
                const response = await fetch('/api/setup/start-link', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_name: deviceName })
                });
                const data = await response.json();

                if (data.success && data.qr_svg) {
                    // Display server-generated QR code
                    const container = document.getElementById('qr-container');
                    container.innerHTML = data.qr_svg;
                    // Style the SVG
                    const svg = container.querySelector('svg');
                    if (svg) {
                        svg.style.width = '250px';
                        svg.style.height = '250px';
                    }

                    // Start countdown
                    let seconds = 60;
                    const countdownEl = document.getElementById('countdown');
                    countdownInterval = setInterval(() => {
                        seconds--;
                        countdownEl.textContent = 'Väntar på scan... ' + seconds + 's';
                        if (seconds <= 15) countdownEl.classList.add('warning');
                        if (seconds <= 0) clearInterval(countdownInterval);
                    }, 1000);

                    // Poll for status
                    pollInterval = setInterval(checkLinkStatus, 2000);
                } else {
                    showError(data.error || 'Kunde inte starta länkning');
                }
            } catch (error) {
                showError('Nätverksfel: ' + error.message);
            }
        }

        async function checkLinkStatus() {
            try {
                const response = await fetch('/api/setup/status');
                const data = await response.json();

                if (data.status === 'linked') {
                    clearInterval(countdownInterval);
                    clearInterval(pollInterval);
                    linkedNumber = data.linked_number;
                    document.getElementById('linked-number').textContent = linkedNumber;
                    document.getElementById('link-waiting').classList.add('hidden');
                    document.getElementById('link-success').classList.remove('hidden');
                } else if (data.status === 'timeout') {
                    clearInterval(countdownInterval);
                    clearInterval(pollInterval);
                    document.getElementById('link-waiting').classList.add('hidden');
                    document.getElementById('link-timeout').classList.remove('hidden');
                    if (data.manual_instructions) {
                        document.getElementById('manual-instructions').textContent = data.manual_instructions;
                    }
                } else if (data.status === 'error') {
                    clearInterval(countdownInterval);
                    clearInterval(pollInterval);
                    showError(data.error || 'Ett fel uppstod');
                }
            } catch (error) {
                console.error('Error checking status:', error);
            }
        }

        function showError(message) {
            document.getElementById('link-waiting').classList.add('hidden');
            document.getElementById('link-error').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }

        async function cancelLinking() {
            clearInterval(countdownInterval);
            clearInterval(pollInterval);
            await fetch('/api/setup/cancel-link', { method: 'POST' });
            document.getElementById('link-waiting').classList.add('hidden');
            document.getElementById('link-start').classList.remove('hidden');
        }

        function retryLinking() {
            document.getElementById('link-timeout').classList.add('hidden');
            document.getElementById('link-error').classList.add('hidden');
            document.getElementById('link-start').classList.remove('hidden');
        }

        function useManualNumber() {
            const number = document.getElementById('manual-number').value.trim();
            if (!number || !number.startsWith('+')) {
                alert('Ange ett giltigt telefonnummer (t.ex. +46701234567)');
                return;
            }
            linkedNumber = number;
            goToStep(3);
        }

        async function saveConfig() {
            const btn = document.getElementById('save-btn');
            const msgDiv = document.getElementById('save-message');
            btn.disabled = true;
            btn.textContent = 'Sparar...';

            try {
                const response = await fetch('/api/setup/save-config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        vault_path: document.getElementById('vault-path').value,
                        signal_number: linkedNumber,
                        display_name: document.getElementById('device-name').value
                    })
                });
                const data = await response.json();

                if (data.success) {
                    msgDiv.innerHTML = '<div class="success" style="padding: 20px; text-align: center;">' +
                        '<h2 style="margin: 0 0 10px 0;">✅ Klart!</h2>' +
                        '<p style="margin: 0;">' + data.message + '</p>' +
                        '<p style="margin: 10px 0 0 0; color: #888;" id="reload-status">Väntar på att Oden ska starta...</p>' +
                        '</div>';
                    btn.style.display = 'none';
                    document.querySelector('button.btn-secondary').style.display = 'none';
                    // Poll until the main server is ready
                    pollForMainServer();
                } else {
                    msgDiv.innerHTML = '<div class="error">' + data.error + '</div>';
                    btn.disabled = false;
                    btn.textContent = 'Spara och starta Oden';
                }
            } catch (error) {
                msgDiv.innerHTML = '<div class="error">Nätverksfel: ' + error.message + '</div>';
                btn.disabled = false;
                btn.textContent = 'Spara och starta Oden';
            }
        }

        async function pollForMainServer() {
            const statusEl = document.getElementById('reload-status');
            let attempts = 0;
            const maxAttempts = 30;  // 30 seconds max

            const poll = async () => {
                attempts++;
                try {
                    // Try to fetch the main page (not /setup)
                    const response = await fetch('/api/config');
                    if (response.ok) {
                        statusEl.textContent = 'Oden är redo! Laddar om...';
                        setTimeout(() => {
                            window.location.href = '/';
                        }, 500);
                        return;
                    }
                } catch (e) {
                    // Server not ready yet
                }

                if (attempts < maxAttempts) {
                    statusEl.textContent = 'Väntar på att Oden ska starta... (' + attempts + 's)';
                    setTimeout(poll, 1000);
                } else {
                    statusEl.innerHTML = 'Oden har startat. <a href="/" style="color: #4ade80;">Klicka här</a> för att öppna.';
                }
            };

            // Start polling after a short delay
            setTimeout(poll, 2000);
        }
    </script>
</body>
</html>
"""


def create_app(setup_mode: bool = False) -> web.Application:
    """Create and configure the aiohttp application.

    Args:
        setup_mode: If True, only enable setup-related routes.
    """
    app = web.Application()

    # Setup routes (always available)
    app.router.add_get("/setup", setup_handler)
    app.router.add_get("/api/setup/status", setup_status_handler)
    app.router.add_post("/api/setup/start-link", setup_start_link_handler)
    app.router.add_post("/api/setup/cancel-link", setup_cancel_link_handler)
    app.router.add_post("/api/setup/save-config", setup_save_config_handler)

    if setup_mode:
        # In setup mode, redirect root to setup
        async def redirect_to_setup(request):
            raise web.HTTPFound("/setup")

        app.router.add_get("/", redirect_to_setup)
    else:
        # Normal mode routes
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
        app.router.add_post("/api/config-save", config_save_handler)

    return app


async def start_web_server(port: int = 8080, setup_mode: bool = False) -> web.AppRunner:
    """Start the web server on the specified port.

    Args:
        port: Port to listen on (default 8080).
        setup_mode: If True, only enable setup-related routes.

    Returns:
        The AppRunner instance (for cleanup).
    """
    app = create_app(setup_mode=setup_mode)

    # Configure access logger to write to file instead of terminal
    access_log: logging.Logger | None = None
    if WEB_ACCESS_LOG and not setup_mode:
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
    mode_str = " (setup mode)" if setup_mode else ""
    logger.info(f"Web GUI started at http://127.0.0.1:{port}{mode_str}")
    return runner


async def run_web_server(port: int = 8080, setup_mode: bool = False) -> None:
    """Run the web server indefinitely.

    This function starts the web server and waits forever.
    Use this with asyncio.gather() to run alongside other tasks.

    Args:
        port: Port to listen on.
        setup_mode: If True, only enable setup-related routes.
    """
    runner = await start_web_server(port, setup_mode=setup_mode)
    try:
        # Wait forever
        await asyncio.sleep(float("inf"))
    finally:
        await runner.cleanup()


async def run_setup_server(port: int = 8080) -> bool:
    """Run the web server in setup mode until configuration is complete.

    Args:
        port: Port to listen on.

    Returns:
        True if setup completed successfully, False otherwise.
    """
    from oden.config import is_configured

    runner = await start_web_server(port, setup_mode=True)
    try:
        # Poll for configuration completion
        while not is_configured():
            await asyncio.sleep(1.0)
        logger.info("Setup completed, configuration saved.")
        # Wait so the browser can show success message and redirect
        await asyncio.sleep(5.0)
        return True
    finally:
        await runner.cleanup()
