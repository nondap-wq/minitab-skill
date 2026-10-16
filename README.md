# Minitab AI Skill

把自然语言 + 数据变成 Minitab 的配置与计算流程：**宏库优先 → 自编宏 → COM 兜底**，
计算全部由本机 Minitab 完成，最终交付 Minitab 原生结果与图表。

## 执行架构

```
用户自然语言 + 数据
   │
   ├─ ① macro_library.search()      官方宏库检索（macros/，官方宏 + index.json）
   │       强命中 → 直接调用官方宏  %NAME
   ├─ ② macro_generator             无可用宏 → 生成参数化 GMACRO 宏文件
   │       runtime/generated_macros/*.MAC
   └─ ③ com_executor / doe_rsm      宏覆盖不到的底层操作 → COM 直接操控 Minitab
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
```

## 目录

```
SKILL.md                  技能入口与执行纪律
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
```

## 真机验证过的关键事实（Minitab 22）

| 任务 | 可用命令（**单行**；子命令 `;` 分隔、`.` 结束） |
|---|---|
| 过程能力 | `CAPA C1 1; LSPEC 9; USPEC 17.`（至少一个规格限，否则报"1 变元太少"） |
| 响应曲面 / CCD | `RSREG; RESPONSE C9; FACTOR C6 C7; TERMS C6 C7 C6*C6 C7*C7 C6*C7; INUNIT 1; LEVELS -1000 0 8 14.` |
| 一般回归 | `REGRESS; RESPONSE C9; CONTINUOUS C6 C7.` |
| 等值线 | `CONTOURPLOT <z> <y> <x>; GSAVE "out.png".` |

**COM 提交协议**
1. 命令必须单行；命令文件里换行续写会被拆散 → `Syntax Error`。
2. 分析类命令（`RSREG`/`REGRESS`/`FITLINE`）同步 `ExecuteCommand` 会挂起，必须
   `ExecuteCommandAsync` + 轮询 `Commands.Count` 判完成；完成前提交下一条会报
   "Minitab 正忙于处理操作"。
3. `RSREG` 必需 `INUNIT` + `LEVELS`；平方项写 `C6*C6`；`INUNIT 0` 会被拒。
4. 只写数值列（文本列写入会挂起）；`Column.RowCount` 写入后不刷新。
5. 读结果：`Command.Name`（分析标题）与 `Command.Outputs.Item(k).Text`（输出原文）。

## 已知限制

- Minitab 17 及更早版本无法自动化（typelib 为私有格式，`LoadTypeLib` 返回 `0x8002801C`）。
- 驱动 COM 的宿主进程需要管理员权限，否则 `0x80080005 CO_E_SERVER_EXEC_FAILURE`。
- 官方宏库（`macros/`）只覆盖比例推断、置信区间模拟、随机抽样、条形图；回归/DOE 类无官方宏，
  由 `macro_generator` 生成宏或走 COM。
- 图形命令的完成判定以 PNG 落盘为准（`MinitabSession.run_macro_with_artifact`）。

## 许可与第三方资料

- 本仓库代码：自行选择许可（如 MIT）。
- `reference/` 中的 **Minitab 官方会话命令参考**与 `macros/` 中的官方宏属 **Minitab, LLC** 版权资料，
  未包含在版本库中（见 `.gitignore`）。使用时请自行从官方渠道获取并遵守其许可条款。
