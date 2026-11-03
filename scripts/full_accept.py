#!/usr/bin/env python3
"""Приёмка полного цикла: NL/фото → verify → 3D → DXF → паспорт → RFQ → каталог → продажи."""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


def _force_utf8_stdio() -> None:
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
    env = os.environ.get("ALS_DATA_DIR")
    return Path(env) if env else ROOT / "data"


def _venv_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


PY = _venv_python()
DATA_DIR = _data_dir()
DB = DATA_DIR / "projects.db"
GOAL = "Современная хрустальная люстра Ø1200 H900 24 лампы латунь"
SAMPLE = ROOT / "data" / "samples" / "sconce_demo.png"

REQUIRED_FILES = [
    ("design_brief", "design/design_brief.json"),  # NL path only; photo may skip
    ("geometry", "cad3d/geometry.json"),
    ("eng_report", "engineering/engineering_report.json"),
    ("preview", "viz/preview_2d.png"),
    ("dxf", "engineering/fixture.dxf"),
    ("passport", "engineering/passport.md"),
    ("rfq", "automation/rfq.json"),
    ("catalog_xlsx_or_csv", None),  # special
    ("site_fragment", "catalogs/site_fragment.html"),
    ("product_card", "sales/product_card.json"),
    ("price_quote", "sales/price_quote.json"),
]

REQUIRED_KINDS = {
    "geometry",
    "eng_report",
    "drawing",
    "passport",
    "rfq",
    "catalog",
    "sales",
}


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, out


def _check_project(project_id: str, mode: str, expect_brief: bool) -> list[str]:
    reasons: list[str] = []
    base = DATA_DIR / "projects" / project_id
    if expect_brief and not (base / "design" / "design_brief.json").is_file():
        reasons.append(f"missing design_brief ({mode})")
    for rel in (
        "cad3d/geometry.json",
        "engineering/engineering_report.json",
        "viz/preview_2d.png",
        "engineering/fixture.dxf",
        "engineering/passport.md",
        "automation/rfq.json",
        "catalogs/site_fragment.html",
        "sales/product_card.json",
        "sales/price_quote.json",
    ):
        if not (base / rel).is_file():
            reasons.append(f"missing {rel} ({mode})")
    if not (
        (base / "catalogs" / "catalog.xlsx").is_file()
        or (base / "catalogs" / "catalog.csv").is_file()
    ):
        reasons.append(f"missing catalogs/catalog.xlsx|.csv ({mode})")

    if not DB.is_file():
        reasons.append(f"missing db {DB}")
        return reasons

    conn = sqlite3.connect(str(DB))
    try:
        status = conn.execute(
            "SELECT status FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not status or status[0] != "done":
            reasons.append(f"db status={status} ({mode})")
        tasks_done = conn.execute(
            "SELECT count(*) FROM tasks WHERE project_id=? AND status='done'",
            (project_id,),
        ).fetchone()[0]
        # full: 2 first + 14 post ≈ 16; photo path same count
        if tasks_done < 14:
            reasons.append(f"tasks_done={tasks_done} < 14 ({mode})")
        kinds = {
            r[0]
            for r in conn.execute(
                "SELECT kind FROM artifacts WHERE project_id=?", (project_id,)
            ).fetchall()
        }
        for need in REQUIRED_KINDS:
            if need not in kinds:
                reasons.append(f"no artifact kind={need} ({mode})")
    finally:
        conn.close()
    return reasons


def main() -> int:
    if not PY.exists():
        print(f"FAIL: no venv python at {PY}", file=sys.stderr)
        print("ACCEPT_FULL=FAIL")
        return 1

    print(f"data_dir={DATA_DIR}")
    ok = True
    all_reasons: list[str] = []

    # --- A: NL full ---
    print("=== CLI full NL ===")
    ec, out = _run([str(PY), "-m", "orchestrator.cli", "run", GOAL])
    print(out)
    if ec != 0:
        ok = False
        all_reasons.append(f"NL cli exit={ec}")
    if "final_status=done" not in out:
        ok = False
        all_reasons.append("NL final_status != done")
    m = re.search(r"project_id=([0-9a-fA-F-]{36})", out)
    if not m:
        ok = False
        all_reasons.append("NL no project_id")
    else:
        all_reasons.extend(_check_project(m.group(1), "NL", expect_brief=True))

    # --- B: photo full ---
    if SAMPLE.is_file():
        print("=== CLI full photo ===")
        ec, out = _run(
            [
                str(PY),
                "-m",
                "orchestrator.cli",
                "run",
                "Бра латунь LED из фото",
                "--input",
                str(SAMPLE),
            ]
        )
        print(out)
        if ec != 0:
            ok = False
            all_reasons.append(f"photo cli exit={ec}")
        if "final_status=done" not in out:
            ok = False
            all_reasons.append("photo final_status != done")
        m = re.search(r"project_id=([0-9a-fA-F-]{36})", out)
        if not m:
            ok = False
            all_reasons.append("photo no project_id")
        else:
            all_reasons.extend(_check_project(m.group(1), "photo", expect_brief=False))
    else:
        print(f"SKIP photo: missing {SAMPLE}")

    # --- C: stdio backend smoke ---
    print("=== backend stdio info ===")
    proc = subprocess.run(
        [str(PY), "-m", "app"],
        cwd=str(ROOT),
        input='{"id":1,"cmd":"info"}\n',
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "MPLBACKEND": "Agg"},
        timeout=30,
    )
    bout = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    print(bout[:500])
    compact = bout.replace(" ", "").lower()
    if '"ok":true' not in compact:
        ok = False
        all_reasons.append("backend info not ok")
    if "app_version" not in compact and "0.5.0" not in bout:
        ok = False
        all_reasons.append("backend missing app_version")

    print("=== checks ===")
    if all_reasons:
        for r in all_reasons:
            print(f"FAIL: {r}")
            ok = False

    if ok:
        print("ACCEPT_FULL=PASS")
        return 0
    print("ACCEPT_FULL=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
