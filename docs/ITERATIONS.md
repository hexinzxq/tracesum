# 迭代记录

每天 5 次，一次一件事：拿真实输入跑工具 → 找到「它说错了/没说」的地方 → 改最小的一处 → 加一条用例 → 推送并确认 CI。

## 2026-11-21 scaffold

- diff：完整的 Chrome trace 读取（`ph: "X"` 事件、tid 分组、主线程 = 最忙的线程）、shell 汇总（script/style/layout/paint + ≥50ms 长任务）、`--json`、`--serve` 本地页面、退出码 0/1/2。
- 为什么先做这四件：一份 trace 的最小问题是「多长、谁忙、忙多久、卡没卡」；这四件事不依赖浏览器也能答。
- 验证：15 个测试（load 的四种输入、summarise 的线程/长任务/分桶/跨度、CLI 退出码、HTTP 页面与 `/api/report`）；`sloplint.py` 扫页面 `clean`。
