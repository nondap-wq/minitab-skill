# Minitab AI Skill

把自然语言 + 数据变成 Minitab 的配置与计算流程：**宏库优先 → 自编宏 → COM 兜底**，
计算全部由本机 Minitab 完成，最终交付 Minitab 原生结果与图表。

---

## ⚠️ 使用前必读：把弹窗报错**手动复制**给 Agent

**Agent 无法读取 Minitab 弹出窗口内的文字。**

当 Minitab 在 GUI 中弹出模态对话框（例如 `无效模型，选定的轴太少`、
`TERMS 是所要求的子命令`、`子命令 FIT 失序，或者对于该命令无效`）时，
COM 端只能观察到"命令提交后没有任何返回"：

- `Commands.Count` 不增长
- 不抛异常、不报错
- 后续命令一律返回 `IProject: Minitab 正忙于处理操作，此时不能接受其他命令`

Agent 看到的现象是"挂起"，但**真正的原因只存在于那个弹窗里**。

### 推荐做法

> **一旦 Minitab 弹出错误对话框，请手动复制弹窗中的报错原文，直接发给 Agent。**

例如：

```
* 错误 * 子命令 FIT 失序，或者对于该命令无效。
        * 其余子命令被忽略。
        * 计算不可能完成。
```

这一条信息能把定位过程从**几十次盲试缩短到一次迭代**。CCD 任务中的三个致命错误
（`FIT` 不是 RSREG 子命令、`TERMS` 是必需子命令、`CONTOUR` 不是子命令）全部是
**用户手动复制弹窗原文后一次性定位的**——在此之前，仅凭 COM 侧观察只能看到"挂起"。

同理，如果 Agent 报告 `*** HANG ***`，请先看一眼 Minitab 窗口有没有弹窗，并把内容贴回来。

---

## 执行架构

```
用户自然语言 + 数据
   │
   ├─ ① macro_library.search()     官方宏库检索（macros/，官方宏 + index.json）
   │       强命中 → 直接调用官方宏  %NAME
   ├─ ② macro_generator            无可用宏 → 生成参数化 GMACRO 宏文件
   │       runtime/generated_macros/*.MAC
   └─ ③ com_executor / doe_rsm     宏覆盖不到的底层操作 → COM 直接操控 Minitab
           doe_rsm.MinitabSession：单行命令 + ExecuteCommandAsync + 完成门控

完成判定 → 读结果 → 出图（Minitab）→ 经验回写（SQLite）→ 报告交付
```

## 快速开始

```powershell
# 依赖：Windows + Minitab 20/21/22 + Python(位数与 Minitab 一致) + pywin32
pip install pywin32

$py = "python"   # 或指定解释器
$skill = "<本仓库路径>"

# 1) 环境预检（COM 注册 / 类型库 / 服务器可用性 + 修复建议）
& $py "$skill\scripts\minitab_cli.py" doctor

# 2) 五层闭环（意图 → 生成 → 执行 → 学习）
& $py "$skill\scripts\minitab_cli.py" run "capability C1 LSL=9 USL=17" --backend com --data

# 3) 路由决策：该任务走官方宏 / 生成宏 / COM？
& $py "$skill\scripts\minitab_cli.py" macro --route "CCD response surface for PNL_BS" --response C9 --factors "C6 C7"

# 4) 官方会话命令检索（内置参考文档，按关键词带页码定位）
& $py "$skill\reference\search_commands.py" RSREG --context 900
& $py "$skill\reference\search_commands.py" --page 348

# 5) 离线闭环演示（无需 Minitab）
& $py "$skill\scripts\minitab_cli.py" demo

# 6) CCD 响应曲面 + 4 张原生图表（可直接运行的完整示例）
& $py "$skill\examples\ccd_rsm_charts.py" --out "$skill\runtime\artifacts\ccd_charts"
```

## 目录

```
SKILL.md                  技能入口与执行纪律
examples/
  ccd_rsm_charts.py       CCD 全二次响应曲面 + 等值线/曲面图（可运行示例）
  ccd_model_check.py      纯 Python 模型精度校核（不调用 Minitab）
scripts/minitab/          Python 包
  intent_parser.py        意图解析（自然语言 → 结构化意图）
  macro_library.py        官方宏库索引与检索
  macro_generator.py      参数化 GMACRO 宏生成
  router.py               路由：official_macro / generated_macro / com
  doe_rsm.py              Minitab 会话封装（提交协议 + 完成门控 + 读输出）
  code_generator.py       会话命令 / Python 驱动脚本生成
  com_executor.py         COM 执行层（背板：ComBackend / DryRun / Replay / doctor）
  knowledge_base.py       知识库（SQLite：经验、避坑、命令模板、对象模型）
  knowledge_writer.py     经验与避坑回写
  orchestrator.py         五层编排
  cli.py                  CLI
reference/                官方会话命令参考与检索工具（PDF 不入库，可用官方渠道获取）
macros/                   官方宏库（.MTB）
runtime/                  运行时产物（知识库、日志、生成的宏与图，默认不入库）
runtime/evidence/         真机验证记录与测试报告
```

## 真机验证过的关键事实

### 命令表（**单行**；子命令 `;` 分隔、`.` 结束）

| 任务 | 命令 |
|---|---|
| 过程能力 | `CAPA C1 1; LSPEC 9; USPEC 17.`（至少一个规格限，否则报"1 变元太少"） |
| 响应曲面 / CCD | `RSREG; RESPONSE C5; FACTOR C3 C4; TERMS C3 C4 C3*C3 C4*C4 C3*C4; INUNIT 1; LEVELS 100 300 200 400; TSUMMARY; TANOVA; TCOEFFICIENT; TEQUATION; FITS C6; RESIDUALS C7.` |
| 一般回归 | `REGRESS; RESPONSE C9; CONTINUOUS C6 C7.` |
| **等值线** | `CONTOURPLOT C5*C4*C3; GSAVE "out.png".`（**星号分隔 z\*y\*x**；空格形式报 Syntax Error） |
| **3D 曲面** | `SURFACEPLOT C5*C4*C3; GSAVE "out.png".`（命令名是 `SURFACEPLOT`，**没有** `SURFPLOT`） |
| 描述统计 | `DESCRIBE C1 C2.` |
| 图形 | `HISTOGRAM C1.` / `BOXPLOT C1.` |

### `RSREG` 子命令要点

- **必需**：`RESPONSE` / `FACTOR` / `TERMS` / `INUNIT` / `LEVELS`。
  `TERMS` 不能省，否则报「TERMS 是所要求的子命令」。
- **不存在** `FIT`（报「子命令 FIT 失序，或者对于该命令无效」）→ 存拟合值用 `FITS C6`。
- **不存在** `CONTOUR` / `SURFACE`（报「子命令 CONT 失序」）
  → 模型等值线请用 `CONTOURPLOT` 画拟合值列（`C6*C4*C3`）。
- 结果表子命令拼写：`TSUMMARY` / `TANOVA` / `TCOEFFICIENT` / `TEQUATION`
  （少一个 U 会被截断成 `TSMM` 并报「失序」）。
- 平方项写 `C6*C6`；`INUNIT 0`（编码因子）会被拒，用 `INUNIT 1` + `LEVELS`。

### COM 提交协议

0. **`UserInterface.Visible` 必须设 `True`**：COM 启动的 Minitab 默认**无头**
   （`Visible=False`），此时会话命令被**静默丢弃**——不执行、不报错、`Commands.Count` 不增长。
   这是最隐蔽的坑；设完等 2–3 s 让窗口初始化。
0. **`DisplayAlerts` 必须保持 `True`**：设 `False` 会吞掉错误报告，出错命令留下的未决状态
   把命令队列**永久卡死**（后续一律"正忙于处理操作"）。保持 `True` 时错误会以
   `Syntax Error` 作为命令名登记出来，可据此逐条迭代语法。
0. 命令必须单行；命令文件里换行续写会被拆散 → `Syntax Error`。
0. 分析类命令（`RSREG`/`REGRESS`/`FITLINE`）应使用 `ExecuteCommandAsync` + 轮询
   `Commands.Count` 判断是否**被受理**；完成前提交下一条会报"Minitab 正忙于处理操作"。
   注意 `Count` 增长不代表算完，出图需再轮询 PNG 落盘。
0. 只写数值列（文本列写入会挂起）；`Column.RowCount` 写入后不刷新。
0. 读结果：`Command.Name`（分析标题）与输出原文。原文按版本取——
   **Mtb 20** 用 `Command.OutputDocument.Text`（无 `Outputs` 属性）；
   **Mtb 22** 用 `Command.Outputs.Item(k).Text`。

### 对象模型差异（与 Excel 不同，别想当然）

| 想做的事 | 错误写法 | 正确写法 |
|---|---|---|
| 显示窗口 | `MTB.Visible = True` | `MTB.UserInterface.Visible = True` |
| 建列 | `WS.Columns.Item(1)`（新表列数为 0） | `WS.Columns.Add(Quantity=n)` |
| 单元格 | `WS.Cells(r,c).Value` | `WS.Columns.Item(i).SetData([...])` |
| 列名 | `col.Label = "x"`（**只读**） | `col.Name = "x"` |
| 追加数据 | `SetData` 传含 `None` 的列表 | 先写主体，再 `SetData([v1,v2], StartRow=10, NumRows=2)` |

> `SetData` 是**整体替换**语义；配合 `StartRow` 时未覆盖的前段会被填哨兵值 `1.23456e+30`。

## 已验证版本

| Minitab | 状态 | 说明 |
|---|---|---|
| **20.0**（Mtb 20.0 Type Library） | ✅ 真机验证 2026-10-28 | CCD 全二次 RSM + 4 张原生图表；输出读 `OutputDocument` |
| **22.1** | ✅ 真机验证 2026-10-16 | 过程能力 CAPA、CCD；旧记录用 `Outputs.Item(k).Text` |

两个版本的 typelib 在**输出读取**上不同，代码已做双路兼容。

## 故障排查

| 现象 | 处理 |
|---|---|
| 所有命令挂起、无任何返回 | **看 Minitab 窗口有无弹窗**，请用户复制报错原文 |
| `未知 Minitab 命令: GMAC` | `EXECUTE` 只跑 exec 文件；调用宏必须用 `%NAME` |
| `gen_py ... CLSIDToClassMap` | 清空 `%TEMP%\gen_py`（强杀 Minitab 后常见） |
| `IColumns 不能为空` | 先 `Columns.Add()` |
| `设置 (null) 中的数据值时出错` | `SetData` 列表含 `None` |
| 子命令被截断（`CONT`/`TSMM`/`GMAC`） | 该子命令不存在或拼写错误，Minitab 截断后报「失序」 |

## 真机验证记录

- [`runtime/evidence/VERIFIED.md`](runtime/evidence/VERIFIED.md) — 过程能力 CAPA（Minitab 22）
- [`runtime/evidence/CCD_TEST_REPORT.md`](runtime/evidence/CCD_TEST_REPORT.md) — CCD 响应曲面（Minitab 22，2026-10-16）
- [`runtime/evidence/CCD_2026-10-28.md`](runtime/evidence/CCD_2026-10-28.md) — CCD 响应曲面 + 原生图表（Minitab 20，2026-10-28）

## 已知限制

- Minitab 17 及更早版本无法自动化（typelib 为私有格式，`LoadTypeLib` 返回 `0x8002801C`）。
- 驱动 COM 的宿主进程需要管理员权限，否则 `0x80080005 CO_E_SERVER_EXEC_FAILURE`。
- 官方宏库（`macros/`）只覆盖比例推断、置信区间模拟、随机抽样、条形图；回归/DOE 类无官方宏，
  由 `macro_generator` 生成宏或走 COM。
- **自动生成的 GMACRO 宏（`%MTB_RSM`）在 Minitab 20 上尚未跑通**：用 `EXECUTE "*.MAC"`
  调用会报「未知 Minitab 命令: GMAC」（`EXECUTE` 是给 exec 文件的，宏应用 `%NAME` 调用）。
  在验证之前，CCD/RSM 请直接用 `examples/ccd_rsm_charts.py` 的 COM 路径。
- 图形命令的完成判定以 PNG 落盘为准（`MinitabSession.run_macro_with_artifact`）。
- 知识库 `scripts/knowledge/experience.db` 属运行时状态，按 `.gitignore` **不入库**；
  首次运行时由 `scripts/minitab/knowledge/seed/` 重建命令模板与对象模型。
  经验与避坑沉淀在当前机器本地库中。

## 许可与第三方资料

- 本仓库代码：自行选择许可（如 MIT）。
- `reference/` 中的 **Minitab 官方会话命令参考**与 `macros/` 中的官方宏属 **Minitab, LLC** 版权资料，
  未包含在版本库中（见 `.gitignore`）。使用时请自行从官方渠道获取并遵守其许可条款。
