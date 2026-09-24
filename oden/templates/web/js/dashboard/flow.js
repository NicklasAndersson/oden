// flow.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Flöde tab: every stored message, newest first, with the pipeline route it
// took and the reason each pipeline gave. Detail pane shows the trace, the raw
// envelope and the file that was written.

const FLOW_KIND_LABELS = {
    handled: 'Hanterade',
    ignored: 'Ignorerade',
    skipped: 'Hoppade över',
    failed: 'Fel',
    running: 'Pågår',
    side: 'Sidoeffekt',
    notrun: 'Kördes inte',
};

const FLOW_STATUS_FILTERS = [
    ['', 'Alla'],
    ['processed', 'Hanterade'],
    ['ignored', 'Ignorerade'],
    ['failed', 'Fel'],
];

let flowItems = [];
let flowChain = [];
let flowSummary = null;
let flowSource = '';
let flowStatus = '';
let flowPaused = false;
let flowSelectedId = null;
let flowDetail = null;
let flowTab = 'trace';

function flowSourceLabel(source) {
    if (source === 'tak') return 'TAK';
    const account = (source || '').replace(/^signal:/, '');
    return account ? `Signal · ${account}` : 'Signal';
}

function flowTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function flowDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString('sv-SE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function flowStepKind(step) {
    if (step.side_effect) return 'side';
    return step.outcome || 'skipped';
}

// One marker per pipeline: the ones that ran, in the order they ran, then the
// rest of the configured chain as "not run" (the chain stopped before them).
function flowRoute(item) {
    const steps = item.steps || [];
    const ran = new Set(steps.map(step => step.pipeline));
    return steps.map(step => ({ name: step.pipeline, kind: flowStepKind(step) }))
        .concat(flowChain.filter(name => !ran.has(name)).map(name => ({ name, kind: 'notrun' })));
}

function flowOutcome(item) {
    const steps = item.steps || [];
    const handler = steps.find(s => s.outcome === 'handled' || s.outcome === 'ignored');
    const published = steps.some(s => s.side_effect);
    const failed = steps.some(s => s.outcome === 'failed');
    if (item.status === 'failed') return { kind: 'failed', label: 'Fel' };
    if (!handler) {
        if (item.status === 'received' || item.status === 'queued' || item.status === 'processing') {
            return { kind: 'running', label: 'Väntar' };
        }
        return { kind: 'skipped', label: 'Inget sparat' };
    }
    if (handler.outcome === 'ignored') return { kind: 'ignored', label: 'Ignorerad' };
    let label = handler.output_path ? handler.output_path.split('/').pop() : handler.pipeline;
    if (published) label += ' + TAK';
    return { kind: failed ? 'warn' : 'handled', label };
}

function flowMarker(kind, name) {
    const title = `${name} – ${(FLOW_KIND_LABELS[kind] || kind).toLowerCase()}`;
    return `<span class="flow-marker flow-marker-${kind}" title="${escapeHtml(title)}"></span>`;
}

function flowMatchesSearch(item, query) {
    if (!query) return true;
    const haystack = [item.source_name, item.source_number, item.group_name, item.message_body]
        .filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(query);
}

function renderFlowChips() {
    const summary = flowSummary || { sources: {}, statuses: {}, total: 0 };
    const sources = [['', 'Alla källor', summary.total]].concat(
        Object.entries(summary.sources).map(([key, count]) => [key, flowSourceLabel(key), count])
    );
    document.getElementById('flow-source-chips').innerHTML = sources.map(([key, label, count]) => `
        <button type="button" class="flow-chip${flowSource === key ? ' active' : ''}" aria-pressed="${flowSource === key}"
                data-source="${escapeHtml(key).replace(/"/g, '&quot;')}" onclick="setFlowSource(this.dataset.source)">${escapeHtml(label)}<span class="flow-chip-count">${count || 0}</span></button>
    `).join('');

    document.getElementById('flow-status-chips').innerHTML = FLOW_STATUS_FILTERS.map(([key, label]) => {
        const count = key ? (summary.statuses[key] || 0) : summary.total;
        const dot = key ? `<span class="flow-chip-dot flow-dot-${key}"></span>` : '';
        return `<button type="button" class="flow-chip${flowStatus === key ? ' active' : ''}" aria-pressed="${flowStatus === key}"
                onclick="setFlowStatus('${key}')">${dot}${label}<span class="flow-chip-count">${count}</span></button>`;
    }).join('');

    const hidden = summary.hidden_without_content || 0;
    document.getElementById('flow-hidden-note').textContent = hidden
        ? `${hidden} kvitton och skrivindikatorer utan innehåll är dolda.`
        : '';
}

function renderFlowList() {
    const list = document.getElementById('flow-list');
    const query = (document.getElementById('flow-search').value || '').trim().toLowerCase();
    const items = flowItems.filter(item => flowMatchesSearch(item, query));
    if (items.length === 0) {
        list.innerHTML = '<div class="empty-state">Inget i flödet matchar filtret.</div>';
        return;
    }
    list.innerHTML = items.map(item => {
        const outcome = flowOutcome(item);
        const tagClass = item.source === 'tak' ? 'flow-tag-tak' : 'flow-tag-signal';
        const sender = item.source_name || item.source_number || 'Okänd';
        const channel = item.group_name || 'Direktmeddelande';
        const body = (item.message_body || (item.has_attachments ? '[bilaga]' : '')).split('\n').slice(0, 3).join(' · ');
        const route = flowRoute(item).map(r => flowMarker(r.kind, r.name)).join('');
        return `
            <button type="button" class="flow-row${item.id === flowSelectedId ? ' selected' : ''}"
                    aria-pressed="${item.id === flowSelectedId}" onclick="selectFlowMessage(${item.id})">
                <span class="flow-col-time mono">${escapeHtml(flowTime(item.timestamp_utc))}</span>
                <span class="flow-col-main">
                    <span class="flow-row-line">
                        <span class="flow-tag ${tagClass}">${escapeHtml(flowSourceLabel(item.source))}</span>
                        <span class="flow-sender">${escapeHtml(sender)}</span>
                        <span class="flow-arrow">→</span>
                        <span class="flow-channel">${escapeHtml(channel)}</span>
                    </span>
                    <span class="flow-preview mono">${escapeHtml(body)}</span>
                </span>
                <span class="flow-col-route">
                    <span class="flow-outcome flow-outcome-${outcome.kind} mono">${escapeHtml(outcome.label)}</span>
                    <span class="flow-route">${route}</span>
                </span>
            </button>`;
    }).join('');
}

function renderFlowDetail() {
    const head = document.getElementById('flow-detail-head');
    const body = document.getElementById('flow-detail-body');
    const reprocessBtn = document.getElementById('flow-reprocess-btn');
    const copyBtn = document.getElementById('flow-copy-btn');

    if (!flowDetail) {
        head.innerHTML = '<div class="empty-state">Välj ett meddelande i flödet.</div>';
        body.innerHTML = '';
        reprocessBtn.disabled = true;
        copyBtn.disabled = true;
        return;
    }
    reprocessBtn.disabled = false;
    copyBtn.disabled = false;

    const item = flowDetail.message;
    const tagClass = item.source === 'tak' ? 'flow-tag-tak' : 'flow-tag-signal';
    const destinations = (item.steps || []).filter(s => s.output_path || s.side_effect || s.outcome === 'ignored');
    const destHtml = destinations.map(s => {
        if (s.side_effect) return `<div class="flow-dest"><span class="flow-badge flow-badge-side">TAK</span><span class="mono">${escapeHtml(s.side_effect)}</span></div>`;
        if (s.outcome === 'ignored') return `<div class="flow-dest"><span class="flow-badge flow-badge-ignored">Ignorerad</span><span>Ingen fil skrevs</span></div>`;
        return `<div class="flow-dest"><span class="flow-badge flow-badge-handled">Vault</span><span class="mono">${escapeHtml(s.output_path)}</span></div>`;
    });
    if (item.status === 'failed') {
        destHtml.push('<div class="flow-dest"><span class="flow-badge flow-badge-failed">Fel</span><span>Inget sparat – kör om när felet är åtgärdat</span></div>');
    }
    const attempts = item.attempts > 1 ? ` · körning ${item.attempts}` : '';

    head.innerHTML = `
        <div class="flow-detail-meta mono">
            <span class="flow-tag ${tagClass}">${escapeHtml(flowSourceLabel(item.source))}</span>
            <span>#${item.id}</span><span>·</span><span>${escapeHtml(flowDate(item.timestamp_utc))}</span>
            <span>·</span><span>${escapeHtml(item.status)}${attempts}</span>
        </div>
        <h4 class="flow-detail-sender">${escapeHtml(item.source_name || item.source_number || 'Okänd')}</h4>
        <div class="flow-detail-sub"><span class="mono">${escapeHtml(item.source_number || '')}</span> → ${escapeHtml(item.group_name || 'Direktmeddelande')}</div>
        <div class="flow-dest-box">
            <span class="flow-label">Hamnade i</span>
            ${destHtml.join('') || '<div class="flow-dest"><span>Inget sparat</span></div>'}
        </div>`;

    document.querySelectorAll('.flow-tab').forEach(btn => {
        const on = btn.dataset.flowTab === flowTab;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on);
    });

    if (flowTab === 'raw') {
        body.innerHTML = `
            <p class="flow-hint">Exakt som raden lagrades i <span class="mono">raw_messages.envelope_raw</span>.</p>
            <pre class="flow-pre">${escapeHtml(JSON.stringify(item.envelope_raw || {}, null, 2))}</pre>`;
        return;
    }
    if (flowTab === 'out') {
        const out = flowDetail.output;
        body.innerHTML = out
            ? `<p class="flow-hint">Så här ser filen <span class="mono">${escapeHtml(out.path)}</span> ut nu${out.truncated ? ' (avkortad)' : ''}.</p>
               <pre class="flow-pre">${escapeHtml(out.content)}</pre>`
            : '<p class="flow-hint">Inget skrevs till vaulten för det här meddelandet.</p>';
        return;
    }

    const trace = [{
        name: item.source === 'tak' ? 'tak-lyssnare' : 'signal-cli',
        kind: 'recv',
        verdict: 'Mottaget',
        why: `Rå rad #${item.id} sparad innan behandling.`,
    }];
    (item.steps || []).forEach(step => {
        const kind = flowStepKind(step);
        let why = step.reason || '';
        if (step.side_effect) why = step.side_effect + (why ? ` ${why}` : '');
        if (step.outcome === 'failed' && step.error) why = step.error;
        trace.push({ name: step.pipeline, kind, verdict: FLOW_KIND_LABELS[kind], why, out: step.output_path, warnings: step.warnings || [] });
    });
    const ran = new Set((item.steps || []).map(s => s.pipeline));
    const notRun = flowChain.filter(name => !ran.has(name));
    if (notRun.length && (item.steps || []).length) {
        trace.push({ name: notRun.join(', '), kind: 'notrun', verdict: FLOW_KIND_LABELS.notrun, why: 'Kedjan stannar vid första pipeline som hanterar meddelandet.' });
    }

    body.innerHTML = `<ol class="flow-trace">${trace.map(step => `
        <li class="flow-trace-step">
            <span class="flow-trace-rail">${flowMarker(step.kind, step.name)}<span class="flow-trace-line"></span></span>
            <span class="flow-trace-body">
                <span class="flow-trace-title"><span class="mono">${escapeHtml(step.name)}</span>
                    <span class="flow-badge flow-badge-${step.kind}">${escapeHtml(step.verdict)}</span></span>
                ${step.why ? `<span class="flow-trace-why">${escapeHtml(step.why)}</span>` : ''}
                ${(step.warnings || []).map(w => `<span class="flow-trace-warn">⚠ ${escapeHtml(w)}</span>`).join('')}
                ${step.out ? `<span class="flow-trace-out mono">→ ${escapeHtml(step.out)}</span>` : ''}
            </span>
        </li>`).join('')}</ol>`;
}

async function fetchFlow() {
    const params = new URLSearchParams({ limit: '200' });
    if (flowSource) params.set('source', flowSource);
    if (flowStatus) params.set('status', flowStatus);
    try {
        const response = await fetch('/api/flow?' + params.toString());
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Kunde inte hämta flödet');
        flowItems = data.messages || [];
        flowChain = data.chain || [];
        flowSummary = data.summary || null;
        const newest = flowItems[0];
        document.getElementById('flow-live-text').textContent = flowPaused
            ? 'Pausad'
            : (newest ? `Live · senast ${flowTime(newest.timestamp_utc)}` : 'Live');
        renderFlowChips();
        renderFlowList();
    } catch (error) {
        document.getElementById('flow-list').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

async function loadFlowDetail(id) {
    try {
        const response = await fetch(`/api/flow/${id}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Kunde inte hämta meddelandet');
        if (id !== flowSelectedId) return;
        flowDetail = data;
        if (data.chain) flowChain = data.chain;
        renderFlowDetail();
    } catch (error) {
        flowDetail = null;
        renderFlowDetail();
        document.getElementById('flow-detail-head').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    }
}

function loadFlowDashboard() {
    fetchFlow();
    if (flowSelectedId) loadFlowDetail(flowSelectedId);
}

function fetchFlowIfVisible() {
    const tab = document.getElementById('tab-flow');
    if (!flowPaused && tab && tab.classList.contains('active')) fetchFlow();
}

function selectFlowMessage(id) {
    flowSelectedId = id;
    renderFlowList();
    loadFlowDetail(id);
}

function setFlowSource(key) {
    flowSource = key;
    fetchFlow();
}

function setFlowStatus(key) {
    flowStatus = key;
    fetchFlow();
}

function showFlowTab(tab) {
    flowTab = tab;
    renderFlowDetail();
}

function toggleFlowPaused() {
    flowPaused = !flowPaused;
    document.getElementById('flow-pause-btn').textContent = flowPaused ? 'Fortsätt' : 'Pausa';
    document.getElementById('flow-live').classList.toggle('paused', flowPaused);
    document.getElementById('flow-live-text').textContent = flowPaused ? 'Pausad' : 'Live';
    if (!flowPaused) fetchFlow();
}

async function reprocessFlowMessage() {
    if (!flowSelectedId) return;
    try {
        const response = await fetch(`/api/messages/${flowSelectedId}/reprocess`, { method: 'POST' });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'Omkörning misslyckades');
        showConfigMessage(data.message || 'Meddelandet kördes om', 'success');
        loadFlowDashboard();
    } catch (error) {
        showConfigMessage(error.message, 'error');
    }
}

async function copyFlowJson() {
    if (!flowDetail) return;
    try {
        await navigator.clipboard.writeText(JSON.stringify(flowDetail.message.envelope_raw || {}, null, 2));
        showConfigMessage('JSON kopierad', 'success');
    } catch (error) {
        showConfigMessage('Kunde inte kopiera: ' + error.message, 'error');
    }
}
