// auto-save.js — Depends on: shared.js (showConfigMessage),
//                 config.js (loadConfigForm),
//                 groups.js (fetchGroups)
//
// Debounced auto-save: saves config automatically when the user changes a field.

let _autoSaveTimer = null;
let _autoSaveInFlight = false;
let _autoSavePending = false;

function autoSaveConfig() {
    clearTimeout(_autoSaveTimer);
    _autoSaveTimer = setTimeout(_doAutoSave, 800);
}

async function _doAutoSave() {
    if (_autoSaveInFlight) {
        _autoSavePending = true;
        return;
    }
    _autoSaveInFlight = true;

    const configData = {
        signal_number: document.getElementById('cfg-signal-number').value,
        display_name: document.getElementById('cfg-display-name').value,
        vault_path: document.getElementById('cfg-vault-path').value,
        timezone: document.getElementById('cfg-timezone').value,
        append_window_minutes: parseInt(document.getElementById('cfg-append-window').value) || 30,
        startup_message: document.getElementById('cfg-startup-message').value,
        signal_cli_host: document.getElementById('cfg-signal-host').value,
        signal_cli_port: parseInt(document.getElementById('cfg-signal-port').value) || 7583,
        signal_cli_path: document.getElementById('cfg-signal-path').value || null,
        unmanaged_signal_cli: document.getElementById('cfg-unmanaged').checked,
        log_level: document.getElementById('cfg-log-level').value,
        diagnostic_mode: document.getElementById('cfg-diagnostic-mode').checked,
        raw_message_retention_days: parseInt(document.getElementById('cfg-raw-retention-days').value) || 30
    };

    try {
        const response = await fetch('/api/config-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('✓ Sparad', 'success');
            await fetchGroups();
        } else {
            showConfigMessage(result.error || 'Kunde inte spara', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    } finally {
        _autoSaveInFlight = false;
        if (_autoSavePending) {
            _autoSavePending = false;
            autoSaveConfig();
        }
    }
}
