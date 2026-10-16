"""Keyword search over the built-in official Minitab session-commands reference.

Usage
-----
    python search_commands.py RSREG                     # find the command / mentions
    python search_commands.py RSREG --context 1200      # show surrounding text
    python search_commands.py RSREG --limit 3 --json    # machine readable
    python search_commands.py --page 347                # dump one PDF page
    python search_commands.py --list                    # list every command heading

Design: the extracted text is a flat, page-tagged file. Search reports the PDF page
number for every hit, so the caller can cite the exact page instead of re-reading the
whole document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TXT = HERE / "Minitab_session_commands.txt"
PAGE_MARK = re.compile(r"<<<PAGE (\d+)>>>")


def _load() -> tuple[str, list[tuple[int, int]]]:
    if not TXT.exists():
        raise SystemExit(
            f"missing {TXT.name}: run  python {HERE / 'extract_text.py'}  first"
        )
    text = TXT.read_text(encoding="utf-8", errors="ignore")
    pages: list[tuple[int, int]] = []
    for m in PAGE_MARK.finditer(text):
        pages.append((m.start(), int(m.group(1))))
    return text, pages


def page_of(pos: int, pages: list[tuple[int, int]]) -> int:
    current = 0
    for start, num in pages:
        if start <= pos:
            current = num
        else:
            break
    return current


def page_text(text: str, pages: list[tuple[int, int]], page: int) -> str:
    for idx, (start, num) in enumerate(pages):
        if num == page:
            end = pages[idx + 1][0] if idx + 1 < len(pages) else len(text)
            return text[start:end]
    return ""


def clean(snippet: str) -> str:
    """The PDF extraction drops spaces; re-insert them after '.' / ':' for readability."""
    s = re.sub(r"(?<=[.:;])(?=[A-Za-z])", " ", snippet)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="search the built-in Minitab session-command reference")
    ap.add_argument("keyword", nargs="?", help="command name or text to find")
    ap.add_argument("--context", type=int, default=0, help="chars of context around each hit")
    ap.add_argument("--limit", type=int, default=5, help="max hits to show")
    ap.add_argument("--page", type=int, help="dump one PDF page instead of searching")
    ap.add_argument("--list", action="store_true", help="list all 'XXX: Session command for ...' headings")
    ap.add_argument("--json", action="store_true", help="json output")
    ap.add_argument("--regex", action="store_true", help="treat keyword as a regular expression")
    args = ap.parse_args()

    text, pages = _load()

    if args.page:
        out = page_text(text, pages, args.page)
        if args.json:
            print(json.dumps({"page": args.page, "text": out}, ensure_ascii=False))
        else:
            sys.stdout.buffer.write(out.encode("utf-8", "replace"))
        return 0

    if args.list:
        heads = re.findall(r"([A-Z%][A-Za-z0-9_%,]*):\s*Session\s*command", clean(text))
        heads += re.findall(r"([A-Z][A-Z0-9_]{1,20}):\s*Session command", text)
        seen = sorted(set(heads))
        if args.json:
            print(json.dumps({"count": len(seen), "commands": seen}, ensure_ascii=False, indent=1))
        else:
            print(f"{len(seen)} session commands documented:")
            for name in seen:
                print(f"  {name}")
        return 0

    if not args.keyword:
        ap.error("keyword required (or use --page / --list)")

    pattern = args.keyword if args.regex else re.escape(args.keyword)
    hits = []
    for m in re.finditer(pattern, text, re.IGNORECASE):
        lo = max(0, m.start() - args.context) if args.context else max(0, m.start() - 120)
        hi = min(len(text), m.end() + args.context) if args.context else m.end() + 260
        hits.append(
            {
                "page": page_of(m.start(), pages),
                "match": m.group(0),
                "snippet": clean(text[lo:hi]),
            }
        )
        if len(hits) >= args.limit:
            break

    if args.json:
        print(json.dumps({"keyword": args.keyword, "hits": hits}, ensure_ascii=False, indent=1))
        return 0

    if not hits:
        print(f"no hits for {args.keyword!r}")
        return 1
    for h in hits:
        print(f"\n=== page {h['page']}  [{h['match']}]")
        print(h["snippet"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
