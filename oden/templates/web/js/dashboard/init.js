// init.js — Wiring only. Depends on: ALL other modules. Must be included last.
//
// Registers event listeners, starts polling intervals, and triggers
// initial data fetches. No business logic lives here.

// ========== Initial Data Fetches ==========
fetchLogs();
fetchInvitations();
fetchGroups();
loadConfigForm();
loadSignalConfig();

// ========== Polling Intervals ==========
setInterval(fetchLogs, 3000);          // Logs: every 3 seconds
setInterval(fetchInvitations, 10000);  // Invitations: every 10 seconds
setInterval(fetchGroups, 30000);       // Groups: every 30 seconds

// ========== Form Handlers ==========
document.getElementById('join-group-form').addEventListener('submit', handleJoinGroupSubmit);

// Prevent form submission on Enter (auto-save handles saving)
['config-form', 'config-form-advanced'].forEach(formId => {
    document.getElementById(formId).addEventListener('submit', e => e.preventDefault());
});

// ========== Auto-Save on Change ==========
['config-form', 'config-form-advanced'].forEach(formId => {
    const form = document.getElementById(formId);
    form.addEventListener('input', autoSaveConfig);
    form.addEventListener('change', autoSaveConfig);
});
