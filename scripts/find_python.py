"""Locate a Python interpreter that can drive Minitab via COM (pywin32 required).

Order: MINITAB_PYTHON env var -> bundled 32-bit venv (if present next to the skill)
       -> python / py -3 on PATH -> common conda installs.
Prints the chosen interpreter path, or exits 2 with guidance.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
CANDIDATES = [
    SKILL_ROOT / "runtime" / "python32" / "Scripts" / "python.exe",
    Path(r"D:\mechanic\minitab\.venv32\Scripts\python.exe"),
    Path(r"D:\Anaconda3\python.exe"),
]


def _has_pywin32(exe: str) -> bool:
    try:
        r = subprocess.run(
            [exe, "-c", "import win32com.client, pythoncom; print(1)"],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    tried: list[str] = []
    env = os.environ.get("MINITAB_PYTHON")
    if env:
        CANDIDATES.insert(0, Path(env))
    for exe in shutil.which("python"), shutil.which("python3"):
        if exe:
            CANDIDATES.append(Path(exe))
    for exe in CANDIDATES:
        if exe and Path(exe).exists():
            tried.append(str(exe))
            if _has_pywin32(str(exe)):
                print(str(exe))
                return 0
    print("no pywin32-capable Python found. tried:", file=sys.stderr)
    for t in tried:
        print("  -", t, file=sys.stderr)
    print("fix: pip install pywin32   (use the same bitness as Minitab)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
