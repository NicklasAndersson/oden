// shared.js — No dependencies. Must be included first.
//
// Shared state and utility functions used across all dashboard modules.

// ========== Shared State ==========
let apiToken = null;
let currentIgnoredGroups = [];
let currentWhitelistGroups = [];

// ========== Utility Functions ==========

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function getApiToken() {
    if (!apiToken) {
        try {
            const response = await fetch('/api/token');
            const data = await response.json();
            apiToken = data.token;
        } catch (error) {
            console.error('Failed to get API token:', error);
        }
    }
    return apiToken;
}

async function authenticatedFetch(url, options) {
    const token = await getApiToken();
    const opts = Object.assign({}, options);
    opts.headers = Object.assign({}, opts.headers);
    if (token) opts.headers['Authorization'] = 'Bearer ' + token;
    const response = await fetch(url, opts);
    if (response.status === 401) {
        // Token may be stale after a server restart — refresh and retry once
        apiToken = null;
        const newToken = await getApiToken();
        if (newToken && newToken !== token) {
            opts.headers['Authorization'] = 'Bearer ' + newToken;
            return fetch(url, opts);
        }
    }
    return response;
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
