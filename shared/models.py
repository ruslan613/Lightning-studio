"""Pydantic-модели проекта, задачи, артефакта."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


ProjectType = Literal["order", "tender"]
ProjectStatus = Literal[
    "draft", "planning", "engineering", "visualization", "automation", "awaiting_confirm", "done", "failed"
]
ArtifactKind = Literal[
    "drawing",
    "spec",
    "passport",
    "render",
    "animation",
    "rfq",
    "catalog_update",
    "design_brief",
    "geometry",
    "eng_report",
    "catalog",
    "sales",
    "other",
]
TaskStatus = Literal["queued", "running", "done", "failed", "cancelled"]
ModuleName = Literal[
    "orchestrator", "engineering", "visualization", "automation", "design", "cad3d", "viz", "catalogs", "sales"
]
InputType = Literal["photo", "pdf", "video", "unknown"]
AutonomyMode = Literal["full_auto", "confirm_key_points", "step_by_step"]
KEY_GATES = ("design_review", "make_rfq", "update_catalog")  # confirm_key_points


class AnalysisDraft(BaseModel):
    """Черновик анализа входа (engineering → visualization)."""

    geometry: dict[str, Any] = Field(default_factory=dict)
    dimensions_mm: dict[str, Any] = Field(default_factory=dict)
    materials: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source: InputType | str = "unknown"
    input_type: Optional[InputType] = None
    cct_k: Optional[int] = None
    iteration: int = 0
    ok: bool = True


class Artifact(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: ArtifactKind
    path: str
    mime: str = "application/octet-stream"
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)


class Task(BaseModel):
    id: str = Field(default_factory=new_id)
    project_id: str
    module: ModuleName
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = "queued"
    parent_id: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
    error: Optional[str] = None


class Result(BaseModel):
    task_id: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    message: str = ""


class Project(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str
    type: ProjectType = "order"
    status: ProjectStatus = "draft"
    memory: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)
