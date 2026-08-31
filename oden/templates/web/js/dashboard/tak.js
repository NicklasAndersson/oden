// tak.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// TAK integration tab: status, settings form and the test marker button.

const TAK_LIST_FIELDS = ['inbound_types', 'inbound_callsign_allow', 'inbound_callsign_deny'];

async function loadTakStatus() {
    const container = document.getElementById('tak-status');

    try {
        const response = await fetch('/api/tak/status');
        const s = await response.json();

        const rows = [];
        if (!s.enabled) {
            rows.push(['Läge', 'Avstängd — aktivera i formuläret nedan']);
        } else {
            rows.push(['Anslutning', s.connected ? '🟢 Ansluten' : '🔴 Frånkopplad']);
            rows.push(['Server', escapeHtml(s.cot_url || '—')]);
            rows.push(['Skickade markörer', String(s.sent_count)]);
            if (s.inbound_enabled) {
                rows.push(['Inkommande CoT', s.rx_total + ' mottagna · ' + s.rx_filtered + ' filtrerade · ' + s.received_count + ' noter']);
                if (s.last_rx_at) rows.push(['Senast mottagen', escapeHtml(s.last_rx_at)]);
                if (s.rx_total > 0 && s.received_count === 0) {
                    rows.push(['', '<span style="color:#e0a800;">CoT kommer in men allt filtreras bort — se inbound_types, eller att Oden och du använder olika TAK-konton</span>']);
                }
            } else {
                rows.push(['Inkommande', 'Avstängt']);
            }
            if (s.last_tx_at) rows.push(['Senast skickad', escapeHtml(s.last_tx_at)]);
            if (s.last_error) rows.push(['Senaste fel', '<span style="color:#e57373;">' + escapeHtml(s.last_error) + '</span>']);
        }

        if (s.cert_days_left !== null && s.cert_days_left !== undefined) {
            const warn = s.cert_warning;
            const text = s.cert_days_left + ' dagar kvar (' + escapeHtml((s.cert_expires_at || '').slice(0, 10)) + ')';
            rows.push(['Certifikat', warn ? '<span style="color:#e57373;">⚠️ ' + text + '</span>' : text]);
        }

        let html = '<table style="width: 100%; border-collapse: collapse;"><tbody>';
        for (const [label, value] of rows) {
            html += '<tr style="border-bottom: 1px solid #222;">';
            html += '<td style="padding: 8px; color: #888; width: 200px;">' + label + '</td>';
            html += '<td style="padding: 8px;">' + value + '</td></tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="empty-state">Kunde inte hämta TAK-status</div>';
    }

    loadTakSettings();
}

async function loadTakSettings() {
    const response = await fetch('/api/tak/settings');
    const settings = await response.json();

    for (const [key, value] of Object.entries(settings)) {
        const field = document.querySelector('#tak-form [name="' + key + '"]');
        if (!field) continue;
        if (field.type === 'checkbox') {
            field.checked = Boolean(value);
        } else if (Array.isArray(value)) {
            field.value = value.join(', ');
        } else {
            field.value = value === null || value === undefined ? '' : value;
        }
    }
}

async function saveTakSettings() {
    const payload = {};
    for (const field of document.querySelectorAll('#tak-form [name]')) {
        if (field.type === 'checkbox') {
            payload[field.name] = field.checked;
        } else if (field.type === 'number') {
            payload[field.name] = Number(field.value);
        } else if (TAK_LIST_FIELDS.includes(field.name)) {
            payload[field.name] = field.value;  // servern delar på komma
        } else {
            payload[field.name] = field.value;
        }
    }

    const response = await fetch('/api/tak/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    });
    const result = await response.json();
    showConfigMessage(result.message || result.error, result.success ? 'success' : 'error');
    if (result.success) loadTakStatus();
}

async function uploadTakPackage(input) {
    const file = input.files && input.files[0];
    if (!file) return;

    const body = new FormData();
    body.append('file', file);
    try {
        const response = await fetch('/api/tak/upload-package', {method: 'POST', body: body});
        const result = await response.json();
        if (result.success) {
            document.getElementById('tak-pref-package').value = result.path;
            showConfigMessage('Data package uppladdad — klicka Spara för att ansluta', 'success');
        } else {
            showConfigMessage(result.error || 'Uppladdning misslyckades', 'error');
        }
    } catch (e) {
        showConfigMessage('Uppladdning misslyckades', 'error');
    } finally {
        input.value = '';  // allow re-picking the same file
    }
}

async function sendTakTest() {
    const mgrs = document.getElementById('tak-test-mgrs').value.trim();
    if (!mgrs) {
        showConfigMessage('Ange en MGRS-position', 'error');
        return;
    }

    const response = await fetch('/api/tak/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mgrs: mgrs}),
    });
    const result = await response.json();
    showConfigMessage(result.message || result.error, result.success ? 'success' : 'error');
    if (result.success) loadTakStatus();
}
