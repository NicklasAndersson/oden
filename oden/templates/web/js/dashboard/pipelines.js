// pipelines.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Pipeline management tab: list pipelines, enable/disable and reorder execution.

let pipelinesState = {
    available: [],
    enabled: [],
    stats: {
        total_processed: 0,
        by_pipeline: {},
    },
};

function getEnabledNames() {
    return pipelinesState.enabled.map(item => item.name);
}

function isPipelineEnabled(name) {
    return getEnabledNames().includes(name);
}

function pipelineRunCount(name) {
    return pipelinesState.stats.by_pipeline?.[name] || 0;
}

function renderGroupFilterSettings(item) {
    const cfg = item.config || {};
    const mode = cfg.mode === 'whitelist' ? 'whitelist' : 'blacklist';
    const groups = Array.isArray(cfg.groups) ? cfg.groups : [];
    const knownGroups = getKnownGroupNames();
    const suggestionsHtml = knownGroups.length
        ? knownGroups.map(groupName => {
            const isSelected = groups.includes(groupName);
            return `<button type="button" class="btn btn-small ${isSelected ? 'btn-secondary' : ''}" data-group-name="${escapeHtml(groupName)}" onclick="addGroupFilterGroupFromButton(this)">${escapeHtml(groupName)}</button>`;
        }).join('')
        : '<span class="text-muted">Inga kända grupper ännu.</span>';

    return `
        <div class="pipeline-settings">
            <div class="pipeline-settings-row">
                <label for="pipeline-config-group_filter-mode">Filterläge</label>
                <select id="pipeline-config-group_filter-mode">
                    <option value="blacklist" ${mode === 'blacklist' ? 'selected' : ''}>Blacklist (exkludera listade grupper)</option>
                    <option value="whitelist" ${mode === 'whitelist' ? 'selected' : ''}>Whitelist (tillåt endast listade grupper)</option>
                </select>
            </div>
            <div class="pipeline-settings-row">
                <label for="pipeline-config-group_filter-groups">Grupper (en per rad)</label>
                <textarea id="pipeline-config-group_filter-groups" rows="4" placeholder="Exempelgrupp A\nExempelgrupp B">${escapeHtml(groups.join('\n'))}</textarea>
                <div class="refresh-info" style="margin-top: 8px;">
                    Förslag från befintliga grupper (klicka för att lägga till):
                </div>
                <div class="pipeline-suggestions" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;">
                    ${suggestionsHtml}
                </div>
                <div class="refresh-info" style="margin-top: 6px;">
                    Du kan också skriva egna gruppnamn som ännu inte finns.
                </div>
            </div>
            <div class="pipeline-settings-actions">
                <button class="btn btn-small" onclick="saveGroupFilterSettings()">Spara filter</button>
            </div>
        </div>
    `;
}

function getKnownGroupNames() {
    const source = Array.isArray(_groupsCache) ? _groupsCache : [];
    const names = source
        .map(group => (group?.name || '').trim())
        .filter(Boolean);
    return [...new Set(names)].sort((a, b) => a.localeCompare(b, 'sv'));
}

function addGroupFilterGroupFromButton(button) {
    addGroupFilterGroup(button?.dataset?.groupName || '');
}

function addGroupFilterGroup(groupName) {
    const groupsEl = document.getElementById('pipeline-config-group_filter-groups');
    const normalized = (groupName || '').trim();
    if (!groupsEl || !normalized) {
        return;
    }

    const groups = groupsEl.value
        .split('\n')
        .map(item => item.trim())
        .filter(Boolean);

    if (!groups.includes(normalized)) {
        groups.push(normalized);
        groupsEl.value = groups.join('\n');
    }
}

function renderGenericTemplateSettings(item) {
    const cfg = item.config || {};
    const templates = cfg.templates || { report_md: '', append_md: '' };
    const regexPatterns = cfg.regex_patterns || {};
    const autoReactionEnabled = cfg.auto_reaction_enabled || false;
    const autoReactionEmoji = cfg.auto_reaction_emoji || '✅';
    const autoReadReceiptEnabled = cfg.auto_read_receipt_enabled || false;

    // Render regex patterns table
    const regexRows = Object.entries(regexPatterns).map(([name, pattern]) => `
        <div class="regex-row-inline" data-name="${escapeHtml(name)}">
            <input type="text" class="regex-name-inline" value="${escapeHtml(name)}" readonly style="flex: 1; padding: 4px 6px; background: #1a1a1a; border: 1px solid #333; border-radius: 3px; margin-right: 6px;">
            <input type="text" class="regex-pattern-inline" value="${escapeHtml(pattern)}" readonly style="flex: 2; padding: 4px 6px; background: #1a1a1a; border: 1px solid #333; border-radius: 3px; margin-right: 6px; font-family: monospace; font-size: 0.9em;">
            <button type="button" class="btn btn-small" onclick="removeGenericTemplateRegexRow(this)" style="padding: 4px 8px; color: #ff6b6b;">✕</button>
        </div>
    `).join('');

    const regexTableHtml = regexRows ? regexRows + '<div style="margin-top: 8px; display: flex; gap: 6px;"><button type="button" class="btn btn-small" onclick="addGenericTemplateRegexRow()">➕ Lägg till mönster</button></div>' : '<div class="refresh-info" style="margin-top: 8px;">Inga regex-mönster konfigurerade ännu. Klicka "Lägg till mönster" för att lägga till.</div>';

    return `
        <div class="pipeline-settings">
            <div class="pipeline-settings-row">
                <h4 style="margin: 0 0 12px 0;">Rapportmallar</h4>
                <div style="display: flex; gap: 12px; margin-bottom: 12px;">
                    <div style="flex: 1;">
                        <label for="pipeline-config-generic_template-report_md" style="display: block; margin-bottom: 6px; font-size: 0.9em;">Rapportmall (report.md.j2)</label>
                        <textarea id="pipeline-config-generic_template-report_md" rows="6" style="width: 100%; padding: 6px; background: #1a1a1a; border: 1px solid #333; border-radius: 3px; font-family: monospace; font-size: 0.85em;" placeholder="Jinja2-mall för rapporter...">${escapeHtml(templates.report_md || '')}</textarea>
                    </div>
                    <div style="flex: 1;">
                        <label for="pipeline-config-generic_template-append_md" style="display: block; margin-bottom: 6px; font-size: 0.9em;">Tilläggsmall (append.md.j2)</label>
                        <textarea id="pipeline-config-generic_template-append_md" rows="6" style="width: 100%; padding: 6px; background: #1a1a1a; border: 1px solid #333; border-radius: 3px; font-family: monospace; font-size: 0.85em;" placeholder="Jinja2-mall för tillägg...">${escapeHtml(templates.append_md || '')}</textarea>
                    </div>
                </div>
            </div>

            <div class="pipeline-settings-row">
                <h4 style="margin: 0 0 12px 0;">Regex-mönster för länkande</h4>
                <div id="pipeline-config-generic_template-regex-patterns" style="display: flex; flex-direction: column; gap: 6px;">
                    ${regexTableHtml}
                </div>
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

function addGenericTemplateRegexRow() {
    const container = document.getElementById('pipeline-config-generic_template-regex-patterns');
    if (!container) return;

    const name = prompt('Mönsternamn (t.ex. registration_number):');
    if (!name || !name.trim()) return;

    const pattern = prompt('Regex-mönster (t.ex. [A-Z]{3}[0-9]{2}[A-Z0-9]):');
    if (!pattern || !pattern.trim()) return;

    const newRow = document.createElement('div');
    newRow.className = 'regex-row-inline';
    newRow.dataset.name = name.trim();
    newRow.innerHTML = `
        <input type="text" class="regex-name-inline" value="${escapeHtml(name)}" readonly style="flex: 1; padding: 4px 6px; background: #1a1a1a; border: 1px solid #333; border-radius: 3px; margin-right: 6px;">
        <input type="text" class="regex-pattern-inline" value="${escapeHtml(pattern)}" readonly style="flex: 2; padding: 4px 6px; background: #1a1a1a; border: 1px solid #333; border-radius: 3px; margin-right: 6px; font-family: monospace; font-size: 0.9em;">
        <button type="button" class="btn btn-small" onclick="removeGenericTemplateRegexRow(this)" style="padding: 4px 8px; color: #ff6b6b;">✕</button>
    `;
    container.insertBefore(newRow, container.lastElementChild);
}

function removeGenericTemplateRegexRow(btn) {
    const row = btn.closest('.regex-row-inline');
    row.remove();
}

async function saveGenericTemplateSettings() {
    const reportMd = document.getElementById('pipeline-config-generic_template-report_md')?.value || '';
    const appendMd = document.getElementById('pipeline-config-generic_template-append_md')?.value || '';
    const autoReaction = document.getElementById('pipeline-config-generic_template-auto_reaction')?.checked || false;
    const autoReactionEmoji = document.getElementById('pipeline-config-generic_template-auto_reaction_emoji')?.value || '✅';
    const autoReadReceipt = document.getElementById('pipeline-config-generic_template-auto_read_receipt')?.checked || false;

    const regexPatterns = {};
    document.querySelectorAll('#pipeline-config-generic_template-regex-patterns .regex-row-inline').forEach(row => {
        const name = row.dataset.name || '';
        const pattern = row.querySelector('.regex-pattern-inline')?.value || '';
        if (name && pattern) {
            regexPatterns[name] = pattern;
        }
    });

    const config = {
        templates: {
            report_md: reportMd,
            append_md: appendMd,
        },
        regex_patterns: regexPatterns,
        auto_reaction_enabled: autoReaction,
        auto_reaction_emoji: autoReactionEmoji,
        auto_read_receipt_enabled: autoReadReceipt,
    };

    try {
        await savePipelineConfig('generic_template', config);
        showConfigMessage('Pipeline-inställningar sparade.', 'success');
        await loadPipelinesDashboard();
    } catch (error) {
        showConfigMessage(`Kunde inte spara inställningar: ${error.message}`, 'error');
    }
}

function renderEnabledPipelines() {
    const container = document.getElementById('pipelines-enabled-list');
    const enabled = pipelinesState.enabled || [];

    if (!enabled.length) {
        container.innerHTML = '<div class="empty-state">Inga aktiva pipelines.</div>';
        return;
    }

    container.innerHTML = enabled.map((item, index) => {
        const meta = pipelinesState.available.find(p => p.name === item.name);
        const canMoveUp = index > 0;
        const canMoveDown = index < enabled.length - 1;
        const displayName = meta?.display_name || item.name;
        const criteria = meta?.selection_criteria || 'Ingen urvalsbeskrivning tillgänglig';
        const description = meta?.description || '';
        const runCount = pipelineRunCount(item.name);

        const settingsHtml = meta?.supports_config && item.name === 'group_filter'
            ? renderGroupFilterSettings(item)
            : meta?.supports_config && item.name === 'generic_template'
            ? renderGenericTemplateSettings(item)
            : '';

        return `
            <div class="pipeline-card enabled">
                <div class="pipeline-card-header">
                    <div class="pipeline-title-wrap">
                        <span class="pipeline-order">${index + 1}.</span>
                        <span class="pipeline-title">${escapeHtml(displayName)}</span>
                        <span class="pipeline-chip active">Aktiv</span>
                    </div>
                    <div class="pipeline-controls">
                        <button class="btn btn-small" onclick="movePipeline('${escapeHtml(item.name)}', -1)" ${canMoveUp ? '' : 'disabled'} title="Flytta upp">↑</button>
                        <button class="btn btn-small" onclick="movePipeline('${escapeHtml(item.name)}', 1)" ${canMoveDown ? '' : 'disabled'} title="Flytta ner">↓</button>
                        <button class="btn btn-small btn-danger-outline" onclick="setPipelineEnabled('${escapeHtml(item.name)}', false)">Stäng av</button>
                    </div>
                </div>
                <div class="pipeline-criteria"><strong>Väljer:</strong> ${escapeHtml(criteria)}</div>
                ${description ? `<div class="pipeline-description">${escapeHtml(description)}</div>` : ''}
                ${settingsHtml}
                <div class="pipeline-meta">Körningar: ${runCount}</div>
            </div>
        `;
    }).join('');
}

function renderAvailablePipelines() {
    const container = document.getElementById('pipelines-available-list');
    const available = pipelinesState.available || [];

    if (!available.length) {
        container.innerHTML = '<div class="empty-state">Inga pipelines hittades.</div>';
        return;
    }

    container.innerHTML = available.map((pipeline) => {
        const enabled = isPipelineEnabled(pipeline.name);
        const runCount = pipelineRunCount(pipeline.name);
        const buttonText = enabled ? 'Aktiv' : 'Aktivera';

        return `
            <div class="pipeline-card ${enabled ? 'enabled' : 'disabled'}">
                <div class="pipeline-card-header">
                    <div class="pipeline-title-wrap">
                        <span class="pipeline-title">${escapeHtml(pipeline.display_name || pipeline.name)}</span>
                        <span class="pipeline-chip ${enabled ? 'active' : 'inactive'}">${enabled ? 'Aktiv' : 'Inaktiv'}</span>
                    </div>
                    <div class="pipeline-controls">
                        <button class="btn btn-small" onclick="setPipelineEnabled('${escapeHtml(pipeline.name)}', true)" ${enabled ? 'disabled' : ''}>${buttonText}</button>
                    </div>
                </div>
                <div class="pipeline-criteria"><strong>Väljer:</strong> ${escapeHtml(pipeline.selection_criteria || 'Ingen urvalsbeskrivning tillgänglig')}</div>
                ${pipeline.description ? `<div class="pipeline-description">${escapeHtml(pipeline.description)}</div>` : ''}
                <div class="pipeline-meta">Körningar: ${runCount}</div>
            </div>
        `;
    }).join('');
}

async function loadPipelinesDashboard() {
    const enabledContainer = document.getElementById('pipelines-enabled-list');
    const availableContainer = document.getElementById('pipelines-available-list');

    if (!enabledContainer || !availableContainer) {
        return;
    }

    try {
        const response = await fetch('/api/pipelines');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const payload = await response.json();
        pipelinesState = {
            available: payload.available || [],
            enabled: payload.enabled || [],
            stats: payload.stats || { total_processed: 0, by_pipeline: {} },
        };

        renderEnabledPipelines();
        renderAvailablePipelines();
    } catch (error) {
        const msg = `<div class="empty-state">Kunde inte ladda pipelines: ${escapeHtml(error.message)}</div>`;
        enabledContainer.innerHTML = msg;
        availableContainer.innerHTML = msg;
    }
}

async function setPipelineEnabled(name, enabled) {
    try {
        const response = await fetch(`/api/pipelines/${encodeURIComponent(name)}/enabled`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ enabled }),
        });

        const payload = await response.json();
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }

        showConfigMessage(`Pipeline ${name} ${enabled ? 'aktiverad' : 'avaktiverad'}.`, 'success');
        await loadPipelinesDashboard();
    } catch (error) {
        showConfigMessage(`Kunde inte uppdatera pipeline: ${error.message}`, 'error');
    }
}

async function movePipeline(name, direction) {
    const current = getEnabledNames();
    const currentIndex = current.indexOf(name);
    const targetIndex = currentIndex + direction;

    if (currentIndex < 0 || targetIndex < 0 || targetIndex >= current.length) {
        return;
    }

    const reordered = [...current];
    const temp = reordered[currentIndex];
    reordered[currentIndex] = reordered[targetIndex];
    reordered[targetIndex] = temp;

    try {
        const response = await fetch('/api/pipelines/reorder', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ order: reordered }),
        });

        const payload = await response.json();
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }

        showConfigMessage('Pipeline-ordning uppdaterad.', 'success');
        await loadPipelinesDashboard();
    } catch (error) {
        showConfigMessage(`Kunde inte ändra ordning: ${error.message}`, 'error');
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

async function saveGroupFilterSettings() {
    const modeEl = document.getElementById('pipeline-config-group_filter-mode');
    const groupsEl = document.getElementById('pipeline-config-group_filter-groups');
    if (!modeEl || !groupsEl) {
        return;
    }

    const groups = groupsEl.value
        .split('\n')
        .map(item => item.trim())
        .filter(Boolean);

    try {
        await savePipelineConfig('group_filter', {
            mode: modeEl.value === 'whitelist' ? 'whitelist' : 'blacklist',
            groups,
        });
        showConfigMessage('Gruppfilter sparat.', 'success');
        await loadPipelinesDashboard();
        await fetchGroups();
    } catch (error) {
        showConfigMessage(`Kunde inte spara gruppfilter: ${error.message}`, 'error');
    }
}

function fetchPipelinesIfVisible() {
    const tab = document.getElementById('tab-pipelines');
    if (tab && tab.classList.contains('active')) {
        loadPipelinesDashboard();
    }
}
