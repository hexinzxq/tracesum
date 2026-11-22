# 迭代记录

每天 5 次，一次一件事：拿真实输入跑工具 → 找到「它说错了/没说」的地方 → 改最小的一处 → 加一条用例 → 推送并确认 CI。

## 2026-11-21 scaffold

- diff：完整的 Chrome trace 读取（`ph: "X"` 事件、tid 分组、主线程 = 最忙的线程）、shell 汇总（script/style/layout/paint + ≥50ms 长任务）、`--json`、`--serve` 本地页面、退出码 0/1/2。
- 为什么先做这四件：一份 trace 的最小问题是「多长、谁忙、忙多久、卡没卡」；这四件事不依赖浏览器也能答。
- 验证：15 个测试（load 的四种输入、summarise 的线程/长任务/分桶/跨度、CLI 退出码、HTTP 页面与 `/api/report`）；`sloplint.py` 扫页面 `clean`。

## 2026-11-21 #1 长任务要带起点

- **改了什么**：`report.build()` 的长任务多一个 `start_s` 字段（`task.start / 1e6`，三位小数）；终端每行改成 `  140.0ms  @  0.301s  Paint`，页面同步显示 `@0.301s`。新增 2 条用例（同名不同起点的两个任务必须落在不同 `start_s`；HTTP 返回里带这个字段）。
- **为什么**：真跑出来的——一份 40 个事件的 trace 里前 10 条是 `140.0ms FunctionCall` / `140.0ms Paint` / `140.0ms Layout` 反复出现，**没有时间戳时它们读起来像同一行被打印了十遍**，既分不出是两个任务，也没法回 DevTools 里定位。名字和耗时都相同是常态，起点才是身份。
- **验证**：16 个测试全过（HEAD 15）；同一份 trace 现在是 `140.0ms @ 0.065s FunctionCall`、`140.0ms @ 0.301s Paint`、`140.0ms @ 0.460s FunctionCall`，退出码不变。

## 2026-11-22 #1 主线程是 trace 说的，不是「最忙的那个」

- **改了什么**：`summarise()` 读元数据事件（`ph: "M"` && `name: "thread_name"`）里的线程名，`Thread` 多了 `name`；`Summary.main` 优先取名为 `CrRendererMain` 的线程，找不到才退回「最忙的线程」。终端头部变成 `main thread 1 (CrRendererMain) busy …`，`--json` 多了 `main_name` 与每个 thread 的 `name`，页面同步显示括号里的线程名。新增 2 条用例（元数据命名、合成线程更忙时主线程仍是 renderer main）。
- **为什么**：真跑出来的——手搓一份 4 事件 trace：`CrRendererMain` 忙 100ms、`Compositor` 忙 400ms，报告写「main thread 2 busy 400ms」。**合成线程更忙是常态**，按「最忙」选主线程等于在一类真实 profile 上把整份报告说成另一个线程。trace 自己带着线程名，不该猜。
- **验证**：18 个测试全过（HEAD 16）；同一份 trace 现在是 `main thread 1 (CrRendererMain) busy 100.0ms (25.0%)`，页面 `sloplint.py` 干净。

## 2026-11-22 #2 嵌套事件不能算两遍

- **改了什么**：新增 `trace.outermost(tasks)`——按 `(start, -dur)` 排序后只保留不被前一个区间覆盖的任务；`Thread.busy` 改为外层任务时长之和（此前把每个 `ph: "X"` 的 `dur` 都加起来）。新增 2 条用例（嵌套父 200ms + 子 100ms → busy 200ms、占比 ≤100%；两个相邻兄弟任务仍相加）。
- **为什么**：真跑出来的——`RunTask` 200ms 里套一个 `FunctionCall` 100ms，报告写 `busy 300.0ms (150.0%)`：**一个 200ms 的 trace 里线程忙了 300ms**。真实 profile 里嵌套是常态（RunTask → FunctionCall → …），这个数不是小偏差，是系统性地把主线程说成超载。
- **验证**：20 个测试全过（HEAD 18）；同一份 trace 现在 `busy 200.0ms (100.0%)`，长任务列表仍同时列出父与子（它们都是真实工作）。
