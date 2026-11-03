"""Видео-вход: заглушка. TODO — извлечение ключевых кадров."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def analyze(path: str | Path | None, payload: dict | None = None) -> dict[str, Any]:
    # TODO: keyframe extraction (opencv / ffmpeg)
    payload = payload or {}
    geometry = dict(payload.get("geometry") or {})
    dims = dict(payload.get("dimensions_mm") or {})
    materials = list(payload.get("materials") or [])
    style = payload.get("style") or []
    if isinstance(style, str):
        style = [style]
    return {
        "ok": True,
        "frames": [],
        "message": "TODO keyframes",
        "geometry": geometry,
        "dimensions_mm": dims,
        "materials": materials,
        "style": list(style),
        "confidence": 0.1,
        "source": "video",
        "cct_k": payload.get("cct_k"),
        "iteration": int(payload.get("iteration") or 0),
        "video_meta": {"path": str(path) if path else None},
    }
