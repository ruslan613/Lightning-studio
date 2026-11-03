"""Оркестратор: анализ/дизайн → verify → 3D → DXF → паспорт → рендер → RFQ."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automation import module as automation_mod
from cad3d import module as cad3d_mod
from design import module as design_mod
from engineering import module as engineering_mod
from orchestrator.memory import ProjectMemory
from shared.store import DB_PATH, DATA_DIR
from orchestrator.autonomy import resolve_mode, should_pause
from shared.models import AutonomyMode
from visualization import module as visualization_mod
from viz import module as viz_mod
from catalogs import module as catalogs_mod
from sales import module as sales_mod

MODULES: dict[str, Callable[[str, dict, dict], dict]] = {
    "engineering": engineering_mod.handle,
    "visualization": visualization_mod.handle,
    "automation": automation_mod.handle,
    "design": design_mod.handle,
    "cad3d": cad3d_mod.handle,
    "viz": viz_mod.handle,
    "catalogs": catalogs_mod.handle,
    "sales": sales_mod.handle,
}

# после approve дизайна
POST_APPROVAL: list[tuple[str, str]] = [
    ("cad3d", "build_parametric"),
    ("cad3d", "export_viz_spec"),
    ("engineering", "engineering_report"),
    ("viz", "render_prompt"),
    ("viz", "preview_2d"),
    ("engineering", "export_dxf"),
    ("engineering", "build_spec"),
    ("visualization", "render"),
    ("automation", "make_rfq"),
    ("automation", "update_catalog"),
    # коммерческий финал (как week4) — полный цикл до карточки/котировки
    ("catalogs", "build_catalog_table"),
    ("catalogs", "site_fragment"),
    ("sales", "product_card"),
    ("sales", "price_quote"),
]

# week2: идея → ТЗ → 3D-спека
WEEK2_PIPELINE: list[tuple[str, str]] = [
    ("design", "brief_from_goal"),
    ("cad3d", "build_parametric"),
    ("cad3d", "export_viz_spec"),
]

# week3: ТЗ → 3D → инж.отчёт → промпт/превью
WEEK3_PIPELINE: list[tuple[str, str]] = [
    ("design", "brief_from_goal"),
    ("cad3d", "build_parametric"),
    ("cad3d", "export_viz_spec"),
    ("engineering", "engineering_report"),
    ("viz", "render_prompt"),
    ("viz", "preview_2d"),
]

# week4: week3 + каталог + продажа
WEEK4_PIPELINE: list[tuple[str, str]] = [
    *WEEK3_PIPELINE,
    ("catalogs", "build_catalog_table"),
    ("catalogs", "site_fragment"),
    ("sales", "product_card"),
    ("sales", "price_quote"),
]

VERIFY_MAX = 3

_STATUS_BY_MODULE = {
    "engineering": "engineering",
    "visualization": "visualization",
    "automation": "automation",
    "design": "visualization",
    "cad3d": "engineering",
    "viz": "visualization",
    "catalogs": "automation",
    "sales": "automation",
}


class Orchestrator:
    def __init__(self, db_path: str | Path | None = None, autonomy: str | None = None) -> None:
        self.memory = ProjectMemory(db_path or DB_PATH)
        self.autonomy: AutonomyMode = resolve_mode(autonomy)

    def create_project(self, title: str, type_: str = "order") -> dict[str, Any]:
        return self.memory.create_project(title, type_)

    def submit(
        self,
        project_id: str,
        goal: str,
        payload: dict | None = None,
    ) -> list[dict[str, Any]]:
        payload = payload or {}
        project = self.memory.get_project(project_id)
        if not project:
            raise KeyError(f"project {project_id}")

        mode = (payload.get("mode") or "").lower().strip()
        week4 = mode == "week4" or bool(payload.get("week4"))
        week3 = (not week4) and (mode == "week3" or bool(payload.get("week3")))
        week2 = (not week4) and (not week3) and (mode == "week2" or bool(payload.get("week2")))

        self.memory.set_memory_key(project_id, "goal", goal)
        self.memory.set_memory_key(project_id, "verify_iteration", 0)
        self.memory.set_memory_key(project_id, "design_remarks", [])
        self.memory.set_memory_key(project_id, "verify_loop", [])
        self.memory.set_memory_key(project_id, "post_approval_enqueued", False)
        self.memory.update_project_status(project_id, "planning")

        if week4:
            plan = [{"module": m, "action": a, "goal": goal} for m, a in WEEK4_PIPELINE]
            self.memory.set_memory_key(project_id, "plan", plan)
            self.memory.set_memory_key(project_id, "pipeline_mode", "week4")
            tasks: list[dict[str, Any]] = []
            for module, action in WEEK4_PIPELINE:
                t = self.memory.enqueue_task(
                    project_id,
                    module,
                    action,
                    payload={**payload, "goal": goal, "mode": "week4"},
                )
                tasks.append(t)
            return tasks

        if week3:
            plan = [{"module": m, "action": a, "goal": goal} for m, a in WEEK3_PIPELINE]
            self.memory.set_memory_key(project_id, "plan", plan)
            self.memory.set_memory_key(project_id, "pipeline_mode", "week3")
            tasks = []
            for module, action in WEEK3_PIPELINE:
                t = self.memory.enqueue_task(
                    project_id,
                    module,
                    action,
                    payload={**payload, "goal": goal, "mode": "week3"},
                )
                tasks.append(t)
            return tasks

        if week2:
            plan = [{"module": m, "action": a, "goal": goal} for m, a in WEEK2_PIPELINE]
            self.memory.set_memory_key(project_id, "plan", plan)
            self.memory.set_memory_key(project_id, "pipeline_mode", "week2")
            tasks = []
            for module, action in WEEK2_PIPELINE:
                t = self.memory.enqueue_task(
                    project_id,
                    module,
                    action,
                    payload={**payload, "goal": goal, "mode": "week2"},
                )
                tasks.append(t)
            return tasks

        has_path = bool(
            payload.get("path")
            or payload.get("file")
            or payload.get("drawing_path")
            or payload.get("photo_path")
            or payload.get("pdf_path")
        )

        if has_path:
            first_steps = [
                ("engineering", "analyze_input"),
                ("visualization", "design_review"),
            ]
        else:
            first_steps = [
                ("design", "brief_from_goal"),
                ("visualization", "design_review"),
            ]

        plan = [
            *[{"module": m, "action": a, "goal": goal} for m, a in first_steps],
            *[
                {"module": m, "action": a, "goal": goal, "after_approve": True}
                for m, a in POST_APPROVAL
            ],
        ]
        self.memory.set_memory_key(project_id, "plan", plan)
        self.memory.set_memory_key(
            project_id, "pipeline_mode", "full_path" if has_path else "full_nl"
        )

        tasks = []
        for module, action in first_steps:
            t = self.memory.enqueue_task(
                project_id,
                module,
                action,
                payload={**payload, "goal": goal},
            )
            tasks.append(t)
        return tasks

    def _current_analysis(self, project_id: str) -> dict:
        mem = self.memory.get_memory(project_id) or {}
        for key in (
            "result:engineering.revise_from_review",
            "result:design.refine_brief",
            "result:design.brief_from_goal",
            "result:engineering.analyze_input",
            "design_brief",
            "analysis",
        ):
            val = mem.get(key)
            if isinstance(val, dict) and val:
                # design_brief alone → обернуть
                if key == "design_brief" and "design_brief" not in val:
                    return {
                        "design_brief": val,
                        "dimensions_mm": val.get("dimensions_mm") or {},
                        "materials": val.get("materials") or [],
                        "style": val.get("style") or [],
                        "cct_k": (val.get("led") or {}).get("cct_k"),
                        "geometry": {"type": val.get("fixture_type") or "fixture"},
                        "led": val.get("led") or {},
                    }
                return val
        return {}

    def _enqueue_post_approval(self, project_id: str, base_payload: dict, analysis: dict) -> None:
        if self.memory.get_memory(project_id, "post_approval_enqueued"):
            return
        brief = analysis.get("design_brief") if isinstance(analysis, dict) else None
        pl = {**base_payload, "analysis": analysis}
        if isinstance(brief, dict):
            pl["design_brief"] = brief
        for module, action in POST_APPROVAL:
            self.memory.enqueue_task(project_id, module, action, payload=pl)
        self.memory.set_memory_key(project_id, "post_approval_enqueued", True)

    def _handle_design_review(
        self,
        project_id: str,
        task: dict,
        result: dict,
        base_payload: dict,
    ) -> Optional[str]:
        """Verify-цикл. Возвращает причину fail или None."""
        data = result.get("data") or {}
        approved = bool(data.get("approved"))
        remarks = list(data.get("remarks") or [])
        iteration = int(self.memory.get_memory(project_id, "verify_iteration") or 0)

        loop = list(self.memory.get_memory(project_id, "verify_loop") or [])
        loop.append({"iteration": iteration, "approved": approved, "remarks": remarks})
        self.memory.set_memory_key(project_id, "verify_loop", loop)

        if approved:
            analysis = self._current_analysis(project_id)
            self.memory.set_memory_key(project_id, "analysis", analysis)
            self.memory.set_memory_key(project_id, "design_approved", True)
            self._enqueue_post_approval(project_id, base_payload, analysis)
            return None

        hist = list(self.memory.get_memory(project_id, "design_remarks") or [])
        hist.append({"iteration": iteration, "remarks": remarks})
        self.memory.set_memory_key(project_id, "design_remarks", hist)

        next_iter = iteration + 1
        self.memory.set_memory_key(project_id, "verify_iteration", next_iter)

        if next_iter >= VERIFY_MAX:
            reason = f"дизайн не утверждён за {VERIFY_MAX} итераций: {remarks}"
            self.memory.set_memory_key(project_id, "fail_reason", reason)
            self.memory.update_project_status(project_id, "failed")
            return reason

        analysis = self._current_analysis(project_id)
        # если старт с NL — refine через design, иначе engineering.revise
        started_nl = (self.memory.get_memory(project_id, "pipeline_mode") or "") == "full_nl"
        if started_nl:
            self.memory.enqueue_task(
                project_id,
                "design",
                "refine_brief",
                payload={**base_payload, "analysis": analysis, "remarks": remarks},
                parent_id=task["id"],
            )
        else:
            self.memory.enqueue_task(
                project_id,
                "engineering",
                "revise_from_review",
                payload={**base_payload, "analysis": analysis, "remarks": remarks},
                parent_id=task["id"],
            )
        self.memory.enqueue_task(
            project_id,
            "visualization",
            "design_review",
            payload={**base_payload, "analysis": analysis, "remarks": remarks},
            parent_id=task["id"],
        )
        return None

    def confirm(self, project_id: str) -> dict[str, Any]:
        """Снять паузу awaiting_confirm и продолжить очередь."""
        project = self.memory.get_project(project_id)
        if not project:
            raise KeyError(f"project {project_id}")
        gate = (project.get("memory") or {}).get("confirm_gate")
        self.memory.set_memory_key(project_id, "awaiting_confirm", False)
        self.memory.set_memory_key(project_id, "confirm_gate", None)
        queued = self.memory.list_tasks(project_id, status="queued")
        if queued:
            st = _STATUS_BY_MODULE.get(queued[0]["module"], "planning")
            self.memory.update_project_status(project_id, st)
        elif project.get("status") == "awaiting_confirm":
            self.memory.update_project_status(project_id, "planning")
        print(f"[autonomy] confirm project={project_id} gate={gate} mode={self.autonomy}")
        return self.memory.get_project(project_id)  # type: ignore[return-value]

    def _pause_for_confirm(self, project_id: str, action: str, task_id: str) -> None:
        gate = f"{action}:{task_id}"
        self.memory.set_memory_key(project_id, "awaiting_confirm", True)
        self.memory.set_memory_key(project_id, "confirm_gate", gate)
        self.memory.update_project_status(project_id, "awaiting_confirm")
        print(f"[autonomy] pause mode={self.autonomy} gate={gate}")

    def run_once(self, project_id: str) -> Optional[dict[str, Any]]:
        queued = self.memory.list_tasks(project_id, status="queued")
        if not queued:
            return None

        task = queued[0]
        project = self.memory.get_project(project_id)
        if not project:
            raise KeyError(f"project {project_id}")

        if project.get("status") == "failed":
            return None
        mem = project.get("memory") or {}
        if project.get("status") == "awaiting_confirm" or mem.get("awaiting_confirm"):
            print(f"[autonomy] blocked awaiting_confirm gate={mem.get('confirm_gate')}")
            return None

        self.memory.update_task(task["id"], status="running")
        module_status = _STATUS_BY_MODULE.get(task["module"])
        if module_status:
            self.memory.update_project_status(project_id, module_status)

        handler = MODULES.get(task["module"])
        if handler is None:
            self.memory.update_task(
                task["id"], status="failed", error=f"нет модуля: {task['module']}"
            )
            self.memory.update_project_status(project_id, "failed")
            return {"ok": False, "task_id": task["id"], "message": "нет модуля"}

        payload = dict(task["payload"] or {})
        analysis_actions = (
            "design_review",
            "export_dxf",
            "build_spec",
            "render",
            "revise_from_review",
            "refine_brief",
            "build_parametric",
            "export_viz_spec",
            "engineering_report",
            "thermal_calc",
            "electrical_calc",
            "mechanical_calc",
            "render_prompt",
            "preview_2d",
            "build_catalog_table",
            "site_fragment",
            "product_card",
            "price_quote",
        )
        if task["action"] in analysis_actions:
            if not payload.get("analysis") or task["action"] in (
                "design_review",
                "build_parametric",
                "export_viz_spec",
                "refine_brief",
                "engineering_report",
                "thermal_calc",
                "electrical_calc",
                "mechanical_calc",
                "render_prompt",
                "preview_2d",
                "build_catalog_table",
                "site_fragment",
                "product_card",
                "price_quote",
            ):
                fresh = self._current_analysis(project_id)
                if fresh:
                    payload["analysis"] = fresh
                    if isinstance(fresh.get("design_brief"), dict):
                        payload.setdefault("design_brief", fresh["design_brief"])
            # после build_parametric — подмешать модель
            if task["action"] == "export_viz_spec":
                model = (self.memory.get_memory(project_id) or {}).get(
                    "result:cad3d.build_parametric"
                )
                if isinstance(model, dict) and model.get("parts"):
                    payload["model"] = model
            # week3/4: geometry / viz_scene / eng из предыдущих шагов
            if task["action"] in (
                "engineering_report",
                "thermal_calc",
                "electrical_calc",
                "mechanical_calc",
                "render_prompt",
                "preview_2d",
                "build_catalog_table",
                "site_fragment",
                "product_card",
                "price_quote",
            ):
                mem = self.memory.get_memory(project_id) or {}
                export = mem.get("result:cad3d.export_viz_spec")
                if isinstance(export, dict):
                    payload.setdefault("cad3d_export", export)
                    if isinstance(export.get("geometry"), dict):
                        payload.setdefault("geometry", export["geometry"])
                        payload.setdefault("model", export["geometry"])
                    if isinstance(export.get("viz_scene"), dict):
                        payload.setdefault("viz_scene", export["viz_scene"])
                model = mem.get("result:cad3d.build_parametric")
                if isinstance(model, dict) and model.get("parts"):
                    payload.setdefault("model", model)
                    payload.setdefault("geometry", model)
                from shared.store import artifact_path as _ap

                payload.setdefault(
                    "geometry_path", str(_ap(project_id, "cad3d", "geometry.json"))
                )
                payload.setdefault(
                    "viz_scene_path", str(_ap(project_id, "cad3d", "viz_scene.json"))
                )
                payload.setdefault(
                    "engineering_report_path",
                    str(_ap(project_id, "engineering", "engineering_report.json")),
                )
                eng = mem.get("result:engineering.engineering_report")
                if isinstance(eng, dict):
                    # engineering_report handler may nest under report/data keys
                    payload.setdefault(
                        "engineering_report",
                        eng.get("report") or eng.get("engineering_report") or eng,
                    )
                db = mem.get("design_brief")
                if isinstance(db, dict):
                    payload.setdefault("design_brief", db)
                cat = mem.get("result:catalogs.build_catalog_table")
                if isinstance(cat, dict) and cat.get("rows"):
                    payload.setdefault("catalog_row", cat["rows"][0])

        try:
            result = handler(task["action"], payload, project)
        except Exception as exc:  # noqa: BLE001
            self.memory.update_task(task["id"], status="failed", error=str(exc))
            self.memory.update_project_status(project_id, "failed")
            return {"ok": False, "task_id": task["id"], "message": str(exc)}

        ok = bool(result.get("ok"))
        if ok:
            for art in result.get("artifacts") or []:
                self.memory.add_artifact(
                    project_id,
                    kind=art.get("kind", "other"),
                    path=art["path"],
                    mime=art.get("mime", "application/octet-stream"),
                    meta=art.get("meta") or {},
                )
            self.memory.update_task(task["id"], status="done")
            self.memory.set_memory_key(
                project_id,
                f"result:{task['module']}.{task['action']}",
                result.get("data") or {},
            )
            if task["action"] in (
                "analyze_input",
                "revise_from_review",
                "brief_from_goal",
                "refine_brief",
            ):
                data = result.get("data") or {}
                self.memory.set_memory_key(project_id, "analysis", data)
                if isinstance(data.get("design_brief"), dict):
                    self.memory.set_memory_key(
                        project_id, "design_brief", data["design_brief"]
                    )

            if task["action"] == "design_review":
                fail_reason = self._handle_design_review(
                    project_id, task, result, payload
                )
                if fail_reason:
                    return {
                        "ok": False,
                        "task_id": task["id"],
                        "module": task["module"],
                        "action": task["action"],
                        "message": fail_reason,
                        "data": result.get("data") or {},
                        "artifacts": result.get("artifacts") or [],
                    }
        else:
            self.memory.update_task(
                task["id"],
                status="failed",
                error=result.get("message") or "failed",
            )
            self.memory.update_project_status(project_id, "failed")

        return {
            "ok": ok,
            "task_id": task["id"],
            "module": task["module"],
            "action": task["action"],
            "message": result.get("message", ""),
            "data": result.get("data") or {},
            "artifacts": result.get("artifacts") or [],
        }

    def run_all(self, project_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for _ in range(50):
            r = self.run_once(project_id)
            if r is None:
                break
            results.append(r)
            if not r.get("ok"):
                break
            action = r.get("action") or ""
            if should_pause(self.autonomy, action, after_ok=True):
                remaining_now = self.memory.list_tasks(project_id, status="queued")
                if remaining_now:
                    self._pause_for_confirm(project_id, action, r.get("task_id") or "")
                    break

        remaining = self.memory.list_tasks(project_id, status="queued")
        failed = self.memory.list_tasks(project_id, status="failed")
        project = self.memory.get_project(project_id)
        if (
            project
            and project.get("status") not in ("failed", "awaiting_confirm")
            and not remaining
            and not failed
        ):
            self.memory.update_project_status(project_id, "done")
            # Ф0: автоснимок версии после успешного прогона (без дублей)
            try:
                from projects import auto_version

                auto_version(project_id, f"Пайплайн завершён ({len(results)} шаг.)")
            except Exception as exc:  # noqa: BLE001
                print(f"[projects] auto_version failed: {exc}", file=sys.stderr)
        return results


def _ensure_demo_sample() -> Path:
    samples = DATA_DIR / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    png = samples / "sconce_demo.png"
    if not png.exists():
        try:
            from PIL import Image, ImageDraw

            img = Image.new("RGB", (64, 16), color=(180, 140, 60))
            draw = ImageDraw.Draw(img)
            draw.rectangle([2, 4, 61, 11], outline=(40, 40, 40), fill=(220, 190, 100))
            img.save(png)
        except Exception:
            import struct
            import zlib

            def chunk(tag: bytes, data: bytes) -> bytes:
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            raw = b"\x00" + b"\xff\x00\x00"
            png.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b"")
            )
    return png


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m orchestrator.orchestrator")
    ap.add_argument(
        "--autonomy",
        choices=("full_auto", "confirm_key_points", "step_by_step"),
        default=None,
        help="режим автономности (или env GILIL_AUTONOMY; default full_auto)",
    )
    args = ap.parse_args()
    orch = Orchestrator(autonomy=args.autonomy)
    print(f"autonomy={orch.autonomy}")
    sample = _ensure_demo_sample()
    project = orch.create_project("Линейное бра — демо", "order")
    print(f"project_id={project['id']}")
    print(f"title={project['title']} status={project['status']}")
    print(f"sample={sample}")

    tasks = orch.submit(
        project["id"],
        goal="фото → verify → DXF → паспорт + рендер → RFQ",
        payload={
            "input_type": "photo",
            "path": str(sample),
            "cct_k": 3000,
            "materials": ["brass"],
            "dimensions_mm": {"length": 600, "height": 40, "depth": 50},
            "style": ["modern_linear"],
            "geometry": {"type": "linear_sconce", "mount": "wall"},
        },
    )
    print(f"enqueued={len(tasks)}")
    for t in tasks:
        print(f"  queued {t['module']}.{t['action']} id={t['id']}")

    results = orch.run_all(project["id"])
    print(f"ran={len(results)}")
    for r in results:
        mark = "OK" if r.get("ok") else "FAIL"
        print(f"  [{mark}] {r.get('module')}.{r.get('action')}: {r.get('message')}")

    final = orch.memory.get_project(project["id"])
    assert final is not None
    print(f"final_status={final['status']}")
    print(f"artifacts={len(final['artifacts'])}")
    for a in final["artifacts"]:
        print(f"  {a['kind']}: {a['path']}")

    all_tasks = orch.memory.list_tasks(project["id"])
    for t in all_tasks:
        print(f"task {t['module']}.{t['action']} -> {t['status']}")

    mem = final["memory"]
    print(f"verify_iteration={mem.get('verify_iteration')}")
    print(f"design_remarks={mem.get('design_remarks')}")


if __name__ == "__main__":
    main()
