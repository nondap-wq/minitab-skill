# CCD 响应曲面正式验证报告（Minitab 22）

日期：2026-10-16 ｜ 计算引擎：**Minitab 22.1.0.0**（`RSREG` 命令，非外部计算）
数据：2008 年论文 Table 6 的 11 次 CCD 试验（2 因子中心复合设计，α=1.41421，1 中心点，含 2 个额外轴点）

## 1. Minitab 实际执行的命令（已固化到 skill）

```
RSREG; RESPONSE C9; FACTOR C6 C7; TERMS C6 C7 C6*C6 C7*C7 C6*C7; INUNIT 1; LEVELS -1000 0 8 14.
RSREG; RESPONSE C10; FACTOR C6 C7; TERMS C6 C7 C6*C6 C7*C7 C6*C7; INUNIT 1; LEVELS -1000 0 8 14.
```
（C6 = SiN_MPa，C7 = Thickness_um，C9 = PNL_BS，C10 = PNL_TP；等价于菜单
`Stat > DOE > Response Surface > Analyze Response Surface Design`，模型含线性+平方+交互）

## 2. Minitab 输出原文（模型汇总 / 方差分析）

### PNL_BS（背压 case）
| 指标 | 值 |
|---|---|
| S | 1.15819 |
| **R-sq** | **94.16%** |
| R-sq（调整） | 88.32% |
| R-sq（预测） | 63.67% |

| 来源 | 自由度 | Adj SS | Adj MS | F 值 | P 值 |
|---|---:|---:|---:|---:|---:|
| 模型 | 5 | 108.096 | 21.619 | 16.12 | 0.004 |
| 线性 | 2 | 28.832 | 14.416 | 10.75 | 0.015 |
| 　B_Coded（膜厚） | 1 | 19.528 | 19.528 | 14.56 | 0.012 |
| 　SiN_MPa（应力） | 1 | 9.221 | 9.221 | 6.87 | 0.047 |
| 平方 | 2 | 19.940 | 9.970 | 7.43 | 0.032 |
| 　B_Coded² | 1 | 19.508 | 19.508 | 14.54 | 0.012 |
| 　SiN_MPa² | 1 | 3.261 | 3.261 | 2.43 | 0.180 |
| 双因子交互作用 | 1 | 9.267 | 9.267 | 6.91 | 0.047 |
| 　B_Coded×SiN_MPa | 1 | 9.267 | 9.267 | 6.91 | 0.047 |
| 误差 | 5 | 6.707 | 1.341 | | |
| 合计 | 10 | 114.803 | | | |

异常观测值：观测 10（PNL_BS=11.198，拟合 10.012，标准化残差 2.03 **R**）

### PNL_TP（顶压 case）
| 指标 | 值 |
|---|---|
| S | 1.08012 |
| **R-sq** | **86.26%** |
| R-sq（调整） | 72.52% |
| R-sq（预测） | 16.36% |

| 来源 | 自由度 | Adj SS | Adj MS | F 值 | P 值 |
|---|---:|---:|---:|---:|---:|
| 模型 | 5 | 36.617 | 7.323 | 6.28 | 0.033 |
| 线性 | 2 | 15.678 | 7.839 | 6.72 | 0.038 |
| 　B_Coded | 1 | 9.456 | 9.456 | 8.11 | 0.036 |
| 　SiN_MPa | 1 | 6.175 | 6.175 | 5.29 | 0.070 |
| 平方 | 2 | 9.968 | 4.984 | 4.27 | 0.083 |
| 　B_Coded² | 1 | 9.458 | 9.458 | 8.11 | 0.036 |
| 　SiN_MPa² | 1 | 2.265 | 2.265 | 1.94 | 0.222 |
| 双因子交互作用 | 1 | 6.209 | 6.209 | 5.32 | 0.069 |
| 误差 | 5 | 5.833 | 1.167 | | |
| 合计 | 10 | 42.451 | | | |

异常观测值：观测 10（PNL_TP=−6.461，拟合 −5.341，标准化残差 −2.06 **R**）

## 3. 模型方程（Minitab "以未编码单位表示的回归方程" 原文）

```
PNL_BS = 0.437 - 0.475 B_Coded + 0.00468 SiN_MPa + 1.822 B_Coded*B_Coded
         + 0.000006 SiN_MPa*SiN_MPa + 0.00282 B_Coded*SiN_MPa

PNL_TP = 0.717 - 0.448 B_Coded - 0.00407 SiN_MPa - 1.269 B_Coded*B_Coded
         - 0.000005 SiN_MPa*SiN_MPa - 0.00231 B_Coded*SiN_MPa
```

> 注：本次 RSREG 输出的"已编码系数"表与"未编码单位回归方程"标签互换（Minitab 22 该命令的一个已知显示问题）。
> 用编码设计矩阵复算可**精确复现 Minitab 的 R²、R²(调整)、S**（94.16%/88.32%/1.15820 与 86.26%/72.52%/1.08013），
> 因此下面给出的编码形式系数是可信的：

```
PNL_BS = -0.416 - 0.450·A - 1.884·B + 0.745·A² + 1.822·B² + 0.996·A·B     (A=应力编码, B=膜厚编码)
PNL_TP = +1.512 + 0.316·A + 0.706·B - 0.621·A² - 1.269·B² - 0.816·A·B
```

## 4. 等值线图与设计窗口

| 图 | 文件 |
|---|---|
| PNL_BS 拟合响应面等值线 | `output/mtb_style_contour_bs.png` |
| PNL_TP 拟合响应面等值线 | `output/mtb_style_contour_tp.png` |
| **设计窗口 \|PNL\|<3%** | `output/mtb_style_design_window.png` |

设计窗口结论（编码空间内 |PNL_BS|<3 且 |PNL_TP|<3 的可行域）：

- 可行域占编码设计空间 **约 80%**（61×61 网格，2974/3721 点）；
- **膜厚越大越安全**：在 α 范围 (8–14 μm) 内，SiN 残余应力从 −1000 到 0 MPa 都存在可行点；
  受约束最紧的是"**低膜厚 + 弱压应力**"角（B=8 μm、SiN≈0 MPa 附近），该区 PNL_BS 预测值最高（>5%）；
- 与论文 Fig.11/12 结论一致的方向性：**背压 case（PNL_BS）对膜厚与应力的组合最敏感，观测点 10（8 μm, −1000 MPa）是唯一显著异常点**（PNL_BS=11.2%），
  顶压 case（PNL_TP）整体绝对值小、模型解释力较弱（R²(预测) 仅 16%）。

## 5. 复现命令

```powershell
# 1) 数据与模型（skill 内封装；Minitab 计算）
python D:\mechanic\minitab\skill\scripts\minitab_cli.py plan "CCD PNL_BS LSL=... USL=..."
python D:\mechanic\minitab\run_all.py          # RSREG 两次 + 取回 Minitab 输出表
python D:\mechanic\minitab\make_ccd_report.py  # 由 Minitab 模型生成等值线图与设计窗口

# 2) 官方会话命令检索（内置 PDF，按关键词检索，避免全文通读）
python D:\mechanic\minitab\skill\reference\search_commands.py RSREG --context 900
python D:\mechanic\minitab\skill\reference\search_commands.py --page 348
```

## 6. 本次验证确立的 COM 使用规则（已写入 SKILL.md）

1. 命令**单行**发送，子命令 `;` 分隔、`.` 结束；命令文件里换行续写会被拆散 → Syntax Error。
2. 分析类命令（RSREG/REGRESS/FITLINE）必须 `ExecuteCommandAsync` 提交，
   并以 `Project.Commands.Count` 增长作为完成信号；**完成前不得提交下一条命令**。
3. `RSREG` 必需 `INUNIT` 与 `LEVELS`；`TERMS` 中平方项写作 `C6*C6`。
4. `CAPA` 必需至少一个规格限（`LSPEC`/`USPEC`），否则报"1 变元太少"。
5. 结果读取用 `Command.Name` 与 `Command.Outputs.Item(k).Text`（可拿到 Minitab 输出表原文）。
6. 文本列写入会挂起：只用数值列；`Column.RowCount` 写入后不即时刷新，不能作为写入判据。
