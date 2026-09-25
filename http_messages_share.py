"""
简易文件快传 + 共享留言板 HTTP 服务
功能：用户按用户名进入后，可查看/下载/删除自己的文件，并在共享留言板上收发文本
存储：留言板为全员共享的一块板，存 clipboards/messages.db（SQLite，标准库）；
     文件按用户隔离存 files/<用户名>/
运行：python http_messages_share.py
访问：http://localhost:5000（启动后自动打开浏览器；端口被旧实例占用时会拒绝启动）
上传限制：最大30GB（支持分片并行上传，跑满带宽）
下载：支持 Range 分片并行下载
完整性：每个文件记录 SHA-256（上传/合并时顺带算出），可对比校验
日志：logs/app.log（滚动，20MB × 5），同时输出到控制台
"""

from flask import Flask, g, render_template, request, jsonify, send_from_directory, send_file, Response
from werkzeug.exceptions import HTTPException
import hashlib
import json
import logging
import queue
import re
import sqlite3
import sys
import os
import time
import shutil
import glob
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from urllib.parse import quote

app = Flask(__name__)
# 30GB 最大上传大小 (30 * 1024^3 字节)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024 * 1024  # 30GB max file size

# === 调优参数 ===
CHUNK_SIZE = 32 * 1024 * 1024       # 分片大小：32MB（前端分片）
STREAM_CHUNK = 16 * 1024 * 1024     # 流式写入缓冲：16MB
SOCKET_SEND_BUF = 4 * 1024 * 1024   # Socket 发送缓冲：4MB
SOCKET_RECV_BUF = 4 * 1024 * 1024   # Socket 接收缓冲：4MB

# 完整性校验
HASH_ALGO = "sha256"                # 校验算法，同时作为接口字段名
HASHES_FILE = ".hashes.json"        # 每个用户目录下的哈希记录
_hash_lock = threading.Lock()       # 保护哈希记录的读改写

# 输入校验：username/filename/file_id 直接拼进存储路径，必须挡住路径穿越
_USERNAME_RE = re.compile(r"^[\w-]{1,64}$")   # \w 含中文等 Unicode 字母数字
_FILE_ID_RE = re.compile(r"^[A-Za-z0-9]{1,64}$")

# 留言板：全员共用一块板（文件仍按用户隔离），SQLite 单文件、标准库自带
BOARD_VISIBLE = 5        # 页面只展示最近 5 条，更早的留在库里不展示
BOARD_TEXT_MAX = 2000    # 单条留言字数上限
_board_lock = threading.Lock()   # 串行化 INSERT，避免多线程同时写

# 存储目录：锚定到 py 文件所在目录。send_from_directory 以 app.root_path（即本文件位置）为基准，
# 其余接口若跟随进程 CWD，从其他目录启动服务时两边会分裂（列表有文件、下载 404），故统一锚定
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIPBOARD_DIR = os.path.join(_BASE_DIR, "clipboards")
BOARD_DB = os.path.join(CLIPBOARD_DIR, "messages.db")   # 共享留言板；开着库时同目录会有 -wal/-shm
FILES_DIR = os.path.join(_BASE_DIR, "files")
LOG_DIR = os.path.join(_BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
for _d in (CLIPBOARD_DIR, FILES_DIR, LOG_DIR):
    if not os.path.exists(_d):
        os.makedirs(_d)

log = logging.getLogger("qfs")


def setup_logging():
    """配置日志：控制台 + 滚动文件（单文件 20MB，保留 5 份）"""
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s [%(process)d] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(stream_handler)

    # gunicorn 多 worker 共享同一文件句柄会让轮转互相踩踏，交给 gunicorn 自己的 accesslog/errorlog
    if "gunicorn" not in sys.modules:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8", delay=True
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    log.info("日志初始化完成 -> %s", os.path.abspath(LOG_FILE))


setup_logging()


def normalize_username(username):
    """用户名同时用作存储目录名，先校验再用；非法返回 None，空白回退 default"""
    if not username or not str(username).strip():
        return "default"
    username = str(username).strip()
    return username if _USERNAME_RE.match(username) else None


# Windows 设备名：open("NUL.txt") 也会命中设备而不是创建文件，上传会"假成功"，整类拒绝
_WIN_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(filename):
    """文件名校验：拒绝路径分隔符、..、隐藏文件（含 .hashes.json）、控制字符、
    Windows 设备名、结尾点/空格（Windows 会静默归一化，导致哈希记录键对不上）、超长名；
    非法返回 None"""
    if not filename:
        return None
    filename = str(filename).strip()
    if not filename or filename in (".", ".."):
        return None
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    if any(ord(c) < 32 for c in filename):
        return None
    if filename.split(".")[0].upper() in _WIN_DEVICE_NAMES:
        return None
    if filename != filename.rstrip(" ."):
        return None
    if len(filename) > 200:
        return None
    return filename


def bad_request(error):
    return jsonify({"success": False, "error": error}), 400


def board_conn():
    conn = sqlite3.connect(BOARD_DB, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_device(device):
    """设备名只用于展示：压平空白、去掉控制字符、限长 24"""
    device = re.sub(r"\s+", " ", str(device or "")).strip()[:24]
    return "".join(c for c in device if ord(c) >= 32) or "未知设备"


def init_board():
    """建表。留言板只有 SQLite 这一个存储，代码不读旧的 clipboards/<user>.txt"""
    conn = board_conn()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  author TEXT NOT NULL,"
            "  device TEXT NOT NULL,"
            "  ts REAL NOT NULL,"
            "  text TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


def append_message(author, device, text):
    """写入一条留言，返回自增 id"""
    conn = board_conn()
    try:
        with _board_lock:
            cur = conn.execute(
                "INSERT INTO messages (author, device, ts, text) VALUES (?, ?, ?, ?)",
                (author, device, time.time(), text),
            )
            conn.commit()
            return cur.lastrowid
    finally:
        conn.close()


def fetch_board(after_id=None):
    """最近 BOARD_VISIBLE 条（按时间正序）；after_id 等于当前最新 id 时只回「没变化」"""
    conn = board_conn()
    try:
        stat = conn.execute("SELECT COUNT(*) AS n, MAX(id) AS latest FROM messages").fetchone()
        total, latest = stat["n"], stat["latest"] or 0
        if after_id is not None and after_id == latest:
            return {"messages": [], "latest_id": latest, "total": total, "unchanged": True}
        rows = conn.execute(
            "SELECT id, author, device, ts, text FROM messages ORDER BY id DESC LIMIT ?",
            (BOARD_VISIBLE,),
        ).fetchall()
    finally:
        conn.close()
    return {"messages": [dict(r) for r in reversed(rows)], "latest_id": latest, "total": total}


def delete_message(message_id, username):
    """删除一条留言，作者必须与请求里的 username 一致。返回 'ok' / 'missing' / 'forbidden'"""
    conn = board_conn()
    try:
        with _board_lock:
            row = conn.execute("SELECT author FROM messages WHERE id = ?", (message_id,)).fetchone()
            if row is None:
                return "missing"
            if row["author"] != username:
                return "forbidden"
            conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            conn.commit()
            return "ok"
    finally:
        conn.close()


def get_user_files_dir(username):
    """获取用户文件目录路径"""
    if not username or username.strip() == "":
        username = "default"
    user_dir = os.path.join(FILES_DIR, username)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir


def get_chunk_dir(username, file_id):
    """获取分片临时目录"""
    chunk_dir = os.path.join(FILES_DIR, username, ".chunks", file_id)
    if not os.path.exists(chunk_dir):
        os.makedirs(chunk_dir)
    return chunk_dir


def cleanup_chunks(username, file_id):
    """清理分片临时目录。取消上传时可能还有分片线程握着句柄在写（Windows 删不掉，改名也被挡），
    重试等写线程松手；仍删不掉只记日志，留给下次启动的 sweep 兜底"""
    chunk_dir = os.path.join(FILES_DIR, username, ".chunks", file_id)
    for _ in range(5):
        shutil.rmtree(chunk_dir, ignore_errors=True)
        if not os.path.isdir(chunk_dir):
            return
        time.sleep(0.2)
    log.warning("分片目录清理失败（仍被占用），留待启动清扫: %s", chunk_dir)


def read_chunk_filename(chunk_dir):
    """读分片目录里的 meta.json 拿原文件名，仅用于日志；没有/坏了返回 ?"""
    try:
        with open(os.path.join(chunk_dir, "meta.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("filename", "?")
    except (OSError, ValueError):
        return "?"


def exclusive_path(user_dir, filename):
    """重名时追加时间戳与序号，返回一个当前不存在的路径。配合 open('x') 独占创建：
    并发同名也不会互相覆盖——同秒同名只加一层时间戳仍可能撞，循环序号兜底"""
    candidate = os.path.join(user_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    name, ext = os.path.splitext(filename)
    base = os.path.join(user_dir, f"{name}_{int(time.time())}")
    counter = 0
    while True:
        candidate = f"{base}{'' if counter == 0 else f'_{counter}'}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def merge_chunks(username, file_id, original_filename, total_chunks):
    """按序号合并分片到最终文件，返回 (文件名, 校验码)。分片不齐全抛 ValueError"""
    chunk_dir = get_chunk_dir(username, file_id)
    user_dir = get_user_files_dir(username)

    # 按序号排序并校验齐全（0..total-1 无缺失）：缺片合并会产出被截断的"完整文件"
    # 只认 chunk_*：目录里还有首片时落的 meta.json，混进来会让 basename.split("_")[1] 炸 IndexError
    chunk_files = sorted(
        glob.glob(os.path.join(chunk_dir, "chunk_*")),
        key=lambda x: int(os.path.basename(x).split("_")[1])
    )
    indices = [int(os.path.basename(x).split("_")[1]) for x in chunk_files]
    if indices != list(range(total_chunks)):
        raise ValueError(f"分片不齐全: 期望 {total_chunks} 片，实收 {len(indices)} 片")

    # 合并时顺带算出整文件哈希，不用再读一遍磁盘。
    # 同名并发抢先时 open('xb') 抛 FileExistsError：分片完好，重挑候选名再试，
    # 不把这次上传丢掉；走到通用 except 的一定是 open 成功后的写入失败，
    # os.remove 删的只会是自己创建的半成品
    hasher = hashlib.new(HASH_ALGO)
    while True:
        file_path = exclusive_path(user_dir, original_filename)
        try:
            with open(file_path, 'xb') as dst:
                writer = HashingWriter(dst, hasher)
                for chunk_file in chunk_files:
                    with open(chunk_file, 'rb') as src:
                        shutil.copyfileobj(src, writer, STREAM_CHUNK)
            break
        except FileExistsError:
            continue
        except Exception:
            # 合并失败：清掉半成品与分片，避免留下损坏文件或孤儿分片
            try:
                os.remove(file_path)
            except OSError:
                pass
            cleanup_chunks(username, file_id)
            raise

    final_name = os.path.basename(file_path)
    # 清理分片
    cleanup_chunks(username, file_id)
    return final_name, hasher.hexdigest()


class HashingWriter:
    """边写边算哈希的 writer，直接喂给 shutil.copyfileobj"""

    def __init__(self, fp, hasher):
        self.fp = fp
        self.hasher = hasher

    def write(self, data):
        self.hasher.update(data)
        return self.fp.write(data)


def hashes_path(user_dir):
    return os.path.join(user_dir, HASHES_FILE)


def read_hashes(user_dir):
    """读取哈希记录，格式 {filename: {"sha256": ..., "size": ..., "mtime": ...}}"""
    path = hashes_path(user_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        return records if isinstance(records, dict) else {}
    except (OSError, ValueError):
        log.warning("哈希记录读取失败，按空处理: %s", path)
        return {}


def write_hashes(user_dir, records):
    """原子写入哈希记录（临时文件 + 替换），避免并发写坏"""
    path = hashes_path(user_dir)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        log.exception("哈希记录写入失败: %s", path)


def file_signature(file_path):
    """文件指纹 (大小, 修改时间)，取不到返回 None"""
    try:
        st = os.stat(file_path)
    except OSError:
        return None
    return st.st_size, st.st_mtime


def record_hash(user_dir, filename, digest):
    """记录文件的哈希，连同大小与修改时间一起存，供判断记录是否还有效"""
    signature = file_signature(os.path.join(user_dir, filename))
    if signature is None:
        return
    with _hash_lock:
        records = read_hashes(user_dir)
        records[filename] = {HASH_ALGO: digest, "size": signature[0], "mtime": signature[1]}
        write_hashes(user_dir, records)


def drop_hash(user_dir, filename):
    """删除文件时同步清理哈希记录"""
    with _hash_lock:
        records = read_hashes(user_dir)
        if records.pop(filename, None) is None:
            return
        write_hashes(user_dir, records)


def hash_file(file_path):
    """分块计算文件哈希，内存占用恒定"""
    hasher = hashlib.new(HASH_ALGO)
    with open(file_path, "rb") as f:
        while True:
            buf = f.read(STREAM_CHUNK)
            if not buf:
                break
            hasher.update(buf)
    return hasher.hexdigest()


def known_hash(record, signature):
    """记录与当前文件指纹一致才算有效，文件被改过则作废"""
    if signature is None or not isinstance(record, dict):
        return None
    if record.get("size") != signature[0] or record.get("mtime") != signature[1]:
        return None
    return record.get(HASH_ALGO)


def get_known_hash(user_dir, filename):
    """按文件名取有效的哈希记录，没有则返回 None"""
    record = read_hashes(user_dir).get(filename)
    return known_hash(record, file_signature(os.path.join(user_dir, filename)))


def reconcile_hashes():
    """启动对账：清掉已删除文件的记录，给没有有效记录的文件补算校验码"""
    if not os.path.isdir(FILES_DIR):
        return
    started = time.monotonic()
    hashed = pruned = failed = 0
    for username in sorted(os.listdir(FILES_DIR)):
        user_dir = os.path.join(FILES_DIR, username)
        if username.startswith(".") or not os.path.isdir(user_dir):
            continue
        try:
            records = read_hashes(user_dir)
            names = [n for n in os.listdir(user_dir) if not n.startswith(".")]

            # 删除的文件 → 清记录；无有效记录的文件 → 补算（hash_file 可能耗时几十秒，留在锁外）
            gone = [name for name in records if name not in names]
            backfill = {}
            for name in names:
                full = os.path.join(user_dir, name)
                if not os.path.isfile(full):
                    continue
                signature = file_signature(full)
                if signature is None or known_hash(records.get(name), signature) is not None:
                    continue
                log.info("补算校验码: user=%s file=%s size=%s", username, name, human_size(signature[0]))
                backfill[name] = {HASH_ALGO: hash_file(full), "size": signature[0], "mtime": signature[1]}

            if gone or backfill:
                # 进锁后重读再合并写出：直接写手里这份旧快照会覆盖并发上传写入的新记录
                with _hash_lock:
                    fresh = read_hashes(user_dir)
                    for name in gone:
                        fresh.pop(name, None)
                    fresh.update(backfill)
                    write_hashes(user_dir, fresh)
                pruned += len(gone)
                hashed += len(backfill)
        except Exception:
            failed += 1
            log.exception("校验码对账失败: %s", user_dir)

    log.info(
        "校验码对账完成: 补算 %d 个, 清理 %d 条, 失败 %d 个目录, 耗时 %.2fs",
        hashed, pruned, failed, time.monotonic() - started
    )


def sweep_stale_chunks(max_age_hours=24):
    """清理残留的分片目录（上传中断/取消的孤儿）。以目录内最新文件的 mtime 判断，
    防止误删仍在进行中的上传——活跃上传会持续写入新分片"""
    if not os.path.isdir(FILES_DIR):
        return
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for username in os.listdir(FILES_DIR):
        chunks_root = os.path.join(FILES_DIR, username, ".chunks")
        if not os.path.isdir(chunks_root):
            continue
        for file_id in os.listdir(chunks_root):
            chunk_dir = os.path.join(chunks_root, file_id)
            if not os.path.isdir(chunk_dir):
                continue
            try:
                entries = os.listdir(chunk_dir)
                newest = max(
                    (os.path.getmtime(os.path.join(chunk_dir, n)) for n in entries),
                    default=os.path.getmtime(chunk_dir)
                )
            except OSError:
                continue
            if newest < cutoff:
                chunk_names = [n for n in entries if n.startswith("chunk_")]
                try:
                    total_bytes = sum(os.path.getsize(os.path.join(chunk_dir, n)) for n in chunk_names)
                except OSError:
                    total_bytes = -1
                log.info(
                    "清理未完成上传: user=%s file_id=%s file=%s 分片数=%d 已收=%s 最后写入=%s",
                    username, file_id, read_chunk_filename(chunk_dir), len(chunk_names),
                    human_size(total_bytes) if total_bytes >= 0 else "?",
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))
                )
                shutil.rmtree(chunk_dir, ignore_errors=True)
                removed += 1
    if removed:
        log.info("清理过期分片目录: %d 个 (阈值 %d 小时)", removed, max_age_hours)


def start_hash_reconcile():
    """后台线程做启动维护：清扫过期分片 + 校验码对账，不拖慢启动
    （对账按大小+修改时间跳过没变的文件，重启基本不耗时）"""
    def _maintenance():
        try:
            sweep_stale_chunks()
        except Exception:
            log.exception("分片目录清扫失败")
        reconcile_hashes()
    threading.Thread(target=_maintenance, name="startup-maintenance", daemon=True).start()


# === 后台哈希计算 ===
# 服务运行中手动放入/原地替换的文件没有哈希记录。/api/files 每次请求都 listdir，
# 扫到"无有效记录"就顺手入队；worker 串行补算，请求线程永不做整文件读盘
# （hashlib 是 C 扩展、计算时释放 GIL，后台线程与请求线程真并行）。
# /api/file/hash 无记录时返回 computing，前端轮询到算好为止。

_hash_queue = queue.Queue()
_hash_queued = set()                 # (user_dir, filename) 防重复入队
_hash_queued_lock = threading.Lock()


def enqueue_hash(user_dir, filename):
    key = (user_dir, filename)
    with _hash_queued_lock:
        if key in _hash_queued:
            return
        _hash_queued.add(key)
    _hash_queue.put(key)


def hash_worker_loop():
    while True:
        user_dir, filename = _hash_queue.get()
        try:
            full = os.path.join(user_dir, filename)
            signature = file_signature(full)
            if signature is None or get_known_hash(user_dir, filename) is not None:
                continue             # 文件已消失，或启动对账/别的路径已算好
            started = time.monotonic()
            log.info("后台计算校验码: file=%s size=%s", filename, human_size(signature[0]))
            digest = hash_file(full)
            record_hash(user_dir, filename, digest)
            log.info("后台校验码完成: file=%s %s=%s 耗时=%.2fs",
                     filename, HASH_ALGO, digest, time.monotonic() - started)
        except Exception:
            log.exception("后台计算校验码失败: %s", user_dir)
        finally:
            with _hash_queued_lock:
                _hash_queued.discard((user_dir, filename))


threading.Thread(target=hash_worker_loop, name="hash-worker", daemon=True).start()


def human_size(num_bytes):
    """字节数转可读字符串"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.2f}{unit}" if unit != "B" else f"{num_bytes}B"
        num_bytes /= 1024


@app.before_request
def _request_start():
    g.request_start = time.monotonic()


@app.after_request
def _request_end(resp):
    """访问日志：客户端 IP、方法、路径、状态码、响应体大小、耗时、Range"""
    start = getattr(g, "request_start", None)
    elapsed = time.monotonic() - start if start else 0.0
    content_length = resp.headers.get("Content-Length")
    size_text = human_size(int(content_length)) if content_length else "-"
    byte_range = request.headers.get("Range")
    # 页面与静态资源禁缓存（靠 ETag 重校验取 304），防止刷新后拿到旧页面旧 CSS/JS；
    # /api/download* 的 ETag/Last-Modified 是断点续传在用的，不能碰
    if request.path == "/" or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    elif request.path.startswith("/api/") and request.path not in ("/api/download", "/api/download/chunk"):
        resp.headers["Cache-Control"] = "no-store"
    # 分片级请求量大（30GB ≈ 960 条），降为 DEBUG；关键事件（完成/合并/中断）仍为 INFO
    log_fn = log.debug if request.path in ("/api/upload/chunk", "/api/download/chunk") else log.info
    log_fn(
        "%s %s %s -> %s %s %.2fs%s",
        request.remote_addr,
        request.method,
        request.full_path.rstrip("?"),
        resp.status_code,
        size_text,
        elapsed,
        f" Range={byte_range}" if byte_range else "",
    )
    return resp


@app.errorhandler(Exception)
def _uncaught_error(e):
    """兜底异常处理：记录完整堆栈，HTTP 异常（404/416 等）按原状态码返回"""
    if isinstance(e, HTTPException):
        log.warning("HTTP %s: %s %s", e.code, request.method, request.full_path.rstrip("?"))
        return e
    log.exception("未捕获异常: %s %s", request.method, request.full_path.rstrip("?"))
    return jsonify({"success": False, "error": "服务器内部错误，详情见服务端日志"}), 500


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/board', methods=['GET'])
def get_board():
    """共享留言板：任何人登录看到的都是同一块板，只回最近 BOARD_VISIBLE 条"""
    username = normalize_username(request.args.get('username', 'default'))
    if username is None:
        return bad_request("用户名不合法")
    after = request.args.get('after', '')
    after_id = int(after) if after.isdigit() else None
    return jsonify(fetch_board(after_id))


@app.route('/api/board', methods=['POST'])
def post_board():
    """发一条留言（全员可见）"""
    data = request.json or {}
    username = normalize_username(data.get('username', 'default'))
    if username is None:
        return bad_request("用户名不合法")
    text = str(data.get('text') or '').strip()
    if not text:
        return bad_request("留言不能为空")
    if len(text) > BOARD_TEXT_MAX:
        return bad_request(f"留言过长，上限 {BOARD_TEXT_MAX} 字")
    device = normalize_device(data.get('device'))
    message_id = append_message(username, device, text)
    log.info("新留言: user=%s device=%s id=%d 字数=%d", username, device, message_id, len(text))
    return jsonify({"success": True, "id": message_id})


@app.route('/api/board/delete', methods=['POST'])
def delete_board():
    """删除一条留言，只能删自己发的（作者须与请求里的 username 一致）"""
    data = request.json or {}
    username = normalize_username(data.get('username', 'default'))
    message_id = data.get('id')
    if username is None or not isinstance(message_id, int) or message_id < 1:
        return bad_request("参数不合法")
    result = delete_message(message_id, username)
    if result == "missing":
        log.warning("删除留言失败(不存在): user=%s id=%d", username, message_id)
        return jsonify({"success": False, "error": "留言不存在或已被删除"}), 404
    if result == "forbidden":
        log.warning("删除留言被拒(非本人): user=%s id=%d", username, message_id)
        return jsonify({"success": False, "error": "只能删除自己发送的留言"}), 403
    log.info("留言已删除: user=%s id=%d", username, message_id)
    return jsonify({"success": True})


@app.route('/api/file/info', methods=['GET'])
def file_info():
    """获取文件大小与校验码（用于分片下载规划）"""
    username = normalize_username(request.args.get('username', 'default'))
    filename = safe_filename(request.args.get('filename', ''))
    if username is None or filename is None:
        return bad_request("参数不合法")
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)

    if not os.path.exists(file_path):
        log.warning("文件信息查询失败(不存在): user=%s file=%s", username, filename)
        return jsonify({"success": False, "error": "文件不存在"}), 404

    file_size = os.path.getsize(file_path)
    digest = get_known_hash(user_dir, filename)
    log.info("文件信息: user=%s file=%s size=%s %s=%s", username, filename, human_size(file_size), HASH_ALGO, digest or "未记录")
    return jsonify({"success": True, "size": file_size, "name": filename, HASH_ALGO: digest})


@app.route('/api/file/hash', methods=['GET'])
def file_hash():
    """获取文件校验码；无记录时入队交后台计算并返回 computing，请求线程不整读文件"""
    username = normalize_username(request.args.get('username', 'default'))
    filename = safe_filename(request.args.get('filename', ''))
    if username is None or filename is None:
        return bad_request("参数不合法")
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)

    if not os.path.isfile(file_path):
        log.warning("校验码查询失败(文件不存在): user=%s file=%s", username, filename)
        return jsonify({"success": False, "error": "文件不存在"}), 404

    file_size = os.path.getsize(file_path)
    digest = get_known_hash(user_dir, filename)
    if digest is None:
        enqueue_hash(user_dir, filename)
        log.info("校验码未就绪，转后台计算: user=%s file=%s size=%s", username, filename, human_size(file_size))
        return jsonify({"success": True, "name": filename, "size": file_size, HASH_ALGO: None, "computing": True})
    return jsonify({"success": True, "name": filename, "size": file_size, HASH_ALGO: digest, "cached": True})


@app.route('/api/upload/chunk', methods=['POST'])
def upload_chunk():
    """接收单个分片。裸 body 直写磁盘：不解析 multipart、不落临时文件，
    每字节省一次临时文件写+读（实测 multipart 路径分片阶段仅 ~102MB/s）"""
    try:
        # username 走 query（可能含中文，请求头只允许 latin-1）；file_id/index 为 ASCII 走头
        username = normalize_username(request.args.get('username', 'default'))
        file_id = request.headers.get('X-File-Id', '')
        chunk_index = request.headers.get('X-Chunk-Index', '0')
        # 原文件名也只进 query，且仅用于日志与 meta.json，绝不参与拼路径
        display_name = safe_filename(request.args.get('filename', '')) or "?"

        if username is None or not _FILE_ID_RE.match(file_id or ''):
            return bad_request("参数不合法")
        try:
            idx = int(chunk_index)
            if idx < 0:
                raise ValueError
        except (TypeError, ValueError):
            return bad_request("chunk_index 不合法")

        chunk_dir = get_chunk_dir(username, file_id)
        chunk_path = os.path.join(chunk_dir, f"chunk_{idx:06d}")

        # 直接从请求流写盘
        with open(chunk_path, 'wb') as dst:
            while True:
                buf = request.stream.read(STREAM_CHUNK)
                if not buf:
                    break
                dst.write(buf)

        # 首片落盘即记「上传开始」+ meta.json：只有开始没有合并完成的 file_id 就是中断签名
        if idx == 0:
            meta_path = os.path.join(chunk_dir, "meta.json")
            if not os.path.exists(meta_path):
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump({"filename": display_name, "started": time.time()}, f, ensure_ascii=False)
                log.info("上传开始: user=%s file=%s file_id=%s", username, display_name, file_id)

        return jsonify({"success": True, "chunk_index": idx})
    except Exception:
        log.exception("分片上传失败: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": "分片写入失败，详情见服务端日志"})


@app.route('/api/upload/merge', methods=['POST'])
def upload_merge():
    """合并分片为最终文件"""
    try:
        started = time.monotonic()
        data = request.json
        username = normalize_username(data.get('username', 'default'))
        file_id = data.get('file_id', '')
        original_filename = safe_filename(data.get('filename', 'untitled'))

        if username is None or not original_filename or not _FILE_ID_RE.match(file_id or ''):
            return bad_request("参数不合法")
        total_chunks = data.get('total_chunks')
        # 上限 4096：30GB/32MB 分片只有 960 片；无上限时 list(range(total_chunks)) 会被恶意大值撑爆内存
        if not isinstance(total_chunks, int) or not (1 <= total_chunks <= 4096):
            return bad_request("total_chunks 缺失或超出范围")

        log.info("开始合并分片: user=%s file=%s file_id=%s", username, original_filename, file_id)
        user_dir = get_user_files_dir(username)
        try:
            final_name, digest = merge_chunks(username, file_id, original_filename, total_chunks)
        except ValueError as e:
            cleanup_chunks(username, file_id)
            log.warning("合并被拒(分片不齐): user=%s file=%s file_id=%s: %s", username, original_filename, file_id, e)
            return bad_request(str(e))
        final_size = os.path.getsize(os.path.join(user_dir, final_name))
        record_hash(user_dir, final_name, digest)
        log.info(
            "合并完成: user=%s file=%s size=%s %s=%s 耗时=%.2fs",
            username, final_name, human_size(final_size), HASH_ALGO, digest, time.monotonic() - started
        )
        return jsonify({"success": True, "filename": final_name, HASH_ALGO: digest})
    except Exception:
        log.exception("合并分片失败: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": "合并失败，详情见服务端日志"})


@app.route('/api/upload/status', methods=['GET'])
def upload_status():
    """断点续传：返回该 file_id 已收到的分片（前端核对大小后跳过合格片，只补缺的）"""
    username = normalize_username(request.args.get('username', 'default'))
    file_id = request.args.get('file_id', '')
    if username is None or not _FILE_ID_RE.match(file_id or ''):
        return bad_request("参数不合法")
    chunk_dir = os.path.join(FILES_DIR, username, ".chunks", file_id)
    received = []
    for path in glob.glob(os.path.join(chunk_dir, "chunk_*")):
        try:
            idx = int(os.path.basename(path).split("_")[1])
            received.append({"index": idx, "size": os.path.getsize(path)})
        except (OSError, ValueError, IndexError):
            continue
    received.sort(key=lambda x: x["index"])
    return jsonify({"success": True, "received": received})


@app.route('/api/upload/abort', methods=['POST'])
def upload_abort():
    """取消上传：丢弃该 file_id 的全部分片（前端取消按钮调用）"""
    try:
        data = request.json
        username = normalize_username(data.get('username', 'default'))
        file_id = data.get('file_id', '')
        if username is None or not _FILE_ID_RE.match(file_id or ''):
            return bad_request("参数不合法")
        chunk_dir = os.path.join(FILES_DIR, username, ".chunks", file_id)
        file_name = read_chunk_filename(chunk_dir)
        cleanup_chunks(username, file_id)
        log.info("上传已取消，清理分片: user=%s file=%s file_id=%s", username, file_name, file_id)
        return jsonify({"success": True})
    except Exception:
        log.exception("取消上传清理分片失败: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": "清理分片失败"}), 500


@app.route('/api/download/chunk', methods=['GET'])
def download_chunk():
    """支持 Range 的分片下载"""
    username = normalize_username(request.args.get('username', 'default'))
    filename = safe_filename(request.args.get('filename', ''))
    if username is None or filename is None:
        return bad_request("参数不合法")
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)

    if not os.path.exists(file_path):
        log.warning("下载失败(文件不存在): user=%s file=%s from=%s", username, filename, request.remote_addr)
        return jsonify({"error": "文件不存在"}), 404

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get('Range', None)

    if not range_header:
        # 无 Range 头则返回整个文件（兜底）
        log.info("整文件下载: user=%s file=%s size=%s from=%s", username, filename, human_size(file_size), request.remote_addr)
        resp = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        resp.headers['Accept-Ranges'] = 'bytes'
        return resp

    # 解析 Range: bytes=start-end；支持 bytes=-N 后缀语义（取末 N 字节），非法一律 416
    spec = range_header.strip()
    if not spec.startswith("bytes="):
        return Response(status=416)
    try:
        first, _, last = spec[6:].partition("-")
        first, last = first.strip(), last.strip()
        if first == "" and last == "":
            raise ValueError
        if first == "":
            suffix = int(last)
            if suffix <= 0:
                raise ValueError
            start = max(0, file_size - suffix)
            end = file_size - 1
        else:
            start = int(first)
            end = int(last) if last else file_size - 1
    except ValueError:
        return Response(status=416)

    if start < 0 or start >= file_size or start > end:
        log.warning(
            "下载越界(416): user=%s file=%s size=%s Range=%s from=%s",
            username, filename, human_size(file_size), range_header, request.remote_addr
        )
        return Response(status=416)

    end = min(end, file_size - 1)
    length = end - start + 1

    # 生成器在请求上下文之外执行，先把日志需要的字段取出来
    client_ip = request.remote_addr

    # 流式发送指定范围，使用大缓冲区
    def generate():
        sent = 0
        started_at = time.monotonic()
        try:
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(STREAM_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    sent += len(chunk)
                    yield chunk
        finally:
            elapsed = time.monotonic() - started_at
            if sent < length:
                # 客户端提前断开（关页面/内存不足导致中止）会在这里暴露出来
                log.warning(
                    "下载中断: user=%s file=%s start=%d 已发送=%s/期望=%s from=%s",
                    username, filename, start, human_size(sent), human_size(length), client_ip
                )
            else:
                # after_request 记不到响应体耗时（0.0x s），真吞吐在这里记
                log.info(
                    "下载完成: user=%s file=%s start=%d 已发送=%s 耗时=%.2fs 均速=%.1fMB/s from=%s",
                    username, filename, start, human_size(sent), elapsed,
                    sent / 1048576 / elapsed if elapsed > 0 else 0, client_ip
                )

    resp = Response(generate(), status=206, mimetype='application/octet-stream')
    resp.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    resp.headers['Content-Length'] = str(length)
    resp.headers['Accept-Ranges'] = 'bytes'
    # RFC 5987：中文等非 ASCII 文件名需百分号编码进 filename*，否则 HTTP 头用 latin-1 编码会崩
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "download"
    resp.headers['Content-Disposition'] = (
        f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    )
    return resp


@app.route('/api/disk', methods=['GET'])
def disk_info():
    """查询存储盘剩余空间（前端上传前预检用，无路径参数）"""
    try:
        usage = shutil.disk_usage(FILES_DIR)
    except OSError:
        log.exception("查询磁盘空间失败")
        return jsonify({"success": False, "error": "查询磁盘空间失败"}), 500
    return jsonify({"success": True, "free": usage.free, "total": usage.total})


@app.route('/api/server-addr', methods=['GET'])
def server_addr():
    """返回服务器局域网 IP，供前端拼"发给别人"的下载命令（页面用 localhost 打开时替换主机名）"""
    ip = get_primary_lan_ip()
    if not ip:
        lan_ips = get_lan_ips()
        ip = lan_ips[0] if lan_ips else None
    return jsonify({"ip": ip})


@app.route('/api/files', methods=['GET'])
def list_files():
    """获取用户的文件列表（含文件大小与校验码，排除隐藏文件）"""
    username = normalize_username(request.args.get('username', 'default'))
    if username is None:
        return bad_request("用户名不合法")
    user_dir = get_user_files_dir(username)
    records = read_hashes(user_dir)
    result = []
    for name in os.listdir(user_dir):
        full = os.path.join(user_dir, name)
        # 跳过分片临时目录、哈希记录等隐藏文件
        if name.startswith('.'):
            continue
        if os.path.isfile(full):
            signature = file_signature(full)
            digest = known_hash(records.get(name), signature)
            if digest is None:
                enqueue_hash(user_dir, name)   # 搭 listdir 的便车，交给后台 worker 补算
            result.append({
                "name": name,
                "size": signature[0] if signature else 0,
                "mtime": signature[1] if signature else 0,
                HASH_ALGO: digest,
            })
    result.sort(key=lambda x: x["name"])
    return jsonify({"files": result})


@app.route('/api/download', methods=['GET'])
def download_file():
    """下载文件"""
    username = normalize_username(request.args.get('username', 'default'))
    filename = safe_filename(request.args.get('filename', ''))
    if username is None or filename is None:
        return bad_request("参数不合法")
    user_dir = get_user_files_dir(username)
    return send_from_directory(user_dir, filename, as_attachment=True)


@app.route('/api/delete', methods=['POST'])
def delete_file():
    """删除文件"""
    try:
        data = request.json
        username = normalize_username(data.get('username', 'default'))
        filename = safe_filename(data.get('filename', ''))
        if username is None or filename is None:
            return bad_request("参数不合法")

        user_dir = get_user_files_dir(username)
        file_path = os.path.join(user_dir, filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            drop_hash(user_dir, filename)
            log.info("删除文件: user=%s file=%s", username, filename)
            return jsonify({"success": True})
        else:
            log.warning("删除失败(文件不存在): user=%s file=%s", username, filename)
            return jsonify({"success": False, "error": "文件不存在"})
    except Exception:
        log.exception("删除文件异常: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": "删除失败，详情见服务端日志"})



try:
    init_board()
except Exception:
    log.exception("留言板初始化失败（建表），留言接口将不可用")


def check_port_in_use(port, timeout=1.0):
    """探测端口是否已有服务在听。waitress 在 Windows 上允许双绑同一端口
    （SO_REUSEADDR 语义），旧实例还在跑时新代码不会生效，启动前先拦下"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def get_lan_ips():
    """枚举本机所有 IPv4（排除回环）。虚拟网卡多时 gethostbyname 只给一个，可能打错"""
    import socket
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def get_primary_lan_ip():
    """UDP connect 探测默认路由出口 IP（不实际发包），通常就是真正的局域网 IP"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def open_browser_when_ready(url):
    """延迟 1 秒在服务器本机打开浏览器（等监听就绪），失败静默"""
    def _open():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    t = threading.Timer(1.0, _open)
    t.daemon = True
    t.start()


def run_dev_server(ip):
    """开发服务器 (Werkzeug) — 仅限本地测试"""
    log.warning("使用开发服务器 (Werkzeug)，仅适合本地测试")
    print("  [警告] 当前使用开发服务器 (Werkzeug)，仅适合本地测试！")
    print("  生产环境请使用:")
    print("    Linux:   gunicorn -c gunicorn.conf.py http_messages_share:app")
    print("=" * 60)
    open_browser_when_ready("http://localhost:5000")
    app.run(debug=False, host='0.0.0.0', port=5000)


def run_prod_server(ip):
    """生产服务器 — 自动选择平台适配的 WSGI 服务器"""
    import platform
    import socket as sock_mod

    system = platform.system()

    if system == "Windows":
        try:
            from waitress.server import create_server

            print(f"  [Waitress] Windows 生产服务器")
            print(f"  最大请求体: 30GB")
            print(f"  线程数: 8")
            print(f"  Socket 收发缓冲: {SOCKET_SEND_BUF // (1024*1024)}MB")
            print(f"  分片大小(上传): {CHUNK_SIZE // (1024*1024)}MB")
            print("=" * 60)

            server = create_server(
                app,
                host='0.0.0.0',
                port=5000,
                threads=8,
                max_request_body_size=30 * 1024 * 1024 * 1024,
                channel_timeout=7200,
                cleanup_interval=60,
                # 调大 socket 收发缓冲以跑满带宽
                recv_bytes=SOCKET_RECV_BUF,
                send_bytes=SOCKET_SEND_BUF,
            )

            # 设置 socket 选项：增大缓冲 + 禁用 Nagle
            # create_server 单 socket 时返回 TcpWSGIServer（有 .socket），
            # 多 socket 时返回 MultiSocketServer（无 .socket，底层 socket 在 .map 中），需兼容两者
            primary_sock = getattr(server, "socket", None)
            if primary_sock is not None:
                listen_sockets = [primary_sock]
            else:
                server_map = getattr(server, "map", None) or {}
                listen_sockets = [getattr(s, "socket", None) for s in server_map.values()]
            for sock in listen_sockets:
                if sock is None:
                    continue
                sock.setsockopt(sock_mod.SOL_SOCKET, sock_mod.SO_SNDBUF, SOCKET_SEND_BUF)
                sock.setsockopt(sock_mod.SOL_SOCKET, sock_mod.SO_RCVBUF, SOCKET_RECV_BUF)
                sock.setsockopt(sock_mod.IPPROTO_TCP, sock_mod.TCP_NODELAY, 1)
                try:
                    sock.setsockopt(sock_mod.IPPROTO_TCP, 12, 1)  # TCP_QUICKACK (Linux)
                except OSError:
                    pass

            print("  [Waitress] 正在监听 http://0.0.0.0:5000 ...")
            log.info("Waitress 启动: 0.0.0.0:5000 threads=8 存储目录=%s", os.path.abspath(FILES_DIR))
            open_browser_when_ready("http://localhost:5000")
            server.run()
        except ImportError:
            print("  [错误] 未安装 waitress，请执行: pip install waitress")
            print("  回退到开发服务器...")
            run_dev_server(ip)
    else:
        run_dev_server(ip)


if __name__ == '__main__':
    primary_ip = get_primary_lan_ip()
    lan_ips = get_lan_ips()

    print("=" * 60)
    print("  QuickFilesSharing 服务")
    print("  本地访问:   http://localhost:5000")
    if primary_ip:
        print(f"  局域网访问: http://{primary_ip}:5000  ← 推荐（默认路由出口）")
    for ip in lan_ips:
        if ip != primary_ip:
            print(f"              http://{ip}:5000")
    if not lan_ips:
        print("  局域网访问: （未检测到局域网 IP，仅本机可访问）")
    print("  支持最大上传: 30GB")
    print("=" * 60)

    if check_port_in_use(5000):
        print("  [错误] 端口 5000 已有服务在运行，本次启动退出。")
        print("  很可能是旧实例没关（它仍在跑旧代码，改动不会生效）：")
        print("    netstat -ano | findstr :5000   ← 找到 PID")
        print("    taskkill /PID <PID> /F         ← 结束后再启动")
        log.error("端口 5000 已被占用，拒绝启动")
        sys.exit(1)

    log.info("服务启动: 局域网IP=%s 最大上传=30GB", lan_ips or ["未知"])
    start_hash_reconcile()
    run_prod_server(primary_ip)
