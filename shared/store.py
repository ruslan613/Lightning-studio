"""Пути артефактов проекта на диске."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ALS_DATA_DIR — переопределение (десктоп-приложение пишет в профиль пользователя)
DATA_DIR = Path(os.environ["ALS_DATA_DIR"]) if os.environ.get("ALS_DATA_DIR") else ROOT / "data"
DB_PATH = DATA_DIR / "projects.db"
PROJECTS_DIR = DATA_DIR / "projects"


def project_dir(project_id: str) -> Path:
    p = PROJECTS_DIR / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def artifact_path(project_id: str, *parts: str) -> Path:
    base = project_dir(project_id)
    path = base.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
