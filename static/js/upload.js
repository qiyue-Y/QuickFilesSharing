/* upload.js — 分片 4 路并行上传（裸 body + X-File-Id/X-Chunk-Index，协议一字未改）
 * 批量队列 + 服务器磁盘预检 + 行内进度。 */

import { api, CHUNK_SIZE, PARALLEL_STREAMS, MAX_UPLOAD_SIZE } from './api.js';
import { formatSize } from './format.js';
import { toast } from './ui.js';
import { makeRow } from './files.js';
import { bindRowProgress } from './progress.js';
import { acquire, release, cancelActive } from './transfer.js';

const fileInput = document.getElementById('fileInput');
const listEl = document.getElementById('file-list');

let ctxRef = null;

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------- 入口 ---------- */

function onPick() {
    const files = Array.from(fileInput.files || []);
    fileInput.value = '';
    if (files.length) uploadFiles(files);
}

/** 整页拖放：任何位置松手都进上传队列；不拦的话浏览器会直接打开文件顶掉页面 */
function initDrag() {
    const hasFiles = e => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
    const canDrop = e => hasFiles(e) && !!ctxRef.getUsername();

    document.addEventListener('dragover', e => {
        if (!canDrop(e)) return;
        e.preventDefault();
        document.body.classList.add('dragging');
    });
    document.addEventListener('dragleave', e => {
        if (e.relatedTarget) return;   // 只是穿梭到子元素，没出窗口
        document.body.classList.remove('dragging');
    });
    document.addEventListener('drop', e => {
        document.body.classList.remove('dragging');
        if (!canDrop(e)) return;
        e.preventDefault();
        const files = Array.from(e.dataTransfer.files || []);
        if (files.length) uploadFiles(files);
    });
}

async function uploadFiles(files) {
    const username = ctxRef.getUsername();
    if (!username) { toast('请先登录', 'error'); return; }

    // 预检：合并期间分片与成品并存，峰值 ≈ 本批总量 + 最大文件，再留 5% 余量
    try {
        const disk = await api.disk();
        if (disk.success) {
            const totalBytes = files.reduce((s, f) => s + f.size, 0);
            const maxBytes = files.reduce((m, f) => Math.max(m, f.size), 0);
            const required = (totalBytes + maxBytes) * 1.05;
            if (disk.free < required) {
                toast(`服务器剩余空间不足：本次约需 ${formatSize(required)}（含合并期间的临时占用），当前可用 ${formatSize(disk.free)}`, 'error', 6000);
                return;
            }
        }
    } catch (e) { /* 查询失败不拦上传 */ }

    const empty = listEl.querySelector('.file-list-empty');
    if (empty) empty.remove();

    let ok = 0;
    let firstError = null;
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (file.size > MAX_UPLOAD_SIZE) {
            firstError = firstError || `${file.name}: 文件过大，最大支持 30GB`;
            continue;
        }
        try {
            await uploadOne(file, { index: i + 1, total: files.length });
            ok++;
        } catch (err) {
            if (err && err.busy) { firstError = '已有传输进行中，批量上传已停止'; break; }
            firstError = firstError || (err && err.message) || '未知错误';
            if (err && err.cancelled) { firstError = '上传已取消'; break; }
        }
    }
    const failed = files.length - ok;
    if (ok && !failed) toast(`批量上传完成：成功 ${ok} 个文件`, 'success');
    else if (ok) toast(`成功 ${ok} 个，失败 ${failed} 个（首个原因：${firstError}）`, 'warn', 6000);
    else if (firstError) toast(firstError, 'error', 6000);
    ctxRef.refreshFiles();
}

/* ---------- 单个文件 ---------- */

function uploadOne(file, batch) {
    const username = ctxRef.getUsername();
    const token = acquire('upload', username);
    if (!token) {
        const err = new Error('已有传输进行中');
        err.busy = true;
        return Promise.reject(err);
    }

    const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
    const fileId = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    token.fileId = fileId;

    const cell = makeRow({ name: file.name, size: file.size, mtime: 0, sha256: null });
    cell.classList.add('transferring', 'fresh-cell');
    cell.querySelector('.fsub').textContent = `${formatSize(file.size)} · 上传中`;
    listEl.insertBefore(cell, listEl.firstChild);

    const prefix = batch.total > 1 ? `第 ${batch.index}/${batch.total} 个` : '';
    const prog = bindRowProgress(cell, {
        totalSize: file.size,
        totalChunks,
        dir: prefix ? `上传 ${prefix}` : '上传',
        onCancel: cancelActive,
        onDone: () => cell.remove(),
        onFailed: () => cell.remove(),
    });
    token.timer = prog.timer;

    return new Promise((resolve, reject) => {
        const uploadChunk = (chunkIndex) => new Promise((chunkResolve, chunkReject) => {
            const blob = file.slice(chunkIndex * CHUNK_SIZE, Math.min((chunkIndex + 1) * CHUNK_SIZE, file.size));
            const xhr = new XMLHttpRequest();
            token.xhrs.push(xhr);
            xhr.upload.addEventListener('progress', e => {
                if (e.lengthComputable) prog.chunkProgress[chunkIndex] = e.loaded;
            });
            xhr.addEventListener('load', () => {
                if (xhr.status !== 200) {
                    let detail = '';
                    try { detail = JSON.parse(xhr.responseText).error || ''; } catch (e) { /* 非 JSON 响应 */ }
                    chunkReject(new Error('HTTP ' + xhr.status + (detail ? '：' + detail : '')));
                    return;
                }
                let data;
                try { data = JSON.parse(xhr.responseText); } catch (e) { chunkReject(new Error('响应解析错误')); return; }
                if (data.success) { prog.completeChunk(chunkIndex, blob.size); chunkResolve(); }
                else chunkReject(new Error(data.error || '分片上传失败'));
            });
            xhr.addEventListener('error', () => chunkReject(new Error('网络错误')));
            xhr.addEventListener('abort', () => chunkReject(new Error('已取消')));
            // 裸 body：不拼 multipart，服务端省一次临时文件落盘
            xhr.open('POST', api.chunkUploadUrl(username));
            xhr.setRequestHeader('X-File-Id', fileId);
            xhr.setRequestHeader('X-Chunk-Index', chunkIndex);
            xhr.send(blob);
        });

        (async () => {
            const queue = Array.from({ length: totalChunks }, (_, i) => i);
            const inFlight = new Set();
            let fatal = false;
            let firstError = null;   // 保住服务端拒绝的原始话术（如"磁盘空间不足"）

            while (queue.length > 0 && !fatal) {
                const idx = queue.shift();
                const p = uploadChunk(idx).catch(async err => {
                    if (!firstError) firstError = err;
                    if (token.cancelled) throw err;
                    await sleep(300);
                    if (token.cancelled) throw err;
                    return uploadChunk(idx).catch(async () => {
                        await sleep(800);
                        fatal = true;
                        throw firstError;
                    });
                });
                inFlight.add(p);
                // finally 派生的新 promise 没人 await，分片失败时会刷一屏 Uncaught (in promise)
                p.finally(() => inFlight.delete(p)).catch(() => {});
                if (inFlight.size >= PARALLEL_STREAMS) await Promise.race(inFlight);
            }
            await Promise.all(inFlight);
            if (fatal) throw firstError || new Error('部分分片上传失败');
        })()
            .then(() => {
                prog.settle('正在合并分片…');
                return api.merge({
                    username,
                    file_id: fileId,
                    filename: file.name,
                    total_chunks: totalChunks,
                });
            })
            .then(data => {
                release(token);
                if (!data.success) throw new Error(data.error || '合并失败');
                prog.finish();
                resolve(data.filename);
            })
            .catch(err => {
                release(token);
                prog.fail(token.cancelled ? '上传已取消' : '上传失败：' + err.message);
                if (token.cancelled) err.cancelled = true;
                reject(err);
            });
    });
}

export function init(ctx) {
    ctxRef = ctx;
    fileInput.addEventListener('change', onPick);
    initDrag();
}
