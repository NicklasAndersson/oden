// tabs.js — Depends on: responses.js (loadResponses), templates.js (loadTemplate), accounts.js (loadAccounts)
//
// Tab switching with lazy-loading of tab content on first visit.

function showTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

    // Show selected tab
    document.getElementById('tab-' + tabName).classList.add('active');
    event.target.classList.add('active');

    // Load template when switching to templates tab
    if (tabName === 'templates') {
        loadTemplate();
    }
    // Load responses when switching to responses tab
    if (tabName === 'responses') {
        loadResponses();
    }
    // Load accounts when switching to accounts tab
    if (tabName === 'accounts') {
        loadAccounts();
    }
    // Load contacts when switching to contacts tab
    if (tabName === 'contacts') {
        loadContacts();
    }
    // Load message observability dashboard when switching to messages tab
    if (tabName === 'messages') {
        loadMessagesDashboard();
    }
}
