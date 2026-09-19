# 项目评审问题清单

- 评审基线：commit `fd3881a`（2026-09-19）
- 范围：`http_messages_share.py`（后端全文）、`templates/index.html`（前端全文）
- 用途：评审记录与逐条讨论的底稿。**未经讨论不改码**，每条处理完更新"状态"。
- 行号以评审基线为准，改动后会漂移。

状态取值：`待讨论` / `已实现` / `决定不做（原因）` / `已修复`。

---

## P0：直接伤"稳定传输 / 数据安全"

### P0-1 下载内存上限与"支持 30GB"宣称矛盾
- 状态：**已实现（2026-09-19，方案见文末附注）**
- 位置：`templates/index.html:1016-1017`（chunkData 全量驻留）、`:1066-1069`（组装再复制一份）、`:1077-1083`（Blob）；`http_messages_share.py:654-660`（未被前端使用的 `/api/download`）
- 问题：分片下载把所有分片存内存，最后 `new Uint8Array(totalLength)` 整体复制，峰值 ≈ 2 倍文件大小；单个 ArrayBuffer 还有浏览器硬上限（约 2GB 级）。实用上限约 1GB，超过则标签页 OOM 或 RangeError，30GB 全白传。
- 改进方向：按大小分流——小文件保留分片并行，大文件走 `/api/download` 让浏览器下载管理器接管（流式落盘、无内存上限、支持断点续传）。

### P0-2 `filename` / `username` 未过滤，路径可越出用户目录
- 状态：待讨论
- 位置：裸 `os.path.join(user_dir, filename)`——`/api/file/info`（`:454`）、`/api/file/hash`（`:472`）、`/api/download/chunk`（`:558`）、`/api/delete`（`:672`）；username 同样裸用：`get_clipboard_path`（`:83-87`）、`get_user_files_dir`（`:90-97`）；上传文件名来自 multipart：`:397`/`:426`，merge 的 filename：`:532`/`:133`
- 问题：`filename=..\..\x` 可越出 `files/` 目录，`/api/delete` 理论上可删任意盘上的文件；`username=..` 会让目录落到项目根。唯一有防护的是 `/api/download`（`send_from_directory` 内部 `safe_join`）。
- 影响：既是安全隐患也是"一次手滑误删文件"的数据安全问题。
- 改进方向：统一入口过滤——username 只允许 `[A-Za-z0-9_-]`，filename 取 basename 并拒绝 `..` / 绝对路径 / 开头带点。

### P0-3 文件列表渲染未转义文件名（XSS / 属性截断）
- 状态：待讨论
- 位置：`templates/index.html:975-993`（`loadFiles` 拼字符串），裸插 `${f.name}` 在 `:984`（含 `title` 属性）；`:976` 只转义了单引号；`escapeHtml` 存在（`:887-891`）但这里没用；`onclick` 拼接在 `:978-979`、`:989-990`
- 问题：文件名含 `<` 会注入 HTML（XSS）；含 `"` 会截断 `onclick` 属性使其失效。Windows 本机文件名不含这些字符，但手机（Android）传的文件可以。
- 改进方向：文件名统一走 `escapeHtml`；根治是 `data-` 属性 + 事件委托，不再把文件名塞进 `onclick` 字符串。

## P1：对"快捷、稳定"体验影响明显

### P1-4 上传/下载没有取消按钮
- 状态：待讨论
- 位置：`uploadXhrs` 收集了 XHR（声明 `:531`、push `:784`、清空 `:856`）但没有任何 UI 调 `abort()`；下载的 XHR 甚至没收集（`:1027-1042`）
- 影响：30GB 传错了只能干等或关页面；关页面又触发 P1-5 的孤儿分片。
- 改进方向：进度区加"取消"按钮，上传调 `xhr.abort()`，下载同理，中止后清理 `.chunks`。

### P1-5 孤儿分片目录无人清理
- 状态：待讨论
- 位置：`cleanup_chunks`（`http_messages_share.py:115-119`）只在合并成功后调用（`:150`）；合并失败、浏览器中途关闭都不清；启动对账（`:268-310`）不碰 `.chunks`
- 影响：一次 30GB 上传失败就白占 30GB 磁盘。
- 改进方向：启动对账时顺带删除超过 N 天的 `files/*/.chunks/*`；merge 异常路径也清理。

### P1-6 端口双绑没有守门（踩过的坑）
- 状态：待讨论
- 位置：`run_prod_server`（`http_messages_share.py:699-758`）固定绑 5000，启动前无检测
- 问题：Windows + waitress 下两个进程能同时绑 5000（SO_REUSEADDR 语义），旧实例还在跑时新代码"改了没生效"。
- 改进方向：启动前向 `localhost:5000` 发探测请求，有响应就警告"已有实例在运行"并退出或提示。

### P1-7 启动脚本与入口体验缺口
- 状态：待讨论
- 位置：`http_messages_share.py:693` 提示用户用 `run_server.bat`，但仓库里没有这个文件；`:764-765` 用 `gethostbyname` 只打一个 IP，有 VMware/WSL 虚拟网卡时会打错；无 `webbrowser.open` 自动开页；无 README
- 改进方向：补 start.bat（venv + 启动）、自动开浏览器、枚举打印所有局域网 IPv4。

### P1-8 `/api/download` 与其他接口的目录基准不一致（CWD ≠ 项目目录时下载 404）
- 状态：**已修复（2026-09-19）**
- 位置：`http_messages_share.py:654-660`。`send_from_directory` 会把相对目录拼到 `app.root_path`（py 文件所在目录）；其余接口全部用进程 CWD 的相对路径（`files/...`）。
- 问题：从项目目录启动时两者恰好一致，一切正常；一旦从其他 CWD 启动（如 `python E:\...\http_messages_share.py`、计划任务、未来的 start.bat 放在别处），上传/列表/删除落在 CWD 的 `files/`，而 `/api/download` 去 `app.root_path/files/` 找——表现为"列表里有文件，点下载 404"。已在测试中复现。
- 修复：`CLIPBOARD_DIR` / `FILES_DIR` / `LOG_DIR` 统一锚定到 `os.path.dirname(os.path.abspath(__file__))`，CWD 不再影响行为。
- 验证：从外来目录（%TEMP%）启动服务，列表与 `/api/download` 一致且内容哈希匹配；curl 断点续传（`-r` 取前 1MB + `-C -` 补完，206）与 aria2c（`-x4 -s4 -c`，64MB）下载结果 SHA-256 均与源一致。

## P2：优化项与低风险瑕疵

### P2-8 分片上传多一次磁盘写（multipart spool）
- 位置：`http_messages_share.py:495-518`。32MB 分片走 multipart，Werkzeug 先把整片 spool 到临时文件，再 `copyfileobj` 到 `chunk_*`（`:515-516`）——每个字节写盘两次，merge 时再读一次。
- 方向：改裸 body 上传（`xhr.send(blob)` + 元数据放请求头），后端直接读 `request.stream`。接口重构，量力而行。

### P2-9 剪切板写入非原子
- 位置：`http_messages_share.py:163-167`。进程被杀可能截断文件。
- 方向：照哈希记录的做法 tmp + `os.replace`。

### P2-10 上传/下载共用同一条进度条与同一个 `progressTimer`
- 位置：`index.html:490-496`（共享 DOM）、`:532`（全局 timer）、`:763`（上传启动）、`:1019`（下载覆盖）。
- 影响：并发进行时互相覆盖，先前的进度显示停摆。简易项目可接受，知悉即可。

### P2-11 `/api/upload` 是前端已不用的死代码
- 位置：`http_messages_share.py:386-445`。前端只走 `/api/upload/chunk` + merge。且其重名处理（`:420-424`）与 `merge_chunks`（`:129-131`）重复。
- 方向：确认后删除或标注废弃。

### P2-12 `/api/download/chunk` 的 Range 解析不严谨
- 位置：`http_messages_share.py:580-582`。`bytes=-500` 后缀语义被当成"取前 500 字节"（应取末 500）；非数字 Range 抛 ValueError → 500（应 416）；未校验 start ≤ end。
- 影响：仅自研前端调用（总是发显式 `bytes=start-end`），无实际故障；但若第三方客户端直连该接口会出错。`/api/download`（Werkzeug 处理 Range）无此问题。

### P2-13 重名去重只做一层、时间戳秒级碰撞
- 位置：`http_messages_share.py:129-131`（merge）、`:420-424`（upload）。同一秒内两次同名上传，第二次的 `名字_时间戳` 仍可能撞上，`open('wb')` 直接覆盖前者。
- 方向：循环加后缀直到不冲突，或引入毫秒/计数。

### P2-14 merge 信任磁盘上的分片集合
- 位置：`http_messages_share.py:136-139`。merge 只合并 `.chunks` 里实际存在的文件，缺片不报错，会产出被截断的文件并记上哈希。自研前端保证了先全后并，但接口本身没有防线。

### P2-15 启动对账可能与早期传输抢磁盘 I/O
- 位置：`http_messages_share.py:313-315`。后台线程给无记录文件补算 SHA-256（会全量读盘）。已有 mtime+size 跳过机制，重启后通常无活干；仅在大量未记录文件时明显。

### P2-16 访问日志逐请求记录，大文件会产生大量分片日志行
- 位置：`http_messages_share.py:331-349`。30GB 下载 ≈ 960 条 chunk 日志。有滚动（20MB×5）不会爆盘，属噪音问题，可选降级。

### P2-17 错误响应把 `str(e)` 原样返回给客户端
- 位置：`http_messages_share.py:359`、`:445`、`:521`、`:549`、`:684`。会泄漏服务器内部路径。局域网自用可接受，知悉即可。

### P2-18 无 favicon
- 每次页面加载一条 404 日志。加一个内联 favicon 或路由即可，纯噪音。

### P2-19 分片重试只有一次、无退避
- 位置：上传 `index.html:818-820`、下载 `:1052`。局域网够用；叠加 P1-4（无取消），网络抖动时用户只能看着。

### P2-20 `total_chunks` 字段收了但服务端没用
- 位置：`http_messages_share.py:506`（接收）、`:518`（回显）。merge 完全信任磁盘状态（见 P2-14）。要么用来校验分片齐全，要么删掉。

---

## 附注：P0-1 已实现的方案（2026-09-19）

- 阈值 `NATIVE_DL_LIMIT = 1GB`：≤1GB 走原分片并行下载（内存峰值约 2~3GB，可接受）；>1GB 前端改请求 `/api/download`，由浏览器下载管理器流式落盘接管，页面提示进度去浏览器下载栏看。
- 前端在校验码弹窗（点文件校验码行打开）新增"命令行下载"区：curl（CMD/PowerShell/Linux/macOS）与 `aria2c -x4 -s4 -c`，命令带真实 URL（取 `location.origin`），配复制按钮；并提示 localhost 打开时需把地址换成局域网 IP。
- 后端零改动；`/api/download` 由 Werkzeug 处理 Range（已验证 206 + Content-Range）。
