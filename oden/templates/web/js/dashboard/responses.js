// responses.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMsg)
//
// CRUD management for auto-reply responses (keywords + body).

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
