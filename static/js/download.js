/* download.js — ≤1GB 分片并行下载到内存后触发保存；>1GB 交给浏览器下载管理器
 * 分片方案整文件驻留内存，所以有 1GB 上限，勿改回整文件流式。 */

import { api, CHUNK_SIZE, PARALLEL_STREAMS, NATIVE_DL_LIMIT } from './api.js';
import { formatSize } from './format.js';
import { toast } from './ui.js';
import { bindRowProgress } from './progress.js';
import { acquire, release, cancelActive } from './transfer.js';

const sleep = ms => new Promise(r => setTimeout(r, ms));

let ctxRef = null;

function saveBlob(blob, filename) {
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objUrl);
}

function nativeDownload(username, filename, size) {
    toast(`文件较大（${formatSize(size)}），已交给浏览器下载管理器，进度与续传看浏览器下载栏`, 'info', 8000);
    const a = document.createElement('a');
    a.href = api.downloadUrl(username, filename);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
}

export function startDownload(cell, filename) {
    const username = ctxRef.getUsername();
    if (!username) { toast('请先登录', 'error'); return; }

    api.fileInfo(username, filename)
        .then(info => {
            if (!info.success) throw new Error(info.error || '文件不存在');
            if (info.size > NATIVE_DL_LIMIT) {
                nativeDownload(username, filename, info.size);
                return;
            }
            downloadChunked(cell, username, filename, info.size);
        })
        .catch(err => toast('下载失败：' + err.message, 'error'));
}

function downloadChunked(cell, username, filename, fileSize) {
    const token = acquire('download', username);
    if (!token) {
        toast('已有传输进行中，请等它完成或点"取消"', 'warn');
        return;
    }

    const totalChunks = Math.max(1, Math.ceil(fileSize / CHUNK_SIZE));
    const chunkData = new Array(totalChunks).fill(null);
    cell.classList.add('transferring');
    const prog = bindRowProgress(cell, {
        totalSize: fileSize,
        totalChunks,
        dir: '下载',
        onCancel: cancelActive,
        onDone: () => ctxRef.refreshFiles(),
        onFailed: () => ctxRef.refreshFiles(),
    });
    token.timer = prog.timer;

    const downloadChunk = (chunkIndex) => new Promise((resolve, reject) => {
        const start = chunkIndex * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE - 1, fileSize - 1);
        const xhr = new XMLHttpRequest();
        token.xhrs.push(xhr);
        xhr.responseType = 'arraybuffer';
        xhr.addEventListener('progress', e => {
            if (e.lengthComputable) prog.chunkProgress[chunkIndex] = e.loaded;
        });
        xhr.addEventListener('load', () => {
            if (xhr.status === 200 || xhr.status === 206) {
                prog.completeChunk(chunkIndex, end - start + 1);
                chunkData[chunkIndex] = new Uint8Array(xhr.response);
                resolve();
            } else reject(new Error('HTTP ' + xhr.status));
        });
        xhr.addEventListener('error', () => reject(new Error('网络错误')));
        xhr.addEventListener('abort', () => reject(new Error('已取消')));
        xhr.open('GET', api.chunkDownloadUrl(username, filename));
        xhr.setRequestHeader('Range', `bytes=${start}-${end}`);
        xhr.send();
    });

    (async () => {
        const queue = Array.from({ length: totalChunks }, (_, i) => i);
        const inFlight = new Set();
        while (queue.length > 0) {
            const idx = queue.shift();
            const p = downloadChunk(idx).catch(async err => {
                if (token.cancelled) throw err;
                await sleep(300);
                if (token.cancelled) throw err;
                return downloadChunk(idx);
            });
            inFlight.add(p);
            // finally 派生的新 promise 没人 await，分片失败时会刷一屏 Uncaught (in promise)
            p.finally(() => inFlight.delete(p)).catch(() => {});
            if (inFlight.size >= PARALLEL_STREAMS) await Promise.race(inFlight);
        }
        await Promise.all(inFlight);
    })()
        .then(() => {
            prog.settle('正在组装文件…');
            const totalLength = chunkData.reduce((s, a) => s + a.length, 0);
            const result = new Uint8Array(totalLength);
            let offset = 0;
            for (const arr of chunkData) { result.set(arr, offset); offset += arr.length; }
            release(token);
            saveBlob(new Blob([result], { type: 'application/octet-stream' }), filename);
            prog.finish();
        })
        .catch(err => {
            release(token);
            prog.fail(token.cancelled ? '下载已取消' : '下载失败：' + err.message);
        });
}

export function init(ctx) {
    ctxRef = ctx;
    ctx.onActiveChange(token => {
        if (token) return;
        document.querySelectorAll('.fcell.transferring').forEach(el => el.classList.remove('transferring'));
    });
}
