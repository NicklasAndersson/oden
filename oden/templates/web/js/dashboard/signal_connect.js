// signal_connect.js — Depends on: shared.js (escapeHtml, showConfigMessage)
//
// Signal → Konton when Oden runs without Signal: use an account signal-cli
// already has, link a new one by QR code, or register a number. Signal →
// Inställningar: turn Signal off. Both take effect after a restart.

let signalLinkPoll = null;

async function postJson(url, body) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {}),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || 'Något gick fel');
    return data;
}

function showRestartNotice(message) {
    const box = document.getElementById('signal-connect') || document.getElementById('tab-signal');
    const note = document.createElement('div');
    note.className = 'success';
    note.textContent = message;
    box.prepend(note);
    showConfigMessage(message, 'success');
}

async function loadSignalConnect() {
    const container = document.getElementById('signal-connect-accounts');
    if (!container) return;  // Signal is on: the panel is not rendered
    try {
        const response = await fetch('/api/signal/connect/status?accounts=1');
        const data = await response.json();
        const accounts = data.accounts || [];
        container.innerHTML = accounts.length ? `
            <h4 class="pane-heading">Konton som redan finns i signal-cli</h4>
            <div class="invitation-list">${accounts.map(account => `
                <div class="invitation-item">
                    <div class="invitation-info">
                        <div class="invitation-name mono">${escapeHtml(account.number)}</div>
                        ${account.number === data.signal_number ? '<div class="invitation-meta">Det konto Oden är inställd på</div>' : ''}
                    </div>
                    <div class="invitation-actions">
                        <button type="button" class="btn btn-primary btn-sm" data-number="${escapeHtml(account.number)}"
                                onclick="useSignalAccount(this.dataset.number)">Använd</button>
                    </div>
                </div>`).join('')}
            </div>` : '';
    } catch (e) {
        container.innerHTML = '';
    }
}

async function useSignalAccount(number) {
    try {
        const data = await postJson('/api/signal/connect/use', {signal_number: number});
        showRestartNotice(data.message);
    } catch (e) {
        showConfigMessage(e.message, 'error');
    }
}

async function startSignalLink() {
    const button = document.getElementById('signal-link-btn');
    button.disabled = true;
    try {
        const data = await postJson('/api/signal/connect/link');
        document.getElementById('signal-link-qr').innerHTML = data.qr_svg;  // server-generated SVG
        document.getElementById('signal-link-status').textContent = 'Väntar på att koden skannas…';
        document.getElementById('signal-link-area').classList.remove('hidden');
        clearInterval(signalLinkPoll);
        signalLinkPoll = setInterval(pollSignalLink, 2000);
    } catch (e) {
        showConfigMessage(e.message, 'error');
    } finally {
        button.disabled = false;
    }
}

async function pollSignalLink() {
    const status = document.getElementById('signal-link-status');
    try {
        const response = await fetch('/api/signal/connect/status');
        const link = (await response.json()).link;
        if (!link) return;
        if (link.status === 'linked' && link.linked_number) {
            clearInterval(signalLinkPoll);
            status.textContent = `Länkat till ${link.linked_number}.`;
            document.getElementById('signal-link-qr').innerHTML = '';
            await useSignalAccount(link.linked_number);
        } else if (link.status === 'timeout' || link.status === 'error') {
            clearInterval(signalLinkPoll);
            status.textContent = link.error || link.manual_instructions || 'Länkningen avbröts. Försök igen.';
        }
    } catch (e) {
        // transient; keep polling
    }
}

async function cancelSignalLink() {
    clearInterval(signalLinkPoll);
    document.getElementById('signal-link-area').classList.add('hidden');
    await fetch('/api/signal/connect/link-cancel', {method: 'POST'}).catch(() => {});
}

async function startSignalRegister() {
    const number = document.getElementById('signal-register-number').value.trim();
    const captcha = document.getElementById('signal-register-captcha').value.trim();
    try {
        const response = await fetch('/api/signal/connect/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                phone_number: number,
                use_voice: document.getElementById('signal-register-voice').checked,
                captcha_token: captcha,
            }),
        });
        const data = await response.json();
        if (data.needs_captcha) {
            document.getElementById('signal-register-captcha-field').classList.remove('hidden');
            showConfigMessage('Signal kräver en CAPTCHA — klistra in länken och klicka Skicka kod igen', 'error');
            return;
        }
        if (!data.success) throw new Error(data.error || 'Registreringen misslyckades');
        document.getElementById('signal-register-code-field').classList.remove('hidden');
        document.getElementById('signal-verify-btn').classList.remove('hidden');
        showConfigMessage('Koden är skickad — skriv in den och klicka Verifiera', 'success');
    } catch (e) {
        showConfigMessage(e.message, 'error');
    }
}

async function verifySignalRegister() {
    try {
        const data = await postJson('/api/signal/connect/verify', {
            code: document.getElementById('signal-register-code').value.trim(),
        });
        await useSignalAccount(data.phone_number || document.getElementById('signal-register-number').value.trim());
    } catch (e) {
        showConfigMessage(e.message, 'error');
    }
}

async function disableSignal() {
    if (!confirm('Stänga av Signal? Oden slutar ta emot Signal-meddelanden efter omstart.')) return;
    try {
        const data = await postJson('/api/signal/connect/disable');
        showRestartNotice(data.message);
    } catch (e) {
        showConfigMessage(e.message, 'error');
    }
}
