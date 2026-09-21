# 前端重构 spec — 睡莲池皮肤 + 无构建模块拆分

- 状态：**待审核**，未获批准前不改任何代码。
- 定稿依据：`<HOME>\Desktop\QFS · 睡莲池.zip` → `pages/QFS · 睡莲池.html`（1492 行），资产在 `qfs-waterlilies/assets/`（2 张 jpg + 3 个 woff2）。
- 现状：`templates/index.html` 1333 行 = CSS 455 行(8~463) + HTML 78 行(465~543) + JS 787 行(544~1331)，30 个函数、13 个接口。
- 路线：**Flask `static/` + 原生 ES Module，无构建、无框架**。部署命令不变（`.venv/Scripts/python.exe http_messages_share.py`）。

## 0. 用户已定的四条决定（2026-09-21）

| # | 决定 | 本 spec 的处理 |
|---|---|---|
| D1 | 剪切板要做成多条消息流，但**先放下来**，等其余任务跑通后重构后端 | 本次只做单条文本的皮肤（后端 `/api/clipboard` 仍是每人一条 `content`）。边界见 §5，后端改动另开条目 |
| D2 | 同意同一时刻只允许一个传输 | 行内进度条，非活跃行按钮置灰。闸门实现见 §6 |
| D3 | 登录页设计稿用户稍后提供 | 登录区留**占位契约**（§7）：DOM 与 `login.js` 接口先定，稿子到了只换标记和 CSS，JS 不动 |
| D4 | 哈希弹窗由我设计同款风格 | 规格见 §4.3 |

## 1. 非目标（明确不做）

- 剪切板消息流、任何后端协议改动（除 §8 那一行缓存头）。
- 放开多传输并发。`templates/index.html:546` 的注释记录过事故：三个全局单例被并发传输互相覆盖，"上传中点下载再点取消"拿残留 `file_id` 误删正在上传的分片。
- 剪切板自动轮询（现在靠手点"刷新"，加轮询属新需求）。
- 候选改进清单里的一键校验、`?u=` 分享链接、断点续传。
- 引入 Tailwind、lucide、任何 npm 依赖或构建步骤。

## 2. 目录与文件划分

```
static/
  img/monet-pond.jpg          1.08 MB   背景，从 qfs-waterlilies/assets 复制
  img/monet-lilies.jpg        1.69 MB   画廊图（显示宽 ≤236px，压缩留作后续）
  fonts/space-grotesk-latin.woff2        22 KB
  fonts/space-grotesk-latin-ext.woff2    19 KB
  fonts/cormorant-garamond-latin.woff2   38 KB
  css/tokens.css        ~95 行   色板 / 字体栈 / @font-face
  css/pond.css         ~140 行   背景层、粒子、QFS 标题渐变、reveal
  css/ui.css           ~420 行   topbar/hero/panel/qbtn/fcell/clip/modal/toast/媒体查询/reduced-motion
  js/api.js            ~90 行    13 个接口封装 + 传输常量
  js/format.js         ~60 行    formatSize/Speed/Time/escapeHtml/fileIcon
  js/ui.js             ~70 行    toast、status、弹窗通用开关
  js/progress.js      ~150 行    行内 .fprog 渲染（原 makeProgressUI 的后继）
  js/transfer.js       ~60 行    单传输闸门 + 取消
  js/upload.js        ~210 行    分片 4 路并行 + 磁盘预检 + 批量队列
  js/download.js      ~180 行    ≤1GB 分片 / >1GB 原生
  js/files.js         ~160 行    列表渲染、删除、哈希弹窗内容
  js/clipboard.js      ~90 行    保存/复制/刷新/清空
  js/hud.js           ~110 行    IP 复制、磁盘剩余、用户切换弹层
  js/login.js         ~70 行     登录门 + 记住我 + autoLogin（占位，见 §7）
  js/main.js           ~50 行    import 各模块 + 初始化顺序
templates/index.html  ~180 行    骨架
```

后端 `http_messages_share.py` 只改 §8 那一行。`@app.route('/')` 的 `render_template('index.html')` 不动，Flask 默认 `static_folder='static'` 自动生效。

## 3. 模块约定

- `<script type="module" src="/static/js/main.js?v=1">`。module 天然 defer，DOM 就绪后才执行，现有"底部脚本直接 getElementById"的写法可以照搬。
- 状态不放全局：`currentUsername` 收进 `js/state.js`？不——只有 `login.js`/`hud.js` 需要，改为 `main.js` 持有并作为参数注入，避免再多一个文件。各模块签名统一形如 `init(ctx)`，`ctx = { getUsername, setStatus, refreshFiles }`。
- **内联事件全部去掉**（`onclick="..."` → 各模块自己 `addEventListener`，列表行用事件委托）。原因：module 作用域里的函数不在 `window` 上，内联 handler 直接找不到函数。这条与 `AGENTS.md` 现有约定"内联事件风格沿用既有写法"冲突，因此 §9 要同步改 `AGENTS.md`。
- 安全线保持：文件名一律 `data-filename` + `textContent`，不拼进 innerHTML 字符串（`index.html:1128` 注释里的既有做法）。`username` 只走 query/body，绝不进请求头。

## 4. 皮肤落地：设计稿 → 新 DOM

### 4.1 逐区块映射

| 设计稿区块 | 处理 |
|---|---|
| `.bg-layer`（背景图 + 雾 + 暗角 + 10 粒子） | 原样保留，`src` 改 `/static/img/monet-pond.jpg`，两张 `<img>` 补 `width`/`height` 属性防 CLS |
| `.topbar .brand` | 原样 |
| `#ip-copy` 里写死的 `198.51.100.7:5000` | 换成 `location.host`；复制逻辑沿用 `navigator.clipboard` + `fallbackCopy` 兜底（局域网 http 非安全上下文，`execCommand` 是唯一稳的） |
| "磁盘剩余 370 GB" | 接 `/api/disk`，`free < 10GB` 时加 `.low`（`--water-rose`）；请求失败整块隐藏，不挡页面 |
| `.user-avatar` / `.user-pop` 弹层 | 内容换成"切换用户 / 记住我复选框 / 退出登录"三项，视觉不动 |
| `.hero`（eyebrow + QFS 渐变字 + 副标题 + 画廊） | 原样。**删掉** `.title-block` 上的内联 `style="width:530px;height:287.719px"`——那是设计工具导出的残留，删后由 CSS 自然撑开，P0 截图核对不塌版 |
| `#files-panel .panel-head` | 右侧"演示上传"按钮 → 换成 `<label class="qbtn primary">上传文件<input type="file" id="fileInput" multiple hidden>`；拖放区从现有 `#dropZone` 扩大到整个 `#files-panel`，`.dragover` 态用 `--gold-glint` 描边 |
| `.fcell` 文件行（示例数据 200 行） | 全部删除，改由 `files.js` 按 `/api/files` 渲染。结构保留 `.frow/.ftype/.fmeta/.fname/.fsub/.factions/.fprog`；`.fsub` = `{size} · {mtime} · SHA-256: ab12cd34ef56…`（哈希段可点，开弹窗）；`.factions` = 下载 + 删除 |
| 图标 | 设计稿 5 个内联 SVG（archive/film/file-text/image/music）作基底，`format.js` 的 `fileIcon()` 把现有 40 项扩展名→SVG 名映射接上；无匹配用 `file-text`。emoji 全部退役 |
| `#clip-panel .clip-list`（3 条假消息） | 删除。面板内改放 `#clipboardContent` textarea（沿用 `.clip-text.mono` 观感，多行、`min-height:180px`）+ 一行按钮 `保存 / 复制 / 刷新 / 清空 / 退出`（`.qbtn`）。`.sendrow` + `#clip-input` 那套单行输入不采用——它是消息流的形态，留给 D1 后续 |
| `.footer`"静态设计稿 · 无后端，双击即看" | 改为"QuickFilesSharing · 局域网剪切板与文件快传 · 服务端时间/版本"。原文案是假的，不能上线 |

### 4.2 传输态视觉（新增，设计稿只有假数据）

- 活跃行加 `.transferring`，进度由真实已传字节驱动：`.fp-fill{width}` ← `totalLoaded/totalSize`，`.fp-pct-num` 保留一位小数，`.fp-spd` 用 8 窗口滑动平均（现有 `makeProgressUI` 的算法平移），`.fp-rem` = `formatTime(ETA)`，末段固定"4 路并行"。
- 完成：加 `.is-done`，点换成 `CHECK_SVG`，`.fp-meta` 显示"完成 · 平均 X MB/s · 用时 Y"，2.6s 后 `resetProg`（沿用设计稿这个时长）。
- 删除：`.gone` 淡出 0.7s 后移除节点。
- 上传中的新文件：先插入临时 `.fcell`（fname + 大小 + "即将入池"），合并成功后 `loadFiles()` 整表刷新，临时行随之替换。

### 4.3 弹窗规格（D4，我设计）

复用既有 token，不新造颜色：

- 遮罩：`position:fixed; inset:0; z-index:40; background:rgba(6,16,20,.62); backdrop-filter:blur(6px)`。
- 盒体：`width:min(660px,92vw); max-height:82vh; overflow:auto`，背景 `--paper-translucent-strong`，`border:1px solid var(--hairline)`，`border-radius:var(--qfs-radius-lg)`，`box-shadow:0 30px 70px -24px rgba(0,0,0,.7)`，内边距 26px。
- 标题行：左标题用 `.panel h2` 同款（`--qfs-font-serif` 17px / `.26em` / `--gold-glint`），右 `×` 关闭按钮（`.qbtn.sm`，`aria-label="关闭"`）。
- 哈希输入框：只读、`--qfs-font-mono` 12.5px、`user-select:all`、`background:var(--pond-deep)`、`border-radius:var(--qfs-radius-md)`。
- 命令行：沿用现有 `.verify-row` 结构，`code` 底色 `--pond-deep`、1px `--hairline`、`radius 8px`；"复制"按钮换成 `.qbtn.sm`。
- 分节标题两块不变：「在接收端本机校验」4 条 certutil/sha256sum 命令 +「命令行下载」4 条 curl/aria2 命令。
- 动效：`opacity 0→1`、`translateY(12px) scale(.98)→none`、`.28s cubic-bezier(.22,1,.36,1)`，与 `.user-pop` 同曲线。
- 交互：ESC 关、点遮罩关、焦点陷阱（Tab 在盒内循环）、打开时 focus 哈希框（保留现有"全选 + execCommand 复制"行为）、关闭时焦点还给触发按钮、`body{overflow:hidden}` 锁背景滚动。
- a11y：`role="dialog" aria-modal="true" aria-labelledby`。
- `prefers-reduced-motion` 下无动画（全局规则已覆盖）。

### 4.4 toast（新增，设计稿没有任何状态提示区）

现有 6 处 `showStatus`/`uploadStatus` 反馈必须有家：`#toast` 固定底部居中，`--paper-translucent-strong` + `--hairline` + `radius 999px`，左侧 3px 色条分三态——成功 `--lily-sage`、警示 `--gold-glint`、错误 `--water-rose`。最多堆 3 条，3s 自动消失，容器 `aria-live="polite"`。`uploadStatus` 那些内联 `style.cssText` 一并换成 `showStatus(msg, type)`。

## 5. 剪切板：本次形态与将来边界

- 本次：单条 `content`，读写走现有 `GET/POST /api/clipboard`，行为与今天完全一致（保存覆盖、清空=存空串、退出只隐藏面板）。
- 为 D1 预留：`clipboard.js` 只导出 `init(ctx)` 与内部 `render(data)`，DOM 根是 `#clip-panel .clip-body`。将来消息流只需换 `render` + 新增 `POST /api/clipboard/append`，不触碰其他模块。
- 建议 D1 的后端形状（**只写在这里，不实施**）：`clipboards/<user>.json` 存 `[{text, device, ts}]` 上限 200 条 + `GET /api/clipboard?after=<ts>` 增量拉取。设备名客户端从 UA 取一次存 localStorage，避免加字段。

## 6. 单传输闸门（D2）

`js/transfer.js` 导出 `acquire(kind) → token | null`、`release(token)`、`cancelActive()`、`onActiveChange(cb)`：

- 一次只存一个 active token，`acquire` 失败即返回 `null`，调用方给 toast「已有传输进行中，请等它完成或点"取消"」。批量上传队列在文件间隙再 `acquire`，抢不到就停下——现有 `err.busy` 语义原样保留。
- token 携带自己的 `xhrs[] / cancelled / fileId / timer`，**所有清理都以 token 为准**，绝不引用全局句柄（这是 546 行注释那次事故的根因）。
- 取消按钮位置：设计稿没有全局取消栏，改为**活跃行 `.fp-meta` 行尾一个 `.qbtn.sm.danger`「取消」**，只在 `onActiveChange` 时插入/移除。语义等价，且天然不会出现"按钮在但传输已结束"的残留态。
- `beforeunload`：有 active 传输时提示确认（现有代码没有，成本低，值得加）。

## 7. 登录区占位契约（D3）

- `templates/index.html` 里独立 `<section id="login-gate">…</section>`，未登录时它是唯一可见主体（`.page > .grid2` 与 `.hero` 加 `hidden`），登录后反过来。
- 现版本先放**最简占位**：一个 `.panel` 卡，内含 `#usernameInput`(`.pop-input` 样式) + 「登录」(`.qbtn.primary`) + `#rememberUser` 复选框 + 「清除记住的用户」。视觉上全部来自已有组件，不出新样式，等设计稿来了整块替换。
- `js/login.js` 契约固定：`init(ctx)` 内部只管这三个元素 + `Enter` 提交 + `autoLogin()`；对外只经 `ctx.setUsername(name)`。**换设计稿时 JS 零改动**，只动 `<section>` 内容和 `.login-*` CSS。

## 8. 后端唯一改动：静态资源缓存头

- 问题：`_request_end`（`http_messages_share.py:443`）只给 `/` 加 `no-cache`、`/api/*` 加 `no-store`，`/static/*` 没有 `Cache-Control`，浏览器按启发式缓存——换皮肤后用户可能仍加载到旧 `js/*.js`，出现"改了没生效"。
- 改法：`http_messages_share.py:453` 的条件并上 `or request.path.startswith("/static/")`，仍走 `no-cache`（带 ETag 回源校验，局域网一次往返 ~1ms，`send_from_directory` 本来就发 ETag）。`/api/download*` 的 ETag/Range 分支不受影响。
- 验证：`curl -sI http://127.0.0.1:5001/static/js/main.js | grep -i cache-control` 期望 `no-cache`。

## 9. 文档同批改（AGENTS.md 要求一次编辑内改完）

- `AGENTS.md` 布局节：`templates/index.html — 前端全部（无框架原生 JS 单文件…）` → 改为骨架 + `static/css` 三份 + `static/js` 十一份的无构建 ESM 描述，删掉"内联事件风格沿用既有写法"，换成"事件在模块内 `addEventListener`，列表行用委托"。
- 常用命令节：`node --check` 那句改成逐个校验 `static/js/*.js`。
- `review-issues.md`：新增一条 `UI-D1 剪切板消息流（后端待重构）`，把 §5 的建议形状搬过去。
- 做完当天写 `docs/<日期>.md`，按四要素（问题/原因/解决方法/验证）记录，本 spec 文件归档进 `docs/`。

## 10. 实施顺序与每步验证

| 阶段 | 内容 | 验证 |
|---|---|---|
| P0 | 建 `static/`、复制资产、三份 CSS、`index.html` 骨架、§8 缓存头 | `py_compile` 过；`app.run(port=5001)` 起临时实例，浏览器看背景/标题/双栏排版，桌面 1280 + 移动 390 截图 |
| P1 | `api.js`/`format.js`/`ui.js`/`hud.js` | 逐个 `node --check`；页面顶栏 IP、磁盘剩余、复制、用户弹层四项可点可用；控制台零报错 |
| P2 | `files.js` + 删除 + §4.3 弹窗 | 一次性用户 `pytest9` 放 2 个文件（含中文名），列表渲染、空态、删除确认、弹窗四段命令、ESC/遮罩关闭、长文件名省略号；特殊字符名 `<img src=x onerror=1>.txt` 验证不执行 |
| P3 | `progress.js`/`transfer.js`/`upload.js`/`download.js`（最高风险） | 上传 500MB（4 路并行 + 合并 + 磁盘预检路径）、下载同一文件（分片路径）、>1GB 走原生下载、传输中点"取消"→ 后端 `abort` 日志 + `.chunks/` 清空、传输中点另一行下载被闸门拦下、批量 3 文件混合成功失败 |
| P4 | `clipboard.js` + `login.js` 占位 | 保存/复制/刷新/清空/退出、记住我 + 刷新后 `autoLogin`、换用户名后列表切换 |
| P5 | 收尾 | 全文 `node --check`、`py_compile`、清理 `files/pytest9/`、`clipboards/pytest9*`、`logs` 无 ERROR、两档截图给你过一遍、§9 文档改动 |

P3 单独成一阶段：协议（裸 body + `X-File-Id`/`X-Chunk-Index` + `merge` 必带 `total_chunks`）一个字都不改，纯搬迁 UI 绑定，出问题好定位。

## 11. 风险与回滚

1. **传输逻辑搬迁引入回归**——最现实的坑。缓解：逐函数平移不改算法、P3 独立验证、大文件实测必须有数字（时间 + 速度），按 `AGENTS.md` 要求记录并报告。
2. **ESM 需要 2020 年后的浏览器**（IE 与旧 Edge 不支持 `type="module"`）。**假设：所有访问端是现代 Chrome/Edge/Firefox。若局域网里有 Win7/老浏览器设备，本方案不成立，需回退到"多份普通 `<script>` + 全局命名空间"的拆分**，其余 spec 内容不变。这一条请在审核时确认。
3. 首屏 2.77 MB 图片：局域网内 ~1s 内可接受，`monet-lilies.jpg` 压缩留作后续小项。
4. 背景 `pondDrift` + 10 粒子常驻动画：低端机上可能吃 GPU。`prefers-reduced-motion` 已有兜底，若实测卡顿再考虑关掉动画。
5. 回滚：全部改动在 git 工作区，`git checkout -- templates http_messages_share.py && rm -rf static` 即回到现版本，旧 `index.html` 一行未动地留在 HEAD。

## 12. 审核点（请逐条给个行或不行）

- [ ] §3 去掉内联 `onclick`（改 `AGENTS.md` 约定）
- [ ] §4.1 `.footer` 文案换掉、`.title-block` 内联尺寸删掉
- [ ] §4.4 新增 toast 组件承载 6 处状态反馈
- [ ] §6 取消按钮从全局栏改为活跃行行内
- [ ] §8 改后端一行缓存头
- [ ] §11.2 访问端浏览器均为现代内核
- [ ] §10 分五阶段、P3 单独验证
