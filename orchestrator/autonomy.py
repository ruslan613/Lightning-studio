"""Уровни автономности оркестратора.

UI: Помощник=step_by_step, Автономный=confirm_key_points, Эксперт=full_auto.
"""
from __future__ import annotations

import os
from typing import Optional

from shared.models import KEY_GATES, AutonomyMode

DEFAULT: AutonomyMode = "full_auto"


def resolve_mode(explicit: Optional[str] = None) -> AutonomyMode:
    raw = (explicit or os.environ.get("GILIL_AUTONOMY") or DEFAULT).strip()
    if raw not in ("full_auto", "confirm_key_points", "step_by_step"):
        raise ValueError(f"unknown autonomy mode: {raw}")
    return raw  # type: ignore[return-value]


def should_pause(mode: AutonomyMode, action: str, *, after_ok: bool) -> bool:
    """Пауза после успешной задачи, перед следующей."""
    if not after_ok:
        return False
    if mode == "full_auto":
        return False
    if mode == "step_by_step":
        return True
    # confirm_key_points
    return action in KEY_GATES
