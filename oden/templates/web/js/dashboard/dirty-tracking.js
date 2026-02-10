// dirty-tracking.js — Depends on: shared.js, regex.js (collectRegexPatterns)
//
// Tracks unsaved changes in the config form and shows visual indicators
// (banner, per-tab dots) when the user has modified settings.

let originalConfig = {};
let configDirty = false;

// Field IDs per tab for per-tab dirty dots
const basicFieldIds = [
    'cfg-signal-number', 'cfg-display-name', 'cfg-vault-path', 'cfg-timezone',
    'cfg-append-window', 'cfg-startup-message', 'cfg-filename-format',
    'cfg-plus-plus', 'cfg-ignored-groups', 'cfg-whitelist-groups'
];
const advancedFieldIds = [
    'cfg-signal-host', 'cfg-signal-port', 'cfg-signal-path', 'cfg-unmanaged',
    'cfg-web-enabled', 'cfg-web-port', 'cfg-log-level'
];

function getFieldValue(id) {
    const el = document.getElementById(id);
    if (!el) return '';
    return el.type === 'checkbox' ? el.checked : el.value;
}

function snapshotConfig() {
    originalConfig = {};
    [...basicFieldIds, ...advancedFieldIds].forEach(id => {
        originalConfig[id] = getFieldValue(id);
    });
    originalConfig._regex = JSON.stringify(collectRegexPatterns());
}

function isFieldDirty(id) {
    if (!(id in originalConfig)) return false;
    return getFieldValue(id) !== originalConfig[id];
}

function updateDirtyState() {
    const basicDirty = basicFieldIds.some(isFieldDirty);
    const regexDirty = '_regex' in originalConfig &&
        JSON.stringify(collectRegexPatterns()) !== originalConfig._regex;
    const advDirty = advancedFieldIds.some(isFieldDirty) || regexDirty;
    configDirty = basicDirty || advDirty;

    // Banner
    const indicator = document.getElementById('unsaved-indicator');
    if (indicator) {
        indicator.classList.toggle('show', configDirty);
    }

    // Tab dots
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        const label = btn.textContent.trim();
        if (label === 'Grundläggande') {
            btn.classList.toggle('has-changes', basicDirty);
        } else if (label === 'Avancerat') {
            btn.classList.toggle('has-changes', advDirty);
        }
    });
}
