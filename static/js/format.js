/* format.js — 数字/时间格式化、HTML 转义、文件图标（emoji 退役，改内联描边 SVG） */

export function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

export function formatSpeed(bps) {
    if (bps < 1024) return bps.toFixed(0) + ' B/s';
    if (bps < 1048576) return (bps / 1024).toFixed(1) + ' KB/s';
    if (bps < 1073741824) return (bps / 1048576).toFixed(1) + ' MB/s';
    return (bps / 1073741824).toFixed(2) + ' GB/s';
}

export function formatTime(seconds) {
    if (!isFinite(seconds) || seconds <= 0) return '--';
    if (seconds < 60) return Math.ceil(seconds) + '秒';
    if (seconds < 3600) return Math.floor(seconds / 60) + '分' + Math.ceil(seconds % 60) + '秒';
    return Math.floor(seconds / 3600) + '时' + Math.floor((seconds % 3600) / 60) + '分';
}

/** 修改时间 → 设计稿的 MM-DD HH:MM */
export function formatDate(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

const SVG_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';

const ICONS = {
    doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    pdf: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 13h1.5a1.5 1.5 0 0 0 0-3H9v6"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    sheet: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/>',
    archive: '<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><line x1="10" y1="13" x2="14" y2="13"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    film: '<rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18M17 3v18M2 8h5M2 16h5M17 8h5M17 16h5M2 12h20"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    tool: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    disc: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="2"/>',
    box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>',
};

const EXT_ICON = {
    txt: 'doc', md: 'pen', rst: 'pen', log: 'doc',
    pdf: 'pdf', epub: 'book',
    doc: 'book', docx: 'book', xls: 'sheet', xlsx: 'sheet', csv: 'sheet', ppt: 'sheet', pptx: 'sheet',
    zip: 'archive', rar: 'archive', '7z': 'archive', gz: 'archive', tar: 'archive', bz2: 'archive',
    mp3: 'music', wav: 'music', flac: 'music',
    mp4: 'film', mkv: 'film', avi: 'film', mov: 'film', webm: 'film',
    jpg: 'image', jpeg: 'image', png: 'image', gif: 'image', bmp: 'image', svg: 'image', webp: 'image', heic: 'image',
    js: 'code', ts: 'code', py: 'code', java: 'code', c: 'code', cpp: 'code', h: 'code', go: 'code', rs: 'code',
    html: 'code', css: 'code', json: 'code', xml: 'code', yml: 'code', yaml: 'code', sh: 'code', sql: 'code',
    exe: 'tool', msi: 'tool', bat: 'tool', apk: 'box', iso: 'disc', img: 'disc',
};

/** 扩展名 → 内联 SVG（无匹配用 doc） */
export function fileIcon(name) {
    const ext = (String(name).split('.').pop() || '').toLowerCase();
    return SVG_OPEN + ICONS[EXT_ICON[ext] || 'doc'] + '</svg>';
}

export const CHECK_SVG = '<svg class="fp-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
