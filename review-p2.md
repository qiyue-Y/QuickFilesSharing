# P2 报备清单（理论风险，按工程权衡原则不修）

> 分级规矩见 `AGENTS.md`「代码评审分级（工程权衡）」：本文件只收 **触发概率×后果×修复成本** 评估后判定"可接受"的项。
> 处置约定：不主动修；若将来因别的改动路过某条，可用零新增复杂度的方式顺带消除，届时在对应归档里记一笔并从本文件删除。

## P2-1 confirmDialog 重入时序（登记于 2026-09-26 二轮评审）

- 现象：`static/js/ui.js` `confirmDialog()` 里 `confirmResolve = resolve` 赋在 `openModal(...)` 之前。若确认框已开时再调一次：`openModal→closeModal→cb()` 会把**刚写入的新 resolve** settle 成 false，旧调用方的 Promise 永远悬空；且 `modalLocked=true` 时 `closeModal` 早退，但 `openModal` 照样覆盖 `openMask` 并把锁置回 false。
- 触发概率：现状 0——唯一调用点 `files.js removeFile` 不 await 结果，modal 遮罩挡住二次触发。
- 若将来要修：把 `openModal` 挪到 resolve 赋值之前即可（纯调序，不加任何新逻辑）。

## P2-2 shareOrigin 失败路径的缓存行为（登记于 2026-09-26 二轮评审）

- 现象：`static/js/api.js` TTL 缓存取 IP 失败时 `addr.at` 不更新 → 缓存永久过期，此后每次调用各吃一个 `/api/server-addr` RTT；页面加载即并发 4 个调用点时无 in-flight 合并，会同时发多份请求。
- 触发概率：仅接口异常时；后果：毫秒级本地请求变慢，功能有 origin 兜底不受损。
- 不修理由：缓存 promise 做 in-flight 合并属为极小概率场景加复杂度。

## P2-3 形状重复与命名口味（登记于 2026-09-26 二轮评审）

- `createGeneration()` 暴露的 `is(g)` 读起来不像谓词；files.js 里同概念两个名字（`hashReq` / `verifyGen`）。
- 三个弹窗的 "close 按钮 addEventListener + closeOnBackdrop" 接线同形；`files.js showVerify` 三个 `if (state === ...)`。
- modal-close 内联 SVG 三处逐字符相同——已在 C-0926-4 按仓库"三行相似好过过早抽象"标准豁免。
- 不修理由：均为改名/抽象口味级，AGENTS.md 明文反对过早抽象。

## P2-4 分片目录内出现畸形 `chunk_*` 文件的两种处置（登记于 2026-09-28 三轮评审，5001 实测）

- 现象：向 `files/p2probe/.chunks/<file_id>/` 手工放置 `chunk_`、`chunk_abc` 后——
  - `GET /api/upload/status`：200，`received` 只含合法片（`chunk_0`），两条畸形文件被 `except: continue` 静默过滤，服务端日志零 warning。
  - `POST /api/upload/merge`（total_chunks=2，另放一个比正常片更大的 `chunk_` 以骗过齐全性校验）：400，错误文案是 Python 原始异常 `invalid literal for int() with base 10: ''`（不是项目自己的友好文案），分片目录被整体删除（含 2 个完全正常的分片）。日志有 `WARNING 合并被拒(分片不齐)` 带原因。
- 触发概率：正常前端操作为 0——分片由页面 PUT 到 `/api/upload/chunk`，文件名恒为 `chunk_<整数>`，且合并前会先查 status 只补缺片。要造出畸形文件需要第三方客户端乱发序号，或人工往目录里扔文件。
- 后果：最坏是"这次上传作废、从头重传"，不丢已落盘的用户数据（分片目录是该 file_id 独有的）。
- 不修理由：status 侧过滤是设计行为（多一层兜底而非报错）；merge 侧回显内部异常文案只是不友好，细节已按约定进日志。按分级规矩登记，不主动修。
