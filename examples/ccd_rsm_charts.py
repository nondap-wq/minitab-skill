# -*- coding: utf-8 -*-
"""
CCD 响应曲面 + 等高线/曲面图（Minitab 原生图表）—— 已验证可运行示例
====================================================================

真机验证环境：Minitab 20.0（Mtb 20.0 Type Library），Python 3.12 64-bit + pywin32
验证日期：2026-10-28
验证数据：2 因子 CCD，α=1.414（4 角点 + 4 轴向 + 1 中心点），另加 2 个验证点

产出 4 张 Minitab 原生图：
  1. CONTOURPLOT  原始数据等高线      Stress * Si3N4 * SiO2
  2. SURFACEPLOT  原始数据 3D 曲面
  3. CONTOURPLOT  模型等高线（画 FITS 列）  <- 响应曲面等值线
  4. SURFACEPLOT  模型 3D 曲面

关键规则（踩过的坑，务必逐条遵守）
----------------------------------
1) COM 启动的 Minitab 默认 ``UserInterface.Visible = False``（无头）。
   此时会话命令被**静默丢弃**：不执行、不报错、Commands.Count 不增长。
   → 必须先 ``UI.Visible = True`` 并等待约 3 s 让窗口初始化。
2) ``DisplayAlerts`` 必须保持 **True**。设成 False 会吞掉错误报告，
   出错命令留下的未决状态把命令队列**永久卡死**（后续一律
   "正忙于处理操作"）。保持 True 时错误会以 ``Syntax Error`` 作为命令名登记，
   可据此逐条迭代语法。
3) ``CONTOURPLOT`` / ``SURFACEPLOT`` 的列必须用 **星号** 分隔：``z*y*x``。
   空格形式 → Syntax Error。命令名是 ``SURFACEPLOT``（**没有** SURFPLOT）。
4) ``RSREG`` 必需子命令：``RESPONSE / FACTOR / TERMS / INUNIT / LEVELS``。
   - ``TERMS`` 不能省，否则报「TERMS 是所要求的子命令」
   - **没有** ``FIT`` 子命令（存拟合值用 ``FITS C``）
   - **没有** ``CONTOUR`` / ``SURFACE`` 子命令（模型等值线请用 CONTOURPLOT 画 FITS 列）
   - 拼写是 ``TSUMMARY``（不是 TSUMMARY 之外的变体；少一个 U 会被截断报「TSMM 失序」）
5) ``IColumn.SetData`` 是**整体替换**语义，列表里不能有 None；
   列长度不一致时先写主体、再 ``SetData([v1,v2], StartRow=10, NumRows=2)`` 追加。
6) 工作表的列要先用 ``Columns.Add(Quantity=n)`` 建出来（新项目列数为 0）。
   列名用 ``col.Name``（``col.Label`` 只读）。

用法
----
    python ccd_rsm_charts.py                 # 用内置示例数据
    python ccd_rsm_charts.py --out D:\\tmp\\out
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import win32com.client as w

sys.stdout.reconfigure(encoding="utf-8")

# --------------------------------------------------------------------------
# 示例数据：2 因子 CCD（α=1.414）+ 2 个验证点
#   C1/C2 编码因子，C3/C4 实际因子（nm），C5 响应（MPa）
# --------------------------------------------------------------------------
A_CODED = [0, 1, -1, 1, -1, 0, 1.414, 0, -1.414]
B_CODED = [0, 1, 1, -1, -1, 1.414, 0, -1.414, 0]
SIO2 = [200, 270.7, 129.3, 270.7, 129.3, 200, 300, 200, 100]
SI3N4 = [300, 370.7, 370.7, 229.3, 229.3, 400, 300, 200, 300]
STRESS = [55.167, 55.169, 55.176, 55.158, 55.164, 55.175, 55.162, 55.158, 55.171]

# 验证点（只有实际因子 + 响应，编码因子留空）
VERIFY = {3: (100.0, 300.0), 4: (400.0, 200.0), 5: (55.180, 55.154)}

# 因子水平（未编码，供 RSREG 的 INUNIT 1 + LEVELS 使用）
LEVELS = "100 300 200 400"


def connect():
    """连接 Minitab 并完成必做的会话初始化。"""
    mtb = w.Dispatch("Mtb.Application")
    ui = mtb.UserInterface
    ui.Visible = True          # 规则 1：不设 True 则命令被静默丢弃
    ui.Interactive = True
    ui.DisplayAlerts = True    # 规则 2：必须 True，否则吞错 + 卡死队列
    time.sleep(3.0)            # 等窗口初始化
    return mtb, ui


def seed_worksheet(proj):
    """写数据到工作表，返回列集合。"""
    ws = proj.ActiveWorksheet
    cols = ws.Columns
    if cols.Count < 8:
        cols.Add(Quantity=8 - cols.Count)     # 规则 6：先建列

    pairs = [
        (1, "A_center", A_CODED),
        (2, "B_center", B_CODED),
        (3, "SiO2_thk", SIO2),
        (4, "Si3N4_thk", SI3N4),
        (5, "MeanStress", STRESS),
    ]
    for idx, name, vals in pairs:
        col = cols.Item(idx)
        col.SetData([float(v) for v in vals])
        col.Name = name

    # 规则 5：验证点用 StartRow 追加
    for idx, (v1, v2) in VERIFY.items():
        cols.Item(idx).SetData([v1, v2], 10, 2)
    return ws, cols


def submit(proj, cmd, label, timeout=90):
    """异步提交一条单行命令，用 Commands.Count 增长判定是否被接收。"""
    commands = proj.Commands
    n0 = commands.Count
    try:
        proj.ExecuteCommandAsync(cmd)
    except Exception as exc:                       # 队列忙等情况
        print("    %-22s SUBMIT-ERR %s" % (label, str(exc)[:80]), flush=True)
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.3)
        if commands.Count > n0:
            time.sleep(1.2)                        # 让输出/图形落盘
            try:
                name = commands.Item(commands.Count).Name
            except Exception:
                name = "?"
            bad = "Syntax" in str(name) or "错误" in str(name)
            print("    %-22s %s %r" % (label, "ERR" if bad else "OK ", name), flush=True)
            return not bad
    print("    %-22s *** HANG *** —— 99%% 是弹窗阻塞，请人工查看 Minitab 窗口" % label,
          flush=True)
    return False


def export_chart(proj, cmd, png, label):
    """执行图形命令并轮询 PNG 落盘。"""
    if os.path.exists(png):
        os.remove(png)
    if not submit(proj, cmd, label):
        return False
    for _ in range(60):
        if os.path.exists(png) and os.path.getsize(png) > 0:
            time.sleep(1.5)
            print("        -> %s  %d bytes"
                  % (os.path.basename(png), os.path.getsize(png)), flush=True)
            return True
        time.sleep(0.5)
    print("        -> %s MISSING" % os.path.basename(png), flush=True)
    return False


def dump_outputs(proj, outdir):
    """把 Minitab 会话输出原文落盘。

    Mtb 20：命令对象有 ``OutputDocument``（无 ``Outputs``）；
    Mtb 22：旧文档记录为 ``Outputs.Item(k).Text``。两种都试一遍。
    """
    commands = proj.Commands
    written = 0
    for i in range(1, commands.Count + 1):
        try:
            cm = commands.Item(i)
            title = cm.Name
        except Exception:
            continue
        text = ""
        try:
            od = cm.OutputDocument
            if od is not None:
                text = getattr(od, "Text", "") or ""
        except Exception:
            pass
        if not text.strip():
            try:
                outs = cm.Outputs
                for k in range(1, outs.Count + 1):
                    t = getattr(outs.Item(k), "Text", "") or ""
                    if t.strip():
                        text += t
            except Exception:
                pass
        if text.strip():
            fn = os.path.join(outdir, "minitab_output_%02d.txt" % i)
            with open(fn, "w", encoding="utf-8") as fh:
                fh.write("COMMAND: %s\n\n%s" % (title, text))
            print("    wrote %s (%d chars)" % (os.path.basename(fn), len(text)), flush=True)
            written += 1
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="CCD 响应曲面 + Minitab 原生等高线/曲面图")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "..", "runtime", "artifacts", "ccd_charts"))
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    mtb, _ui = connect()
    proj = mtb.ActiveProject
    _ws, cols = seed_worksheet(proj)
    print("[1] 数据写入完成：C3/C4/C5 共 11 行（9 设计点 + 2 验证点）", flush=True)

    # ---- 拟合全二次响应曲面（未编码单位）--------------------------------
    print("\n[2] RSREG 全二次模型", flush=True)
    rsreg = ("RSREG; RESPONSE C5; FACTOR C3 C4; "
             "TERMS C3 C4 C3*C3 C4*C4 C3*C4; "
             "INUNIT 1; LEVELS %s; "
             "TSUMMARY; TANOVA; TCOEFFICIENT; TEQUATION; "
             "FITS C6; RESIDUALS C7." % LEVELS)
    fitted = submit(proj, rsreg, "RSREG fit")
    time.sleep(2)
    n_fit = cols.Item(6).RowCount
    print("    拟合值列 C6 行数 = %d" % n_fit, flush=True)

    # ---- 4 张原生图 -----------------------------------------------------
    print("\n[3] Minitab 原生图表", flush=True)
    charts = [
        ('CONTOURPLOT C5*C4*C3; GSAVE "%s".' % os.path.join(out, "01_contour_rawdata.png"),
         "01_contour_rawdata.png", "contour(raw)"),
        ('SURFACEPLOT C5*C4*C3; GSAVE "%s".' % os.path.join(out, "02_surface_rawdata.png"),
         "02_surface_rawdata.png", "surface(raw)"),
        ('CONTOURPLOT C6*C4*C3; GSAVE "%s".' % os.path.join(out, "03_contour_model.png"),
         "03_contour_model.png", "contour(model)"),
        ('SURFACEPLOT C6*C4*C3; GSAVE "%s".' % os.path.join(out, "04_surface_model.png"),
         "04_surface_model.png", "surface(model)"),
    ]
    ok = 0
    for cmd, png, label in charts:
        if export_chart(proj, cmd, os.path.join(out, png), label):
            ok += 1

    # ---- 会话输出 -------------------------------------------------------
    print("\n[4] Minitab 会话输出", flush=True)
    n_txt = dump_outputs(proj, out)

    # ---- 汇总 -----------------------------------------------------------
    with open(os.path.join(out, "_result.json"), "w", encoding="utf-8") as fh:
        json.dump({"rsreg_ok": fitted, "charts_ok": ok, "text_outputs": n_txt,
                   "outdir": out}, fh, ensure_ascii=False, indent=2)

    print("\n[5] 产物清单", flush=True)
    for fp in sorted(glob.glob(os.path.join(out, "*.png"))):
        print("    %-30s %8d" % (os.path.basename(fp), os.path.getsize(fp)), flush=True)
    print("\nDONE -> %s" % out, flush=True)
    return 0 if (fitted and ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
