/* files.js — 文件列表渲染、删除、文件信息弹窗（spec §4.1 / §4.3） */

import { api, shareOrigin } from './api.js';
import { formatSize, formatDate, escapeHtml, fileIcon } from './format.js';
import { toast, copyText, openModal, closeModal, closeOnBackdrop } from './ui.js';

const listEl = document.getElementById('file-list');
const modal = document.getElementById('hashModal');

/* ---------- 弹窗里的命令块 ---------- */

function cmdRows(rows) {
    return rows.map(([os, cmd]) => `
        <div class="verify-row">
            <div class="verify-os">${os}</div>
            <div class="verify-cmd"><code>${escapeHtml(cmd)}</code><button type="button" class="qbtn sm verify-copy">复制</button></div>
        </div>`).join('');
}

function verifyCommands(filename) {
    return cmdRows([
        ['Windows · CMD', `certutil -hashfile "${filename}" SHA256`],
        ['Windows · PowerShell', `Get-FileHash -Algorithm SHA256 "${filename}"`],
        ['Linux', `sha256sum "${filename}"`],
        ['macOS', `shasum -a 256 "${filename}"`],
    ]);
}

function downloadCommands(username, filename, origin) {
    const url = `${origin}/api/download?username=${encodeURIComponent(username)}&filename=${encodeURIComponent(filename)}`;
    return cmdRows([
        ['Windows · CMD', `curl -C - -o "${filename}" "${url}"`],
        ['Windows · PowerShell', `curl.exe -C - -o "${filename}" "${url}"`],
        ['Linux / macOS', `curl -C - -o "${filename}" "${url}"`],
        ['aria2 · 4 线程', `aria2c -x4 -s4 -c -o "${filename}" "${url}"`],
    ]);
}

/* 复制按钮：整份列表 + 弹窗共用一个委托 */
document.addEventListener('click', e => {
    const btn = e.target.closest && e.target.closest('.verify-copy');
    if (!btn) return;
    const ok = copyText(btn.parentElement.querySelector('code').textContent);
    btn.textContent = ok ? '已复制' : '复制失败';
    setTimeout(() => { btn.textContent = '复制'; }, 1500);
});

document.getElementById('verifyHelpBox').innerHTML = verifyCommands('文件名.zip');

/* ---------- 行渲染 ---------- */

const PROG_SKELETON = `
    <div class="fprog"><div class="fp-inner">
        <div class="fp-line">
            <span class="fp-dot"></span>
            <div class="fp-track"><div class="fp-fill" style="width:0%"><span class="fp-sheen"></span></div><span class="fp-glint" style="left:0%"></span></div>
            <div class="fp-pct"><span class="fp-pct-num">0.0</span><i>%</i></div>
        </div>
        <div class="fp-meta"></div>
    </div></div>`;

/** 生成一行；文件名只进 data-* 与 textContent，不拼进 HTML */
export function makeRow({ name, size, mtime, sha256 }) {
    const cell = document.createElement('div');
    cell.className = 'fcell';
    cell.dataset.filename = name;
    cell.innerHTML = `
        <div class="frow">
            <span class="ftype">${fileIcon(name)}</span>
            <div class="fmeta">
                <div class="fname"></div>
                <div class="fsub"></div>
            </div>
            <div class="factions">
                <button type="button" class="qbtn sm dl">下载</button>
                <button type="button" class="qbtn sm danger del">删除</button>
            </div>
        </div>` + PROG_SKELETON;

    const fname = cell.querySelector('.fname');
    fname.textContent = name;
    fname.title = name;

    const sub = cell.querySelector('.fsub');
    const pre = document.createElement('span');
    pre.className = 'fsub-pre';
    pre.textContent = `${formatSize(size)} · ${formatDate(mtime)} · `;
    sub.appendChild(pre);
    const hashBtn = document.createElement('button');
    hashBtn.type = 'button';
    hashBtn.className = 'fhash';
    if (sha256) {
        hashBtn.textContent = `SHA-256: ${sha256}`;
        hashBtn.title = `SHA-256: ${sha256}\n点击查看完整校验码与命令行下载`;
    } else {
        hashBtn.textContent = '校验码未记录，点击计算';
        hashBtn.title = '点击让服务端计算 SHA-256（大文件需数分钟）';
        hashBtn.classList.add('fresh');
    }
    sub.appendChild(hashBtn);
    return cell;
}

/* ---------- 列表 ---------- */

let ctxRef = null;

export function loadFiles() {
    const username = ctxRef.getUsername();
    if (!username) return Promise.resolve();
    return api.files(username)
        .then(data => {
            listEl.innerHTML = '';
            const files = data.files || [];
            if (files.length === 0) {
                listEl.innerHTML = '<div class="file-list-empty">池底空空 · 还没有文件</div>';
                return;
            }
            const frag = document.createDocumentFragment();
            files.forEach(f => frag.appendChild(makeRow(f)));
            listEl.appendChild(frag);
        })
        .catch(err => toast('文件列表加载失败：' + err.message, 'error'));
}

listEl.addEventListener('click', e => {
    const cell = e.target.closest('.fcell');
    if (!cell) return;
    const filename = cell.dataset.filename;
    if (e.target.closest('.dl')) ctxRef.startDownload(cell, filename);
    else if (e.target.closest('.del')) removeFile(cell, filename);
    else if (e.target.closest('.fhash')) openHashModal(filename, e.target.closest('.fhash'));
});

function removeFile(cell, filename) {
    if (!confirm(`确定要删除文件 "${filename}" 吗？`)) return;
    api.remove(ctxRef.getUsername(), filename)
        .then(data => {
            if (!data.success) throw new Error(data.error || '未知错误');
            cell.classList.add('gone');
            setTimeout(() => { cell.remove(); if (!listEl.querySelector('.fcell')) loadFiles(); }, 700);
            toast('已删除: ' + filename, 'success');
        })
        .catch(err => toast('删除失败：' + err.message, 'error'));
}

/* ---------- 弹窗 ---------- */

function openHashModal(filename, trigger) {
    const valueInput = document.getElementById('hashModalValue');
    const hint = document.getElementById('hashModalHint');
    const username = ctxRef.getUsername();

    shareOrigin().then(origin => {
        document.getElementById('hashModalFile').textContent = filename;
        document.getElementById('hashModalCmds').innerHTML = verifyCommands(filename);
        document.getElementById('hashModalDl').innerHTML = downloadCommands(username, filename, origin);
        valueInput.value = '';
        valueInput.placeholder = '计算中…';
        hint.textContent = '正在获取校验码…';
        openModal(modal, trigger);

        api.fileHash(username, filename)
            .then(info => {
                if (!info.success) throw new Error(info.error || '获取失败');
                valueInput.value = info.sha256;
                valueInput.placeholder = '';
                valueInput.focus();
                valueInput.select();
                const copied = copyText(info.sha256);
                hint.textContent = (copied ? '已复制到剪贴板。' : '输入框已全选，按 Ctrl+C 复制。')
                    + '接收端下载完后用下面的命令算一遍，和这串对比。'
                    + (info.cached ? '' : '（本次为服务端现算，大文件会慢一些）');
            })
            .catch(err => {
                valueInput.placeholder = '获取失败';
                hint.textContent = '获取校验码失败：' + err.message;
            });
    });
}

document.getElementById('hashModalClose').addEventListener('click', closeModal);
closeOnBackdrop(modal);

export function init(ctx) {
    ctxRef = ctx;
    ctx.onFilesRefresh(loadFiles);
}
