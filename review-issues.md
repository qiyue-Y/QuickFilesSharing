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
- 状态：**已修复（2026-09-19）**
- 位置：裸 `os.path.join(user_dir, filename)`——`/api/file/info`（`:454`）、`/api/file/hash`（`:472`）、`/api/download/chunk`（`:558`）、`/api/delete`（`:672`）；username 同样裸用：`get_clipboard_path`（`:83-87`）、`get_user_files_dir`（`:90-97`）；上传文件名来自 multipart：`:397`/`:426`，merge 的 filename：`:532`/`:133`
- 修复：新增 `normalize_username`（`^[\w-]{1,64}$`，含中文）、`safe_filename`（拒绝路径分隔符 / `..` / 隐藏文件）、`_FILE_ID_RE`，全部 11 个接口入口统一校验，非法一律 400。注意：用户名不再允许空格和点（现有用户名均兼容）。
- 验证：`username=../foo`、`filename=..\..\x`、`.hashes.json`、`..`、JSON body 里的 `..\` 删除请求全部 400；正常文件（含 `it's & test #1.txt`、中文名）列表/校验/下载不受影响。

### P0-3 文件列表渲染未转义文件名（XSS / 属性截断）
- 状态：**已修复（2026-09-19）**
- 位置：`templates/index.html:975-993`（`loadFiles` 拼字符串），裸插 `${f.name}` 在 `:984`（含 `title` 属性）；`:976` 只转义了单引号；`escapeHtml` 存在（`:887-891`）但这里没用；`onclick` 拼接在 `:978-979`、`:989-990`
- 修复：`loadFiles` 改为 `data-filename="${escapeHtml(f.name)}"` + `#fileList` 事件委托（下载/删除/校验码按 `closest()` 路由），内联 `onclick` 全部移除，文件名展示统一走 `escapeHtml`。
- 验证：浏览器实测 `it's & test #1.txt` 渲染正确、委托点击打开弹窗且命令 URL 编码正确、`onclick` 属性已不存在。

## P1：对"快捷、稳定"体验影响明显

### P1-4 上传/下载没有取消按钮
- 状态：**已实现（2026-09-19）**
- 位置：`uploadXhrs` 收集了 XHR（声明 `:531`、push `:784`、清空 `:856`）但没有任何 UI 调 `abort()`；下载的 XHR 甚至没收集（`:1027-1042`）
- 实现：进度区新增"取消传输"按钮（传输开始显示、结束隐藏）；`cancelTransfer()` 统一 abort 当前传输的所有 XHR（`transferXhrs`，上传下载共用），上传侧附带调 `/api/upload/abort` 清分片；取消后跳过重试、批量上传中止后续文件，状态提示"已取消"。
- 验证：浏览器实测 1GB 上传中途点取消——分片目录被清理、无半成品文件、按钮隐藏、输入框恢复可用。

### P1-5 孤儿分片目录无人清理
- 状态：**已修复（2026-09-19）**
- 位置：`cleanup_chunks`（`http_messages_share.py:115-119`）只在合并成功后调用（`:150`）；合并失败、浏览器中途关闭都不清；启动对账（`:268-310`）不碰 `.chunks`
- 修复：三条清理路径——(1) 启动维护线程 `sweep_stale_chunks()`：删除"目录内最新文件 mtime 超过 24 小时"的分片目录（活跃上传会持续写新分片，不会误删）；(2) 取消上传调 `/api/upload/abort` 即时清理；(3) `merge_chunks` 失败时清理半成品文件与分片。
- 验证：启动清扫实测——3 天前的分片目录被删、新鲜目录保留；abort 接口实测分片目录即时消失。

### P1-6 端口双绑没有守门（踩过的坑）
- 状态：**已修复（2026-09-19）**
- 位置：`run_prod_server`（`http_messages_share.py:699-758`）固定绑 5000，启动前无检测
- 修复：启动入口新增 `check_port_in_use(5000)`，被占用则打印排查指引（netstat / taskkill）并 exit(1)，不再静默双绑。
- 验证：占住 5000 后启动，退出码 1、提示正确。

### P1-7 启动脚本与入口体验缺口
- 状态：**已修复（2026-09-19）**——其中"启动脚本"一项被用户明确否决（不要 .bat），代码内引用已全部移除
- 位置：原 `http_messages_share.py:693` 提示用不存在的 `run_server.bat`；`:764-765` 用 `gethostbyname` 只打一个 IP，有 VMware/WSL 虚拟网卡时会打错；无 `webbrowser.open` 自动开页；无 README
- 修复：(1) 启动横幅枚举全部局域网 IPv4，并用 UDP connect（不发包）标出默认路由出口为"推荐"；(2) 监听就绪后 1 秒自动打开浏览器（注意 `threading.Timer` 不接受 daemon 参数，需构造后赋值）；(3) 新增 README.md；(4) 移除代码中对 run_server.bat 的提示（曾试做 .bat，实测发现 cmd 按 GBK 解析 .bat、UTF-8 中文行会被当命令执行，用户明确不需要，已删）。
- 验证：本机实测枚举出 3 个 IP（2 个虚拟网卡 + 198.51.100.7），推荐标记正确；启动后 GET / 返回 200、API 正常。

### P1-8 `/api/download` 与其他接口的目录基准不一致（CWD ≠ 项目目录时下载 404）
- 状态：**已修复（2026-09-19）**
- 位置：`http_messages_share.py:654-660`。`send_from_directory` 会把相对目录拼到 `app.root_path`（py 文件所在目录）；其余接口全部用进程 CWD 的相对路径（`files/...`）。
- 问题：从项目目录启动时两者恰好一致，一切正常；一旦从其他 CWD 启动（如 `python E:\...\http_messages_share.py`、计划任务），上传/列表/删除落在 CWD 的 `files/`，而 `/api/download` 去 `app.root_path/files/` 找——表现为"列表里有文件，点下载 404"。已在测试中复现。
- 修复：`CLIPBOARD_DIR` / `FILES_DIR` / `LOG_DIR` 统一锚定到 `os.path.dirname(os.path.abspath(__file__))`，CWD 不再影响行为。
- 验证：从外来目录（%TEMP%）启动服务，列表与 `/api/download` 一致且内容哈希匹配；curl 断点续传（`-r` 取前 1MB + `-C -` 补完，206）与 aria2c（`-x4 -s4 -c`，64MB）下载结果 SHA-256 均与源一致。

## P2：优化项与低风险瑕疵

### P2-8 分片上传多一次磁盘写（multipart spool）
- 位置：`http_messages_share.py:495-518`。32MB 分片走 multipart，Werkzeug 先把整片 spool 到临时文件，再 `copyfileobj` 到 `chunk_*`（`:515-516`）——每个字节写盘两次，merge 时再读一次。
- 状态：**已实现（2026-09-19，数据驱动）**——先实测：multipart 基线 1GB 端到端 82.3 MB/s（分片阶段 102.2，低于千兆线速 118），合并阶段纯磁盘 421.7 MB/s 证明瓶颈在双写。改为裸 body 上传（`xhr.send(blob)` + `X-File-Id`/`X-Chunk-Index` 请求头，后端直接读 `request.stream`）后：分片阶段 389.0 MB/s，端到端 **237.4 MB/s（2.9 倍）**，SHA-256 一致。注意 username 必须走 query（请求头仅 latin-1，中文名会炸）。

### P2-9 剪切板写入非原子
- 位置：`http_messages_share.py:163-167`。进程被杀可能截断文件。
- 状态：**已修复（2026-09-19）**——临时文件 + `os.replace` 原子替换，与 `write_hashes` 同款模式；写入失败照常返回 500（用户数据不静默吞）。
- 验证：写入/回读一致，无 `.tmp` 残留。

### P2-10 上传/下载共用同一条进度条与同一个 `progressTimer`
- 位置：`index.html:490-496`（共享 DOM）、`:532`（全局 timer）、`:763`（上传启动）、`:1019`（下载覆盖）。
- 状态：**已修复（2026-09-19）**——真正的 bug 是定时器泄漏：全局句柄被并发传输覆盖后旧 interval 永不清除，双 tick 互踩。改为每次传输持有局部句柄、终态自清；共享进度条"后来者覆盖显示"按简易项目定位保留。

### P2-11 `/api/upload` 是前端已不用的死代码
- 位置：`http_messages_share.py:386-445`。前端只走 `/api/upload/chunk` + merge。且其重名处理（`:420-424`）与 `merge_chunks`（`:129-131`）重复。
- 状态：**已删除（2026-09-19，用户确认）**——连带删除仅它使用的 `check_disk_space`；回归确认 POST /api/upload 404。

### P2-12 `/api/download/chunk` 的 Range 解析不严谨
- 位置：`http_messages_share.py:580-582`。`bytes=-500` 后缀语义被当成"取前 500 字节"（应取末 500）；非数字 Range 抛 ValueError → 500（应 416）；未校验 start ≤ end。
- 状态：**已修复（2026-09-19）**——完整解析：后缀 `bytes=-N` 取末 N 字节、负 start/倒序/非数字/空区间一律 416。
- 验证：`bytes=0-9`→206 前段、`bytes=-10`→206 末 10 字节（Content-Range 正确）、`abc`/`99-1`/`-0` 全部 416。

### P2-13 重名去重只做一层、时间戳秒级碰撞
- 位置：`http_messages_share.py:129-131`（merge）、`:420-424`（upload）。同一秒内两次同名上传，第二次的 `名字_时间戳` 仍可能撞上，`open('wb')` 直接覆盖前者。
- 状态：**已修复（2026-09-19）**——新增 `exclusive_path()`（原名 → 时间戳 → 时间戳_1 … 循环到空闲）+ `open('xb')` 独占创建，并发抢先时宁可报错也不覆盖。merge 与旧接口 `/api/upload` 两处统一。
- 验证：同秒两次同名合并产出 `dup.txt` 与 `dup_1789806230.txt`，内容互不覆盖。

### P2-14 merge 信任磁盘上的分片集合
- 位置：`http_messages_share.py:136-139`。merge 只合并 `.chunks` 里实际存在的文件，缺片不报错，会产出被截断的文件并记上哈希。自研前端保证了先全后并，但接口本身没有防线。
- 状态：**已修复（2026-09-19）**——与 P2-20 一起闭环：merge 请求必须带 `total_chunks`（前端补发），后端校验分片序号恰为 0..N-1 无缺失，缺片返回 400"分片不齐全"并自动清理分片目录，不再产出截断文件。

### P2-15 启动对账可能与早期传输抢磁盘 I/O
- 位置：`http_messages_share.py:313-315`。后台线程给无记录文件补算 SHA-256（会全量读盘）。已有 mtime+size 跳过机制，重启后通常无活干；仅在大量未记录文件时明显。
- 状态：**决定不做（2026-09-19）**——日志实测"补算 0 个、耗时 0.00s"，现有跳过机制已够用。

### P2-16 访问日志逐请求记录，大文件会产生大量分片日志行
- 位置：`http_messages_share.py:331-349`。30GB 下载 ≈ 960 条 chunk 日志。有滚动（20MB×5）不会爆盘，属噪音问题，可选降级。
- 状态：**已修复（2026-09-19）**——分片路径请求日志降为 DEBUG，完成/合并/中断等关键事件保持 INFO。注意：dev 服务器另有 werkzeug 自带访问日志（不受控），生产 waitress 无此噪音。

### P2-17 错误响应把 `str(e)` 原样返回给客户端
- 位置：`http_messages_share.py:359`、`:445`、`:521`、`:549`、`:684`。会泄漏服务器内部路径。局域网自用可接受，知悉即可。
- 状态：**已修复（2026-09-19）**——兜底 handler 与各 except 块改为固定友好文案，堆栈与细节只进日志（配合后端日志落盘可查）。自产的业务错误文案（如"分片不齐全"）保留原文。

### P2-18 无 favicon
- 每次页面加载一条 404 日志。加一个内联 favicon 或路由即可，纯噪音。
- 状态：**已修复（2026-09-19）**——`<head>` 加 data-URI SVG 图标，零请求。

### P2-19 分片重试只有一次、无退避
- 位置：上传 `index.html:818-820`、下载 `:1052`。局域网够用；叠加 P1-4（无取消），网络抖动时用户只能看着。
- 状态：**已修复（2026-09-19）**——重试前加 300ms / 800ms 退避，取消时立即中止不再重试。

### P2-20 `total_chunks` 字段收了但服务端没用
- 位置：`http_messages_share.py:506`（接收）、`:518`（回显）。merge 完全信任磁盘状态（见 P2-14）。要么用来校验分片齐全，要么删掉。
- 状态：**已修复（2026-09-19）**——合并请求改为必带 `total_chunks`，作为 P2-14 防线的输入；缺失或非法返回 400。

---

## 附注：P0-1 已实现的方案（2026-09-19）

- 阈值 `NATIVE_DL_LIMIT = 1GB`：≤1GB 走原分片并行下载（内存峰值约 2~3GB，可接受）；>1GB 前端改请求 `/api/download`，由浏览器下载管理器流式落盘接管，页面提示进度去浏览器下载栏看。
- 前端在校验码弹窗（点文件校验码行打开）新增"命令行下载"区：curl（CMD/PowerShell/Linux/macOS）与 `aria2c -x4 -s4 -c`，命令带真实 URL（取 `location.origin`），配复制按钮；并提示 localhost 打开时需把地址换成局域网 IP。
- 后端零改动；`/api/download` 由 Werkzeug 处理 Range（已验证 206 + Content-Range）。
