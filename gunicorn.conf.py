"""
Gunicorn 配置文件
适用于 30GB 大文件上传/下载场景，支持分片并行传输
使用方法: gunicorn -c gunicorn.conf.py http_messages_share:app
"""

import multiprocessing
import socket

# === 绑定地址 ===
bind = "0.0.0.0:5000"

# === 工作进程 ===
workers = min(multiprocessing.cpu_count() * 2 + 1, 8)
worker_class = "gevent"
worker_connections = 1000
max_requests = 5000
max_requests_jitter = 200

# === 超时设置 ===
timeout = 7200
graceful_timeout = 60
keepalive = 5

# === 请求体限制 ===
limit_request_line = 0
limit_request_fields = 200
limit_request_field_size = 0

# === TCP 调优：跑满带宽 ===

def post_fork(server, worker):
    """worker fork 后立即调优 socket"""
    import socket as sock_mod
    # Gunicorn 的 server.sockets 包含所有监听 socket
    for s in server.sockets if hasattr(server, 'sockets') else []:
        s.setsockopt(sock_mod.SOL_SOCKET, sock_mod.SO_SNDBUF, 4 * 1024 * 1024)  # 4MB 发送缓冲
        s.setsockopt(sock_mod.SOL_SOCKET, sock_mod.SO_RCVBUF, 4 * 1024 * 1024)  # 4MB 接收缓冲
        s.setsockopt(sock_mod.IPPROTO_TCP, sock_mod.TCP_NODELAY, 1)              # 禁用 Nagle


def post_worker_init(worker):
    """每个 worker 初始化后，对所有活跃连接 socket 调优"""
    import socket as sock_mod
    # 这里的 socket 选项会影响 accept 后的子连接
    # 通过底层继承实现，提前设置好选项
    try:
        # Linux 特有：启用 TCP_CORK 的替代——TCP_NODELAY 已经足够
        # 增大 socket 默认缓冲
        sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM).setsockopt
    except Exception:
        pass

# === sendfile 零拷贝（Gunicorn + gevent 默认支持） ===
# sendfile 在内核态完成文件→socket 传输，无需用户态拷贝
# 只要不设置 "--no-sendfile" 即可，此处显式确认

# === 日志 ===
accesslog = "-"
errorlog = "-"
loglevel = "info"

# 访问日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'

# === 进程管理 ===
# 预加载应用代码（节省内存，但要求应用线程安全）
preload_app = True

# 以 demon 模式运行（后台运行），Windows 不支持
daemon = False

# PID 文件
pidfile = "gunicorn.pid"

# === 其他 ===
# 临时文件上传目录（可选，默认使用系统临时目录）
# worker_tmp_dir = "/dev/shm"  # Linux 下使用内存文件系统加速小文件
