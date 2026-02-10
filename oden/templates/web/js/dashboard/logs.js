// logs.js — Depends on: shared.js (escapeHtml)
//
// Fetches and renders the live log stream from the API.

async function fetchLogs() {
    try {
        const response = await fetch('/api/logs');
        const logs = await response.json();
        const container = document.getElementById('log-container');

        if (logs.length === 0) {
            container.innerHTML = '<div class="empty-state">Inga loggar ännu</div>';
            return;
        }

        container.innerHTML = logs.map(log => `
            <div class="log-entry">
                <span class="log-time">${log.timestamp.split(' ')[1]}</span>
                <span class="log-level ${log.level}">${log.level}</span>
                <span class="log-name">${log.name.split('.').pop()}</span>
                <span class="log-message">${escapeHtml(log.message)}</span>
            </div>
        `).join('');

        // Auto-scroll to bottom
        container.scrollTop = container.scrollHeight;
    } catch (error) {
        console.error('Error fetching logs:', error);
    }
}
