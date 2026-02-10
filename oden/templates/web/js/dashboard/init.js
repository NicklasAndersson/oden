// init.js — Wiring only. Depends on: ALL other modules. Must be included last.
//
// Registers event listeners, starts polling intervals, and triggers
// initial data fetches. No business logic lives here.

// ========== Initial Data Fetches ==========
fetchLogs();
fetchInvitations();
fetchGroups();
loadConfigForm();

// ========== Polling Intervals ==========
setInterval(fetchLogs, 3000);          // Logs: every 3 seconds
setInterval(fetchInvitations, 10000);  // Invitations: every 10 seconds
setInterval(fetchGroups, 30000);       // Groups: every 30 seconds

// ========== Form Handlers ==========
document.getElementById('join-group-form').addEventListener('submit', handleJoinGroupSubmit);
document.getElementById('config-form').addEventListener('submit', saveConfigForm);
document.getElementById('config-form-advanced').addEventListener('submit', saveConfigForm);

// ========== Change Tracking ==========
['config-form', 'config-form-advanced'].forEach(formId => {
    const form = document.getElementById(formId);
    form.addEventListener('input', updateDirtyState);
    form.addEventListener('change', updateDirtyState);
});

// ========== Unsaved Changes Warning ==========
window.addEventListener('beforeunload', function(e) {
    if (configDirty) {
        e.preventDefault();
        e.returnValue = '';
    }
});
