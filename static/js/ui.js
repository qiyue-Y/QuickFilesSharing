/* ui.js — toast 状态提示、复制兜底、弹窗通用开关与通用确认框（spec §4.3 / §4.4） */

const TOAST_HOST = document.getElementById('toast-host');
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

/** 代际计数：next() 领新号，is(g) 判断 g 是否仍是最新一代——作废"关窗/开窗之后才回来的旧回调" */
export function createGeneration() {
    let gen = 0;
    return { next: () => ++gen, is: g => g === gen };
}

let openMask = null;
let lastFocused = null;
let onCloseCb = null;
let modalLocked = false;
const modalGen = createGeneration();

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

export function openModal(mask, opener, onClose) {
    if (openMask) closeModal();
    modalGen.next();
    openMask = mask;
    lastFocused = opener || document.activeElement;
    onCloseCb = onClose || null;
    modalLocked = false;
    mask.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(() => mask.classList.add('in'));
}

export function closeModal() {
    if (!openMask || modalLocked) return;
    const mask = openMask;
    const gen = modalGen.next();
    openMask = null;
    const cb = onCloseCb; onCloseCb = null;
    mask.classList.remove('in');
    document.body.classList.remove('modal-open');
    setTimeout(() => { if (modalGen.is(gen)) mask.hidden = true; }, 300);
    if (lastFocused && lastFocused.isConnected) lastFocused.focus();
    lastFocused = null;
    if (cb) cb();
}

/** 点遮罩空白处关闭（点击落在盒体内时不关） */
export function closeOnBackdrop(mask) {
    mask.addEventListener('click', e => { if (e.target === mask) closeModal(); });
}

/* ---------- 通用确认框 ----------
 * confirmDialog({title, body, okText, cancelText, onOk}) → Promise<boolean>
 * 无 onOk：点确认即关窗 resolve(true)；有 onOk：请求期间锁窗（Esc/遮罩/取消都关不掉），
 * onOk 返回 false 或抛错则保持打开、按钮恢复，成功才关窗。取消/Esc/遮罩 resolve(false)。 */

const confirmMask = document.getElementById('confirm-modal');
const confirmTitle = document.getElementById('confirm-title');
const confirmBody = document.getElementById('confirm-body');
const confirmOk = document.getElementById('confirm-ok');
const confirmCancel = document.getElementById('confirm-cancel');
let confirmResolve = null;
let confirmOnOk = null;

function settleConfirm(v) {
    const r = confirmResolve; confirmResolve = null;
    if (r) r(v);
}

export function confirmDialog({ title, body, okText = '确认', cancelText = '取消', onOk }) {
    confirmTitle.textContent = title;
    confirmBody.textContent = body;
    confirmOk.textContent = okText;
    confirmCancel.textContent = cancelText;
    confirmOk.disabled = confirmCancel.disabled = false;
    confirmOnOk = onOk || null;
    return new Promise(resolve => {
        confirmResolve = resolve;
        openModal(confirmMask, document.activeElement, () => settleConfirm(false));
        confirmCancel.focus();
    });
}

confirmOk.addEventListener('click', async () => {
    if (!confirmOnOk) { settleConfirm(true); closeModal(); return; }
    modalLocked = true;
    confirmOk.disabled = confirmCancel.disabled = true;
    let done;
    try { done = await confirmOnOk(); }
    catch (e) { console.warn('confirmDialog onOk 抛错，按返回 false 处理', e); done = false; }
    modalLocked = false;
    confirmOk.disabled = confirmCancel.disabled = false;
    if (done !== false) { settleConfirm(true); closeModal(); }
});

confirmCancel.addEventListener('click', closeModal);
document.getElementById('confirm-close').addEventListener('click', closeModal);
closeOnBackdrop(confirmMask);
