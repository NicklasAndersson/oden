// shared.js — No dependencies. Must be included first.
//
// Shared state and utility functions used across all dashboard modules.

// ========== Utility Functions ==========

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
        msgDiv.querySelector('.icon').textContent = '⚠️';
    }
    msgDiv.classList.add('show');
    setTimeout(() => msgDiv.classList.remove('show'), 5000);
}
