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

## 2026-11-23 #1 长任务的时间是相对 trace 起的，不是进程开机以来的

- **改了什么**：`Summary` 多了 `origin_us`（第一个事件的 `ts`）；`report.build()` 的 `start_s` 改为 `(task.start - summary.origin_us) / 1e6`，同时保留绝对 `ts_us` 供需要的人取。新增 1 条用例（首个事件 `ts=5_000_000`、第二个 `5_100_000` → `start_s` 0.0 / 0.1，`ts_us` 仍是原值）。
- **为什么**：真跑出来的——trace 的 `ts` 是进程启动以来的微秒数，开了二十分钟的应用导出来 `ts ≈ 12_000_000_000`，报告写 `@12000.000s`。**DevTools 的时间轴是从录制开始算的**，屏幕上是 12.3s，报告给 12000s，对不上也没法回看；`@0.000s`/`@50.000s` 才是能直接对照的坐标。
- **验证**：24 个测试全过（HEAD 23）；同一份 trace 现在 `@ 0.000s` / `@ 50.000s`（两段事件之间确实空了 50 秒），`ts_us` 保留 12000000000 / 12050000000。

## 2026-11-23 #2 页面每 5 秒刷新，但 trace 只读一次

- **改了什么**：payload 多 `read_at`（读文件的本地时间，CLI 与 `make_handler` 都会补），页面底部加一行「数据读于 12:30:19，来自 many.json · 重新导出 trace 后请重启 tracesum --serve」；`source` 现在真的带上路径（CLI 一直传的是 `str(path)`，之前页面没显示）。新增 1 条用例（页面含 `read_at`、`/api/report` 的 `read_at` 形如 `HH:MM:SS` 且 `source` 非空）。
- **为什么**：页面每 5 秒轮询 `/api/report`，看起来像实时数据；实际上服务在启动时把 trace 读进内存，**重新导出 trace、刷新页面，什么都不会变，也没有任何地方说这是快照**。提示语写在页面上比写在 README 里有用——看页面的人不会翻 README。
- **验证**：25 个测试全过（HEAD 24）；`--serve` 起的页面上能看到 `数据读于 …，来自 …`，`/api/report` 带 `read_at` 与 `source`；页面 `sloplint.py` 干净。

## 2026-11-23 #3 退出码只回答「主线程有没有被占住」

- **改了什么**：`build()` 新增 `main_long_count`（长任务里落在主线程的数量），每条长任务多 `thread` 名字；`verdict()` 改成只看 `main_long_count`（原来只要 `long_tasks` 非空就 exit 1）。终端在存在非主线程长任务时把标题写成 `longest tasks (1, 1 not on the main thread):`，每行尾巴标 `(Compositor)`。新增 2 条用例（只在合成线程上 500ms → exit 0 且标题带提示；主线程 500ms → exit 1）。
- **为什么**：真跑出来的——主线程只忙 20ms、合成线程一个 500ms `Paint` 的 trace，报告第一行写着主线程很闲，退出码却是 1。**「长任务」在性能语境里指主线程 >50ms**，合成线程慢不会让页面卡；拿这个当 CI 门禁会在健康的 trace 上红。
- **验证**：27 个测试全过（HEAD 25）；`/tmp/worker.json` 现在 exit 0 且标题为 `(1, 1 not on the main thread)`，主线程长任务的 trace 仍 exit 1。

## 2026-11-23 #4 页面标题也要有「共几个、几个不在主线程」

- **改了什么**：`static/index.html` 的「最长的任务」标题改成动态：`共 15` 或 `显示前 10 / 共 15`，有非主线程长任务时再补「，1 个不在主线程」；每条长任务的小字从 `tid 2` 变成线程名（`Compositor`，没有名字才退回 tid）。新增 1 条用例：页面源码必须引用 `main_long_count` 与 `task.thread`。
- **为什么**：命令行已经会说 `longest tasks (1, 1 not on the main thread)` 和 `(10 of 15 shown)`，**页面还只写「最长的任务」四个字**——两个数（总数、是否在主线程）在页面上完全看不见，而页面恰好是最容易被分享给别人的那一半。另外页面一直印 `tid 2`，终端早就在印 `(Compositor)` 了。
- **验证**：28 个测试全过（HEAD 27）；页面源码含 `offMain` 分支与线程名回退，`sloplint.py` 干净；`/api/report` 的 `main_long_count` / `thread` 字段此前已就位。

## 2026-11-23 #5 阈值是可调的，而且被打印出来

- **改了什么**：新增 `--long-ms MS`（默认 50，Web Vitals 那条线；`<=0` 直接 exit 2），透传给 `summarise(long_ms=…)`；payload 带 `long_ms`；终端标题从 `longest tasks (15):` 变成 `longest tasks ≥50ms (15):`，空结果行写 `no task over 100ms — …`，页面页脚与标题同样显示 `≥100ms`。新增 2 条用例（80ms 的任务默认 exit 1、`--long-ms 100` 下 exit 0 且写「no task over 100ms」；`--long-ms 0` exit 2）。
- **为什么**：真跑出来的——`--long-ms 100` 时输出 `no task over 50ms`，**阈值明明改了，文字还写着 50**；这个数原来硬编码在 `summarise(long_ms=50.0)` 的默认值、终端文案和页面页脚三处，改一处就撒谎一次。阈值现在只有一份来源，并且凡是出现它的地方都跟着实时值走。
- **验证**：30 个测试全过（HEAD 28）；`--long-ms 100` 输出 `no task over 100ms` 且 exit 0，`--json` 的 `long_ms` 是 100.0，页面 `sloplint.py` 干净。

## 2026-11-24 #1 「主线程」是猜的，就说它是猜的

- **改了什么**：`build()` 多一个 `main_guessed`（trace 里没有任何 `CrRendererMain` 线程名时为 true）；终端第一行在猜的时候写 `busiest thread 2 busy 300.0ms (100.0%) — this trace names no threads, so "main" is a guess`，页面同理（「最忙的线程是 2——这份 trace 没写线程名，主线程是猜的」）。新增 2 条用例（无元数据 → `busiest thread 2` 且含「no threads」；有 `CrRendererMain` 元数据 → `main thread 1 (CrRendererMain)` 且不含 `guess`）。
- **为什么**：真跑出来的——手搓一份没有元数据事件的 trace（`tid 1` 100ms、`tid 2` 300ms），报告写 `main thread 2 busy 300.0ms`，理直气壮。**那份 trace 里根本没有「主线程」这个信息**，工具只是挑了最忙的线程；真 trace 里更忙的往往是合成线程，读者会拿这个数当主线程卡顿。
- **验证**：32 个测试全过（HEAD 30）；有线程名的那份仍是 `main thread 1 (CrRendererMain) busy 1005.0ms`，不再出现 guess 文案；页面 `sloplint.py` 干净。

## 2026-11-24 #2 其他线程一直在 payload 里，但没出现在任何地方

- **改了什么**：终端在第一行下面多一行 `threads: 2 Compositor 400.0ms · 1 CrRendererMain 100.0ms`（只在多于一个线程时打，最多三个，按忙时降序）；页面 chips 末尾补上同样的线程 chip（`Compositor 400ms`）。新增 2 条用例（两个线程 → 出现 `threads: 2 Compositor 500.0ms`；单线程 → 不打这一行）。
- **为什么**：真跑出来的——`/api/report` 从第一版起就带着 `threads`（tid、名字、忙时、任务数），**终端一行没印、页面一个没画**（`grep threads index.html` = 0）。工具叫「谁把主线程占了」，却看不到别的线程在干什么；判断「合成线程是不是更忙」得自己翻 JSON。
- **验证**：34 个测试全过（HEAD 32）；`/tmp/meta.json` 现在第二行后跟着 `threads: 2 Compositor 400.0ms · 1 CrRendererMain 100.0ms`，页面 chips 多出来；`sloplint.py` 干净。

## 2026-11-24 #3 线程列表也在截断，也得说一声

- **改了什么**：payload 多 `thread_total`（`len(summary.threads)`，`threads` 本身仍只带前 5）；终端在超过 3 个线程时写 `threads (3 of 7 shown, busiest first): …`，不多于 3 个时仍是 `threads: …`；页面在截断时补一个 chip「另有 4 个线程」。新增 1 条用例（6 个有工作的线程 → 出现 `threads (3 of 6 shown`）。
- **为什么**：真跑出来的——一份 6 个 worker 线程的 trace，终端只印三行 `threads: 2 Worker2 … · 3 Worker3 … · 4 Worker4 …`，**不说还有几个；payload 里 `threads[:5]` 更是悄悄只留五个**。这和长任务上一轮修的是同一类毛病：截断本身没问题，装作没截断才有问题。
- **验证**：35 个测试全过（HEAD 34）；同一份 trace 现在写 `threads (3 of 7 shown, busiest first)`（含主线程共 7 个），页面多出「另有 N 个线程」chip；`sloplint.py` 干净。

## 2026-11-24 #4 线程名、任务数：都算出来了，就该写出来

- **改了什么**：终端 `threads:` 行里没名字的线程从 `2 ? 60.0ms` 改成 `tid 2 60.0ms`（`?` 看起来像取值失败），名字与 tid 二选一不再并列；每个线程额外带上它跑过的任务数 `2 Compositor 400.0ms / 1 task`（单复数分开），页面 chip 同样加「N 个任务」。新增 1 条用例（两个无名线程 → 行里出现 `tid 2` 且不含 `?`），原有 `threads: 2 Compositor 500.0ms` 断言加上 `/ 1 task`。
- **为什么**：真跑出来的——无元数据的 trace 打 `threads: 2 ? 60.0ms`，读者既不知道 2 是谁也不知道 `?` 是没名字还是解析失败；而 payload 里每个线程一直带着 `tasks` 数，**终端和页面都没用过它**。合成线程忙 400ms 是 1 个长任务还是 200 个小任务，对「它到底在干嘛」是两个答案。
- **验证**：36 个测试全过（HEAD 35）；`/tmp/unnamed.json` 现在是 `threads: tid 2 60.0ms / 1 task · tid 3 60.0ms / 1 task`，`/tmp/meta.json` 是 `2 Compositor 400.0ms / 1 task`；`sloplint.py` 干净。
