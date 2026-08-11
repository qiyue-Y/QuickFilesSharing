"""
简易剪切板HTTP服务
功能：用户可以登录后查看、保存剪切板内容，以及上传/下载/删除文件
存储：剪切板存为TXT文件，文件存储在用户目录下
运行：python http_messages_share.py
访问：http://localhost:5000
上传限制：最大30GB（支持分片并行上传，跑满带宽）
下载：支持 Range 分片并行下载
"""

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, Response
import os
import time
import shutil
import glob
from urllib.parse import quote

app = Flask(__name__)
# 30GB 最大上传大小 (30 * 1024^3 字节)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024 * 1024  # 30GB max file size

# === 调优参数 ===
CHUNK_SIZE = 32 * 1024 * 1024       # 分片大小：32MB（前端分片）
STREAM_CHUNK = 16 * 1024 * 1024     # 流式写入缓冲：16MB
SOCKET_SEND_BUF = 4 * 1024 * 1024   # Socket 发送缓冲：4MB
SOCKET_RECV_BUF = 4 * 1024 * 1024   # Socket 接收缓冲：4MB

# 存储目录
CLIPBOARD_DIR = "clipboards"
FILES_DIR = "files"
if not os.path.exists(CLIPBOARD_DIR):
    os.makedirs(CLIPBOARD_DIR)
if not os.path.exists(FILES_DIR):
    os.makedirs(FILES_DIR)


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
    """按序号合并分片到最终文件"""
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

    with open(file_path, 'wb') as dst:
        for chunk_file in chunk_files:
            with open(chunk_file, 'rb') as src:
                shutil.copyfileobj(src, dst, STREAM_CHUNK)

    # 清理分片
    cleanup_chunks(username, file_id)
    return final_name


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


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/clipboard', methods=['GET'])
def get_clipboard():
    """获取剪切板内容"""
    username = request.args.get('username', 'default')
    content = read_clipboard(username)
    return jsonify({"content": content})


@app.route('/api/clipboard', methods=['POST'])
def post_clipboard():
    """保存剪切板内容"""
    data = request.json
    username = data.get('username', 'default')
    content = data.get('content', '')
    write_clipboard(username, content)
    return jsonify({"success": True})


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传文件（支持最大30GB，高效流式写入磁盘，内存占用恒定）"""
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "没有文件"})
        
        file = request.files['file']
        username = request.form.get('username', 'default')
        
        original_filename = file.filename
        if not original_filename:
            return jsonify({"success": False, "error": "文件名为空"})
        
        # 通过 Content-Length 请求头快速预估文件大小
        content_length = request.content_length
        if content_length is not None:
            # Content-Length 包含整个 multipart body，取 1.2 倍作为安全空间估算
            if not check_disk_space(username, int(content_length * 1.2)):
                return jsonify({"success": False, "error": "磁盘空间不足"})
        else:
            # 无法获取 Content-Length 时，尝试从文件流尾部获取大小
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)
            if not check_disk_space(username, int(file_size * 1.1)):
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
        with open(file_path, 'wb') as dst:
            shutil.copyfileobj(file.stream, dst, chunk_size)
        
        return jsonify({"success": True, "filename": original_filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/file/info', methods=['GET'])
def file_info():
    """获取文件大小（用于分片下载规划）"""
    username = request.args.get('username', 'default')
    filename = request.args.get('filename', '')
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)

    if not os.path.exists(file_path):
        return jsonify({"success": False, "error": "文件不存在"}), 404

    file_size = os.path.getsize(file_path)
    return jsonify({"success": True, "size": file_size, "name": filename})


@app.route('/api/upload/chunk', methods=['POST'])
def upload_chunk():
    """接收单个分片"""
    try:
        if 'chunk' not in request.files:
            return jsonify({"success": False, "error": "没有分片数据"})

        chunk_file = request.files['chunk']
        username = request.form.get('username', 'default')
        file_id = request.form.get('file_id', '')
        chunk_index = request.form.get('chunk_index', '0')
        total_chunks = request.form.get('total_chunks', '1')

        if not file_id:
            return jsonify({"success": False, "error": "缺少 file_id"})

        chunk_dir = get_chunk_dir(username, file_id)
        chunk_path = os.path.join(chunk_dir, f"chunk_{int(chunk_index):06d}")

        # 流式写入分片
        with open(chunk_path, 'wb') as dst:
            shutil.copyfileobj(chunk_file.stream, dst, STREAM_CHUNK)

        return jsonify({"success": True, "chunk_index": int(chunk_index)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/upload/merge', methods=['POST'])
def upload_merge():
    """合并分片为最终文件"""
    try:
        data = request.json
        username = data.get('username', 'default')
        file_id = data.get('file_id', '')
        original_filename = data.get('filename', 'untitled')

        if not file_id:
            return jsonify({"success": False, "error": "缺少 file_id"})

        final_name = merge_chunks(username, file_id, original_filename)
        return jsonify({"success": True, "filename": final_name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/download/chunk', methods=['GET'])
def download_chunk():
    """支持 Range 的分片下载"""
    username = request.args.get('username', 'default')
    filename = request.args.get('filename', '')
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)

    if not os.path.exists(file_path):
        return jsonify({"error": "文件不存在"}), 404

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get('Range', None)

    if not range_header:
        # 无 Range 头则返回整个文件（兜底）
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
        return Response(status=416)

    end = min(end, file_size - 1)
    length = end - start + 1

    # 流式发送指定范围，使用大缓冲区
    def generate():
        with open(file_path, 'rb') as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(STREAM_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

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
    """获取用户的文件列表（含文件大小，排除分片临时目录）"""
    username = request.args.get('username', 'default')
    user_dir = get_user_files_dir(username)
    result = []
    for name in os.listdir(user_dir):
        full = os.path.join(user_dir, name)
        # 跳过分片临时目录与隐藏目录
        if name == '.chunks' or name.startswith('.') and os.path.isdir(full):
            continue
        if os.path.isfile(full):
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            result.append({"name": name, "size": size})
    result.sort(key=lambda x: x["name"])
    return jsonify({"files": result})


@app.route('/api/download', methods=['GET'])
def download_file():
    """下载文件"""
    username = request.args.get('username', 'default')
    filename = request.args.get('filename', '')
    user_dir = get_user_files_dir(username)
    return send_from_directory(user_dir, filename, as_attachment=True)


@app.route('/api/delete', methods=['POST'])
def delete_file():
    """删除文件"""
    try:
        data = request.json
        username = data.get('username', 'default')
        filename = data.get('filename', '')
        
        user_dir = get_user_files_dir(username)
        file_path = os.path.join(user_dir, filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "文件不存在"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})



def run_dev_server(ip):
    """开发服务器 (Werkzeug) — 仅限本地测试"""
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
    
    run_prod_server(ip)
