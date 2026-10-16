# Minitab COM 自动化 AI Skill —— 真机验证记录

环境：Windows 11 (10.0.26200)，Minitab 22.1.0.0（`D:\Program Files\Minitab\Mtb.exe`），Python 3.12.4 (64-bit) + pywin32。
验证时间：2026-10-16 12:11。

## 1. 结果（一次真机调用，未做任何人工干预）

| 项 | 值 |
|---|---|
| 输入 | `capability C1 LSL=9 USL=17 subgroup 1` |
| 生成命令 | `CAPA C1 1; LSPEC 9; USPEC 17; GSAVE "D:\mechanic\minitab\output\capa_chart.png".` |
| 执行耗时 | 0.37 s（连接 1.83 s，全程 ~3 s） |
| Minitab 输出条目 | `Thickness 的过程能力报告`（2 个输出对象） |
| 图表 | `output\capa_chart.png`（32 085 B，748×561，A 方案 GSAVE 成功） |
| 证据 | `skill\runtime\deliverable\result.json`、`capa.log` |

## 2. Minitab 报告数值 vs 独立复算（Python statistics）

数据：30 个测量值，均值 13.76，最小 10.2，最大 16.4，LSL=9，USL=17，子组大小 1。

| 统计量 | Minitab（整体/组内） | Python 复算 | 一致性 |
|---|---|---|---|
| 样本均值 | 13.76 | 13.760 | ✅ |
| 标准差（整体） | 1.49496 | 1.4950 | ✅ |
| 标准差（组内，移动极差法） | 1.44595 | —（Minitab 特有估计） | n/a |
| 观测 PPM < LSL / > USL | 0.00 / 0.00 | （数据全在规格内） | ✅ |
| 预期 PPM < LSL / > USL（整体） | 726.18 / 15106.51 | 726.2 / 15106.5 | ✅ |
| 合计 PPM（整体） | 15832.69 | 15832.7 | ✅ |
| 预期 PPM（组内） | 497.48 / 12521.54 | — | n/a |

能力指数（直接读取 Minitab 报告）：

| 指数 | 整体 | 潜在（组内） |
|---|---|---|
| Cp / Pp | Pp 0.89 | Cp 0.92 |
| CPL / PPL | PPL 1.06 | CPL 1.10 |
| CPU / PPU | PPU 0.72 | CPU 0.75 |
| **Cpk / Ppk** | **Ppk 0.72** | **Cpk 0.75** |
| Cpm | *（未指定目标值） | — |

**结论**：过程均值 13.76 相对规格中心 13.0 偏上，上限侧能力不足（PPU 0.72 < PPL 1.06）；整体 Ppk 0.72 < 1.00，过程能力不足，主要改善方向是**降低均值偏移**（向 13.0 靠拢）并压缩整体波动。

## 3. 本次真机验证到的 COM 行为（已固化进实现）

1. **命令名是 `CAPA`**（不是 `CAPABILITY`），语法 `CAPA [C...C E]`：列 + 子组大小（常量或列）。
2. **子命令必须与主命令在同一行**，用 `;` 分隔、以 `.` 结束：
   - `CAPA C1 1; LSPEC 9; USPEC 17.` ✅
   - 分成多次 `ExecuteCommand` 调用 → `* 错误 * 未知 Minitab 命令: LSPEC`
   - 用换行组成多行块 → 报 `未知 Minitab 命令: C1`
   - 用 `ExecuteCommandAsync` 逐行发子命令 → `Minitab 正忙于处理操作`
3. **必须至少给出 `USPEC` 或 `LSPEC`**，否则报 `* 错误 * 1 变元太少`（生成器已改为前置校验并给出可读提示）。
4. 图形导出用子命令 `GSAVE "路径"`（默认 PNG），无需额外 COM 调用。
5. **列写入**：`Columns.Item(i).SetData(list, 1, n)` 只可靠支持数值列；写文本列会挂起（已避免）。
6. **输出读取**：`IOutput` 在 v22 晚期绑定下没有 `OutputDocument` 属性；应读 `Command.Name`（即分析标题，如 `Thickness 的过程能力报告`）。
7. 宿主进程需管理员权限：非提权 `Dispatch` 报 `0x80080005 CO_E_SERVER_EXEC_FAILURE`。
8. Minitab 17 及更早版本不可自动化（typelib 为 Windows 无法解析的私有格式，`0x8002801C`）。

## 4. 复现命令

```powershell
# 1) 环境预检
python D:\mechanic\minitab\skill\scripts\minitab_cli.py doctor

# 2) 意图→命令生成（不执行）
python D:\mechanic\minitab\skill\scripts\minitab_cli.py plan "capability C1 LSL=9 USL=17 subgroup 1"

# 3) 真机执行（附图导出）
python D:\mechanic\minitab\deliver_capa.py
# 等价于向 Minitab 发送：CAPA C1 1; LSPEC 9; USPEC 17; GSAVE "D:\mechanic\minitab\output\capa_chart.png".

# 4) 离线闭环（无需 Minitab）
python D:\mechanic\minitab\skill\scripts\minitab_cli.py demo
```
