"""stdio JSON-lines мост: Electron ⇄ Orchestrator.

Протокол: на stdin строка {"id": N, "cmd": "...", "args": {...}};
на stdout строка {"id": N, "ok": true, "result": ...} | {"id": N, "ok": false, "error": "..."}.
Пайплайны выполняются в фоновых потоках, UI опрашивает `project`.
Запуск: python -m app  (cwd = корень gilil_program).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLBACKEND", "Agg")

from orchestrator.orchestrator import Orchestrator  # noqa: E402
from orchestrator.orchestrator import WEEK2_PIPELINE, WEEK3_PIPELINE, WEEK4_PIPELINE  # noqa: E402
from shared import store  # noqa: E402
import projects as vproj  # noqa: E402

PIPELINES = {"week2": WEEK2_PIPELINE, "week3": WEEK3_PIPELINE, "week4": WEEK4_PIPELINE}
AUTONOMY = ("step_by_step", "confirm_key_points", "full_auto")
_running: dict[str, threading.Thread] = {}
_errors: dict[str, str] = {}
_out_lock = threading.Lock()


def _orch(autonomy: str | None = None) -> Orchestrator:
    return Orchestrator(autonomy=autonomy or "full_auto")


def _guess_input_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "photo"
    if ext == ".pdf":
        return "pdf"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video"
    return "unknown"


def _run_bg(project_id: str, autonomy: str) -> None:
    def work() -> None:
        try:
            orch = _orch(autonomy)
            orch.run_all(project_id)
        except Exception as exc:  # noqa: BLE001
            _errors[project_id] = f"{exc}\n{traceback.format_exc()}"
        finally:
            _running.pop(project_id, None)

    t = threading.Thread(target=work, daemon=True)
    _running[project_id] = t
    t.start()


def _autonomy_of(project_id: str) -> str:
    mem = _orch().memory.get_memory(project_id) or {}
    a = mem.get("ui_autonomy")
    return a if a in AUTONOMY else "full_auto"


# ---------- команды ----------

def cmd_info(_: dict) -> dict:
    return {
        "data_dir": str(store.DATA_DIR),
        "db_path": str(store.DB_PATH),
        "pipelines": list(PIPELINES) + ["full"],
        "autonomy": list(AUTONOMY),
        "python": sys.version.split()[0],
        "app_version": vproj.APP_VERSION,
    }


def cmd_list_projects(_: dict) -> list[dict]:
    import sqlite3

    orch = _orch()
    with sqlite3.connect(str(orch.memory.db_path)) as conn:
        rows = conn.execute(
            "SELECT id, title, type, status, created_at, updated_at FROM projects "
            "ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return [
        {
            "id": r[0], "title": r[1], "type": r[2], "status": r[3],
            "created_at": r[4], "updated_at": r[5], "running": r[0] in _running,
        }
        for r in rows
    ]


def cmd_create_project(a: dict) -> dict:
    goal = (a.get("goal") or "").strip()
    if not goal:
        raise ValueError("пустая задача")
    pipeline = a.get("pipeline") or "week4"
    autonomy = a.get("autonomy") or "full_auto"
    if autonomy not in AUTONOMY:
        raise ValueError(f"unknown autonomy {autonomy}")
    orch = _orch(autonomy)
    project = orch.create_project(goal[:120], a.get("type") or "order")
    pid = project["id"]
    vproj.ensure_meta(pid, name=project["title"])
    orch.memory.set_memory_key(pid, "ui_autonomy", autonomy)
    orch.memory.set_memory_key(pid, "ui_pipeline", pipeline)

    payload: dict[str, Any] = {"goal": goal}
    upload = a.get("upload_path")
    if upload:
        src = Path(upload)
        if not src.is_file():
            raise FileNotFoundError(str(src))
        dst = store.artifact_path(pid, "input", src.name)
        shutil.copyfile(src, dst)
        orch.memory.set_memory_key(pid, "input_file", str(dst))
        upload_payload = {"goal": goal, "path": str(dst), "input_type": _guess_input_type(dst)}
    else:
        upload_payload = None

    if pipeline in PIPELINES:
        if upload_payload:
            # фото/PDF → engineering.analyze_input перед пайплайном недели
            orch.memory.enqueue_task(pid, "engineering", "analyze_input", payload=upload_payload)
        payload.update({"mode": pipeline, pipeline: True})
        orch.submit(pid, goal=goal, payload=payload)
        if pipeline in ("week3", "week4"):
            # для вкладки «Инженерия» — DXF (ezdxf) в конце цепочки
            orch.memory.enqueue_task(pid, "engineering", "export_dxf", payload={"goal": goal})
    else:  # full: verify-цикл (design_review) + DXF/паспорт/RFQ
        orch.submit(pid, goal=goal, payload=upload_payload or payload)
    _run_bg(pid, autonomy)
    return {"id": pid}


def _rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(store.DATA_DIR.resolve()))
    except ValueError:
        return path


def cmd_project(a: dict) -> dict:
    pid = a["id"]
    orch = _orch()
    project = orch.memory.get_project(pid)
    if not project:
        raise KeyError(pid)
    mem = project.get("memory") or {}
    tasks = [
        {k: t[k] for k in ("id", "module", "action", "status", "error", "created_at", "updated_at")}
        for t in orch.memory.list_tasks(pid)
    ]
    pdir = store.PROJECTS_DIR / pid
    files = sorted(
        str(p.relative_to(pdir)).replace("\\", "/")
        for p in pdir.rglob("*")
        if p.is_file() and p.relative_to(pdir).parts[0] not in vproj.core.RESERVED
    ) if pdir.is_dir() else []
    try:
        meta = vproj.load(pid)
    except vproj.ProjectError:
        meta = {}
    arts = [
        {**x, "rel": _rel(x["path"])} for x in project.get("artifacts") or []
    ]
    return {
        "id": pid,
        "title": project["title"],
        "type": project["type"],
        "status": project["status"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "goal": mem.get("goal"),
        "autonomy": mem.get("ui_autonomy") or "full_auto",
        "pipeline": mem.get("ui_pipeline") or mem.get("pipeline_mode"),
        "awaiting_confirm": bool(mem.get("awaiting_confirm")),
        "confirm_gate": mem.get("confirm_gate"),
        "fail_reason": mem.get("fail_reason") or _errors.get(pid),
        "verify_loop": mem.get("verify_loop") or [],
        "running": pid in _running,
        "tasks": tasks,
        "artifacts": arts,
        "files": files,
        "project_dir": str(pdir),
        "meta": meta,
        "current_version": meta.get("current_version", 0),
    }


def cmd_set_autonomy(a: dict) -> dict:
    pid, mode = a["id"], a["autonomy"]
    if mode not in AUTONOMY:
        raise ValueError(mode)
    _orch().memory.set_memory_key(pid, "ui_autonomy", mode)
    return {"autonomy": mode}


def cmd_confirm(a: dict) -> dict:
    pid = a["id"]
    if pid in _running:
        return {"running": True}
    autonomy = a.get("autonomy") or _autonomy_of(pid)
    _orch(autonomy).confirm(pid)
    _run_bg(pid, autonomy)
    return {"running": True}


def cmd_rerun_step(a: dict) -> dict:
    """Повтор одного шага: enqueue module.action (оркестратор подмешает актуальный контекст)."""
    pid, module, action = a["id"], a["module"], a["action"]
    if pid in _running:
        raise RuntimeError("пайплайн ещё выполняется")
    orch = _orch()
    project = orch.memory.get_project(pid)
    if not project:
        raise KeyError(pid)
    mem = project.get("memory") or {}
    goal = mem.get("goal") or project["title"]
    mode = mem.get("pipeline_mode")
    payload: dict[str, Any] = {"goal": goal}
    if mode in PIPELINES:
        payload["mode"] = mode
    orch.memory.set_memory_key(pid, "awaiting_confirm", False)
    orch.memory.set_memory_key(pid, "fail_reason", None)
    _errors.pop(pid, None)
    orch.memory.update_project_status(pid, "planning")
    orch.memory.enqueue_task(pid, module, action, payload=payload)
    _run_bg(pid, "full_auto")
    return {"running": True}


def cmd_rerun_pipeline(a: dict) -> dict:
    pid = a["id"]
    project = _orch().memory.get_project(pid)
    if not project:
        raise KeyError(pid)
    mem = project.get("memory") or {}
    return cmd_create_project({
        "goal": mem.get("goal") or project["title"],
        "pipeline": mem.get("ui_pipeline") or "week4",
        "autonomy": a.get("autonomy") or mem.get("ui_autonomy") or "full_auto",
        "upload_path": mem.get("input_file"),
    })


def cmd_geometry(a: dict) -> dict:
    p = store.PROJECTS_DIR / a["id"] / "cad3d" / "geometry.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_wait(a: dict) -> dict:
    t = _running.get(a["id"])
    if t:
        t.join(timeout=float(a.get("timeout", 120)))
    return cmd_project(a)


# ---------- Ф0: версии проектов ----------

def _strip(m: dict) -> dict:
    return {k: v for k, v in m.items() if k != "files"}


def _idle(pid: str) -> None:
    if pid in _running:
        raise RuntimeError("пайплайн ещё выполняется — дождитесь завершения")


def cmd_save_version(a: dict) -> dict:
    _idle(a["id"])
    return _strip(vproj.save_version(a["id"], a.get("message") or "", allow_empty=bool(a.get("allow_empty", True))))


def cmd_list_versions(a: dict) -> list[dict]:
    return vproj.list_versions(a["id"])


def cmd_checkout_version(a: dict) -> dict:
    _idle(a["id"])
    return _strip(vproj.checkout_version(a["id"], int(a["version"]), a.get("message")))


def cmd_diff_versions(a: dict) -> dict:
    to_v = lambda x: None if x in (None, "", "working", 0) else int(x)  # noqa: E731
    return vproj.diff_versions(a["id"], to_v(a.get("a")), to_v(a.get("b")))


def cmd_export_project(a: dict) -> dict:
    return vproj.export_project(a["id"], a["dest"])


def cmd_import_project(a: dict) -> dict:
    return vproj.import_project(a["path"], new_id=a.get("new_id"))


def cmd_rename_project(a: dict) -> dict:
    return vproj.rename_project(a["id"], a["name"])


def cmd_verify_version(a: dict) -> dict:
    return vproj.verify_version(a["id"], int(a["version"]))


COMMANDS = {
    "save_version": cmd_save_version,
    "list_versions": cmd_list_versions,
    "checkout_version": cmd_checkout_version,
    "diff_versions": cmd_diff_versions,
    "export_project": cmd_export_project,
    "import_project": cmd_import_project,
    "rename_project": cmd_rename_project,
    "verify_version": cmd_verify_version,
    "info": cmd_info,
    "list_projects": cmd_list_projects,
    "create_project": cmd_create_project,
    "project": cmd_project,
    "set_autonomy": cmd_set_autonomy,
    "confirm": cmd_confirm,
    "rerun_step": cmd_rerun_step,
    "rerun_pipeline": cmd_rerun_pipeline,
    "geometry": cmd_geometry,
    "wait": cmd_wait,
}


def _emit(obj: dict, out) -> None:
    with _out_lock:
        out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        out.flush()


def main() -> int:
    # stdout — только протокол; print() модулей уходит в stderr
    out = sys.stdout
    sys.stdout = sys.stderr
    _emit({"event": "ready", "info": cmd_info({})}, out)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            fn = COMMANDS[req["cmd"]]
            result = fn(req.get("args") or {})
            _emit({"id": rid, "ok": True, "result": result}, out)
        except Exception as exc:  # noqa: BLE001
            _emit({"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"}, out)
    return 0
