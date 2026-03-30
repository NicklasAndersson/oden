// accounts.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Signal account management: list, link (add), activate, delete, force-delete.

let linkPollInterval = null;
let accountsRetryTimeout = null;

async function loadAccounts() {
    const container = document.getElementById('accounts-list');
    const warning = document.getElementById('accounts-warning');

    // Clear any pending retry
    if (accountsRetryTimeout) {
        clearTimeout(accountsRetryTimeout);
        accountsRetryTimeout = null;
    }

    try {
        const response = await fetch('/api/accounts');
        const data = await response.json();

        const accounts = data.accounts || [];
        const activeValid = data.active_valid;
        const connected = data.connected;

        // If not connected to signal-cli, show connecting state and auto-retry
        if (!connected && accounts.length === 0) {
            warning.classList.add('hidden');
            container.innerHTML = '<div class="empty-state">⏳ Ansluter till signal-cli... Kontolistan laddas automatiskt.</div>';
            accountsRetryTimeout = setTimeout(loadAccounts, 3000);
            return;
        }

        // Show warning if active account is invalid (only when connected)
        if (!activeValid && data.active_number && connected) {
            warning.classList.remove('hidden');
            document.getElementById('accounts-warning-text').textContent =
                'Det konfigurerade kontot (' + escapeHtml(data.active_number) + ') finns inte bland de tillgängliga kontona. Välj ett giltigt konto eller lägg till ett nytt.';
        } else {
            warning.classList.add('hidden');
        }

        if (accounts.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga konton hittades. Klicka "Lägg till konto" för att länka ett Signal-konto.</div>';
            return;
        }

        container.innerHTML = '';
        for (const acc of accounts) {
            const num = acc.number;
            const isActive = acc.active;

            const row = document.createElement('div');
            row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; padding: 12px 15px; border: 1px solid ' + (isActive ? '#2e7d32' : '#333') + '; border-radius: 8px; margin-bottom: 8px; background: ' + (isActive ? '#1a3a1a' : '#16213e') + ';';

            const info = document.createElement('div');
            const strong = document.createElement('strong');
            strong.style.fontSize = '1.05em';
            strong.textContent = num;
            info.appendChild(strong);

            if (isActive) {
                const badge = document.createElement('span');
                badge.style.cssText = 'color: #4caf50; font-size: 0.9em; margin-left: 8px;';
                badge.textContent = '● Aktivt konto';
                info.appendChild(badge);
            }

            const actions = document.createElement('div');
            actions.style.cssText = 'display: flex; gap: 8px;';

            if (!isActive) {
                const useBtn = document.createElement('button');
                useBtn.className = 'btn btn-primary';
                useBtn.style.cssText = 'padding: 5px 12px; font-size: 0.85em;';
                useBtn.textContent = 'Använd';
                useBtn.addEventListener('click', () => activateAccount(num));

                const delBtn = document.createElement('button');
                delBtn.className = 'btn btn-secondary';
                delBtn.style.cssText = 'padding: 5px 12px; font-size: 0.85em;';
                delBtn.textContent = 'Radera';
                delBtn.addEventListener('click', () => deleteAccount(num));

                const forceBtn = document.createElement('button');
                forceBtn.className = 'btn btn-secondary';
                forceBtn.style.cssText = 'padding: 5px 12px; font-size: 0.85em; color: #ff5252;';
                forceBtn.textContent = 'Tvinga radering';
                forceBtn.addEventListener('click', () => forceDeleteAccount(num));

                actions.appendChild(useBtn);
                actions.appendChild(delBtn);
                actions.appendChild(forceBtn);
            } else {
                const note = document.createElement('span');
                note.style.cssText = 'color: #888; font-size: 0.85em; padding: 5px 0;';
                note.textContent = 'Kan inte raderas medan aktivt';
                actions.appendChild(note);
            }

            row.appendChild(info);
            row.appendChild(actions);
            container.appendChild(row);
        }

    } catch (error) {
        container.innerHTML = '<div class="empty-state" style="color: #ff5252;">Kunde inte ladda konton: ' + escapeHtml(error.message) + '</div>';
    }
}

async function activateAccount(number) {
    if (!confirm('Vill du byta aktivt konto till ' + number + '?\n\nMeddelanden kommer att behandlas för det nya kontot.')) {
        return;
    }

    try {
        const response = await fetch('/api/accounts/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ number })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('Aktivt konto ändrat till ' + number, 'success');
            await loadAccounts();
            await loadConfigForm();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function deleteAccount(number) {
    if (!confirm('Vill du radera alla lokala data för kontot ' + number + '?\n\nDetta tar bort kontodata från signal-cli men avregistrerar inte kontot från Signals servrar.')) {
        return;
    }

    try {
        const response = await fetch('/api/accounts/' + encodeURIComponent(number), {
            method: 'DELETE',
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage(result.message, 'success');
            await loadAccounts();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function forceDeleteAccount(number) {
    if (!confirm('⚠️ VARNING: Tvångsradering!\n\nDetta raderar kontodatan direkt från filsystemet.\nAnvänd detta bara om kontot är korrupt och inte kan raderas normalt.\n\nVill du fortsätta med tvångsradering av ' + number + '?')) {
        return;
    }

    try {
        const response = await fetch('/api/accounts/' + encodeURIComponent(number) + '/force', {
            method: 'DELETE',
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage(result.message, 'success');
            await loadAccounts();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function startAccountLink() {
    const modal = document.getElementById('account-link-modal');
    const qrContainer = document.getElementById('link-qr-container');
    const statusText = document.getElementById('link-status-text');
    const successDiv = document.getElementById('link-success');
    const cancelBtn = document.getElementById('link-cancel-btn');
    const doneBtn = document.getElementById('link-done-btn');

    // Show modal
    modal.classList.remove('hidden');
    qrContainer.innerHTML = '<div class="empty-state" style="color: #333;">Genererar QR-kod...</div>';
    statusText.textContent = 'Ansluter till signal-cli...';
    successDiv.style.display = 'none';
    cancelBtn.style.display = '';
    doneBtn.style.display = 'none';

    try {
        const response = await fetch('/api/accounts/link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_name: 'Oden' })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            qrContainer.innerHTML = result.qr_svg;
            statusText.textContent = 'Skanna QR-koden med Signal-appen på din telefon';

            // Start polling for link completion
            linkPollInterval = setInterval(pollLinkStatus, 2000);
        } else {
            qrContainer.innerHTML = '<div class="empty-state" style="color: #c00;">Fel!</div>';
            statusText.textContent = result.error || 'Kunde inte starta länkning';
        }
    } catch (error) {
        qrContainer.innerHTML = '<div class="empty-state" style="color: #c00;">Nätverksfel</div>';
        statusText.textContent = error.message;
    }
}

async function pollLinkStatus() {
    try {
        const response = await fetch('/api/accounts/link-status');
        const data = await response.json();

        if (data.status === 'linked') {
            clearInterval(linkPollInterval);
            linkPollInterval = null;

            const statusText = document.getElementById('link-status-text');
            const successDiv = document.getElementById('link-success');
            const cancelBtn = document.getElementById('link-cancel-btn');
            const doneBtn = document.getElementById('link-done-btn');

            statusText.style.display = 'none';
            successDiv.style.display = 'block';
            document.getElementById('link-success-number').textContent = ' ' + data.linked_number;
            cancelBtn.style.display = 'none';
            doneBtn.style.display = '';
        } else if (data.status === 'error') {
            clearInterval(linkPollInterval);
            linkPollInterval = null;

            document.getElementById('link-status-text').textContent = data.error || 'Länkning misslyckades';
            document.getElementById('link-qr-container').innerHTML = '<div class="empty-state" style="color: #c00;">Misslyckades</div>';
        }
    } catch (error) {
        // Network error during poll, keep trying
        console.error('Poll error:', error);
    }
}

async function cancelAccountLink() {
    if (linkPollInterval) {
        clearInterval(linkPollInterval);
        linkPollInterval = null;
    }

    // Inform the server to cancel the link operation
    try {
        await fetch('/api/accounts/link-cancel', {
            method: 'POST',
        });
    } catch (error) {
        console.error('Failed to cancel account link on server:', error);
    }

    document.getElementById('account-link-modal').classList.add('hidden');
}

function finishAccountLink() {
    document.getElementById('account-link-modal').classList.add('hidden');
    loadAccounts();
}

async function loadDevices() {
    const container = document.getElementById('devices-list');
    container.innerHTML = '<div class="empty-state">Hämtar enheter...</div>';

    try {
        const response = await fetch('/api/accounts/devices');
        const data = await response.json();
        const devices = data.devices || [];

        if (devices.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga enheter hittades.</div>';
            return;
        }

        let html = '<table style="width: 100%; border-collapse: collapse;">';
        html += '<thead><tr style="border-bottom: 1px solid #333; text-align: left;">';
        html += '<th style="padding: 8px;">ID</th>';
        html += '<th style="padding: 8px;">Namn</th>';
        html += '<th style="padding: 8px;">Skapad</th>';
        html += '<th style="padding: 8px;">Senast sedd</th>';
        html += '</tr></thead><tbody>';

        for (const d of devices) {
            const created = d.createdTimestamp ? new Date(d.createdTimestamp).toLocaleDateString('sv-SE') : '—';
            const lastSeen = d.lastSeenTimestamp ? new Date(d.lastSeenTimestamp).toLocaleString('sv-SE') : '—';

            html += '<tr style="border-bottom: 1px solid #222;">';
            html += '<td style="padding: 8px;">' + escapeHtml(String(d.id || '')) + '</td>';
            html += '<td style="padding: 8px;">' + escapeHtml(d.name || '—') + '</td>';
            html += '<td style="padding: 8px;">' + created + '</td>';
            html += '<td style="padding: 8px;">' + lastSeen + '</td>';
            html += '</tr>';
        }

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (error) {
        container.innerHTML = '<div class="empty-state" style="color: #ff5252;">Kunde inte hämta enheter: ' + escapeHtml(error.message) + '</div>';
    }
}
