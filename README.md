# tracesum

用命令行读一份 Chrome performance trace：谁在忙、忙了多久、主线程被谁卡住。

对标 [ChromeDevTools/chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp)：那是把 DevTools 交给 agent 去开浏览器；**这个不上浏览器、不连页面、不联网**，只吃你已经导出好的 trace 文件（DevTools → Performance → Save profile），一秒钟给出结论。适合「同事发来一个 120MB 的 profile.json，我只想知道哪里抖」的场合。

## 它回答什么

- 这份 trace 多长，主线程（最忙的那个 tid）忙了多少毫秒、占比多少
- script / style / layout / paint 各占多久，layout 跑了几趟
- 主线程上超过 50ms 的完整事件（`ph: "X"`），按耗时从长到短

`script` 只认 `FunctionCall` / `EvaluateScript` / `v8.run` 三个名字，所以它是下限而不是全貌——报告里不给百分比，只给毫秒数。

## 快速开始

```sh
pip install -e .

tracesum profile.json              # 人读的报告；有 >50ms 任务时 exit 1
tracesum profile.json --json       # 给脚本
tracesum profile.json --top 5      # 只看最长的 5 个
tracesum profile.json --serve      # 本地页面（默认 127.0.0.1:8765）
```

退出码：`0` 没有长任务，`1` 有 ≥50ms 的任务（脚本里当「这次卡了」用），`2` 读不了这个文件。

## 设计取舍

- **零依赖**：stdlib 的 `json` + `http.server`。工具的价值在于「拿到文件就能跑」，装依赖的摩擦力会把「顺手看一眼」变成「下次吧」。
- **只读**：不连 Chrome、不 attach、不改任何东西；输入是一个文件，输出是一段话。
- **不做火焰图**：那需要渲染与缩放，浏览器 DevTools 已经做得很好。这里做的是「先告诉你值不值得打开 DevTools」。
- **名字即判据**：布局类事件按 `Layout` / `UpdateLayoutTree` 计，script 按三个固定名字计；换浏览器或 Blink 内部改名会漏，这是已知的取舍（写在这里，不假装没有）。

## 测试

```sh
python -m unittest discover -s tests -t .
```

用例都是手搓的小 trace（几百字节），不依赖真实 profile——真实文件太大，进不了仓库。

## 待办

- 大文件：现在是整体 `json.loads`，200MB 的 profile 会吃掉内存；下一步做流式解析（按 `traceEvents` 切块）
- 事件分类表做成可配置（`--kind script=FunctionCall,Compile`），不同框架叫法不一样
- `--serve` 加上把长任务按「前后 200ms 的上下文」展开，点一下能看到邻居事件
