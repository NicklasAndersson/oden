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
        const token = await getApiToken();
        const response = await fetch('/api/join-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
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
        const token = await getApiToken();
        const response = await fetch(`/api/invitations/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
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
        const token = await getApiToken();
        const response = await fetch('/api/toggle-ignore-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
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
        const token = await getApiToken();
        const response = await fetch('/api/toggle-whitelist-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
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
    // Load template when switching to templates tab
    if (tabName === 'templates') {
        loadTemplate();
    }
    // Load responses when switching to responses tab
    if (tabName === 'responses') {
        loadResponses();
    }
}

// ============================================================
// Response (auto-reply) management
// ============================================================

async function loadResponses() {
    const container = document.getElementById('responses-list');
    try {
        const response = await fetch('/api/responses');
        const data = await response.json();

        if (!data.length) {
            container.innerHTML = '<div class="empty-state">Inga svar konfigurerade. Klicka "Nytt svar" för att lägga till.</div>';
            return;
        }

        let html = '<table style="width:100%; border-collapse:collapse;">';
        html += '<thead><tr style="border-bottom:1px solid #333;">';
        html += '<th style="text-align:left; padding:8px; color:#888;">Nyckelord</th>';
        html += '<th style="text-align:left; padding:8px; color:#888;">Förhandsvisning</th>';
        html += '<th style="text-align:right; padding:8px; color:#888;">Åtgärder</th>';
        html += '</tr></thead><tbody>';

        data.forEach(r => {
            const keywords = r.keywords.map(k => '<code style="background:#1a2744; padding:2px 6px; border-radius:3px; margin-right:4px; color:#4fc3f7;">#' + k + '</code>').join(' ');
            const preview = r.body.length > 80 ? r.body.substring(0, 80) + '…' : r.body;
            html += '<tr style="border-bottom:1px solid #222;">';
            html += '<td style="padding:8px;">' + keywords + '</td>';
            html += '<td style="padding:8px; color:#aaa; font-size:0.9em;">' + preview.replace(/</g, '&lt;') + '</td>';
            html += '<td style="padding:8px; text-align:right; white-space:nowrap;">';
            html += '<button class="btn btn-secondary" style="padding:4px 10px; font-size:0.85em; margin-left:4px;" onclick="editResponse(' + r.id + ')">✏️ Redigera</button>';
            html += '<button class="btn btn-secondary" style="padding:4px 10px; font-size:0.85em; margin-left:4px; color:#ff6b6b;" onclick="deleteResponse(' + r.id + ')">🗑️ Ta bort</button>';
            html += '</td></tr>';
        });

        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (error) {
        container.innerHTML = '<div class="empty-state" style="color:#ff6b6b;">Kunde inte ladda svar: ' + error.message + '</div>';
    }
}

function newResponse() {
    document.getElementById('response-edit-id').value = '';
    document.getElementById('response-keywords').value = '';
    document.getElementById('response-body').value = '';
    document.getElementById('response-editor-title').textContent = 'Nytt svar';
    document.getElementById('response-editor').style.display = 'block';
}

async function editResponse(id) {
    try {
        const token = await getApiToken();
        const response = await fetch('/api/responses/' + id + '?token=' + token);
        const data = await response.json();

        if (!response.ok) {
            alert(data.error || 'Kunde inte hämta svar');
            return;
        }

        document.getElementById('response-edit-id').value = data.id;
        document.getElementById('response-keywords').value = data.keywords.join(', ');
        document.getElementById('response-body').value = data.body;
        document.getElementById('response-editor-title').textContent = 'Redigera svar #' + data.keywords[0];
        document.getElementById('response-editor').style.display = 'block';
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function saveResponse() {
    const id = document.getElementById('response-edit-id').value;
    const keywordsStr = document.getElementById('response-keywords').value;
    const body = document.getElementById('response-body').value;

    const keywords = keywordsStr.split(',').map(k => k.trim()).filter(k => k);

    if (!keywords.length) {
        alert('Ange minst ett nyckelord.');
        return;
    }
    if (!body.trim()) {
        alert('Svarstext kan inte vara tom.');
        return;
    }

    try {
        const token = await getApiToken();
        const url = id ? '/api/responses/' + id + '?token=' + token : '/api/responses/new?token=' + token;
        const response = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({keywords, body})
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage(result.message, 'success');
            cancelResponseEdit();
            await loadResponses();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function deleteResponse(id) {
    if (!confirm('Vill du verkligen ta bort detta svar?')) return;

    try {
        const token = await getApiToken();
        const response = await fetch('/api/responses/' + id + '?token=' + token, {
            method: 'DELETE'
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage(result.message, 'success');
            await loadResponses();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

function cancelResponseEdit() {
    document.getElementById('response-editor').style.display = 'none';
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
        const token = await getApiToken();
        const response = await fetch('/api/config-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
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
        const token = await getApiToken();
        const response = await fetch('/api/config-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ content, reload: true })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('✓ Config importerad och applicerad!', 'success');
            await fetchConfig();
            await fetchGroups();
            await loadConfigForm();
        } else {
            showConfigMessage(result.error || 'Kunde inte importera config', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
}

// Export config as downloadable INI file
async function exportConfig() {
    try {
        const response = await fetch('/api/config/export');
        if (!response.ok) {
            throw new Error('Kunde inte exportera config');
        }
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'oden-config.ini';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
        showConfigMessage('✓ Config nedladdad!', 'success');
    } catch (error) {
        showConfigMessage('Fel vid export: ' + error.message, 'error');
    }
}

// Shutdown the application
async function shutdownApp() {
    if (!confirm('Är du säker på att du vill stänga av Oden?')) {
        return;
    }
    try {
        const token = await getApiToken();
        const response = await fetch('/api/shutdown', { 
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token }
        });
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

// ========== Template Editor Functions ==========

// Store API token for template operations
let apiToken = null;

async function getApiToken() {
    if (!apiToken) {
        try {
            const response = await fetch('/api/token');
            const data = await response.json();
            apiToken = data.token;
        } catch (error) {
            console.error('Failed to get API token:', error);
        }
    }
    return apiToken;
}

async function loadTemplate() {
    const templateName = document.getElementById('template-select').value;
    const editor = document.getElementById('template-editor');
    const variablesContainer = document.getElementById('template-variables');
    const errorDiv = document.getElementById('template-error');

    errorDiv.style.display = 'none';

    try {
        const token = await getApiToken();
        const response = await fetch(`/api/templates/${templateName}?token=${token}`);
        const data = await response.json();

        if (response.ok) {
            editor.value = data.content;

            // Display variables
            if (data.variables && data.variables.length > 0) {
                variablesContainer.innerHTML = data.variables.map(v => `
                    <div class="template-var-item">
                        <span class="template-var-name">${'{{'} ${v.name} ${'}}'}</span>
                        ${v.required ? '<span class="template-var-required">*</span>' : ''}
                        <div class="template-var-desc">${escapeHtml(v.description)}</div>
                    </div>
                `).join('');
            }

            // Auto-preview
            await previewTemplate();
        } else {
            errorDiv.textContent = data.error || 'Kunde inte ladda mall';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        errorDiv.textContent = 'Nätverksfel: ' + error.message;
        errorDiv.style.display = 'block';
    }
}

async function previewTemplate() {
    const templateName = document.getElementById('template-select').value;
    const content = document.getElementById('template-editor').value;
    const previewDiv = document.getElementById('template-preview');
    const errorDiv = document.getElementById('template-error');
    const useFullData = document.getElementById('template-full-data').checked;

    errorDiv.style.display = 'none';

    if (!content.trim()) {
        previewDiv.innerHTML = '<div class="empty-state">Ingen mall att förhandsgranska</div>';
        return;
    }

    try {
        const token = await getApiToken();
        const response = await fetch(`/api/templates/${templateName}/preview?token=${token}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, full: useFullData })
        });
        const data = await response.json();

        if (data.success) {
            previewDiv.textContent = data.preview;
        } else {
            errorDiv.textContent = data.error || 'Förhandsvisning misslyckades';
            errorDiv.style.display = 'block';
            previewDiv.innerHTML = '<div class="empty-state">Fel i mallen - se felmeddelande ovan</div>';
        }
    } catch (error) {
        errorDiv.textContent = 'Nätverksfel: ' + error.message;
        errorDiv.style.display = 'block';
    }
}

async function saveTemplate() {
    const templateName = document.getElementById('template-select').value;
    const content = document.getElementById('template-editor').value;
    const errorDiv = document.getElementById('template-error');

    errorDiv.style.display = 'none';

    if (!content.trim()) {
        errorDiv.textContent = 'Mallinnehåll kan inte vara tomt';
        errorDiv.style.display = 'block';
        return;
    }

    try {
        const token = await getApiToken();
        const response = await fetch(`/api/templates/${templateName}?token=${token}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await response.json();

        if (data.success) {
            let message = 'Mall sparad!';
            if (data.warning) {
                message += ' ' + data.warning;
                showConfigMessage(message, 'warning');
            } else {
                showConfigMessage(message, 'success');
            }
        } else {
            errorDiv.textContent = data.error || 'Kunde inte spara mall';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        errorDiv.textContent = 'Nätverksfel: ' + error.message;
        errorDiv.style.display = 'block';
    }
}

async function resetTemplate() {
    const templateName = document.getElementById('template-select').value;
    const errorDiv = document.getElementById('template-error');

    if (!confirm('Är du säker på att du vill återställa mallen till standardvärdet? Dina ändringar kommer att försvinna.')) {
        return;
    }

    errorDiv.style.display = 'none';

    try {
        const token = await getApiToken();
        const response = await fetch(`/api/templates/${templateName}/reset?token=${token}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            document.getElementById('template-editor').value = data.content;
            showConfigMessage('Mall återställd till standard!', 'success');
            await previewTemplate();
        } else {
            errorDiv.textContent = data.error || 'Kunde inte återställa mall';
            errorDiv.style.display = 'block';
        }
    } catch (error) {
        errorDiv.textContent = 'Nätverksfel: ' + error.message;
        errorDiv.style.display = 'block';
    }
}

async function exportCurrentTemplate() {
    const templateName = document.getElementById('template-select').value;
    const token = await getApiToken();
    window.location.href = `/api/templates/${templateName}/export?token=${token}`;
}

async function exportAllTemplates() {
    const token = await getApiToken();
    window.location.href = `/api/templates/export?token=${token}`;
}
