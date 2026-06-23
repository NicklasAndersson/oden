// message_queue.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Message observability tab: list, detail, stats, and reprocess action.

let selectedMessageId = null;

function formatMessageLabel(msg) {
    const sender = msg.source_name || msg.source_number || 'Okänd';
    const group = msg.group_name || 'inbox';
    return `${sender} → ${group}`;
}

function renderMessagesList(messages) {
    const list = document.getElementById('messages-list');
    if (!messages || messages.length === 0) {
        list.innerHTML = '<div class="empty-state">Inga meddelanden hittades.</div>';
        return;
    }

    list.innerHTML = messages.map(msg => {
        const selectedClass = selectedMessageId === msg.id ? ' selected' : '';
        const bodyPreview = msg.message_body ? escapeHtml(msg.message_body).slice(0, 120) : '(ingen text)';
        return `
            <button class="message-row${selectedClass}" onclick="selectMessage(${msg.id})">
                <div class="message-row-top">
                    <span class="message-row-title">${escapeHtml(formatMessageLabel(msg))}</span>
                    <span class="message-status status-${escapeHtml(msg.status)}">${escapeHtml(msg.status)}</span>
                </div>
                <div class="message-row-meta">${escapeHtml(msg.timestamp_utc || '')}</div>
                <div class="message-row-body">${bodyPreview}</div>
            </button>
        `;
    }).join('');
}

function renderMessageDetail(payload) {
    const container = document.getElementById('message-detail');
    const message = payload.message;
    const runs = payload.runs || [];

    const runsHtml = runs.map(run => {
        const events = run.events || [];
        const eventsHtml = events.map(event =>
            `<li><strong>${escapeHtml(event.event_type)}</strong> <span>${escapeHtml(event.occurred_at || '')}</span></li>`
        ).join('');

        return `
            <div class="pipeline-run">
                <div><strong>${escapeHtml(run.pipeline_name)}</strong> — <span class="message-status status-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></div>
                <div class="pipeline-run-meta">Start: ${escapeHtml(run.started_at || '-')} | Klar: ${escapeHtml(run.completed_at || '-')}</div>
                ${run.error_message ? `<div class="pipeline-run-error">${escapeHtml(run.error_message)}</div>` : ''}
                <ul class="pipeline-events">${eventsHtml || '<li>Inga events</li>'}</ul>
            </div>
        `;
    }).join('');

    const raw = JSON.stringify(message.envelope_raw || {}, null, 2);

    container.innerHTML = `
        <div class="message-detail-meta">
            <div><strong>ID:</strong> ${message.id}</div>
            <div><strong>Status:</strong> <span class="message-status status-${escapeHtml(message.status)}">${escapeHtml(message.status)}</span></div>
            <div><strong>Avsändare:</strong> ${escapeHtml(message.source_name || message.source_number || 'Okänd')}</div>
            <div><strong>Grupp:</strong> ${escapeHtml(message.group_name || message.group_id || 'inbox')}</div>
        </div>
        <h4>Pipeline-körningar</h4>
        <div>${runsHtml || '<div class="empty-state">Inga pipeline-runs.</div>'}</div>
        <h4>Rått meddelande</h4>
        <pre class="message-raw-json">${escapeHtml(raw)}</pre>
    `;
}

async function loadMessageDetail(messageId) {
    try {
        const response = await fetch(`/api/messages/${messageId}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const payload = await response.json();
        renderMessageDetail(payload);
        document.getElementById('btn-reprocess-message').disabled = false;
    } catch (error) {
        document.getElementById('message-detail').innerHTML = `<div class="empty-state">Kunde inte ladda detalj: ${escapeHtml(error.message)}</div>`;
    }
}

async function loadMessageStats() {
    try {
        const response = await fetch('/api/messages/stats');
        if (!response.ok) {
            return;
        }
        const stats = await response.json();
        document.getElementById('messages-stat-total').textContent = stats.total || 0;
        document.getElementById('messages-stat-processed').textContent = stats.processed || 0;
        document.getElementById('messages-stat-failed').textContent = stats.failed || 0;
        document.getElementById('messages-stat-ignored').textContent = stats.ignored || 0;
    } catch (_error) {
        // Best-effort stats refresh.
    }
}

async function loadMessagesDashboard() {
    try {
        const status = document.getElementById('messages-status-filter').value;
        const params = new URLSearchParams({ limit: '100' });
        if (status) {
            params.set('status', status);
        }

        const response = await fetch(`/api/messages?${params.toString()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const payload = await response.json();
        const messages = payload.messages || [];
        renderMessagesList(messages);

        if (selectedMessageId && messages.some(m => m.id === selectedMessageId)) {
            await loadMessageDetail(selectedMessageId);
        }

        await loadMessageStats();
    } catch (error) {
        document.getElementById('messages-list').innerHTML = `<div class="empty-state">Kunde inte ladda meddelanden: ${escapeHtml(error.message)}</div>`;
    }
}

async function selectMessage(messageId) {
    selectedMessageId = messageId;
    await loadMessagesDashboard();
}

async function reprocessSelectedMessage() {
    if (!selectedMessageId) {
        return;
    }

    try {
        const response = await fetch(`/api/messages/${selectedMessageId}/reprocess`, { method: 'POST' });
        const payload = await response.json();
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        showConfigMessage('Meddelandet processades om.', 'success');
        await loadMessagesDashboard();
    } catch (error) {
        showConfigMessage(`Kunde inte reprocessa meddelande: ${error.message}`, 'error');
    }
}

function fetchMessagesIfVisible() {
    const tab = document.getElementById('tab-messages');
    if (tab && tab.classList.contains('active')) {
        loadMessagesDashboard();
    }
}
