// groups.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMsg,
//              currentIgnoredGroups, currentWhitelistGroups)
//
// Fetches and renders the groups list, handles ignore/whitelist toggles
// and the join-group form submission.

async function fetchGroups() {
    try {
        const response = await fetch('/api/groups');
        const data = await response.json();
        const container = document.getElementById('groups-container');
        currentIgnoredGroups = data.ignoredGroups || [];
        currentWhitelistGroups = data.whitelistGroups || [];

        if (!data.groups || data.groups.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga grupper hittades</div>';
            return;
        }

        container.innerHTML = data.groups.map(group => {
            const isIgnored = currentIgnoredGroups.includes(group.name);
            const isWhitelisted = currentWhitelistGroups.includes(group.name);
            return `
                <div class="group-item ${isIgnored ? 'ignored' : ''} ${isWhitelisted ? 'whitelisted' : ''}" data-group-name="${escapeHtml(group.name)}">
                    <div class="group-info">
                        <div class="group-name">${escapeHtml(group.name)}</div>
                        <div class="group-meta">${group.memberCount} medlemmar</div>
                    </div>
                    <div class="group-buttons">
                        <button class="toggle-ignore ${isIgnored ? 'ignored' : ''}"
                                onclick="toggleIgnoreGroup('${escapeHtml(group.name)}')"
                                title="${isIgnored ? 'Sluta ignorera' : 'Ignorera grupp'}">
                            ${isIgnored ? '✓ Ignorerad' : 'Ignorera'}
                        </button>
                        <button class="toggle-whitelist ${isWhitelisted ? 'whitelisted' : ''}"
                                onclick="toggleWhitelistGroup('${escapeHtml(group.name)}')"
                                title="${isWhitelisted ? 'Ta bort från whitelist' : 'Lägg till i whitelist'}">
                            ${isWhitelisted ? '✓ Whitelist' : 'Whitelist'}
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error fetching groups:', error);
    }
}

async function toggleIgnoreGroup(groupName) {
    try {
        const token = await getApiToken();
        const response = await fetch('/api/toggle-ignore-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ groupName })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('Grupp uppdaterad! Ändringen appliceras direkt.', 'success');
            await fetchGroups();
            await loadConfigForm();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function toggleWhitelistGroup(groupName) {
    try {
        const token = await getApiToken();
        const response = await fetch('/api/toggle-whitelist-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ groupName })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showConfigMessage('Whitelist uppdaterad! Ändringen appliceras direkt.', 'success');
            await fetchGroups();
            await loadConfigForm();
        } else {
            alert(result.error || 'Något gick fel');
        }
    } catch (error) {
        alert('Nätverksfel: ' + error.message);
    }
}

async function handleJoinGroupSubmit(e) {
    e.preventDefault();
    const linkInput = document.getElementById('group-link');
    const submitBtn = document.getElementById('join-btn');
    const messageDiv = document.getElementById('join-message');
    const link = linkInput.value.trim();

    if (!link) return;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Går med...';
    messageDiv.className = 'message';
    messageDiv.textContent = '';

    try {
        const token = await getApiToken();
        const response = await fetch('/api/join-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ link })
        });
        const result = await response.json();

        if (response.ok && result.success) {
            messageDiv.className = 'message success';
            messageDiv.textContent = result.message || 'Gick med i gruppen!';
            linkInput.value = '';
        } else {
            messageDiv.className = 'message error';
            messageDiv.textContent = result.error || 'Kunde inte gå med i gruppen';
        }
    } catch (error) {
        messageDiv.className = 'message error';
        messageDiv.textContent = 'Nätverksfel: ' + error.message;
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Gå med i grupp';
    }
}
