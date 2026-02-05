"""
HTML templates for the Oden web interface.

This module contains the HTML templates used by the web server.
Separating templates from handler logic improves code organization
and makes the templates easier to maintain.
"""

# HTML template for the main web interface
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
        .header-actions {
            display: flex;
            align-items: center;
            gap: 20px;
        }
        .status {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .btn-danger {
            background: #dc3545;
            border-color: #dc3545;
        }
        .btn-danger:hover {
            background: #c82333;
            border-color: #bd2130;
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
        .group-buttons {
            display: flex;
            gap: 5px;
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
        .toggle-whitelist {
            padding: 4px 10px;
            font-size: 0.8em;
            border-radius: 3px;
            cursor: pointer;
            border: 1px solid #555;
            background: transparent;
            color: #888;
            transition: all 0.2s;
            margin-left: 5px;
        }
        .toggle-whitelist:hover {
            border-color: #4fc3f7;
            color: #4fc3f7;
        }
        .toggle-whitelist.whitelisted {
            border-color: #4caf50;
            background: rgba(76, 175, 80, 0.2);
            color: #4caf50;
        }
        .toggle-whitelist.whitelisted:hover {
            background: rgba(76, 175, 80, 0.3);
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
            <div class="header-actions">
                <div class="status">
                    <div class="status-dot"></div>
                    <span>Lyssnar</span>
                </div>
                <button class="btn btn-danger" onclick="shutdownApp()" title="Stäng av Oden">
                    ⏻ Stäng av
                </button>
            </div>
        </header>

        <div class="grid">
            <div class="card full-width">
                <h2>👥 Grupper</h2>
                <div id="groups-container" class="group-list">
                    <div class="empty-state">Laddar grupper...</div>
                </div>
                <div class="refresh-info">Klicka på "Ignorera" för att dölja gruppen, eller "Whitelist" för att endast tillåta den. Om whitelist är satt ignoreras alla andra grupper.</div>
            </div>

            <div class="card full-width">
                <h2>🔗 Gå med i grupp</h2>
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
                                    <label for="cfg-filename-format">Filnamnsformat</label>
                                    <select id="cfg-filename-format" name="filename_format">
                                        <option value="classic">Classic (DDHHMM-telefon-namn.md)</option>
                                        <option value="tnr">TNR (DDHHMM.md)</option>
                                        <option value="tnr-name">TNR-namn (DDHHMM-namn.md)</option>
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
                                <div class="config-field full-width">
                                    <label for="cfg-whitelist-groups">Whitelist-grupper (kommaseparerade)</label>
                                    <input type="text" id="cfg-whitelist-groups" name="whitelist_groups" placeholder="Grupp1, Grupp2">
                                    <span class="help-text">Om satt sparas ENDAST meddelanden från dessa grupper (har prioritet över ignorerade)</span>
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
        let currentWhitelistGroups = [];

        async function fetchGroups() {
            try {
                const response = await fetch('/api/groups');
                const data = await response.json();
                const container = document.getElementById('groups-container');
                currentIgnoredGroups = data.ignoredGroups || [];
                currentWhitelistGroups = data.whitelistGroups || [];

                if (!data.groups || data.groups.length === 0) {
                    container.innerHTML = '<div class="empty-state">Inga grupper hittades</div>';
                    return;
                }

                container.innerHTML = data.groups.map(group => {
                    const isIgnored = currentIgnoredGroups.includes(group.name);
                    const isWhitelisted = currentWhitelistGroups.includes(group.name);
                    return `
                        <div class="group-item ${isIgnored ? 'ignored' : ''} ${isWhitelisted ? 'whitelisted' : ''}" data-group-name="${escapeHtml(group.name)}">
                            <div class="group-info">
                                <div class="group-name">${escapeHtml(group.name)}</div>
                                <div class="group-meta">${group.memberCount} medlemmar</div>
                            </div>
                            <div class="group-buttons">
                                <button class="toggle-ignore ${isIgnored ? 'ignored' : ''}"
                                        onclick="toggleIgnoreGroup('${escapeHtml(group.name)}')"
                                        title="${isIgnored ? 'Sluta ignorera' : 'Ignorera grupp'}">
                                    ${isIgnored ? '✓ Ignorerad' : 'Ignorera'}
                                </button>
                                <button class="toggle-whitelist ${isWhitelisted ? 'whitelisted' : ''}"
                                        onclick="toggleWhitelistGroup('${escapeHtml(group.name)}')"
                                        title="${isWhitelisted ? 'Ta bort från whitelist' : 'Lägg till i whitelist'}">
                                    ${isWhitelisted ? '✓ Whitelist' : 'Whitelist'}
                                </button>
                            </div>
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

        async function toggleWhitelistGroup(groupName) {
            try {
                const response = await fetch('/api/toggle-whitelist-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ groupName })
                });
                const result = await response.json();

                if (response.ok && result.success) {
                    showConfigMessage('Whitelist uppdaterad! Ändringen appliceras direkt.', 'success');
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
                document.getElementById('cfg-filename-format').value = config.filename_format || 'classic';
                document.getElementById('cfg-plus-plus').checked = config.plus_plus_enabled || false;
                document.getElementById('cfg-ignored-groups').value = (config.ignored_groups || []).join(', ');
                document.getElementById('cfg-whitelist-groups').value = (config.whitelist_groups || []).join(', ');

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
                filename_format: document.getElementById('cfg-filename-format').value,
                plus_plus_enabled: document.getElementById('cfg-plus-plus').checked,
                ignored_groups: document.getElementById('cfg-ignored-groups').value
                    .split(',').map(s => s.trim()).filter(s => s),
                whitelist_groups: document.getElementById('cfg-whitelist-groups').value
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

        // Shutdown the application
        async function shutdownApp() {
            if (!confirm('Är du säker på att du vill stänga av Oden?')) {
                return;
            }
            try {
                const response = await fetch('/api/shutdown', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showMessage('Stänger av Oden...', true);
                    // Update UI to show shutdown state
                    document.querySelector('.status-dot').style.background = '#888';
                    document.querySelector('.status span').textContent = 'Stänger av...';
                } else {
                    showMessage('Kunde inte stänga av: ' + data.error, false);
                }
            } catch (error) {
                showMessage('Fel vid avstängning: ' + error.message, false);
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
            <div class="form-group" style="margin-top: 20px;">
                <label style="display: flex; align-items: center; gap: 10px; cursor: pointer;">
                    <input type="checkbox" id="install-obsidian" checked style="width: 20px; height: 20px;">
                    <span>Installera Obsidian-inställningar (Map View plugin)</span>
                </label>
                <p style="color: #666; font-size: 0.85em; margin-top: 5px; margin-left: 30px;">
                    Rekommenderas för att visa platser på karta i Obsidian.
                </p>
            </div>
            <button class="btn btn-primary" onclick="goToStep(2)">Nästa →</button>
        </div>

        <!-- Step 2: Signal Linking -->
        <div class="step" id="step-2">
            <h2 style="margin-bottom: 20px;">📱 Signal-konto</h2>

            <!-- Loading indicator -->
            <div id="accounts-loading" style="text-align: center; padding: 40px;">
                <div class="spinner"></div>
                <p style="color: #888; margin-top: 15px;">Letar efter befintliga Signal-konton...</p>
            </div>

            <!-- Existing accounts section -->
            <div id="existing-accounts" class="hidden">
                <div style="background: #1a3a1a; border: 1px solid #2d5a2d; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #4ade80;">✓ Befintliga Signal-konton hittades</h3>
                    <p style="color: #888; margin-bottom: 15px;">Du har redan konfigurerade Signal-konton. Välj ett att använda eller konfigurera nytt.</p>
                    <div id="accounts-list"></div>
                </div>
            </div>

            <!-- Method selection -->
            <div id="method-selection" class="hidden">
                <p style="color: #888; margin-bottom: 15px;">Välj hur du vill konfigurera Signal:</p>
                <div style="display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px;">
                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer; padding: 12px; background: #0d1421; border-radius: 6px; border: 1px solid #333;">
                        <input type="radio" name="setup-method" value="link" checked style="width: 18px; height: 18px;">
                        <div>
                            <strong style="color: #4fc3f7;">Länka befintligt konto</strong>
                            <p style="color: #888; font-size: 0.85em; margin: 4px 0 0 0;">Använd QR-kod för att länka till din Signal-app</p>
                        </div>
                    </label>
                    <label style="display: flex; align-items: center; gap: 10px; cursor: pointer; padding: 12px; background: #0d1421; border-radius: 6px; border: 1px solid #333;">
                        <input type="radio" name="setup-method" value="register" style="width: 18px; height: 18px;">
                        <div>
                            <strong style="color: #ffb74d;">Registrera nytt nummer</strong>
                            <p style="color: #888; font-size: 0.85em; margin: 4px 0 0 0;">⚠️ Använd INTE ditt huvudnummer!</p>
                        </div>
                    </label>
                </div>
                <button class="btn btn-primary" onclick="startSelectedMethod()">Fortsätt</button>
                <button class="btn btn-secondary" onclick="goToStep(1)">← Tillbaka</button>
            </div>

            <!-- Link form -->
            <div id="link-start" class="hidden">
                <p style="color: #888; margin-bottom: 20px;">
                    Klicka på knappen nedan för att starta länkningen. En QR-kod visas som du scannar med Signal-appen.
                </p>
                <div class="form-group">
                    <label for="device-name">Enhetsnamn</label>
                    <input type="text" id="device-name" value="Oden" placeholder="Oden">
                </div>
                <button class="btn btn-primary" onclick="startLinking()">Länka konto</button>
                <button class="btn btn-secondary" onclick="showMethodSelection()">← Tillbaka</button>
            </div>

            <!-- Registration form -->
            <div id="register-start" class="hidden">
                <div style="background: #3a2a1a; border: 1px solid #5a4a2a; border-radius: 6px; padding: 12px; margin-bottom: 20px;">
                    <strong style="color: #ffb74d;">⚠️ Varning</strong>
                    <p style="color: #888; font-size: 0.9em; margin: 5px 0 0 0;">
                        Använd ett separat telefonnummer, INTE ditt huvudnummer på Signal!
                    </p>
                </div>
                <div class="form-group">
                    <label for="register-phone">Telefonnummer</label>
                    <input type="text" id="register-phone" placeholder="+46701234567">
                </div>
                <div class="form-group">
                    <label style="color: #888;">Verifieringsmetod</label>
                    <div style="display: flex; gap: 15px; margin-top: 8px;">
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                            <input type="radio" name="verify-method" value="sms" checked>
                            <span>SMS</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                            <input type="radio" name="verify-method" value="voice">
                            <span>Samtal</span>
                        </label>
                    </div>
                </div>
                <button class="btn btn-primary" onclick="startRegistration()">Registrera</button>
                <button class="btn btn-secondary" onclick="showMethodSelection()">← Tillbaka</button>
            </div>

            <!-- CAPTCHA required -->
            <div id="register-captcha" class="hidden">
                <div style="background: #2a2a3a; border: 1px solid #4a4a5a; border-radius: 6px; padding: 15px; margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #ffb74d;">🔒 CAPTCHA krävs</h3>
                    <ol style="color: #aaa; margin: 0; padding-left: 20px; line-height: 1.8;">
                        <li>Öppna länken nedan i din webbläsare</li>
                        <li>Lös CAPTCHA-uppgiften</li>
                        <li>Högerklicka på "Open Signal" och <strong>kopiera länkadressen</strong></li>
                        <li>Klistra in länken nedan</li>
                    </ol>
                </div>
                <a href="https://signalcaptchas.org/registration/generate.html" target="_blank"
                   style="display: block; background: #0d1421; padding: 12px; border-radius: 6px; margin-bottom: 15px; color: #4fc3f7; text-decoration: none; word-break: break-all;">
                    https://signalcaptchas.org/registration/generate.html ↗
                </a>
                <div class="form-group">
                    <label for="captcha-token">Klistra in signalcaptcha:// länken</label>
                    <input type="text" id="captcha-token" placeholder="signalcaptcha://signal-recaptcha-v2...">
                </div>
                <button class="btn btn-primary" onclick="submitCaptcha()">Fortsätt</button>
                <button class="btn btn-secondary" onclick="showMethodSelection()">Avbryt</button>
            </div>

            <!-- Verification code -->
            <div id="register-verify" class="hidden">
                <div class="success" style="margin-bottom: 20px;">
                    📱 Verifieringskod skickad!
                </div>
                <p style="color: #888; margin-bottom: 20px;">
                    Ange koden du fick via <span id="verify-method-text">SMS</span> till <strong id="verify-phone-text"></strong>
                </p>
                <div class="form-group">
                    <label for="verify-code">Verifieringskod</label>
                    <input type="text" id="verify-code" placeholder="123456" maxlength="10" style="font-size: 1.5em; text-align: center; letter-spacing: 5px;">
                </div>
                <button class="btn btn-primary" onclick="submitVerifyCode()">Verifiera</button>
                <button class="btn btn-secondary" onclick="showMethodSelection()">Avbryt</button>
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
        let registerPhone = null;

        // Set default vault path on page load (quick, no signal-cli needed)
        fetch('/api/setup/status')
            .then(r => r.json())
            .then(data => {
                document.getElementById('vault-path').value = data.default_vault || '~/oden-vault';
            });

        function hideAllStep2Sections() {
            ['accounts-loading', 'existing-accounts', 'method-selection', 'link-start',
             'link-waiting', 'link-success', 'link-timeout', 'link-error',
             'register-start', 'register-captcha', 'register-verify'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.add('hidden');
            });
        }

        function showMethodSelection() {
            hideAllStep2Sections();
            document.getElementById('method-selection').classList.remove('hidden');
            if (existingAccounts.length > 0) {
                document.getElementById('existing-accounts').classList.remove('hidden');
            }
        }

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
            hideAllStep2Sections();
            document.getElementById('link-success').classList.remove('hidden');
            document.getElementById('linked-number').textContent = number;
        }

        async function loadExistingAccounts() {
            hideAllStep2Sections();
            document.getElementById('accounts-loading').classList.remove('hidden');

            try {
                const response = await fetch('/api/setup/status?accounts=true');
                const data = await response.json();

                document.getElementById('accounts-loading').classList.add('hidden');

                if (data.existing_accounts && data.existing_accounts.length > 0) {
                    existingAccounts = data.existing_accounts;
                    showExistingAccounts(data.existing_accounts);
                }

                document.getElementById('method-selection').classList.remove('hidden');

            } catch (error) {
                document.getElementById('accounts-loading').classList.add('hidden');
                document.getElementById('method-selection').classList.remove('hidden');
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
                loadExistingAccounts();
            }

            if (step === 3) {
                document.getElementById('confirm-vault').textContent = document.getElementById('vault-path').value;
                document.getElementById('confirm-number').textContent = linkedNumber || '(ej konfigurerad)';
                document.getElementById('confirm-device').textContent = document.getElementById('device-name')?.value || 'Oden';
            }
        }

        function startSelectedMethod() {
            const method = document.querySelector('input[name="setup-method"]:checked').value;
            hideAllStep2Sections();
            if (method === 'link') {
                document.getElementById('link-start').classList.remove('hidden');
            } else {
                document.getElementById('register-start').classList.remove('hidden');
            }
        }

        async function startLinking() {
            const deviceName = document.getElementById('device-name').value || 'Oden';

            hideAllStep2Sections();
            document.getElementById('link-waiting').classList.remove('hidden');

            try {
                const response = await fetch('/api/setup/start-link', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_name: deviceName })
                });
                const data = await response.json();

                if (data.success && data.qr_svg) {
                    const container = document.getElementById('qr-container');
                    container.innerHTML = data.qr_svg;
                    const svg = container.querySelector('svg');
                    if (svg) {
                        svg.style.width = '250px';
                        svg.style.height = '250px';
                    }

                    let seconds = 60;
                    const countdownEl = document.getElementById('countdown');
                    countdownInterval = setInterval(() => {
                        seconds--;
                        countdownEl.textContent = 'Väntar på scan... ' + seconds + 's';
                        if (seconds <= 15) countdownEl.classList.add('warning');
                        if (seconds <= 0) clearInterval(countdownInterval);
                    }, 1000);

                    pollInterval = setInterval(checkLinkStatus, 2000);
                } else {
                    showError(data.error || 'Kunde inte starta länkning');
                }
            } catch (error) {
                showError('Nätverksfel: ' + error.message);
            }
        }

        async function startRegistration() {
            const phone = document.getElementById('register-phone').value.trim();
            const useVoice = document.querySelector('input[name="verify-method"]:checked').value === 'voice';

            if (!phone || !phone.startsWith('+')) {
                alert('Ange ett giltigt telefonnummer (t.ex. +46701234567)');
                return;
            }

            registerPhone = phone;

            hideAllStep2Sections();
            document.getElementById('accounts-loading').classList.remove('hidden');

            try {
                const response = await fetch('/api/setup/start-register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone_number: phone, use_voice: useVoice })
                });
                const data = await response.json();

                document.getElementById('accounts-loading').classList.add('hidden');

                if (data.needs_captcha) {
                    document.getElementById('register-captcha').classList.remove('hidden');
                } else if (data.success) {
                    document.getElementById('verify-phone-text').textContent = phone;
                    document.getElementById('verify-method-text').textContent = useVoice ? 'samtal' : 'SMS';
                    document.getElementById('register-verify').classList.remove('hidden');
                } else {
                    showError(data.error || 'Registrering misslyckades');
                }
            } catch (error) {
                document.getElementById('accounts-loading').classList.add('hidden');
                showError('Nätverksfel: ' + error.message);
            }
        }

        async function submitCaptcha() {
            const token = document.getElementById('captcha-token').value.trim();
            const useVoice = document.querySelector('input[name="verify-method"]:checked').value === 'voice';

            if (!token || !token.startsWith('signalcaptcha://')) {
                alert('Klistra in en giltig signalcaptcha:// länk');
                return;
            }

            hideAllStep2Sections();
            document.getElementById('accounts-loading').classList.remove('hidden');

            try {
                const response = await fetch('/api/setup/start-register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        phone_number: registerPhone,
                        use_voice: useVoice,
                        captcha_token: token
                    })
                });
                const data = await response.json();

                document.getElementById('accounts-loading').classList.add('hidden');

                if (data.success) {
                    document.getElementById('verify-phone-text').textContent = registerPhone;
                    document.getElementById('verify-method-text').textContent = useVoice ? 'samtal' : 'SMS';
                    document.getElementById('register-verify').classList.remove('hidden');
                } else {
                    showError(data.error || 'Registrering misslyckades');
                }
            } catch (error) {
                document.getElementById('accounts-loading').classList.add('hidden');
                showError('Nätverksfel: ' + error.message);
            }
        }

        async function submitVerifyCode() {
            const code = document.getElementById('verify-code').value.trim();

            if (!code || code.length < 4) {
                alert('Ange verifieringskoden');
                return;
            }

            hideAllStep2Sections();
            document.getElementById('accounts-loading').classList.remove('hidden');

            try {
                const response = await fetch('/api/setup/verify-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code })
                });
                const data = await response.json();

                document.getElementById('accounts-loading').classList.add('hidden');

                if (data.success) {
                    linkedNumber = data.phone_number;
                    document.getElementById('linked-number').textContent = linkedNumber;
                    document.getElementById('link-success').classList.remove('hidden');
                } else {
                    showError(data.error || 'Verifiering misslyckades');
                }
            } catch (error) {
                document.getElementById('accounts-loading').classList.add('hidden');
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
                    hideAllStep2Sections();
                    document.getElementById('link-success').classList.remove('hidden');
                } else if (data.status === 'timeout') {
                    clearInterval(countdownInterval);
                    clearInterval(pollInterval);
                    hideAllStep2Sections();
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
            hideAllStep2Sections();
            document.getElementById('link-error').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }

        async function cancelLinking() {
            clearInterval(countdownInterval);
            clearInterval(pollInterval);
            await fetch('/api/setup/cancel-link', { method: 'POST' });
            showMethodSelection();
        }

        function retryLinking() {
            showMethodSelection();
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

            // Install Obsidian template if checkbox is checked
            const installObsidian = document.getElementById('install-obsidian').checked;
            const vaultPath = document.getElementById('vault-path').value;

            if (installObsidian) {
                try {
                    const obsResponse = await fetch('/api/setup/install-obsidian-template', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ vault_path: vaultPath })
                    });
                    const obsData = await obsResponse.json();
                    if (!obsData.success && !obsData.skipped) {
                        console.warn('Obsidian template installation warning:', obsData.error);
                    }
                } catch (e) {
                    console.warn('Obsidian template installation failed:', e);
                }
            }

            try {
                const response = await fetch('/api/setup/save-config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        vault_path: vaultPath,
                        signal_number: linkedNumber,
                        display_name: document.getElementById('device-name')?.value || 'Oden'
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
            const maxAttempts = 30;

            const poll = async () => {
                attempts++;
                try {
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

            setTimeout(poll, 2000);
        }
    </script>
</body>
</html>
"""
