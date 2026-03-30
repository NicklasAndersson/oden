// contacts.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMessage)
//
// Contact list display, refresh from signal-cli, and contact editing modal.

// Cache contacts data for the edit modal
let _contactsCache = [];

async function loadContacts() {
    const container = document.getElementById('contacts-list');

    try {
        const response = await fetch('/api/contacts');
        const data = await response.json();
        _contactsCache = data.contacts || [];

        if (_contactsCache.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga kontakter hittades. Klicka "Uppdatera från Signal" för att hämta.</div>';
            return;
        }

        let html = '<table style="width: 100%; border-collapse: collapse;">';
        html += '<thead><tr style="border-bottom: 1px solid #333; text-align: left;">';
        html += '<th style="padding: 8px;">Namn</th>';
        html += '<th style="padding: 8px;">Nummer</th>';
        html += '<th style="padding: 8px;">Profilnamn</th>';
        html += '<th style="padding: 8px;"></th>';
        html += '</tr></thead><tbody>';

        for (const c of _contactsCache) {
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
            html += '<td style="padding: 8px; text-align: right; white-space: nowrap;"><button class="btn btn-secondary btn-sm" onclick="openContactEditModal(\'' + number + '\')">Redigera</button></td>';
            html += '</tr>';
        }

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (error) {
        container.innerHTML = '<div class="empty-state" style="color: #ff5252;">Kunde inte ladda kontakter: ' + escapeHtml(error.message) + '</div>';
    }
}

// ========== Contact edit modal ==========

function openContactEditModal(number) {
    const contact = _contactsCache.find(c => c.number === number);

    document.getElementById('contact-edit-number').value = number;
    document.getElementById('contact-edit-number-display').value = number;
    document.getElementById('contact-edit-given-name').value = (contact && contact.givenName) || '';
    document.getElementById('contact-edit-family-name').value = (contact && contact.familyName) || '';
    document.getElementById('contact-edit-nick').value = (contact && contact.nickName) || (contact && contact.nickGivenName) || '';
    document.getElementById('contact-edit-note').value = (contact && contact.note) || '';
    document.getElementById('contact-edit-expiration').value = String((contact && contact.messageExpirationTime) || 0);
    document.getElementById('contact-edit-message').textContent = '';

    document.getElementById('contact-edit-modal').classList.remove('hidden');
}

function closeContactEditModal() {
    document.getElementById('contact-edit-modal').classList.add('hidden');
}

async function saveContactChanges() {
    const btn = document.getElementById('contact-edit-save-btn');
    const msgDiv = document.getElementById('contact-edit-message');
    btn.disabled = true;
    btn.textContent = 'Sparar...';
    msgDiv.textContent = '';

    const number = document.getElementById('contact-edit-number').value;
    const payload = {
        givenName: document.getElementById('contact-edit-given-name').value,
        familyName: document.getElementById('contact-edit-family-name').value,
        nickGivenName: document.getElementById('contact-edit-nick').value,
        note: document.getElementById('contact-edit-note').value,
        expiration: parseInt(document.getElementById('contact-edit-expiration').value, 10),
    };

    try {
        const response = await authenticatedFetch('/api/contacts/' + encodeURIComponent(number), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (response.ok && result.success) {
            showConfigMessage('Kontakt uppdaterad!', 'success');
            closeContactEditModal();
            await loadContacts();
        } else {
            msgDiv.className = 'message error';
            msgDiv.textContent = result.error || 'Kunde inte spara ändringar';
        }
    } catch (error) {
        msgDiv.className = 'message error';
        msgDiv.textContent = 'Nätverksfel: ' + error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Spara';
    }
}

async function refreshContacts() {
    const container = document.getElementById('contacts-list');
    container.innerHTML = '<div class="empty-state">Hämtar kontakter från signal-cli...</div>';

    try {
        const response = await authenticatedFetch('/api/contacts/refresh', {
            method: 'POST',
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
