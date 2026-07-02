// ── Page transitions ───────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();

    // Sidebar overlay
    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.addEventListener('click', toggleSidebar);

    // Intercept nav links for smooth exit → enter transition
    document.querySelectorAll('a.nav-item, a[href="/"], a[href="/settings"], a[href="/prompts"], a[href="/research"], a[href="/monitor"]').forEach(link => {
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('http') || link.target === '_blank') return;
        link.addEventListener('click', e => {
            if (e.metaKey || e.ctrlKey) return;
            e.preventDefault();
            document.body.style.opacity = '0';
            document.body.style.transition = 'opacity 0.15s ease';
            setTimeout(() => { window.location.href = href; }, 150);
        });
    });
});

// Fade in on load
window.addEventListener('pageshow', () => {
    document.body.style.transition = 'opacity 0.18s ease';
    document.body.style.opacity = '0';
    requestAnimationFrame(() => requestAnimationFrame(() => { document.body.style.opacity = '1'; }));
    setTimeout(() => { document.body.style.opacity = '1'; }, 500);
});

// ── Toast ──────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
    const icons = { success: 'check-circle', error: 'x-circle', info: 'info', warning: 'alert-triangle' };
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', icons[type] || 'info');
    icon.style.cssText = 'width:15px;height:15px;flex-shrink:0;';
    toast.appendChild(icon);
    const span = document.createElement('span');
    span.textContent = message;
    toast.appendChild(span);
    container.appendChild(toast);
    lucide.createIcons({ nodes: [toast] });
    setTimeout(() => {
        toast.style.transition = 'opacity 0.25s, transform 0.25s';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(6px)';
        setTimeout(() => toast.remove(), 250);
    }, duration);
}

// ── Loading overlay ────────────────────────────────────
function showLoading(msg = 'Generating Article…') {
    let el = document.getElementById('loadingOverlay');
    if (!el) {
        el = document.createElement('div');
        el.id = 'loadingOverlay';
        const box = document.createElement('div');
        box.className = 'loading-box';
        const spinner = document.createElement('div');
        spinner.className = 'spinner spinner-lg';
        spinner.style.margin = '0 auto';
        box.appendChild(spinner);
        const h3 = document.createElement('h3');
        h3.id = 'loading-msg';
        h3.textContent = msg;
        box.appendChild(h3);
        const p = document.createElement('p');
        p.textContent = 'This may take 30\u201360 seconds';
        box.appendChild(p);
        el.appendChild(box);
        document.body.appendChild(el);
    } else {
        const m = el.querySelector('#loading-msg');
        if (m) m.textContent = msg;
        el.classList.remove('hidden');
    }
}
function hideLoading() {
    const el = document.getElementById('loadingOverlay');
    if (el) el.classList.add('hidden');
}

// ── Generic API action ─────────────────────────────────
function apiAction(url, btn, loadingText, successText) {
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> ${loadingText || 'Loading…'}`;
    fetch(url, { method: 'POST' })
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(data => {
            btn.disabled = false;
            btn.innerHTML = orig;
            lucide.createIcons({ nodes: [btn] });
            data.success !== false
                ? showToast(successText || data.message || 'Done!', 'success')
                : showToast(data.error || data.message || 'Something went wrong', 'error');
        })
        .catch(err => {
            btn.disabled = false;
            btn.innerHTML = orig;
            lucide.createIcons({ nodes: [btn] });
            showToast('Request failed: ' + err.message, 'error');
        });
}

// ── Logout ─────────────────────────────────────────────
function logout() {
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.15s ease';
    setTimeout(() => {
        fetch('/logout', { method: 'POST' }).finally(() => { window.location.href = '/login'; });
    }, 150);
}

// ── Sidebar toggle (mobile) ────────────────────────────
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebar-overlay').classList.toggle('open');
}

// ── Confirm Modal ──────────────────────────────────────
function showConfirm(title, message, onConfirm) {
    let modal = document.getElementById('confirm-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'confirm-modal';
        modal.innerHTML = `
        <div class="modal-backdrop" onclick="closeConfirm()"></div>
        <div class="modal-box">
            <div class="modal-icon"><i data-lucide="alert-triangle" style="width:22px;height:22px;color:#fbbf24;"></i></div>
            <h3 id="confirm-title" class="modal-title"></h3>
            <p id="confirm-msg" class="modal-msg"></p>
            <div class="modal-actions">
                <button class="btn btn-ghost" onclick="closeConfirm()">Cancel</button>
                <button id="confirm-ok" class="btn btn-primary">Confirm</button>
            </div>
        </div>`;
        document.body.appendChild(modal);
    }
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-msg').textContent = message;
    document.getElementById('confirm-ok').onclick = () => { closeConfirm(); onConfirm(); };
    modal.classList.add('open');
    lucide.createIcons({ nodes: [modal] });
}
function closeConfirm() {
    const m = document.getElementById('confirm-modal');
    if (m) m.classList.remove('open');
}

// ── Password toggle ────────────────────────────────────
function togglePassword(btn) {
    const input = btn.previousElementSibling;
    const isText = input.type === 'text';
    input.type = isText ? 'password' : 'text';
    btn.innerHTML = `<i data-lucide="${isText ? 'eye' : 'eye-off'}" style="width:14px;height:14px;"></i>`;
    lucide.createIcons({ nodes: [btn] });
}
