// groups.js — Depends on: shared.js (getApiToken, escapeHtml, showConfigMsg,
//              currentIgnoredGroups, currentWhitelistGroups)
//
// Fetches and renders the groups list, handles ignore/whitelist toggles,
// join-group form submission, and group administration modal.

// Cache full group data for the edit modal
let _groupsCache = [];

async function fetchGroups() {
    try {
        const response = await fetch('/api/groups');
        const data = await response.json();
        const container = document.getElementById('groups-container');
        currentIgnoredGroups = data.ignoredGroups || [];
        currentWhitelistGroups = data.whitelistGroups || [];
        _groupsCache = data.groups || [];

        if (_groupsCache.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga grupper hittades</div>';
            return;
        }

        container.innerHTML = _groupsCache.map(group => {
            const isIgnored = currentIgnoredGroups.includes(group.name);
            const isWhitelisted = currentWhitelistGroups.includes(group.name);
            const editBtn = group.isAdmin
                ? `<button class="btn btn-secondary btn-sm" onclick="openGroupEditModal('${escapeHtml(group.id)}')" title="Redigera grupp">Redigera</button>`
                : '';
            return `
                <div class="group-item ${isIgnored ? 'ignored' : ''} ${isWhitelisted ? 'whitelisted' : ''}" data-group-name="${escapeHtml(group.name)}">
                    <div class="group-info">
                        <div class="group-name">${escapeHtml(group.name)}</div>
                        <div class="group-meta">${group.memberCount} medlemmar</div>
                    </div>
                    <div class="group-buttons">
                        ${editBtn}
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

// ========== Group edit modal ==========

function openGroupEditModal(groupId) {
    const group = _groupsCache.find(g => g.id === groupId);
    if (!group) return;

    document.getElementById('group-edit-id').value = group.id;
    document.getElementById('group-edit-name').value = group.name || '';
    document.getElementById('group-edit-description').value = group.description || '';
    document.getElementById('group-edit-expiration').value = String(group.messageExpirationTime || 0);
    document.getElementById('group-edit-perm-add').value = group.permissionAddMember || 'every-member';
    document.getElementById('group-edit-perm-edit').value = group.permissionEditDetails || 'every-member';
    document.getElementById('group-edit-perm-send').value = group.permissionSendMessages || 'every-member';
    document.getElementById('group-edit-title').textContent = 'Redigera: ' + (group.name || 'Grupp');

    // Determine link setting from URL presence
    const link = group.groupInviteLink;
    if (!link) {
        document.getElementById('group-edit-link').value = 'disabled';
    } else {
        document.getElementById('group-edit-link').value = 'enabled';
    }

    _renderGroupMembers(group.members || []);

    document.getElementById('group-edit-message').textContent = '';
    document.getElementById('group-edit-modal').classList.remove('hidden');
}

function closeGroupEditModal() {
    document.getElementById('group-edit-modal').classList.add('hidden');
}

function _renderGroupMembers(members) {
    const container = document.getElementById('group-edit-members');
    if (!members.length) {
        container.innerHTML = '<div class="text-muted">Inga medlemmar</div>';
        return;
    }
    container.innerHTML = members.map(m => {
        const name = escapeHtml(m.name && m.name !== 'Okänd' ? m.name : '');
        const number = escapeHtml(m.number || '');
        const isAdmin = m.role === 'ADMINISTRATOR';
        const badge = isAdmin ? '<span style="color: #4caf50; font-size: 0.85em; margin-left: 4px;">Admin</span>' : '';
        const adminBtn = isAdmin
            ? `<button class="btn btn-secondary btn-sm" onclick="toggleGroupAdmin('${number}', false)" title="Ta bort admin">↓ Medlem</button>`
            : `<button class="btn btn-secondary btn-sm" onclick="toggleGroupAdmin('${number}', true)" title="Gör till admin">↑ Admin</button>`;
        return `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border);">
                <div>
                    <span style="font-family: monospace;">${number}</span>
                    ${name ? ' — ' + name : ''}${badge}
                </div>
                <div style="display: flex; gap: 4px;">
                    ${adminBtn}
                    <button class="btn btn-secondary btn-sm" onclick="removeGroupMember('${number}')" title="Ta bort" style="color: #ff5252;">✕</button>
                </div>
            </div>`;
    }).join('');
}

async function saveGroupChanges() {
    const btn = document.getElementById('group-edit-save-btn');
    const msgDiv = document.getElementById('group-edit-message');
    btn.disabled = true;
    btn.textContent = 'Sparar...';
    msgDiv.textContent = '';

    const payload = {
        groupId: document.getElementById('group-edit-id').value,
        name: document.getElementById('group-edit-name').value,
        description: document.getElementById('group-edit-description').value,
        expiration: parseInt(document.getElementById('group-edit-expiration').value, 10),
        setPermissionAddMember: document.getElementById('group-edit-perm-add').value,
        setPermissionEditDetails: document.getElementById('group-edit-perm-edit').value,
        setPermissionSendMessages: document.getElementById('group-edit-perm-send').value,
        link: document.getElementById('group-edit-link').value,
    };

    try {
        const token = await getApiToken();
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (response.ok && result.success) {
            showConfigMessage('Grupp uppdaterad!', 'success');
            closeGroupEditModal();
            await fetchGroups();
        } else {
            msgDiv.className = 'message error';
            msgDiv.textContent = result.error || 'Kunde inte spara ändringar';
        }
    } catch (error) {
        msgDiv.className = 'message error';
        msgDiv.textContent = 'Nätverksfel: ' + error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Spara ändringar';
    }
}

async function addGroupMember() {
    const input = document.getElementById('group-edit-add-member');
    const number = input.value.trim();
    if (!number) return;

    const groupId = document.getElementById('group-edit-id').value;
    try {
        const token = await getApiToken();
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ groupId, member: [number] }),
        });
        const result = await response.json();
        if (response.ok && result.success) {
            input.value = '';
            showConfigMessage('Medlem tillagd!', 'success');
            await fetchGroups();
            // Re-open modal with refreshed data
            openGroupEditModal(groupId);
        } else {
            showConfigMessage(result.error || 'Kunde inte lägga till medlem', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
}

async function removeGroupMember(memberNumber) {
    const groupId = document.getElementById('group-edit-id').value;
    try {
        const token = await getApiToken();
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify({ groupId, removeMember: [memberNumber] }),
        });
        const result = await response.json();
        if (response.ok && result.success) {
            showConfigMessage('Medlem borttagen!', 'success');
            await fetchGroups();
            openGroupEditModal(groupId);
        } else {
            showConfigMessage(result.error || 'Kunde inte ta bort medlem', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
}

async function toggleGroupAdmin(memberNumber, makeAdmin) {
    const groupId = document.getElementById('group-edit-id').value;
    const payload = { groupId };
    if (makeAdmin) {
        payload.admin = [memberNumber];
    } else {
        payload.removeAdmin = [memberNumber];
    }
    try {
        const token = await getApiToken();
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (response.ok && result.success) {
            showConfigMessage(makeAdmin ? 'Medlem gjord till admin!' : 'Admin borttagen!', 'success');
            await fetchGroups();
            openGroupEditModal(groupId);
        } else {
            showConfigMessage(result.error || 'Kunde inte ändra roll', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    }
}

async function refreshGroups() {
    const btn = document.getElementById('refresh-groups-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Uppdaterar...';
    }
    try {
        const token = await getApiToken();
        const response = await fetch('/api/groups/refresh', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
        });
        const result = await response.json();
        if (response.ok && result.success) {
            showConfigMessage('Grupper uppdaterade från signal-cli.', 'success');
        } else {
            showConfigMessage(result.error || 'Kunde inte uppdatera grupper', 'error');
        }
    } catch (error) {
        showConfigMessage('Nätverksfel: ' + error.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Uppdatera';
        }
        await fetchGroups();
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
