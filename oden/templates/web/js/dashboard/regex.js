// regex.js — Depends on: shared.js
//
// Regex pattern editor for custom extraction rules in the config form.

function createRegexHeader() {
    const header = document.createElement('div');
    header.className = 'regex-header';
    header.innerHTML = '<span>Namn</span><span>Mönster (regex)</span><span></span>';
    return header;
}

function loadRegexPatterns(patterns) {
    const container = document.getElementById('regex-patterns-list');
    container.innerHTML = '';
    const entries = Object.entries(patterns);
    if (entries.length > 0) {
        container.appendChild(createRegexHeader());
        entries.forEach(([name, pattern]) => addRegexRow(name, pattern));
    }
}

function addRegexRow(name, pattern) {
    const container = document.getElementById('regex-patterns-list');
    // Add header if this is the first row
    if (!container.querySelector('.regex-header')) {
        container.appendChild(createRegexHeader());
    }
    const row = document.createElement('div');
    row.className = 'regex-row';

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'regex-name';
    nameInput.placeholder = 't.ex. registration_number';
    nameInput.value = name || '';

    const patternInput = document.createElement('input');
    patternInput.type = 'text';
    patternInput.className = 'regex-pattern';
    patternInput.placeholder = 't.ex. [A-Z]{3}[0-9]{2}[A-Z0-9]';
    patternInput.value = pattern || '';

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn-remove';
    removeBtn.title = 'Ta bort';
    removeBtn.textContent = '✕';
    removeBtn.addEventListener('click', function() { removeRegexRow(this); });

    row.appendChild(nameInput);
    row.appendChild(patternInput);
    row.appendChild(removeBtn);
    container.appendChild(row);

    // Track changes
    nameInput.addEventListener('input', updateDirtyState);
    patternInput.addEventListener('input', updateDirtyState);
    updateDirtyState();
}

function removeRegexRow(btn) {
    const row = btn.closest('.regex-row');
    row.remove();
    // Remove header if no rows left
    const container = document.getElementById('regex-patterns-list');
    if (!container.querySelector('.regex-row')) {
        container.innerHTML = '';
    }
    updateDirtyState();
}

function collectRegexPatterns() {
    const patterns = {};
    document.querySelectorAll('#regex-patterns-list .regex-row').forEach(row => {
        const name = row.querySelector('.regex-name').value.trim();
        const pattern = row.querySelector('.regex-pattern').value.trim();
        if (name && pattern) {
            patterns[name] = pattern;
        }
    });
    return patterns;
}
