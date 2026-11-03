#!/usr/bin/env python3
"""Приёмка Ф0 (система проектов с версиями) через stdio-бэкенд `python -m app`.

create_project(week4) → авто v1 → правка параметров ТЗ + пересборка 3D → save v2 →
diff v1↔v2 → откат к v1 (новая v3) → sha256 рабочей копии == v1 → export .alsproj →
import → те же версии и sha256. Плюс CLI `python -m projects`. Изолированный ALS_DATA_DIR.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
GOAL = "Разработай люстру Baccarat Ø1200 H900 24 лампы латунь+хрусталь"
fails: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


class Backend:
    def __init__(self, env: dict) -> None:
        self.p = subprocess.Popen([str(PY), "-u", "-m", "app"], cwd=ROOT, env=env, text=True,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  encoding="utf-8")
        self.n = 0
        ready = json.loads(self.p.stdout.readline())
        assert ready.get("event") == "ready", ready
        self.info = ready["info"]

    def __call__(self, cmd: str, **args):
        self.n += 1
        self.p.stdin.write(json.dumps({"id": self.n, "cmd": cmd, "args": args}, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        if not r["ok"]:
            raise RuntimeError(f"{cmd}: {r['error']}")
        return r["result"]

    def close(self) -> None:
        self.p.stdin.close()
        self.p.wait(10)


def tree_sha(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()
            and p.relative_to(root).parts[0] not in ("versions", "project.json")}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="als-f0-"))
    env = {**os.environ, "ALS_DATA_DIR": str(tmp / "data"), "MPLBACKEND": "Agg", "PYTHONUTF8": "1",
           "ALS_AUTHOR": "f0_accept"}
    print(f"data_dir={tmp / 'data'}")
    b = Backend(env)
    try:
        print("=== 1. create_project + pipeline week4 ===")
        pid = b("create_project", goal=GOAL, pipeline="week4", autonomy="full_auto")["id"]
        fin = b("wait", id=pid, timeout=600)
        check(fin["status"] == "done", f"pipeline status=done ({fin['status']})")
        pdir = Path(fin["project_dir"])
        meta = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
        check(all(k in meta for k in ("id", "name", "created_at", "updated_at", "current_version",
                                      "fixture_type", "author", "app_version")), "project.json: все поля метаданных")
        vs = b("list_versions", id=pid)
        check(len(vs) == 1 and vs[0]["kind"] == "pipeline", f"авто-версия v1 после пайплайна ({len(vs)})")
        v1_sha = tree_sha(pdir)
        man1 = json.loads((pdir / "versions/v1/manifest.json").read_text(encoding="utf-8"))
        check({k: v["sha256"] for k, v in man1["files"].items()} == v1_sha, "manifest v1 sha256 == рабочая копия")
        check(not any(f.startswith("versions/") for f in fin["files"]), "versions/ не в списке файлов рабочей копии")

        print("=== 2. правка параметров → save v2 ===")
        bp = pdir / "design" / "design_brief.json"
        brief = json.loads(bp.read_text(encoding="utf-8"))
        old_dims = dict(brief.get("dimensions_mm") or {})
        brief["dimensions_mm"] = {**old_dims, "diameter": 1500}
        brief["materials"] = list(brief.get("materials") or []) + ["алебастр"]
        bp.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        v2 = b("save_version", id=pid, message="Ø1500 + алебастр")
        check(v2["version"] == 2 and v2["parent"] == 1, f"save_version → v{v2['version']} (parent v1)")
        # пересборка 3D по новым параметрам → оркестратор сам создаёт v3, если артефакты изменились
        b("rerun_step", id=pid, module="cad3d", action="build_parametric")
        b("wait", id=pid, timeout=300)
        v2n = v2["version"]
        d = b("diff_versions", id=pid, a=1, b=v2n)
        check("design/design_brief.json" in d["changed"], "diff: design_brief.json changed")
        keys = {p["key"] for p in d["params"]}
        check("dimensions_mm.diameter" in keys, f"diff: параметр dimensions_mm.diameter ({sorted(keys)[:6]})")
        print("   diff:", json.dumps({k: d[k] for k in ("added", "removed", "changed")}, ensure_ascii=False)[:400])
        check(tree_sha(pdir) != v1_sha, "рабочая копия отличается от v1")

        print("=== 3. откат к v1 ===")
        rb = b("checkout_version", id=pid, version=1)
        check(rb["kind"] == "rollback" and rb["restored_from"] == 1 and rb["version"] == v2n + 1,
              f"rollback создал v{rb['version']} (restored_from=1)")
        check(tree_sha(pdir) == v1_sha, "sha256 рабочей копии после отката == v1 (все файлы)")
        check(rb["tree_sha256"] == man1["tree_sha256"], "tree_sha256 v_rollback == v1")
        vs = b("list_versions", id=pid)
        check([v["version"] for v in vs] == list(range(rb["version"], 0, -1)), "история не удалена: v1..vN")
        check(all(b("verify_version", id=pid, version=v["version"])["ok"] for v in vs), "verify всех снимков ok")
        check(b("diff_versions", id=pid, a=1, b=rb["version"])["changed"] == [], "diff v1↔rollback пуст")

        print("=== 4. rename + export/import .alsproj ===")
        b("rename_project", id=pid, name="Baccarat F0 test")
        ex = b("export_project", id=pid, dest=str(tmp / "out"))
        check(Path(ex["path"]).is_file() and ex["path"].endswith(".alsproj"), f"export {ex['path']} ({ex['size']} B)")
        im = b("import_project", path=ex["path"])
        nid = im["id"]
        check(nid != pid, "import получил новый id (исходный существует)")
        vs2 = b("list_versions", id=nid)
        check([(v["version"], v["tree_sha256"]) for v in vs2] == [(v["version"], v["tree_sha256"]) for v in vs],
              "импорт: те же версии и tree_sha256")
        ndir = Path(fin["project_dir"]).parent / nid
        check(tree_sha(ndir) == v1_sha, "импорт: sha256 рабочей копии == v1")
        lp = [p["id"] for p in b("list_projects")]
        check(nid in lp, "импортированный проект в list_projects")
        np = b("project", id=nid)
        check(np["meta"]["name"] == "Baccarat F0 test", "имя сохранилось при импорте")
        rb2 = b("checkout_version", id=nid, version=v2n)
        check(rb2["tree_sha256"] == v2["tree_sha256"], "импорт: откат к v2 воспроизводит v2")
    finally:
        b.close()

    print("=== 5. CLI python -m projects ===")
    r = subprocess.run([str(PY), "-m", "projects", "log", pid], cwd=ROOT, env=env, capture_output=True, text=True)
    check(r.returncode == 0 and len(json.loads(r.stdout)) >= 3, "CLI log")
    r = subprocess.run([str(PY), "-m", "projects", "diff", pid, "v1", "v2"], cwd=ROOT, env=env, capture_output=True, text=True)
    check(r.returncode == 0 and "design/design_brief.json" in r.stdout, "CLI diff v1 v2")

    ok = not fails
    print(f"project_id={pid}")
    print("ACCEPT_F0_PROJECTS=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
