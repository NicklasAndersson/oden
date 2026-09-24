// pipelines.js — Depends on: shared.js (escapeHtml, showConfigMessage), routing.js (loadRouting)
//
// Pipelines tab, lower half: each pipeline's global settings (used by every
// branch unless the branch's step overrides them) and the report template
// editor. The branches themselves live in routing.js.

let pipelinesState = {
    available: [],
    enabled: [],
    stats: {
        total_processed: 0,
        by_pipeline: {},
    },
};

const genericTemplateVariableCache = {};
const genericTemplateDefaultContentCache = {};
const genericTemplateMeta = {
    report_md: {
        apiName: 'report.md.j2',
        label: 'Rapportmall',
    },
    append_md: {
        apiName: 'append.md.j2',
        label: 'Tilläggsmall',
    },
};

// ponytail: set true while the user is editing a pipeline's settings so the 3s
// auto-refresh poll doesn't re-render the list and wipe unsaved dropdown/textarea
// input. Reset on every full render (tab switch / post-save).
let _pipelineSettingsDirty = false;

function pipelineRunCount(name) {
    return pipelinesState.stats.by_pipeline?.[name] || 0;
}

function getGenericTemplateStorageField(key) {
    return document.getElementById(`pipeline-config-generic_template-${key}`);
}

function getGenericTemplateEditorModal() {
    return document.getElementById('generic-template-editor-modal');
}

function getGenericTemplateEditorKey() {
    return document.getElementById('generic-template-editor-select')?.value || 'report_md';
}

function getGenericTemplateEditorApiName() {
    return genericTemplateMeta[getGenericTemplateEditorKey()]?.apiName || 'report.md.j2';
}

async function getGenericTemplateEditorContent(key) {
    const field = getGenericTemplateStorageField(key);
    const currentContent = field?.value || '';
    if (currentContent.trim()) {
        return currentContent;
    }

    const apiName = genericTemplateMeta[key]?.apiName;
    if (!apiName) {
        return currentContent;
    }

    if (Object.prototype.hasOwnProperty.call(genericTemplateDefaultContentCache, apiName)) {
        const cached = genericTemplateDefaultContentCache[apiName] || '';
        if (field && !field.value.trim()) {
            field.value = cached;
        }
        return cached;
    }

    try {
        const response = await fetch(`/api/templates/${apiName}`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }

        const content = typeof data.content === 'string' ? data.content : '';
        genericTemplateDefaultContentCache[apiName] = content;
        if (field && !field.value.trim()) {
            field.value = content;
        }
        return content;
    } catch (error) {
        setGenericTemplateEditorError(`Kunde inte ladda standardmall: ${error.message}`);
        return currentContent;
    }
}

function setGenericTemplateEditorError(message) {
    const errorDiv = document.getElementById('generic-template-editor-error');
    if (!errorDiv) {
        return;
    }

    if (!message) {
        errorDiv.style.display = 'none';
        return;
    }

    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
}

function setGenericTemplateEditorPreviewText(preview) {
    const previewDiv = document.getElementById('generic-template-editor-preview');
    if (previewDiv) {
        previewDiv.textContent = preview;
    }
}

function setGenericTemplateEditorPreviewEmpty(message) {
    const previewDiv = document.getElementById('generic-template-editor-preview');
    if (previewDiv) {
        previewDiv.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
    }
}

function syncGenericTemplateEditorDraft() {
    const key = getGenericTemplateEditorKey();
    const field = getGenericTemplateStorageField(key);
    const editor = document.getElementById('generic-template-editor-textarea');
    if (field && editor) {
        field.value = editor.value;
    }
}

async function loadGenericTemplateEditorVariables() {
    const templateName = getGenericTemplateEditorApiName();
    const variablesContainer = document.getElementById('generic-template-editor-variables');
    if (!variablesContainer) {
        return;
    }

    if (genericTemplateVariableCache[templateName]) {
        variablesContainer.innerHTML = genericTemplateVariableCache[templateName];
        return;
    }

    try {
        const response = await fetch(`/api/templates/${templateName}`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }

        const html = (data.variables || []).map(function(v) {
            var brOpen = '{' + '{';
            var brClose = '}' + '}';
            var req = v.required ? '<span class="template-var-required">*</span>' : '';
            return '<div class="template-var-item">'
                + '<span class="template-var-name">' + brOpen + ' ' + escapeHtml(v.name) + ' ' + brClose + '</span>'
                + req
                + '<div class="template-var-desc">' + escapeHtml(v.description) + '</div>'
                + '</div>';
        }).join('');

        genericTemplateVariableCache[templateName] = html || '<div class="empty-state">Inga variabler hittades</div>';
        variablesContainer.innerHTML = genericTemplateVariableCache[templateName];
    } catch (error) {
        variablesContainer.innerHTML = `<div class="empty-state">Kunde inte ladda variabler: ${escapeHtml(error.message)}</div>`;
    }
}

async function switchGenericTemplateEditorTemplate() {
    syncGenericTemplateEditorDraft();

    const key = getGenericTemplateEditorKey();
    const editor = document.getElementById('generic-template-editor-textarea');
    if (editor) {
        editor.value = await getGenericTemplateEditorContent(key);
    }

    await loadGenericTemplateEditorVariables();
    await previewGenericTemplateEditor();
}

async function openGenericTemplateEditor() {
    const modal = getGenericTemplateEditorModal();
    const select = document.getElementById('generic-template-editor-select');
    const editor = document.getElementById('generic-template-editor-textarea');
    if (!modal || !select || !editor) {
        return;
    }

    setGenericTemplateEditorError('');
    select.value = 'report_md';
    editor.value = '';
    modal.classList.remove('hidden');
    editor.value = await getGenericTemplateEditorContent('report_md');
    await loadGenericTemplateEditorVariables();
    await previewGenericTemplateEditor();
    editor.focus();
}

function closeGenericTemplateEditor(event) {
    if (event && event.target && event.target !== getGenericTemplateEditorModal()) {
        return;
    }

    syncGenericTemplateEditorDraft();
    setGenericTemplateEditorError('');
    getGenericTemplateEditorModal()?.classList.add('hidden');
}

async function previewGenericTemplateEditor() {
    const editor = document.getElementById('generic-template-editor-textarea');
    const useFullData = document.getElementById('generic-template-editor-full-data')?.checked || false;
    if (!editor) {
        return;
    }

    syncGenericTemplateEditorDraft();
    setGenericTemplateEditorError('');

    if (!editor.value.trim()) {
        setGenericTemplateEditorPreviewEmpty('Ingen mall att förhandsgranska');
        return;
    }

    try {
        const response = await fetch(`/api/templates/${getGenericTemplateEditorApiName()}/preview`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: editor.value, full: useFullData }),
        });
        const data = await response.json();

        if (data.success) {
            setGenericTemplateEditorPreviewText(data.preview);
        } else {
            setGenericTemplateEditorError(data.error || 'Förhandsvisning misslyckades');
            setGenericTemplateEditorPreviewEmpty('Fel i mallen - se felmeddelande ovan');
        }
    } catch (error) {
        setGenericTemplateEditorError('Nätverksfel: ' + error.message);
    }
}

function renderStructuredSubdirSettings(item) {
    const cfg = item.config || {};
    const enabled = !!cfg.vault_subdir_enabled;
    const subdir = cfg.vault_subdir || '';
    const inputId = `pipeline-config-${item.name}-vault_subdir`;
    const toggleId = `pipeline-config-${item.name}-vault_subdir_enabled`;

    return `
        <div class="pipeline-settings">
            <div class="pipeline-settings-row">
                <label>
                    <input type="checkbox" id="${toggleId}" ${enabled ? 'checked' : ''} onchange="toggleStructuredSubdirInput('${item.name}')">
                    Spara i underkatalog
                </label>
                <span class="help-text" style="font-size: 0.85em; color: #888;">Av: skriv i vault-roten. På: skriv i vald undermapp.</span>
            </div>
            <div class="pipeline-settings-row">
                <label for="${inputId}">Underkatalog (relativ till vault)</label>
                <input type="text" id="${inputId}" value="${escapeHtml(subdir)}" placeholder="t.ex. rapporter/7s" ${enabled ? '' : 'disabled'}>
            </div>
            <div class="pipeline-settings-actions">
                <button class="btn btn-small" onclick="saveStructuredSubdirSettings('${item.name}')">Spara inställningar</button>
            </div>
        </div>
    `;
}

function toggleStructuredSubdirInput(name) {
    const enabledEl = document.getElementById(`pipeline-config-${name}-vault_subdir_enabled`);
    const subdirEl = document.getElementById(`pipeline-config-${name}-vault_subdir`);
    if (!enabledEl || !subdirEl) {
        return;
    }
    subdirEl.disabled = !enabledEl.checked;
}

async function saveStructuredSubdirSettings(name) {
    const enabledEl = document.getElementById(`pipeline-config-${name}-vault_subdir_enabled`);
    const subdirEl = document.getElementById(`pipeline-config-${name}-vault_subdir`);
    if (!enabledEl || !subdirEl) {
        return;
    }

    const config = {
        vault_subdir_enabled: enabledEl.checked,
        vault_subdir: (subdirEl.value || '').trim(),
    };

    try {
        await savePipelineConfig(name, config);
        showConfigMessage('Pipeline-inställningar sparade.', 'success');
        await loadPipelinesDashboard();
    } catch (error) {
        showConfigMessage(`Kunde inte spara inställningar: ${error.message}`, 'error');
    }
}

function renderGenericTemplateSettings(item) {
    const cfg = item.config || {};
    const templates = cfg.templates || { report_md: '', append_md: '' };
    const autoReactionEnabled = cfg.auto_reaction_enabled || false;
    const autoReactionEmoji = cfg.auto_reaction_emoji || '✅';
    const autoReadReceiptEnabled = cfg.auto_read_receipt_enabled || false;

    const reportSummary = templates.report_md ? 'Anpassad mall sparad' : 'Standardmall används';
    const appendSummary = templates.append_md ? 'Anpassad mall sparad' : 'Standardmall används';

    return `
        <div class="pipeline-settings">
            <div class="pipeline-settings-row">
                <h4 style="margin: 0 0 12px 0;">Rapportmallar</h4>
                <div class="pipeline-template-summary">
                    <div class="pipeline-template-summary-item">
                        <strong>Rapportmall</strong>
                        <span>${escapeHtml(reportSummary)}</span>
                    </div>
                    <div class="pipeline-template-summary-item">
                        <strong>Tilläggsmall</strong>
                        <span>${escapeHtml(appendSummary)}</span>
                    </div>
                </div>
                <div class="refresh-info" style="margin-top: 8px;">Öppna mallredigeraren för att redigera och förhandsgranska mallarna i ett större fönster.</div>
                <div class="pipeline-settings-actions" style="justify-content: flex-start; margin-top: 10px;">
                    <button type="button" class="btn btn-small" onclick="openGenericTemplateEditor()">Öppna mallredigerare</button>
                </div>
                <textarea id="pipeline-config-generic_template-report_md" class="pipeline-template-storage" aria-hidden="true">${escapeHtml(templates.report_md || '')}</textarea>
                <textarea id="pipeline-config-generic_template-append_md" class="pipeline-template-storage" aria-hidden="true">${escapeHtml(templates.append_md || '')}</textarea>
            </div>

            <div class="pipeline-settings-row">
                <h4 style="margin: 0 0 12px 0;">Signal-bekräftelser</h4>
                <div class="config-grid">
                    <div class="config-field">
                        <label>
                            <input type="checkbox" id="pipeline-config-generic_template-auto_reaction" ${autoReactionEnabled ? 'checked' : ''}>
                            Auto-reaktion
                        </label>
                        <span class="help-text" style="font-size: 0.85em; color: #888;">Reagera med emoji på sparade meddelanden</span>
                    </div>
                    <div class="config-field">
                        <label for="pipeline-config-generic_template-auto_reaction_emoji" style="font-size: 0.9em;">Reaktions-emoji</label>
                        <input type="text" id="pipeline-config-generic_template-auto_reaction_emoji" value="${escapeHtml(autoReactionEmoji)}" style="width: 80px; padding: 4px 6px;">
                    </div>
                    <div class="config-field">
                        <label>
                            <input type="checkbox" id="pipeline-config-generic_template-auto_read_receipt" ${autoReadReceiptEnabled ? 'checked' : ''}>
                            Läskvitton
                        </label>
                        <span class="help-text" style="font-size: 0.85em; color: #888;">Skicka läskvitto när meddelande bearbetats</span>
                    </div>
                </div>
            </div>

            <div class="pipeline-settings-actions">
                <button class="btn btn-small" onclick="saveGenericTemplateSettings()">Spara inställningar</button>
            </div>
        </div>
    `;
}

async function saveGenericTemplateSettings() {
    syncGenericTemplateEditorDraft();
    const reportMd = document.getElementById('pipeline-config-generic_template-report_md')?.value || '';
    const appendMd = document.getElementById('pipeline-config-generic_template-append_md')?.value || '';
    const autoReaction = document.getElementById('pipeline-config-generic_template-auto_reaction')?.checked || false;
    const autoReactionEmoji = document.getElementById('pipeline-config-generic_template-auto_reaction_emoji')?.value || '✅';
    const autoReadReceipt = document.getElementById('pipeline-config-generic_template-auto_read_receipt')?.checked || false;

    const config = {
        templates: {
            report_md: reportMd,
            append_md: appendMd,
        },
        auto_reaction_enabled: autoReaction,
        auto_reaction_emoji: autoReactionEmoji,
        auto_read_receipt_enabled: autoReadReceipt,
    };

    try {
        await savePipelineConfig('generic_template', config);
        showConfigMessage('Pipeline-inställningar sparade.', 'success');
        if (!getGenericTemplateEditorModal()?.classList.contains('hidden')) {
            closeGenericTemplateEditor();
        }
        await loadPipelinesDashboard();
    } catch (error) {
        showConfigMessage(`Kunde inte spara inställningar: ${error.message}`, 'error');
    }
}

async function savePipelineConfig(name, config) {
    const response = await fetch(`/api/pipelines/${encodeURIComponent(name)}/config`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ config }),
    });

    const payload = await response.json();
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || `HTTP ${response.status}`);
    }
}


function renderPipelineDefaults() {
    const container = document.getElementById('pipelines-available-list');
    const available = (pipelinesState.available || []).filter(p => p.name !== 'group_filter');
    if (!available.length) {
        container.innerHTML = '<div class="empty-state">Inga pipelines hittades.</div>';
        return;
    }
    const configs = Object.fromEntries((pipelinesState.enabled || []).map(item => [item.name, item.config]));
    container.innerHTML = available.map(pipeline => {
        const item = { name: pipeline.name, config: configs[pipeline.name] || pipelinesState.settings?.[pipeline.name] || {} };
        const settingsHtml = pipeline.name === 'generic_template'
            ? renderGenericTemplateSettings(item)
            : ['seven_s', 'fors', 'pedars', 'scrim'].includes(pipeline.name)
            ? renderStructuredSubdirSettings(item)
            : '';
        return `
            <details class="pipeline-card">
                <summary class="pipeline-card-header">
                    <span class="pipeline-title">${escapeHtml(routingPipelineLabel(pipeline.name))}</span>
                    <span class="pipeline-meta">Körningar totalt: ${pipelineRunCount(pipeline.name)}</span>
                </summary>
                <div class="pipeline-criteria"><strong>Väljer:</strong> ${escapeHtml(pipeline.selection_criteria || '')}</div>
                ${pipeline.description ? `<div class="pipeline-description">${escapeHtml(pipeline.description)}</div>` : ''}
                ${settingsHtml || '<div class="pipeline-meta">Inga inställningar.</div>'}
            </details>`;
    }).join('');
}

async function loadPipelinesDashboard() {
    const container = document.getElementById('pipelines-available-list');
    if (!container) return;
    try {
        const response = await fetch('/api/pipelines');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        pipelinesState = {
            available: payload.available || [],
            enabled: payload.enabled || [],
            settings: payload.settings || {},
            stats: payload.stats || { total_processed: 0, by_pipeline: {} },
        };
        renderPipelineDefaults();
    } catch (error) {
        container.innerHTML = `<div class="empty-state">Kunde inte ladda pipelines: ${escapeHtml(error.message)}</div>`;
    }
    await loadRouting();
}
