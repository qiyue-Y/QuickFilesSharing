/* api.js — 15 个接口的封装与传输常量。username 只走 query/body，绝不进请求头 */

export const CHUNK_SIZE = 32 * 1024 * 1024;          // 32MB 每片
export const PARALLEL_STREAMS = 4;                   // 4 路并行
export const NATIVE_DL_LIMIT = 1024 * 1024 * 1024;   // >1GB 交给浏览器下载管理器（分片方案要整文件驻留内存）
export const MAX_UPLOAD_SIZE = 30 * 1024 * 1024 * 1024;
export const LOW_DISK_BYTES = 10 * 1024 * 1024 * 1024;

function url(path, params) {
    return path + '?' + new URLSearchParams(params);
}

async function getJSON(path, params) {
    const res = await fetch(url(path, params));
    return res.json();
}

async function postJSON(path, body) {
    const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}

export const api = {
    board: (username, afterId) => getJSON('/api/board', afterId == null ? { username } : { username, after: afterId }),
    sendBoard: (username, text, device) => postJSON('/api/board', { username, text, device }),
    deleteBoard: (username, id) => postJSON('/api/board/delete', { username, id }),
    files: (username) => getJSON('/api/files', { username }),
    disk: () => getJSON('/api/disk', {}),
    serverAddr: () => getJSON('/api/server-addr', {}),
    fileInfo: (username, filename) => getJSON('/api/file/info', { username, filename }),
    fileHash: (username, filename) => getJSON('/api/file/hash', { username, filename }),
    remove: (username, filename) => postJSON('/api/delete', { username, filename }),
    merge: (payload) => postJSON('/api/upload/merge', payload),
    uploadStatus: (username, fileId) => getJSON('/api/upload/status', { username, file_id: fileId }),
    abortUpload: (username, fileId) => postJSON('/api/upload/abort', { username, file_id: fileId }),

    chunkUploadUrl: (username, filename) => url('/api/upload/chunk', { username, filename }),
    chunkDownloadUrl: (username, filename) => url('/api/download/chunk', { username, filename }),
    downloadUrl: (username, filename) => url('/api/download', { username, filename }),
};

/* 复制给别人的地址：页面用 localhost 打开时换成服务器局域网 IP，否则接收端连不上 */
export async function shareOrigin() {
    if (!['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) return location.origin;
    try {
        const d = await api.serverAddr();
        if (d.ip) {
            const u = new URL(location.origin);
            u.hostname = d.ip;
            return u.origin;
        }
    } catch (e) { /* 取不到 IP 就退回地址栏里的地址 */ }
    return location.origin;
}
