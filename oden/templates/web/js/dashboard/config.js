// config.js — Depends on: shared.js (showConfigMessage, showMessage)
//
// Loads the main configuration form, plus reset/export/shutdown.
// Saving is handled by auto-save.js (debounced on every change).

async function loadConfigForm() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();

        // Basic tab
        document.getElementById('cfg-signal-number').value = config.signal_number || '';
        document.getElementById('cfg-display-name').value = config.display_name || '';
        document.getElementById('cfg-vault-path').value = config.vault_path || '';
        document.getElementById('cfg-group-split-enabled').checked = config.group_split_enabled !== false;
        document.getElementById('cfg-timezone').value = config.timezone || 'Europe/Stockholm';
        document.getElementById('cfg-append-window').value = config.append_window_minutes || 30;
        document.getElementById('cfg-startup-message').value = config.startup_message || 'self';

        // Advanced tab
        document.getElementById('cfg-signal-host').value = config.signal_cli_host || '127.0.0.1';
        document.getElementById('cfg-signal-port').value = config.signal_cli_port || 7583;
        document.getElementById('cfg-signal-path').value = config.signal_cli_path || '';
        document.getElementById('cfg-unmanaged').checked = config.unmanaged_signal_cli || false;
        document.getElementById('cfg-log-level').value = config.log_level || 'INFO';
        document.getElementById('cfg-raw-retention-days').value = config.raw_message_retention_days || 30;
        document.getElementById('cfg-raw-max-mb').value = config.raw_message_max_mb || 0;
        document.getElementById('cfg-diagnostic-mode').checked = config.diagnostic_mode || false;
    } catch (error) {
        console.error('Error loading config:', error);
    }
}

let versionMismatchWarned = false;

async function loadSignalCliStatus() {
    const versionNode = document.getElementById('signal-cli-version-status');
    const logNode = document.getElementById('signal-cli-log-monitor-status');
    if (!versionNode || !logNode) {
        return;
    }
    if (!SIGNAL_ENABLED) {
        versionNode.textContent = 'Signal är avstängt.';
        logNode.textContent = 'Signal är avstängt.';
        return;
    }

    try {
        const response = await fetch('/api/signal-cli/status');
        const data = await response.json();

        const expected = data.expected_version || 'okänd';
        const detected = data.detected_version || 'okänd';
        const versionStatus = data.version_status || 'unknown';

        versionNode.classList.remove('warning');
        if (versionStatus === 'mismatch') {
            versionNode.classList.add('warning');
            versionNode.textContent = `Installerad: ${detected}. Förväntad: ${expected}.`;
            if (!versionMismatchWarned) {
                showConfigMessage(`signal-cli-version avviker: installerad ${detected}, förväntad ${expected}.`, 'error');
                versionMismatchWarned = true;
            }
        } else if (versionStatus === 'ok') {
            versionNode.textContent = `Installerad: ${detected}. Förväntad: ${expected}.`; 
        } else {
            versionNode.textContent = `Kunde inte avgöra installerad version. Förväntad: ${expected}.`;
        }

        const monitor = data.log_monitor || {};
        logNode.classList.remove('warning');
        if (monitor.severity === 'warning') {
            logNode.classList.add('warning');
        }
        logNode.textContent = monitor.message || 'Ingen loggstatus tillgänglig.';
    } catch (error) {
        versionNode.classList.remove('warning');
        logNode.classList.remove('warning');
        versionNode.textContent = 'Kunde inte läsa signal-cli-status.';
        logNode.textContent = 'Kunde inte läsa loggövervakningsstatus.';
    }
}

async function loadSignalConfig() {
    try {
        const response = await fetch('/api/signal-config');
        const config = await response.json();

        document.getElementById('cfg-signal-typing-indicators').checked = config.typingIndicators || false;
        document.getElementById('cfg-signal-link-previews').checked = config.linkPreviews || false;
        document.getElementById('cfg-signal-unidentified-delivery').checked = config.unidentifiedDeliveryIndicators || false;
    } catch (error) {
        console.error('Error loading signal config:', error);
    }
}

async function saveSignalConfig() {
    const data = {
        typingIndicators: document.getElementById('cfg-signal-typing-indicators').checked,
        linkPreviews: document.getElementById('cfg-signal-link-previews').checked,
        unidentifiedDeliveryIndicators: document.getElementById('cfg-signal-unidentified-delivery').checked,
    };

    try {
        const response = await fetch('/api/signal-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('Signal-inställningar sparade', 'success');
        } else {
            showConfigMessage(result.error || 'Kunde inte spara Signal-inställningar', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
}

async function shutdownApp() {
    if (!confirm('Är du säker på att du vill stänga av Oden?')) {
        return;
    }
    try {
        const response = await fetch('/api/shutdown', {
            method: 'POST',
        });
        const data = await response.json();
        if (data.success) {
            showConfigMessage('Stänger av Oden...', 'success');
            document.querySelector('.status-dot').style.background = '#888';
            document.querySelector('.status span').textContent = 'Stänger av...';
        } else {
            showConfigMessage('Kunde inte stänga av: ' + data.error, 'error');
        }
    } catch (error) {
        showConfigMessage('Fel vid avstängning: ' + error.message, 'error');
    }
}

async function restartSignalCli() {
    if (!confirm('Är du säker på att du vill starta om signal-cli?')) {
        return;
    }
    try {
        const response = await fetch('/api/signal-cli/restart', {
            method: 'POST',
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showConfigMessage('Startar om signal-cli...', 'success');
            document.querySelector('.status span').textContent = 'Startar om...';
            setTimeout(() => {
                document.querySelector('.status span').textContent = 'Lyssnar';
                loadSignalCliStatus();
            }, 4000);
        } else {
            showConfigMessage(data.error || 'Kunde inte starta om signal-cli', 'error');
        }
    } catch (error) {
        showConfigMessage('Fel vid omstart: ' + error.message, 'error');
    }
}

// ========== Oden-hemkatalog (Avancerat) ==========

async function loadOdenHome() {
    const box = document.getElementById('oden-home-current');
    try {
        const response = await fetch('/api/oden-home');
        const data = await response.json();
        let html = `<span class="mono">${escapeHtml(data.current)}</span>`;
        if (data.locked_by_env) {
            html += '<br>Styrs av miljövariabeln <span class="mono">ODEN_HOME</span> (t.ex. i Docker) och kan inte bytas här.';
        } else if (data.pending) {
            html += `<br>Efter omstart: <span class="mono">${escapeHtml(data.pending)}</span>`;
        }
        box.innerHTML = html;
        document.getElementById('oden-home-change-field').classList.toggle('hidden', data.locked_by_env);
        document.getElementById('oden-home-actions').classList.toggle('hidden', data.locked_by_env);
    } catch (error) {
        box.textContent = 'Kunde inte läsa hemkatalogen';
    }
}

async function changeOdenHome() {
    const path = document.getElementById('oden-home-path').value.trim();
    if (!path) {
        showConfigMessage('Ange en katalog', 'error');
        return;
    }
    if (!confirm(`Byta Odens hemkatalog till ${path}? Det gäller efter omstart.`)) return;
    try {
        const response = await fetch('/api/oden-home', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: path}),
        });
        const data = await response.json();
        showConfigMessage(data.message || data.error, data.success ? 'success' : 'error');
        if (data.success) document.getElementById('oden-home-path').value = '';
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
    loadOdenHome();
}

// ========== Lagring (Avancerat) ==========

function formatBytes(bytes) {
    if (!bytes) return '0 MB';
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} kB`;
    const mb = bytes / (1024 * 1024);
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

async function loadStorageStatus() {
    const box = document.getElementById('storage-status');
    try {
        const response = await fetch('/api/storage');
        const data = await response.json();
        const since = data.oldest ? new Date(data.oldest).toLocaleDateString('sv-SE') : '–';
        const limit = data.max_mb ? ` av max ${data.max_mb} MB` : '';
        const lines = [
            `${data.messages} meddelanden (varav ${data.tak_messages} från TAK) sedan ${escapeHtml(since)}: `
                + `${formatBytes(data.raw_bytes)} rådata${limit}.`,
            `${data.pipeline_runs} pipeline-körningar, ${data.pipeline_events} händelser. `
                + `Databasfilen: ${formatBytes(data.db_file_bytes)}.`,
        ];
        const last = data.last_cleanup;
        if (last && last.at) {
            const when = new Date(last.at).toLocaleString('sv-SE');
            lines.push(`Senaste rensning ${escapeHtml(when)}: ${last.deleted_raw_messages} meddelanden borttagna`
                + (last.deleted_for_size ? ` (${last.deleted_for_size} för storleksgränsen)` : '')
                + (last.vacuumed ? ', filen komprimerad' : '') + '.');
        }
        box.innerHTML = lines.join('<br>');
    } catch (error) {
        box.textContent = 'Kunde inte läsa lagringsstatus';
    }
}

async function runStorageCleanup() {
    try {
        const response = await fetch('/api/storage/cleanup', {method: 'POST'});
        const data = await response.json();
        const s = data.summary || {};
        showConfigMessage(data.success
            ? `Rensat: ${s.deleted_raw_messages || 0} meddelanden, ${s.deleted_pipeline_runs || 0} körningar`
            : (data.error || 'Rensningen misslyckades'), data.success ? 'success' : 'error');
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
    loadStorageStatus();
}
