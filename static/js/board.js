/* board.js — 留言板：全员共用一块板，只渲染最近 5 条，更早的留在后端库里
 * 文本一律走 textContent，不拼进 HTML；轮询只在已登录且页面可见时跑。 */

import { api } from './api.js';
import { formatDate } from './format.js';
import { toast, copyText } from './ui.js';

const listEl = document.getElementById('clip-list');
const inputEl = document.getElementById('clip-input');
const sendBtn = document.getElementById('clip-send');

const POLL_MS = 5000;
const DEVICE_KEY = 'qfs_device';

let ctxRef = null;
let latestId = null;      // 已渲染的最新一条，轮询用它问「有没有新的」
let sending = false;
let deleting = false;
let timer = null;

/* 设备名：只按 UA 判一次存起来，之后换浏览器才算新设备 */
function deviceName() {
    const saved = localStorage.getItem(DEVICE_KEY);
    if (saved) return saved;
    const ua = navigator.userAgent;
    const os = /Windows/i.test(ua) ? 'Windows' : /Macintosh|Mac OS/i.test(ua) ? 'macOS'
        : /Android/i.test(ua) ? '安卓' : /iPhone|iPad|iPod/i.test(ua) ? 'iOS'
        : /Linux/i.test(ua) ? 'Linux' : '';
    const kind = /iPad|Tablet/i.test(ua) ? '平板' : /Mobi|iPhone|iPod|Android.*Mobile/i.test(ua) ? '手机' : '电脑';
    const name = [os, kind].filter(Boolean).join(' · ') || '未知设备';
    localStorage.setItem(DEVICE_KEY, name);
    return name;
}

/* 链接与命令用等宽显示，中文留言走正文字体 */
function looksTechnical(text) {
    return text.includes('\n') || /^(https?:\/\/|ftp:\/\/|file:\/\/|[a-z]:\\|\\\\|certutil\b|curl\b|aria2c\b|sha256sum\b|get-filehash\b|ssh\b|ping\b|location \/)/i.test(text);
}

function qbtn(label, act) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'qbtn sm' + (act === 'delete' ? ' danger' : '');
    btn.dataset.act = act;
    btn.textContent = label;
    return btn;
}

function makeClip(m) {
    const row = document.createElement('div');
    row.className = 'clip';
    row.dataset.id = m.id;
    if (latestId !== null && m.id > latestId) row.classList.add('fresh');

    const meta = document.createElement('div');
    meta.className = 'clip-meta';
    const who = document.createElement('span');
    who.textContent = `${m.author} · ${m.device}`;
    const when = document.createElement('span');
    when.textContent = formatDate(m.ts);
    // 复制固定放在最右，各行右边缘对齐；删除是可选的，排在它左边
    const actions = document.createElement('div');
    actions.className = 'clip-actions';
    if (m.author === ctxRef.getUsername()) actions.append(qbtn('删除', 'delete'));
    actions.append(qbtn('复制', 'copy'));
    meta.append(who, when, actions);

    const body = document.createElement('div');
    body.className = 'clip-text collapsed' + (looksTechnical(m.text) ? ' mono' : '');
    body.textContent = m.text;
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'clip-more';               // 渲染后量过是否真溢出，再决定显不显示
    more.dataset.act = 'toggle';
    more.textContent = '展开';
    more.hidden = true;

    const wrap = document.createElement('div');
    wrap.className = 'clip-body';
    wrap.append(body, more);
    row.append(meta, wrap);
    return row;
}

/** 折叠只对真正溢出 10 行的留言生效 */
function fitClamps() {
    listEl.querySelectorAll('.clip-body').forEach(wrap => {
        const body = wrap.querySelector('.clip-text');
        const more = wrap.querySelector('.clip-more');
        if (body.scrollHeight - body.clientHeight > 1) {
            more.hidden = false;
        } else {
            body.classList.remove('collapsed');
            more.hidden = true;
        }
    });
}

function render(messages) {
    listEl.textContent = '';
    if (!messages.length) {
        const empty = document.createElement('p');
        empty.className = 'clip-list-empty';
        empty.textContent = '还没有留言，写第一条放进池子里';
        listEl.append(empty);
        return;
    }
    listEl.append(...messages.map(makeClip));
    fitClamps();
}

function load() {
    const username = ctxRef.getUsername();
    if (!username) return;
    api.board(username, latestId)
        .then(data => {
            if (data.unchanged) return;
            render(data.messages);          // 先渲染（新留言靠旧 latestId 打 .fresh）
            latestId = data.latest_id;
        })
        .catch(() => toast('留言板读取失败', 'error'));
}

function reload() {
    latestId = null;
    load();
}

function send() {
    const username = ctxRef.getUsername();
    if (!username) { toast('请先登录', 'error'); return; }
    const text = inputEl.value.trim();
    if (!text) { toast('还没有内容可发送', 'warn'); return; }
    if (sending) return;
    sending = true;
    sendBtn.disabled = true;
    api.sendBoard(username, text, deviceName())
        .then(data => {
            if (data && data.success === false) throw new Error(data.error || '未知错误');
            inputEl.value = '';
            load();          // 保留 latestId，新留言才能被打上 .fresh
        })
        .catch(err => toast('发送失败：' + err.message, 'error'))
        .finally(() => { sending = false; sendBtn.disabled = false; });
}

/* 删除后整块重取：删中间那条时 latest_id 不变，带 after 的轮询会以为"没变化" */
function removeMessage(id, btn) {
    const username = ctxRef.getUsername();
    if (!username || deleting) return;
    deleting = true;
    btn.disabled = true;
    api.deleteBoard(username, id)
        .then(data => {
            if (data && data.success === false) throw new Error(data.error || '未知错误');
            toast('已删除', 'success');
            reload();
        })
        .catch(err => {
            toast('删除失败：' + err.message, 'error');
            btn.disabled = false;
        })
        .finally(() => { deleting = false; });
}

/* 轮询：只在已登录、页面可见时跑，切走标签页不打扰传输 */
function startPolling() {
    stopPolling();
    timer = setInterval(() => {
        if (!ctxRef.getUsername() || document.hidden) return;
        load();
    }, POLL_MS);
}

function stopPolling() {
    if (timer) clearInterval(timer);
    timer = null;
}

export function init(ctx) {
    ctxRef = ctx;
    ctx.onBoardLoad(reload);

    sendBtn.addEventListener('click', send);
    inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
    document.getElementById('clip-refresh').addEventListener('click', () => { reload(); toast('已刷新', 'success'); });

    listEl.addEventListener('click', e => {
        const btn = e.target.closest && e.target.closest('.clip-actions .qbtn, .clip-more');
        if (!btn) return;
        const row = btn.closest('.clip');
        const body = row.querySelector('.clip-text');
        if (btn.dataset.act === 'toggle') {
            const collapsed = body.classList.toggle('collapsed');
            btn.textContent = collapsed ? '展开' : '收起';
            return;
        }
        if (btn.dataset.act === 'delete') {
            removeMessage(Number(row.dataset.id), btn);
            return;
        }
        toast(copyText(body.textContent) ? '已复制到剪贴板' : '复制失败，请手动选中复制', 'success');
    });

    document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
    ctx.onUserChange(username => {
        if (!username) { stopPolling(); listEl.textContent = ''; latestId = null; return; }
        startPolling();
    });
    startPolling();
}
