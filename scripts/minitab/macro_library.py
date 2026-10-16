"""宏库检索层 —— 设计流程的第②步："优先从宏库中查找可用宏"。

索引 `skill/macros/` 下的官方宏（.MTB），提供：
  * name / path / purpose（NOTE 首行）/ keywords / commands / interactive
  * search(query) —— 关键词打分检索，返回可直接调用的宏
  * build_index()  —— 重建缓存（skill/macros/index.json）

设计原则：只读取、不修改宏文件；本模块不触碰 COM 层（com_executor）。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
MACRO_DIR = SKILL_ROOT / "macros"
INDEX_FILE = MACRO_DIR / "index.json"

# 命令关键字：用于判断宏"会用到哪些能力"，也用于检索
CMD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]{1,14})\b")
INTERACTIVE_HINTS = ("'terminal'", '"terminal"', "terminal", "please enter", "what value", "how many")


@dataclass
class MacroEntry:
    name: str
    rel_path: str
    purpose: str = ""
    keywords: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    interactive: bool = False
    lines: int = 0
    sub_macros: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _purpose(lines: list[str]) -> str:
    chunks = []
    for ln in lines[:40]:
        s = ln.strip()
        if not s:
            if chunks:
                break
            continue
        if s.lower().startswith("note"):
            text = s[4:].strip().strip('"').strip()
            if text:
                chunks.append(text)
        elif chunks:
            break
    return " ".join(chunks)[:220].strip()


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower())
    stop = {"the", "and", "for", "you", "your", "that", "with", "this", "will", "are", "from", "into",
            "note", "macro", "please", "enter", "value", "using", "each", "have", "when", "them"}
    seen: list[str] = []
    for w in words:
        if w not in stop and w not in seen:
            seen.append(w)
    return seen[:24]


def build_index(macro_dir: Path | None = None, force: bool = False) -> list[MacroEntry]:
    macro_dir = Path(macro_dir) if macro_dir else MACRO_DIR
    if INDEX_FILE.exists() and not force and macro_dir == MACRO_DIR:
        try:
            raw = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            return [MacroEntry(**item) for item in raw]
        except Exception:  # noqa: BLE001
            pass

    entries: list[MacroEntry] = []
    seen_paths: set[str] = set()
    files = sorted({p.resolve() for p in list(macro_dir.rglob("*.mtb")) + list(macro_dir.rglob("*.MTB"))})
    for path in files:
        if path.name.startswith("."):
            continue
        if str(path) in seen_paths:
            continue
        seen_paths.add(str(path))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        lines = text.splitlines()
        low = text.lower()
        commands: list[str] = []
        for ln in lines:
            m = CMD_RE.match(ln.lstrip())
            if m:
                cmd = m.group(1).upper()
                if cmd not in commands and cmd not in ("NOTE", "NOECHO", "END", "GMACRO", "MACRO", "ENDMACRO"):
                    commands.append(cmd)
        purpose = _purpose(lines)
        entry = MacroEntry(
            name=path.stem.upper(),
            rel_path=str(path.relative_to(macro_dir)).replace("\\", "/"),
            purpose=purpose,
            keywords=_keywords(f"{path.stem} {purpose} {' '.join(commands)}"),
            commands=commands[:18],
            interactive=any(h in low for h in INTERACTIVE_HINTS),
            lines=len(lines),
            sub_macros=[c for c in commands if c.lower().endswith(("mac", "mtb"))][:6],
        )
        entries.append(entry)
    if macro_dir == MACRO_DIR:
        try:
            INDEX_FILE.write_text(json.dumps([e.to_dict() for e in entries], ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return entries


def _score(entry: MacroEntry, terms: list[str]) -> int:
    hay = f"{entry.name} {entry.purpose} {' '.join(entry.keywords)} {' '.join(entry.commands)}".lower()
    score = 0
    for t in terms:
        if not t:
            continue
        if t in entry.name.lower():
            score += 6
        if t in hay:
            score += 3
        if t in entry.commands:
            score += 4
    # 非交互式宏优先（可无人值守调用）
    if not entry.interactive:
        score += 1
    return score


def search(query: str, top_k: int = 5, include_interactive: bool = True) -> list[dict]:
    """检索宏库。返回按相关度排序的宏（含 purpose / commands / interactive）。"""
    entries = build_index()
    terms = [t for t in re.findall(r"[A-Za-z][A-Za-z\-']{1,}", (query or "").lower())]
    scored = []
    for e in entries:
        if e.interactive and not include_interactive:
            continue
        s = _score(e, terms)
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, e in scored[:top_k]:
        d = e.to_dict()
        d["score"] = s
        out.append(d)
    return out


def get(name: str) -> MacroEntry | None:
    key = (name or "").lower()
    for e in build_index():
        if e.name.lower() == key or Path(e.rel_path).stem.lower() == key:
            return e
    return None


def stats() -> dict:
    entries = build_index()
    return {
        "total": len(entries),
        "interactive": sum(1 for e in entries if e.interactive),
        "non_interactive": sum(1 for e in entries if not e.interactive),
        "commands_used": sorted({c for e in entries for c in e.commands})[:40],
        "index_file": str(INDEX_FILE),
    }


if __name__ == "__main__":  # 手动重建索引
    es = build_index(force=True)
    print(f"indexed {len(es)} macros -> {INDEX_FILE}")
    for e in es[:10]:
        flag = "interactive" if e.interactive else "batch"
        print(f"  {e.name:<12} {flag:<12} {e.purpose[:70]}")
