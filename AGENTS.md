# AGENTS.md — QuickFilesSharing

局域网留言板 + 大文件快传服务。文件按用户名隔离、留言全员共享，无鉴权，仅限可信局域网使用。

## 布局

- `http_messages_share.py` — 后端全部（Flask + waitress/gunicorn），端口固定 5000
- `templates/index.html` — 前端骨架（247 行，只有标记，无内联 style/script）
- `static/css/` — `tokens.css`（色板/字体栈/@font-face；色相只在这里定义一次：11 个 `--rgb-*` 通道三元组是唯一的源，整色令牌由它派生 `--gold-glint: rgb(var(--rgb-gold))`，界面里带透明度一律写 `rgba(var(--rgb-gold), .55)`，**不要再落新的 `rgba(242,207,143,…)` 字面量**；例外是 E-0925-1 挂起的 14 处深墨色裸值（通道 `4,11,15`～`11,26,32`，拍板接受现状，见 `review-issues.md`），这 14 处之外不许再添加裸色值）、`pond.css`（背景层/粒子/标题渐变）、`ui.css`（topbar/panel/文件行/弹窗/toast/媒体查询）、`login.css`（登录台：拱框展品 + 宣纸登录卡，规则全部收在 `#login-gate` 作用域内；转场不用整屏遮挡层，进入/退出两个方向共用 `body[data-stage]` 驱动的一组 opacity 过渡）
- `static/js/` — 原生 ES Module，无构建无框架（13 个模块 + `vendor/qrcode.js` 自托管 MIT 库，末尾补了 ESM 导出行），`main.js` 汇总并按 hud→files→upload→download→board→login 顺序 `init(ctx)` 初始化；`api.js` 收口 15 个接口（含 `shareOrigin()`：页面用 localhost 打开时把复制给别人的地址换成局域网 IP），`ui.js` 管 toast/复制/焦点圈定弹窗与通用确认框 `confirmDialog()`（危险操作一律用它，不用原生 confirm），`format.js` 收口格式化与文件图标，`transfer.js` 是单传输闸门，`upload.js` 是分片上传 + 整页拖放（提示层 `.drop-veil`；弹窗开着时投放不触发上传），`verify.js` 是页面内一键校验（纯 JS SHA-256 跑在 Blob URL Worker 里——非安全上下文没有 `crypto.subtle`），`board.js` 是留言板（5s 轮询 + `after` 增量 + 长留言折叠 / 删自己那条）。模块作用域里的函数不在 `window` 上，**事件一律在模块内 `addEventListener`（列表行用委托），不写内联 `onclick`**
- `static/img/` `static/fonts/` — 睡莲池背景/画廊图 + 自托管 woff2
- `files/<用户名>/` — 用户文件；`.chunks/` 分片临时目录（含 `meta.json`：文件名+开始时间；启动清扫 mtime>24h，逐条记日志）；`.hashes.json` 哈希记录
- `clipboards/messages.db` — 留言板（SQLite，标准库 `sqlite3`，WAL）。全员共享一块板，页面只展示最近 5 条（`BOARD_VISIBLE`），更早的留在库里。**代码不读旧的 `clipboards/<user>.txt`**（一次性导入已完成，别再往启动流程里加兼容迁移）
- `logs/app.log` — 运行日志（20MB×5 滚动）
- `review-issues.md` — **三块**：状态总表（每个编号一行：状态/重要性/详情在哪）→ 已完结表（一行一条，详情在 `docs/`）→ 待实施正文（四要素，未完成事项的唯一详细来源）。**改敏感区域前先读**；一件事做完 = 正文删掉 + `docs/` 当天写记录 + 两张表各加一行
- `review-p2.md` — P2 报备清单：评审判定"理论风险、不修"的项（分级规矩见「代码评审分级」）。路过顺带消除时从本文件删除并在归档记一笔
- `design-archive/` — 前端样式归档留存（demo-v1/v2/v3 竞稿 + qfs-waterlilies 定稿，~14MB 纯静态页面与参考图，不参与运行时；2026-09-26 由根目录合并入库）
- `docs/<日期>.md` — 改动记录归档（见下节），如 `docs/2026-09-19.md`
- `tools/` — 仓库内的开发辅助脚本（不参与运行时），目前只有 `check_dead_css.py`
- `README.md` — 面向使用者的说明

## 归档方法（docs/）

- **一份文件只写一天**：文件名就是日期 `docs/YYYY-MM-DD.md`，只放当天做完的改动。跨天的改动各归各天，不要合并成一份"总记录"。
- **一条记录四要素**：问题 / 原因 / 解决方法 / 日期。有实测就补一行 `验证`（跑了什么命令、拿到什么数字或结果）；改了什么就附提交号。
- **做完即移**：事情做完就从 `review-issues.md` 的待实施正文里删掉、写进当天的归档文件，同时在 `review-issues.md` 的「已完结」表加一行、状态总表那行改成已完结。明确否决的决定也归档（写清原因），正文不占条目，只在总表留一行状态。
- **表与正文不重复写结论**：已完结表只放"一行改动 + 归档在哪"，四要素详情只在 `docs/`；状态总表只放状态与指针，不复制待实施正文的方案描述。加了重复就一定会漂移。
- **编号用状态前缀**（2026-09-25 起）：`A` 待定（有/无方案但未拍板）/ `B` 待实施（已拍板未执行）/ `C` 待验收（已实施未验收）/ `D` 已验收 / `E` 挂起（拍板挂起），格式 `字母-MMDD-序号`（如 `A-0925-1`）；状态变化即换字母重编号，旧编号在正文标注。2026-09-25 前完结的历史条目（`P0-2`、`R3-P1-3` 等）保留原编号。

### 写法：说人话、给例子，不要堆抽象名词

- 用常见的计算机词汇（端口、进程、请求头、锁、磁盘剩余空间……），不要造抽象名词——"健壮性增强""可诊断性提升""链路的优化"这类。**抽象概念必须落回具体对象**：文件名、函数名、接口名、命令、数字。
- 一句一件事，主谓宾写清楚。禁止空壳动词："进行了…的优化""实现了…的提升""围绕…建立了…机制"。
- 能写数字就写数字：阈值、耗时、速度、行数、实测值。
- 不写过程叙述（"经过分析发现""综合考虑后"），直接给结论和证据。
- 一条 5~10 行够用；写不下通常说明还没想清楚。

同一件事的两种写法：

坏的（一堆抽象名词，读完不知道到底改了什么）：

```
针对启动阶段的端口冲突场景，建立了前置感知与可诊断性增强机制，
有效提升了异常场景下的运维体验与链路可靠性。
```

好的（具体到接口、命令、数字）：

```
- 问题：Windows 下两个进程能同时绑 5000，旧实例还在跑时新代码"改了没生效"。
- 原因：Windows 的 SO_REUSEADDR 允许重叠绑定，而启动前没做检查。
- 解决方法：启动时先连一次 127.0.0.1:5000，通则打印 netstat / taskkill 命令并 exit(1)。
- 日期：2026-09-19（d1662a6）
- 验证：占住 5000 再启动，退出码 1，提示文案正确。
```

## 常用命令

```bash
# 启动（Windows 生产 = waitress；被占用会守门拒绝启动）
.venv/Scripts/python.exe http_messages_share.py

# 语法检查（仓库无测试套件，验证以 py_compile + node --check + 接口实测为主）
.venv/Scripts/python.exe -m py_compile http_messages_share.py
# 前端逐个语法检查（13 个模块）
for f in static/js/*.js; do node --check "$f" || echo "FAIL $f"; done

# 死 CSS 核对：类选择器与 HTML/JS 引用做集合差，零命中退出码 1
.venv/Scripts/python.exe tools/check_dead_css.py

# Linux: gunicorn -c gunicorn.conf.py http_messages_share:app
```

验证/调试时**不要占用 5000**（可能有用户实例在跑），临时实例用 `python -c "from http_messages_share import app; app.run(port=5001)"` 方式起在别的端口。

## 架构与协议要点

- 分片上传协议（前端↔后端必须一致）：分片 = 裸 body POST `/api/upload/chunk?username=<u>&filename=<原文件名>`（filename 仅进日志与分片目录的 `meta.json`，绝不参与拼路径；请求头只允许 latin-1 所以中文名走 query），元数据在 `X-File-Id` / `X-Chunk-Index` 请求头；首片落盘记 INFO「上传开始」，"只有开始没有合并完成"= 中断签名；合并 POST `/api/upload/merge` 必带 `total_chunks`，后端校验分片序号 0..N-1 齐全，缺片 400 并清分片；`merge_chunks` 只认 `chunk_*`（目录里还有 meta.json）。**断点续传**：file_id 由 `FNV-1a(名|大小|lastModified)` 派生（同文件恒同 id），`GET /api/upload/status` 返回已收分片 `[{index,size}]`，前端只复用大小分毫不差的片（截断片自动重传），续传窗口即 sweep 的 24h
- **username 只能走 query/body，绝不能放请求头**（HTTP 头仅 latin-1，中文用户名会炸）
- 重名处理统一走 `exclusive_path()` + `open('xb')` 独占创建，绝不覆盖已有文件
- 哈希计算全在后台，请求线程永不整读文件：merge 顺带算 + 启动对账 + 常驻 `hash-worker` 线程（`/api/files` 每次 listdir 时把无有效记录的文件搭便车入队；`/api/file/hash` 无记录时入队并返回 `computing: true`，前端每 3s 轮询到出值为止）
- 下载：≤1GB 前端分片并行（内存约束，勿改回整文件驻留）；>1GB 走 `/api/download` 交给浏览器下载管理器（阈值 `NATIVE_DL_LIMIT`），其 ETag/Range 是断点续传依赖，勿动
- `safe_filename` / `normalize_username` 是所有入口的路径安全防线，新接口必须接入
- 留言板：`GET/POST /api/board`（username 仍走 query/body），全员一块板、`BOARD_VISIBLE = 5` 只取最近 5 条，更早的留在 `messages.db` 不删；INSERT 用 `_board_lock` 串行化，`GET ?after=<latest_id>` 命中最新返回 `unchanged: true`；删除走 `POST /api/board/delete`，`delete_message()` 在 `_board_lock` 里比对 `author == username`，不匹配 403、不存在 404（用户名是自选的，这条只是"界面上删自己的"，不是安全边界）；前端删完调 `reload()` 而不是 `load()`——删中间那条时 `latest_id` 不变，带 `after` 的请求会被判成"没变化"；留言文本与设备名只进 `textContent`（设备名过 `normalize_device`：压平空白、去控制字符、限长 24），长留言靠 `.clip-text.collapsed` 折到 10 行，`fitClamps()` 量过 `scrollHeight` 才决定显不显「展开」
- 分享链路：登录页读 `?u=<用户名>` 预填（"记住我"命中时直接自动进入、不看 query）；顶栏"二维码"按钮弹 `shareOrigin()+'/?u='+当前用户` 的离线二维码（vendor/qrcode.js 现画 SVG，无在线服务依赖）
- 存储目录锚定 `__file__`（勿改回 CWD 相对路径，会复现"/api/download 与其他接口基准分裂"）

## 约定

- git：提交前先展示变更摘要；commit message 简洁英文；未经用户明确要求不 commit/push
- 日志：落文件 + 控制台，异常必须 `log.exception` 带堆栈，禁止静默 except；对客户端只给友好文案，细节进日志
- 分片级请求日志用 DEBUG（降噪），完成/合并/中断等关键事件保持 INFO；传输测试必须记录并报告时间与速度（curl `-w` / aria2 摘要）
- 测试用一次性用户名（pytest9/pytest10 风格）并**事后清理**产生的文件与目录；`files/`、`clipboards/` 是用户数据（已 gitignore），不得移动或删除其中内容（`files/<用户名>/` 下含用户私有证书文件）
- 命名：元素 id 一律 kebab-case（HTML 惯例，2026-09-26 已把 1.0 遗留的 27 个驼峰 id 全部改掉），JS 变量保持 camelCase；改 HTML 不许漂回驼峰
- 沟通：中文回复，结论先行；改动需用户点头后才动手，先报告问题与方案
- **汇报评审 / 方案问题必须分四段**：① 问题本身（现象 + 证据，写到不懂前情也能看懂）② 原本方案（引用原话，不要转述）③ 方案问题（具体到哪一步、哪个判断、哪种时序）④ 我的想法（推荐做法 + 为什么不选另一条）。多条问题**逐条重复这四段**，不要先总述一遍再逐条点评——直接讲"方案不对"，没有上下文的用户读不懂
- **清单三块各司其职**：状态总表 = 每个编号一行（状态/重要性/详情在哪），改状态只动这一行；已完结表 = 一行一条改动指向 `docs/`；待实施正文 = 四要素写全，是未完成事项的唯一详细来源。正文与表不复述结论，否则改了正文忘改表，读表的人被误导
- 改了结论或后果描述，同一次编辑里把引用它的地方（`review-issues.md`、`README.md`、本文件、当天的归档）一并改掉

## 代码评审分级（工程权衡）

- 评审先区分【必须修复】与【低风险理论缺陷】；每项按 **触发概率 × 故障后果 × 修复带来的维护成本** 三因子评估。
- 输出分三级：**P0 必须修复 / P1 建议优化 / P2 理论风险（可接受）**；低概率、业务上不可能触发的边界 case 只单独列为 P2 报备，不要求修改。
- 禁止建议过度防御式编码：不为极小概率场景往代码里加复杂度；P2 项不顺手改。

## 平台坑（实测踩过）

- waitress 在 Windows 允许双绑同端口（SO_REUSEADDR）→ 启动守门 `check_port_in_use`，勿移除
- `threading.Timer` 不接受 `daemon` 参数；`cmd.exe` 按 GBK 解析 .bat（本项目不使用 .bat，若引入必须纯 ASCII）
- 局域网 http 无 secure context：`crypto.subtle` / StreamSaver / showSaveFilePicker 全不可用；复制用 `execCommand` 兜底；前端落盘只能靠浏览器原生下载
- `send_from_directory` 以 `app.root_path` 为基准，与其他接口的 CWD 基准曾经分裂（已修，勿回退）
- Windows 下被打开的文件删不掉，**父目录改名也不行**（Python 内置 `open()` 的句柄不带 FILE_SHARE_DELETE，`os.rename` 同样撞 WinError）——清理写入中的分片目录只能重试等句柄松手（`cleanup_chunks` 的 5×200ms 就是为此），别想用 rename 绕过（R4-P1-1 实测）
- 本机 IDM 的浏览器集成会劫持带 `Range` 的分片下载：页面侧收到它自造的 `HTTP 204`（`connection: close`、无 `Content-Range`），服务端日志仍是 206。实测 19.5KB 单分片正常、200MB 七分片必断。测前端分片下载前先关 IDM 集成
