"""Автоматизация: паспорт→RFQ поставщику, обновление сайта/каталога (заглушка)."""
from __future__ import annotations

import json
from typing import Any

from shared.store import artifact_path


def handle(action: str, payload: dict, project: dict) -> dict[str, Any]:
    pid = project["id"]
    if action == "stub_pipeline":
        path = artifact_path(pid, "automation", "week1_stub.json")
        data = {
            "week": 1,
            "mode": "stub",
            "project_id": pid,
            "title": project.get("title"),
            "goal": payload.get("goal", ""),
            "ok": True,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "other",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action, "week": 1},
                }
            ],
            "message": "week1 stub_pipeline ok",
        }

    if action == "make_rfq":
        path = artifact_path(pid, "automation", "rfq.json")
        data = {
            "supplier": payload.get("supplier", "CN-stub"),
            "items": payload.get("items", [{"sku": "LINEAR-BRA-DEMO", "qty": 1}]),
            "attachments": payload.get("attachments", []),
            "note": "запрос на основе паспорта (stub)",
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "rfq",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action},
                }
            ],
            "message": "RFQ сформирован (stub)",
        }

    if action == "update_catalog":
        path = artifact_path(pid, "automation", "catalog_update.json")
        data = {
            "product": project.get("title", "untitled"),
            "status": "pending_publish",
            "langs": ["ru", "en", "zh"],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "data": data,
            "artifacts": [
                {
                    "kind": "catalog_update",
                    "path": str(path),
                    "mime": "application/json",
                    "meta": {"action": action},
                }
            ],
            "message": "обновление каталога (stub)",
        }

    return {
        "ok": False,
        "data": {},
        "artifacts": [],
        "message": f"неизвестное действие: {action}",
    }
