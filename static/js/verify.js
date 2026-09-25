/* verify.js — 页面内一键校验：纯 JS SHA-256 跑在 Worker 里。
 * 局域网 http 非安全上下文，crypto.subtle 不可用；Worker 用 Blob URL 起，
 * 主线程按 8MB 切片读文件、以可转移缓冲喂给 Worker，界面不卡。 */

export const VERIFY_MAX = 2 * 1024 * 1024 * 1024;   // >2GB 交给命令行（实测 ~43MB/s，2GB 要 40+ 秒起步）

/* K：前 64 个素数立方根小数部分前 32 位；H0：前 8 个素数平方根小数部分前 32 位（FIPS 180-4） */
const SHA256_WORKER = `'use strict';
const K = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
const H0 = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
let H, blk, tail, total;
const rotr = (x, n) => (x >>> n) | (x << (32 - n));

function reset() { H = H0.slice(); blk = new Uint8Array(64); tail = 0; total = 0; }

function compress() {
    const w = new Uint32Array(64);
    for (let i = 0; i < 16; i++)
        w[i] = (blk[i * 4] << 24) | (blk[i * 4 + 1] << 16) | (blk[i * 4 + 2] << 8) | blk[i * 4 + 3];
    for (let i = 16; i < 64; i++) {
        const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
    for (let i = 0; i < 64; i++) {
        const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
        const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0;
        d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
}

function update(arr) {
    total += arr.length;
    let i = 0;
    if (tail > 0) {
        const need = 64 - tail;
        const take = Math.min(need, arr.length);
        blk.set(arr.subarray(0, take), tail);
        tail += take; i = take;
        if (tail === 64) { compress(); tail = 0; }
    }
    for (; i + 64 <= arr.length; i += 64) { blk.set(arr.subarray(i, i + 64)); compress(); }
    if (i < arr.length) { blk.set(arr.subarray(i), 0); tail = arr.length - i; }
}

function finish() {
    const bitLen = total * 8;
    const hi = Math.floor(bitLen / 4294967296), lo = bitLen % 4294967296;
    blk[tail++] = 0x80;
    if (tail > 56) { while (tail < 64) blk[tail++] = 0; compress(); tail = 0; }
    while (tail < 56) blk[tail++] = 0;
    const view = new DataView(blk.buffer);
    view.setUint32(56, hi); view.setUint32(60, lo);
    compress();
    return Array.from(H, x => x.toString(16).padStart(8, '0')).join('');
}

self.onmessage = e => {
    const d = e.data;
    if (d.init) { reset(); return; }
    if (d.chunk) { update(new Uint8Array(d.chunk)); return; }
    if (d.end) postMessage({ hex: finish() });
};
`;

export function verifyFile(file, onProgress) {
    return new Promise((resolve, reject) => {
        const blobUrl = URL.createObjectURL(new Blob([SHA256_WORKER], { type: 'text/javascript' }));
        const w = new Worker(blobUrl);
        const settle = fn => { w.terminate(); URL.revokeObjectURL(blobUrl); fn(); };
        w.onmessage = e => settle(() => resolve(e.data.hex));
        w.onerror = () => settle(() => reject(new Error('校验线程异常')));
        (async () => {
            w.postMessage({ init: true });
            const CH = 8 * 1024 * 1024;
            for (let off = 0; off < file.size; off += CH) {
                const buf = await file.slice(off, Math.min(off + CH, file.size)).arrayBuffer();
                w.postMessage({ chunk: buf }, [buf]);
                if (onProgress) onProgress(Math.min(1, (off + CH) / file.size));
            }
            w.postMessage({ end: true });
        })().catch(err => settle(() => reject(err)));
    });
}
