"""Extract the official Minitab session-commands PDF into a page-tagged text file.

Run once (or after replacing the PDF):
    python extract_text.py

Produces ``Minitab_session_commands.txt`` next to the PDF, with explicit markers:
    <<<PAGE 123>>>  ... page text ...

so that search can report the exact PDF page for a hit.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF = HERE / "Minitab_session_commands.pdf"
TXT = HERE / "Minitab_session_commands.txt"


def main() -> int:
    try:
        import pypdf
    except ImportError:
        print("pypdf required: pip install pypdf", file=sys.stderr)
        return 2
    if not PDF.exists():
        print(f"missing PDF: {PDF}", file=sys.stderr)
        return 2

    reader = pypdf.PdfReader(str(PDF))
    parts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            text = f"<extract failed: {exc!r}>"
        parts.append(f"<<<PAGE {i}>>>\n{text}")
    TXT.write_text("\n".join(parts), encoding="utf-8")
    print(f"{len(reader.pages)} pages -> {TXT} ({TXT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
