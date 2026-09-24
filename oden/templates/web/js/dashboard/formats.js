// formats.js — Depends on: shared.js (escapeHtml, showConfigMessage), routing.js (loadRouting)
//
// Rapportformat: report formats defined here instead of in code. A format is
// its header lines, labelled fields, sections, which are required, the TNR
// field and an optional note template. Each saved format becomes a step
// (format:<id>) that branches can use. Built-in formats are shown read-only,
// with "Utgå från" to start an own format from them.

let formatsState = null;   // {formats, used_in, builtins, template_variables}
let formatDraft = null;    // the format being edited (a copy)
let formatDraftIndex = -1; // index in formatsState.formats, -1 = new
let formatTestTimer = null;

const FORMAT_FIELD_TYPES = [['text', 'Text'], ['mgrs', 'Position (MGRS)']];

async function loadFormats() {
    try {
        const response = await fetch('/api/report-formats');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        formatsState = await response.json();
        renderFormatsList();
        renderFormatEditor();
    } catch (error) {
        const box = document.getElementById('formats-list');
        if (box) box.innerHTML = `<div class="empty-state">Kunde inte ladda rapportformaten: ${escapeHtml(error.message)}</div>`;
    }
}

function renderFormatsList() {
    const box = document.getElementById('formats-list');
    if (!box || !formatsState) return;
    const own = formatsState.formats.map((fmt, index) => {
        const used = formatsState.used_in[fmt.id] || [];
        return `
            <button type="button" class="format-card ${formatDraftIndex === index && formatDraft ? 'focused' : ''}"
                    onclick="editFormat(${index})">
                <span class="format-card-name">${escapeHtml(fmt.name)}</span>
                <span class="routing-source-meta mono">${escapeHtml(fmt.headers.join(' / '))}</span>
                <span class="routing-source-meta">${fmt.fields.length} fält · ${fmt.sections.length} avsnitt ·
                    ${used.length ? `används i ${escapeHtml(used.join(', '))}` : 'inte i någon gren'}</span>
            </button>`;
    }).join('');
    const builtins = formatsState.builtins.map(b => `
        <div class="format-card builtin">
            <span class="format-card-name">${escapeHtml(b.display_name)} <span class="routing-flag format-builtin-flag">inbyggt</span></span>
            <span class="routing-source-meta mono">${escapeHtml(b.headers.join(' / '))}</span>
            <button type="button" class="btn btn-small" data-name="${escapeHtml(b.name)}"
                    onclick="newFormat(this.dataset.name)">Utgå från ${escapeHtml(b.starter.name.replace(' (eget)', ''))}</button>
        </div>`).join('');
    box.innerHTML = `
        <h5 class="format-list-heading">Egna format</h5>
        ${own || '<p class="routing-source-meta">Inga ännu. Skapa ett nytt eller utgå från ett inbyggt.</p>'}
        <button type="button" class="btn btn-small" onclick="newFormat()">+ Nytt format</button>
        <h5 class="format-list-heading">Inbyggda</h5>
        <p class="routing-source-meta">Skrivna i kod och kan inte ändras här. Gör en egen kopia om formatet ska se annorlunda ut.</p>
        ${builtins}`;
}

// Same shape as the server's keys (a–z, 0–9, _). Rows not yet saved follow
// their label; a saved row keeps its key so notes already written stay consistent.
function formatKey(label) {
    const key = label.toLowerCase().replace(/[åä]/g, 'a').replace(/ö/g, 'o').replace(/é/g, 'e')
        .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
    return /^[a-z]/.test(key) ? key : (key ? `f_${key}`.slice(0, 40) : '');
}

function blankFormatRow(kind) {
    return kind === 'fields'
        ? {key: '', label: '', aliases: [], required: false, type: 'text', _auto: true}
        : {key: '', label: '', aliases: [], required: false, _auto: true};
}

function newFormat(builtinName) {
    const builtin = builtinName && formatsState.builtins.find(b => b.name === builtinName);
    formatDraft = builtin
        ? JSON.parse(JSON.stringify(builtin.starter))
        : {name: '', headers: [''], fields: [blankFormatRow('fields')], sections: [], tnr_field: '', file_prefix: '', report_type: '', end_marker: '', template: ''};
    formatDraft.id = '';
    for (const row of [...formatDraft.fields, ...formatDraft.sections]) {
        row._auto = !row.key;
        row.key = row.key || formatKey(row.label);
    }
    formatDraft.end_marker = formatDraft.end_marker || '';
    formatDraft.template = formatDraft.template || '';
    formatDraftIndex = -1;
    renderFormatsList();
    renderFormatEditor();
}

function editFormat(index) {
    formatDraft = JSON.parse(JSON.stringify(formatsState.formats[index]));
    formatDraftIndex = index;
    renderFormatsList();
    renderFormatEditor();
}

function cancelFormatEdit() {
    formatDraft = null;
    formatDraftIndex = -1;
    renderFormatsList();
    renderFormatEditor();
}

function formatRowsHtml(kind) {
    const rows = formatDraft[kind];
    const isField = kind === 'fields';
    const body = rows.map((row, i) => `
        <tr>
            <td><input type="text" data-kind="${kind}" data-i="${i}" data-prop="label" value="${escapeHtml(row.label)}"
                       placeholder="${isField ? 'Till' : 'O – Orientering'}" oninput="formatDraftInput(this)"></td>
            <td><input type="text" data-kind="${kind}" data-i="${i}" data-prop="aliases" value="${escapeHtml(row.aliases.join(', '))}"
                       placeholder="andra namn, kommaseparerat" oninput="formatDraftInput(this)"></td>
            ${isField ? `<td><select data-kind="${kind}" data-i="${i}" data-prop="type" onchange="formatDraftInput(this)">
                ${FORMAT_FIELD_TYPES.map(([v, l]) => `<option value="${v}" ${row.type === v ? 'selected' : ''}>${l}</option>`).join('')}
            </select></td>` : ''}
            <td class="format-center"><input type="checkbox" data-kind="${kind}" data-i="${i}" data-prop="required"
                       ${row.required ? 'checked' : ''} onchange="formatDraftInput(this)" aria-label="Obligatorisk"></td>
            <td><button type="button" class="btn btn-small" onclick="removeFormatRow('${kind}', ${i})" aria-label="Ta bort rad">✕</button></td>
        </tr>`).join('');
    return `
        <table class="format-table">
            <thead><tr><th>${isField ? 'Fält (etikett)' : 'Avsnitt (rubrik)'}</th><th>Andra namn</th>${isField ? '<th>Typ</th>' : ''}<th>Krävs</th><th></th></tr></thead>
            <tbody>${body || `<tr><td colspan="5" class="routing-source-meta">Inga ${isField ? 'fält' : 'avsnitt'}.</td></tr>`}</tbody>
        </table>
        <button type="button" class="btn btn-small" onclick="addFormatRow('${kind}')">+ ${isField ? 'Fält' : 'Avsnitt'}</button>`;
}

function renderFormatEditor() {
    const box = document.getElementById('format-editor');
    if (!box) return;
    if (!formatDraft) {
        box.innerHTML = '<div class="empty-state">Välj ett format till vänster, eller skapa ett nytt.</div>';
        return;
    }
    const used = formatDraftIndex >= 0 ? (formatsState.used_in[formatDraft.id] || []) : [];
    const vars = Object.entries(formatsState.template_variables || {})
        .map(([k, v]) => `<li><code>${escapeHtml(k)}</code> – ${escapeHtml(v)}</li>`).join('');
    box.innerHTML = `
        <div class="format-grid">
            <label class="routing-field">Namn
                <input type="text" id="format-name" value="${escapeHtml(formatDraft.name)}" placeholder="t.ex. Anmälan" oninput="formatDraftInput(this)">
            </label>
            <label class="routing-field">Rubrikrader (en per rad) — formatet väljs när meddelandets första rad börjar så
                <textarea id="format-headers" rows="2" oninput="formatDraftInput(this)">${escapeHtml(formatDraft.headers.join('\n'))}</textarea>
            </label>
            <label class="routing-field">Rapporttyp (<code>typ:</code> i anteckningen)
                <input type="text" id="format-report-type" value="${escapeHtml(formatDraft.report_type)}" placeholder="namn + -rapport" oninput="formatDraftInput(this)">
            </label>
            <label class="routing-field">Filprefix (filen blir prefix + TNR)
                <input type="text" id="format-file-prefix" value="${escapeHtml(formatDraft.file_prefix)}" placeholder="t.ex. ANM" oninput="formatDraftInput(this)">
            </label>
            <label class="routing-field">TNR-fält (ger filnamn och rapporttid)
                <select id="format-tnr" onchange="formatDraftInput(this)">${formatTnrOptions()}</select>
            </label>
            <label class="routing-field">Slutrad (valfri, t.ex. SLUT!)
                <input type="text" id="format-end" value="${escapeHtml(formatDraft.end_marker)}" oninput="formatDraftInput(this)">
            </label>
        </div>
        <div class="routing-field">Fält — rader som <code>Etikett: värde</code>${formatRowsHtml('fields')}</div>
        <div class="routing-field">Avsnitt — en rubrikrad, sedan fri text till nästa avsnitt${formatRowsHtml('sections')}</div>
        <details class="format-template" ${formatDraft.template ? 'open' : ''}>
            <summary>Mall för anteckningens innehåll (valfri)</summary>
            <p class="routing-source-meta">Tom mall = fälten som <b>Etikett:</b> värde och avsnitten som rubriker. Frontmatter (id, typ, tnr, tider, avsändare och fälten) skrivs alltid.</p>
            <textarea id="format-template" rows="6" class="mono" oninput="formatDraftInput(this)">${escapeHtml(formatDraft.template)}</textarea>
            <ul class="format-vars">${vars}</ul>
        </details>
        <div class="routing-field">Testa formatet — klistra in ett meddelande (inget sparas eller skrivs)
            <textarea id="format-test-text" rows="6" class="mono" oninput="scheduleFormatTest()"
                      placeholder="${escapeHtml((formatDraft.headers[0] || 'RUBRIK') + '\\nTNR: 241430\\n…')}"></textarea>
        </div>
        <div id="format-test-result"></div>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-primary btn-small" onclick="saveFormat()">Spara format</button>
            <button type="button" class="btn btn-small" onclick="cancelFormatEdit()">Avbryt</button>
            ${formatDraftIndex >= 0 ? `<button type="button" class="btn btn-small btn-danger-outline" onclick="deleteFormat()"
                ${used.length ? `disabled title="Används i ${escapeHtml(used.join(', '))} – ta bort steget där först"` : ''}>Ta bort format</button>` : ''}
        </div>
        ${formatDraftIndex >= 0 ? `<p class="routing-source-meta">Steg-id <code>format:${escapeHtml(formatDraft.id)}</code>${used.length ? ` · används i ${escapeHtml(used.join(', '))}` : ' · lägg till det i en gren under Grenar ovan'}</p>` : ''}`;
}

// Reads one edited input into the draft (no re-render, so focus stays).
function formatDraftInput(el) {
    if (el.dataset.kind) {
        const row = formatDraft[el.dataset.kind][Number(el.dataset.i)];
        const prop = el.dataset.prop;
        if (prop === 'required') row.required = el.checked;
        else if (prop === 'aliases') row.aliases = el.value.split(',').map(s => s.trim()).filter(Boolean);
        else row[prop] = el.value;
        if (prop === 'label' && row._auto) {
            const wasTnr = el.dataset.kind === 'fields' && row.key && formatDraft.tnr_field === row.key;
            row.key = formatKey(row.label);
            if (wasTnr) formatDraft.tnr_field = row.key;
        }
        if (el.dataset.kind === 'fields' && prop === 'label') refreshFormatTnrOptions();
    } else {
        const map = {
            'format-name': 'name', 'format-report-type': 'report_type', 'format-file-prefix': 'file_prefix',
            'format-tnr': 'tnr_field', 'format-end': 'end_marker', 'format-template': 'template',
        };
        if (el.id === 'format-headers') formatDraft.headers = el.value.split('\n');
        else formatDraft[map[el.id]] = el.value;
    }
    scheduleFormatTest();
}

function formatTnrOptions() {
    return [['', '– inget (meddelandets tid) –']]
        .concat(formatDraft.fields.filter(f => f.label && f.key).map(f => [f.key, f.label]))
        .map(([k, l]) => `<option value="${escapeHtml(k)}" ${formatDraft.tnr_field === k ? 'selected' : ''}>${escapeHtml(l)}</option>`)
        .join('');
}

function refreshFormatTnrOptions() {
    const select = document.getElementById('format-tnr');
    if (select) select.innerHTML = formatTnrOptions();
}

function addFormatRow(kind) {
    formatDraft[kind].push(blankFormatRow(kind));
    renderFormatEditor();
}

function removeFormatRow(kind, index) {
    const [removed] = formatDraft[kind].splice(index, 1);
    if (kind === 'fields' && removed && removed.key && formatDraft.tnr_field === removed.key) formatDraft.tnr_field = '';
    renderFormatEditor();
}

// The draft as the API wants it: empty rows dropped.
function formatPayload() {
    const clean = rows => rows.filter(r => r.label.trim()).map(({_auto, ...row}) => row);
    const fields = clean(formatDraft.fields);
    return {
        ...formatDraft,
        headers: formatDraft.headers.map(h => h.trim()).filter(Boolean),
        fields,
        sections: clean(formatDraft.sections),
        tnr_field: fields.some(f => f.key === formatDraft.tnr_field) ? formatDraft.tnr_field : '',
    };
}

function scheduleFormatTest() {
    clearTimeout(formatTestTimer);
    formatTestTimer = setTimeout(testFormat, 400);
}

async function testFormat() {
    const textEl = document.getElementById('format-test-text');
    const box = document.getElementById('format-test-result');
    if (!textEl || !box || !formatDraft) return;
    if (!textEl.value.trim()) {
        box.innerHTML = '';
        return;
    }
    try {
        const response = await fetch('/api/report-formats/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({format: formatPayload(), text: textEl.value}),
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
        box.innerHTML = renderFormatTest(data);
    } catch (error) {
        box.innerHTML = `<p class="format-test-bad">${escapeHtml(error.message)}</p>`;
    }
}

function renderFormatTest(data) {
    if (!data.matched) {
        return '<p class="format-test-bad">Första raden matchar ingen av rubrikraderna – formatet skulle hoppa över meddelandet.</p>';
    }
    const p = data.parsed;
    const found = formatDraft.fields.filter(f => f.label).map(f => {
        const value = p.fields[f.key];
        const cls = value ? 'ok' : (f.required ? 'bad' : 'empty');
        return `<span class="format-chip ${cls}" title="${escapeHtml(value || '')}">${escapeHtml(f.label)}${value ? ' ✓' : (f.required ? ' saknas' : '')}</span>`;
    }).join('');
    const sections = formatDraft.sections.filter(s => s.label).map(s => {
        const has = p.sections[s.key];
        return `<span class="format-chip ${has ? 'ok' : (s.required ? 'bad' : 'empty')}">${escapeHtml(s.label)}${has ? ' ✓' : (s.required ? ' saknas' : '')}</span>`;
    }).join('');
    const verdict = data.handled
        ? `<p class="format-test-ok">✓ Tas av formatet. ${escapeHtml(data.reason || '')}</p>`
        : `<p class="format-test-bad">✕ ${escapeHtml(data.reason || 'Tas inte')}</p>`;
    return `${verdict}
        <div class="format-chips">${found}${sections}</div>
        ${p.other.length ? `<p class="routing-source-meta">Rader utan fält hamnar under Övrigt: ${escapeHtml(p.other.slice(0, 3).join(' · '))}${p.other.length > 3 ? ' …' : ''}</p>` : ''}
        ${(data.warnings || []).map(w => `<p class="flow-trace-warn">⚠ ${escapeHtml(w)}</p>`).join('')}
        ${data.content ? `<pre class="routing-test-content">${escapeHtml(data.content)}</pre>` : ''}`;
}

async function saveFormatsList(formats, message) {
    const response = await fetch('/api/report-formats', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({formats}),
    });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
    showConfigMessage(message, 'success');
    return data.formats;
}

async function saveFormat() {
    const payload = formatPayload();
    const formats = formatsState.formats.slice();
    if (formatDraftIndex >= 0) formats[formatDraftIndex] = payload;
    else formats.push(payload);
    try {
        const saved = await saveFormatsList(formats, `Formatet ”${payload.name}” sparat`);
        const index = formatDraftIndex >= 0 ? formatDraftIndex : saved.length - 1;
        await loadFormats();
        editFormat(index);
        loadRouting();
    } catch (error) {
        showConfigMessage(`Kunde inte spara: ${error.message}`, 'error');
    }
}

async function deleteFormat() {
    const fmt = formatsState.formats[formatDraftIndex];
    if (!confirm(`Ta bort formatet ”${fmt.name}”?`)) return;
    try {
        await saveFormatsList(formatsState.formats.filter((_, i) => i !== formatDraftIndex), `Formatet ”${fmt.name}” borttaget`);
        formatDraft = null;
        formatDraftIndex = -1;
        await loadFormats();
        loadRouting();
    } catch (error) {
        showConfigMessage(`Kunde inte ta bort: ${error.message}`, 'error');
    }
}
