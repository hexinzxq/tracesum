# 每日迭代 routine

每天五个窗口（08:00 / 12:30 / 13:30 / 18:30 / 21:30），每个窗口一次真迭代，收口汇报三行。

1. `cd /Users/xin/Documents/deepseek-harness/default-workspace/tracesum`，`git pull --rebase`，看 `docs/ITERATIONS.md` 最近三条，别做重复的事。
2. 拿**真实 trace** 跑一遍（DevTools 导出的 profile，或从 `~/Downloads` 找一个真实文件），记录它说错/没说的地方。
3. 选一个最小改动：一条规则、一条提示、一个开关。改完要能用真实文件复现「改前 X、改后 Y」。
4. 加一条用例，`python -m unittest discover -s tests -t .` 必须全过。
5. 写 `docs/ITERATIONS.md`（改了什么 / 为什么 / 验证），commit（`fix: …` 或 `feat: …`），推 `origin/main`，`gh run list -R hexinzxq/tracesum --limit 1` 确认绿。
6. 汇报：改了什么 / 为什么 / 验证结果，三行以内。

规矩：
- 不凑数。「没有值得改的」就写明看过哪些真实文件、结论是什么。
- 退出码是契约：`0` 干净、`1` 长任务、`2` 读不了；改退出码要写进 README。
- 每个新提示都要能回答「它替我看到了什么我没看到的」。
- 网络抖动（`SSL_ERROR_SYSCALL` / GitHub EOF）就重试，别改工具本身。
