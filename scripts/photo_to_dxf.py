#!/usr/bin/env python3
"""photo_to_dxf.py — фото светильника/бра → DXF (ezdxf + OpenCV).

1. OpenCV: Canny + findContours → прямоугольники, линии, выступы.
2. Контуры → LWPOLYLINE / LINE в мм через --mm-per-px.
3. Fallback: если OpenCV недоступен или контуров нет — размер кадра × масштаб
   (как раньше) и простой прямоугольник корпуса.

Пример:
  python photo_to_dxf.py fixture.jpg
  python photo_to_dxf.py fixture.jpg -o out/fixture.dxf --mm-per-px 0.5
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import units
from ezdxf.enums import TextEntityAlignment


@dataclass
class ContourPrim:
    """Один контур / примитив в мм (вид спереди, Y вверх как в DXF)."""

    kind: str  # "rect" | "poly" | "line"
    points_mm: list[tuple[float, float]]
    closed: bool = True


@dataclass
class FixtureGeom:
    """Геометрия линейного бра/светильника в мм (каталог Gilil Lighting)."""

    length_mm: float
    height_mm: float
    depth_mm: float = 40.0
    name: str = "fixture"
    source: str = "fallback"  # "opencv" | "fallback"
    primitives: list[ContourPrim] = field(default_factory=list)


def _image_size_px(photo: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("нужен Pillow: pip install pillow") from e
    with Image.open(photo) as im:
        return im.size  # (w, h)


def _fallback_geom(photo: Path, mm_per_px: float) -> FixtureGeom:
    """Пиксели кадра × масштаб — прежнее поведение."""
    w_px, h_px = _image_size_px(photo)
    length = round(w_px * mm_per_px, 1)
    height = round(h_px * mm_per_px, 1)
    length = max(200.0, min(length, 2000.0))
    height = max(40.0, min(height, 400.0))
    return FixtureGeom(
        length_mm=length,
        height_mm=height,
        name=photo.stem,
        source="fallback",
        primitives=[
            ContourPrim(
                kind="rect",
                points_mm=[(0.0, 0.0), (length, 0.0), (length, height), (0.0, height)],
                closed=True,
            )
        ],
    )


def _opencv_detect(photo: Path, mm_per_px: float) -> FixtureGeom | None:
    """Распознать контуры OpenCV. None → вызвать fallback."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    img = cv2.imread(str(photo), cv2.IMREAD_COLOR)
    if img is None:
        return None

    h_px, w_px = img.shape[:2]
    if w_px < 8 or h_px < 8:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # Canny помогает на фото бра (металл/стекло)
    edges = cv2.Canny(gray, 40, 120)
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    # LIST: корпус + внутренние/дочерние контуры (выступы, отверстия)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    min_area = max(60.0, 0.0015 * w_px * h_px)
    frame_area = float(w_px * h_px)
    usable: list[Any] = []
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_area:
            continue
        # отбрасываем почти весь кадр (рамка)
        if area > 0.92 * frame_area:
            continue
        usable.append(cnt)

    if not usable:
        return None

    # крупнейший ≈ корпус; остальные — выступы/детали
    usable.sort(key=cv2.contourArea, reverse=True)
    # убрать почти-дубликаты по IoU bbox
    kept: list[Any] = []
    bboxes: list[tuple[int, int, int, int]] = []
    for cnt in usable:
        x, y, bw, bh = cv2.boundingRect(cnt)
        dup = False
        for bx, by, bbw, bbh in bboxes:
            ix = max(0, min(x + bw, bx + bbw) - max(x, bx))
            iy = max(0, min(y + bh, by + bbh) - max(y, by))
            inter = ix * iy
            union = bw * bh + bbw * bbh - inter
            if union > 0 and inter / union > 0.85:
                dup = True
                break
        if dup:
            continue
        kept.append(cnt)
        bboxes.append((x, y, bw, bh))
        if len(kept) >= 12:
            break

    prims: list[ContourPrim] = []
    xs_all: list[float] = []
    ys_all: list[float] = []

    def px_to_mm(x: float, y: float) -> tuple[float, float]:
        # OpenCV: Y вниз; DXF: Y вверх
        return (round(x * mm_per_px, 2), round((h_px - y) * mm_per_px, 2))

    def remember(pts_mm: list[tuple[float, float]]) -> None:
        for mx, my in pts_mm:
            xs_all.append(mx)
            ys_all.append(my)

    for cnt in kept:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        pts_px = [(float(p[0][0]), float(p[0][1])) for p in approx]
        if len(pts_px) < 2:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = max(bw, bh) / max(1, min(bw, bh))
        pts_mm = [px_to_mm(px, py) for px, py in pts_px]
        remember(pts_mm)

        if len(pts_px) == 2 or (aspect >= 6 and len(pts_px) <= 4):
            if bw >= bh:
                a = px_to_mm(x, y + bh / 2)
                b = px_to_mm(x + bw, y + bh / 2)
            else:
                a = px_to_mm(x + bw / 2, y)
                b = px_to_mm(x + bw / 2, y + bh)
            prims.append(ContourPrim(kind="line", points_mm=[a, b], closed=False))
        elif len(pts_px) == 4:
            prims.append(ContourPrim(kind="rect", points_mm=pts_mm, closed=True))
        else:
            prims.append(ContourPrim(kind="poly", points_mm=pts_mm, closed=True))

    # Hough: тонкие линии / выступы-стержни, которых нет как площади
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=max(30, min(w_px, h_px) // 8),
        minLineLength=max(20, min(w_px, h_px) // 10),
        maxLineGap=8,
    )
    if lines is not None:
        added = 0
        for seg in lines:
            x1, y1, x2, y2 = (float(v) for v in seg.reshape(-1)[:4])
            length_px = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if length_px < 20:
                continue
            # только почти горизонтальные/вертикальные (оси бра)
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if min(dx, dy) > 0.25 * max(dx, dy):
                continue
            a = px_to_mm(x1, y1)
            b = px_to_mm(x2, y2)
            remember([a, b])
            prims.append(ContourPrim(kind="line", points_mm=[a, b], closed=False))
            added += 1
            if added >= 6:
                break

    if not prims or not xs_all:
        return None

    min_x, max_x = min(xs_all), max(xs_all)
    min_y, max_y = min(ys_all), max(ys_all)
    shift_x, shift_y = min_x, min_y
    for pr in prims:
        pr.points_mm = [(x - shift_x, y - shift_y) for x, y in pr.points_mm]

    length = round(max_x - min_x, 1)
    height = round(max_y - min_y, 1)
    if length < 1 or height < 1:
        return None

    length_c = max(10.0, min(length, 2000.0))
    height_c = max(5.0, min(height, 400.0))

    return FixtureGeom(
        length_mm=length_c,
        height_mm=height_c,
        name=photo.stem,
        source="opencv",
        primitives=prims,
    )


def detect_geometry(photo: Path, mm_per_px: float) -> FixtureGeom:
    """OpenCV-контуры → FixtureGeom; иначе pixel×scale fallback."""
    geom = _opencv_detect(photo, mm_per_px)
    if geom is not None:
        return geom
    return _fallback_geom(photo, mm_per_px)


def write_dxf(geom: FixtureGeom, out: Path) -> Path:
    """DXF: контуры (или прямоугольник), осевая, размеры."""
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    msp = doc.modelspace()

    L, H = geom.length_mm, geom.height_mm

    if geom.primitives:
        for pr in geom.primitives:
            layer = "OUTLINE" if pr.kind in ("rect", "poly") else "DETAIL"
            color = 7 if layer == "OUTLINE" else 5
            if pr.kind == "line" and len(pr.points_mm) >= 2:
                msp.add_line(
                    pr.points_mm[0],
                    pr.points_mm[1],
                    dxfattribs={"layer": layer, "color": color},
                )
            elif len(pr.points_mm) >= 2:
                msp.add_lwpolyline(
                    pr.points_mm,
                    close=pr.closed,
                    dxfattribs={"layer": layer, "color": color},
                )
    else:
        msp.add_lwpolyline(
            [(0, 0), (L, 0), (L, H), (0, H)],
            close=True,
            dxfattribs={"layer": "OUTLINE", "color": 7},
        )

    # осевая по длине корпуса
    msp.add_line(
        (0, H / 2),
        (L, H / 2),
        dxfattribs={"layer": "CENTER", "color": 1, "linetype": "CONTINUOUS"},
    )

    dim_y = -30.0
    msp.add_line((0, dim_y), (L, dim_y), dxfattribs={"layer": "DIM", "color": 3})
    msp.add_line((0, dim_y - 5), (0, dim_y + 5), dxfattribs={"layer": "DIM", "color": 3})
    msp.add_line((L, dim_y - 5), (L, dim_y + 5), dxfattribs={"layer": "DIM", "color": 3})
    msp.add_text(
        f"{L:.0f} mm",
        height=12,
        dxfattribs={"layer": "DIM", "color": 3},
    ).set_placement((L / 2, dim_y - 20), align=TextEntityAlignment.MIDDLE_CENTER)

    dim_x = L + 30.0
    msp.add_line((dim_x, 0), (dim_x, H), dxfattribs={"layer": "DIM", "color": 3})
    msp.add_text(
        f"{H:.0f} mm",
        height=12,
        dxfattribs={"layer": "DIM", "color": 3},
    ).set_placement((dim_x + 15, H / 2), align=TextEntityAlignment.MIDDLE_LEFT)

    msp.add_text(
        f"Gilil Lighting | {geom.name} | L={L:.0f} H={H:.0f} D={geom.depth_mm:.0f} mm"
        f" | src={geom.source}",
        height=10,
        dxfattribs={"layer": "NOTE", "color": 4},
    ).set_placement((0, H + 20), align=TextEntityAlignment.LEFT)

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Фото → DXF (OpenCV + ezdxf, Gilil Lighting)")
    p.add_argument("photo", type=Path, help="путь к фото светильника/бра")
    p.add_argument("-o", "--out", type=Path, default=None, help="выходной .dxf")
    p.add_argument(
        "--mm-per-px",
        type=float,
        default=0.5,
        help="масштаб пиксель→мм (калибровка / ручной ввод)",
    )
    p.add_argument(
        "--force-fallback",
        action="store_true",
        help="пропустить OpenCV, только pixel×scale",
    )
    args = p.parse_args(argv)

    photo = args.photo.expanduser().resolve()
    if not photo.is_file():
        print(f"нет файла: {photo}", file=sys.stderr)
        return 1

    out = args.out or photo.with_suffix(".dxf")
    out = out.expanduser().resolve()

    if args.force_fallback:
        geom = _fallback_geom(photo, args.mm_per_px)
    else:
        geom = detect_geometry(photo, args.mm_per_px)

    path = write_dxf(geom, out)
    nprim = len(geom.primitives)
    print(f"OK {path}")
    print(f"  source={geom.source} primitives={nprim}")
    print(f"  L={geom.length_mm} H={geom.height_mm} D={geom.depth_mm} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
