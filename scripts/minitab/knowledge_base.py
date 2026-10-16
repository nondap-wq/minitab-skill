"""Layer 2 - knowledge base: SQLite experience store + template/pitfall library + retrieval.

Design goals
------------
* zero external dependencies (no ChromaDB/FAISS required) - retrieval uses a
  deterministic lexical/char-ngram similarity so the skill runs anywhere,
  while the interface stays compatible with a vector-store backend.
* three tables mirroring the framework spec: experiences / pitfalls / command_templates.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path(__file__).resolve().parent.parent / "knowledge" / "experience.db"
PACKAGE_SEED = Path(__file__).resolve().parent / "knowledge" / "seed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    raw_input TEXT,
    parsed_intent TEXT,
    session_commands TEXT,
    generated_code TEXT,
    command_used TEXT,
    execution_result TEXT,
    success INTEGER,
    dry_run INTEGER DEFAULT 0,
    execution_time_ms INTEGER,
    error_message TEXT,
    user_feedback TEXT,
    tags TEXT
);
CREATE TABLE IF NOT EXISTS pitfalls (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    command TEXT,
    error_pattern TEXT,
    root_cause TEXT,
    solution TEXT,
    occurrence_count INTEGER DEFAULT 1,
    resolved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS command_templates (
    command_name TEXT PRIMARY KEY,
    category TEXT,
    syntax_template TEXT,
    parameters TEXT,
    description TEXT,
    min_version TEXT,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    reliability_score REAL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_exp_tags ON experiences(tags);
CREATE INDEX IF NOT EXISTS idx_pit_command ON pitfalls(command);
"""


@dataclass
class ExperienceRecord:
    raw_input: str
    parsed_intent: dict
    session_commands: list[str]
    generated_code: str
    command_used: str
    execution_result: str
    success: bool
    dry_run: bool = False
    execution_time_ms: int = 0
    error_message: str | None = None
    user_feedback: str | None = None
    tags: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["parsed_intent"] = json.dumps(self.parsed_intent, ensure_ascii=False)
        d["session_commands"] = json.dumps(self.session_commands, ensure_ascii=False)
        d["success"] = int(self.success)
        d["dry_run"] = int(self.dry_run)
        return d


@dataclass
class PitfallRecord:
    command: str
    error_pattern: str
    root_cause: str
    solution: str
    resolved: int = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


def _bigrams(text: str) -> set[str]:
    t = "".join(ch for ch in text.lower() if ch.isalnum() or ch == "_")
    return {t[i : i + 2] for i in range(len(t) - 1)} or {t}


def similarity(a: str, b: str) -> float:
    """Dice coefficient over character bigrams - cheap, dependency-free, robust to
    Chinese/English mixing and to word-order noise in short intents."""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


class KnowledgeBase:
    def __init__(self, db_path: str | Path | None = None, seed_dir: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.seed_dir = Path(seed_dir) if seed_dir else PACKAGE_SEED
        if not self.seed_dir.exists():
            alt = self.db_path.parent / "seed"
            if alt.exists():
                self.seed_dir = alt
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.bootstrap()

    # ------------------------------------------------------------------ seed
    def bootstrap(self) -> dict[str, int]:
        stats = {"commands": 0, "object_types": 0}
        cmd_file = self.seed_dir / "session_commands.json"
        if cmd_file.exists():
            rows = json.loads(cmd_file.read_text(encoding="utf-8"))
            for row in rows:
                self.upsert_command_template(**row)
            stats["commands"] = len(rows)
        om_file = self.seed_dir / "object_model.json"
        if om_file.exists():
            self.object_model = json.loads(om_file.read_text(encoding="utf-8"))
            stats["object_types"] = len(self.object_model.get("types", []))
        else:
            self.object_model = {"types": []}
        return stats

    # ------------------------------------------------------------- write API
    def write_experience(self, record: ExperienceRecord) -> str:
        row = record.to_row()
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self._conn.execute(f"INSERT OR REPLACE INTO experiences ({cols}) VALUES ({marks})", list(row.values()))
        self._conn.commit()
        return record.id

    def write_pitfall(self, pitfall: PitfallRecord) -> str:
        cur = self._conn.execute(
            "SELECT id, occurrence_count FROM pitfalls WHERE command=? AND error_pattern=?",
            (pitfall.command, pitfall.error_pattern),
        ).fetchone()
        if cur:
            self._conn.execute(
                "UPDATE pitfalls SET occurrence_count=occurrence_count+1, timestamp=?, solution=? WHERE id=?",
                (pitfall.timestamp, pitfall.solution, cur["id"]),
            )
            pid = cur["id"]
        else:
            d = asdict(pitfall)
            cols = ", ".join(d)
            self._conn.execute(
                f"INSERT INTO pitfalls ({cols}) VALUES ({', '.join('?' for _ in d)})", list(d.values())
            )
            pid = pitfall.id
        self.update_reliability(pitfall.command, success=False)
        self._conn.commit()
        return pid

    def upsert_command_template(
        self,
        command_name: str,
        category: str = "stat",
        syntax_template: str = "",
        parameters: str | dict = "{}",
        description: str = "",
        min_version: str = "17",
        **_: Any,
    ) -> None:
        if isinstance(parameters, dict):
            parameters = json.dumps(parameters, ensure_ascii=False)
        self._conn.execute(
            """INSERT INTO command_templates
                 (command_name, category, syntax_template, parameters, description, min_version)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(command_name) DO UPDATE SET
                 category=excluded.category,
                 syntax_template=excluded.syntax_template,
                 parameters=excluded.parameters,
                 description=excluded.description""",
            (command_name.upper(), category, syntax_template, parameters, description, min_version),
        )
        self._conn.commit()

    def update_reliability(self, command: str, success: bool) -> None:
        name = (command or "").strip().split()[0].upper() if command else ""
        if not name:
            return
        col = "success_count" if success else "failure_count"
        self._conn.execute(
            f"UPDATE command_templates SET {col}={col}+1 WHERE command_name=?", (name,)
        )
        self._conn.execute(
            """UPDATE command_templates
               SET reliability_score = (success_count + 1.0) / (success_count + failure_count + 2.0)
               WHERE command_name=?""",
            (name,),
        )
        self._conn.commit()

    def write_user_correction(self, record_id: str, correction: str) -> None:
        self._conn.execute(
            "UPDATE experiences SET user_feedback=?, success=0 WHERE id=?", (correction, record_id)
        )
        self._conn.commit()

    # --------------------------------------------------------- retrieval API
    def retrieve_command_template(self, command_name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM command_templates WHERE command_name=?", ((command_name or "").upper(),)
        ).fetchone()
        return dict(row) if row else None

    def retrieve_pitfalls(self, command_name: str, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM pitfalls WHERE command LIKE ? ORDER BY occurrence_count DESC LIMIT ?",
            (f"%{command_name}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def retrieve_similar(self, query: str, top_k: int = 5, only_success: bool = True) -> list[dict]:
        where = "WHERE success=1" if only_success else ""
        rows = self._conn.execute(f"SELECT * FROM experiences {where}").fetchall()
        scored = []
        for r in rows:
            text = f"{r['raw_input']} {r['tags']} {r['command_used']}"
            scored.append((similarity(query, text), dict(r)))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, row in scored[:top_k]:
            if score <= 0.0 and out:
                continue
            row["_score"] = round(score, 4)
            out.append(row)
        return out

    def stats(self) -> dict:
        c = self._conn
        return {
            "db": str(self.db_path),
            "experiences": c.execute("SELECT COUNT(*) FROM experiences").fetchone()[0],
            "success": c.execute("SELECT COUNT(*) FROM experiences WHERE success=1").fetchone()[0],
            "dry_runs": c.execute("SELECT COUNT(*) FROM experiences WHERE dry_run=1").fetchone()[0],
            "pitfalls": c.execute("SELECT COUNT(*) FROM pitfalls").fetchone()[0],
            "commands": c.execute("SELECT COUNT(*) FROM command_templates").fetchone()[0],
            "object_types": len(getattr(self, "object_model", {}).get("types", [])),
            "top_commands": [
                dict(r)
                for r in c.execute(
                    "SELECT command_name, success_count, failure_count, ROUND(reliability_score,3) AS score "
                    "FROM command_templates WHERE success_count+failure_count>0 "
                    "ORDER BY success_count DESC LIMIT 5"
                ).fetchall()
            ],
        }

    def object_members(self, type_name: str) -> list[dict]:
        for t in getattr(self, "object_model", {}).get("types", []):
            if t["name"].lower() == type_name.lower():
                return t["members"]
        return []
