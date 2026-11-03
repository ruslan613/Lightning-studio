#!/usr/bin/env python3
"""Приёмка недели 2: NL → design_brief + geometry, status=done."""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

def _force_utf8_stdio() -> None:
    """Avoid UnicodeEncodeError when printing Cyrillic on Windows cp1252 consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


_force_utf8_stdio()

ROOT = Path(__file__).resolve().parent.parent

def _data_dir() -> Path:
    """Respect ALS_DATA_DIR the same way shared.store does."""
    import os
    env = os.environ.get("ALS_DATA_DIR")
    return Path(env) if env else ROOT / "data"


def _venv_python() -> Path:
    import os
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

PY = _venv_python()
DATA_DIR = _data_dir()
DB = DATA_DIR / "projects.db"
GOAL = "Разработай люстру Baccarat Ø1200 H900 24 лампы латунь+хрусталь"


def main() -> int:
    if not PY.exists():
        print(f"FAIL: no venv python at {PY}", file=sys.stderr)
        print("ACCEPT_WEEK2=FAIL")
        return 1

    cmd = [
        str(PY),
        "-m",
        "orchestrator.cli",
        "run",
        GOAL,
        "--week2",
    ]
    print(f"data_dir={DATA_DIR}")
    print("=== CLI week2 ===")
    print(" ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    print(out)

    ok = True
    reasons: list[str] = []

    if proc.returncode != 0:
        ok = False
        reasons.append(f"cli exit={proc.returncode}")

    m = re.search(r"project_id=([0-9a-fA-F-]{36})", out)
    if not m:
        ok = False
        reasons.append("no project_id in stdout")
        project_id = None
    else:
        project_id = m.group(1)

    if "final_status=done" not in out:
        ok = False
        reasons.append("final_status != done")

    brief_path = None
    geom_path = None
    if project_id:
        brief_path = DATA_DIR / "projects" / project_id / "design" / "design_brief.json"
        geom_path = DATA_DIR / "projects" / project_id / "cad3d" / "geometry.json"
        if not brief_path.is_file():
            ok = False
            reasons.append(f"missing {brief_path}")
        if not geom_path.is_file():
            ok = False
            reasons.append(f"missing {geom_path}")

    # SQLite
    if not DB.is_file():
        ok = False
        reasons.append(f"missing db {DB}")
        tasks_done = arts = 0
    else:
        conn = sqlite3.connect(str(DB))
        if project_id:
            status = conn.execute(
                "SELECT status FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if not status or status[0] != "done":
                ok = False
                reasons.append(f"db status={status}")
            tasks_done = conn.execute(
                "SELECT count(*) FROM tasks WHERE project_id=? AND status='done'",
                (project_id,),
            ).fetchone()[0]
            arts = conn.execute(
                "SELECT count(*) FROM artifacts WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            kinds = {
                r[0]
                for r in conn.execute(
                    "SELECT kind FROM artifacts WHERE project_id=?", (project_id,)
                ).fetchall()
            }
            if "design_brief" not in kinds:
                ok = False
                reasons.append("no artifact kind=design_brief")
            if "geometry" not in kinds:
                ok = False
                reasons.append("no artifact kind=geometry")
            if tasks_done < 3:
                ok = False
                reasons.append(f"tasks_done={tasks_done} < 3")
            if arts < 2:
                ok = False
                reasons.append(f"artifacts={arts} < 2")
        else:
            tasks_done = arts = 0
        conn.close()

    print("=== checks ===")
    print(f"project_id={project_id}")
    print(f"design_brief={brief_path}")
    print(f"geometry={geom_path}")
    print(f"tasks_done={tasks_done if DB.is_file() else '?'} artifacts={arts if DB.is_file() else '?'}")
    if reasons:
        for r in reasons:
            print(f"FAIL: {r}")

    if ok:
        print("ACCEPT_WEEK2=PASS")
        return 0
    print("ACCEPT_WEEK2=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
