"""Ф0: версионируемые проекты AI Lighting Studio (снимки, манифесты sha256, откат, .alsproj)."""
from .core import (  # noqa: F401
    APP_VERSION, ProjectError, auto_version, checkout_version, create, diff_versions,
    ensure_meta, export_project, import_project, list_projects, list_versions, load,
    rename_project, save_version, verify_version, working_manifest,
)
