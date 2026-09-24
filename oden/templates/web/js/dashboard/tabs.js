// tabs.js — Depends on: responses.js (loadResponses), accounts.js (loadAccounts),
// contacts.js (loadContacts), pipelines.js (loadPipelinesDashboard),
// flow.js (loadFlowDashboard), tak.js (loadTakStatus), obsidian.js (loadObsidianStatus),
// signal_connect.js (loadSignalConnect)
//
// Tab switching with lazy-loading of tab content on first visit. The Signal
// tab has its own row of sub-tabs (panes), each lazy-loaded the same way.

let signalPane = 'accounts';

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

    document.getElementById('tab-' + tabName).classList.add('active');
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if (btn.getAttribute('onclick') === `showTab('${tabName}')`) btn.classList.add('active');
    });

    if (tabName === 'flow') {
        loadFlowDashboard();
    }
    if (tabName === 'signal') {
        showSignalPane(signalPane);
    }
    if (tabName === 'obsidian') {
        loadObsidianStatus();
    }
    if (tabName === 'pipelines') {
        loadPipelinesDashboard();
    }
    if (tabName === 'advanced') {
        loadOdenHome();
    }
    if (tabName === 'tak') {
        loadTakStatus();
    }
}

function showSignalPane(pane) {
    signalPane = pane;
    document.querySelectorAll('#tab-signal .subtab-pane').forEach(el => {
        el.classList.toggle('active', el.id === 'signal-pane-' + pane);
    });
    document.querySelectorAll('#tab-signal .subtab-btn').forEach(btn => {
        const on = btn.dataset.pane === pane;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on);
    });

    if (pane === 'accounts') {
        loadAccounts();
        loadSignalConnect();
    }
    if (pane === 'contacts') {
        loadContacts();
    }
    if (pane === 'responses') {
        loadResponses();
    }
}
