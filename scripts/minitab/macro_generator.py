"""宏生成层 —— 设计流程的第③步："若宏库中不存在可用宏，则尝试编写宏文件"。

产出的是**标准 Minitab 宏**（`GMACRO ... ENDMACRO`），而不是普通命令文件：
带参数、可被 `%NAME args` 或 `EXECUTE` 调用，能直接接受用户数据与要求。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = SKILL_ROOT / "runtime" / "generated_macros"


@dataclass
class MacroPlan:
    name: str
    path: str
    kind: str                      # "official" | "generated"
    purpose: str
    invocation: str                # 发给 Minitab 的调用命令（单行）
    args: list[str] = field(default_factory=list)
    body: str = ""
    source_macro: str = ""         # 官方宏时的 rel_path
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_name(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", (text or "MtbTask").strip())
    return (s[:24] or "MtbTask").upper()


# --------------------------------------------------------------- official macro
def plan_official(entry: dict, args: list[str] | None = None) -> MacroPlan:
    """把命中的官方宏包装成可直接调用的一行命令。"""
    name = Path(entry.get("rel_path", entry["name"])).stem.upper()
    args = args or []
    invocation = "%" + name + ((" " + " ".join(str(a) for a in args)) if args else "")
    return MacroPlan(
        name=name,
        path=str(SKILL_ROOT / "macros" / entry.get("rel_path", "")),
        kind="official",
        purpose=entry.get("purpose", ""),
        invocation=invocation,
        args=[str(a) for a in args],
        source_macro=entry.get("rel_path", ""),
        notes=[
            f"官方宏命令：{', '.join(entry.get('commands', [])[:8])}",
            "交互式宏（等待键盘输入）不适合无人值守；批处理宏可直接调用" if entry.get("interactive")
            else "批处理宏：可无人值守调用",
        ],
    )


# -------------------------------------------------------------- generated macro
def build_rsm_macro(response_col: str, factor_cols: list[str], terms: str,
                    levels: str, fits_col: str, resid_col: str,
                    contour_png: str | None = None, name: str = "MTB_RSM",
                    inunit: int = 1) -> MacroPlan:
    """生成标准的响应曲面宏（全二次模型 + 可选等值线出图）。

    宏体使用真机验证过的单行命令形式（子命令 ';' 分隔、'.' 结束）。
    """
    name = _safe_name(name)
    factors = " ".join(factor_cols)
    lines = [
        f"GMACRO",
        f"  # {name}: 响应曲面拟合（最小二乘全二次模型）",
        f"  NOTE === {name} start ===",
        f"  RSREG; RESPONSE {response_col}; FACTOR {factors}; TERMS {terms}; INUNIT {inunit}; LEVELS {levels}; FITS {fits_col}; RESIDUALS {resid_col}.",
    ]
    if contour_png:
        lines.append(f'  CONTOURPLOT {fits_col} {factor_cols[1]} {factor_cols[0]}; GSAVE "{contour_png}".')
    lines += [f"  NOTE === {name} done ===", "ENDMACRO"]
    body = "\n".join(lines) + "\n"

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{name}.MAC"
    path.write_text(body, encoding="ascii", errors="replace")
    return MacroPlan(
        name=name,
        path=str(path),
        kind="generated",
        purpose=f"响应曲面：{response_col} ~ {factors}",
        invocation=f'%{name}',
        args=[response_col, *factor_cols],
        body=body,
        notes=[
            "宏已写入 skill/runtime/generated_macros/，Minitab 需能访问该路径（可用 EXECUTE 绝对路径调用）",
            "若宏调用失败，直接回退到 COM 单行命令（com_executor / doe_rsm）",
        ],
    )


def build_chart_macro(z_col: str, y_col: str, x_col: str, png: str,
                      name: str = "MTB_CHART") -> MacroPlan:
    name = _safe_name(name)
    body = "\n".join([
        "GMACRO",
        f"  # {name}: 等值线图导出 PNG",
        f"  NOTE === {name} start ===",
        f'  CONTOURPLOT {z_col} {y_col} {x_col}; GSAVE "{png}".',
        f"  NOTE === {name} done ===",
        "ENDMACRO",
    ]) + "\n"
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{name}.MAC"
    path.write_text(body, encoding="ascii", errors="replace")
    return MacroPlan(
        name=name, path=str(path), kind="generated",
        purpose=f"等值线图 {z_col} over ({x_col},{y_col})",
        invocation=f"%{name}", args=[z_col, y_col, x_col], body=body,
        notes=["图形宏：调用后以 PNG 是否落盘作为完成信号（见 doe_rsm.MinitabSession.run_macro_with_artifact）"],
    )


def write_plan(plan: MacroPlan, out_dir: str | Path | None = None) -> Path:
    d = Path(out_dir) if out_dir else GENERATED_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{plan.name}_plan.json"
    p.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return p
