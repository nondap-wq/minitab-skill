---
name: minitab
description: Minitab COM 自动化 AI Skill（自然语言 → 意图解析 → 知识库检索 → 会话命令/Python 代码生成 → COM 执行 → 知识回写）。当用户提到 Minitab、过程能力 Cpk/Ppk、控制图 Xbar-R、MSA/量具 R&R、DOE、描述性统计、直方图/箱线图、会话命令（CAPABILITY/XBR/GAGE/DESCRIBE/FACTORIAL）、Mtb.Application、win32com 驱动 Minitab、把质量/统计分析自动化，或输入 /minitab 时使用。
---

# Minitab COM 自动化 Skill

五层闭环：`意图解析 → 知识库检索 → 代码生成 → COM 执行 → 知识回写`。零第三方依赖（只需 pywin32）。

> ⚠️ **Agent 无法读取 Minitab 弹窗内的报错信息。**
> Minitab 弹出模态对话框时，COM 侧只能看到"命令无返回 + 后续一律报『正忙于处理操作』"，
> 真实原因只在弹窗文字里。**请让用户手动复制弹窗报错原文发给 Agent**，
> 可将定位从数十次盲试压缩到一次迭代。详见 `README.md`。

## 何时使用

- 用户要用**自然语言**让 Minitab 做统计分析（过程能力、控制图、MSA、DOE、描述性统计、图形）。
- 用户要 Minitab **会话命令**（CAPABILITY / XBR / GAGE / DESCRIBE / FACTORIAL …）或可用 Python COM 驱动的脚本。
- 用户要排查 Minitab COM 环境问题（`Mtb.Application` 连不上、类型库错误、进程泄漏）。

## 目录

```
scripts/minitab/                 Python 包（五层实现）
  intent_parser.py               Layer1 规则/LLM 意图解析
  knowledge_base.py              Layer2 SQLite 经验库 + 命令模板 + 避坑库 + 检索
  knowledge/seed/                种子：56 条会话命令模板、52 个对象模型类型（从本机 typelib 导出）
  code_generator.py              Layer3 会话命令 + 独立 Python COM 脚本生成
  com_executor.py                Layer4 COM 执行/预检 doctor/错误码诊断
  knowledge_writer.py            Layer5 经验与避坑自动回写
  orchestrator.py                五层编排
  cli.py                         CLI 入口
scripts/minitab_cli.py           CLI 入口（无需安装）
scripts/knowledge/experience.db  知识库（**DEFAULT_DB，运行时实际写入位置**）
examples/ccd_rsm_charts.py      可运行示例：CCD 全二次 RSM + 4 张原生图表
runtime/artifacts/               生成脚本与输出
runtime/evidence/               真机验证记录与测试报告
```

> 知识库路径以 `knowledge_base.py` 的 `DEFAULT_DB` 为准（`scripts/knowledge/experience.db`）。
> 旧版文档写的 `runtime/knowledge/experience.db` 已废弃，历史记录已合并进当前库。

## 命令

在 skill 根目录执行（`<skill>` 为技能目录）：

```powershell
$py = python                       # 需 pywin32；32 位 Minitab 用 32 位 Python
& $py <skill>\scripts\minitab_cli.py doctor                 # COM 环境预检（含修复建议）
& $py <skill>\scripts\minitab_cli.py run "对 C1 做过程能力分析 LSL=9 USL=17" --backend auto
& $py <skill>\scripts\minitab_cli.py run "<请求>" --backend com     # 强制真机 COM
& $py <skill>\scripts\minitab_cli.py plan "<请求>" --save driver.py # 只生成不执行
& $py <skill>\scripts\minitab_cli.py kb --command CAPABILITY        # 查命令模板 + 避坑记录
& $py <skill>\scripts\minitab_cli.py kb --members IProject          # 查对象模型成员/DISPID
& $py <skill>\scripts\minitab_cli.py demo                           # 内置 4 个示例走通闭环
```

`--backend`：`auto`（预检通过用 COM，否则 dry-run）/ `com`（真机）/ `dry-run`（离线模拟，写入知识库并标记 dry_run）。

## 执行架构（宏优先 → 自编宏 → COM 兜底）

```
用户自然语言 + 数据
   │
   ├─ ① macro_library.search()      官方宏库检索（macros/，54 个官方宏，带 index.json）
   │      强命中（核心词出现在宏用途中）→ 直接调用官方宏  %NAME
   │
   ├─ ② macro_generator              宏库无匹配 → 生成参数化 GMACRO 宏文件
   │      build_rsm_macro / build_chart_macro → runtime/generated_macros/*.MAC
   │      调用：%MTB_RSM（或 EXECUTE 绝对路径）
   │
   └─ ③ com_executor / doe_rsm       宏无法覆盖的底层操作 → COM 直接操控
          doe_rsm.MinitabSession：单行命令 + ExecuteCommandAsync + 完成门控
          com_executor.ComBackend：已验证的会话命令链路（**保持不变**）

完成判定 → 读结果 → 出图（Minitab）→ 经验回写（knowledge_base）→ 报告交付
```

决策入口：`minitab.router.route(intent, **kw)` / `route_from_text(text, **kw)`
CLI 检查：`minitab_cli.py macro --route "<任务>"`、`macro --search "<关键词>"`、`macro`（策略总览）

**路由实测样例**

| 输入 | 决策层 | 结果 |
|---|---|---|
| `CCD response surface for PNL_BS` | generated_macro | `%MTB_RSM`（官方宏库无 RSM 能力） |
| `confidence interval for a population proportion` | official_macro | `%2PINF`（相关度 28，核心词命中用途） |
| `contour plot for design window` | generated_macro | `%MTB_CHART` |
| `capability analysis C1 LSL=9 USL=17` | com | `CAPA C1 1; LSPEC 9; USPEC 17.` |

> ⚠️ 上表是**路由决策**层面的实测，不代表宏一定能跑通。
> 截至 2026-10-28，`%MTB_RSM` 在 Minitab 20 上仍未跑通（见「已知限制」）；
> **CCD / RSM / 等高线请直接走 `examples/ccd_rsm_charts.py` 的 COM 路径**，
> 或手工发送下表的会话命令。

```powershell
python <skill>\scripts\minitab_cli.py macro                          # 策略 + 宏库统计
python <skill>\scripts\minitab_cli.py macro --search "contour plot"  # 宏库检索
python <skill>\scripts\minitab_cli.py macro --route "CCD response surface for PNL_BS" --response C9 --factors "C6 C7"
python <skill>\scripts\minitab_cli.py macro --reindex                # 重建宏索引
```

**完成信号（出图收尾）**：分析命令用 `submit_and_wait`（轮询 `Commands.Count` 增长只代表被受理）；
图形命令必须再轮询 **PNG 落盘**才算完成（`GSAVE` 是异步落盘）。
宏整体执行用 `wait_idle`（历史若干轮不再增长）。

**对象模型要点（Minitab COM 与 Excel 不同，别想当然）**

| 想做的事 | 错误写法 | 正确写法 |
|---|---|---|
| 显示窗口 | `MTB.Visible = True` | `MTB.UserInterface.Visible = True` |
| 建列 | `WS.Columns.Item(1)`（新表列数为 0） | `WS.Columns.Add(Quantity=n)` |
| 单元格 | `WS.Cells(r,c).Value` | `WS.Columns.Item(i).SetData([...])` |
| 列名 | `col.Label = "x"`（**只读**） | `col.Name = "x"` |
| 追加数据 | `SetData` 传含 `None` 的列表 | 先写主体，再 `SetData([v1,v2], StartRow=10, NumRows=2)` |

> `SetData` 是**整体替换**语义；配合 `StartRow` 时未覆盖的前段会被填哨兵值 `1.23456e+30`。

## 真机验证过的命令（Minitab 20 / 22，必须逐字遵守）

| 任务 | 可用命令（**单行**，子命令 `;` 分隔、`.` 结束） |
|---|---|
| 过程能力 | `CAPA C1 1; LSPEC 9; USPEC 17.`（**至少一个规格限**，否则报"1 变元太少"） |
| 响应曲面/CCD | `RSREG; RESPONSE C5; FACTOR C3 C4; TERMS C3 C4 C3*C3 C4*C4 C3*C4; INUNIT 1; LEVELS 100 300 200 400; TSUMMARY; TANOVA; TCOEFFICIENT; TEQUATION; FITS C6; RESIDUALS C7.` |
| 一般回归 | `REGRESS; RESPONSE C9; CONTINUOUS C6 C7.` |
| **等值线** | `CONTOURPLOT C5*C4*C3; GSAVE "out.png".`（**星号分隔 z\*y\*x**，空格形式报 Syntax Error） |
| **3D 曲面** | `SURFACEPLOT C5*C4*C3; GSAVE "out.png".`（命令名是 `SURFACEPLOT`，**没有** `SURFPLOT`） |
| 描述统计 | `DESCRIBE C1 C2.` |
| 图形 | `HISTOGRAM C1.` / `BOXPLOT C1.` |

**`RSREG` 子命令要点**
- **必需**：`RESPONSE` / `FACTOR` / `TERMS` / `INUNIT` / `LEVELS`。
  `TERMS` 不能省，否则报「TERMS 是所要求的子命令」。
- **不存在** `FIT`（报「子命令 FIT 失序，或者对于该命令无效」）→ 存拟合值用 `FITS C6`。
- **不存在** `CONTOUR` / `SURFACE`（报「子命令 CONT 失序」）→ 模型等值线请用
  `CONTOURPLOT` 画拟合值列（`C6*C4*C3`）。
- 结果表子命令拼写：`TSUMMARY` / `TANOVA` / `TCOEFFICIENT` / `TEQUATION`
  （少一个 U 会被截断成 `TSMM` 并报「失序」）。
- 平方项写 `C3*C3`，不能用 `A*A`；`INUNIT 0`（编码因子）会被拒，用 `INUNIT 1` + `LEVELS`。

**COM 提交协议（踩坑总结，务必遵守）**
1. **`UserInterface.Visible` 必须设 `True`**：COM 启动的 Minitab 默认**无头**
   （`Visible=False`），此时会话命令被**静默丢弃**——不执行、不报错、`Commands.Count` 不增长。
   这是最隐蔽的坑；设完等 2–3 s 让窗口初始化。
2. **`DisplayAlerts` 必须设 `True`**：设 `False` 会吞掉错误报告，出错命令留下的未决状态
   把命令队列**永久卡死**（后续一律"正忙于处理操作"）。保持 `True` 时错误会以
   `Syntax Error` 作为命令名登记出来，可据此逐条迭代语法。
3. 命令必须**单行**；`.mtb` 命令文件里的换行续写会被拆成独立命令 → `Syntax Error`。
4. 分析类命令用 `ExecuteCommandAsync` 提交，然后轮询 `Project.Commands.Count` 增长判断是否被接收；
   **完成前提交下一条会报 "IProject: Minitab 正忙于处理操作"**。
   注意 `Count` 增长只代表命令被**受理**，不代表算完——图形命令需再轮询 PNG 落盘。
5. **只写数值列**（文本列写入会挂起）；`Column.RowCount` 写入后不刷新，不能当写入判据。
6. 读结果：`Command.Name` 是分析标题；输出原文按版本取——
   **Mtb 20** 用 `Command.OutputDocument.Text`（无 `Outputs` 属性）；
   **Mtb 22** 早期记录为 `Command.Outputs.Item(k).Text`。代码里建议双路 try。
7. 一个 Minitab 实例同一时刻只接受一条分析命令；批量任务要串行 + 等待。
8. **遇到 `*** HANG ***` 先看弹窗**：让用户复制 Minitab 窗口内的报错原文，
   这是唯一可靠的诊断信息（Agent 读不到弹窗文字）。

## 内置资料（不必通读，按关键词检索）

```
reference/Minitab_session_commands.pdf    官方会话命令参考（1204 页）
reference/Minitab_session_commands.txt    抽取后的带页码文本（<<<PAGE n>>> 标记）
reference/search_commands.py              关键词检索工具
macros/                                   官方宏库（.MTB：比例推断/置信区间模拟/随机抽样/条形图）
examples/ccd_rsm_charts.py                可运行示例：CCD 全二次 RSM + 4 张原生图表
runtime/evidence/                         真机验证记录（含 CCD_2026-10-28.md 与图表原件）
```

```powershell
python <skill>\reference\search_commands.py RSREG --context 900     # 找命令语法（带页码）
python <skill>\reference\search_commands.py --page 348              # 直接看某页
python <skill>\reference\search_commands.py --list                  # 列出全部会话命令
```

## 执行纪律

1. **先 `doctor` 再执行**：`ready=false` 时不要直接跑 `--backend com`，按 `remediation` 处理环境。
2. **`auto` 是默认**：环境未就绪时自动降级为 dry-run，结果里 `simulated=true`，必须如实告知用户"未真机执行"。
3. **生成物必看**：`plan` 会打印会话命令与 Python 脚本；命令语法要点——子命令以 `;` 引导、整条命令以 `.` 结束。
4. **每个请求都要回写知识库**：`run` 自动写 `experiences`；真机失败自动写 `pitfalls` 并更新命令可靠性评分。不要绕过这一步。
5. **进程纪律**：COM 对象在顶层作用域持有；只有本次会话启动的 Minitab 才调用 `Quit()`（`ComBackend.quit_when_launched`）。
6. **危险操作二次确认**：`DELETE` 行/列、覆盖保存项目 (`SAVE`/`WSAVE`) 前必须先向用户确认。

## 环境要求（关键）

- Minitab 许可证需含 COM/Automation 模块；Minitab 需**以管理员身份启动**；`工具 > 选项 > OLE/COM > Enable Automation` 必须勾选。
- Python 位数必须与 Minitab 一致（Minitab 22 同时注册 win32/win64；Minitab 17 仅 32 位）。
- **Minitab 17 及更早版本无法在新 Windows 上自动化**：其 typelib 是 Windows 无法解析的私有格式，`LoadTypeLib`/`Dispatch` 均返回 `0x8002801C TYPE_E_CANTLOADLIBRARY`。此时只能用 `dry-run`，或升级到 Minitab 20/21/22。
- `0x80080005 CO_E_SERVER_EXEC_FAILURE`：Minitab 进程启动失败（崩溃/需提权）。先手动以管理员身份启动并确认窗口出现。

## 已知限制

- 检索使用字符二元组相似度（无向量库依赖）；接口与向量库后端兼容，可替换 `KnowledgeBase.retrieve_similar`。
- `capture_outputs` 只读取命令行历史里的输出文档标题；若需要完整 CSV 导出，用会话命令 `WSAVE` 或 `SaveAs`（见 `export_outputs`）。
- DOE 生成的是 2^3 全因子占位语法，实际设计需用户补充因子/水平。
- **官方宏库无 RSM/CCD/等高线能力**（`macros/` 仅比例推断、置信区间模拟、随机抽样、条形图），
  这类任务走 COM 会话命令。
- **自动生成的 GMACRO 宏（`%MTB_RSM`）在 Minitab 20 上尚未跑通**：用 `EXECUTE "*.MAC"`
  调用会报「未知 Minitab 命令: GMAC」（`EXECUTE` 是给 exec 文件的，宏应用 `%NAME` 调用）。
  在修好之前，CCD/RSM 请直接用 `examples/ccd_rsm_charts.py` 的 COM 路径。
- 强制结束 Minitab 进程后，`%TEMP%\gen_py` 缓存可能损坏，表现为
  `AttributeError: module 'win32com.gen_py...' has no attribute 'CLSIDToClassMap'`；
  清空该目录即可恢复。

## 故障排查速查

| 现象 | 处理 |
|---|---|
| 命令全部挂起、无任何返回 | **看 Minitab 窗口有无弹窗**，请用户复制报错原文 |
| `未知 Minitab 命令: GMAC` | `EXECUTE` 用于 exec 文件；调用宏用 `%NAME` |
| `gen_py ... CLSIDToClassMap` | 清空 `%TEMP%\gen_py` |
| `IColumns 不能为空` | 先 `Columns.Add()` |
| `设置 (null) 中的数据值时出错` | `SetData` 列表含 `None` |
| 子命令被截断（如 `CONT`/`TSMM`/`GMAC`） | 该子命令不存在或拼写错误，Minitab 截断后报「失序」 |
