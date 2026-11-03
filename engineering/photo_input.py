"""Анализ фото: метаданные + эвристики (stub vision)."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _empty_analysis() -> dict[str, Any]:
    return {
        "geometry": {},
        "dimensions_mm": {},
        "materials": [],
        "style": [],
        "confidence": 0.0,
        "source": "photo",
        "cct_k": None,
    }


def analyze(path: str | Path | None, payload: dict | None = None) -> dict[str, Any]:
    """Структурированный разбор фото. Не падает без Pillow/opencv."""
    payload = payload or {}
    out = _empty_analysis()
    p = Path(path) if path else None

    # эвристики по имени файла
    name = (p.name if p else "") or str(payload.get("filename") or "")
    low = name.lower()
    if "sconce" in low or "бра" in low or "linear" in low:
        out["geometry"] = {"type": "linear_sconce", "mount": "wall"}
        out["style"].append("modern_linear")
        out["dimensions_mm"] = {"length": 600, "height": 40, "depth": 50}
        out["confidence"] = 0.4
    if "brass" in low or "латунь" in low:
        out["materials"].append("brass")
    if "alabaster" in low or "алебастр" in low:
        out["materials"].append("alabaster")
    if "stainless" in low or "нерж" in low:
        out["materials"].append("stainless")

    # payload overrides / vision_notes
    if payload.get("materials"):
        out["materials"] = list(payload["materials"])
    if payload.get("dimensions_mm"):
        out["dimensions_mm"] = dict(payload["dimensions_mm"])
    if payload.get("geometry"):
        out["geometry"] = dict(payload["geometry"])
    if payload.get("style"):
        out["style"] = list(payload["style"]) if isinstance(payload["style"], list) else [payload["style"]]
    if payload.get("cct_k") is not None:
        out["cct_k"] = payload["cct_k"]
    notes = payload.get("vision_notes")
    if notes:
        out["vision_notes"] = notes
        out["confidence"] = max(out["confidence"], 0.55)

    meta: dict[str, Any] = {}
    if p and p.is_file():
        try:
            from PIL import Image  # type: ignore

            with Image.open(p) as img:
                meta["format"] = img.format
                meta["size_px"] = list(img.size)
                meta["mode"] = img.mode
                exif = getattr(img, "getexif", lambda: None)()
                if exif:
                    meta["exif_keys"] = list(exif.keys())[:20]
            out["confidence"] = max(out["confidence"], 0.5)
        except Exception as exc:  # noqa: BLE001
            meta["pillow_error"] = str(exc)
        meta["path"] = str(p)
        meta["bytes"] = p.stat().st_size
    elif path:
        meta["path"] = str(path)
        meta["missing"] = True

    out["image_meta"] = meta
    if not out["materials"]:
        out["materials"] = ["brass"]  # дефолт Gilil
    if not out["geometry"]:
        out["geometry"] = {"type": "linear_sconce", "mount": "wall"}
    if not out["dimensions_mm"]:
        out["dimensions_mm"] = {"length": 600, "height": 40, "depth": 50}
    if out["cct_k"] is None:
        out["cct_k"] = payload.get("cct_k", 3000)
    if not out["style"]:
        out["style"] = ["modern_linear"]
    out["ok"] = True
    out["iteration"] = int(payload.get("iteration") or 0)
    return out
