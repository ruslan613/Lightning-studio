#!/usr/bin/env python3
"""Приёмка недели 3: NL → ТЗ + 3D + eng.report + prompt/preview, status=done."""
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
PY = ROOT / ".venv" / "bin" / "python"
DB = ROOT / "data" / "projects.db"
GOAL = "Разработай люстру Baccarat Ø1200 H900 24 лампы латунь+хрусталь"


def main() -> int:
    if not PY.exists():
        print(f"FAIL: no venv python at {PY}", file=sys.stderr)
        print("ACCEPT_WEEK3=FAIL")
        return 1

    cmd = [
        str(PY),
        "-m",
        "orchestrator.cli",
        "run",
        GOAL,
        "--week3",
    ]
    print("=== CLI week3 ===")
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

    paths: dict[str, Path | None] = {
        "design_brief": None,
        "geometry": None,
        "eng_json": None,
        "eng_md": None,
        "prompt_txt": None,
        "prompt_json": None,
        "preview": None,
    }
    if project_id:
        base = ROOT / "data" / "projects" / project_id
        paths["design_brief"] = base / "design" / "design_brief.json"
        paths["geometry"] = base / "cad3d" / "geometry.json"
        paths["eng_json"] = base / "engineering" / "engineering_report.json"
        paths["eng_md"] = base / "engineering" / "engineering_report.md"
        paths["prompt_txt"] = base / "viz" / "render_prompt.txt"
        paths["prompt_json"] = base / "viz" / "render_prompt.json"
        paths["preview"] = base / "viz" / "preview_2d.png"

        for key in ("design_brief", "geometry", "eng_json", "preview"):
            p = paths[key]
            if p is None or not p.is_file():
                ok = False
                reasons.append(f"missing {p}")

        # промпт: txt или json
        if not (
            (paths["prompt_txt"] and paths["prompt_txt"].is_file())
            or (paths["prompt_json"] and paths["prompt_json"].is_file())
        ):
            ok = False
            reasons.append("missing render_prompt.txt/.json")

    # SQLite
    tasks_done = arts = 0
    if not DB.is_file():
        ok = False
        reasons.append(f"missing db {DB}")
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
            for need in ("design_brief", "geometry", "eng_report"):
                if need not in kinds:
                    ok = False
                    reasons.append(f"no artifact kind={need}")
            # render или other для prompt/preview
            if "render" not in kinds and arts < 5:
                ok = False
                reasons.append("no preview/render artifact")
            if tasks_done < 6:
                ok = False
                reasons.append(f"tasks_done={tasks_done} < 6")
            if arts < 5:
                ok = False
                reasons.append(f"artifacts={arts} < 5")
        conn.close()

    print("=== checks ===")
    print(f"project_id={project_id}")
    for k, v in paths.items():
        print(f"{k}={v}")
    print(f"tasks_done={tasks_done} artifacts={arts}")
    if reasons:
        for r in reasons:
            print(f"FAIL: {r}")

    if ok:
        print("ACCEPT_WEEK3=PASS")
        return 0
    print("ACCEPT_WEEK3=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
