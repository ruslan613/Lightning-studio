"""Визуализация: design_review + рендер CCT 3000–4000K."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from shared.store import artifact_path

_ALLOWED_MATERIALS = {
    "brass", "stainless", "aluminum", "aluminium", "alabaster", "glass", "crystal",
    "латунь", "нержавейка", "алюминий", "алебастр", "стекло", "хрусталь",
}

_MATERIAL_ALIASES = {
    "латунь": "brass",
    "нержавейка": "stainless",
    "нерж": "stainless",
    "алюминий": "aluminum",
    "aluminium": "aluminum",
    "алебастр": "alabaster",
    "стекло": "glass",
    "хрусталь": "crystal",
}

# тяжёлый барокко без «коллекционного» Baccarat — конфликт для линейного Gilil
_CONFLICT_STYLE = re.compile(
    r"\b(baroque|rococo|victorian|барокко|рокок)\b",
    re.I,
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return _MATERIAL_ALIASES.get(s, s)


def _is_chandelier(analysis: dict) -> bool:
    geom = analysis.get("geometry") or {}
    gtype = str(geom.get("type") or "").lower()
    styles = analysis.get("style") or []
    if isinstance(styles, str):
        styles = [styles]
    style_blob = " ".join(str(s).lower() for s in styles)
    dims = analysis.get("dimensions_mm") or {}
    brief = analysis.get("design_brief") or {}
    if brief.get("fixture_type") == "chandelier":
        return True
    if "diameter" in dims or "diameter" in (brief.get("dimensions_mm") or {}):
        return True
    if "chandelier" in gtype or "люстр" in gtype:
        return True
    if "chandelier" in style_blob or "baccarat" in style_blob:
        return True
    return False


def design_review(analysis: dict) -> dict[str, Any]:
    """Правила совместимости с дизайном Gilil Lighting."""
    remarks: list[str] = []
    checks: dict[str, Any] = {}

    # design_brief → плоские поля
    brief = analysis.get("design_brief") if isinstance(analysis.get("design_brief"), dict) else {}
    if brief:
        if not analysis.get("materials") and brief.get("materials"):
            analysis = {**analysis, "materials": brief["materials"]}
        if not analysis.get("style") and brief.get("style"):
            analysis = {**analysis, "style": brief["style"]}
        if not analysis.get("dimensions_mm") and brief.get("dimensions_mm"):
            analysis = {**analysis, "dimensions_mm": brief["dimensions_mm"]}
        led = brief.get("led") or {}
        if analysis.get("cct_k") is None and led.get("cct_k") is not None:
            analysis = {**analysis, "cct_k": led["cct_k"]}

    chandelier = _is_chandelier(analysis)

    materials = analysis.get("materials") or []
    norm_mats = [_norm(m) for m in materials]
    allowed_norm = {_norm(m) for m in _ALLOWED_MATERIALS}
    ok_mats = [m for m in norm_mats if m in allowed_norm]
    checks["materials"] = {"input": materials, "normalized": norm_mats, "ok": bool(ok_mats)}
    if not materials:
        remarks.append("материалы не указаны — используйте brass/stainless/aluminum/alabaster/glass/crystal")
    elif not ok_mats:
        remarks.append(
            f"материалы несовместимы ({materials}); замените на brass (латунь) или stainless"
        )

    cct = analysis.get("cct_k")
    if isinstance(cct, (list, tuple)) and cct:
        cct = cct[0]
    try:
        cct_v = int(cct) if cct is not None else None
    except (TypeError, ValueError):
        cct_v = None
    checks["cct"] = {"value": cct_v}
    if cct_v is None:
        remarks.append("CCT не задан — укажите 3000–4000K")
        checks["cct"]["ok"] = False
    else:
        preferred = 3000 <= cct_v <= 4000
        wide = 2700 <= cct_v <= 4500
        checks["cct"]["preferred"] = preferred
        checks["cct"]["ok"] = wide
        if not wide:
            remarks.append(f"CCT {cct_v}K вне 2700–4500; поставьте 3000K")
        elif not preferred:
            remarks.append(f"CCT {cct_v}K вне предпочтительного 3000–4000K")

    dims = analysis.get("dimensions_mm") or {}
    if chandelier:
        D = dims.get("diameter") or dims.get("D")
        H = dims.get("height") or dims.get("H")
        try:
            Df = float(D) if D is not None else None
            Hf = float(H) if H is not None else None
        except (TypeError, ValueError):
            Df, Hf = None, None
        if Df and Hf and Df > 0:
            ratio = Hf / Df
            ok_prop = 0.3 <= ratio <= 2.5
            checks["proportions"] = {
                "diameter": Df, "height": Hf, "ratio_h_d": ratio, "ok": ok_prop, "kind": "chandelier"
            }
            if not ok_prop:
                remarks.append(
                    f"пропорции H/Ø={ratio:.2f} вне 0.3–2.5 (люстра); скорректируйте размеры"
                )
        else:
            checks["proportions"] = {"ok": False, "soft": True, "kind": "chandelier"}
            remarks.append("нет diameter/height — задайте габариты люстры")
    else:
        L = dims.get("length") or dims.get("L")
        H = dims.get("height") or dims.get("H")
        try:
            Lf = float(L) if L is not None else None
            Hf = float(H) if H is not None else None
        except (TypeError, ValueError):
            Lf, Hf = None, None
        if Lf and Hf and Hf > 0:
            ratio = Lf / Hf
            ok_prop = 3.0 <= ratio <= 40.0
            checks["proportions"] = {"length": Lf, "height": Hf, "ratio": ratio, "ok": ok_prop}
            if not ok_prop:
                remarks.append(
                    f"пропорции length/height={ratio:.1f} вне 3–40 (линейное бра); скорректируйте размеры"
                )
        else:
            checks["proportions"] = {"ok": False, "soft": True}
            remarks.append("нет length_mm/height_mm — задайте пропорции линейного бра (L/H 3–40)")

    styles = analysis.get("style") or []
    if isinstance(styles, str):
        styles = [styles]
    style_blob = " ".join(str(s) for s in styles)
    # Baccarat/crystal допустимы для люстр
    conflict = bool(_CONFLICT_STYLE.search(style_blob))
    if chandelier and re.search(r"baccarat|crystal|хрустал", style_blob, re.I):
        conflict = False
    checks["style"] = {"values": styles, "ok": not conflict, "chandelier": chandelier}
    if conflict:
        remarks.append(
            "стиль baroque/rococo конфликтует с Gilil — смените на modern / Baccarat chandelier"
        )

    approved = len(remarks) == 0
    checks["approved"] = approved
    return {
        "ok": True,
        "approved": approved,
        "remarks": remarks,
        "checks": checks,
        "soft_fail": False,
    }


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    payload = payload or {}

    if action == "design_review":
        analysis = payload.get("analysis") or {}
        if payload.get("design_brief") and not analysis.get("design_brief"):
            analysis = {**analysis, "design_brief": payload["design_brief"]}
        review = design_review(analysis)
        path = artifact_path(pid, "visualization", "design_review.json")
        path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        msg = "дизайн OK" if review["approved"] else f"замечания: {len(review['remarks'])}"
        return {
            "ok": True,
            "data": review,
            "artifacts": [
                {
                    "kind": "other",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action, "approved": review["approved"]},
                }
            ],
            "message": msg,
        }

    if action == "render":
        cct = payload.get("cct_k", 3000)
        analysis = payload.get("analysis") or {}
        brief = analysis.get("design_brief") or payload.get("design_brief") or {}
        if analysis.get("cct_k") is not None and payload.get("cct_k") is None:
            cct = analysis["cct_k"]
            if isinstance(cct, (list, tuple)):
                cct = cct[0]
        elif (brief.get("led") or {}).get("cct_k") is not None and payload.get("cct_k") is None:
            cct = brief["led"]["cct_k"]
        try:
            cct = int(cct)
        except (TypeError, ValueError):
            cct = 3000
        if cct < 3000 or cct > 4000:
            cct = 3000
        meta_path = artifact_path(pid, "visualization", f"render_{cct}k.json")
        render_path = artifact_path(pid, "visualization", f"render_{cct}k.png")
        materials = (
            analysis.get("materials")
            or brief.get("materials")
            or payload.get("materials")
            or ["brass", "opal_diffuser"]
        )
        meta = {
            "cct_k": cct,
            "materials": materials,
            "engine": "stub",
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        render_path.write_bytes(b"")
        return {
            "ok": True,
            "data": meta,
            "artifacts": [
                {
                    "kind": "render",
                    "path": str(render_path),
                    "mime": "image/png",
                    "meta": meta,
                },
                {
                    "kind": "other",
                    "path": str(meta_path),
                    "mime": "application/json",
                    "meta": {"action": action},
                },
            ],
            "message": f"рендер CCT {cct}K (stub)",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
