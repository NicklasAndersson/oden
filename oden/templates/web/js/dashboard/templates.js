// templates.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMsg)
//
// Jinja2 template editor with live preview, save/reset, and export.

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
