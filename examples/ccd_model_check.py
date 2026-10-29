# -*- coding: utf-8 -*-
"""
CCD 模型精度校核（纯 Python，不调用 Minitab）
============================================

用途：拿到 Minitab `RSREG` 输出的「已编码系数」后，用它复算各设计点与验证点，
      检查残差量级、确认回归系数抄录无误。

为什么用**编码系数**而不是 Minitab 打印的未编码方程：
      Minitab 的「以未编码单位表示的回归方程」只保留 6 位小数，
      本数据的系数是 1e-5 量级，末项有效位会被截断丢掉。
      编码系数有效位更足，配合编码尺度换算可精确复现每个点。

适用：本文档中的系数取自 2026-10-28 的 CCD 实测（响应单位 MPa，因子单位 nm）。
      换数据集时请替换 `c` 与 `CODE_CENTER` / `CODE_HALF`。
"""
import math


# Minitab UNCODED regression equation (from rsreg_output_01.txt):
# MeanStress = 55.1440 - 1.7e-5*SiO2 + 1.11e-4*Si3N4 - 0*SiO2^2 - 0*Si3N4^2 - 0*SiO2*Si3N4
# The printed coefficients are rounded to 6 dp, so rebuild from CODED coefficients
# (more reliable) using the coding: A = (SiO2-200)/70.71, B = (Si3N4-300)/70.71
# Coded model: y = 55.1669 - 0.004582A + 0.008350B - 0.000271A^2 - 0.000271B^2 - 0.000584AB
c = dict(const=55.1669, A=-0.004582, B=0.008350,
         AA=-0.000271, BB=-0.000271, AB=-0.000584)


def pred(sio2, si3n4):
    A = (sio2 - 200.0) / 70.7107
    B = (si3n4 - 300.0) / 70.7107
    return (c['const'] + c['A'] * A + c['B'] * B
            + c['AA'] * A * A + c['BB'] * B * B + c['AB'] * A * B)


print("=== 设计点核算 (coded-coefficient model) ===")
design = [
    (0, 0, 200, 300, 55.167),
    (1, 1, 270.7, 370.7, 55.169),
    (-1, 1, 129.3, 370.7, 55.176),
    (1, -1, 270.7, 229.3, 55.158),
    (-1, -1, 129.3, 229.3, 55.164),
    (0, 1.414, 200, 400, 55.175),
    (1.414, 0, 300, 300, 55.162),
    (0, -1.414, 200, 200, 55.158),
    (-1.414, 0, 100, 300, 55.171),
]
maxerr = 0.0
for a, b, s, n, y in design:
    p = pred(s, n)
    e = p - y
    maxerr = max(maxerr, abs(e))
    print("  A=%6.3f B=%6.3f  SiO2=%6.1f Si3N4=%6.1f  y=%7.3f  pred=%7.4f  err=%+.5f"
          % (a, b, s, n, y, p, e))
print("  max |err| on design points = %.5f MPa" % maxerr)

print("\n=== 验证点校核 ===")
for i, (s, n, y) in enumerate([(100, 400, 55.180), (300, 200, 55.154)], 1):
    p = pred(s, n)
    print("  验证点%d: SiO2=%d Si3N4=%d  实测=%.3f  模型预测=%.4f  误差=%+.4f MPa  (%.3f%%)"
          % (i, s, n, y, p, p - y, abs(p - y) / y * 100))

print("\n=== 极值（设计域内）===")
best = None
for i in range(0, 401):
    for j in range(0, 401):
        s = 100 + i * 0.5
        n = 200 + j * 0.5
        v = pred(s, n)
        if best is None or v > best[0]:
            best = (v, s, n)
print("  最大平均应力 = %.4f MPa  @ SiO2=%.1f nm, Si3N4=%.1f nm" % best)
worst = None
for i in range(0, 401):
    for j in range(0, 401):
        s = 100 + i * 0.5
        n = 200 + j * 0.5
        v = pred(s, n)
        if worst is None or v < worst[0]:
            worst = (v, s, n)
print("  最小平均应力 = %.4f MPa  @ SiO2=%.1f nm, Si3N4=%.1f nm" % worst)
