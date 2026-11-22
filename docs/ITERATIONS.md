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

## 2026-11-22 #3 分项只统计主线程，且不重复计同一件事

- **改了什么**：`summarise()` 先算出主线程（`CrRendererMain`，没有就用最忙的），script/style/layout/paint 四个分项只由**该线程**的任务累加；`layout_us` 只算 `Layout`，`style_us` 只算 `UpdateLayoutTree`（原来 `layout` 把两者都加进来，同一段 100ms 在 style 与 layout 里各出现一次）。顺手修 `1 passes` 的单复数。新增 1 条用例（worker 的 500ms Layout 不进主线程的 layout 总计），并把原来断言 30ms 的用例改成 20+10。
- **为什么**：真跑出来的——`UpdateLayoutTree` 100ms、主线程 `Layout` 200ms、worker `Layout` 500ms 的 trace，报告写 `layout 800.0ms in 2 passes`，而同一行上面写着主线程只忙 300ms：**分项之和比主线程总时长还大，且包含一个跟主线程无关的线程**。分项是给人看「时间去哪了」的，不是独立计数器。
- **验证**：21 个测试全过（HEAD 20）；同一份 trace 现在 `style 100.0ms · layout 200.0ms in 1 pass`，与主线程 300ms 的构成对得上。

## 2026-11-22 #4 长任务列表要说「一共多少个」

- **改了什么**：`report.build()` 多返回 `long_count`（截断前的长任务总数）；终端标题从 `longest tasks:` 改成 `longest tasks (3 of 15 shown, --top to see more):`（没截断时写 `(15):`），页面标题同样变成「显示前 3 / 共 15」。新增 1 条用例（3 个长任务、`--top 1`：JSON 里 `len(long_tasks) == 1` 且 `long_count == 3`）。
- **为什么**：真跑出来的——15 个长任务、`--top 3`，输出只有三行、没有一句提示还有 12 个。`--top` 是视图不是度量，**「3 个长任务」和「一共 15 个，给你看 3 个」对排查是两件事**；JSON 消费方也没法从 `long_tasks` 长度反推被截断了。
- **验证**：22 个测试全过（HEAD 21）；同一份 trace 现在 `longest tasks (3 of 15 shown, --top to see more):`，`/api/report` 的 `long_count` 返回 3，页面 `sloplint.py` 干净。

## 2026-11-22 #5 忙时是两个区间的并集，不是「挑最外层那个」

- **改了什么**：`outermost()` 换成 `busy_time(tasks)`——按 `(start, -dur)` 扫一遍，区间不相交就整段加、与已覆盖区间相交就只加露出来的尾巴、完全被盖住才跳过；`Thread.busy` 用它。新增 1 条用例（`A[0,100]` 与 `B[50,150]` 必须算 150ms、占比 100%）。
- **为什么**：真跑出来的——上一版「只留最外层任务」在两段**相交但不包含**的区间上会把后一段整个丢掉：`A` 100ms、`B` 从 50ms 起 100ms，trace 长 150ms、实际忙满 150ms，报告写 `busy 100.0ms (66.7%)`。嵌套（上一轮修的）和相交是两种情况，前者不能重复计，后者不能少计。
- **验证**：23 个测试全过（HEAD 22）；同一份 trace 现在 `busy 150.0ms (100.0%)`，嵌套用例仍是 `200.0ms (100.0%)` 没有被改坏。
