// obsidian.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Obsidian tab: status of the vault and installing Oden's .obsidian settings.
// Vault path and directory structure are ordinary auto-saved config fields.

async function loadObsidianStatus() {
    const box = document.getElementById('obsidian-status');
    const button = document.getElementById('obsidian-install-btn');
    try {
        const response = await fetch('/api/obsidian/status');
        const data = await response.json();
        const parts = [`Valv: ${escapeHtml(data.vault_path)}${data.vault_exists ? '' : ' (skapas vid första rapporten)'}`];
        if (data.obsidian_installed) {
            parts.push('Obsidian-inställningar finns i valvet.');
        } else if (!data.template_available) {
            parts.push('Obsidian-mallen saknas i den här installationen.');
        } else {
            parts.push('Inga Obsidian-inställningar i valvet än.');
        }
        box.innerHTML = parts.join('<br>');
        button.disabled = data.obsidian_installed || !data.template_available;
    } catch (e) {
        box.textContent = 'Kunde inte läsa valvets status';
    }
}

async function installObsidianTemplate() {
    try {
        const response = await fetch('/api/obsidian/install-template', {method: 'POST'});
        const data = await response.json();
        showConfigMessage(data.message || data.error, data.success ? 'success' : 'error');
    } catch (e) {
        showConfigMessage('Kunde inte installera Obsidian-inställningarna', 'error');
    }
    loadObsidianStatus();
}
