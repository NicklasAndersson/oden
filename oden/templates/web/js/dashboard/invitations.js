// invitations.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMsg)
//
// Fetches and renders pending group invitations, handles accept/decline.

async function fetchInvitations() {
    try {
        const response = await fetch('/api/invitations');
        const invitations = await response.json();
        const container = document.getElementById('invitations-container');

        if (!invitations || invitations.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga väntande inbjudningar</div>';
            return;
        }

        container.innerHTML = invitations.map(inv => `
            <div class="invitation-item" data-group-id="${escapeHtml(inv.id)}">
                <div class="invitation-info">
                    <div class="invitation-name">${escapeHtml(inv.name || 'Okänd grupp')}</div>
                    <div class="invitation-meta">${inv.memberCount || '?'} medlemmar</div>
                </div>
                <div class="invitation-actions">
                    <button class="btn btn-sm btn-success" onclick="handleInvitation('${escapeHtml(inv.id)}', 'accept')">Acceptera</button>
                    <button class="btn btn-sm btn-danger" onclick="handleInvitation('${escapeHtml(inv.id)}', 'decline')">Avböj</button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Error fetching invitations:', error);
    }
}

async function handleInvitation(groupId, action) {
    const item = document.querySelector(`[data-group-id="${groupId}"]`);
    const buttons = item.querySelectorAll('button');
    buttons.forEach(btn => btn.disabled = true);

    try {
        const token = await getApiToken();
        const response = await fetch(`/api/invitations/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ groupId })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            item.style.opacity = '0.5';
            item.innerHTML = `<div class="invitation-info"><div class="invitation-name">${result.message}</div></div>`;
            setTimeout(() => fetchInvitations(), 2000);
        } else {
            alert(result.error || 'Något gick fel');
            buttons.forEach(btn => btn.disabled = false);
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
        buttons.forEach(btn => btn.disabled = false);
    }
}
