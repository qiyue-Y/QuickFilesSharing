/* progress.js — 文件行内 .fprog 的渲染（原 makeProgressUI 的后继）
 * 速度用 8 窗口滑动平均，UI 由 200ms 定时器驱动，progress 事件稀疏时也持续刷新。 */

import { PARALLEL_STREAMS } from './api.js';
import { formatSize, formatSpeed, formatTime, CHECK_SVG } from './format.js';

const TICK_MS = 200;
const DONE_VISIBLE_MS = 2600;

/**
 * @param cell   .fcell 元素（含 .fprog 骨架）
 * @param opts   { totalSize, totalChunks, dir: '上传'|'下载', prefix }
 */
export function bindRowProgress(cell, opts) {
    const fill = cell.querySelector('.fp-fill');
    const glint = cell.querySelector('.fp-glint');
    const pctNum = cell.querySelector('.fp-pct-num');
    const meta = cell.querySelector('.fp-meta');

    const chunkProgress = new Array(opts.totalChunks).fill(0);
    let completedChunks = 0;
    const startTime = Date.now();
    let speeds = [];
    let lastTotal = 0;
    let lastTime = startTime;

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'qbtn sm danger fp-cancel';
    cancelBtn.textContent = '取消';
    cancelBtn.addEventListener('click', () => opts.onCancel && opts.onCancel());

    function renderMeta(html, showCancel) {
        meta.innerHTML = html;
        // 取消按钮只活在传输中，否则会出现"按钮在、传输已结束"的残留态
        if (showCancel) meta.appendChild(cancelBtn);
    }

    function tick() {
        const now = Date.now();
        const totalLoaded = chunkProgress.reduce((a, b) => a + b, 0);
        const percent = opts.totalSize > 0 ? Math.min(100, (totalLoaded / opts.totalSize) * 100) : 0;

        const timeDiff = (now - lastTime) / 1000;
        const bytesDiff = totalLoaded - lastTotal;
        if (timeDiff >= 0.25 && bytesDiff > 0) {
            speeds.push(bytesDiff / timeDiff);
            if (speeds.length > 8) speeds.shift();
            lastTotal = totalLoaded;
            lastTime = now;
        }
        const avgSpeed = speeds.length > 0 ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
        const eta = avgSpeed > 0 ? (opts.totalSize - totalLoaded) / avgSpeed : 0;

        const pctText = percent.toFixed(1);
        fill.style.width = pctText + '%';
        glint.style.left = pctText + '%';
        pctNum.textContent = pctText;
        renderMeta(
            `<span>${opts.dir}</span> · <span>${formatSpeed(avgSpeed)}</span>` +
            ` · <span>剩余 ${formatTime(eta)}</span>` +
            ` · <span>${formatSize(totalLoaded)} / ${formatSize(opts.totalSize)}</span>` +
            ` · <span>分片 ${completedChunks}/${opts.totalChunks}</span>` +
            ` · <span>${PARALLEL_STREAMS} 路并行</span>`,
            true
        );
    }

    const timer = setInterval(tick, TICK_MS);
    tick();

    return {
        timer,
        chunkProgress,
        setCompleted(n) { completedChunks = n; },
        completeChunk(idx, fullSize) {
            chunkProgress[idx] = fullSize;
            completedChunks++;
        },
        /** 合并/组装等收尾阶段：停表，保留 100% */
        settle(label) {
            clearInterval(timer);
            fill.style.width = '100%';
            glint.style.left = '100%';
            pctNum.textContent = '100.0';
            renderMeta(`<span>${label}</span>`);
        },
        /** 成功收尾：换成对勾 + 平均速度，DONE_VISIBLE_MS 后交还给调用方刷新列表 */
        finish() {
            const elapsed = (Date.now() - startTime) / 1000;
            const avg = elapsed > 0 ? opts.totalSize / elapsed : 0;
            cell.classList.remove('transferring');
            cell.classList.add('is-done');
            fill.style.width = '100%';
            pctNum.textContent = '100.0';
            renderMeta(`${CHECK_SVG}<span>完成 · 平均 ${formatSpeed(avg)} · 用时 ${formatTime(elapsed)}</span>`);
            setTimeout(() => opts.onDone && opts.onDone(), DONE_VISIBLE_MS);
        },
        /** 失败/取消：停表并显示原因，等用户处置 */
        fail(message) {
            clearInterval(timer);
            renderMeta(`<span>${message}</span>`);
            setTimeout(() => opts.onFailed && opts.onFailed(message), 1200);
        },
        stop() {
            clearInterval(timer);
        },
    };
}
