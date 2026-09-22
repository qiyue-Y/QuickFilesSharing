/* login.js — 登录页（设计稿 QFS · 登录）
 * 覆盖整屏的 #login-gate 由本模块负责入场/转场/复位：
 * 提交 → body[data-stage] 立刻翻成 app（主页面淡入、登录台整组淡出，同一帧开始）→ 480ms 收幕。
 * 背景只有 pond.css 的 .bg-layer 一层，登录态由 body[data-stage="login"] 压住主内容，
 * 两个方向（进入 / 退出登录）走同一组 opacity 过渡，中间不插揭示层、也不空等。 */

import { toast } from './ui.js';
import { rememberUser, forgetUser, rememberedUser } from './hud.js';

const stage = document.getElementById('login-gate');
const card = document.getElementById('loginCard');
const field = document.getElementById('loginField');
const input = document.getElementById('usernameInput');
const err = document.getElementById('loginError');
const rememberBox = document.getElementById('rememberUserLogin');
const clearBtn = document.getElementById('clearRememberBtn');

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

/* 退出登录后回到登录台：清掉上一轮转场留下的类与输入状态 */
function resetStage() {
    clearTimers();
    busy = false;
    stage.hidden = false;
    document.body.dataset.stage = 'login';
    stage.classList.remove('rm-out');
    card.classList.remove('shake');
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

    // 主页面淡入与登录台淡出同帧开始，中间不空等；480ms 时两条曲线都已走到 ~99%，收幕看不出来
    document.body.dataset.stage = 'app';
    later(hideStage, 480);
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
