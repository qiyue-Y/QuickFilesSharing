/* main.js — 唯一入口：持有 currentUsername，装配 ctx 并按时序初始化各模块
 * 状态不放全局：各模块只通过 ctx 读写用户名与触发刷新。 */

import * as hud from './hud.js';
import * as files from './files.js';
import * as upload from './upload.js';
import * as download from './download.js';
import * as board from './board.js';
import * as login from './login.js';
import * as transfer from './transfer.js';

let currentUsername = null;

const listeners = {
    userChange: [],
    diskRefresh: [],
    filesRefresh: [],
    boardLoad: [],
};

const mainGrid = document.getElementById('mainGrid');

const ctx = {
    getUsername: () => currentUsername,

    setUsername(username) {
        currentUsername = username;
        // 登录台的显隐由 login.js 自己管（它要播 1.68s 转场），这里只切主区域
        mainGrid.hidden = !username;
        listeners.userChange.forEach(cb => cb(username));
        if (!username) return;
        ctx.refreshFiles();
        listeners.boardLoad.forEach(cb => cb());
    },

    logout() {
        ctx.setUsername(null);
    },

    refreshFiles() { listeners.filesRefresh.forEach(cb => cb()); },
    startDownload(cell, filename) { download.startDownload(cell, filename); },

    onUserChange: reg('userChange'),
    onDiskRefresh: reg('diskRefresh'),
    onFilesRefresh: reg('filesRefresh'),
    onBoardLoad: reg('boardLoad'),
    onActiveChange: transfer.onActiveChange,
};

function reg(key) {
    return cb => listeners[key].push(cb);
}

/* 面板滚动入场 */
const io = new IntersectionObserver(entries => {
    entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('in');
        io.unobserve(entry.target);
    });
}, { threshold: 0.08 });
document.querySelectorAll('.reveal').forEach(el => io.observe(el));

hud.init(ctx);
files.init(ctx);
upload.init(ctx);
download.init(ctx);
board.init(ctx);
login.init(ctx);   // 放最后：autoLogin 会经 ctx.setUsername 触发上面各模块的刷新
