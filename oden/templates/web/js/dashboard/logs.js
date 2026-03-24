// logs.js — Depends on: shared.js (escapeHtml)
//
// Fetches and renders the live log stream from the API.
// Only updates the DOM when new entries arrive, preserving scroll position
// unless the user is already scrolled to the bottom.

let _lastLogCount = 0;
let _lastLogTimestamp = '';

function _isScrolledToBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 30;
}

async function fetchLogs() {
    try {
        const response = await fetch('/api/logs');
        const logs = await response.json();
        const container = document.getElementById('log-container');

        if (logs.length === 0) {
            if (_lastLogCount !== 0) {
                container.innerHTML = '<div class="empty-state">Inga loggar ännu</div>';
                _lastLogCount = 0;
                _lastLogTimestamp = '';
            }
            return;
        }

        // Check if anything changed since last fetch
        const newTimestamp = logs[logs.length - 1].timestamp;
        if (logs.length === _lastLogCount && newTimestamp === _lastLogTimestamp) {
            return;  // No changes, skip DOM update
        }

        const wasAtBottom = _isScrolledToBottom(container);

        container.innerHTML = logs.map(log => `
            <div class="log-entry">
                <span class="log-time">${log.timestamp.split(' ')[1]}</span>
                <span class="log-level ${log.level}">${log.level}</span>
                <span class="log-name">${log.name.split('.').pop()}</span>
                <span class="log-message">${escapeHtml(log.message)}</span>
            </div>
        `).join('');

        _lastLogCount = logs.length;
        _lastLogTimestamp = newTimestamp;

        // Only auto-scroll if user was already at the bottom
        if (wasAtBottom) {
            container.scrollTop = container.scrollHeight;
        }
    } catch (error) {
        console.error('Error fetching logs:', error);
    }
}
