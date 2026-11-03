#!/usr/bin/env python3
"""Приёмка недели 4: NL → week3 + catalog + product_card + price_quote, status=done."""
from __future__ import annotations

import os
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
    env = os.environ.get("ALS_DATA_DIR")
    return Path(env) if env else ROOT / "data"

# Cross-platform venv interpreter (Windows: Scripts\python.exe, POSIX: bin/python)
PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
DATA_DIR = _data_dir()
DB = DATA_DIR / "projects.db"
GOAL = "Разработай люстру Baccarat Ø1200 H900 24 лампы латунь+хрусталь"


def main() -> int:
    if not PY.exists():
        print(f"FAIL: no venv python at {PY}", file=sys.stderr)
        print("ACCEPT_WEEK4=FAIL")
        return 1

    cmd = [
        str(PY),
        "-m",
        "orchestrator.cli",
        "run",
        GOAL,
        "--week4",
    ]
    print(f"data_dir={DATA_DIR}")
    print("=== CLI week4 ===")
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
        "preview": None,
        "catalog_xlsx": None,
        "catalog_csv": None,
        "site_fragment": None,
        "product_card_json": None,
        "product_card_md": None,
        "price_quote": None,
    }
    if project_id:
        base = DATA_DIR / "projects" / project_id
        paths["design_brief"] = base / "design" / "design_brief.json"
        paths["geometry"] = base / "cad3d" / "geometry.json"
        paths["eng_json"] = base / "engineering" / "engineering_report.json"
        paths["preview"] = base / "viz" / "preview_2d.png"
        paths["catalog_xlsx"] = base / "catalogs" / "catalog.xlsx"
        paths["catalog_csv"] = base / "catalogs" / "catalog.csv"
        paths["site_fragment"] = base / "catalogs" / "site_fragment.html"
        paths["product_card_json"] = base / "sales" / "product_card.json"
        paths["product_card_md"] = base / "sales" / "product_card.md"
        paths["price_quote"] = base / "sales" / "price_quote.json"

        for key in (
            "design_brief",
            "geometry",
            "eng_json",
            "preview",
            "site_fragment",
            "product_card_json",
            "price_quote",
        ):
            p = paths[key]
            if p is None or not p.is_file():
                ok = False
                reasons.append(f"missing {p}")

        # catalog: xlsx and/or csv
        if not (
            (paths["catalog_xlsx"] and paths["catalog_xlsx"].is_file())
            or (paths["catalog_csv"] and paths["catalog_csv"].is_file())
        ):
            ok = False
            reasons.append("missing catalogs/catalog.xlsx|.csv")

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
            for need in ("design_brief", "geometry", "eng_report", "catalog", "sales"):
                if need not in kinds:
                    ok = False
                    reasons.append(f"no artifact kind={need}")
            # week4: 10 tasks (6 week3 + 4 catalogs/sales)
            if tasks_done < 10:
                ok = False
                reasons.append(f"tasks_done={tasks_done} < 10")
            if arts < 8:
                ok = False
                reasons.append(f"artifacts={arts} < 8")
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
        print("ACCEPT_WEEK4=PASS")
        return 0
    print("ACCEPT_WEEK4=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
