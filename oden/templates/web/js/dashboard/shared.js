// shared.js — No dependencies. Must be included first.
//
// Shared state and utility functions used across all dashboard modules.

// ========== Utility Functions ==========

// Escapes quotes too: the result is used inside attributes (value="…",
// onclick="…('…')"), and group/contact names come straight from Signal.
function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

function showConfigMessage(message, type) {
    const msgDiv = document.getElementById('config-message');
    const msgText = document.getElementById('config-message-text');
    msgDiv.classList.remove('show', 'success');
    msgText.textContent = message;
    if (type === 'success') {
        msgDiv.classList.add('success');
        msgDiv.querySelector('.icon').textContent = '✓';
    } else {
        msgDiv.querySelector('.icon').textContent = '⚠';
    }
    msgDiv.classList.add('show');
    setTimeout(() => msgDiv.classList.remove('show'), 5000);
}
