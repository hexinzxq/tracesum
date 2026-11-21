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
