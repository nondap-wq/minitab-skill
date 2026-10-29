"""DOE / 响应曲面（CCD）工作流 —— 全部由 Minitab 自身计算。

真机验证过的事实（Minitab 20 / 22 + COM，记录见 runtime/evidence/）：

0. **COM 启动的 Minitab 默认 `UserInterface.Visible = False`（无头）**，此时会话命令
   被**静默丢弃**：不执行、不报错、`Commands.Count` 不增长。必须先设 `Visible = True`。
   `DisplayAlerts` 必须保持 **True**：设 False 会吞掉错误报告并把命令队列永久卡死。
1. 命令必须**单行**发送，子命令用 ';' 分隔、以 '.' 结束。
   跨行续写（.mtb 文件里换行）会被拆成独立命令 → "Syntax Error"。
2. 模型类命令（RSREG/REGRESS/FITLINE）应使用 `ExecuteCommandAsync` 提交，
   并轮询 `Project.Commands.Count` 增长判断是否被**受理**；完成前**不能**再提交命令
   （否则报 "Minitab 正忙于处理操作"）。注意 Count 增长不代表算完，出图需再等文件落盘。
3. RSREG 必需子命令：RESPONSE / FACTOR / TERMS / INUNIT / LEVELS
   - `TERMS` 不可省，否则报 "* 错误 * TERMS 是所要求的子命令"
   - **没有** `FIT` 子命令（报"子命令 FIT 失序"）→ 存拟合值用 `FITS C`
   - **没有** `CONTOUR`/`SURFACE` 子命令（报"子命令 CONT 失序"）
     → 模型等值线用 `CONTOURPLOT` 画拟合值列
   - 结果表拼写：`TSUMMARY` / `TANOVA` / `TCOEFFICIENT` / `TEQUATION`
   - TERMS 里平方项写成 `C6*C6`（列号*列号），不能用 `A*A` 形式的名字。
4. CAPA 必需规格限：`CAPA C1 1; LSPEC 9; USPEC 17.`
5. 图形命令的列必须用**星号**分隔：`CONTOURPLOT z*y*x`；命令名是 `SURFACEPLOT`。
6. 结果读取：`Command.Name` 是分析标题；输出原文
   **Mtb 20** 用 `Command.OutputDocument.Text`，**Mtb 22** 用 `Command.Outputs.Item(k).Text`。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

# --------------------------------------------------------------------------
# 命令模板（全部为真机验证通过的单行形式）
# --------------------------------------------------------------------------
COMMANDS = {
    # 过程能力：CAPA [列] <子组大小>; LSPEC/USPEC/TARGET 子命令
    "capability": "CAPA {cols} {subgroup}; {subcommands}.",
    # 响应曲面（最小二乘、全二次）：必需 INUNIT 与 LEVELS
    "rsreg": (
        "RSREG; RESPONSE {response}; FACTOR {factors}; TERMS {terms}; "
        "INUNIT {inunit}; LEVELS {levels}{extra}."
    ),
    # 一般回归：REGRESS 需要 RESPONSE + CONTINUOUS 子命令（真机报"1 变元太多"即此因）
    "regress": "REGRESS; RESPONSE {response}; CONTINUOUS {predictors}.",
    # 等值线：z * y * x（z 为被绘制变量，y 为纵轴，x 为横轴）
    # 注意：列之间必须用 **星号** 分隔；空格形式会报 Syntax Error（Minitab 20/22 真机验证）
    "contour": 'CONTOURPLOT {z}*{y}*{x}; GSAVE "{png}".',
    # 3D 曲面：同样是星号分隔；命令名是 SURFACEPLOT（没有 SURFPLOT）
    "surface": 'SURFACEPLOT {z}*{y}*{x}; GSAVE "{png}".',
    "surface_data": "LET {target} = {expr}",
    "describe": "DESCRIBE {cols}.",
    "histogram": "HISTOGRAM {cols}.",
}


def capability_command(columns: str, lsl: float | None = None, usl: float | None = None,
                       target: float | None = None, subgroup: int = 1) -> str:
    subs = []
    if lsl is not None:
        subs.append(f"LSPEC {lsl:g}")
    if usl is not None:
        subs.append(f"USPEC {usl:g}")
    if target is not None:
        subs.append(f"TARGET {target:g}")
    if not subs:
        raise ValueError("CAPA 需要至少一个规格限（LSPEC/USPEC）")
    return COMMANDS["capability"].format(cols=columns, subgroup=subgroup, subcommands="; ".join(subs))


def rsreg_command(response: str, factors: str, terms: str, levels: str,
                  coded: bool = False, fits: str | None = None,
                  residuals: str | None = None, extra: str = "") -> str:
    """Build a verified RSREG command.

    factors  : e.g. "C6 C7"（未编码因子列）或 "C4 C5"（编码因子列）
    terms    : e.g. "C6 C7 C6*C6 C7*C7 C6*C7"（平方项必须写成 列*列）
    levels   : 未编码水平 "低1 高1 低2 高2"，例如 "-1000 0 8 14"
    coded    : False -> INUNIT 1（列里是未编码值）；True -> INUNIT 0（列里是编码值）
    """
    store = ""
    if fits:
        store += f"; FITS {fits}"
    if residuals:
        store += f"; RESIDUALS {residuals}"
    return COMMANDS["rsreg"].format(
        response=response, factors=factors, terms=terms,
        inunit=0 if coded else 1, levels=levels, extra=store + extra,
    )


def contour_command(z: str, y: str, x: str, png: str | Path) -> str:
    return COMMANDS["contour"].format(z=z, y=y, x=x, png=png)


# --------------------------------------------------------------------------
# Minitab 会话封装：唯一被验证可靠的提交/等待模式
# --------------------------------------------------------------------------
class MinitabSession:
    """Thin wrapper implementing the verified submit-and-wait protocol."""

    def __init__(self, visible: bool = True):
        import pythoncom
        import win32com.client
        from win32com.client import gencache

        pythoncom.CoInitialize()
        try:
            self.app = gencache.EnsureDispatch("Mtb.Application")
        except Exception:
            self.app = win32com.client.dynamic.Dispatch("Mtb.Application")
        try:
            self.app.UserInterface.Visible = visible
        except Exception:  # noqa: BLE001
            pass
        # DisplayAlerts 必须保持 True：设 False 会吞掉错误报告，出错命令留下的
        # 未决状态会把命令队列永久卡死（后续一律报"正忙于处理操作"）。
        try:
            self.app.UserInterface.DisplayAlerts = True
            self.app.UserInterface.Interactive = True
        except Exception:  # noqa: BLE001
            pass
        # 无头模式（Visible=False）下命令会被静默丢弃，等窗口初始化
        if visible:
            time.sleep(3)
        project = self.app.ActiveProject
        if project is None:
            self.app.New()
            project = self.app.ActiveProject
        self.project = project
        self.ws = project.ActiveWorksheet

    # ------------------------------------------------------------- data
    def write_column(self, index: int, name: str, values: list[float]) -> None:
        while self.ws.Columns.Count < index:
            self.ws.Columns.Add()
        col = self.ws.Columns.Item(index)
        col.SetData([float(v) for v in values], 1, len(values))
        col.Name = name

    def read_column(self, index: int, rows: int) -> list[float]:
        col = self.ws.Columns.Item(index)
        return [float(v) for v in list(col.GetData(rows, 1))]

    def command_count(self) -> int:
        try:
            return int(self.project.Commands.Count)
        except Exception:  # noqa: BLE001
            return -1

    # ------------------------------------------------------- submission
    def submit_sync(self, command: str) -> None:
        """For light commands (LET/DESCRIBE/HISTOGRAM/CONTOURPLOT)."""
        self.project.ExecuteCommand(command)

    def submit_and_wait(self, command: str, timeout: float = 240,
                        on_poll: Callable[[int, float], None] | None = None) -> tuple[bool, float]:
        """For analysis commands: async submit + history-growth gate (verified protocol)."""
        before = self.command_count()
        self.project.ExecuteCommandAsync(command)
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(3)
            now = self.command_count()
            if on_poll:
                on_poll(now, time.time() - t0)
            if now > before:
                return True, time.time() - t0
        return False, time.time() - t0

    # ---------------------------------------------------------- results
    def read_outputs(self, want: str = "") -> list[dict]:
        """Return Minitab's own output tables: [{name, texts:[...]}, ...]."""
        out: list[dict] = []
        n = self.command_count()
        for i in range(1, n + 1):
            cmd = self.project.Commands.Item(i)
            try:
                name = str(cmd.Name)
            except Exception:  # noqa: BLE001
                name = ""
            if want and want not in name:
                continue
            texts = []
            # 输出读取因 Minitab 版本而异：
            #   Mtb 20 -> Command.OutputDocument.Text（IMTBCommand 没有 Outputs 属性）
            #   Mtb 22 -> Command.Outputs.Item(k).Text（旧记录）
            try:
                od = cmd.OutputDocument
                if od is not None:
                    t = str(getattr(od, "Text", "") or "")
                    if t.strip():
                        texts.append(t)
            except Exception:  # noqa: BLE001
                pass
            if not texts:
                try:
                    outs = cmd.Outputs
                except Exception:  # noqa: BLE001
                    outs = None
                if outs is not None:
                    for k in range(1, outs.Count + 1):
                        try:
                            texts.append(str(outs.Item(k).Text))
                        except Exception:  # noqa: BLE001
                            continue
            out.append({"name": name, "texts": texts})
        return out

    def save_project(self, path: str | Path) -> None:
        self.project.SaveAs(str(path), True, 22)

    # ------------------------------------------------- 宏 / 图形 完成信号
    def run_macro_with_artifact(self, invocation: str, artifact: str | Path,
                               timeout: float = 240, poll: float = 3.0) -> tuple[bool, float]:
        """调用宏（或命令）后，以**产物文件落盘**作为完成信号。

        图形类命令（CONTOURPLOT+ GSAVE）不会立刻让 Commands.Count 增长，
        因此必须用产物文件判断；这是"操控 Minitab 出图"的可靠收尾方式。
        """
        art = Path(artifact)
        if art.exists():
            try:
                art.unlink()
            except Exception:  # noqa: BLE001
                pass
        before = self.command_count()
        self.project.ExecuteCommandAsync(invocation)
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(poll)
            if art.exists() and art.stat().st_size > 0:
                return True, time.time() - t0
            if self.command_count() > before:
                # 命令已结束但产物缺失：再给一小段宽限期
                for _ in range(5):
                    time.sleep(poll)
                    if art.exists() and art.stat().st_size > 0:
                        return True, time.time() - t0
                return False, time.time() - t0
        return False, time.time() - t0

    def wait_idle(self, idle_rounds: int = 3, poll: float = 2.0, timeout: float = 300) -> bool:
        """轮询直到命令历史在若干轮内不再增长（Macro 执行完毕的判据）。"""
        last = self.command_count()
        stable = 0
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(poll)
            now = self.command_count()
            if now == last:
                stable += 1
                if stable >= idle_rounds:
                    return True
            else:
                stable = 0
                last = now
        return False

