"""Layer 1 - intent understanding.

Two interchangeable backends:
  * RuleIntentParser  - deterministic, offline, keyword/pattern based (default; always available)
  * LLMIntentParser   - optional; wraps any callable that returns JSON. Used when the host
                        agent (Codex/DSH) supplies an LLM bridge.

Both emit the same MinitabIntent structure described in the framework spec.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

# intent category -> (session command, knowledge tags)
CATEGORY_MAP: dict[str, tuple[str, list[str]]] = {
    "capability": ("CAPA", ["quality", "capability", "cpk", "ppk"]),
    "spc": ("XBR", ["quality", "control_chart", "spc"]),
    "msa": ("GAGE", ["quality", "msa", "gage_rr"]),
    "doe": ("RSREG", ["doe", "rsm"]),
    "rsm": ("RSREG", ["doe", "rsm", "response_surface"]),
    "contour": ("CONTOURPLOT", ["graph", "contour"]),
    "proportion": ("PINF", ["stat", "proportion", "official_macro"]),
    "regression": ("REGRESS", ["stat", "regression"]),
    "anova": ("ANOVA", ["stat", "anova"]),
    "ttest": ("ONET", ["stat", "hypothesis_test"]),
    "descriptive": ("DESCRIBE", ["stat", "descriptive"]),
    "histogram": ("HISTOGRAM", ["graph", "histogram"]),
    "boxplot": ("BOXPLOT", ["graph", "boxplot"]),
    "scatterplot": ("PLOT", ["graph", "scatterplot"]),
    "run_chart": ("RUNCHART", ["graph", "run_chart"]),
}

KEYWORDS: dict[str, list[str]] = {
    "capability": ["capability", "cpk", "ppk", "cp ", "过程能力", "工序能力", "能力分析", "制程能力"],
    "spc": ["control chart", "xbar", "x-bar", "xbr", "控制图", "管制图", "spc", "均值极差"],
    "msa": ["gage", "gauge", "r&r", "rr ", "msa", "量具", "测量系统"],
    "doe": ["doe", "factorial", "响应面", "因子", "试验设计", "正交", "response surface", "mixture", "ccd", "central composite"],
    "rsm": ["rsm", "response surface", "响应曲面", "响应面", "二次模型", "quadratic model", "central composite", "ccd"],
    "contour": ["contour", "等值线", "等高线", "design window", "设计窗口", "overlaid contour"],
    "proportion": ["proportion", "比例", "合格率", "confidence interval for a proportion",
                   "two proportions", "两个总体比例", "置信区间(比例)", "defective rate"],
    "regression": ["regress", "回归", "linear model", "拟合", "预测方程"],
    "anova": ["anova", "方差分析"],
    "ttest": ["t-test", "t test", "t检验", "双样本", "单样本", "假设检验", "hypothesis"],
    "descriptive": ["describe", "descriptive", "summary", "统计量", "描述性", "汇总", "均值", "标准差"],
    "histogram": ["histogram", "直方图", "分布图"],
    "boxplot": ["boxplot", "box plot", "箱线图", "箱形图"],
    "scatterplot": ["scatter", "散点图", "plot ", "相关图"],
    "run_chart": ["run chart", "运行图", "趋势图", "游程"],
}

COLUMN_PATTERNS = [
    re.compile(r"\bC(\d{1,4})\b", re.I),
    re.compile(r"\bcol(?:umn)?\s*(\d{1,4})\b", re.I),
    re.compile(r"\bcolumn\s*'([^']+)'", re.I),
]
SPEC_PATTERNS = {
    "lsl": re.compile(r"\b(?:lsl|lower spec(?:ification)?(?: limit)?)\s*[=:]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "usl": re.compile(r"\b(?:usl|upper spec(?:ification)?(?: limit)?)\s*[=:]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "target": re.compile(r"\b(?:target|nominal)\s*[=:]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "subgroup": re.compile(r"\b(?:subgroup|sample size|n)\s*[=:]?\s*(\d{1,3})\b", re.I),
    "confidence": re.compile(r"\b(?:confidence|alpha|α)\s*[=:]?\s*(0?\.\d+|\d{2}(?:\.\d+)?\s*%)", re.I),
}
SPEC_CN = {
    "lsl": r"(?:下规格限|下限)\s*[=:：]?\s*(-?\d+(?:\.\d+)?)",
    "usl": r"(?:上规格限|上限)\s*[=:：]?\s*(-?\d+(?:\.\d+)?)",
    "target": r"(?:目标值|目标)\s*[=:：]?\s*(-?\d+(?:\.\d+)?)",
    "subgroup": r"(?:子组大小|子组容量|每组)\s*[=:：]?\s*(\d{1,3})",
}
for k, pat in SPEC_CN.items():
    SPEC_PATTERNS.setdefault(k, re.compile(pat))


@dataclass
class MinitabIntent:
    action_type: str = "analysis"          # data_input | analysis | visualization | report | composite
    analysis_category: str = "descriptive"
    target_columns: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    output_format: str = "table"           # chart | table | report | dashboard
    constraints: list[str] = field(default_factory=list)
    session_command: str = ""
    raw_input: str = ""
    confidence: float = 0.5
    backend: str = "rules"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "MinitabIntent":
        known = {f for f in MinitabIntent.__dataclass_fields__}
        return MinitabIntent(**{k: v for k, v in d.items() if k in known})


def _map_command(category: str) -> tuple[str, list[str]]:
    return CATEGORY_MAP.get(category, ("DESCRIBE", ["stat", "descriptive"]))


class RuleIntentParser:
    backend = "rules"

    def parse(self, text: str) -> MinitabIntent:
        raw = (text or "").strip()
        low = raw.lower()
        scores: dict[str, int] = {}
        for cat, words in KEYWORDS.items():
            score = 0
            for w in words:
                if w in low:
                    score += 2 if len(w) > 3 else 1
            if score:
                scores[cat] = score
        category = max(scores, key=lambda k: scores[k]) if scores else "descriptive"
        command, tags = _map_command(category)

        columns: list[str] = []
        for m in re.finditer(r"['\"]([A-Za-z_][A-Za-z0-9_ ]{0,30})['\"]", raw):
            columns.append(f"'{m.group(1)}'")
        for pat in COLUMN_PATTERNS:
            for m in pat.finditer(raw):
                token = m.group(1)
                col = f"C{token}" if token.isdigit() else f"'{token}'"
                if col not in columns:
                    columns.append(col)
        if not columns:
            # bare identifiers that look like a column name (e.g. "Thickness 列")
            stop = {
                "C", "NOTE", "LSL", "USL", "Target", "NORMAL", "DOE", "MSA", "SPC", "ANOVA", "Xbar", "R",
                "R&R", "Cp", "Cpk", "Pp", "Ppk", "COM", "Minitab", "Excel", "CSV",
            }
            for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]{2,20})\b", raw):
                word = m.group(1)
                if word in stop or word.isupper():
                    continue
                columns.append(f"'{word}'")
                break

        params: dict[str, Any] = {}
        for key, pat in SPEC_PATTERNS.items():
            m = pat.search(raw)
            if m:
                val = m.group(1).strip()
                if key == "confidence" and val.endswith("%"):
                    val = str(float(val.rstrip("%")) / 100.0)
                params[key] = float(val) if re.fullmatch(r"-?\d+(\.\d+)?", val) else val
        if category == "capability":
            params.setdefault("distribution", "NORMAL")
            if any(k in params for k in ("lsl", "usl", "target")):
                params.setdefault("spec_source", "user")
        if category == "spc":
            params.setdefault("subgroup", params.get("subgroup", 5))

        action = "visualization" if category in ("histogram", "boxplot", "scatterplot", "run_chart") else "analysis"
        if any(w in low for w in ("write", "save", "导出", "保存", "export")):
            constraints = ["export"]
        else:
            constraints = []
        if any(w in low for w in ("chart", "图", "plot", "graph")):
            constraints.append("show_graph")

        out_format = "chart" if action == "visualization" or "show_graph" in constraints else "table"
        top = scores.get(category, 0)
        confidence = min(0.95, 0.45 + 0.12 * top) if scores else 0.3
        return MinitabIntent(
            action_type=action,
            analysis_category=category,
            target_columns=columns,
            parameters=params,
            output_format=out_format,
            constraints=sorted(set(constraints) | set(tags[:1])),
            session_command=command,
            raw_input=raw,
            confidence=round(confidence, 2),
            backend="rules",
        )


LLM_PROMPT = """你是 Minitab 自动化助手。把用户指令解析为严格 JSON：
{{"action_type":"data_input|analysis|visualization|report|composite",
  "analysis_category":"capability|spc|msa|doe|regression|anova|ttest|descriptive|histogram|boxplot|scatterplot|run_chart",
  "target_columns":["C1"],"parameters":{{}},"output_format":"chart|table|report","constraints":[]}}
已知会话命令类别（Minitab 22 实测可用）：DESCRIBE/STATS/ONET/TWOT/ONEZ/ANOVA/REGRESS/CAPA/GAGE/XBR/XBAR/RSREG/CONTOURPLOT/HISTOGRAM/BOXPLOT/PLOT。
注意：过程能力的命令名是 CAPA（不是 CAPABILITY），且必须给出 LSPEC/USPEC 子命令。
用户指令：{user_input}
只输出 JSON，不要解释。"""


class LLMIntentParser:
    """Wrap any callable(text)->str returning JSON; falls back to rules on failure."""

    backend = "llm"

    def __init__(self, llm: Callable[[str], str], fallback: RuleIntentParser | None = None):
        self.llm = llm
        self.fallback = fallback or RuleIntentParser()
        self.prompt_template = LLM_PROMPT

    def parse(self, text: str) -> MinitabIntent:
        try:
            raw = self.llm(self.prompt_template.format(user_input=text))
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            intent = MinitabIntent.from_dict(data)
            intent.raw_input = text
            intent.backend = "llm"
            return intent
        except Exception:
            return self.fallback.parse(text)
