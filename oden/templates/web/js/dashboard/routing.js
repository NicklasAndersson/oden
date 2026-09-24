// routing.js — Depends on: shared.js (escapeHtml, showConfigMessage), flow.js (showFlowFiltered)
//
// Pipelines tab: the vägval (which branch each source goes to) on the left,
// the branches as columns of steps in the middle, and a detail panel on the
// right for the selected branch or step. Edits are made on a copy of the
// routing and saved with PUT /api/routing; the next message uses them.

const ROUTING_LABELS = {
    seven_s: '7S-rapport',
    fors: 'FORS',
    pedars: 'PEDARS',
    scrim: 'SCRIM',
    generic_template: 'Reserv (allt annat)',
    tak_publish: 'TAK-publicering',
};
const ROUTING_STRUCTURED = ['seven_s', 'fors', 'pedars', 'scrim'];

let routingState = null;   // {routing, sources, branch_counts_24h, step_stats_24h, pipelines, publish_to_tak}
let routingFocus = null;   // {branch: id} or {branch: id, step: pipeline}

function routingPipelineLabel(name) {
    if (ROUTING_LABELS[name]) return ROUTING_LABELS[name];
    const meta = routingState && (routingState.pipelines || []).find(p => p.name === name);
    return meta ? meta.display_name : name.replace(/^format:/, '');
}

// Report steps write one note per report and have a folder per branch:
// the built-ins and the formats from Rapportformat (format:<id>).
function routingIsReport(name) {
    return ROUTING_STRUCTURED.includes(name) || name.startsWith('format:');
}

function routingReportSteps() {
    return ROUTING_STRUCTURED.concat((routingState.pipelines || []).filter(p => p.format).map(p => p.name));
}

function routingBranch(id) {
    return routingState.routing.branches.find(b => b.id === id);
}

function routingMeta(name) {
    return (routingState.pipelines || []).find(p => p.name === name) || {};
}

function routingStepStats(branchId, pipeline) {
    return ((routingState.step_stats_24h || {})[branchId] || {})[pipeline] || {handled: 0, skipped: 0, failed: 0, side: 0};
}

// The branch to focus when nothing (or an ignore branch) is: the default, if it has steps.
function routingFirstColumn() {
    const {routing} = routingState;
    const home = routing.branches.find(b => b.id === routing.default && !b.ignore);
    return (home || routing.branches.find(b => !b.ignore) || routing.branches[0]).id;
}

async function loadRouting() {
    try {
        const response = await fetch('/api/routing');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        routingState = await response.json();
        const focused = routingFocus && routingBranch(routingFocus.branch);
        if (!focused || focused.ignore) routingFocus = {branch: routingFirstColumn()};
        renderRouting();
    } catch (error) {
        const box = document.getElementById('routing-sources');
        if (box) box.innerHTML = `<div class="empty-state">Kunde inte ladda vägvalet: ${escapeHtml(error.message)}</div>`;
    }
}

async function saveRouting(routing, message) {
    try {
        const response = await fetch('/api/routing', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({routing}),
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
        showConfigMessage(message || 'Sparat', 'success');
        await loadRouting();
        return data.routing;
    } catch (error) {
        showConfigMessage(`Kunde inte spara: ${error.message}`, 'error');
        await loadRouting();
        return null;
    }
}

function routingCopy() {
    return JSON.parse(JSON.stringify(routingState.routing));
}

// Branches with steps first; "Ignorera" (no steps, never a column) last.
function branchOptions(selected) {
    const branches = routingState.routing.branches;
    return branches.filter(b => !b.ignore).concat(branches.filter(b => b.ignore)).map(b =>
        `<option value="${escapeHtml(b.id)}" ${b.id === selected ? 'selected' : ''}>${escapeHtml(b.name)}</option>`
    ).join('');
}

// ---------- rendering ----------

function renderRouting() {
    if (!routingState || !document.getElementById('routing-sources')) return;
    renderRoutingSources();
    renderRoutingColumns();
    renderRoutingDetail();
    renderRoutingTestSources();
}

function renderRoutingSources() {
    const {routing, sources} = routingState;
    const unassigned = sources.filter(s => !s.assigned && s.count_24h > 0 && s.kind === 'group');
    const flag = document.getElementById('routing-unassigned');
    flag.textContent = unassigned.length
        ? `${unassigned.length} ${unassigned.length === 1 ? 'grupp' : 'grupper'} med trafik saknar egen gren`
        : '';
    flag.classList.toggle('hidden', !unassigned.length);

    document.getElementById('routing-default').innerHTML = branchOptions(routing.default);
    const ignoreIds = routing.branches.filter(b => b.ignore).map(b => b.id);
    const ignored = sources.filter(s => ignoreIds.includes(s.branch));
    const ignoredCount = ignored.reduce((sum, s) => sum + s.count_24h, 0);
    document.getElementById('routing-ignored').innerHTML = ignored.length
        ? `<b>Ignoreras</b> (sparas bara i Flöde): ${escapeHtml(ignored.map(s => s.label).join(', '))} · ${ignoredCount} senaste 24 h
           <button type="button" class="flow-link" data-branch="${escapeHtml(ignoreIds[0])}" onclick="showFlowFiltered({branch: this.dataset.branch})">Visa i Flöde</button>`
        : 'Inget ignoreras. Välj <b>Ignorera</b> för en källa för att bara spara den i Flöde.';
    document.getElementById('routing-sources').innerHTML = sources.map(source => {
        const kindLabel = source.kind === 'tak' ? 'TAK' : (source.kind === 'direct' ? 'DM' : 'SIG');
        const warn = !source.assigned && source.count_24h > 0 && source.kind === 'group'
            ? '<span class="routing-flag">ej tilldelad</span>' : '';
        return `
            <div class="routing-source">
                <span class="routing-kind routing-kind-${source.kind}">${kindLabel}</span>
                <span class="routing-source-name">
                    <span>${escapeHtml(source.label)} ${warn}</span>
                    <span class="routing-source-meta">${source.count_24h} senaste 24 h${source.assigned ? '' : ' · standardgren'}</span>
                </span>
                <select aria-label="Gren för ${escapeHtml(source.label)}" data-key="${escapeHtml(source.key)}"
                        onchange="assignSource(this.dataset.key, this.value)">
                    <option value="" ${source.assigned ? '' : 'selected'}>Standard</option>
                    ${branchOptions(source.assigned ? source.branch : null)}
                </select>
            </div>`;
    }).join('');
}

function stepCard(branch, step, index) {
    const stats = routingStepStats(branch.id, step.pipeline);
    const isFallback = step.pipeline === 'generic_template';
    const subdir = (step.config || {}).vault_subdir;
    const focused = routingFocus.branch === branch.id && routingFocus.step === step.pipeline;
    const statLine = `${stats.handled} hanterade${stats.failed ? ` · <span class="routing-fail">${stats.failed} fel</span>` : ''}`;
    return `
        <button type="button" class="routing-step ${focused ? 'focused' : ''} ${step.enabled ? '' : 'off'}"
                data-branch="${escapeHtml(branch.id)}" data-step="${escapeHtml(step.pipeline)}"
                onclick="focusStep(this.dataset.branch, this.dataset.step)" aria-pressed="${focused}">
            <span class="routing-step-head">
                <span class="flow-marker flow-marker-${step.enabled ? 'handled' : 'skipped'}"></span>
                <span class="routing-step-name">${escapeHtml(routingPipelineLabel(step.pipeline))}</span>
                <span class="routing-step-order">${isFallback ? (step.enabled ? 'sist' : 'av') : (step.enabled ? index + 1 : 'av')}</span>
            </span>
            ${routingIsReport(step.pipeline)
                ? `<span class="routing-step-target mono">→ ${escapeHtml(subdir || 'grundinställning')}</span>` : ''}
            ${isFallback ? `<span class="routing-step-target mono">${step.enabled
                ? `→ ${escapeHtml(subdir ? `gruppen/${subdir}` : 'gruppens mapp')}`
                : 'allt annat sparas bara i Flöde'}</span>` : ''}
            <span class="routing-step-stat">${statLine}</span>
        </button>`;
}

function renderRoutingColumns() {
    const {routing} = routingState;
    const counts = routingState.branch_counts_24h || {};
    const columns = routing.branches.filter(branch => !branch.ignore).map(branch => {
        const sources = routingState.sources.filter(s => s.branch === branch.id).length;
        const headFocused = routingFocus.branch === branch.id && !routingFocus.step;
        const takCard = routingState.publish_to_tak ? `
            <div class="routing-step locked">
                <span class="routing-step-head"><span class="flow-marker flow-marker-side"></span>
                <span class="routing-step-name">TAK-publicering</span><span class="routing-step-order">först</span></span>
                <span class="routing-step-target">Styrs i TAK-fliken</span>
            </div>` : '';
        const present = branch.steps.map(s => s.pipeline);
        const addable = routingReportSteps().filter(name => !present.includes(name));
        const body = takCard + branch.steps.map((step, index) => stepCard(branch, step, index)).join('') + (addable.length ? `
            <div class="routing-add-step">
                <select id="routing-add-${escapeHtml(branch.id)}" aria-label="Steg att lägga till">
                    ${addable.map(n => `<option value="${escapeHtml(n)}">${escapeHtml(routingPipelineLabel(n))}</option>`).join('')}
                </select>
                <button type="button" class="btn btn-small" data-branch="${escapeHtml(branch.id)}"
                        onclick="addStep(this.dataset.branch)">+ Steg</button>
            </div>` : '');
        return `
            <section class="routing-column" aria-label="Gren ${escapeHtml(branch.name)}">
                <button type="button" class="routing-column-head ${headFocused ? 'focused' : ''}"
                        data-branch="${escapeHtml(branch.id)}" onclick="focusBranch(this.dataset.branch)">
                    <span class="routing-column-name">${escapeHtml(branch.name)}${branch.id === routing.default ? ' <span title="Standardgren">★</span>' : ''}</span>
                    <span class="routing-source-meta">${sources} ${sources === 1 ? 'källa' : 'källor'} · ${counts[branch.id] || 0} senaste 24 h</span>
                </button>
                ${body}
            </section>`;
    });
    columns.push(`
        <section class="routing-column new" aria-label="Ny gren">
            <h4 class="pane-heading">Ny gren</h4>
            <input type="text" id="routing-new-name" placeholder="Namn, t.ex. Övning" autocomplete="off">
            <select id="routing-new-kind" aria-label="Typ av gren">
                <option value="copy">Samma steg som standardgrenen</option>
                <option value="empty">Bara reserven</option>
            </select>
            <button type="button" class="btn btn-small" onclick="createBranch()">Skapa</button>
        </section>`);
    document.getElementById('routing-columns').innerHTML = columns.join('');
}

function renderRoutingDetail() {
    const box = document.getElementById('routing-detail');
    const branch = routingBranch(routingFocus.branch);
    if (!branch) {
        box.innerHTML = '';
        return;
    }
    const step = routingFocus.step ? branch.steps.find(s => s.pipeline === routingFocus.step) : null;
    box.innerHTML = step ? stepDetail(branch, step) : branchDetail(branch);
}

function branchDetail(branch) {
    const {routing} = routingState;
    const sources = routingState.sources.filter(s => s.branch === branch.id);
    const isDefault = branch.id === routing.default;
    return `
        <div class="routing-detail-head">
            <span class="routing-source-meta">Gren${isDefault ? ' · standardgren' : ''}${branch.ignore ? ' · ignorera' : ''}</span>
            <h4 class="pane-heading">${escapeHtml(branch.name)}</h4>
        </div>
        <label class="routing-field">Namn
            <input type="text" id="routing-branch-name" value="${escapeHtml(branch.name)}">
        </label>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small btn-primary" onclick="renameFocusedBranch()">Spara namn</button>
            ${isDefault ? '' : '<button type="button" class="btn btn-small" onclick="makeFocusedDefault()">Gör till standardgren</button>'}
        </div>
        <div class="routing-field">Källor
            <div class="routing-source-meta">${sources.length ? escapeHtml(sources.map(s => s.label).join(', ')) : 'Inga — tilldela i listan till vänster'}${isDefault ? ', och allt som inte tilldelats' : ''}</div>
        </div>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small" data-branch="${escapeHtml(branch.id)}"
                    onclick="showFlowFiltered({branch: this.dataset.branch})">Visa grenens meddelanden i Flöde</button>
        </div>
        <div class="routing-detail-actions routing-danger">
            <button type="button" class="btn btn-small btn-danger-outline" onclick="deleteFocusedBranch()"
                    ${isDefault ? 'disabled title="Gör en annan gren till standardgren först"' : ''}>Ta bort gren</button>
        </div>`;
}

function stepDetail(branch, step) {
    const meta = routingMeta(step.pipeline);
    const stats = routingStepStats(branch.id, step.pipeline);
    const index = branch.steps.indexOf(step);
    const isFallback = step.pipeline === 'generic_template';
    const lastMovable = branch.steps.length - 2;
    const total = Math.max(1, stats.handled + stats.skipped + stats.failed);
    const subdir = (step.config || {}).vault_subdir || '';
    return `
        <div class="routing-detail-head">
            <span class="routing-source-meta">Gren ${escapeHtml(branch.name)} · ${isFallback ? 'sist' : `steg ${index + 1}`}</span>
            <h4 class="pane-heading">${escapeHtml(routingPipelineLabel(step.pipeline))}</h4>
            <p class="routing-what">${escapeHtml(meta.selection_criteria || '')}</p>
        </div>
        ${isFallback ? `
        <p class="routing-source-meta">Tar det som inget steg ovanför tog. ${step.enabled
            ? 'Skrivs som en anteckning per meddelande i gruppens mapp, eller i mappen nedan.'
            : 'Avstängd: det inget steg tog sparas bara i Flöde (status ignorerad) och skrivs aldrig.'}</p>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small" onclick="toggleFocusedStep()">${step.enabled ? 'Stäng av reserven' : 'Slå på reserven'}</button>
        </div>
        ${step.enabled ? `
        <label class="routing-field">Mapp för allt annat i den här grenen
            <input type="text" id="routing-step-subdir" value="${escapeHtml(subdir)}" placeholder="tom = gruppens mapp, t.ex. Övrigt">
        </label>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small btn-primary" onclick="saveFocusedSubdir()">Spara</button>
            <button type="button" class="btn btn-small" onclick="renderRoutingDetail()">Ångra</button>
        </div>` : ''}` : `
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small" onclick="toggleFocusedStep()">${step.enabled ? 'Stäng av' : 'Slå på'}</button>
            <button type="button" class="btn btn-small" onclick="moveFocusedStep(-1)" ${index > 0 ? '' : 'disabled'} aria-label="Flytta upp">↑ Upp</button>
            <button type="button" class="btn btn-small" onclick="moveFocusedStep(1)" ${index < lastMovable ? '' : 'disabled'} aria-label="Flytta ner">↓ Ner</button>
        </div>`}
        ${routingIsReport(step.pipeline) ? `
        <label class="routing-field">Undermapp i den här grenen
            <input type="text" id="routing-step-subdir" value="${escapeHtml(subdir)}" placeholder="tom = grundinställningen">
        </label>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small btn-primary" onclick="saveFocusedSubdir()">Spara</button>
            <button type="button" class="btn btn-small" onclick="renderRoutingDetail()">Ångra</button>
        </div>` : ''}
        ${isFallback ? '<p class="routing-source-meta">Mallar och bekräftelser för reserven ställs in under Grundinställningar nedan.</p>' : ''}
        <div class="routing-field">Senaste 24 h
            <div class="routing-bar">
                <span style="width:${stats.handled / total * 100}%" class="routing-bar-handled"></span>
                <span style="width:${stats.failed / total * 100}%" class="routing-bar-failed"></span>
            </div>
            <div class="routing-source-meta">${stats.handled} hanterade · ${stats.skipped} hoppade över · ${stats.failed} fel</div>
        </div>
        <div class="routing-detail-actions">
            <button type="button" class="btn btn-small" data-branch="${escapeHtml(branch.id)}" data-step="${escapeHtml(step.pipeline)}"
                    onclick="showFlowFiltered({branch: this.dataset.branch, pipeline: this.dataset.step, outcome: 'handled'})">Visa hanterade i Flöde</button>
            ${stats.failed ? `<button type="button" class="btn btn-small" data-branch="${escapeHtml(branch.id)}" data-step="${escapeHtml(step.pipeline)}"
                    onclick="showFlowFiltered({branch: this.dataset.branch, pipeline: this.dataset.step, outcome: 'failed'})">Visa fel</button>` : ''}
        </div>
        ${isFallback ? '' : `
        <div class="routing-detail-actions routing-danger">
            <button type="button" class="btn btn-small btn-danger-outline" onclick="removeFocusedStep()">Ta bort steg</button>
        </div>`}`;
}

// ---------- focus ----------

function focusBranch(id) {
    routingFocus = {branch: id};
    renderRoutingColumns();
    renderRoutingDetail();
}

function focusStep(branchId, pipeline) {
    routingFocus = {branch: branchId, step: pipeline};
    renderRoutingColumns();
    renderRoutingDetail();
}

// ---------- edits ----------

function withBranch(branchId, fn, message) {
    const routing = routingCopy();
    fn(routing.branches.find(b => b.id === branchId), routing);
    return saveRouting(routing, message);
}

function withFocusedStep(fn, message) {
    const {branch, step} = routingFocus;
    return withBranch(branch, b => fn(b, b.steps.findIndex(s => s.pipeline === step)), message);
}

function assignSource(key, branchId) {
    const routing = routingCopy();
    if (branchId) routing.assign[key] = branchId;
    else delete routing.assign[key];
    saveRouting(routing, 'Källan flyttad');
}

function setDefaultBranch(branchId) {
    const routing = routingCopy();
    routing.default = branchId;
    saveRouting(routing, 'Standardgren ändrad');
}

function makeFocusedDefault() {
    setDefaultBranch(routingFocus.branch);
}

function toggleFocusedStep() {
    withFocusedStep((b, i) => { b.steps[i].enabled = !b.steps[i].enabled; }, 'Steget ändrat');
}

function moveFocusedStep(direction) {
    withFocusedStep((b, i) => {
        const j = i + direction;
        [b.steps[i], b.steps[j]] = [b.steps[j], b.steps[i]];
    }, 'Ordningen ändrad');
}

function removeFocusedStep() {
    const {branch} = routingFocus;
    withFocusedStep((b, i) => { b.steps.splice(i, 1); }, 'Steget borttaget');
    routingFocus = {branch};
}

function saveFocusedSubdir() {
    const value = document.getElementById('routing-step-subdir').value.trim();
    withFocusedStep((b, i) => {
        const config = {...(b.steps[i].config || {})};
        if (value) {
            config.vault_subdir = value;
            config.vault_subdir_enabled = true;
        } else {
            delete config.vault_subdir;
            delete config.vault_subdir_enabled;
        }
        b.steps[i].config = config;
    }, 'Undermappen sparad');
}

function addStep(branchId) {
    const name = document.getElementById(`routing-add-${branchId}`).value;
    withBranch(branchId, b => {
        b.steps.splice(b.steps.length - 1, 0, {pipeline: name, enabled: true, config: {}});
    }, 'Steg tillagt').then(() => focusStep(branchId, name));
}

async function createBranch() {
    const name = document.getElementById('routing-new-name').value.trim();
    const kind = document.getElementById('routing-new-kind').value;
    if (!name) {
        showConfigMessage('Ge grenen ett namn', 'error');
        return;
    }
    const routing = routingCopy();
    const template = routing.branches.find(b => b.id === routing.default);
    routing.branches.push({
        name,
        steps: kind === 'copy' && template && !template.ignore ? JSON.parse(JSON.stringify(template.steps)) : [],
    });
    const saved = await saveRouting(routing, `Grenen ”${name}” skapad`);
    if (saved) focusBranch(saved.branches[saved.branches.length - 1].id);
}

function renameFocusedBranch() {
    const name = document.getElementById('routing-branch-name').value.trim();
    if (!name) return;
    withBranch(routingFocus.branch, b => { b.name = name; }, 'Namnet ändrat');
}

function deleteFocusedBranch() {
    const branch = routingBranch(routingFocus.branch);
    if (!confirm(`Ta bort grenen ”${branch.name}”? Källor som går hit flyttas till standardgrenen.`)) return;
    const routing = routingCopy();
    routing.branches = routing.branches.filter(b => b.id !== branch.id);
    for (const [key, target] of Object.entries(routing.assign)) {
        if (target === branch.id) delete routing.assign[key];
    }
    routingFocus = null;
    saveRouting(routing, `Grenen ”${branch.name}” borttagen`);
}

// ---------- Testruta ----------

const ROUTING_TEST_VERDICTS = {
    handled: 'Tog meddelandet',
    skipped: 'Hoppade över',
    failed: 'Fel',
    notrun: 'Körs inte',
    side: 'Sidoeffekt',
};

function renderRoutingTestSources() {
    const select = document.getElementById('routing-test-source');
    if (!select) return;
    const previous = select.value;
    select.innerHTML = routingState.sources.map(source =>
        `<option value="${escapeHtml(source.key)}">${escapeHtml(source.kind === 'group' ? `Grupp: ${source.label}` : source.label)}</option>`
    ).join('');
    const firstGroup = routingState.sources.find(s => s.kind === 'group');
    select.value = previous || (firstGroup ? firstGroup.key : 'source:direct');
}

async function runRoutingTest() {
    const box = document.getElementById('routing-test-result');
    const text = document.getElementById('routing-test-text').value;
    const source = document.getElementById('routing-test-source').value;
    box.innerHTML = '<div class="empty-state">Testar…</div>';
    try {
        const response = await fetch('/api/pipelines/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text, source}),
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
        box.innerHTML = renderRoutingTestResult(data);
    } catch (error) {
        box.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function renderRoutingTestResult(data) {
    const trace = [{
        kind: data.ignore ? 'ignored' : 'route',
        name: 'vägval',
        verdict: `Gren: ${data.branch_name}`,
        why: data.route_reason,
    }];
    if (data.ignore) {
        trace.push({kind: 'ignored', name: '∅', verdict: 'Inga steg', why: 'Ignorera-gren: sparas bara i Flöde, skrivs aldrig.'});
    }
    for (const step of data.steps) {
        trace.push({
            kind: step.outcome,
            name: routingPipelineLabel(step.pipeline),
            verdict: ROUTING_TEST_VERDICTS[step.outcome] || step.outcome,
            why: step.reason,
            warnings: step.warnings || [],
            out: step.outcome === 'handled' ? step.output_file : null,
        });
    }
    const steps = trace.map(step => `
        <li class="flow-trace-step">
            <span class="flow-trace-rail">${flowMarker(step.kind, step.name)}<span class="flow-trace-line"></span></span>
            <span class="flow-trace-body">
                <span class="flow-trace-title"><span class="mono">${escapeHtml(step.name)}</span>
                    <span class="flow-badge flow-badge-${step.kind}">${escapeHtml(step.verdict)}</span></span>
                ${step.why ? `<span class="flow-trace-why">${escapeHtml(step.why)}</span>` : ''}
                ${(step.warnings || []).map(w => `<span class="flow-trace-warn">⚠ ${escapeHtml(w)}</span>`).join('')}
                ${step.out ? `<span class="flow-trace-out mono">→ ${escapeHtml(step.out)}</span>` : ''}
            </span>
        </li>`).join('');
    const file = data.content
        ? `<div class="routing-field">Skulle skrivas till <span class="mono">${escapeHtml(data.output_file || '')}</span>
               <pre class="routing-test-content">${escapeHtml(data.content)}</pre></div>`
        : '<p class="routing-source-meta">Ingen fil skulle skrivas.</p>';
    return `<ol class="flow-trace">${steps}</ol>${file}`;
}
