"""sales: product_card + price_quote (себестоимость + наценка, RUB/CNY)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.store import artifact_path

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
_ASSEMBLY_RUB = 8500.0
_MARKUP = 2.4
_CNY_PER_RUB = 0.078
_TERMS_STUB = (
    "Срок производства 45–60 раб. дней после утверждения чертежей. "
    "Предоплата 50%, остаток до отгрузки. "
    "Упаковка экспортная. Гарантия 24 мес. на LED/драйвер. "
    "Цены stub — не оферта; финальная калькуляция после RFQ CN/RU."
)


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


def _inputs(payload: dict, project: dict) -> tuple[dict, dict, dict, dict]:
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

    catalog = payload.get("catalog_row") or {}
    if not isinstance(catalog, dict):
        catalog = {}

    pid = project.get("id") or ""
    if pid and not brief:
        brief = _load_json(artifact_path(pid, "design", "design_brief.json")) or brief
    if pid and (not geom.get("parts")):
        geom = _load_json(artifact_path(pid, "cad3d", "geometry.json")) or geom
    if pid and not eng:
        eng = _load_json(artifact_path(pid, "engineering", "engineering_report.json")) or eng
    if pid and not catalog:
        cat_meta = _load_json(artifact_path(pid, "catalogs", "catalog.json"))
        if cat_meta.get("rows"):
            catalog = cat_meta["rows"][0]
    return brief, geom, eng, catalog


def _estimate_cost(brief: dict, geom: dict, eng: dict) -> dict[str, Any]:
    led = brief.get("led") or geom.get("led_layout") or {}
    watts = float(
        (eng.get("electrical") or {}).get("total_w")
        or led.get("watts_est")
        or (float(led.get("count") or 12) * 5.0)
    )
    mass = float((eng.get("mechanical") or {}).get("mass_kg") or 0.0)
    mats = [str(m).lower() for m in (brief.get("materials") or geom.get("materials") or ["brass"])]
    if mass <= 0:
        dims = brief.get("dimensions_mm") or geom.get("dimensions_mm") or {}
        d = float(dims.get("diameter") or dims.get("length") or 600)
        h = float(dims.get("height") or 400)
        mass = max(2.0, (d / 1000) * (h / 1000) * 45.0)

    mat_cost = 0.0
    share = mass / max(len(mats), 1)
    breakdown = []
    for m in mats:
        unit = _MAT_COST_RUB_PER_KG.get(m, 500)
        line = round(share * unit, 2)
        mat_cost += line
        breakdown.append({"material": m, "mass_kg": round(share, 3), "rub": line})

    led_cost = round(watts * _LED_COST_RUB_PER_W, 2)
    assembly = _ASSEMBLY_RUB
    cost_rub = round(led_cost + mat_cost + assembly, 2)
    price_rub = round(cost_rub * _MARKUP, 2)
    return {
        "watts": watts,
        "mass_kg": round(mass, 3),
        "materials_breakdown": breakdown,
        "led_cost_rub": led_cost,
        "materials_cost_rub": round(mat_cost, 2),
        "assembly_rub": assembly,
        "cost_rub": cost_rub,
        "markup": _MARKUP,
        "price_rub": price_rub,
        "cost_cny": round(cost_rub * _CNY_PER_RUB, 2),
        "price_cny": round(price_rub * _CNY_PER_RUB, 2),
        "fx_cny_per_rub": _CNY_PER_RUB,
        "method": "heuristic_watts_materials_v1",
    }


def price_quote(payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    brief, geom, eng, catalog = _inputs(payload, project)
    est = _estimate_cost(brief, geom, eng)
    model = catalog.get("model") or f"GILIL-{(brief.get('fixture_type') or 'FIX')[:8].upper()}-{pid[:8].upper()}"
    title = brief.get("title") or geom.get("title") or project.get("title") or model
    quote = {
        "sku": model,
        "title": title,
        "currency": ["RUB", "CNY"],
        "cost": {
            "RUB": est["cost_rub"],
            "CNY": est["cost_cny"],
        },
        "price": {
            "RUB": est["price_rub"],
            "CNY": est["price_cny"],
        },
        "markup": est["markup"],
        "heuristic": est,
        "note": "stub quote — не оферта; уточняется RFQ",
    }
    path = artifact_path(pid, "sales", "price_quote.json")
    path.write_text(json.dumps(quote, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"quote": quote, "path": str(path), "sku": model}


def product_card(payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    brief, geom, eng, catalog = _inputs(payload, project)
    est = _estimate_cost(brief, geom, eng)
    # prefer quote already computed
    quote_data = _load_json(artifact_path(pid, "sales", "price_quote.json"))
    if quote_data.get("price"):
        price_rub = quote_data["price"].get("RUB", est["price_rub"])
        price_cny = quote_data["price"].get("CNY", est["price_cny"])
        sku = quote_data.get("sku")
    else:
        price_rub = est["price_rub"]
        price_cny = est["price_cny"]
        sku = None

    model = sku or catalog.get("model") or f"GILIL-{(brief.get('fixture_type') or 'FIX')[:8].upper()}-{pid[:8].upper()}"
    title = brief.get("title") or geom.get("title") or project.get("title") or model
    dims = brief.get("dimensions_mm") or geom.get("dimensions_mm") or {}
    mats = brief.get("materials") or geom.get("materials") or []
    led = brief.get("led") or geom.get("led_layout") or {}
    styles = brief.get("style") or geom.get("style") or []
    fixture = brief.get("fixture_type") or geom.get("fixture_type") or "fixture"
    cct = led.get("cct_k") or (eng.get("electrical") or {}).get("cct_k") or 3000
    watts = est["watts"]
    count = led.get("count") or (eng.get("electrical") or {}).get("lamp_count") or 12

    dim_txt = catalog.get("dims")
    if not dim_txt:
        bits = []
        if dims.get("diameter"):
            bits.append(f"Ø{dims['diameter']}")
        if dims.get("height"):
            bits.append(f"H{dims['height']}")
        if dims.get("length"):
            bits.append(f"L{dims['length']}")
        dim_txt = "×".join(bits) if bits else "—"

    description = (
        f"{title} — светильник Gilil ({fixture}) в стиле {', '.join(map(str, styles)) or 'contemporary'}. "
        f"Материалы: {', '.join(map(str, mats)) or 'brass'}. "
        f"Светотехника: {count} источников, ~{watts:g} W, CCT {cct}K. "
        f"Габариты: {dim_txt} mm. "
        f"Коллекция для gilil_lighting; каркас параметрический, инженерный отчёт и viz-превью в комплекте проекта."
    )
    spec = {
        "sku": model,
        "fixture_type": fixture,
        "dimensions_mm": dims,
        "dims_label": dim_txt,
        "materials": list(mats),
        "style": list(styles),
        "led": {"count": int(count), "watts": watts, "cct_k": int(cct)},
        "mass_kg": est["mass_kg"],
        "ip": (eng.get("electrical") or {}).get("suggested_ip") or "IP20",
        "thermal_pass": (eng.get("thermal") or {}).get("pass"),
        "mechanical_pass": (eng.get("mechanical") or {}).get("pass"),
    }
    card = {
        "sku": model,
        "title": title,
        "description": description,
        "spec_summary": spec,
        "terms": _TERMS_STUB,
        "price": {"RUB": price_rub, "CNY": price_cny},
        "currency": ["RUB", "CNY"],
        "brand": "gilil_lighting",
    }

    json_path = artifact_path(pid, "sales", "product_card.json")
    md_path = artifact_path(pid, "sales", "product_card.md")
    json_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

    md = f"""# {title}

**SKU:** `{model}` · **Бренд:** gilil_lighting

## Описание

{description}

## Спецификация

| Параметр | Значение |
|----------|----------|
| Тип | {fixture} |
| Габариты | {dim_txt} mm |
| Материалы | {', '.join(map(str, mats)) or '—'} |
| LED | {count} шт, {watts:g} W, {cct}K |
| Масса (est.) | {est['mass_kg']} kg |
| IP | {spec['ip']} |
| Цена (stub) | {price_rub:,.0f} ₽ / {price_cny:,.0f} ¥ |

## Условия

{_TERMS_STUB}
"""
    md_path.write_text(md, encoding="utf-8")
    return {
        "card": card,
        "paths": {"json": str(json_path), "md": str(md_path)},
        "sku": model,
    }


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    payload = payload or {}

    if action == "price_quote":
        data = price_quote(payload, project)
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "sales",
                    "path": data["path"],
                    "mime": "application/json",
                    "meta": {"action": action, "sku": data.get("sku")},
                }
            ],
            "message": f"котировка {data.get('sku')}: {data['quote']['price']['RUB']} RUB / {data['quote']['price']['CNY']} CNY",
        }

    if action == "product_card":
        # подтянуть quote / catalog из memory проекта
        mem = project.get("memory") or {}
        if not payload.get("catalog_row"):
            prev = mem.get("result:catalogs.build_catalog_table")
            if isinstance(prev, dict) and prev.get("rows"):
                payload = {**payload, "catalog_row": prev["rows"][0]}
        data = product_card(payload, project)
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "sales",
                    "path": data["paths"]["json"],
                    "mime": "application/json",
                    "meta": {"action": action, "format": "json"},
                },
                {
                    "kind": "sales",
                    "path": data["paths"]["md"],
                    "mime": "text/markdown",
                    "meta": {"action": action, "format": "md"},
                },
            ],
            "message": f"карточка товара: {data.get('sku')}",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
