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
