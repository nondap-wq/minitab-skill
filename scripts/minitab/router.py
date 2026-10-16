"""任务路由层 —— 按设计流程决策：宏库优先 → 自编宏 → COM 兜底。

    用户自然语言/数据
        │
        ├─ ① 宏库检索（macro_library.search）：命中且可批处理 → 直接用官方宏
        ├─ ② 无可用宏 → 生成宏文件（macro_generator，GMACRO 参数化宏）
        └─ ③ 宏无法覆盖的底层操作 → COM 直接操控（doe_rsm / com_executor，本层不改动）

本模块只做"决策 + 编排"，不修改已验证的 COM 执行链路。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import macro_generator as mg
from . import macro_library as ml
from .intent_parser import MinitabIntent

# 意图类别 -> 是否需要"宏层"以及生成宏所需的默认参数
MACRO_TASKS = {
    "rsm": {"keywords": "response surface regression quadratic contour",
            "builder": "rsm"},
    "doe": {"keywords": "factorial design doe analysis", "builder": "rsm"},
    "contour": {"keywords": "contour plot", "builder": "chart"},
    # 官方宏库确实覆盖的任务（比例推断/置信区间模拟/随机抽样）
    "proportion": {"official_only": True, "keywords": "proportion confidence interval test"},
    "simulation": {"official_only": True, "keywords": "random sampling simulation defective"},
}

# 这些类别由 COM 直接承担：宏库里没有对应能力（已盘点官方宏库 54 个宏）
COM_ONLY = {"capability", "spc", "msa", "descriptive", "ttest", "anova",
            "regression", "histogram", "boxplot", "scatterplot", "run_chart"}


@dataclass
class RouteDecision:
    task: str
    stage: str                 # "official_macro" | "generated_macro" | "com"
    reason: str
    macro_name: str = ""
    invocation: str = ""
    candidates: list[dict] = field(default_factory=list)
    plan: dict | None = None
    com_fallback: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _task_of(intent: MinitabIntent) -> str:
    cat = (intent.analysis_category or "").lower()
    if cat in ("rsm", "doe", "contour", "proportion", "simulation"):
        return cat
    cat_map = {"capability": "capability", "spc": "spc", "msa": "msa", "descriptive": "descriptive",
               "ttest": "ttest", "anova": "anova", "regression": "regression", "histogram": "histogram",
               "boxplot": "boxplot", "scatterplot": "scatterplot", "run_chart": "run_chart"}
    return cat_map.get(cat, cat or "descriptive")


# 官方宏库确实覆盖 = 这些宏用途说明里出现的关键能力词
OFFICIAL_MACRO_HINTS: dict[str, list[str]] = {
    "proportion": ["proportion", "confidence interval", "test of significance"],
    "simulation": ["simulate", "random sampl", "defective", "success"],
}


def route(intent: MinitabIntent, query: str = "", **macro_kwargs) -> RouteDecision:
    """返回该任务应走哪一层，以及具体调用方式。"""
    task = _task_of(intent)

    # ---------- ① 官方宏检索（强匹配：任务关键词必须真的出现在宏名称/用途里）
    MIN_MACRO_SCORE = 10
    if task not in COM_ONLY:
        kw = MACRO_TASKS.get(task, {}).get("keywords", task)
        core_terms = [t for t in kw.split() if len(t) >= 5]
        hits = ml.search(f"{kw} {query}".strip(), top_k=8)
        strong = []

        def _text(hit: dict) -> str:
            return f"{hit.get('name','')} {hit.get('purpose','')}".lower()

        for h in hits:
            if h.get("score", 0) < MIN_MACRO_SCORE:
                continue
            text = _text(h)
            # (a) 任务核心词命中宏名称/用途，或 (b) 命中该类别在官方宏库中已确认的能力词
            if any(t in text for t in core_terms):
                strong.append(h)
            elif any(t in text for t in OFFICIAL_MACRO_HINTS.get(task, [])):
                strong.append(h)
        if strong:
            plan = mg.plan_official(strong[0])
            return RouteDecision(
                task=task, stage="official_macro",
                reason=(f"宏库强命中：{plan.name}（相关度 {strong[0].get('score')}，"
                        f"核心词命中其用途说明）"),
                macro_name=plan.name, invocation=plan.invocation,
                candidates=hits, plan=plan.to_dict(),
            )

        # ---------- ② 生成宏文件
        builder = MACRO_TASKS.get(task, {}).get("builder")
        if builder == "rsm":
            cols = intent.target_columns or []
            resp = macro_kwargs.get("response") or (cols[0] if cols else "C9")
            factors = macro_kwargs.get("factors") or (cols[1:] if len(cols) > 1 else ["C6", "C7"])
            factors = list(factors)
            terms = macro_kwargs.get("terms")
            if not terms:
                squares = [f"{f}*{f}" for f in factors]
                inter = [f"{factors[i]}*{factors[j]}" for i in range(len(factors)) for j in range(i + 1, len(factors))]
                terms = " ".join(factors + squares + inter)
            plan = mg.build_rsm_macro(
                response_col=resp, factor_cols=list(factors), terms=terms,
                levels=macro_kwargs.get("levels", "-1000 0 8 14"),
                fits_col=macro_kwargs.get("fits", "C11"), resid_col=macro_kwargs.get("resid", "C12"),
                contour_png=macro_kwargs.get("contour_png"),
            )
            return RouteDecision(
                task=task, stage="generated_macro",
                reason="宏库无匹配项 → 已生成参数化 GMACRO 宏文件",
                macro_name=plan.name, invocation=plan.invocation, candidates=hits,
                plan=plan.to_dict(), com_fallback="doe_rsm.rsreg_command + MinitabSession",
            )
        if builder == "chart":
            plan = mg.build_chart_macro(
                z_col=macro_kwargs.get("z", "C11"), y_col=macro_kwargs.get("y", "C7"),
                x_col=macro_kwargs.get("x", "C6"), png=macro_kwargs.get("png", "chart.png"),
            )
            return RouteDecision(
                task=task, stage="generated_macro",
                reason="宏库无匹配项 → 已生成图形宏",
                macro_name=plan.name, invocation=plan.invocation, plan=plan.to_dict(),
                com_fallback="doe_rsm.contour_command + run_macro_with_artifact",
            )

    # ---------- ③ COM 兜底
    return RouteDecision(
        task=task, stage="com",
        reason=f"{task} 属于 COM 直控类别（宏库 56 个官方宏中无对应能力）" if task in COM_ONLY
        else f"{task} 未匹配到宏，交由 COM 直接执行",
        com_fallback="com_executor.ComBackend（已验证链路，保持不变）",
    )


def route_from_text(text: str, **macro_kwargs) -> RouteDecision:
    from .intent_parser import RuleIntentParser

    intent = RuleIntentParser().parse(text)
    return route(intent, query=text, **macro_kwargs)


def describe() -> dict:
    return {
        "policy": ["official_macro", "generated_macro", "com"],
        "macro_stats": ml.stats(),
        "com_only_categories": sorted(COM_ONLY),
        "macro_tasks": sorted(MACRO_TASKS),
    }
