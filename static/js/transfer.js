/* transfer.js — 同一时刻只允许一个传输的闸门（spec §6）
 * token 携带自己的 xhrs / cancelled / fileId / timer，所有清理只认 token，
 * 绝不引用全局句柄——旧版三个全局单例被并发传输互相覆盖，取消时会拿残留的
 * file_id 误删正在上传的分片。 */

import { api } from './api.js';

let active = null;
const listeners = [];

/** 抢闸门，已被占用返回 null */
export function acquire(kind, username) {
    if (active) return null;
    active = { kind, username, xhrs: [], cancelled: false, fileId: null, timer: null };
    notify();
    return active;
}

export function release(token) {
    if (active !== token) return;
    if (token.timer) { clearInterval(token.timer); token.timer = null; }
    active = null;
    notify();
}

/** 取消当前传输：中断所有 XHR，上传还要通知后端丢分片 */
export function cancelActive() {
    const token = active;
    if (!token || token.cancelled) return;
    token.cancelled = true;
    token.xhrs.forEach(x => { try { x.abort(); } catch (e) { /* 已结束的请求 */ } });
    if (token.kind === 'upload' && token.fileId) {
        api.abortUpload(token.username, token.fileId).catch(() => {});
    }
}

export function onActiveChange(cb) {
    listeners.push(cb);
    cb(active);
}

function notify() {
    listeners.forEach(cb => cb(active));
}

window.addEventListener('beforeunload', e => {
    if (!active) return;
    e.preventDefault();
    e.returnValue = '';
});
