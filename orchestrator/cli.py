"""CLI: python -m orchestrator.cli run "текст" [--week2|--week3|--week4] [--stub] [--input PATH] [--autonomy MODE]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from orchestrator.orchestrator import Orchestrator, _ensure_demo_sample
from shared.store import DB_PATH


def _guess_input_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
        return "photo"
    if ext == ".pdf":
        return "pdf"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        return "video"
    return "unknown"


def _build_payload(
    goal: str,
    input_path: Path | None,
    *,
    week2: bool = False,
    week3: bool = False,
    week4: bool = False,
) -> dict:
    if week4:
        return {"goal": goal, "mode": "week4", "week4": True}
    if week3:
        return {"goal": goal, "mode": "week3", "week3": True}
    if week2:
        return {"goal": goal, "mode": "week2", "week2": True}
    if input_path is None:
        # NL без файла — полный пайплайн через design.brief_from_goal
        return {"goal": goal}
    path = input_path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"input not found: {path}")
    return {
        "input_type": _guess_input_type(path),
        "path": str(path),
        "goal": goal,
    }


def _print_summary(orch: Orchestrator, project_id: str, results: list) -> dict:
    print(f"ran={len(results)}")
    for r in results:
        mark = "OK" if r.get("ok") else "FAIL"
        extra = " PAUSED" if r.get("paused") else ""
        print(f"  [{mark}]{extra} {r.get('module')}.{r.get('action')}: {r.get('message')}")

    final = orch.memory.get_project(project_id)
    assert final is not None
    print(f"final_status={final['status']}")
    mem = final.get("memory") or {}
    if mem.get("awaiting_confirm"):
        print(f"awaiting_confirm=True confirm_gate={mem.get('confirm_gate')}")

    all_tasks = orch.memory.list_tasks(project_id)
    for t in all_tasks:
        print(f"task {t['module']}.{t['action']} -> {t['status']}")

    arts = final["artifacts"]
    print(f"artifacts={len(arts)}")
    for a in arts:
        print(f"  {a['kind']}: {a['path']}")

    print(f"db_path={DB_PATH}")
    return final


def cmd_run(args: argparse.Namespace) -> int:
    # week2/3/4 — всегда full_auto
    week_fast = bool(args.week2 or args.week3 or args.week4)
    autonomy = "full_auto" if week_fast else args.autonomy
    orch = Orchestrator(autonomy=autonomy)
    goal = args.text
    project = orch.create_project(goal[:120] or "CLI project", args.type)
    print(f"project_id={project['id']}")
    print(f"db_path={orch.memory.db_path}")
    print(
        f"type={args.type} stub={bool(args.stub)} "
        f"week2={bool(args.week2)} week3={bool(args.week3)} week4={bool(args.week4)} "
        f"autonomy={orch.autonomy}"
    )

    if args.stub and not week_fast:
        payload = {"goal": goal}
        if args.input:
            p = Path(args.input)
            if not p.exists():
                print(f"error: input not found: {p}", file=sys.stderr)
                return 1
            payload["path"] = str(p.resolve())
            payload["input_type"] = _guess_input_type(p)
        task = orch.memory.enqueue_task(
            project["id"],
            "automation",
            "stub_pipeline",
            payload=payload,
        )
        print(f"enqueued=1")
        print(f"  queued {task['module']}.{task['action']} id={task['id']}")
    else:
        try:
            input_path = Path(args.input) if args.input else None
            # week2/week3 игнорируют демо-фото: только NL
            if week_fast:
                input_path = None
            payload = _build_payload(
                goal,
                input_path,
                week2=bool(args.week2),
                week3=bool(args.week3),
                week4=bool(args.week4),
            )
            # без week-флага и без --input раньше подставлялось демо-фото;
            # теперь NL без path → design.brief_from_goal (если не stub).
            # Для обратной совместимости demo-фото: только явный --input или demo flag.
            if not week_fast and not args.input and getattr(args, "demo_photo", False):
                sample = _ensure_demo_sample()
                payload = {
                    "input_type": "photo",
                    "path": str(sample),
                    "cct_k": 3000,
                    "materials": ["brass"],
                    "dimensions_mm": {"length": 600, "height": 40, "depth": 50},
                    "style": ["modern_linear"],
                    "geometry": {"type": "linear_sconce", "mount": "wall"},
                    "goal": goal,
                }
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        tasks = orch.submit(project["id"], goal=goal, payload=payload)
        print(f"enqueued={len(tasks)}")
        for t in tasks:
            print(f"  queued {t['module']}.{t['action']} id={t['id']}")

    results = orch.run_all(project["id"])
    final = _print_summary(orch, project["id"], results)
    if final["status"] == "done":
        return 0
    if final["status"] == "awaiting_confirm":
        return 0
    return 1


def cmd_confirm(args: argparse.Namespace) -> int:
    orch = Orchestrator(autonomy=args.autonomy)
    print(f"project_id={args.project_id}")
    print(f"autonomy={orch.autonomy}")
    try:
        orch.confirm(args.project_id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    results = orch.run_all(args.project_id)
    final = _print_summary(orch, args.project_id, results)
    if final["status"] == "done":
        return 0
    if final["status"] == "awaiting_confirm":
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m orchestrator.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="создать проект и прогнать пайплайн")
    run_p.add_argument("text", help="задача на обычном языке")
    run_p.add_argument(
        "--type",
        choices=("order", "tender"),
        default="order",
        help="тип проекта (default: order)",
    )
    run_p.add_argument(
        "--stub",
        action="store_true",
        help="week1: одна сквозная заглушка automation.stub_pipeline",
    )
    run_p.add_argument(
        "--week2",
        action="store_true",
        help="week2: design.brief_from_goal → cad3d → done (full_auto)",
    )
    run_p.add_argument(
        "--week3",
        action="store_true",
        help="week3: design → cad3d → eng.report → viz → done (full_auto)",
    )
    run_p.add_argument(
        "--week4",
        action="store_true",
        help="week4: week3 + catalogs + sales → done (full_auto)",
    )
    run_p.add_argument(
        "--input",
        metavar="PATH",
        default=None,
        help="опциональный фото/PDF/видео; без --input — NL через design",
    )
    run_p.add_argument(
        "--demo-photo",
        action="store_true",
        help="подставить демо-фото sconce (старый путь engineering.analyze_input)",
    )
    run_p.add_argument(
        "--autonomy",
        choices=("full_auto", "confirm_key_points", "step_by_step"),
        default=None,
        help="режим автономности (или env GILIL_AUTONOMY)",
    )
    run_p.set_defaults(func=cmd_run)

    conf_p = sub.add_parser("confirm", help="снять паузу awaiting_confirm и продолжить")
    conf_p.add_argument("project_id", help="id проекта")
    conf_p.add_argument(
        "--autonomy",
        choices=("full_auto", "confirm_key_points", "step_by_step"),
        default=None,
        help="режим для продолжения (default: env/full_auto)",
    )
    conf_p.set_defaults(func=cmd_confirm)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
