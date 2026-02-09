let currentStep = 1;
let linkedNumber = null;
let countdownInterval = null;
let pollInterval = null;
let existingAccounts = [];
let registerPhone = null;

// Check for recovery candidate and set default vault path on page load
fetch('/api/setup/status')
    .then(r => r.json())
    .then(data => {
        document.getElementById('vault-path').value = data.default_vault || '~/oden-vault';

        // If a recovery candidate was found, show the recovery step
        if (data.recovery_candidate) {
            document.getElementById('recovery-path').value = data.recovery_candidate;
            showRecoveryStep();
        }
    });

function hideAllStep2Sections() {
    ['accounts-loading', 'existing-accounts', 'method-selection', 'link-start',
     'link-waiting', 'link-success', 'link-timeout', 'link-error',
     'register-start', 'register-captcha', 'register-verify'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });
}

function showMethodSelection() {
    hideAllStep2Sections();
    document.getElementById('method-selection').classList.remove('hidden');
    if (existingAccounts.length > 0) {
        document.getElementById('existing-accounts').classList.remove('hidden');
    }
}

function showExistingAccounts(accounts) {
    const container = document.getElementById('existing-accounts');
    const list = document.getElementById('accounts-list');

    list.innerHTML = accounts.map((acc, i) => `
        <button class="btn btn-primary" style="margin: 5px; width: auto;"
                onclick="useExistingAccount('${acc.number}')">
            ${acc.number}
        </button>
    `).join('');

    container.classList.remove('hidden');
}

function useExistingAccount(number) {
    linkedNumber = number;
    hideAllStep2Sections();
    document.getElementById('link-success').classList.remove('hidden');
    document.getElementById('linked-number').textContent = number;
}

async function loadExistingAccounts() {
    hideAllStep2Sections();
    document.getElementById('accounts-loading').classList.remove('hidden');

    try {
        const response = await fetch('/api/setup/status?accounts=true');
        const data = await response.json();
        console.log('Existing accounts response:', data);

        document.getElementById('accounts-loading').classList.add('hidden');

        if (data.existing_accounts && data.existing_accounts.length > 0) {
            existingAccounts = data.existing_accounts;
            showExistingAccounts(data.existing_accounts);
        }

        document.getElementById('method-selection').classList.remove('hidden');

    } catch (error) {
        console.error('Error loading existing accounts:', error);
        document.getElementById('accounts-loading').classList.add('hidden');
        document.getElementById('method-selection').classList.remove('hidden');
    }
}

function goToStep(step) {
    document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
    document.getElementById('step-' + step).classList.add('active');

    document.querySelectorAll('.step-dot').forEach((dot, i) => {
        dot.classList.remove('active', 'completed');
        if (i + 1 < step) dot.classList.add('completed');
        if (i + 1 === step) dot.classList.add('active');
    });

    currentStep = step;

    if (step === 2) {
        loadExistingAccounts();
    }

    if (step === 3) {
        document.getElementById('confirm-vault').textContent = document.getElementById('vault-path').value;
        document.getElementById('confirm-number').textContent = linkedNumber || '(ej konfigurerad)';
        document.getElementById('confirm-device').textContent = document.getElementById('device-name')?.value || 'Oden';
    }
}

function startSelectedMethod() {
    const method = document.querySelector('input[name="setup-method"]:checked').value;
    hideAllStep2Sections();
    if (method === 'link') {
        document.getElementById('link-start').classList.remove('hidden');
    } else {
        document.getElementById('register-start').classList.remove('hidden');
    }
}

async function startLinking() {
    const deviceName = document.getElementById('device-name').value || 'Oden';

    hideAllStep2Sections();
    document.getElementById('link-waiting').classList.remove('hidden');

    try {
        const response = await fetch('/api/setup/start-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_name: deviceName })
        });
        const data = await response.json();

        if (data.success && data.qr_svg) {
            const container = document.getElementById('qr-container');
            container.innerHTML = data.qr_svg;
            const svg = container.querySelector('svg');
            if (svg) {
                svg.style.width = '250px';
                svg.style.height = '250px';
            }

            let seconds = 60;
            const countdownEl = document.getElementById('countdown');
            countdownInterval = setInterval(() => {
                seconds--;
                countdownEl.textContent = 'Väntar på scan... ' + seconds + 's';
                if (seconds <= 15) countdownEl.classList.add('warning');
                if (seconds <= 0) clearInterval(countdownInterval);
            }, 1000);

            pollInterval = setInterval(checkLinkStatus, 2000);
        } else {
            showError(data.error || 'Kunde inte starta länkning');
        }
    } catch (error) {
        showError('Nätverksfel: ' + error.message);
    }
}

async function startRegistration() {
    const phone = document.getElementById('register-phone').value.trim();
    const useVoice = document.querySelector('input[name="verify-method"]:checked').value === 'voice';

    if (!phone || !phone.startsWith('+')) {
        alert('Ange ett giltigt telefonnummer (t.ex. +46701234567)');
        return;
    }

    registerPhone = phone;

    hideAllStep2Sections();
    document.getElementById('accounts-loading').classList.remove('hidden');

    try {
        const response = await fetch('/api/setup/start-register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone_number: phone, use_voice: useVoice })
        });
        const data = await response.json();

        document.getElementById('accounts-loading').classList.add('hidden');

        if (data.needs_captcha) {
            document.getElementById('register-captcha').classList.remove('hidden');
        } else if (data.success) {
            document.getElementById('verify-phone-text').textContent = phone;
            document.getElementById('verify-method-text').textContent = useVoice ? 'samtal' : 'SMS';
            document.getElementById('register-verify').classList.remove('hidden');
        } else {
            showError(data.error || 'Registrering misslyckades');
        }
    } catch (error) {
        document.getElementById('accounts-loading').classList.add('hidden');
        showError('Nätverksfel: ' + error.message);
    }
}

async function submitCaptcha() {
    const token = document.getElementById('captcha-token').value.trim();
    const useVoice = document.querySelector('input[name="verify-method"]:checked').value === 'voice';

    if (!token || !token.startsWith('signalcaptcha://')) {
        alert('Klistra in en giltig signalcaptcha:// länk');
        return;
    }

    hideAllStep2Sections();
    document.getElementById('accounts-loading').classList.remove('hidden');

    try {
        const response = await fetch('/api/setup/start-register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone_number: registerPhone,
                use_voice: useVoice,
                captcha_token: token
            })
        });
        const data = await response.json();

        document.getElementById('accounts-loading').classList.add('hidden');

        if (data.success) {
            document.getElementById('verify-phone-text').textContent = registerPhone;
            document.getElementById('verify-method-text').textContent = useVoice ? 'samtal' : 'SMS';
            document.getElementById('register-verify').classList.remove('hidden');
        } else {
            showError(data.error || 'Registrering misslyckades');
        }
    } catch (error) {
        document.getElementById('accounts-loading').classList.add('hidden');
        showError('Nätverksfel: ' + error.message);
    }
}

async function submitVerifyCode() {
    const code = document.getElementById('verify-code').value.trim();

    if (!code || code.length < 4) {
        alert('Ange verifieringskoden');
        return;
    }

    hideAllStep2Sections();
    document.getElementById('accounts-loading').classList.remove('hidden');

    try {
        const response = await fetch('/api/setup/verify-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        });
        const data = await response.json();

        document.getElementById('accounts-loading').classList.add('hidden');

        if (data.success) {
            linkedNumber = data.phone_number;
            document.getElementById('linked-number').textContent = linkedNumber;
            document.getElementById('link-success').classList.remove('hidden');
        } else {
            showError(data.error || 'Verifiering misslyckades');
        }
    } catch (error) {
        document.getElementById('accounts-loading').classList.add('hidden');
        showError('Nätverksfel: ' + error.message);
    }
}

async function checkLinkStatus() {
    try {
        const response = await fetch('/api/setup/status');
        const data = await response.json();

        if (data.status === 'linked') {
            clearInterval(countdownInterval);
            clearInterval(pollInterval);
            linkedNumber = data.linked_number;
            document.getElementById('linked-number').textContent = linkedNumber;
            hideAllStep2Sections();
            document.getElementById('link-success').classList.remove('hidden');
        } else if (data.status === 'timeout') {
            clearInterval(countdownInterval);
            clearInterval(pollInterval);
            hideAllStep2Sections();
            document.getElementById('link-timeout').classList.remove('hidden');
            if (data.manual_instructions) {
                document.getElementById('manual-instructions').textContent = data.manual_instructions;
            }
        } else if (data.status === 'error') {
            clearInterval(countdownInterval);
            clearInterval(pollInterval);
            showError(data.error || 'Ett fel uppstod');
        }
    } catch (error) {
        console.error('Error checking status:', error);
    }
}

function showError(message) {
    hideAllStep2Sections();
    document.getElementById('link-error').classList.remove('hidden');
    document.getElementById('error-message').textContent = message;
}

async function cancelLinking() {
    clearInterval(countdownInterval);
    clearInterval(pollInterval);
    await fetch('/api/setup/cancel-link', { method: 'POST' });
    showMethodSelection();
}

function retryLinking() {
    showMethodSelection();
}

function useManualNumber() {
    const number = document.getElementById('manual-number').value.trim();
    if (!number || !number.startsWith('+')) {
        alert('Ange ett giltigt telefonnummer (t.ex. +46701234567)');
        return;
    }
    linkedNumber = number;
    goToStep(3);
}

async function saveConfig() {
    const btn = document.getElementById('save-btn');
    const msgDiv = document.getElementById('save-message');
    btn.disabled = true;
    btn.textContent = 'Sparar...';

    // Install Obsidian template if checkbox is checked
    const installObsidian = document.getElementById('install-obsidian').checked;
    const vaultPath = document.getElementById('vault-path').value;

    if (installObsidian) {
        try {
            const obsResponse = await fetch('/api/setup/install-obsidian-template', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ vault_path: vaultPath })
            });
            const obsData = await obsResponse.json();
            if (!obsData.success && !obsData.skipped) {
                console.warn('Obsidian template installation warning:', obsData.error);
            }
        } catch (e) {
            console.warn('Obsidian template installation failed:', e);
        }
    }

    try {
        const response = await fetch('/api/setup/save-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vault_path: vaultPath,
                signal_number: linkedNumber,
                display_name: document.getElementById('device-name')?.value || 'Oden'
            })
        });
        const data = await response.json();

        if (data.success) {
            msgDiv.innerHTML = '<div class="success" style="padding: 20px; text-align: center;">' +
                '<h2 style="margin: 0 0 10px 0;">✅ Klart!</h2>' +
                '<p style="margin: 0;">' + data.message + '</p>' +
                '<p style="margin: 10px 0 0 0; color: #888;" id="reload-status">Väntar på att Oden ska starta...</p>' +
                '</div>';
            btn.style.display = 'none';
            document.querySelector('button.btn-secondary').style.display = 'none';
            pollForMainServer();
        } else {
            msgDiv.innerHTML = '<div class="error">' + data.error + '</div>';
            btn.disabled = false;
            btn.textContent = 'Spara och starta Oden';
        }
    } catch (error) {
        msgDiv.innerHTML = '<div class="error">Nätverksfel: ' + error.message + '</div>';
        btn.disabled = false;
        btn.textContent = 'Spara och starta Oden';
    }
}

async function pollForMainServer() {
    const statusEl = document.getElementById('reload-status');
    let attempts = 0;
    const maxAttempts = 30;

    const poll = async () => {
        attempts++;
        try {
            const response = await fetch('/api/config');
            if (response.ok) {
                statusEl.textContent = 'Oden är redo! Laddar om...';
                setTimeout(() => {
                    window.location.href = '/';
                }, 500);
                return;
            }
        } catch (e) {
            // Server not ready yet
        }

        if (attempts < maxAttempts) {
            statusEl.textContent = 'Väntar på att Oden ska starta... (' + attempts + 's)';
            setTimeout(poll, 1000);
        } else {
            statusEl.innerHTML = 'Oden har startat. <a href="/" style="color: #4ade80;">Klicka här</a> för att öppna.';
        }
    };

    setTimeout(poll, 2000);
}

// === Recovery functions ===

function showRecoveryStep() {
    // Hide step 1, show recovery step
    document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
    document.getElementById('step-recovery').classList.add('active');
    // Hide the step indicator dots during recovery
    document.getElementById('step-indicator').style.display = 'none';
}

function skipRecovery() {
    // User wants fresh install — go to normal step 1
    document.getElementById('step-recovery').classList.remove('active');
    document.getElementById('step-1').classList.add('active');
    document.getElementById('step-indicator').style.display = 'flex';
    currentStep = 1;
}

async function confirmRecovery() {
    const recoveryPath = document.getElementById('recovery-path').value.trim();
    const btn = document.getElementById('recovery-btn');
    const msgDiv = document.getElementById('recovery-message');

    if (!recoveryPath) {
        msgDiv.innerHTML = '<div class="error">Ange en sökväg</div>';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Validerar...';
    msgDiv.innerHTML = '';

    try {
        // First validate the path
        const valResponse = await fetch('/api/setup/validate-path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: recoveryPath })
        });
        const valData = await valResponse.json();

        if (!valData.valid) {
            msgDiv.innerHTML = '<div class="error">Ogiltig sökväg: ' + (valData.error || 'okänt fel') + '</div>';
            btn.disabled = false;
            btn.textContent = 'Återställ';
            return;
        }

        if (!valData.has_config_db) {
            msgDiv.innerHTML = '<div class="error" style="margin-bottom: 15px;">' +
                '⚠️ Ingen konfigurationsdatabas hittades på angiven sökväg.</div>';
            btn.disabled = false;
            btn.textContent = 'Återställ';
            return;
        }

        // Path is valid and has config.db — set up oden home (creates pointer file)
        btn.textContent = 'Återställer...';
        const response = await fetch('/api/setup/oden-home', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ oden_home: recoveryPath })
        });
        const data = await response.json();

        if (data.success) {
            msgDiv.innerHTML = '<div class="success" style="padding: 20px; text-align: center;">' +
                '<h2 style="margin: 0 0 10px 0;">✅ Konfiguration återställd!</h2>' +
                '<p style="margin: 0;">Oden startar om med befintlig konfiguration...</p>' +
                '<p style="margin: 10px 0 0 0; color: #888;" id="reload-status">Väntar på att Oden ska starta...</p>' +
                '</div>';
            btn.style.display = 'none';
            // Hide the "Ny installation" button too
            btn.nextElementSibling.style.display = 'none';
            pollForMainServer();
        } else {
            msgDiv.innerHTML = '<div class="error">' + (data.error || 'Kunde inte återställa') + '</div>';
            btn.disabled = false;
            btn.textContent = 'Återställ';
        }
    } catch (error) {
        msgDiv.innerHTML = '<div class="error">Nätverksfel: ' + error.message + '</div>';
        btn.disabled = false;
        btn.textContent = 'Återställ';
    }
}
