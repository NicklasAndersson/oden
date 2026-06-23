// templates.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Jinja2 template editor with live preview, save/reset, and export.

function getTemplateModal() {
    return document.getElementById('template-editor-modal');
}

function isTemplateModalOpen() {
    const modal = getTemplateModal();
    return modal && !modal.classList.contains('hidden');
}

function getActiveTemplateEditor() {
    if (isTemplateModalOpen()) {
        return document.getElementById('template-editor-large');
    }
    return document.getElementById('template-editor');
}

function setTemplateContent(content) {
    document.getElementById('template-editor').value = content;

    const largeEditor = document.getElementById('template-editor-large');
    if (largeEditor) {
        largeEditor.value = content;
    }
}

function setTemplatePreview(preview) {
    const previewDiv = document.getElementById('template-preview');
    previewDiv.textContent = preview;

    const largePreviewDiv = document.getElementById('template-preview-large');
    if (largePreviewDiv) {
        largePreviewDiv.textContent = preview;
    }
}

function setTemplateEmptyPreview(message) {
    const html = '<div class="empty-state">' + escapeHtml(message) + '</div>';
    document.getElementById('template-preview').innerHTML = html;

    const largePreviewDiv = document.getElementById('template-preview-large');
    if (largePreviewDiv) {
        largePreviewDiv.innerHTML = html;
    }
}

function setTemplateError(message) {
    const errorDiv = document.getElementById('template-error');
    const largeErrorDiv = document.getElementById('template-error-large');

    if (message) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        if (largeErrorDiv) {
            largeErrorDiv.textContent = message;
            largeErrorDiv.style.display = 'block';
        }
        return;
    }

    errorDiv.style.display = 'none';
    if (largeErrorDiv) {
        largeErrorDiv.style.display = 'none';
    }
}

function syncTemplateContentFromActiveEditor() {
    const editor = getActiveTemplateEditor();
    setTemplateContent(editor.value);
    return editor.value;
}

function openTemplateEditorModal() {
    const modal = getTemplateModal();
    setTemplateContent(document.getElementById('template-editor').value);

    const previewDiv = document.getElementById('template-preview');
    const largePreviewDiv = document.getElementById('template-preview-large');
    if (largePreviewDiv) {
        largePreviewDiv.innerHTML = previewDiv.innerHTML;
    }

    setTemplateError('');
    modal.classList.remove('hidden');
    document.getElementById('template-editor-large').focus();
}

function closeTemplateEditorModal(event) {
    if (event && event.target && event.target !== getTemplateModal()) {
        return;
    }

    syncTemplateContentFromActiveEditor();
    setTemplateError('');
    getTemplateModal().classList.add('hidden');
}

async function loadTemplate() {
    const templateName = document.getElementById('template-select').value;
    const variablesContainer = document.getElementById('template-variables');

    setTemplateError('');

    try {
        const response = await fetch(`/api/templates/${templateName}`);
        const data = await response.json();

        if (response.ok) {
            setTemplateContent(data.content);

            // Display variables
            if (data.variables && data.variables.length > 0) {
                variablesContainer.innerHTML = data.variables.map(function(v) {
                    var brOpen = '{' + '{';
                    var brClose = '}' + '}';
                    var req = v.required ? '<span class="template-var-required">*</span>' : '';
                    return '<div class="template-var-item">'
                        + '<span class="template-var-name">' + brOpen + ' ' + escapeHtml(v.name) + ' ' + brClose + '</span>'
                        + req
                        + '<div class="template-var-desc">' + escapeHtml(v.description) + '</div>'
                        + '</div>';
                }).join('');
            }

            // Auto-preview
            await previewTemplate();
        } else {
            setTemplateError(data.error || 'Kunde inte ladda mall');
        }
    } catch (error) {
        setTemplateError('Nätverksfel: ' + error.message);
    }
}

async function previewTemplate() {
    const templateName = document.getElementById('template-select').value;
    const content = syncTemplateContentFromActiveEditor();
    const useFullData = document.getElementById('template-full-data').checked;

    setTemplateError('');

    if (!content.trim()) {
        setTemplateEmptyPreview('Ingen mall att förhandsgranska');
        return;
    }

    try {
        const response = await fetch(`/api/templates/${templateName}/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, full: useFullData })
        });
        const data = await response.json();

        if (data.success) {
            setTemplatePreview(data.preview);
        } else {
            setTemplateError(data.error || 'Förhandsvisning misslyckades');
            setTemplateEmptyPreview('Fel i mallen - se felmeddelande ovan');
        }
    } catch (error) {
        setTemplateError('Nätverksfel: ' + error.message);
    }
}

async function saveTemplate() {
    const templateName = document.getElementById('template-select').value;
    const content = syncTemplateContentFromActiveEditor();

    setTemplateError('');

    if (!content.trim()) {
        setTemplateError('Mallinnehåll kan inte vara tomt');
        return;
    }

    try {
        const response = await fetch(`/api/templates/${templateName}`, {
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
            setTemplateError(data.error || 'Kunde inte spara mall');
        }
    } catch (error) {
        setTemplateError('Nätverksfel: ' + error.message);
    }
}

async function resetTemplate() {
    const templateName = document.getElementById('template-select').value;

    if (!confirm('Är du säker på att du vill återställa mallen till standardvärdet? Dina ändringar kommer att försvinna.')) {
        return;
    }

    setTemplateError('');

    try {
        const response = await fetch(`/api/templates/${templateName}/reset`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            setTemplateContent(data.content);
            showConfigMessage('Mall återställd till standard!', 'success');
            await previewTemplate();
        } else {
            setTemplateError(data.error || 'Kunde inte återställa mall');
        }
    } catch (error) {
        setTemplateError('Nätverksfel: ' + error.message);
    }
}

function exportCurrentTemplate() {
    const templateName = document.getElementById('template-select').value;
    window.location.href = `/api/templates/${templateName}/export`;
}

function exportAllTemplates() {
    window.location.href = '/api/templates/export';
}
