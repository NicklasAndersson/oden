// groups.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Fetches and renders the groups list and handles group administration.

// Cache full group data for the edit modal
let _groupsCache = [];

async function fetchGroups() {
    try {
        const response = await fetch('/api/groups');
        const data = await response.json();
        const container = document.getElementById('groups-container');
        _groupsCache = data.groups || [];

        if (_groupsCache.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga grupper hittades</div>';
            return;
        }

        container.innerHTML = _groupsCache.map(group => {
            const editBtn = group.isAdmin
                ? `<button class="btn btn-secondary btn-sm" onclick="openGroupEditModal('${escapeHtml(group.id)}')" title="Redigera grupp">Redigera</button>`
                : '';
            return `
                <div class="group-item" data-group-name="${escapeHtml(group.name)}">
                    <div class="group-header">
                        <div class="group-name">${escapeHtml(group.name)}</div>
                        <div class="group-buttons">${editBtn}</div>
                    </div>
                    ${_renderGroupMemberTree(group)}
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error fetching groups:', error);
    }
}

function _renderGroupMemberTree(group) {
    if (!group.memberCount) {
        return '<div class="group-meta">0 medlemmar</div>';
    }
    const members = group.members || [];
    if (!members.length) {
        return `<div class="group-meta">${group.memberCount} medlemmar (uppdatera för att se namn)</div>`;
    }
    const rows = members.map(m => {
        const name = escapeHtml(m.name && m.name !== 'Okänd' ? m.name : '');
        const number = escapeHtml(m.number || 'Okänd medlem');
        const adminBadge = m.role === 'ADMINISTRATOR' ? '<span class="admin-badge">Admin</span>' : '';
        const blockedBadge = m.isBlocked ? '<span class="blocked-badge">Blockerad</span>' : '';
        const note = m.note ? `<div class="member-note">${escapeHtml(m.note)}</div>` : '';
        return `<li><span class="mono">${number}</span>${name ? ' — ' + name : ''}${adminBadge}${blockedBadge}${note}</li>`;
    }).join('');
    return `
        <details class="group-members">
            <summary>${group.memberCount} medlemmar</summary>
            <ul class="group-member-list">${rows}</ul>
        </details>
    `;
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

    // Determine link setting; signal-cli only provides the URL, not the mode,
    // so we cannot distinguish 'enabled' from 'enabled-with-approval' here.
    // Store the original value to avoid sending unchanged settings on save.
    const linkSelect = document.getElementById('group-edit-link');
    if (!group.groupInviteLink) {
        linkSelect.value = 'disabled';
    } else {
        linkSelect.value = 'enabled';
    }
    linkSelect.dataset.original = linkSelect.value;

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
        const number = escapeHtml(m.number || 'Okänd medlem');
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

    const linkSelect = document.getElementById('group-edit-link');
    const payload = {
        groupId: document.getElementById('group-edit-id').value,
        name: document.getElementById('group-edit-name').value,
        description: document.getElementById('group-edit-description').value,
        expiration: parseInt(document.getElementById('group-edit-expiration').value, 10),
        setPermissionAddMember: document.getElementById('group-edit-perm-add').value,
        setPermissionEditDetails: document.getElementById('group-edit-perm-edit').value,
        setPermissionSendMessages: document.getElementById('group-edit-perm-send').value,
    };
    // Only send link if the user explicitly changed it (we cannot detect
    // 'enabled' vs 'enabled-with-approval' from signal-cli data alone).
    if (linkSelect.value !== linkSelect.dataset.original) {
        payload.link = linkSelect.value;
    }

    try {
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const response = await fetch('/api/groups/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        const response = await fetch('/api/groups/refresh', {
            method: 'POST',
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
        const response = await fetch('/api/join-group', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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

// ========== Create group ==========

async function loadCreateGroupContacts() {
    const container = document.getElementById('create-group-contacts');
    try {
        const response = await fetch('/api/contacts');
        const data = await response.json();
        const contacts = data.contacts || [];

        if (contacts.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga kontakter hittades</div>';
            return;
        }

        container.innerHTML = contacts.map(c => {
            const number = escapeHtml(c.number || '');
            const name = escapeHtml(c.name || c.nickName || number);
            return `<label style="display: block; padding: 3px 0;"><input type="checkbox" value="${number}"> ${name}</label>`;
        }).join('');
    } catch (error) {
        container.innerHTML = '<div class="empty-state">Kunde inte ladda kontakter</div>';
    }
}

async function handleCreateGroupSubmit(e) {
    e.preventDefault();
    const nameInput = document.getElementById('create-group-name');
    const submitBtn = document.getElementById('create-group-btn');
    const messageDiv = document.getElementById('create-group-message');
    const name = nameInput.value.trim();

    if (!name) return;

    const checked = Array.from(
        document.querySelectorAll('#create-group-contacts input[type="checkbox"]:checked')
    ).map(cb => cb.value);

    const manualInput = document.getElementById('create-group-add-number');
    const manualNumbers = manualInput.value.split(',').map(s => s.trim()).filter(Boolean);

    const member = [...new Set([...checked, ...manualNumbers])];

    submitBtn.disabled = true;
    submitBtn.textContent = 'Skapar...';
    messageDiv.className = 'message';
    messageDiv.textContent = '';

    try {
        const response = await fetch('/api/groups/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, member }),
        });
        const result = await response.json();

        if (response.ok && result.success) {
            messageDiv.className = 'message success';
            messageDiv.textContent = 'Grupp skapad!';
            nameInput.value = '';
            manualInput.value = '';
            document.querySelectorAll('#create-group-contacts input[type="checkbox"]:checked')
                .forEach(cb => { cb.checked = false; });
            await fetchGroups();
        } else {
            messageDiv.className = 'message error';
            messageDiv.textContent = result.error || 'Kunde inte skapa grupp';
        }
    } catch (error) {
        messageDiv.className = 'message error';
        messageDiv.textContent = 'Nätverksfel: ' + error.message;
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Skapa grupp';
    }
}
