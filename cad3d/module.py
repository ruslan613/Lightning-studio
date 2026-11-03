"""3D-конструктор: параметрическая модель + viz-спека (без Blender)."""
from __future__ import annotations

import json
import math
from typing import Any

from shared.store import artifact_path


def _brief_from_payload(payload: dict) -> dict[str, Any]:
    if isinstance(payload.get("design_brief"), dict):
        return payload["design_brief"]
    analysis = payload.get("analysis") or {}
    if isinstance(analysis.get("design_brief"), dict):
        return analysis["design_brief"]
    # собрать из analysis
    dims = dict(analysis.get("dimensions_mm") or payload.get("dimensions_mm") or {})
    materials = list(analysis.get("materials") or payload.get("materials") or ["brass"])
    styles = list(analysis.get("style") or payload.get("style") or ["modern"])
    led = analysis.get("led") or payload.get("led") or {}
    if not led:
        led = {
            "count": int(payload.get("lamp_count") or 12),
            "cct_k": int(analysis.get("cct_k") or payload.get("cct_k") or 3000),
            "watts_est": 60,
        }
    geom = analysis.get("geometry") or {}
    return {
        "title": payload.get("goal") or "fixture",
        "style": styles,
        "materials": materials,
        "dimensions_mm": dims,
        "led": led,
        "fixture_type": geom.get("type") or ("chandelier" if "diameter" in dims else "fixture"),
        "variants": [],
    }


def _build_model(brief: dict[str, Any]) -> dict[str, Any]:
    dims = dict(brief.get("dimensions_mm") or {})
    diameter = float(dims.get("diameter") or dims.get("width") or dims.get("length") or 800)
    height = float(dims.get("height") or 600)
    depth = float(dims.get("depth") or (80 if "diameter" not in dims else diameter))
    materials = list(brief.get("materials") or ["brass"])
    primary = materials[0] if materials else "brass"
    secondary = materials[1] if len(materials) > 1 else primary
    led = dict(brief.get("led") or {})
    count = int(led.get("count") or 12)
    cct = int(led.get("cct_k") or 3000)
    fixture = brief.get("fixture_type") or ("chandelier" if "diameter" in dims else "fixture")

    canopy_d = min(180.0, diameter * 0.15)
    rod_len = max(200.0, height * 0.35)
    ring_h = 40.0
    crystal_len = max(80.0, height * 0.25)

    parts = [
        {
            "name": "ceiling_canopy",
            "type": "disk",
            "dims_mm": {"diameter": canopy_d, "height": 25},
            "material": primary,
            "qty": 1,
        },
        {
            "name": "suspension_rod",
            "type": "cylinder",
            "dims_mm": {"diameter": 16, "length": rod_len},
            "material": primary,
            "qty": 1,
        },
        {
            "name": "main_ring",
            "type": "torus_ring",
            "dims_mm": {"diameter": diameter, "profile": ring_h},
            "material": primary,
            "qty": 1,
        },
    ]
    if "crystal" in materials or "glass" in materials:
        parts.append(
            {
                "name": "crystal_pendant",
                "type": "prism",
                "dims_mm": {"length": crystal_len, "width": 18, "depth": 18},
                "material": secondary if secondary in ("crystal", "glass") else "crystal",
                "qty": max(count * 2, 24),
            }
        )
    parts.append(
        {
            "name": "led_holder",
            "type": "socket",
            "dims_mm": {"diameter": 35, "height": 45},
            "material": primary,
            "qty": count,
        }
    )

    # круговое размещение LED
    r = diameter / 2.0 * 0.85
    led_positions = []
    for i in range(count):
        ang = 2 * math.pi * i / max(count, 1)
        led_positions.append(
            {
                "index": i,
                "x": round(r * math.cos(ang), 2),
                "y": round(r * math.sin(ang), 2),
                "z": round(-rod_len, 2),
            }
        )

    bbox = {
        "x": diameter if fixture == "chandelier" else float(dims.get("length") or diameter),
        "y": diameter if fixture == "chandelier" else float(dims.get("depth") or depth),
        "z": height,
    }

    return {
        "units": "mm",
        "fixture_type": fixture,
        "title": brief.get("title"),
        "parts": parts,
        "led_layout": {
            "count": count,
            "cct_k": cct,
            "watts_est": led.get("watts_est"),
            "pattern": "circular" if fixture == "chandelier" else "linear",
            "positions": led_positions,
        },
        "bbox_mm": bbox,
        "materials": materials,
        "style": list(brief.get("style") or []),
        "dimensions_mm": dims,
    }


def _viz_scene(model: dict[str, Any]) -> dict[str, Any]:
    bbox = model.get("bbox_mm") or {}
    cx = float(bbox.get("x") or 800) / 2
    cy = float(bbox.get("y") or 800) / 2
    cz = float(bbox.get("z") or 600) / 2
    dist = max(cx, cy, cz) * 2.5
    mats = model.get("materials") or ["brass"]
    return {
        "engine": "blender_later",
        "units": "mm",
        "camera": {
            "location": [dist, -dist, dist * 0.8],
            "look_at": [0, 0, -cz],
            "focal_mm": 50,
        },
        "lights": [
            {"type": "area", "power": 200, "location": [dist, dist, dist]},
            {"type": "point", "power": 50, "location": [0, 0, -cz]},
        ],
        "materials_refs": [
            {"name": m, "shader": "principled", "source": "gilil_lib"} for m in mats
        ],
        "geometry_ref": "geometry.json",
        "bbox_mm": bbox,
    }


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    payload = payload or {}

    if action == "build_parametric":
        brief = _brief_from_payload(payload)
        model = _build_model(brief)
        path = artifact_path(pid, "cad3d", "parametric_model.json")
        path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": model,
            "artifacts": [
                {
                    "kind": "geometry",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action, "name": "parametric_model"},
                }
            ],
            "message": f"параметрика: {len(model.get('parts') or [])} частей",
        }

    if action == "export_viz_spec":
        # взять модель из payload / memory-результата / пересобрать
        model = payload.get("model") or payload.get("parametric_model")
        if not isinstance(model, dict) or not model.get("parts"):
            brief = _brief_from_payload(payload)
            model = _build_model(brief)

        geom_path = artifact_path(pid, "cad3d", "geometry.json")
        viz_path = artifact_path(pid, "cad3d", "viz_scene.json")
        geom_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        scene = _viz_scene(model)
        viz_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": {"geometry": model, "viz_scene": scene},
            "artifacts": [
                {
                    "kind": "geometry",
                    "path": str(geom_path),
                    "mime": "application/json",
                    "meta": {"action": action, "name": "geometry"},
                },
                {
                    "kind": "other",
                    "path": str(viz_path),
                    "mime": "application/json",
                    "meta": {"action": action, "name": "viz_scene"},
                },
            ],
            "message": "geometry.json + viz_scene.json",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
