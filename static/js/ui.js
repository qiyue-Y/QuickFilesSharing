/* ui.js — toast 状态提示、复制兜底、弹窗通用开关（spec §4.3 / §4.4） */

const TOAST_HOST = document.getElementById('toastHost');
const MAX_TOASTS = 3;

/** 替代旧的 showStatus / uploadStatus 内联样式 */
export function toast(msg, type = 'info', ttl = 3000) {
    while (TOAST_HOST.children.length >= MAX_TOASTS) {
        TOAST_HOST.removeChild(TOAST_HOST.firstElementChild);
    }
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    TOAST_HOST.appendChild(el);
    requestAnimationFrame(() => el.classList.add('in'));
    setTimeout(() => {
        el.classList.remove('in');
        setTimeout(() => el.remove(), 320);
    }, ttl);
}

/** 局域网 http 非安全上下文，navigator.clipboard 不可用，execCommand 是唯一稳的 */
export function copyText(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none;';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
}

/* ---------- 弹窗 ---------- */

let openMask = null;
let lastFocused = null;

function focusables(mask) {
    return Array.from(mask.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )).filter(el => !el.disabled && el.offsetParent !== null);
}

function onKeydown(e) {
    if (!openMask) return;
    if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
    } else if (e.key === 'Tab') {
        const list = focusables(openMask);
        if (list.length === 0) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
}

document.addEventListener('keydown', onKeydown);

export function openModal(mask, opener) {
    if (openMask) closeModal();
    openMask = mask;
    lastFocused = opener || document.activeElement;
    mask.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(() => mask.classList.add('in'));
}

export function closeModal() {
    if (!openMask) return;
    const mask = openMask;
    openMask = null;
    mask.classList.remove('in');
    document.body.classList.remove('modal-open');
    setTimeout(() => { mask.hidden = true; }, 300);
    if (lastFocused && lastFocused.isConnected) lastFocused.focus();
    lastFocused = null;
}

/** 点遮罩空白处关闭（点击落在盒体内时不关） */
export function closeOnBackdrop(mask) {
    mask.addEventListener('click', e => { if (e.target === mask) closeModal(); });
}
