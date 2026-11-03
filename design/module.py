"""Дизайн: NL-цель → структурированное ТЗ (design_brief)."""
from __future__ import annotations

import json
import re
from typing import Any

from shared.store import artifact_path

_DIAM_RE = re.compile(
    r"(?:[Øø⌀∅]|диаметр|diameter|\bD\b)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(?:mm|мм)?",
    re.I,
)
_HEIGHT_RE = re.compile(
    r"(?:высота|height|\bH\b)\s*[:=×xх*]?\s*(\d+(?:[.,]\d+)?)\s*(?:mm|мм)?",
    re.I,
)
_LEN_RE = re.compile(
    r"(?:длина|length|\bL\b)\s*[:=×xх*]?\s*(\d+(?:[.,]\d+)?)\s*(?:mm|мм)?",
    re.I,
)
_LAMPS_RE = re.compile(
    r"(\d+)\s*(?:ламп\w*|led|светодиод\w*|лампоч\w*|light\s*sources?)",
    re.I,
)
_CCT_RE = re.compile(r"(\d{4})\s*[KkКк]")

_MATERIAL_MAP = [
    (re.compile(r"латунь|brass", re.I), "brass"),
    (re.compile(r"хрустал|crystal", re.I), "crystal"),
    (re.compile(r"нерж|stainless|steel", re.I), "stainless"),
    (re.compile(r"алебастр|alabaster", re.I), "alabaster"),
    (re.compile(r"алюмин|alumin", re.I), "aluminum"),
    (re.compile(r"стекл|glass", re.I), "glass"),
]

_STYLE_MAP = [
    (re.compile(r"baccarat|баккара", re.I), "Baccarat"),
    (re.compile(r"modern|современ", re.I), "modern"),
    (re.compile(r"classic|классик", re.I), "classic"),
    (re.compile(r"linear|линейн", re.I), "modern_linear"),
    (re.compile(r"минимал|minimal", re.I), "minimal"),
    (re.compile(r"арт[\s-]?деко|art[\s-]?deco", re.I), "art_deco"),
]


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _parse_goal(goal: str) -> dict[str, Any]:
    text = goal or ""
    dims: dict[str, Any] = {}
    m = _DIAM_RE.search(text)
    if m:
        dims["diameter"] = int(_num(m.group(1)))
    m = _HEIGHT_RE.search(text)
    if m:
        dims["height"] = int(_num(m.group(1)))
    m = _LEN_RE.search(text)
    if m and "diameter" not in dims:
        dims["length"] = int(_num(m.group(1)))

    # Ø1200 H900 без слов
    if "diameter" not in dims:
        m = re.search(r"[Øø⌀∅]\s*(\d+)", text)
        if m:
            dims["diameter"] = int(m.group(1))
    if "height" not in dims:
        m = re.search(r"\bH\s*(\d{2,4})\b", text, re.I)
        if m:
            dims["height"] = int(m.group(1))

    lamps = 0
    m = _LAMPS_RE.search(text)
    if m:
        lamps = int(m.group(1))

    cct = 3000
    m = _CCT_RE.search(text)
    if m:
        cct = int(m.group(1))

    materials: list[str] = []
    for rx, name in _MATERIAL_MAP:
        if rx.search(text) and name not in materials:
            materials.append(name)
    if not materials:
        materials = ["brass"]

    styles: list[str] = []
    for rx, name in _STYLE_MAP:
        if rx.search(text) and name not in styles:
            styles.append(name)
    if re.search(r"люстр|chandelier|подвес", text, re.I):
        if "chandelier" not in styles:
            styles.append("chandelier")
    if not styles:
        styles = ["modern"]

    fixture = "chandelier" if ("diameter" in dims or "chandelier" in styles or re.search(r"люстр|chandelier", text, re.I)) else "fixture"
    title_bits = []
    if any(s.lower() == "baccarat" for s in styles):
        title_bits.append("Baccarat")
    title_bits.append("люстра" if fixture == "chandelier" else "светильник")
    if dims.get("diameter"):
        title_bits.append(f"Ø{dims['diameter']}")
    if dims.get("height"):
        title_bits.append(f"H{dims['height']}")
    title = " ".join(title_bits)

    watts_est = max(1, lamps) * 5 if lamps else 40

    variants = [
        {
            "id": "v1_classic",
            "label": "Классика",
            "notes": "базовая компоновка по ТЗ",
        },
        {
            "id": "v2_dense",
            "label": "Плотная подвеска",
            "notes": "больше хрустальных элементов, тот же Ø",
        },
        {
            "id": "v3_lite",
            "label": "Облегчённый",
            "notes": "меньше подвесок, акцент на каркасе",
        },
    ]

    design_brief = {
        "title": title,
        "style": styles,
        "materials": materials,
        "dimensions_mm": dims,
        "led": {"count": lamps or 12, "cct_k": cct, "watts_est": watts_est},
        "variants": variants,
        "fixture_type": fixture,
        "goal": text,
    }

    geometry = {
        "type": fixture,
        "mount": "ceiling" if fixture == "chandelier" else "wall",
        "shape": "circular" if "diameter" in dims else "rect",
    }

    return {
        "geometry": geometry,
        "dimensions_mm": dims,
        "materials": materials,
        "style": styles,
        "confidence": 0.85 if dims else 0.55,
        "source": "nl_goal",
        "input_type": "unknown",
        "cct_k": cct,
        "iteration": 0,
        "ok": True,
        "design_brief": design_brief,
        "led": design_brief["led"],
    }


def _apply_edits(base: dict[str, Any], edits: dict | None, remarks: list | None) -> dict[str, Any]:
    out = json.loads(json.dumps(base))  # deep copy
    brief = dict(out.get("design_brief") or {})
    edits = edits or {}

    if "title" in edits:
        brief["title"] = edits["title"]
    if "style" in edits:
        brief["style"] = list(edits["style"])
        out["style"] = list(edits["style"])
    if "materials" in edits:
        brief["materials"] = list(edits["materials"])
        out["materials"] = list(edits["materials"])
    if "dimensions_mm" in edits:
        dims = dict(brief.get("dimensions_mm") or {})
        dims.update(edits["dimensions_mm"])
        brief["dimensions_mm"] = dims
        out["dimensions_mm"] = dims
    if "led" in edits:
        led = dict(brief.get("led") or {})
        led.update(edits["led"])
        brief["led"] = led
        out["led"] = led
        if "cct_k" in led:
            out["cct_k"] = led["cct_k"]
    if "variants" in edits:
        brief["variants"] = list(edits["variants"])

    for raw in remarks or []:
        r = (raw or "").lower()
        if "латунь" in r or "brass" in r:
            mats = list(brief.get("materials") or [])
            if "brass" not in mats:
                mats.append("brass")
            brief["materials"] = mats
            out["materials"] = mats
        if "хрустал" in r or "crystal" in r:
            mats = list(brief.get("materials") or [])
            if "crystal" not in mats:
                mats.append("crystal")
            brief["materials"] = mats
            out["materials"] = mats
        m = re.search(r"(\d{4})\s*k", r)
        if m or "cct" in r:
            cct = int(m.group(1)) if m else 3000
            led = dict(brief.get("led") or {})
            led["cct_k"] = cct
            brief["led"] = led
            out["cct_k"] = cct
            out["led"] = led

    out["design_brief"] = brief
    return out


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    payload = payload or {}

    if action == "brief_from_goal":
        goal = payload.get("goal") or project.get("title") or ""
        data = _parse_goal(goal)
        # подмешать явные поля payload
        if payload.get("materials"):
            data["materials"] = list(payload["materials"])
            data["design_brief"]["materials"] = list(payload["materials"])
        if payload.get("dimensions_mm"):
            data["dimensions_mm"] = dict(payload["dimensions_mm"])
            data["design_brief"]["dimensions_mm"] = dict(payload["dimensions_mm"])
        if payload.get("cct_k") is not None:
            data["cct_k"] = int(payload["cct_k"])
            data["design_brief"]["led"]["cct_k"] = int(payload["cct_k"])

        brief_path = artifact_path(pid, "design", "design_brief.json")
        brief_path.write_text(
            json.dumps(data["design_brief"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        concepts_path = artifact_path(pid, "design", "concepts.json")
        concepts = {
            "selected": "v1_classic",
            "variants": data["design_brief"].get("variants") or [],
        }
        concepts_path.write_text(
            json.dumps(concepts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "design_brief",
                    "path": str(brief_path),
                    "mime": "application/json",
                    "meta": {"action": action},
                },
                {
                    "kind": "other",
                    "path": str(concepts_path),
                    "mime": "application/json",
                    "meta": {"action": action, "name": "concepts"},
                },
            ],
            "message": f"ТЗ: {data['design_brief'].get('title', 'design')}",
        }

    if action == "refine_brief":
        base = (
            payload.get("design_brief")
            and {"design_brief": payload["design_brief"], **(payload.get("analysis") or {})}
        ) or payload.get("analysis") or {}
        if "design_brief" not in base and payload.get("goal"):
            base = _parse_goal(payload["goal"])
        data = _apply_edits(
            base,
            payload.get("edits"),
            payload.get("remarks") or payload.get("design_remarks"),
        )
        brief_path = artifact_path(pid, "design", "design_brief.json")
        brief_path.write_text(
            json.dumps(data.get("design_brief") or data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "design_brief",
                    "path": str(brief_path),
                    "mime": "application/json",
                    "meta": {"action": action},
                }
            ],
            "message": "ТЗ уточнено",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
