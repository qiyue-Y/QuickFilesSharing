"""
简易剪切板HTTP服务
功能：用户可以登录后查看、保存剪切板内容，以及上传/下载/删除文件
存储：剪切板存为TXT文件，文件存储在用户目录下
运行：python http_messages_share.py
访问：http://localhost:5000
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
import re
import sys
import os
import time
import shutil
import glob
import threading
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

# 存储目录：锚定到 py 文件所在目录。send_from_directory 以 app.root_path（即本文件位置）为基准，
# 其余接口若跟随进程 CWD，从其他目录启动服务时两边会分裂（列表有文件、下载 404），故统一锚定
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIPBOARD_DIR = os.path.join(_BASE_DIR, "clipboards")
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


def safe_filename(filename):
    """文件名校验：拒绝路径分隔符、..、隐藏文件（含 .hashes.json）；非法返回 None"""
    if not filename:
        return None
    filename = str(filename).strip()
    if not filename or filename in (".", ".."):
        return None
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    return filename


def bad_request(error):
    return jsonify({"success": False, "error": error}), 400


def get_clipboard_path(username):
    """获取用户剪切板文件路径"""
    if not username or username.strip() == "":
        username = "default"
    return os.path.join(CLIPBOARD_DIR, f"{username}.txt")


def get_user_files_dir(username):
    """获取用户文件目录路径"""
    if not username or username.strip() == "":
        username = "default"
    user_dir = os.path.join(FILES_DIR, username)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir


def check_disk_space(username, required_bytes):
    """检查磁盘空间是否足够"""
    user_dir = get_user_files_dir(username)
    stat = shutil.disk_usage(user_dir)
    return stat.free >= required_bytes


def get_chunk_dir(username, file_id):
    """获取分片临时目录"""
    chunk_dir = os.path.join(FILES_DIR, username, ".chunks", file_id)
    if not os.path.exists(chunk_dir):
        os.makedirs(chunk_dir)
    return chunk_dir


def cleanup_chunks(username, file_id):
    """清理分片临时目录"""
    chunk_dir = os.path.join(FILES_DIR, username, ".chunks", file_id)
    if os.path.exists(chunk_dir):
        shutil.rmtree(chunk_dir)


def merge_chunks(username, file_id, original_filename):
    """按序号合并分片到最终文件，返回 (文件名, 校验码)"""
    chunk_dir = get_chunk_dir(username, file_id)
    user_dir = get_user_files_dir(username)

    # 处理重名
    final_name = original_filename
    if os.path.exists(os.path.join(user_dir, final_name)):
        name, ext = os.path.splitext(original_filename)
        final_name = f"{name}_{int(time.time())}{ext}"

    file_path = os.path.join(user_dir, final_name)

    # 按序号排序分片并合并
    chunk_files = sorted(
        glob.glob(os.path.join(chunk_dir, "*")),
        key=lambda x: int(os.path.basename(x).split("_")[1])
    )

    # 合并时顺带算出整文件哈希，不用再读一遍磁盘
    hasher = hashlib.new(HASH_ALGO)
    try:
        with open(file_path, 'wb') as dst:
            writer = HashingWriter(dst, hasher)
            for chunk_file in chunk_files:
                with open(chunk_file, 'rb') as src:
                    shutil.copyfileobj(src, writer, STREAM_CHUNK)
    except Exception:
        # 合并失败：清掉半成品与分片，避免留下损坏文件或孤儿分片
        try:
            os.remove(file_path)
        except OSError:
            pass
        cleanup_chunks(username, file_id)
        raise

    # 清理分片
    cleanup_chunks(username, file_id)
    return final_name, hasher.hexdigest()


def read_clipboard(username):
    """读取用户剪切板内容"""
    path = get_clipboard_path(username)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""


def write_clipboard(username, content):
    """保存用户剪切板内容"""
    path = get_clipboard_path(username)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


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
            dirty = False

            for name in list(records):
                if name not in names:
                    records.pop(name)
                    pruned += 1
                    dirty = True

            for name in names:
                full = os.path.join(user_dir, name)
                if not os.path.isfile(full):
                    continue
                signature = file_signature(full)
                if signature is None or known_hash(records.get(name), signature) is not None:
                    continue
                log.info("补算校验码: user=%s file=%s size=%s", username, name, human_size(signature[0]))
                records[name] = {HASH_ALGO: hash_file(full), "size": signature[0], "mtime": signature[1]}
                hashed += 1
                dirty = True

            if dirty:
                write_hashes(user_dir, records)
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
    log.info(
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
    return jsonify({"success": False, "error": str(e)}), 500


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/clipboard', methods=['GET'])
def get_clipboard():
    """获取剪切板内容"""
    username = normalize_username(request.args.get('username', 'default'))
    if username is None:
        return bad_request("用户名不合法")
    content = read_clipboard(username)
    return jsonify({"content": content})


@app.route('/api/clipboard', methods=['POST'])
def post_clipboard():
    """保存剪切板内容"""
    data = request.json
    username = normalize_username(data.get('username', 'default'))
    if username is None:
        return bad_request("用户名不合法")
    content = data.get('content', '')
    write_clipboard(username, content)
    return jsonify({"success": True})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传文件（支持最大30GB，高效流式写入磁盘，内存占用恒定）"""
    try:
        started = time.monotonic()
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "没有文件"})
        
        file = request.files['file']
        username = normalize_username(request.form.get('username', 'default'))
        if username is None:
            return bad_request("用户名不合法")

        original_filename = safe_filename(file.filename)
        if not original_filename:
            return bad_request("文件名不合法")
        
        # 通过 Content-Length 请求头快速预估文件大小
        content_length = request.content_length
        if content_length is not None:
            # Content-Length 包含整个 multipart body，取 1.2 倍作为安全空间估算
            if not check_disk_space(username, int(content_length * 1.2)):
                log.warning("上传被拒(磁盘不足): user=%s file=%s body=%s", username, original_filename, human_size(content_length))
                return jsonify({"success": False, "error": "磁盘空间不足"})
        else:
            # 无法获取 Content-Length 时，尝试从文件流尾部获取大小
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)
            if not check_disk_space(username, int(file_size * 1.1)):
                log.warning("上传被拒(磁盘不足): user=%s file=%s size=%s", username, original_filename, human_size(file_size))
                return jsonify({"success": False, "error": "磁盘空间不足"})
        
        # 保留原始文件名，处理重名情况
        user_dir = get_user_files_dir(username)
        
        # 如果文件已存在，添加时间戳避免覆盖
        if os.path.exists(os.path.join(user_dir, original_filename)):
            name, ext = os.path.splitext(original_filename)
            timestamp = int(time.time())
            original_filename = f"{name}_{timestamp}{ext}"
        
        file_path = os.path.join(user_dir, original_filename)
        
        # 使用 shutil.copyfileobj 进行高效流式写入（16MB 缓冲区，减少系统调用）
        # Werkzeug 已将上传数据流式写入临时文件，这里从临时文件流式复制到目标位置
        chunk_size = 16 * 1024 * 1024  # 16MB per chunk，适合大文件传输
        hasher = hashlib.new(HASH_ALGO)
        with open(file_path, 'wb') as dst:
            shutil.copyfileobj(file.stream, HashingWriter(dst, hasher), chunk_size)
        
        written = os.path.getsize(file_path)
        digest = hasher.hexdigest()
        record_hash(user_dir, original_filename, digest)
        log.info(
            "上传完成: user=%s file=%s size=%s %s=%s 耗时=%.2fs",
            username, original_filename, human_size(written), HASH_ALGO, digest, time.monotonic() - started
        )
        return jsonify({"success": True, "filename": original_filename, HASH_ALGO: digest})
    except Exception as e:
        log.exception("上传失败: %s %s", request.method, request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": str(e)})


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
    """获取文件校验码；没有记录（历史文件）时现算一次并落盘"""
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
    cached = digest is not None

    if not cached:
        started = time.monotonic()
        log.info("开始计算校验码: user=%s file=%s size=%s", username, filename, human_size(file_size))
        digest = hash_file(file_path)
        record_hash(user_dir, filename, digest)
        log.info(
            "校验码计算完成: user=%s file=%s %s=%s 耗时=%.2fs",
            username, filename, HASH_ALGO, digest, time.monotonic() - started
        )

    return jsonify({"success": True, "name": filename, "size": file_size, HASH_ALGO: digest, "cached": cached})


@app.route('/api/upload/chunk', methods=['POST'])
def upload_chunk():
    """接收单个分片"""
    try:
        if 'chunk' not in request.files:
            return jsonify({"success": False, "error": "没有分片数据"})

        chunk_file = request.files['chunk']
        username = normalize_username(request.form.get('username', 'default'))
        file_id = request.form.get('file_id', '')
        chunk_index = request.form.get('chunk_index', '0')
        total_chunks = request.form.get('total_chunks', '1')

        if username is None or not _FILE_ID_RE.match(file_id or ''):
            return bad_request("参数不合法")

        chunk_dir = get_chunk_dir(username, file_id)
        chunk_path = os.path.join(chunk_dir, f"chunk_{int(chunk_index):06d}")

        # 流式写入分片
        with open(chunk_path, 'wb') as dst:
            shutil.copyfileobj(chunk_file.stream, dst, STREAM_CHUNK)

        return jsonify({"success": True, "chunk_index": int(chunk_index)})
    except Exception as e:
        log.exception("分片上传失败: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": str(e)})


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

        log.info("开始合并分片: user=%s file=%s file_id=%s", username, original_filename, file_id)
        user_dir = get_user_files_dir(username)
        final_name, digest = merge_chunks(username, file_id, original_filename)
        final_size = os.path.getsize(os.path.join(user_dir, final_name))
        record_hash(user_dir, final_name, digest)
        log.info(
            "合并完成: user=%s file=%s size=%s %s=%s 耗时=%.2fs",
            username, final_name, human_size(final_size), HASH_ALGO, digest, time.monotonic() - started
        )
        return jsonify({"success": True, "filename": final_name, HASH_ALGO: digest})
    except Exception as e:
        log.exception("合并分片失败: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/upload/abort', methods=['POST'])
def upload_abort():
    """取消上传：丢弃该 file_id 的全部分片（前端取消按钮调用）"""
    try:
        data = request.json
        username = normalize_username(data.get('username', 'default'))
        file_id = data.get('file_id', '')
        if username is None or not _FILE_ID_RE.match(file_id or ''):
            return bad_request("参数不合法")
        cleanup_chunks(username, file_id)
        log.info("上传已取消，清理分片: user=%s file_id=%s", username, file_id)
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

    # 解析 Range: bytes=start-end
    byte_range = range_header.replace('bytes=', '').split('-')
    start = int(byte_range[0]) if byte_range[0] else 0
    end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1

    if start >= file_size:
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
            # 客户端提前断开（关页面/内存不足导致中止）会在这里暴露出来
            if sent < length:
                log.warning(
                    "下载中断: user=%s file=%s start=%d 已发送=%s/期望=%s from=%s",
                    username, filename, start, human_size(sent), human_size(length), client_ip
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
            result.append({
                "name": name,
                "size": signature[0] if signature else 0,
                HASH_ALGO: known_hash(records.get(name), signature),
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
    except Exception as e:
        log.exception("删除文件异常: %s", request.full_path.rstrip("?"))
        return jsonify({"success": False, "error": str(e)})



def run_dev_server(ip):
    """开发服务器 (Werkzeug) — 仅限本地测试"""
    log.warning("使用开发服务器 (Werkzeug)，仅适合本地测试")
    print("  [警告] 当前使用开发服务器 (Werkzeug)，仅适合本地测试！")
    print("  生产环境请使用:")
    print("    Windows: run_server.bat")
    print("    Linux:   gunicorn -c gunicorn.conf.py http_messages_share:app")
    print("=" * 60)
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
            server.run()
        except ImportError:
            print("  [错误] 未安装 waitress，请执行: pip install waitress")
            print("  回退到开发服务器...")
            run_dev_server(ip)
    else:
        run_dev_server(ip)


if __name__ == '__main__':
    import socket
    
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    
    print("=" * 60)
    print("  QuickFilesSharing 服务")
    print(f"  本地访问:   http://localhost:5000")
    print(f"  局域网访问: http://{ip}:5000")
    print(f"  支持最大上传: 30GB")
    print("=" * 60)
    
    log.info("服务启动: 本地=http://localhost:5000 局域网=http://%s:5000 最大上传=30GB", ip)
    start_hash_reconcile()
    run_prod_server(ip)
