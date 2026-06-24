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
        document.getElementById('cfg-diagnostic-mode').checked = config.diagnostic_mode || false;
    } catch (error) {
        console.error('Error loading config:', error);
    }
}

async function rerunSetup() {
    if (!confirm('Är du säker? Detta startar om Oden i setup-läge. Befintlig konfiguration behålls tills du sparar ny.')) {
        return;
    }
    try {
        const response = await fetch('/api/setup/reset', {
            method: 'DELETE',
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showConfigMessage('Setup startar om...', 'success');
            setTimeout(() => { window.location.href = '/setup'; }, 1500);
        } else {
            showConfigMessage(data.error || 'Kunde inte starta om setup', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
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
            showMessage('Stänger av Oden...', true);
            document.querySelector('.status-dot').style.background = '#888';
            document.querySelector('.status span').textContent = 'Stänger av...';
        } else {
            showMessage('Kunde inte stänga av: ' + data.error, false);
        }
    } catch (error) {
        showMessage('Fel vid avstängning: ' + error.message, false);
    }
}
