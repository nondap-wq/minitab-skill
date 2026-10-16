---
name: minitab
description: Minitab COM 自动化 AI Skill（自然语言 → 意图解析 → 知识库检索 → 会话命令/Python 代码生成 → COM 执行 → 知识回写）。当用户提到 Minitab、过程能力 Cpk/Ppk、控制图 Xbar-R、MSA/量具 R&R、DOE、描述性统计、直方图/箱线图、会话命令（CAPABILITY/XBR/GAGE/DESCRIBE/FACTORIAL）、Mtb.Application、win32com 驱动 Minitab、把质量/统计分析自动化，或输入 /minitab 时使用。
---

# Minitab COM 自动化 Skill

五层闭环：`意图解析 → 知识库检索 → 代码生成 → COM 执行 → 知识回写`。零第三方依赖（只需 pywin32）。

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
runtime/knowledge/experience.db  知识库（自动创建）
runtime/artifacts/               生成脚本与输出
```

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

```powershell
python <skill>\scripts\minitab_cli.py macro                          # 策略 + 宏库统计
python <skill>\scripts\minitab_cli.py macro --search "contour plot"  # 宏库检索
python <skill>\scripts\minitab_cli.py macro --route "CCD response surface for PNL_BS" --response C9 --factors "C6 C7"
python <skill>\scripts\minitab_cli.py macro --reindex                # 重建宏索引
```

**完成信号（出图收尾）**：图形命令用 `MinitabSession.run_macro_with_artifact(invocation, png)`
（轮询 PNG 落盘）；分析命令用 `submit_and_wait`（轮询 `Commands.Count` 增长）；
宏整体执行用 `wait_idle`（历史若干轮不再增长）。

## 真机验证过的命令（Minitab 22，必须逐字遵守）

| 任务 | 可用命令（**单行**，子命令 `;` 分隔、`.` 结束） |
|---|---|
| 过程能力 | `CAPA C1 1; LSPEC 9; USPEC 17.`（**至少一个规格限**，否则报"1 变元太少"） |
| 响应曲面/CCD | `RSREG; RESPONSE C9; FACTOR C6 C7; TERMS C6 C7 C6*C6 C7*C7 C6*C7; INUNIT 1; LEVELS -1000 0 8 14.` |
| 一般回归 | `REGRESS; RESPONSE C9; CONTINUOUS C6 C7.` |
| 等值线 | `CONTOURPLOT <z> <y> <x>; GSAVE "out.png".` |
| 描述统计 | `DESCRIBE C1 C2.` |
| 图形 | `HISTOGRAM C1.` / `BOXPLOT C1.` |

**COM 提交协议（踩坑总结，务必遵守）**
1. 命令必须**单行**；`.mtb` 命令文件里的换行续写会被拆成独立命令 → `Syntax Error`。
2. 分析类命令（`RSREG`/`REGRESS`/`FITLINE`）用**同步** `ExecuteCommand` 会**挂起**；必须
   `ExecuteCommandAsync` 提交，然后轮询 `Project.Commands.Count` 增长判断完成；
   **完成前提交下一条会报 "IProject: Minitab 正忙于处理操作"**（`skill/scripts/minitab/doe_rsm.py::MinitabSession.submit_and_wait`）。
3. `RSREG` **必需** `INUNIT` 与 `LEVELS`（缺则报"INUNIT 是所要求的子命令"）；
   平方项写 `C6*C6`，不能用 `A*A`；`INUNIT 0`（编码因子）会被拒，用 `INUNIT 1` + `LEVELS`。
4. 只写数值列（文本列写入会挂起）；`Column.RowCount` 写入后不刷新，不能当写入判据。
5. 读结果：`Command.Name` 是分析标题；`Command.Outputs.Item(k).Text` 是 Minitab 输出表**原文**。
6. 一个 Minitab 实例同一时刻只接受一条分析命令；批量任务要串行 + 等待。

## 内置资料（不必通读，按关键词检索）

```
reference/Minitab_session_commands.pdf    官方会话命令参考（1204 页）
reference/Minitab_session_commands.txt    抽取后的带页码文本（<<<PAGE n>>> 标记）
reference/search_commands.py              关键词检索工具
macros/                                   官方宏库（56 个 .MTB：比例推断/置信区间模拟/随机抽样/条形图）
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
