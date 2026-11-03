"""Инженерный модуль: анализ входа, ревизия, DXF, паспорт."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.store import artifact_path

from . import pdf_input, photo_input, video_input
from . import reports

_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
_PDF_EXT = {".pdf"}
_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def _detect_input_type(payload: dict) -> str:
    t = (payload.get("input_type") or "").lower().strip()
    if t in ("photo", "pdf", "video", "unknown"):
        return t
    path = payload.get("path") or payload.get("file") or payload.get("drawing_path") or ""
    ext = Path(str(path)).suffix.lower()
    if ext in _PHOTO_EXT:
        return "photo"
    if ext in _PDF_EXT:
        return "pdf"
    if ext in _VIDEO_EXT:
        return "video"
    return "unknown"


def _path_from_payload(payload: dict) -> str | None:
    for k in ("path", "file", "drawing_path", "photo_path", "pdf_path", "video_path"):
        if payload.get(k):
            return str(payload[k])
    return None


def _analyze_input(payload: dict) -> dict[str, Any]:
    kind = _detect_input_type(payload)
    path = _path_from_payload(payload)
    if kind == "photo":
        data = photo_input.analyze(path, payload)
    elif kind == "pdf":
        data = pdf_input.analyze(path, payload)
    elif kind == "video":
        data = video_input.analyze(path, payload)
    else:
        # неизвестный тип — фото-эвристика по payload
        data = photo_input.analyze(path, payload)
        data["source"] = "unknown"
    data["input_type"] = kind
    return data


def _apply_remarks(analysis: dict, remarks: list[str]) -> dict[str, Any]:
    """Применить замечания дизайна к анализу."""
    out = dict(analysis)
    out["materials"] = list(analysis.get("materials") or [])
    out["style"] = list(analysis.get("style") or [])
    dims = dict(analysis.get("dimensions_mm") or {})
    geom = dict(analysis.get("geometry") or {})
    cct = analysis.get("cct_k")
    applied: list[str] = []

    for raw in remarks:
        r = (raw or "").lower()
        # материалы
        if "plastic" in r or "пластик" in r or "material" in r or "материал" in r:
            banned = {"plastic", "пластик", "chrome-plastic", "abs"}
            out["materials"] = [m for m in out["materials"] if m.lower() not in banned]
            if "brass" in r or "латунь" in r:
                if "brass" not in [m.lower() for m in out["materials"]]:
                    out["materials"].append("brass")
            elif "stainless" in r or "нерж" in r:
                if "stainless" not in [m.lower() for m in out["materials"]]:
                    out["materials"].append("stainless")
            elif "aluminum" in r or "алюмин" in r:
                if "aluminum" not in [m.lower() for m in out["materials"]]:
                    out["materials"].append("aluminum")
            elif not out["materials"]:
                out["materials"].append("brass")
            applied.append(raw)
        if any(x in r for x in ("brass", "латунь", "stainless", "aluminum", "alabaster", "glass",
                                 "нерж", "алюмин", "алебастр", "стекло")) and "material" not in r and "материал" not in r:
            # прямое указание материала
            mapping = [
                ("brass", "brass"), ("латунь", "brass"),
                ("stainless", "stainless"), ("нерж", "stainless"),
                ("aluminum", "aluminum"), ("алюмин", "aluminum"),
                ("alabaster", "alabaster"), ("алебастр", "alabaster"),
                ("glass", "glass"), ("стекло", "glass"),
            ]
            for needle, name in mapping:
                if needle in r and name not in [m.lower() for m in out["materials"]]:
                    # заменить запрещённые
                    out["materials"] = [
                        m for m in out["materials"]
                        if m.lower() not in {"plastic", "пластик", "abs"}
                    ]
                    out["materials"].append(name)
                    applied.append(raw)
                    break
        # CCT
        if "cct" in r or "температур" in r or "kelvin" in r or "k " in r or r.endswith("k"):
            import re
            m = re.search(r"(\d{4})", raw)
            if m:
                cct = int(m.group(1))
                applied.append(raw)
            elif "3000" in r or "4000" in r:
                cct = 3000
                applied.append(raw)
            elif cct is None or not (3000 <= int(cct) <= 4000):
                cct = 3000
                applied.append(raw)
        # пропорции
        if "proportion" in r or "пропорц" in r or "length" in r or "height" in r or "длин" in r:
            L = float(dims.get("length") or 600)
            H = float(dims.get("height") or 40)
            ratio = L / H if H else 0
            if ratio < 3:
                dims["length"] = max(L, H * 8)
                applied.append(raw)
            elif ratio > 40:
                dims["height"] = max(H, L / 20)
                applied.append(raw)
            elif not dims:
                dims = {"length": 600, "height": 40, "depth": 50}
                applied.append(raw)
        # стиль
        if "baroque" in r or "crystal" in r or "барокко" in r or "хрустал" in r or "style" in r or "стил" in r:
            out["style"] = [s for s in out["style"] if not any(
                x in str(s).lower() for x in ("baroque", "crystal", "барокко", "хрустал")
            )]
            if "modern_linear" not in out["style"]:
                out["style"].append("modern_linear")
            applied.append(raw)

    if not out["materials"]:
        out["materials"] = ["brass"]
    out["dimensions_mm"] = dims or {"length": 600, "height": 40, "depth": 50}
    out["geometry"] = geom or {"type": "linear_sconce", "mount": "wall"}
    out["cct_k"] = cct if cct is not None else 3000
    out["iteration"] = int(analysis.get("iteration") or 0) + 1
    out["remarks_applied"] = applied
    out["ok"] = True
    return out


def _export_dxf(pid: str, analysis: dict) -> dict[str, Any]:
    import ezdxf  # type: ignore

    # dims из analysis или вложенного design_brief
    dims = dict(analysis.get("dimensions_mm") or {})
    brief = analysis.get("design_brief") if isinstance(analysis.get("design_brief"), dict) else {}
    if brief.get("dimensions_mm"):
        for k, v in brief["dimensions_mm"].items():
            dims.setdefault(k, v)
    L = float(dims.get("length") or dims.get("L") or dims.get("diameter") or 600)
    H = float(dims.get("height") or dims.get("H") or 40)
    D = float(dims.get("depth") or dims.get("W") or dims.get("D") or (dims.get("diameter") or 50))

    doc = ezdxf.new("R2010")
    for layer in ("OUTLINE", "HOLES", "LED", "NOTES"):
        if layer not in doc.layers:
            doc.layers.add(layer)
    msp = doc.modelspace()

    # корпус — прямоугольник
    msp.add_lwpolyline(
        [(0, 0), (L, 0), (L, H), (0, H), (0, 0)],
        dxfattribs={"layer": "OUTLINE", "closed": True},
    )
    # крепёжные отверстия
    hole_r = 3.0
    margin = min(50.0, L * 0.1)
    for x in (margin, L - margin):
        msp.add_circle((x, H / 2), hole_r, dxfattribs={"layer": "HOLES"})
    # зона LED-ленты
    led_y0, led_y1 = H * 0.25, H * 0.75
    msp.add_lwpolyline(
        [(10, led_y0), (L - 10, led_y0), (L - 10, led_y1), (10, led_y1), (10, led_y0)],
        dxfattribs={"layer": "LED", "closed": True},
    )
    mats = ", ".join(analysis.get("materials") or [])
    msp.add_text(
        f"Gilil linear sconce L={L} H={H} D={D} mat={mats}",
        dxfattribs={"layer": "NOTES", "height": max(5.0, H * 0.3)},
    ).set_placement((0, H + 10))

    dxf_path = artifact_path(pid, "engineering", "fixture.dxf")
    doc.saveas(str(dxf_path))

    meta = {
        "path": str(dxf_path),
        "layers": ["OUTLINE", "HOLES", "LED", "NOTES"],
        "dimensions_mm": {"length": L, "height": H, "depth": D},
        "materials": analysis.get("materials") or [],
        "format": "DXF R2010",
        "note": "полный DWG — следующим этапом",
    }
    meta_path = artifact_path(pid, "engineering", "fixture_dxf.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"meta": meta, "dxf_path": str(dxf_path), "meta_path": str(meta_path)}


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    payload = payload or {}

    if action == "analyze_input":
        data = _analyze_input(payload)
        path = artifact_path(pid, "engineering", "analysis.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "drawing",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action, "input_type": data.get("input_type")},
                }
            ],
            "message": f"анализ входа ({data.get('input_type')})",
        }

    if action == "revise_from_review":
        analysis = payload.get("analysis") or {}
        remarks = list(payload.get("remarks") or [])
        data = _apply_remarks(analysis, remarks)
        path = artifact_path(pid, "engineering", "analysis.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "drawing",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action, "iteration": data.get("iteration")},
                }
            ],
            "message": f"ревизия по замечаниям (iter={data.get('iteration')})",
        }

    if action == "export_dxf":
        analysis = dict(payload.get("analysis") or {})
        if payload.get("design_brief") and not analysis.get("design_brief"):
            analysis["design_brief"] = payload["design_brief"]
        if not analysis:
            # fallback stub dims
            analysis = {
                "dimensions_mm": {"length": 600, "height": 40, "depth": 50},
                "materials": payload.get("materials") or ["brass"],
            }
        try:
            exported = _export_dxf(pid, analysis)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "data": {},
                "artifacts": [],
                "message": f"DXF ошибка: {exc}",
            }
        return {
            "ok": True,
            "data": exported["meta"],
            "artifacts": [
                {
                    "kind": "drawing",
                    "path": exported["dxf_path"],
                    "mime": "application/dxf",
                    "meta": {"action": action},
                },
                {
                    "kind": "other",
                    "path": exported["meta_path"],
                    "mime": "application/json",
                    "meta": {"action": action},
                },
            ],
            "message": "DXF экспортирован",
        }

    if action == "build_spec":
        analysis = payload.get("analysis") or {}
        dims = analysis.get("dimensions_mm") or {}
        path = artifact_path(pid, "engineering", "spec.json")
        passport = artifact_path(pid, "engineering", "passport.md")
        data = {
            "power_w": payload.get("power_w", 24),
            "driver": "const-current 700mA",
            "ip": "IP20",
            "cct_k": [3000, 4000],
            "voltage_drop_v": 0.8,
            "materials": analysis.get("materials") or payload.get("materials") or ["brass"],
            "dimensions_mm": dims or {"length": 600, "height": 40, "depth": 50},
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        passport.write_text(
            "# Паспорт\n\n"
            f"Мощность: {data['power_w']} W\n"
            f"IP: {data['ip']}\n"
            f"CCT: {data['cct_k']}\n"
            f"Материалы: {', '.join(data['materials'])}\n"
            f"Размеры мм: {data['dimensions_mm']}\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "spec",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action},
                },
                {
                    "kind": "passport",
                    "path": str(passport),
                    "mime": "text/markdown",
                    "meta": {"action": action},
                },
            ],
            "message": "спецификация и паспорт",
        }

    if action == "thermal_calc":
        data = reports.thermal_calc(payload)
        path = artifact_path(pid, "engineering", "thermal_calc.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "other",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action},
                }
            ],
            "message": f"тепло: ΔT={data.get('delta_t_c')}°C {'PASS' if data.get('pass') else 'FAIL'}",
        }

    if action == "electrical_calc":
        data = reports.electrical_calc(payload)
        path = artifact_path(pid, "engineering", "electrical_calc.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "other",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action},
                }
            ],
            "message": f"электрика: {data.get('total_w')}W IP={data.get('suggested_ip')}",
        }

    if action == "mechanical_calc":
        data = reports.mechanical_calc(payload)
        path = artifact_path(pid, "engineering", "mechanical_calc.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "other",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action},
                }
            ],
            "message": f"механика: {data.get('mass_kg')} кг, {data.get('fastener')}",
        }

    if action == "engineering_report":
        data = reports.engineering_report(pid, payload)
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "eng_report",
                    "path": data["paths"]["json"],
                    "mime": "application/json",
                    "meta": {"action": action, "name": "engineering_report"},
                },
                {
                    "kind": "eng_report",
                    "path": data["paths"]["md"],
                    "mime": "text/markdown",
                    "meta": {"action": action, "name": "engineering_report_md"},
                },
            ],
            "message": f"инж.отчёт overall={'PASS' if data.get('overall_pass') else 'FAIL'}",
        }

    # совместимость: старый parse_drawing → analyze
    if action == "parse_drawing":
        return handle("analyze_input", {**payload, "input_type": payload.get("input_type") or "unknown"}, project)

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
