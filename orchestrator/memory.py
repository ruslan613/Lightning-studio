"""SQLite-память проектов: проекты, артефакты, очередь задач."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid4())


class ProjectMemory:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    memory_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    module TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    parent_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );
                """
            )

    def create_project(self, title: str, type_: str = "order") -> dict[str, Any]:
        pid = _new_id()
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, title, type, status, memory_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '{}', ?, ?)",
                (pid, title, type_, "draft", now, now),
            )
        return self.get_project(pid)  # type: ignore[return-value]

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "type": row["type"],
            "status": row["status"],
            "memory": json.loads(row["memory_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "artifacts": self.list_artifacts(project_id),
        }

    def update_project_status(self, project_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (status, _utc_now(), project_id),
            )

    def set_memory_key(self, project_id: str, key: str, value: Any) -> None:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(f"project {project_id}")
        mem = dict(project["memory"])
        mem[key] = value
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET memory_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(mem, ensure_ascii=False), _utc_now(), project_id),
            )

    def get_memory(self, project_id: str, key: Optional[str] = None) -> Any:
        project = self.get_project(project_id)
        if not project:
            return None
        mem = project["memory"]
        if key is None:
            return mem
        return mem.get(key)

    def add_artifact(
        self,
        project_id: str,
        kind: str,
        path: str,
        mime: str = "application/octet-stream",
        meta: Optional[dict] = None,
    ) -> dict[str, Any]:
        aid = _new_id()
        now = _utc_now()
        meta = meta or {}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO artifacts (id, project_id, kind, path, mime, meta_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (aid, project_id, kind, path, mime, json.dumps(meta, ensure_ascii=False), now),
            )
        return {
            "id": aid,
            "kind": kind,
            "path": path,
            "mime": mime,
            "meta": meta,
            "created_at": now,
        }

    def list_artifacts(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "kind": r["kind"],
                "path": r["path"],
                "mime": r["mime"],
                "meta": json.loads(r["meta_json"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def enqueue_task(
        self,
        project_id: str,
        module: str,
        action: str,
        payload: Optional[dict] = None,
        parent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        tid = _new_id()
        now = _utc_now()
        payload = payload or {}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks "
                "(id, project_id, module, action, payload_json, status, parent_id, error, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, NULL, ?, ?)",
                (
                    tid,
                    project_id,
                    module,
                    action,
                    json.dumps(payload, ensure_ascii=False),
                    parent_id,
                    now,
                    now,
                ),
            )
        return self.get_task(tid)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "module": row["module"],
            "action": row["action"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "status": row["status"],
            "parent_id": row["parent_id"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        error: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if payload is not None:
            fields.append("payload_json = ?")
            values.append(json.dumps(payload, ensure_ascii=False))
        values.append(task_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)

    def list_tasks(
        self, project_id: str, status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id = ? AND status = ? ORDER BY created_at",
                    (project_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at",
                    (project_id,),
                ).fetchall()
        return [
            {
                "id": r["id"],
                "project_id": r["project_id"],
                "module": r["module"],
                "action": r["action"],
                "payload": json.loads(r["payload_json"] or "{}"),
                "status": r["status"],
                "parent_id": r["parent_id"],
                "error": r["error"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
