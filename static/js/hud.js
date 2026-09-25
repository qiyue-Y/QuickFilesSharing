/* hud.js — 顶栏：访问地址复制、磁盘剩余、用户头像弹层（切换 / 记住我 / 退出） */

import { api, LOW_DISK_BYTES, shareOrigin } from './api.js';
import { formatSize } from './format.js';
import { toast, copyText, openModal, closeModal, closeOnBackdrop } from './ui.js';
import qrcode from './vendor/qrcode.js';

const STORAGE_KEY = 'clipboard_last_user';

export function rememberUser(username) {
    localStorage.setItem(STORAGE_KEY, username);
}

export function forgetUser() {
    localStorage.removeItem(STORAGE_KEY);
}

export function rememberedUser() {
    return localStorage.getItem(STORAGE_KEY);
}

export function init(ctx) {
    const hostBtn = document.getElementById('ip-copy');
    const hostText = document.getElementById('hudHost');
    const diskEl = document.getElementById('hudDisk');
    const diskSep = document.getElementById('hudDiskSep');
    const wrap = document.getElementById('userWrap');
    const chip = document.getElementById('user-chip');
    const avatar = document.getElementById('user-avatar');
    const pop = document.getElementById('user-pop');
    const popInput = document.getElementById('pop-input');
    const popRemember = document.getElementById('popRemember');

    shareOrigin().then(origin => { hostText.textContent = new URL(origin).host; });

    hostBtn.addEventListener('click', () => {
        shareOrigin().then(origin => {
            const ok = copyText(origin + '/');
            toast(ok ? '访问地址已复制: ' + origin : '复制失败，请手动复制地址栏', ok ? 'success' : 'error');
            hostBtn.classList.toggle('copied', ok);
            setTimeout(() => hostBtn.classList.remove('copied'), 1500);
        });
    });

    /* ---------- 访问二维码 ---------- */

    const qrModal = document.getElementById('qrModal');
    document.getElementById('qr-btn').addEventListener('click', () => {
        shareOrigin().then(origin => {
            const user = ctx.getUsername();
            const url = origin + '/' + (user ? '?u=' + encodeURIComponent(user) : '');
            const qr = qrcode(0, 'M');
            qr.addData(url);
            qr.make();
            const n = qr.getModuleCount();
            let d = '';
            for (let r = 0; r < n; r++)
                for (let c = 0; c < n; c++)
                    if (qr.isDark(r, c)) d += `M${c} ${r}h1v1z`;
            // path 里只有数字矩阵；url 不进 HTML 字符串，事后 setAttribute/textContent 挂上去
            document.getElementById('qrBox').innerHTML =
                `<svg viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" role="img"><path d="${d}"/></svg>`;
            document.querySelector('#qrBox svg').setAttribute('aria-label', url);
            document.getElementById('qrUrl').textContent = url;
            openModal(qrModal);
        });
    });
    document.getElementById('qrModalClose').addEventListener('click', closeModal);
    closeOnBackdrop(qrModal);

    /* ---------- 磁盘剩余 ---------- */
    ctx.onDiskRefresh(loadDisk);

    function loadDisk() {
        api.disk()
            .then(d => {
                if (!d.success) throw new Error(d.error || '查询失败');
                const low = d.free < LOW_DISK_BYTES;
                diskEl.textContent = `磁盘剩余 ${formatSize(d.free)}`;
                diskEl.title = `服务器存储盘剩余 ${formatSize(d.free)} / 共 ${formatSize(d.total)}`;
                diskEl.classList.toggle('low', low);
                diskEl.hidden = false;
                diskSep.hidden = false;
            })
            .catch(() => {
                diskEl.hidden = true;
                diskSep.hidden = true;
            });
    }

    /* ---------- 用户弹层 ---------- */
    function setOpen(open) {
        wrap.classList.toggle('open', open);
        chip.setAttribute('aria-expanded', String(open));
        if (open) {
            popInput.value = '';
            popInput.placeholder = ctx.getUsername() || 'default';
            popRemember.checked = rememberedUser() !== null;
            popInput.focus();
        }
    }

    chip.addEventListener('click', () => setOpen(!wrap.classList.contains('open')));
    document.getElementById('pop-cancel').addEventListener('click', () => setOpen(false));
    document.addEventListener('click', e => {
        if (wrap.classList.contains('open') && !wrap.contains(e.target)) setOpen(false);
    });

    function applySwitch() {
        const username = popInput.value.trim() || 'default';
        if (popRemember.checked) rememberUser(username);
        else forgetUser();
        setOpen(false);
        ctx.setUsername(username);
    }

    document.getElementById('pop-ok').addEventListener('click', applySwitch);
    popInput.addEventListener('keydown', e => { if (e.key === 'Enter') applySwitch(); });
    document.getElementById('pop-logout').addEventListener('click', () => {
        setOpen(false);
        ctx.logout();
    });

    ctx.onUserChange(username => {
        if (!username) {
            wrap.hidden = true;
            diskEl.hidden = true;
            diskSep.hidden = true;
            return;
        }
        wrap.hidden = false;
        avatar.textContent = username.length > 2 ? username.slice(0, 2) : username;
        avatar.title = username;
        loadDisk();
    });
}
