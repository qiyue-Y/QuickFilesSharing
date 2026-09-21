# AGENTS.md — QuickFilesSharing

局域网剪切板 + 大文件快传服务。单用户名隔离、无鉴权，仅限可信局域网使用。

## 布局

- `http_messages_share.py` — 后端全部（Flask + waitress/gunicorn），端口固定 5000
- `templates/index.html` — 前端全部（无框架原生 JS 单文件，内联 style/script + 内联事件风格沿用既有写法）
- `files/<用户名>/` — 用户文件；`.chunks/` 分片临时目录（启动清扫 mtime>24h）；`.hashes.json` 哈希记录
- `clipboards/` — 各用户剪切板文本
- `logs/app.log` — 运行日志（20MB×5 滚动）
- `review-issues.md` — **待实施清单**：只写还没做的事（问题、解决方案、重要性、影响评估）。**改敏感区域前先读**；一件事做完就从这里删掉、转去 `docs/` 归档
- `docs/<日期>.md` — 改动记录归档（见下节），如 `docs/2026-09-19.md`
- `README.md` — 面向使用者的说明

## 归档方法（docs/）

- **一份文件只写一天**：文件名就是日期 `docs/YYYY-MM-DD.md`，只放当天做完的改动。跨天的改动各归各天，不要合并成一份"总记录"。
- **一条记录四要素**：问题 / 原因 / 解决方法 / 日期。有实测就补一行 `验证`（跑了什么命令、拿到什么数字或结果）；改了什么就附提交号。
- **做完即移**：事情做完就从 `review-issues.md` 删掉、写进当天的归档文件；根文档只留待实施。明确否决的决定也归档（写清原因），不在根文档占条目。
- **编号沿用原清单编号**（如 `P0-2`、`R3-P1-3`），方便归档与待实施两边对照。

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
# 前端 JS 抽出后 node --check

# Linux: gunicorn -c gunicorn.conf.py http_messages_share:app
```

验证/调试时**不要占用 5000**（可能有用户实例在跑），临时实例用 `python -c "from http_messages_share import app; app.run(port=5001)"` 方式起在别的端口。

## 架构与协议要点

- 分片上传协议（前端↔后端必须一致）：分片 = 裸 body POST `/api/upload/chunk?username=<u>`，元数据在 `X-File-Id` / `X-Chunk-Index` 请求头；合并 POST `/api/upload/merge` 必带 `total_chunks`，后端校验分片序号 0..N-1 齐全，缺片 400 并清分片
- **username 只能走 query/body，绝不能放请求头**（HTTP 头仅 latin-1，中文用户名会炸）
- 重名处理统一走 `exclusive_path()` + `open('xb')` 独占创建，绝不覆盖已有文件
- 下载：≤1GB 前端分片并行（内存约束，勿改回整文件驻留）；>1GB 走 `/api/download` 交给浏览器下载管理器（阈值 `NATIVE_DL_LIMIT`），其 ETag/Range 是断点续传依赖，勿动
- `safe_filename` / `normalize_username` 是所有入口的路径安全防线，新接口必须接入
- 存储目录锚定 `__file__`（勿改回 CWD 相对路径，会复现"/api/download 与其他接口基准分裂"）

## 约定

- git：提交前先展示变更摘要；commit message 简洁英文；未经用户明确要求不 commit/push
- 日志：落文件 + 控制台，异常必须 `log.exception` 带堆栈，禁止静默 except；对客户端只给友好文案，细节进日志
- 分片级请求日志用 DEBUG（降噪），完成/合并/中断等关键事件保持 INFO；传输测试必须记录并报告时间与速度（curl `-w` / aria2 摘要）
- 测试用一次性用户名（pytest9/pytest10 风格）并**事后清理**产生的文件与目录；`files/`、`clipboards/` 是用户数据（已 gitignore），不得移动或删除其中内容（`files/<用户名>/` 下含用户私有证书文件）
- 沟通：中文回复，结论先行；改动需用户点头后才动手，先报告问题与方案
- **汇报评审 / 方案问题必须分四段**：① 问题本身（现象 + 证据，写到不懂前情也能看懂）② 原本方案（引用原话，不要转述）③ 方案问题（具体到哪一步、哪个判断、哪种时序）④ 我的想法（推荐做法 + 为什么不选另一条）。多条问题**逐条重复这四段**，不要先总述一遍再逐条点评——直接讲"方案不对"，没有上下文的用户读不懂
- **清单不维护"总表 / 摘要表"**：待实施清单按重要性排章节顺序即可，正文就是唯一事实来源。摘要表只会与正文漂移（改了正文忘改表，读表的人被误导）
- 改了结论或后果描述，同一次编辑里把引用它的地方（`review-issues.md`、`README.md`、本文件、当天的归档）一并改掉

## 平台坑（实测踩过）

- waitress 在 Windows 允许双绑同端口（SO_REUSEADDR）→ 启动守门 `check_port_in_use`，勿移除
- `threading.Timer` 不接受 `daemon` 参数；`cmd.exe` 按 GBK 解析 .bat（本项目不使用 .bat，若引入必须纯 ASCII）
- 局域网 http 无 secure context：`crypto.subtle` / StreamSaver / showSaveFilePicker 全不可用；复制用 `execCommand` 兜底；前端落盘只能靠浏览器原生下载
- `send_from_directory` 以 `app.root_path` 为基准，与其他接口的 CWD 基准曾经分裂（已修，勿回退）
