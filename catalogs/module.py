"""catalogs: build_catalog_table + site_fragment из design_brief / eng / geometry."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from shared.store import artifact_path

# stub $/W и материалы → RUB себестоимость (эвристика week4)
_MAT_COST_RUB_PER_KG = {
    "brass": 920,
    "aluminum": 380,
    "aluminium": 380,
    "steel": 220,
    "stainless": 650,
    "crystal": 2800,
    "glass": 900,
    "alabaster": 1200,
}
_LED_COST_RUB_PER_W = 45.0
_MARKUP = 2.4  # stub наценка каталога
_CNY_PER_RUB = 0.078  # грубый курс stub


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

    eng = payload.get("engineering_report") or {}
    if not isinstance(eng, dict) or not eng:
        if payload.get("engineering_report_path"):
            eng = _load_json(payload["engineering_report_path"])
    if not isinstance(eng, dict):
        eng = {}

    pid = project.get("id") or ""
    if pid and not brief:
        brief = _load_json(artifact_path(pid, "design", "design_brief.json")) or brief
    if pid and (not geom.get("parts")):
        geom = _load_json(artifact_path(pid, "cad3d", "geometry.json")) or geom
    if pid and not eng:
        eng = _load_json(artifact_path(pid, "engineering", "engineering_report.json")) or eng
    return brief, geom, eng


def _fmt_dims(dims: dict) -> str:
    bits: list[str] = []
    if dims.get("diameter"):
        bits.append(f"Ø{dims['diameter']}")
    if dims.get("length"):
        bits.append(f"L{dims['length']}")
    if dims.get("width"):
        bits.append(f"W{dims['width']}")
    if dims.get("height"):
        bits.append(f"H{dims['height']}")
    if dims.get("depth"):
        bits.append(f"D{dims['depth']}")
    return "×".join(bits) if bits else "—"


def _stub_price_rub(brief: dict, geom: dict, eng: dict) -> float:
    """Себестоимость×наценка → цена каталога (RUB stub)."""
    led = brief.get("led") or geom.get("led_layout") or {}
    watts = float(
        (eng.get("electrical") or {}).get("total_w")
        or led.get("watts_est")
        or (float(led.get("count") or 12) * 5.0)
    )
    mass = float((eng.get("mechanical") or {}).get("mass_kg") or 0.0)
    mats = [str(m).lower() for m in (brief.get("materials") or geom.get("materials") or ["brass"])]
    if mass <= 0:
        # грубая оценка по габаритам
        dims = brief.get("dimensions_mm") or geom.get("dimensions_mm") or {}
        d = float(dims.get("diameter") or dims.get("length") or 600)
        h = float(dims.get("height") or 400)
        mass = max(2.0, (d / 1000) * (h / 1000) * 45.0)

    mat_cost = 0.0
    share = mass / max(len(mats), 1)
    for m in mats:
        mat_cost += share * _MAT_COST_RUB_PER_KG.get(m, 500)
    cost = watts * _LED_COST_RUB_PER_W + mat_cost + 8500  # сборка/логистика stub
    return round(cost * _MARKUP, 2)


def _row(brief: dict, geom: dict, eng: dict, project: dict) -> dict[str, Any]:
    dims = brief.get("dimensions_mm") or geom.get("dimensions_mm") or {}
    led = brief.get("led") or geom.get("led_layout") or {}
    mats = brief.get("materials") or geom.get("materials") or []
    title = brief.get("title") or geom.get("title") or project.get("title") or "fixture"
    fixture = brief.get("fixture_type") or geom.get("fixture_type") or "fixture"
    model = f"GILIL-{str(fixture).upper()[:8]}-{str(project.get('id', 'X')[:8]).upper()}"
    watts = float(
        (eng.get("electrical") or {}).get("total_w")
        or led.get("watts_est")
        or (float(led.get("count") or 12) * 5.0)
    )
    cct = led.get("cct_k") or (eng.get("electrical") or {}).get("cct_k") or 3000
    count = led.get("count") or (eng.get("electrical") or {}).get("lamp_count") or 12
    price_rub = _stub_price_rub(brief, geom, eng)
    return {
        "model": model,
        "title": title,
        "fixture_type": fixture,
        "dims": _fmt_dims(dims),
        "dimensions_mm": dims,
        "materials": ", ".join(map(str, mats)) if mats else "—",
        "materials_list": list(mats),
        "led_count": int(count),
        "led_watts": watts,
        "cct_k": int(cct),
        "led": f"{count}× LED, {watts:g} W, {cct}K",
        "price_stub_rub": price_rub,
        "price_stub_cny": round(price_rub * _CNY_PER_RUB, 2),
        "style": ", ".join(map(str, brief.get("style") or geom.get("style") or [])),
    }


def _write_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "catalog"
    headers = [
        "model",
        "title",
        "fixture_type",
        "dims",
        "materials",
        "led",
        "led_count",
        "led_watts",
        "cct_k",
        "price_stub_rub",
        "price_stub_cny",
        "style",
    ]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    wb.save(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    headers = [
        "model",
        "title",
        "fixture_type",
        "dims",
        "materials",
        "led",
        "led_count",
        "led_watts",
        "cct_k",
        "price_stub_rub",
        "price_stub_cny",
        "style",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h) for h in headers})


def build_catalog_table(payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    brief, geom, eng = _inputs(payload, project)
    row = _row(brief, geom, eng, project)
    rows = [row]

    xlsx = artifact_path(pid, "catalogs", "catalog.xlsx")
    csv_path = artifact_path(pid, "catalogs", "catalog.csv")
    meta_path = artifact_path(pid, "catalogs", "catalog.json")
    _write_xlsx(xlsx, rows)
    _write_csv(csv_path, rows)
    meta = {"rows": rows, "count": len(rows), "currency": ["RUB", "CNY"]}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "rows": rows,
        "paths": {"xlsx": str(xlsx), "csv": str(csv_path), "json": str(meta_path)},
        "model": row["model"],
        "price_stub_rub": row["price_stub_rub"],
    }


def site_fragment(payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    brief, geom, eng = _inputs(payload, project)
    # reuse catalog row if already built
    cat = payload.get("catalog_row")
    if not isinstance(cat, dict):
        mem_cat = _load_json(artifact_path(pid, "catalogs", "catalog.json"))
        if mem_cat.get("rows"):
            cat = mem_cat["rows"][0]
    if not isinstance(cat, dict):
        cat = _row(brief, geom, eng, project)

    title = cat.get("title") or "Gilil fixture"
    model = cat.get("model") or "GILIL-MODEL"
    mats = cat.get("materials") or "—"
    dims = cat.get("dims") or "—"
    led = cat.get("led") or "—"
    price_rub = cat.get("price_stub_rub") or 0
    price_cny = cat.get("price_stub_cny") or 0
    style = cat.get("style") or ""
    preview = artifact_path(pid, "viz", "preview_2d.png")
    img_src = str(preview) if preview.is_file() else ""

    html = f"""<!-- gilil_lighting product listing card (fragment) -->
<article class="gilil-product-card" data-sku="{model}" data-brand="gilil_lighting">
  <header class="gilil-product-card__header">
    <h3 class="gilil-product-card__title">{title}</h3>
    <p class="gilil-product-card__sku">SKU: {model}</p>
  </header>
  {"<figure class=\"gilil-product-card__media\"><img src=\"" + img_src + "\" alt=\"" + title + "\" loading=\"lazy\"/></figure>" if img_src else ""}
  <ul class="gilil-product-card__specs">
    <li><span>Габариты</span> <strong>{dims} mm</strong></li>
    <li><span>Материалы</span> <strong>{mats}</strong></li>
    <li><span>LED</span> <strong>{led}</strong></li>
    <li><span>Стиль</span> <strong>{style or "—"}</strong></li>
  </ul>
  <p class="gilil-product-card__price">
    <span class="price-rub">{price_rub:,.0f} ₽</span>
    <span class="price-cny">≈ {price_cny:,.0f} ¥</span>
    <em class="price-note">(stub catalog)</em>
  </p>
  <footer class="gilil-product-card__cta">
    <a class="btn" href="#rfq" data-sku="{model}">Запросить КП</a>
  </footer>
</article>
"""
    out = artifact_path(pid, "catalogs", "site_fragment.html")
    out.write_text(html, encoding="utf-8")
    return {
        "path": str(out),
        "sku": model,
        "title": title,
        "html_bytes": len(html.encode("utf-8")),
    }


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    payload = payload or {}
    if action == "build_catalog_table":
        data = build_catalog_table(payload, project)
        arts = [
            {
                "kind": "catalog",
                "path": data["paths"]["xlsx"],
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "meta": {"action": action, "format": "xlsx"},
            },
            {
                "kind": "catalog",
                "path": data["paths"]["csv"],
                "mime": "text/csv",
                "meta": {"action": action, "format": "csv"},
            },
            {
                "kind": "catalog",
                "path": data["paths"]["json"],
                "mime": "application/json",
                "meta": {"action": action, "format": "json"},
            },
        ]
        return {
            "ok": True,
            "data": data,
            "artifacts": arts,
            "message": f"каталог: {data.get('model')} ({data.get('price_stub_rub')} RUB stub)",
        }

    if action == "site_fragment":
        # подмешать строку каталога из предыдущего шага
        if not payload.get("catalog_row"):
            prev = (project.get("memory") or {}).get("result:catalogs.build_catalog_table")
            if isinstance(prev, dict) and prev.get("rows"):
                payload = {**payload, "catalog_row": prev["rows"][0]}
        data = site_fragment(payload, project)
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "catalog",
                    "path": data["path"],
                    "mime": "text/html",
                    "meta": {"action": action, "sku": data.get("sku")},
                }
            ],
            "message": f"HTML-фрагмент сайта: {data.get('sku')}",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
