# 浪漫主义云海 · 执行升级稿

对 `demo-v2/浪漫主义云海/index.html`（902 行）做「保留艺术方向的执行升级」。
艺术方向（弗里德里希云海、光之岛、传输光柱、山巅铭牌、衬线/楷体、乳白/暖金/灰蓝/远山黛/朝霞玫）
全部保留，假数据完全一致（同 8 文件、同 2 路传输、同 4 条剪切板），两版可直接对比。

## Design Read（skill 0.B）

> Reading this as: redesign-preserve of a LAN file/clipboard transfer tool page,
> with a Friedrich-romanticism cloud-sea brand language, leaning toward
> native single-file CSS + serif/kai typography + restrained atmospheric motion.

三旋钮（skill 11.A "redesign - preserve"：VARIANCE 沿用原稿、MOTION +1、DENSITY 沿用）：

- `DESIGN_VARIANCE: 7` - 原稿即非对称 7/5 两栏 + 手绘感光岛 + 绘画性天空，沿用
- `MOTION_INTENSITY: 5` - 原稿约 4（云带视差 + 漂浮 + 光柱流动），preserve +1；连续动效按任务约束
  收在「幅度 ≤±5px、周期 ≥8s」以内，不追 8+ 的编排
- `VISUAL_DENSITY: 5` - 工具页日常密度（剪切板 + 8 文件 + 2 传输行），沿用

技术栈锁定：原生单文件 HTML，零外部资源，file:// 直开。skill 的 React/Tailwind/Motion/
图标库/图片生成路径全部不适用（离线局域网），图形只用 CSS/SVG。

## 一、v2 审计记录（skill 11.B）

### 字号体系现状（v2）
无 token，13 种裸字号散落：46 / 34 / 24 / 15 / 14 / 13.5 / 13 / 12.5 / 12 / 11.5 / 11 / 10.5。
**低于 12px 的 4 处**：note-head 11.5、f-meta 11.5、tr-dir 11、f-ext 10.5。
行高仅 3 处显式声明，其余默认。letter-spacing 加在大量中文正文与元信息上（.58em/.3em/.22em 等 14 处）。
tabular-nums 只覆盖传输大数字与速度，文件尺寸、时间戳、铭牌数据均未覆盖。

### 逐色 WCAG 对比度（v2，实测计算）
背景取值：岛面（isle 渐变近白，L≈0.977）、铭牌区天空（含晨光罩，最亮 L≈0.846）、
中段天空 #eee4d4（L≈0.784）、底部天空 #97a3b2（L≈0.360）。

| v2 用色 | 用途 | 背景 | 对比度 | 判定 |
|---|---|---|---|---|
| #3f4a5d ink | 标题 | 岛面 | 8.7:1 | 过 |
| #43506a | 正文 | 岛面 | 7.9:1 | 过 |
| #98a1ae faint | note-head/f-meta/sec-sub 11.5px | 岛面 | 2.55:1 | **败** |
| #c9929c rose | plaque-sub 13px | 晨光天空 | 2.2:1 | **败** |
| #5c6d82 slate | plaque-meta 13px | 晨光天空 | 4.5:1 | 临界 |
| #6e7889 ink-soft | tr-speed 12.5px | 岛面 | 4.36:1 | **败** |
| #a5884f | f-ext 10.5px / tr-dir 11px | 岛面 | 3.3:1 | **败** |
| #71809a | word-btn 12.5px | 岛面 | 3.91:1 | **败** |
| #9aa4b0 | settled 速度 | 岛面 | 2.47:1 | **败** |
| #a9b1bd | 输入占位 | 岛面 | 2.13:1 | **败** |
| #b98a3e | word-btn 悬停 / settled 大数 | 岛面 | 3.03:1 | 悬停败（小字）/ 大数临界过 |
| #8b95a5 | colophon 12px | 底部天空 | **1.18:1** | **严重败**（近乎不可见） |
| #8a6a2f | demo-btn 13px | 按钮金底 | ~4.3:1 | 临界偏败 |

结论：**晨光亮区与底部深空两头失守**。奶油/暖金系文字在亮天空上普遍不过线。

### 圆角清单（v2，7 处）
isle 有机八值 `20px 26px 22px 28px / 24px 20px 28px 22px`、seal 3px、f-ext 3px、
demo-btn 999px、toast 10px、dot 50%、（f-acts 无）。共 6 档并存，无规则。

### 动效清单（v2，逐条动机）
| 动画 | 参数 | 动机判定 |
|---|---|---|
| cloudDrift 六层云带 | 190s-62s translateX | 有：视差纵深，云海的语言本体 |
| sunray breathe | 20s opacity | 有：晨光呼吸，静中有生气 |
| dot pulse | 4s opacity | 有：在线状态指示（语义） |
| drift 岛漂浮 | ±5px、9-14s alternate | 有：光之岛悬于云上的失重感 |
| beam flow | 7s 纹理位移 | 有：指示传输方向 |
| arrive flash | 1.4s 亮度脉冲 | 有：完成反馈 |
| tr-card fade | 0.8s 退场 | 有：状态移除 |
| beam 高度过渡 | 0.6s linear | 有：进度连续感 |
| **prefers-reduced-motion** | **0 处** | **缺失，必须补** |

### AI Tells 扫描（v2）
- em-dash / en-dash：无
- 中点：页脚一行 3 个（超限）；文件行/传输行以「名称 · 尺寸」点串混排
- 装饰状态点：仅「在线」一枚，语义成立，保留
- 印章「云海」：铭牌品牌印记，中文铭牌惯例，判定为品牌件非 AI Tell，保留（补 aria-hidden）
- 版本标签：无
- 文案：「上垂于天 · 下落于岛」语法别扭（读不出谁是主语），需改

### 其他基线确认
- focus 态仅 input 一处；按钮无 focus-visible、无 :active
- 楷体栈 `"Kaiti SC", STKaiti, KaiTi, ...`：本机 `C:/Windows/Fonts` 实测存在
  simkai.ttf（KaiTi）与 STKAITI.TTF，Windows 可用；栈尾已挂 SimSun/Noto Serif 回退
- 无图标式按钮（全部文字按钮），aria-label 需求仅在输入框

## 二、升级清单（对应 skill 条目）

### 1. 排版体系（skill 4.1 / 任务 1）
- 建立七档字号 token：46(h1) / 34(传输大数) / 24(h2) / 15(传输文件名) / 14(正文) / 13(铭牌小字/按钮/toast) / 12(元信息)
- 最小字号 12px：note-head 11.5→12、f-meta 11.5→12、tr-dir 11→12、f-ext 10.5→12
- 行高体系：h1 1.25 / h2 1.4 / 大数 1.1 / 正文 1.75 / 元信息 1.5-1.6
- `font-variant-numeric: tabular-nums` 覆盖全部数据数字：文件尺寸、时间戳、速度、
  传输百分比、note-head 时间、铭牌 IP/磁盘
- 中文 letter-spacing 只留铭牌两处（h1 .22em、plaque-sub .58em→.4em）与拉丁扩展名 chip（.16em），
  其余 12 处全部清零
- 楷体收窄到 h1 / h2 / 印章；正文统一衬线栈（Georgia + SimSun + Noto Serif CJK 回退）

### 2. 色彩对比锁（skill 4.2 / 4.5 / 任务 2）
新增文字色 token 并逐色实测（判定标准：正文 ≥4.5:1，≥24px 大字 ≥3:1）：

| token | 值 | 用途 | 实测 |
|---|---|---|---|
| --ink #3f4a5d | 保留 | 标题/大数 | 岛面 8.7:1 |
| --body #43506a | 保留 | 正文 | 岛面 7.9:1 |
| --mist #5a6779 | 新 | 次要文字（时间/速度/副题/按钮基色） | 岛面 5.6:1，中段天空 4.6:1 |
| --plaque #4e5c6e | 新 | 铭牌小字 | 晨光天空 6.0:1 |
| --rose-deep #8a5a64 | 新 | 铭副题/印章底/下载向标签 | 晨光最亮区 4.8:1 |
| --gold-text #7d5f27 | 新 | 扩展名/方向标签/按钮字/悬停 | 岛面 4.5:1，按钮金底 5.0:1 |
| --gold-num #9c7530 | 新 | 完成态大数字（34px 大字） | 岛面 4.1:1 ≥3:1 过 |
| --danger #7d5058 | 新 | 删除悬停 | 岛面 6.5:1 |
| --deep #28303f | 新 | 页脚（压深色天空） | 底部天空 5.2:1 |
| --ph #67717f | 新 | 输入占位 | 岛面 4.8:1 |

处理原则：**加深文字，不动天空**。晨光氛围（渐变、云带、sunray）原样保留；
#dcb67f 暖金降级为纯装饰色（描边/光晕/印章点），不再承担小字。
v2 中 8 个不过线的文字色全部替换，0 个遗留。

### 3. 形状锁（skill 4.4 / 任务 3）
三档圆角全页贯彻，CSS token 化：
- `--r-card: 18px` - 所有光之岛卡片（剪切板面板、文件卡、传输卡）
- `--r-chip: 8px` - 小件（扩展名 chip、印章、toast）
- `--r-pill: 999px` - 主行动按钮（发送、演示传输）
- 状态点 50% 正圆属于形状而非圆角档
isle 原八值有机圆角收敛为统一 18px（柔和光晕系下 18px 保持软感，牺牲手绘感换取一致性）。

### 4. 交互态（skill 4.5 / 任务 4）
- hover 反馈保留（word-btn 金色亮起、demo-btn 光晕增强）
- 新增 `:active`：word-btn `translateY(1px)`、demo-btn `scale(.98)` 物理按压
- 新增全局 `:focus-visible`：2px #b98a3e 暖金焦点环 + 2px offset，融入晨光语言（键盘导航可见）
- 输入框补 `aria-label="新剪切板内容"`（placeholder 不充当 label，skill 4.6）
- 印章、状态点、天空、光柱层补 `aria-hidden="true"`
- 图标式按钮：本稿无（全文字按钮），无需 aria-label

### 5. 动效审计（skill 5 MOTION MUST BE MOTIVATED / 6.B / 任务 5）
每条动画一句话动机（写在 CSS 注释里）：
- 云带视差：纵深，云海语言本体
- 晨光呼吸：静态天空的呼吸感
- 状态点 pulse：在线语义
- 岛漂浮 ±5px：失重感；全部周期 9-14s alternate（完整周期 18-28s），满足 ≤±5px / ≥8s
- 光柱 flow：传输方向
- arrive flash：完成反馈
- 退场 fade：状态移除
- 无「说不清动机」的动画，无新增无动机动画
- **新增 `@media (prefers-reduced-motion: reduce)` 全量兜底**：云带/晨光/漂浮/光柱流动/
  完成脉冲全部静止，光柱退化为静态渐变（长度仍随进度更新），进度条与光柱高度直接跳变

### 6. 数据排版（skill 4.9 / 任务 6）
- 文件卡三行改列对齐：首行扩展名（左）+ 尺寸（右，tabular-nums）；中行文件名；
  末行时间（左）+ 操作（右）。点串「38.4GB · 昨日 23:41」拆为两个对齐字段
- 传输卡：方向（左）+ 尺寸（右）；文件名单独一行；大百分比（左）+ 速度（右）基线对齐；
  文件名不再内嵌「· 21.7GB」
- 中点密度：全文件逐行 ≤1 个（页脚拆两行：「云在山巅，光在途中」+「仅限可信局域网 · 静态设计稿，未接后端」）

### 7. 文案自查（skill 4.9 COPY SELF-AUDIT / 9.F / 任务 7）
- 「上垂于天 · 下落于岛」→「光垂落，是上传；光收拢，是下载」（原句语法不通，新句解释了光柱隐喻）
- fileAct toast「静态演示 · 「x」的下载操作未连接后端」→「静态演示：「x」的下载操作未连接后端」（中点换冒号）
- 其余品牌语（「已送上云海」「一道晨光落下」等）语法人称通顺，按 skill 11.C 保留原声
- 可见文本 0 个 em-dash / en-dash（grep 实证）
- 页面标题保持「消息快传 · 浪漫主义云海」，界面无版本字样

### 8. 性能（skill 6.A / 6.E / 任务 8）
- 云带视差只动 `transform: translateX`，六层均为合成器动画
- 光柱 `blur(13px)` 单元素承担，内部流动是子元素 transform 位移，不重复滤镜
- 远山三层 SVG 纯静态
- 无滚动监听动画（scroll listener 仅用于光柱几何重算，passive）

## 三、自检结果

1. `<script>` 抽出跑 `node --check`：**通过**（临时文件已删）
2. grep 外部引用：**0 处** http:// / https://（剪切板示例直链以 `&#58;` 转义呈现，是演示数据非资源引用）；
   em-dash / en-dash：**0 处**；可见文本「v2」：**0 处**；单行双中点：**0 处**；<12px 字号：**0 处**
3. 文件行数：index.html **1024 行**（v2 为 902 行，增量来自数据行列对齐结构与 reduced-motion/焦点环规则）

## 四、Pre-Flight 摘录（skill 14，产品工具页适用项）

- Design Read 已声明；三旋钮已给理由（preserve 模式）
- 主题锁：全页单主题（晨光天空），无中段反转
- 色彩锁：暖金一个强调色贯穿（描边/光晕/焦点环/按钮）
- 形状锁：三档圆角，全页 0 例外
- 按钮对比：发送/演示传输金底深棕字 5.0:1 过
- 表单对比：占位 4.8:1、焦点下划线 + 焦点环双重可见
- 每条动画有动机；reduced-motion 全量兜底
- 无滚动提示、无版本脚标、无 section 编号眉题、无装饰性照片题注
- landing 专项（hero 视口纪律、logo wall、CTA 查重、marquee）按语境裁定不适用
