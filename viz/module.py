"""viz: render_prompt + preview_2d из geometry / viz_scene / design_brief."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shared.store import artifact_path


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _inputs(payload: dict, project: dict) -> tuple[dict, dict, dict]:
    brief = payload.get("design_brief")
    if not isinstance(brief, dict):
        analysis = payload.get("analysis") or {}
        brief = analysis.get("design_brief") if isinstance(analysis.get("design_brief"), dict) else {}
    brief = brief or {}

    geom = payload.get("geometry") or payload.get("model") or {}
    if not isinstance(geom, dict) or not geom.get("parts"):
        export = payload.get("cad3d_export") or {}
        if isinstance(export.get("geometry"), dict):
            geom = export["geometry"]
    if (not isinstance(geom, dict) or not geom.get("parts")) and payload.get("geometry_path"):
        geom = _load_json(payload["geometry_path"])
    if not isinstance(geom, dict):
        geom = {}

    scene = payload.get("viz_scene") or {}
    if not isinstance(scene, dict) or not scene:
        export = payload.get("cad3d_export") or {}
        if isinstance(export.get("viz_scene"), dict):
            scene = export["viz_scene"]
    if (not isinstance(scene, dict) or not scene) and payload.get("viz_scene_path"):
        scene = _load_json(payload["viz_scene_path"])
    # файлы проекта по умолчанию
    pid = project.get("id") or ""
    if pid and (not geom.get("parts")):
        geom = _load_json(artifact_path(pid, "cad3d", "geometry.json")) or geom
    if pid and not scene:
        scene = _load_json(artifact_path(pid, "cad3d", "viz_scene.json")) or scene
    if pid and not brief:
        brief = _load_json(artifact_path(pid, "design", "design_brief.json")) or brief
    return brief, geom, scene if isinstance(scene, dict) else {}


def _build_prompt(brief: dict, geom: dict, scene: dict) -> str:
    title = brief.get("title") or geom.get("title") or "luxury lighting fixture"
    mats = brief.get("materials") or geom.get("materials") or ["brass"]
    styles = brief.get("style") or geom.get("style") or []
    dims = brief.get("dimensions_mm") or geom.get("dimensions_mm") or {}
    fixture = brief.get("fixture_type") or geom.get("fixture_type") or "fixture"
    led = brief.get("led") or geom.get("led_layout") or {}
    cct = led.get("cct_k") or 3000
    count = led.get("count") or (geom.get("led_layout") or {}).get("count") or 12
    bbox = geom.get("bbox_mm") or scene.get("bbox_mm") or {}

    dim_bits = []
    if dims.get("diameter"):
        dim_bits.append(f"diameter {dims['diameter']} mm")
    if dims.get("height"):
        dim_bits.append(f"height {dims['height']} mm")
    if dims.get("length"):
        dim_bits.append(f"length {dims['length']} mm")
    if not dim_bits and bbox:
        dim_bits.append(f"bbox {bbox.get('x')}×{bbox.get('y')}×{bbox.get('z')} mm")

    parts = geom.get("parts") or []
    part_names = ", ".join(p.get("name", "?") for p in parts[:8])

    cam = (scene.get("camera") or {}) if scene else {}
    prompt = (
        f"Photorealistic product render of a Gilil {fixture}: {title}. "
        f"Style: {', '.join(map(str, styles)) or 'modern luxury'}. "
        f"Materials: {', '.join(map(str, mats))}. "
        f"Dimensions: {', '.join(dim_bits) or 'as designed'}. "
        f"Lighting: {count} LED sources at {cct}K, soft warm glow, subtle caustics if crystal/glass. "
        f"Parts: {part_names or 'canopy, ring, pendants'}. "
        f"Camera: studio three-quarter view"
        + (f", look_at {cam.get('look_at')}" if cam.get("look_at") else "")
        + ", shallow depth of field, clean dark-grey backdrop, high detail metal reflections, "
        f"catalog hero shot, 4K, physically based materials."
    )
    return prompt


def _render_prompt(pid: str, brief: dict, geom: dict, scene: dict) -> dict[str, Any]:
    prompt = _build_prompt(brief, geom, scene)
    txt_path = artifact_path(pid, "viz", "render_prompt.txt")
    meta_path = artifact_path(pid, "viz", "render_prompt.json")
    txt_path.write_text(prompt, encoding="utf-8")
    meta = {
        "prompt": prompt,
        "title": brief.get("title") or geom.get("title"),
        "materials": brief.get("materials") or geom.get("materials") or [],
        "style": brief.get("style") or geom.get("style") or [],
        "fixture_type": brief.get("fixture_type") or geom.get("fixture_type"),
        "source": {
            "has_geometry": bool(geom.get("parts")),
            "has_viz_scene": bool(scene),
            "has_brief": bool(brief),
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "prompt": prompt,
        "paths": {"txt": str(txt_path), "json": str(meta_path)},
        "meta": meta,
    }


def _preview_2d(pid: str, brief: dict, geom: dict) -> dict[str, Any]:
    """Ортогональное 2D-превью bbox/частей (matplotlib → Pillow fallback)."""
    out = artifact_path(pid, "viz", "preview_2d.png")
    bbox = dict(geom.get("bbox_mm") or {})
    dims = dict(brief.get("dimensions_mm") or geom.get("dimensions_mm") or {})
    w = float(bbox.get("x") or dims.get("diameter") or dims.get("length") or 800)
    h = float(bbox.get("z") or dims.get("height") or 600)
    parts = list(geom.get("parts") or [])
    led = (geom.get("led_layout") or {}).get("positions") or []
    title = brief.get("title") or geom.get("title") or "preview"

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

        fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
        ax.set_aspect("equal")
        ax.set_facecolor("#1a1a1e")
        fig.patch.set_facecolor("#121214")

        # основной контур (вид сбоку/фасад): ширина × высота
        ax.add_patch(
            FancyBboxPatch(
                (-w / 2, -h),
                w,
                h,
                boxstyle="round,pad=5",
                linewidth=1.5,
                edgecolor="#c9a227",
                facecolor="#2a2418",
                alpha=0.85,
            )
        )
        # кольцо (top-ish overlay as circle at mid height)
        ring = next((p for p in parts if "ring" in str(p.get("name", "")).lower()), None)
        if ring or dims.get("diameter"):
            rd = float((ring or {}).get("dims_mm", {}).get("diameter") or dims.get("diameter") or w) / 2
            cy = -h * 0.55
            ax.add_patch(
                Circle((0, cy), rd * 0.9, fill=False, edgecolor="#e8c547", linewidth=2)
            )

        # канопи сверху
        canopy = next((p for p in parts if "canopy" in str(p.get("name", "")).lower()), None)
        cd = float((canopy or {}).get("dims_mm", {}).get("diameter") or min(180, w * 0.15))
        ax.add_patch(
            Rectangle((-cd / 2, -20), cd, 20, facecolor="#b8963e", edgecolor="#f0d878")
        )

        # LED точки (проекция x→x, z→y)
        for pos in led[:64]:
            ax.plot(pos.get("x", 0), pos.get("z", -h / 2), "o", color="#ffe566", markersize=4)

        # кристаллы — маленькие прямоугольники по кругу
        crystal = next((p for p in parts if "crystal" in str(p.get("name", "")).lower()), None)
        if crystal:
            n = min(int(crystal.get("qty") or 24), 48)
            r = w / 2 * 0.75
            cl = float((crystal.get("dims_mm") or {}).get("length") or 100)
            for i in range(n):
                ang = 2 * math.pi * i / n
                x = r * math.cos(ang)
                y = -h * 0.55 - cl * 0.3
                ax.add_patch(
                    Rectangle(
                        (x - 4, y - cl * 0.15),
                        8,
                        cl * 0.3,
                        facecolor="#a8d4e8",
                        edgecolor="#d0eef8",
                        alpha=0.7,
                    )
                )

        margin = max(w, h) * 0.15
        ax.set_xlim(-w / 2 - margin, w / 2 + margin)
        ax.set_ylim(-h - margin, margin)
        ax.set_title(str(title)[:80], color="#eee", fontsize=11)
        ax.tick_params(colors="#888")
        for spine in ax.spines.values():
            spine.set_color("#444")
        ax.set_xlabel("mm", color="#888")
        ax.set_ylabel("mm", color="#888")
        fig.tight_layout()
        fig.savefig(str(out), facecolor=fig.get_facecolor())
        plt.close(fig)
        engine = "matplotlib"
    except Exception:
        # Pillow fallback
        from PIL import Image, ImageDraw

        size = 800
        img = Image.new("RGB", (size, size), (18, 18, 20))
        draw = ImageDraw.Draw(img)
        scale = min((size - 80) / max(w, 1), (size - 80) / max(h, 1))
        cx, cy = size // 2, size // 2 + int(h * scale / 4)

        def sx(x: float) -> float:
            return cx + x * scale

        def sy(z: float) -> float:
            return cy + z * scale  # z вниз отрицательный в модели

        draw.rectangle(
            [sx(-w / 2), sy(-h), sx(w / 2), sy(0)],
            outline=(201, 162, 39),
            width=2,
        )
        r = w / 2 * 0.9
        draw.ellipse(
            [sx(-r), sy(-h * 0.55 - r), sx(r), sy(-h * 0.55 + r)],
            outline=(232, 197, 71),
            width=2,
        )
        for pos in led[:64]:
            x, z = float(pos.get("x", 0)), float(pos.get("z", 0))
            draw.ellipse([sx(x) - 3, sy(z) - 3, sx(x) + 3, sy(z) + 3], fill=(255, 229, 102))
        img.save(out)
        engine = "pillow"

    return {
        "path": str(out),
        "engine": engine,
        "bbox_mm": {"x": w, "z": h},
        "parts": len(parts),
        "led_points": len(led),
    }


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    payload = payload or {}
    brief, geom, scene = _inputs(payload, project)

    if action == "render_prompt":
        data = _render_prompt(pid, brief, geom, scene)
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "other",
                    "path": data["paths"]["txt"],
                    "mime": "text/plain",
                    "meta": {"action": action, "name": "render_prompt"},
                },
                {
                    "kind": "other",
                    "path": data["paths"]["json"],
                    "mime": "application/json",
                    "meta": {"action": action, "name": "render_prompt_meta"},
                },
            ],
            "message": "промпт AI-рендера",
        }

    if action == "preview_2d":
        data = _preview_2d(pid, brief, geom)
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "render",
                    "path": data["path"],
                    "mime": "image/png",
                    "meta": {"action": action, "engine": data.get("engine")},
                }
            ],
            "message": f"2D-превью ({data.get('engine')})",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
