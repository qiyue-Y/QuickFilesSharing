/* login.js — 登录页（设计稿 QFS · 登录）
 * 覆盖整屏的 #login-gate 由本模块负责入场/转场/复位：
 * 提交 → 按钮加载态(0) → 卡片退出+拱框苏醒(520ms) → 金色揭示 + body[data-stage] 翻成 app(950ms) → 收幕(1680ms)。
 * 背景只有 pond.css 的 .bg-layer 一层，登录态由 body[data-stage="login"] 压住主内容，
 * 所以 data-stage 一翻、主页面就在金色幕布底下淡入到位，收幕不再有两层背景对不上的闪动。 */

import { toast } from './ui.js';
import { rememberUser, forgetUser, rememberedUser } from './hud.js';

const stage = document.getElementById('login-gate');
const card = document.getElementById('loginCard');
const field = document.getElementById('loginField');
const input = document.getElementById('usernameInput');
const err = document.getElementById('loginError');
const btn = document.getElementById('loginBtn');
const btnLabel = document.getElementById('btnLabel');
const rememberBox = document.getElementById('rememberUserLogin');
const clearBtn = document.getElementById('clearRememberBtn');
const archExhibit = document.getElementById('archExhibit');
const arch = archExhibit.querySelector('.arch');
const wash = document.getElementById('transitionWash');

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let busy = false;
let timers = [];

let ctxRef = null;

function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
function clearTimers() { timers.forEach(clearTimeout); timers = []; }

function showError() {
    field.classList.add('invalid');
    card.classList.remove('shake');
    void card.offsetWidth;          // 重启 shake 动画
    card.classList.add('shake');
    later(() => card.classList.remove('shake'), 320);
    err.textContent = '请输入用户名';
    input.focus();
}

function clearError() {
    field.classList.remove('invalid');
    err.textContent = '';
}

function hideStage() {
    clearTimers();
    stage.hidden = true;
    document.body.dataset.stage = 'app';
    document.body.classList.remove('login-pending');
}

/* 退出登录后回到登录台：清掉上一轮转场留下的类与按钮状态 */
function resetStage() {
    clearTimers();
    busy = false;
    stage.hidden = false;
    document.body.dataset.stage = 'login';
    stage.classList.remove('rm-out');
    card.classList.remove('is-leaving', 'shake');
    archExhibit.classList.remove('awake');
    wash.classList.remove('revealing');
    btn.classList.remove('is-loading');
    btn.disabled = false;
    btnLabel.textContent = '进入';
    input.value = '';
    clearError();
    syncClearBtn();
    document.body.classList.add('login-pending');
    input.focus();
}

function syncClearBtn() {
    clearBtn.hidden = !rememberedUser();
}

function enter(username) {
    busy = true;
    if (rememberBox.checked) rememberUser(username);
    else forgetUser();
    syncClearBtn();
    ctxRef.setUsername(username);

    if (reduceMotion) {
        stage.classList.add('rm-out');
        later(hideStage, 180);
        return;
    }

    btn.classList.add('is-loading');
    btn.disabled = true;
    later(() => {
        card.classList.add('is-leaving');
        archExhibit.classList.add('awake');
    }, 520);
    later(() => {
        const r = arch.getBoundingClientRect();
        wash.style.setProperty('--rx', (r.left + r.width / 2) + 'px');
        wash.style.setProperty('--ry', (r.top + r.height / 2) + 'px');
        wash.classList.add('revealing');
        // 金幕铺开的同时翻开 data-stage：主页面淡入、登录蒙版淡出都发生在幕布底下
        document.body.dataset.stage = 'app';
    }, 950);
    later(hideStage, 1680);
}

export function init(ctx) {
    ctxRef = ctx;

    document.getElementById('loginForm').addEventListener('submit', e => {
        e.preventDefault();
        if (busy) return;
        const username = input.value.trim();
        if (!username) { showError(); return; }
        clearError();
        enter(username);
    });
    input.addEventListener('input', () => { if (field.classList.contains('invalid')) clearError(); });

    clearBtn.addEventListener('click', () => {
        forgetUser();
        rememberBox.checked = false;
        syncClearBtn();
        toast('已清除记住的用户', 'success');
    });

    ctx.onUserChange(username => { if (!username) resetStage(); });

    const saved = rememberedUser();
    if (saved) {
        rememberBox.checked = true;
        ctx.setUsername(saved);
        hideStage();
        return;
    }
    syncClearBtn();
    document.body.classList.add('login-pending');
    input.focus();
}
