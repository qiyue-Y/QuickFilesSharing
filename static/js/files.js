/* files.js — 文件列表渲染、删除、文件信息弹窗（spec §4.1 / §4.3） */

import { api, shareOrigin } from './api.js';
import { verifyFile, VERIFY_MAX } from './verify.js';
import { formatSize, formatDate, escapeHtml, fileIcon } from './format.js';
import { toast, copyText, openModal, closeModal, closeOnBackdrop, confirmDialog, createGeneration } from './ui.js';

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
    confirmDialog({
        title: '删除文件',
        body: `确定要删除 "${filename}" 吗？删除后不可恢复。`,
        okText: '删除',
        onOk: () => api.remove(ctxRef.getUsername(), filename).then(data => {
            if (!data.success) throw new Error(data.error || '未知错误');
            cell.classList.add('gone');
            setTimeout(() => { cell.remove(); if (!listEl.querySelector('.fcell')) loadFiles(); }, 700);
            toast('已删除: ' + filename, 'success');
        }).catch(err => {
            toast('删除失败：' + err.message, 'error');
            return false;
        }),
    });
}

/* ---------- 弹窗 ---------- */

const hashReq = createGeneration();   // 每次打开弹窗领新号，旧轮询凭号作废

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
        verifyGen.next();
        showVerify('');
        openModal(modal, trigger);

        const reqId = hashReq.next();
        (function fetchHash() {
            api.fileHash(username, filename)
                .then(info => {
                    if (!hashReq.is(reqId) || modal.hidden) return;
                    if (!info.success) throw new Error(info.error || '获取失败');
                    if (info.computing) {
                        hint.textContent = '服务端正在计算校验码（大文件需数分钟），每 3 秒自动重试…';
                        setTimeout(fetchHash, 3000);
                        return;
                    }
                    valueInput.value = info.sha256;
                    valueInput.placeholder = '';
                    valueInput.focus();
                    valueInput.select();
                    const copied = copyText(info.sha256);
                    hint.textContent = (copied ? '已复制到剪贴板。' : '输入框已全选，按 Ctrl+C 复制。')
                        + '接收端下载完后用下面的命令算一遍，和这串对比。';
                })
                .catch(err => {
                    if (!hashReq.is(reqId) || modal.hidden) return;
                    valueInput.placeholder = '获取失败';
                    hint.textContent = '获取校验码失败：' + err.message;
                });
        })();
    });
}

document.getElementById('hashModalClose').addEventListener('click', closeModal);
closeOnBackdrop(modal);

/* ---------- 页面内一键校验（verify.js 的 SHA-256 Worker） ---------- */

const verifyDrop = document.getElementById('verifyDrop');
const verifyInput = document.getElementById('verifyInput');
const verifyResult = document.getElementById('verifyResult');
const verifyGen = createGeneration();

function showVerify(msg, state) {
    verifyResult.hidden = !msg;
    verifyResult.textContent = msg || '';
    verifyResult.className = 'verify-result';
    if (state === 'ok') verifyResult.classList.add('ok');
    if (state === 'bad') verifyResult.classList.add('bad');
    if (state === 'run') verifyResult.classList.add('run');
}

async function runVerify(file) {
    const expected = document.getElementById('hashModalValue').value;
    if (!expected) { showVerify('校验码尚未就绪，稍候再放入文件', 'run'); return; }
    if (file.size > VERIFY_MAX) {
        showVerify(`文件 ${formatSize(file.size)} 超过本页 2GB 上限，请用上面的命令行校验`, 'run');
        return;
    }
    const token = verifyGen.next();
    const started = performance.now();
    try {
        const digest = await verifyFile(file, p => {
            if (verifyGen.is(token))
                showVerify(`计算中 ${(p * 100).toFixed(0)}%（${formatSize(file.size * p)} / ${formatSize(file.size)}）`, 'run');
        });
        if (!verifyGen.is(token)) return;
        const secs = (performance.now() - started) / 1000;
        if (digest === expected)
            showVerify(`✅ 与服务器记录一致 · ${formatSize(file.size)} 用时 ${secs.toFixed(1)}s（约 ${formatSize(file.size / secs)}/s）`, 'ok');
        else
            showVerify(`❌ 不一致！本页算出 ${digest}，服务器记录 ${expected}。文件可能没下完或被改动`, 'bad');
    } catch (err) {
        if (verifyGen.is(token)) showVerify('校验失败：' + err.message, 'bad');
    }
}

verifyDrop.addEventListener('dragover', e => {
    e.preventDefault(); e.stopPropagation();
    verifyDrop.classList.add('dragover');
});
verifyDrop.addEventListener('dragleave', () => verifyDrop.classList.remove('dragover'));
verifyDrop.addEventListener('drop', e => {
    e.preventDefault(); e.stopPropagation();   // 冒泡到 document 会被当成"上传投放"
    verifyDrop.classList.remove('dragover');
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) runVerify(f);
});
verifyInput.addEventListener('change', () => {
    const f = verifyInput.files[0];
    verifyInput.value = '';
    if (f) runVerify(f);
});

export function init(ctx) {
    ctxRef = ctx;
    ctx.onFilesRefresh(loadFiles);
}
