// routing.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Pipelines tab, upper half: the vägval (which branch each source goes to)
// and the branches with their steps. Edits are made on a copy of the routing
// and saved with PUT /api/routing; the next message uses them.

const ROUTING_LABELS = {
    seven_s: '7S-rapport',
    fors: 'FORS',
    pedars: 'PEDARS',
    scrim: 'SCRIM',
    generic_template: 'Reserv (allt annat)',
    tak_publish: 'TAK-publicering',
};
const ROUTING_STRUCTURED = ['seven_s', 'fors', 'pedars', 'scrim'];

let routingState = null;      // {routing, sources, branch_counts_24h, pipelines}
let routingSelected = null;   // branch id shown in the detail pane

function routingPipelineLabel(name) {
    return ROUTING_LABELS[name] || name;
}

function routingBranch(id) {
    return routingState.routing.branches.find(b => b.id === id);
}

function routingMeta(name) {
    return (routingState.pipelines || []).find(p => p.name === name) || {};
}

async function loadRouting() {
    try {
        const response = await fetch('/api/routing');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        routingState = await response.json();
        if (!routingSelected || !routingBranch(routingSelected)) routingSelected = routingState.routing.default;
        renderRouting();
    } catch (error) {
        document.getElementById('routing-sources').innerHTML =
            `<div class="empty-state">Kunde inte ladda vägvalet: ${escapeHtml(error.message)}</div>`;
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
        showConfigMessage(message || 'Vägvalet sparat', 'success');
    } catch (error) {
        showConfigMessage(`Kunde inte spara: ${error.message}`, 'error');
    }
    await loadRouting();
}

function routingCopy() {
    return JSON.parse(JSON.stringify(routingState.routing));
}

function branchOptions(selected) {
    return routingState.routing.branches.map(b =>
        `<option value="${escapeHtml(b.id)}" ${b.id === selected ? 'selected' : ''}>${escapeHtml(b.name)}${b.ignore ? ' (ignorera)' : ''}</option>`
    ).join('');
}

function renderRouting() {
    const {routing, sources} = routingState;
    const counts = routingState.branch_counts_24h || {};
    const unassigned = sources.filter(s => !s.assigned && s.count_24h > 0 && s.kind === 'group');

    document.getElementById('routing-unassigned').textContent = unassigned.length
        ? `${unassigned.length} ${unassigned.length === 1 ? 'grupp' : 'grupper'} med trafik saknar egen gren`
        : '';
    document.getElementById('routing-unassigned').classList.toggle('hidden', !unassigned.length);

    document.getElementById('routing-default').innerHTML = branchOptions(routing.default);

    document.getElementById('routing-sources').innerHTML = sources.map(source => {
        const kindLabel = source.kind === 'tak' ? 'TAK' : (source.kind === 'direct' ? 'DM' : 'SIG');
        const flag = !source.assigned && source.count_24h > 0 && source.kind === 'group'
            ? '<span class="routing-flag">ej tilldelad</span>' : '';
        return `
            <div class="routing-source">
                <span class="routing-kind routing-kind-${source.kind}">${kindLabel}</span>
                <span class="routing-source-name">
                    <span>${escapeHtml(source.label)} ${flag}</span>
                    <span class="routing-source-meta">${source.count_24h} senaste 24 h${source.assigned ? '' : ' · standardgren'}</span>
                </span>
                <select aria-label="Gren för ${escapeHtml(source.label)}" data-key="${escapeHtml(source.key)}"
                        onchange="assignSource(this.dataset.key, this.value)">
                    <option value="" ${source.assigned ? '' : 'selected'}>Standard</option>
                    ${branchOptions(source.assigned ? source.branch : null)}
                </select>
            </div>`;
    }).join('');

    document.getElementById('routing-branch-pills').innerHTML = routing.branches.map(b => `
        <button type="button" class="subtab-btn ${b.id === routingSelected ? 'active' : ''}"
                data-branch="${escapeHtml(b.id)}" onclick="selectBranch(this.dataset.branch)">
            ${escapeHtml(b.name)}${b.id === routing.default ? ' ★' : ''}
            <span class="flow-chip-count">${counts[b.id] || 0}</span>
        </button>`).join('');

    renderBranchDetail();
}

function renderBranchDetail() {
    const branch = routingBranch(routingSelected);
    const container = document.getElementById('routing-branch-detail');
    if (!branch) {
        container.innerHTML = '';
        return;
    }
    const counts = routingState.branch_counts_24h || {};
    const sources = routingState.sources.filter(s => s.branch === branch.id).map(s => s.label);
    const isDefault = branch.id === routingState.routing.default;

    let stepsHtml;
    if (branch.ignore) {
        stepsHtml = '<div class="empty-state">Inga steg: meddelanden hit sparas bara i Flöde (status ignorerad) och skrivs aldrig till valvet.</div>';
    } else {
        const present = branch.steps.map(s => s.pipeline);
        const addable = ROUTING_STRUCTURED.filter(name => !present.includes(name));
        stepsHtml = branch.steps.map((step, index) => {
            const isFallback = step.pipeline === 'generic_template';
            const meta = routingMeta(step.pipeline);
            const subdir = (step.config || {}).vault_subdir || '';
            const canUp = !isFallback && index > 0;
            const canDown = !isFallback && index < branch.steps.length - 2;
            return `
                <div class="pipeline-card ${step.enabled ? 'enabled' : 'disabled'}">
                    <div class="pipeline-card-header">
                        <div class="pipeline-title-wrap">
                            <span class="pipeline-order">${isFallback ? 'sist' : index + 1 + '.'}</span>
                            <span class="pipeline-title">${escapeHtml(routingPipelineLabel(step.pipeline))}</span>
                            <span class="pipeline-chip ${step.enabled ? 'active' : 'inactive'}">${step.enabled ? 'På' : 'Av'}</span>
                        </div>
                        <div class="pipeline-controls">
                            ${isFallback ? '<span class="pipeline-meta">alltid sist</span>' : `
                            <button class="btn btn-small" onclick="moveStep(${index}, -1)" ${canUp ? '' : 'disabled'} aria-label="Flytta upp">↑</button>
                            <button class="btn btn-small" onclick="moveStep(${index}, 1)" ${canDown ? '' : 'disabled'} aria-label="Flytta ner">↓</button>
                            <button class="btn btn-small" onclick="toggleStep(${index})">${step.enabled ? 'Stäng av' : 'Slå på'}</button>
                            <button class="btn btn-small btn-danger-outline" onclick="removeStep(${index})">Ta bort</button>`}
                        </div>
                    </div>
                    <div class="pipeline-criteria"><strong>Väljer:</strong> ${escapeHtml(meta.selection_criteria || '')}</div>
                    ${ROUTING_STRUCTURED.includes(step.pipeline) ? `
                    <div class="pipeline-settings-row routing-step-setting">
                        <label for="routing-subdir-${index}">Undermapp i den här grenen</label>
                        <input type="text" id="routing-subdir-${index}" value="${escapeHtml(subdir)}"
                               placeholder="tom = grundinställningen nedan">
                        <button class="btn btn-small" onclick="saveStepSubdir(${index})">Spara</button>
                    </div>` : ''}
                </div>`;
        }).join('') + (addable.length ? `
            <div class="routing-add-step">
                <select id="routing-add-step">${addable.map(n => `<option value="${n}">${escapeHtml(routingPipelineLabel(n))}</option>`).join('')}</select>
                <button class="btn btn-small" onclick="addStep()">+ Lägg till steg</button>
            </div>` : '');
    }

    container.innerHTML = `
        <div class="routing-branch-head">
            <div>
                <h4 class="pane-heading">${escapeHtml(branch.name)}${branch.ignore ? ' <span class="routing-flag">ignorera</span>' : ''}</h4>
                <div class="pipeline-meta">${counts[branch.id] || 0} meddelanden senaste 24 h ·
                    ${sources.length ? `Källor: ${escapeHtml(sources.join(', '))}` : 'Inga källor'}${isDefault ? ' · standardgren för allt annat' : ''}</div>
            </div>
            <div class="pipeline-controls">
                <button class="btn btn-small" onclick="renameBranch()">Byt namn</button>
                <button class="btn btn-small btn-danger-outline" onclick="deleteBranch()" ${isDefault ? 'disabled title="Välj en annan standardgren först"' : ''}>Ta bort gren</button>
            </div>
        </div>
        ${stepsHtml}`;
}

function selectBranch(id) {
    routingSelected = id;
    renderRouting();
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

function mutateBranch(fn, message) {
    const routing = routingCopy();
    const branch = routing.branches.find(b => b.id === routingSelected);
    fn(branch, routing);
    saveRouting(routing, message);
}

function moveStep(index, direction) {
    mutateBranch(branch => {
        const target = index + direction;
        [branch.steps[index], branch.steps[target]] = [branch.steps[target], branch.steps[index]];
    }, 'Ordningen ändrad');
}

function toggleStep(index) {
    mutateBranch(branch => { branch.steps[index].enabled = !branch.steps[index].enabled; }, 'Steget ändrat');
}

function removeStep(index) {
    mutateBranch(branch => { branch.steps.splice(index, 1); }, 'Steget borttaget');
}

function addStep() {
    const name = document.getElementById('routing-add-step').value;
    mutateBranch(branch => {
        branch.steps.splice(branch.steps.length - 1, 0, {pipeline: name, enabled: true, config: {}});
    }, 'Steg tillagt');
}

function saveStepSubdir(index) {
    const value = document.getElementById(`routing-subdir-${index}`).value.trim();
    mutateBranch(branch => {
        const config = {...(branch.steps[index].config || {})};
        if (value) {
            config.vault_subdir = value;
            config.vault_subdir_enabled = true;
        } else {
            delete config.vault_subdir;
            delete config.vault_subdir_enabled;
        }
        branch.steps[index].config = config;
    }, 'Undermappen sparad');
}

function addBranch() {
    const name = (prompt('Namn på den nya grenen:') || '').trim();
    if (!name) return;
    const ignore = confirm('Ska grenen ignorera allt som kommer hit (inga steg, inget skrivs)?\n\nOK = ignorera, Avbryt = vanlig gren med samma steg som standardgrenen.');
    const routing = routingCopy();
    const template = routing.branches.find(b => b.id === routing.default);
    routing.branches.push({
        name,
        ignore,
        steps: ignore ? [] : JSON.parse(JSON.stringify(template && !template.ignore ? template.steps : [])),
    });
    saveRouting(routing, `Grenen ”${name}” skapad`).then(() => {
        const created = routingState.routing.branches[routingState.routing.branches.length - 1];
        if (created) selectBranch(created.id);
    });
}

function renameBranch() {
    const branch = routingBranch(routingSelected);
    const name = (prompt('Nytt namn:', branch.name) || '').trim();
    if (!name || name === branch.name) return;
    mutateBranch(b => { b.name = name; }, 'Namnet ändrat');
}

function deleteBranch() {
    const branch = routingBranch(routingSelected);
    if (!confirm(`Ta bort grenen ”${branch.name}”? Källor som går hit flyttas till standardgrenen.`)) return;
    const routing = routingCopy();
    routing.branches = routing.branches.filter(b => b.id !== branch.id);
    for (const [key, target] of Object.entries(routing.assign)) {
        if (target === branch.id) delete routing.assign[key];
    }
    routingSelected = routing.default;
    saveRouting(routing, `Grenen ”${branch.name}” borttagen`);
}
