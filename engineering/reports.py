"""Инженерные расчёты: тепло / электрика / механика → отчёт."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from shared.store import artifact_path

# грубые плотности кг/м³
_DENSITY = {
    "brass": 8500,
    "aluminum": 2700,
    "aluminium": 2700,
    "steel": 7850,
    "stainless": 8000,
    "crystal": 2500,
    "glass": 2500,
    "alabaster": 2300,
}

# ориентировочная теплоотдача поверхности Вт/м²·К (конвекция+излучение, комнатная среда)
_H_CONV = {
    "brass": 12.0,
    "aluminum": 14.0,
    "aluminium": 14.0,
    "steel": 11.0,
    "stainless": 10.0,
    "crystal": 8.0,
    "glass": 8.0,
    "alabaster": 9.0,
}

# мягкие лимиты
_MAX_DT_SOFT_C = 45.0  # ΔT корпуса
_SAFETY_FACTOR_MIN = 4.0


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


def _brief_and_geom(payload: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    brief = payload.get("design_brief")
    if not isinstance(brief, dict):
        analysis = payload.get("analysis") or {}
        brief = analysis.get("design_brief") if isinstance(analysis.get("design_brief"), dict) else {}
        if not brief and isinstance(analysis, dict):
            brief = {
                "materials": analysis.get("materials") or [],
                "dimensions_mm": analysis.get("dimensions_mm") or {},
                "led": analysis.get("led") or {},
                "style": analysis.get("style") or [],
                "fixture_type": (analysis.get("geometry") or {}).get("type") or "fixture",
            }
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
    return brief, geom


def _led_watts(brief: dict, geom: dict) -> float:
    led = dict(brief.get("led") or {})
    if led.get("watts_est"):
        return float(led["watts_est"])
    layout = geom.get("led_layout") or {}
    if layout.get("watts_est"):
        return float(layout["watts_est"])
    count = int(led.get("count") or layout.get("count") or 12)
    return float(max(1, count) * 5)


def _primary_material(brief: dict, geom: dict) -> str:
    mats = list(brief.get("materials") or geom.get("materials") or ["brass"])
    for m in mats:
        key = str(m).lower()
        if key in _DENSITY and key not in ("crystal", "glass", "alabaster"):
            return key
    return str(mats[0]).lower() if mats else "brass"


def _estimate_surface_m2(brief: dict, geom: dict) -> float:
    """Грубая оценка площади теплоотдачи по bbox / кольцу."""
    dims = dict(brief.get("dimensions_mm") or geom.get("dimensions_mm") or {})
    bbox = dict(geom.get("bbox_mm") or {})
    diam = float(dims.get("diameter") or bbox.get("x") or 600)
    height = float(dims.get("height") or bbox.get("z") or 400)
    # кольцо + канопи: боковая + торцы (мм → м)
    r = diam / 2000.0
    h = max(height, 40) / 1000.0
    # цилиндр-аппроксимация
    area = 2 * math.pi * r * h + 2 * math.pi * r * r
    return max(area, 0.05)


def _part_volume_m3(part: dict) -> float:
    d = part.get("dims_mm") or {}
    t = (part.get("type") or "").lower()
    qty = int(part.get("qty") or 1)
    if t in ("disk", "socket"):
        r = float(d.get("diameter") or 30) / 2000.0
        h = float(d.get("height") or 20) / 1000.0
        v = math.pi * r * r * h
    elif t == "cylinder":
        r = float(d.get("diameter") or 16) / 2000.0
        L = float(d.get("length") or d.get("height") or 200) / 1000.0
        v = math.pi * r * r * L
    elif t == "torus_ring":
        R = float(d.get("diameter") or 800) / 2000.0
        a = float(d.get("profile") or 40) / 2000.0
        v = 2 * math.pi * math.pi * R * a * a
    elif t == "prism":
        L = float(d.get("length") or 100) / 1000.0
        W = float(d.get("width") or 20) / 1000.0
        D = float(d.get("depth") or 20) / 1000.0
        v = L * W * D
    else:
        # bbox куб
        L = float(d.get("length") or d.get("diameter") or 50) / 1000.0
        W = float(d.get("width") or d.get("diameter") or 50) / 1000.0
        H = float(d.get("height") or d.get("depth") or 50) / 1000.0
        v = L * W * H
    return v * qty


def thermal_calc(payload: dict) -> dict[str, Any]:
    brief, geom = _brief_and_geom(payload)
    watts = _led_watts(brief, geom)
    # ~70% мощности LED уходит в тепло
    heat_w = watts * 0.70
    mat = _primary_material(brief, geom)
    h = _H_CONV.get(mat, 11.0)
    area = _estimate_surface_m2(brief, geom)
    # Q = h * A * ΔT → ΔT = Q / (h A)
    dt = heat_w / max(h * area, 1e-6)
    # удельная теплоотдача Вт/м² при данном ΔT
    flux = heat_w / area
    passed = dt <= _MAX_DT_SOFT_C
    return {
        "led_watts": round(watts, 2),
        "heat_w": round(heat_w, 2),
        "material": mat,
        "h_w_m2k": h,
        "surface_m2": round(area, 4),
        "heat_flux_w_m2": round(flux, 2),
        "delta_t_c": round(dt, 2),
        "limit_delta_t_c": _MAX_DT_SOFT_C,
        "pass": passed,
        "notes": "эвристика: 70% LED→тепло, конвекция комнатной среды",
    }


def electrical_calc(payload: dict) -> dict[str, Any]:
    brief, geom = _brief_and_geom(payload)
    watts = _led_watts(brief, geom)
    led = dict(brief.get("led") or {})
    count = int(led.get("count") or (geom.get("led_layout") or {}).get("count") or 12)
    styles = [str(s).lower() for s in (brief.get("style") or geom.get("style") or [])]
    fixture = str(brief.get("fixture_type") or geom.get("fixture_type") or "").lower()

    # IP-эвристика: outdoor/bath → IP44, иначе IP20
    outdoorish = any(
        x in " ".join(styles + [fixture])
        for x in ("outdoor", "улиц", "bath", "ванн", "влаж", "ip44", "wet")
    )
    ip = "IP44" if outdoorish else "IP20"

    # напряжение: крупные люстры / много ламп → 230V AC драйвер; малые → 24V DC
    if watts >= 60 or count >= 12 or fixture == "chandelier":
        voltage = 230
        voltage_note = "230V AC вход драйвера; вторичная цепь LED обычно 24–48V DC"
        driver_v = 36.0  # типичная вторичка
    else:
        voltage = 24
        voltage_note = "24V DC константное напряжение / ток"
        driver_v = 24.0

    current_a = watts / max(driver_v, 1.0)
    # ток драйвера с запасом 20%
    driver_current_a = current_a * 1.2

    return {
        "total_w": round(watts, 2),
        "lamp_count": count,
        "driver_secondary_v": driver_v,
        "driver_current_a": round(driver_current_a, 3),
        "suggested_ip": ip,
        "mains_voltage_v": voltage,
        "voltage_note": voltage_note,
        "cct_k": led.get("cct_k") or (geom.get("led_layout") or {}).get("cct_k") or 3000,
        "notes": "ток с запасом 20%; IP — стиль/среда",
    }


def mechanical_calc(payload: dict) -> dict[str, Any]:
    brief, geom = _brief_and_geom(payload)
    parts = list(geom.get("parts") or [])
    mass_kg = 0.0
    breakdown: list[dict[str, Any]] = []
    if parts:
        for p in parts:
            mat = str(p.get("material") or _primary_material(brief, geom)).lower()
            dens = _DENSITY.get(mat, 5000)
            vol = _part_volume_m3(p)
            m = vol * dens
            mass_kg += m
            breakdown.append(
                {
                    "name": p.get("name"),
                    "material": mat,
                    "volume_m3": round(vol, 6),
                    "mass_kg": round(m, 3),
                }
            )
    else:
        # bbox * средняя плотность * коэффициент заполнения
        dims = dict(brief.get("dimensions_mm") or {})
        bbox = dict(geom.get("bbox_mm") or {})
        x = float(dims.get("diameter") or dims.get("length") or bbox.get("x") or 600) / 1000.0
        y = float(dims.get("depth") or dims.get("diameter") or bbox.get("y") or x) / 1000.0
        z = float(dims.get("height") or bbox.get("z") or 400) / 1000.0
        mat = _primary_material(brief, geom)
        fill = 0.08  # тонкостенная конструкция
        mass_kg = x * y * z * _DENSITY.get(mat, 5000) * fill
        breakdown.append({"name": "bbox_estimate", "material": mat, "mass_kg": round(mass_kg, 3)})

    # нагрузка на крепёж (вес), Н
    g = 9.81
    load_n = mass_kg * g
    sf = 5.0  # рекомендованный запас
    design_load_n = load_n * sf

    # подбор крепежа по расчётной нагрузке
    if design_load_n < 500:
        fastener = "M6×2 анкер/шуруп в потолок (бетон/дерево)"
    elif design_load_n < 1500:
        fastener = "M8×3 потолочный анкер + крюк canopy"
    else:
        fastener = "M10×4 химический анкер / закладная пластина"

    return {
        "mass_kg": round(mass_kg, 3),
        "load_n": round(load_n, 2),
        "safety_factor": sf,
        "design_load_n": round(design_load_n, 2),
        "safety_factor_min": _SAFETY_FACTOR_MIN,
        "pass": sf >= _SAFETY_FACTOR_MIN,
        "fastener": fastener,
        "breakdown": breakdown,
        "notes": "масса = Σ(объём×плотность); запас ≥4",
        "tolerances": {
            "mass_pct": 15,
            "dims_mm": 2.0,
        },
    }


def _report_markdown(thermal: dict, electrical: dict, mechanical: dict, meta: dict) -> str:
    lines = [
        "# Инженерный отчёт",
        "",
        f"**Проект:** {meta.get('title') or '—'}",
        f"**Тип:** {meta.get('fixture_type') or '—'}",
        "",
        "## Тепловой расчёт",
        f"- LED мощность: {thermal.get('led_watts')} W",
        f"- Тепловыделение (~70%): {thermal.get('heat_w')} W",
        f"- Материал корпуса: {thermal.get('material')}",
        f"- Площадь теплоотдачи: {thermal.get('surface_m2')} м²",
        f"- Поток: {thermal.get('heat_flux_w_m2')} W/м²",
        f"- Оценка ΔT: {thermal.get('delta_t_c')} °C (лимит {thermal.get('limit_delta_t_c')} °C)",
        f"- Статус: {'PASS' if thermal.get('pass') else 'FAIL'}",
        "",
        "## Электрический расчёт",
        f"- Суммарная мощность: {electrical.get('total_w')} W",
        f"- Ламп/LED: {electrical.get('lamp_count')}",
        f"- Ток драйвера (с запасом): {electrical.get('driver_current_a')} A @ {electrical.get('driver_secondary_v')} V",
        f"- Рекомендуемый IP: {electrical.get('suggested_ip')}",
        f"- Сеть: {electrical.get('mains_voltage_v')} V — {electrical.get('voltage_note')}",
        f"- CCT: {electrical.get('cct_k')} K",
        "",
        "## Механический расчёт",
        f"- Оценка массы: {mechanical.get('mass_kg')} кг",
        f"- Нагрузка: {mechanical.get('load_n')} Н",
        f"- Коэф. запаса: {mechanical.get('safety_factor')} (мин {mechanical.get('safety_factor_min')})",
        f"- Расчётная нагрузка: {mechanical.get('design_load_n')} Н",
        f"- Крепёж: {mechanical.get('fastener')}",
        f"- Статус: {'PASS' if mechanical.get('pass') else 'FAIL'}",
        "",
        "## Допуски",
        f"- Масса ±{((mechanical.get('tolerances') or {}).get('mass_pct'))}%",
        f"- Габариты ±{((mechanical.get('tolerances') or {}).get('dims_mm'))} мм",
        "",
    ]
    return "\n".join(lines)


def engineering_report(pid: str, payload: dict) -> dict[str, Any]:
    brief, geom = _brief_and_geom(payload)
    thermal = thermal_calc(payload)
    electrical = electrical_calc(payload)
    mechanical = mechanical_calc(payload)
    meta = {
        "title": brief.get("title") or geom.get("title"),
        "fixture_type": brief.get("fixture_type") or geom.get("fixture_type"),
        "materials": brief.get("materials") or geom.get("materials") or [],
        "dimensions_mm": brief.get("dimensions_mm") or geom.get("dimensions_mm") or {},
    }
    overall = bool(thermal.get("pass")) and bool(mechanical.get("pass"))
    data = {
        "meta": meta,
        "thermal": thermal,
        "electrical": electrical,
        "mechanical": mechanical,
        "tolerances": {
            "mass_pct": 15,
            "dims_mm": 2.0,
            "power_pct": 10,
            "delta_t_c": 5.0,
        },
        "overall_pass": overall,
    }
    json_path = artifact_path(pid, "engineering", "engineering_report.json")
    md_path = artifact_path(pid, "engineering", "engineering_report.md")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_report_markdown(thermal, electrical, mechanical, meta), encoding="utf-8")
    data["paths"] = {"json": str(json_path), "md": str(md_path)}
    return data
