"""Парсинг PDF: размеры и материалы из текста."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DIM_RE = re.compile(
    r"(?P<val>\d+(?:[.,]\d+)?)\s*(?P<unit>mm|см|cm|мм)",
    re.IGNORECASE,
)
_MAT_PATTERNS = [
    (re.compile(r"латунь|brass", re.I), "brass"),
    (re.compile(r"нержав|stainless", re.I), "stainless"),
    (re.compile(r"алюмин|aluminum|aluminium", re.I), "aluminum"),
    (re.compile(r"алебастр|alabaster", re.I), "alabaster"),
    (re.compile(r"стекло|glass", re.I), "glass"),
]


def _extract_text(path: Path) -> str:
    # pypdf
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:
        pass
    # PyMuPDF
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(path))
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts)
    except Exception:
        pass
    return ""


def analyze(path: str | Path | None, payload: dict | None = None) -> dict[str, Any]:
    payload = payload or {}
    out: dict[str, Any] = {
        "geometry": {"type": "linear_sconce", "mount": "wall"},
        "dimensions_mm": {},
        "materials": [],
        "style": ["modern_linear"],
        "confidence": 0.2,
        "source": "pdf",
        "cct_k": payload.get("cct_k", 3000),
        "ok": True,
        "iteration": int(payload.get("iteration") or 0),
        "snippets": [],
    }
    p = Path(path) if path else None
    text = ""
    if p and p.is_file():
        text = _extract_text(p)
        out["pdf_meta"] = {"path": str(p), "bytes": p.stat().st_size, "chars": len(text)}
    elif path:
        out["pdf_meta"] = {"path": str(path), "missing": True}

    if text:
        dims: list[float] = []
        for m in _DIM_RE.finditer(text):
            val = float(m.group("val").replace(",", "."))
            unit = m.group("unit").lower()
            if unit in ("cm", "см"):
                val *= 10.0
            dims.append(val)
            out["snippets"].append(m.group(0))
        if len(dims) >= 1:
            out["dimensions_mm"]["length"] = dims[0]
        if len(dims) >= 2:
            out["dimensions_mm"]["height"] = dims[1]
        if len(dims) >= 3:
            out["dimensions_mm"]["depth"] = dims[2]
        for rx, name in _MAT_PATTERNS:
            if rx.search(text):
                out["materials"].append(name)
        out["confidence"] = 0.6 if (dims or out["materials"]) else 0.3

    # payload overrides
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

    if not out["materials"]:
        out["materials"] = ["brass"]
    if not out["dimensions_mm"]:
        out["dimensions_mm"] = {"length": 600, "height": 40, "depth": 50}
    return out
