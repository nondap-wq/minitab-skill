"""minitab CLI - command line entry point for the Minitab AI skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .com_executor import doctor
from .knowledge_base import KnowledgeBase
from .orchestrator import MinitabAISkill

DEMOS = [
    "对 C1 列做过程能力分析，下规格限 LSL=9，上规格限 USL=17，子组大小 5",
    "对 Thickness 列画直方图并给出描述性统计",
    "对 C1 做 Xbar-R 控制图，子组大小 5",
    "用量具 R&R 分析 C1 C2 C3 这三列",
]


def _print(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=1))
    else:
        print(obj)


def cmd_doctor(args) -> int:
    report = doctor()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print("Minitab COM preflight")
        print(f"  platform      : {report['platform']}")
        print(f"  python        : {report['python']} ({report['python_bits']}-bit)")
        print(f"  Mtb.Application CLSID : {report['registrations'].get('Mtb.Application CLSID')}")
        print(f"  LocalServer32 : {report['server'].get('LocalServer32')}")
        print(f"  version       : {report['server'].get('product_version') or report['server'].get('file_version')}")
        print(f"  typelib       : {report['typelib'].get('name')} libid={report['typelib'].get('libid')}")
        print(f"  typelib loadable : {report['typelib'].get('loadable')} types={report['typelib'].get('types')}")
        print(f"  dispatch      : {report['server'].get('dispatch')}")
        print(f"  READY         : {report['ready']}")
        for key in ("hresult",):
            if report["server"].get(key):
                print(f"  hresult       : {report['server'][key]}")
        diag = report["server"].get("diagnosis") or {}
        if diag:
            print(f"  diagnosis     : {diag.get('name')} - {diag.get('cause')}")
        for item in report.get("remediation", []):
            print(f"  remediation   : {item}")
    return 0 if report.get("ready") else 3


def _make_skill(args) -> MinitabAISkill:
    skill = MinitabAISkill(
        db_path=args.db,
        backend=args.backend,
        artifact_dir=args.out,
    )
    if getattr(args, "sample_data", False) and hasattr(skill.backend, "sample_data"):
        skill.backend.sample_data = True
    return skill


def cmd_run(args) -> int:
    skill = _make_skill(args)
    try:
        run = skill.run(args.prompt, project=args.project or "", output_dir=args.out)
    finally:
        if args.backend == "com" or args.backend == "auto":
            skill.shutdown()
    if args.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=1))
    else:
        print(f"intent   : {run.intent['analysis_category']} -> {run.intent['session_command']} "
              f"(cols={run.intent['target_columns']}, params={run.intent['parameters']}, conf={run.intent['confidence']})")
        print(f"commands :")
        for c in run.generation["session_commands"]:
            print(f"   {c}")
        for r in run.generation["rationale"]:
            print(f"   · {r}")
        print(f"backend  : {run.backend}{' (simulated)' if run.simulated else ''}")
        print(f"success  : {run.execution['success']}  time={run.execution['time_ms']}ms")
        for o in run.execution["outputs"]:
            rows = o.get("rows")
            if rows:
                print(f"   [{o.get('title')}] " + "; ".join(f"{a}={b}" for a, b in rows))
            else:
                print(f"   [{o.get('type')}] {o.get('title') or o.get('text', '')}")
        if run.execution.get("error"):
            print(f"error    : {run.execution['error']}")
            print(f"diagnosis: {run.execution.get('diagnosis')}")
        print(f"knowledge: {run.knowledge}")
        for k, v in run.artifacts.items():
            print(f"artifact : {k} -> {v}")
    return 0 if run.execution["success"] else 1


def cmd_plan(args) -> int:
    skill = _make_skill(args)
    intent, gen = skill.plan(args.prompt)
    data = {
        "intent": intent.to_dict(),
        "session_commands": gen.session_commands,
        "command_used": gen.command_used,
        "rationale": gen.rationale,
        "python_code": gen.python_code,
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print(json.dumps({k: v for k, v in data.items() if k != "python_code"}, ensure_ascii=False, indent=1))
        print("\n--- generated python ---\n" + gen.python_code)
    if args.save:
        p = Path(args.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(gen.python_code, encoding="utf-8")
        print(f"saved -> {p}")
    return 0


def cmd_kb(args) -> int:
    kb = KnowledgeBase(args.db)
    if args.command:
        tpl = kb.retrieve_command_template(args.command)
        pits = kb.retrieve_pitfalls(args.command)
        _print({"template": tpl, "pitfalls": pits}, args.json)
        return 0
    if args.members:
        _print(kb.object_members(args.members)[:60], args.json)
        return 0
    _print(kb.stats(), args.json)
    return 0


def cmd_demo(args) -> int:
    skill = _make_skill(args)
    rc = 0
    for prompt in DEMOS:
        print(f"\n=== {prompt}")
        run = skill.run(prompt, output_dir=args.out)
        for c in run.generation["session_commands"]:
            print(f"   cmd: {c}")
        print(f"   backend={run.backend} simulated={run.simulated} success={run.execution['success']}")
        rc = rc or (0 if run.execution["success"] else 1)
    print("\nknowledge base after demo:")
    _print(skill.kb.stats(), False)
    return rc


def cmd_macro(args) -> int:
    """宏库检索 / 路由决策 / 生成宏文件 —— 检查"宏优先 → 自编宏 → COM 兜底"链路。"""
    from . import macro_library as ml
    from .router import describe, route_from_text

    if args.reindex:
        entries = ml.build_index(force=True)
        print(f"macro index rebuilt: {len(entries)} entries")
        return 0
    if args.search:
        hits = ml.search(args.search, top_k=args.limit)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=1))
        elif not hits:
            print(f"宏库中没有匹配 {args.search!r} 的宏")
        else:
            for h in hits:
                flag = "交互式" if h["interactive"] else "批处理"
                print(f"[{h['score']:>3}] {h['name']:<12} {flag:<6} {h['rel_path']}")
                print(f"      {h['purpose'][:110]}")
                print(f"      commands: {', '.join(h['commands'][:8])}")
        return 0
    if args.route:
        kw = {}
        if args.factors:
            kw["factors"] = args.factors.split()
        if args.response:
            kw["response"] = args.response
        d = route_from_text(args.route, **kw)
        if args.json:
            print(json.dumps(d.to_dict(), ensure_ascii=False, indent=1))
        else:
            print(f"任务       : {d.task}")
            print(f"决策层     : {d.stage}")
            print(f"理由       : {d.reason}")
            if d.macro_name:
                print(f"宏         : {d.macro_name}   调用: {d.invocation}")
            if d.plan and d.plan.get("path"):
                print(f"宏文件     : {d.plan['path']}")
                for n in d.plan.get("notes", []):
                    print(f"      · {n}")
            print(f"COM 兜底   : {d.com_fallback}")
        return 0
    print(json.dumps(describe(), ensure_ascii=False, indent=1))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("minitab", description="Minitab COM automation AI skill")
    p.add_argument("--db", default=None, help="knowledge base sqlite path")
    p.add_argument("--out", default=None, help="artifact/output directory")
    p.add_argument("--json", action="store_true", help="machine readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="preflight the Minitab COM environment")
    d.set_defaults(func=cmd_doctor)

    for name, fn, help_text in (
        ("run", cmd_run, "parse -> generate -> execute -> learn (full loop)"),
        ("plan", cmd_plan, "parse + generate only (no execution)"),
    ):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("prompt", help="natural language request")
        s.add_argument("--backend", default="auto", choices=["auto", "com", "dry-run"])
        s.add_argument("--project", default="", help="open an existing Minitab project first")
        s.add_argument("--save", default="", help="(plan) write generated python here")
        s.add_argument("--out", default=None, help="artifact/output directory")
        s.add_argument("--data", dest="sample_data", action="store_true", help="load a deterministic sample dataset into C1..C3 first")
        s.set_defaults(func=fn)

    k = sub.add_parser("kb", help="inspect the knowledge base")
    k.add_argument("--command", default="", help="show a session command template + pitfalls")
    k.add_argument("--members", default="", help="dump members of an object model type, e.g. IProject")
    k.set_defaults(func=cmd_kb)

    m = sub.add_parser("macro", help="macro library search / routing decision / macro generation")
    m.add_argument("--search", default="", help="keyword search over the official macro library")
    m.add_argument("--limit", type=int, default=5, help="max hits")
    m.add_argument("--route", default="", help="natural-language task; show which stage would handle it")
    m.add_argument("--response", default="", help="(route) response column override")
    m.add_argument("--factors", default="", help="(route) factor columns, space separated")
    m.add_argument("--reindex", action="store_true", help="rebuild macros/index.json")
    m.set_defaults(func=cmd_macro)

    dm = sub.add_parser("demo", help="run the built-in demo prompts")
    dm.add_argument("--backend", default="dry-run", choices=["auto", "com", "dry-run"])
    dm.add_argument("--out", default=None, help="artifact/output directory")
    dm.add_argument("--data", dest="sample_data", action="store_true", help="load sample data first")
    dm.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "backend", None) == "com" and args.cmd in ("run", "demo"):
        args.backend = "com"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
