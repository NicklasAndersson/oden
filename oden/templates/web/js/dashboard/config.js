// config.js — Depends on: shared.js (getApiToken, showConfigMsg),
//              regex.js (loadRegexPatterns, collectRegexPatterns),
//              dirty-tracking.js (snapshotConfig, updateDirtyState),
//              groups.js (fetchGroups)
//
// Loads and saves the main configuration form, plus reset/export/shutdown.

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

        // Signal confirmations
        document.getElementById('cfg-auto-reaction').checked = config.auto_reaction_enabled || false;
        document.getElementById('cfg-auto-reaction-emoji').value = config.auto_reaction_emoji || '✅';
        document.getElementById('cfg-auto-read-receipt').checked = config.auto_read_receipt_enabled || false;

        // Regex patterns
        loadRegexPatterns(config.regex_patterns || {});

        // Snapshot values so we can detect changes
        snapshotConfig();
        updateDirtyState();
    } catch (error) {
        console.error('Error loading config:', error);
    }
}

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
        log_level: document.getElementById('cfg-log-level').value,
        auto_reaction_enabled: document.getElementById('cfg-auto-reaction').checked,
        auto_reaction_emoji: document.getElementById('cfg-auto-reaction-emoji').value || '✅',
        auto_read_receipt_enabled: document.getElementById('cfg-auto-read-receipt').checked,
        regex_patterns: collectRegexPatterns()
    };

    try {
        const response = await authenticatedFetch('/api/config-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('✓ Inställningar sparade och applicerade!', 'success');
            await loadConfigForm();
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

async function rerunSetup() {
    if (!confirm('Är du säker? Detta startar om Oden i setup-läge. Befintlig konfiguration behålls tills du sparar ny.')) {
        return;
    }
    try {
        const response = await authenticatedFetch('/api/setup/reset', {
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
        const response = await authenticatedFetch('/api/signal-config');
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
        const response = await authenticatedFetch('/api/signal-config', {
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
        const response = await authenticatedFetch('/api/shutdown', {
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
