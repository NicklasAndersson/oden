// contacts.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMessage)
//
// Contact list display and refresh from signal-cli.

async function loadContacts() {
    const container = document.getElementById('contacts-list');

    try {
        const response = await fetch('/api/contacts');
        const data = await response.json();
        const contacts = data.contacts || [];

        if (contacts.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga kontakter hittades. Klicka "Uppdatera från Signal" för att hämta.</div>';
            return;
        }

        let html = '<table style="width: 100%; border-collapse: collapse;">';
        html += '<thead><tr style="border-bottom: 1px solid #333; text-align: left;">';
        html += '<th style="padding: 8px;">Namn</th>';
        html += '<th style="padding: 8px;">Nummer</th>';
        html += '<th style="padding: 8px;">Profilnamn</th>';
        html += '</tr></thead><tbody>';

        for (const c of contacts) {
            const name = escapeHtml(c.name || c.nickName || '');
            const number = escapeHtml(c.number || '');
            const profileName = escapeHtml(
                (c.profile && (c.profile.givenName || '')) +
                (c.profile && c.profile.familyName ? ' ' + c.profile.familyName : '')
            ).trim();

            html += '<tr style="border-bottom: 1px solid #222;">';
            html += '<td style="padding: 8px;">' + (name || '<span style="color:#666;">—</span>') + '</td>';
            html += '<td style="padding: 8px; font-family: monospace;">' + number + '</td>';
            html += '<td style="padding: 8px; color: #888;">' + (profileName || '—') + '</td>';
            html += '</tr>';
        }

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (error) {
        container.innerHTML = '<div class="empty-state" style="color: #ff5252;">Kunde inte ladda kontakter: ' + escapeHtml(error.message) + '</div>';
    }
}

async function refreshContacts() {
    const container = document.getElementById('contacts-list');
    container.innerHTML = '<div class="empty-state">Hämtar kontakter från signal-cli...</div>';

    try {
        const token = await getApiToken();
        const response = await fetch('/api/contacts/refresh', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        const data = await response.json();

        if (response.ok && data.success) {
            showConfigMessage('Kontaktlistan uppdaterad (' + (data.contacts || []).length + ' kontakter)', 'success');
            await loadContacts();
        } else {
            container.innerHTML = '<div class="empty-state" style="color: #ff5252;">' + escapeHtml(data.error || 'Kunde inte hämta kontakter') + '</div>';
        }
    } catch (error) {
        container.innerHTML = '<div class="empty-state" style="color: #ff5252;">Nätverksfel: ' + escapeHtml(error.message) + '</div>';
    }
}
