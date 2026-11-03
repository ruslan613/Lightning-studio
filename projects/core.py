"""Версионируемые проекты.

Раскладка (корень = store.PROJECTS_DIR/<id>/):
  project.json            метаданные (id, name, created_at, updated_at, current_version,
                          fixture_type, author, app_version)
  versions/vN/files/...   неизменяемый снимок рабочей копии
  versions/vN/manifest.json  sha256 + size на файл, parent, message, timestamp
  всё остальное           рабочая копия (артефакты модулей пишут сюда, как и раньше)
Индекс — в SQLite (store.DB_PATH): таблицы als_project_meta / als_project_versions.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from shared import store

APP_VERSION = "0.5.0"
SCHEMA_VERSION = 1
RESERVED = {"project.json", "versions"}  # не входят в рабочую копию
ALSPROJ_FORMAT = "alsproj/1"
KEY_FILES = ("design/design_brief.json", "cad3d/geometry.json")


class ProjectError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _author() -> str:
    try:
        return os.environ.get("ALS_AUTHOR") or getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------- SQLite ----------

def _db() -> sqlite3.Connection:
    store.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(store.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS als_schema (name TEXT PRIMARY KEY, version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS als_project_meta (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, current_version INTEGER NOT NULL DEFAULT 0,
            fixture_type TEXT, author TEXT, app_version TEXT
        );
        CREATE TABLE IF NOT EXISTS als_project_versions (
            project_id TEXT NOT NULL, version INTEGER NOT NULL, parent INTEGER,
            message TEXT NOT NULL, created_at TEXT NOT NULL, author TEXT,
            kind TEXT NOT NULL DEFAULT 'manual', restored_from INTEGER,
            file_count INTEGER NOT NULL, total_bytes INTEGER NOT NULL, tree_sha256 TEXT NOT NULL,
            PRIMARY KEY (project_id, version)
        );
        """
    )
    conn.execute("INSERT OR IGNORE INTO als_schema(name, version) VALUES ('projects', ?)", (SCHEMA_VERSION,))
    return conn


def _legacy_row(pid: str) -> Optional[sqlite3.Row]:
    """Строка из таблицы оркестратора `projects` (если есть)."""
    with _db() as c:
        try:
            return c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        except sqlite3.OperationalError:
            return None


# ---------- рабочая копия ----------

def _pdir(pid: str) -> Path:
    return store.PROJECTS_DIR / pid


def _work_files(pid: str) -> list[Path]:
    root = _pdir(pid)
    if not root.is_dir():
        return []
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts[0] in RESERVED or "__pycache__" in rel.parts:
            continue
        out.append(p)
    return sorted(out)


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def working_manifest(pid: str) -> dict[str, dict]:
    root = _pdir(pid)
    return {_rel(root, p): {"sha256": _sha256(p), "size": p.stat().st_size} for p in _work_files(pid)}


def _tree_sha(files: dict[str, dict]) -> str:
    h = hashlib.sha256()
    for k in sorted(files):
        h.update(f"{k}\0{files[k]['sha256']}\n".encode())
    return h.hexdigest()


def _fixture_type(pid: str) -> Optional[str]:
    p = _pdir(pid) / "design" / "design_brief.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("fixture_type")
    except Exception:  # noqa: BLE001
        return None


# ---------- метаданные ----------

def _write_project_json(meta: dict) -> None:
    p = _pdir(meta["id"]) / "project.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _upsert_meta(meta: dict) -> None:
    with _db() as c:
        c.execute(
            "INSERT INTO als_project_meta(id,name,created_at,updated_at,current_version,fixture_type,author,app_version) "
            "VALUES(:id,:name,:created_at,:updated_at,:current_version,:fixture_type,:author,:app_version) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at, "
            "current_version=excluded.current_version, fixture_type=excluded.fixture_type, "
            "author=excluded.author, app_version=excluded.app_version",
            meta,
        )
    _write_project_json(meta)


def load(pid: str) -> dict:
    """Метаданные проекта (project.json); создаёт их для старых проектов (миграция)."""
    return ensure_meta(pid)


def ensure_meta(pid: str, name: Optional[str] = None) -> dict:
    pj = _pdir(pid) / "project.json"
    if pj.is_file():
        meta = json.loads(pj.read_text(encoding="utf-8"))
        with _db() as c:
            if not c.execute("SELECT 1 FROM als_project_meta WHERE id=?", (pid,)).fetchone():
                _upsert_meta(meta)
        return meta
    row = _legacy_row(pid)
    if row is None and not _pdir(pid).is_dir():
        raise ProjectError(f"проект не найден: {pid}")
    now = _now()
    meta = {
        "id": pid,
        "name": name or (row["title"] if row else pid),
        "created_at": row["created_at"] if row else now,
        "updated_at": now,
        "current_version": 0,
        "fixture_type": _fixture_type(pid),
        "author": _author(),
        "app_version": APP_VERSION,
        "format": "als-project/1",
    }
    _upsert_meta(meta)
    return meta


def create(name: str, project_id: Optional[str] = None) -> dict:
    """Пустой проект (без оркестратора). Пайплайн-проекты создаются оркестратором и подхватываются ensure_meta."""
    pid = project_id or str(uuid4())
    if (_pdir(pid) / "project.json").exists():
        raise ProjectError(f"проект уже существует: {pid}")
    _pdir(pid).mkdir(parents=True, exist_ok=True)
    return ensure_meta(pid, name=name)


def rename_project(pid: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ProjectError("пустое имя")
    meta = ensure_meta(pid)
    meta.update(name=name, updated_at=_now())
    _upsert_meta(meta)
    with _db() as c:
        try:
            c.execute("UPDATE projects SET title=?, updated_at=? WHERE id=?", (name, meta["updated_at"], pid))
        except sqlite3.OperationalError:
            pass
    return meta


def list_projects() -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM als_project_meta ORDER BY updated_at DESC")]


# ---------- версии ----------

def _vdir(pid: str, v: int) -> Path:
    return _pdir(pid) / "versions" / f"v{v}"


def _manifest(pid: str, v: int) -> dict:
    p = _vdir(pid, v) / "manifest.json"
    if not p.is_file():
        raise ProjectError(f"версия v{v} не найдена в проекте {pid}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_version(pid: str, message: str = "", *, kind: str = "manual", allow_empty: bool = True,
                 restored_from: Optional[int] = None) -> dict:
    """Снимок рабочей копии → versions/v{N+1}. allow_empty=False: не создавать, если не изменилось."""
    meta = ensure_meta(pid)
    files = working_manifest(pid)
    tree = _tree_sha(files)
    parent = meta.get("current_version") or 0
    if parent and not allow_empty:
        if _manifest(pid, parent).get("tree_sha256") == tree:
            return {**_manifest(pid, parent), "created": False}
    with _db() as c:
        row = c.execute("SELECT MAX(version) FROM als_project_versions WHERE project_id=?", (pid,)).fetchone()
    existing = [int(d.name[1:]) for d in (_pdir(pid) / "versions").glob("v*") if d.name[1:].isdigit()] \
        if (_pdir(pid) / "versions").is_dir() else []
    v = max([row[0] or 0, *existing]) + 1
    final = _vdir(pid, v)
    tmp = final.parent / f".tmp-v{v}-{uuid4().hex[:6]}"
    root = _pdir(pid)
    for rel, info in files.items():
        dst = tmp / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
        if _sha256(dst) != info["sha256"]:  # файл поменялся во время снимка
            shutil.rmtree(tmp, ignore_errors=True)
            raise ProjectError(f"файл изменился во время сохранения: {rel}")
    (tmp / "files").mkdir(parents=True, exist_ok=True)
    ts = _now()
    man = {
        "project_id": pid, "version": v, "parent": parent or None, "message": message or f"v{v}",
        "timestamp": ts, "author": _author(), "app_version": APP_VERSION, "kind": kind,
        "restored_from": restored_from, "tree_sha256": tree,
        "file_count": len(files), "total_bytes": sum(i["size"] for i in files.values()),
        "files": files,
    }
    (tmp / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)  # атомарно: версия появляется целиком
    with _db() as c:
        c.execute(
            "INSERT INTO als_project_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, v, man["parent"], man["message"], ts, man["author"], kind, restored_from,
             man["file_count"], man["total_bytes"], tree),
        )
    meta.update(current_version=v, updated_at=ts, fixture_type=_fixture_type(pid) or meta.get("fixture_type"))
    _upsert_meta(meta)
    return {**man, "created": True}


def auto_version(pid: str, message: str = "Пайплайн завершён") -> Optional[dict]:
    """Хук оркестратора: снимок после успешного прогона (без дублей)."""
    if not _pdir(pid).is_dir():
        return None
    return save_version(pid, message, kind="pipeline", allow_empty=False)


def list_versions(pid: str) -> list[dict]:
    meta = ensure_meta(pid)
    with _db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM als_project_versions WHERE project_id=? ORDER BY version DESC", (pid,))]
    for r in rows:
        r["current"] = r["version"] == meta.get("current_version")
    return rows


def verify_version(pid: str, v: int) -> dict:
    man = _manifest(pid, v)
    base = _vdir(pid, v) / "files"
    bad = [rel for rel, i in man["files"].items()
           if not (base / rel).is_file() or _sha256(base / rel) != i["sha256"]]
    return {"version": v, "ok": not bad, "corrupted": bad}


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    """{'a': {'b': 1}} -> {'a.b': 1}; длинные списки сворачиваются."""
    if isinstance(d, dict):
        out: dict[str, Any] = {}
        for k, val in d.items():
            out.update(_flat(val, f"{prefix}{k}."))
        return out
    key = prefix.rstrip(".")
    if isinstance(d, list) and len(json.dumps(d, ensure_ascii=False)) > 200:
        return {key: f"[{len(d)} items, sha={hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:8]}]"}
    return {key: d}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _side(pid: str, v: Optional[int]) -> tuple[dict, Path]:
    if v is None or v == 0:
        return working_manifest(pid), _pdir(pid)
    return _manifest(pid, v)["files"], _vdir(pid, v) / "files"


def diff_versions(pid: str, a: Optional[int], b: Optional[int]) -> dict:
    """a, b — номера версий; None/0 = рабочая копия."""
    fa, ra = _side(pid, a)
    fb, rb = _side(pid, b)
    added = sorted(set(fb) - set(fa))
    removed = sorted(set(fa) - set(fb))
    changed = sorted(k for k in set(fa) & set(fb) if fa[k]["sha256"] != fb[k]["sha256"])
    params = []
    for kf in KEY_FILES:
        ja = _load_json(ra / kf) if kf in fa else None
        jb = _load_json(rb / kf) if kf in fb else None
        if ja is None and jb is None:
            continue
        xa, xb = _flat(ja or {}), _flat(jb or {})
        for k in sorted(set(xa) | set(xb)):
            if xa.get(k) != xb.get(k):
                params.append({"file": kf, "key": k, "from": xa.get(k), "to": xb.get(k)})
    return {"a": a or "working", "b": b or "working", "added": added, "removed": removed,
            "changed": changed, "unchanged": len(set(fa) & set(fb)) - len(changed), "params": params[:200]}


def checkout_version(pid: str, v: int, message: Optional[str] = None) -> dict:
    """Откат: рабочая копия := снимок vN, затем новая версия (история не удаляется)."""
    man = _manifest(pid, v)
    chk = verify_version(pid, v)
    if not chk["ok"]:
        raise ProjectError(f"снимок v{v} повреждён: {chk['corrupted'][:5]}")
    root = _pdir(pid)
    src = _vdir(pid, v) / "files"
    for p in _work_files(pid):
        p.unlink()
    for d in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
        if d.relative_to(root).parts[0] in RESERVED:
            continue
        try:
            d.rmdir()
        except OSError:
            pass
    for rel in man["files"]:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst)
    return save_version(pid, message or f"Откат к v{v}", kind="rollback", restored_from=v)


# ---------- .alsproj ----------

def export_project(pid: str, dest: str | Path) -> dict:
    meta = ensure_meta(pid)
    dest = Path(dest)
    if dest.is_dir() or dest.suffix.lower() != ".alsproj":
        dest.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in meta["name"])[:60].strip() or pid
        dest = dest / f"{safe}.alsproj"
    dest.parent.mkdir(parents=True, exist_ok=True)
    row = _legacy_row(pid)
    root = _pdir(pid)
    with _db() as c:
        vrows = [dict(r) for r in c.execute("SELECT * FROM als_project_versions WHERE project_id=?", (pid,))]
        try:
            arts = [dict(r) for r in c.execute("SELECT kind, path, mime, meta_json, created_at FROM artifacts WHERE project_id=?", (pid,))]
        except sqlite3.OperationalError:
            arts = []
    for a in arts:
        try:
            a["path"] = Path(a["path"]).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    header = {"format": ALSPROJ_FORMAT, "exported_at": _now(), "app_version": APP_VERSION, "project": meta,
              "orchestrator": dict(row) if row else None, "versions": vrows, "artifacts": arts}
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("alsproj.json", json.dumps(header, ensure_ascii=False, indent=2))
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith(".tmp-"):
                z.write(p, "project/" + _rel(root, p))
                n += 1
    return {"path": str(dest), "size": dest.stat().st_size, "files": n, "versions": len(vrows)}


def import_project(src: str | Path, *, new_id: bool | None = None) -> dict:
    """Импорт .alsproj. Если id уже занят (или new_id=True) — получает новый id."""
    src = Path(src)
    with zipfile.ZipFile(src) as z:
        header = json.loads(z.read("alsproj.json"))
        if header.get("format") != ALSPROJ_FORMAT:
            raise ProjectError(f"неизвестный формат: {header.get('format')}")
        old = header["project"]["id"]
        pid = old
        if new_id or (new_id is None and _pdir(old).exists()):
            pid = str(uuid4())
        root = _pdir(pid)
        tmp = Path(tempfile.mkdtemp(prefix="alsimp-", dir=store.PROJECTS_DIR.parent if store.PROJECTS_DIR.parent.exists() else None))
        try:
            for info in z.infolist():
                name = info.filename
                if not name.startswith("project/") or name.endswith("/"):
                    continue
                rel = Path(name[len("project/"):])
                if rel.is_absolute() or ".." in rel.parts:
                    raise ProjectError(f"небезопасный путь в архиве: {name}")
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as fi, open(dst, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
            # целостность всех снимков
            for vd in (tmp / "versions").glob("v*") if (tmp / "versions").is_dir() else []:
                man = json.loads((vd / "manifest.json").read_text(encoding="utf-8"))
                for rel, i in man["files"].items():
                    if _sha256(vd / "files" / rel) != i["sha256"]:
                        raise ProjectError(f"sha256 не совпал: v{man['version']}/{rel}")
                if pid != old:
                    man["project_id"] = pid
                    (vd / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
            root.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp), str(root))
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    meta = {**header["project"], "id": pid, "updated_at": _now()}
    with _db() as c:
        c.execute("DELETE FROM als_project_versions WHERE project_id=?", (pid,))
        for r in header.get("versions") or []:
            r = {**r, "project_id": pid}
            c.execute("INSERT INTO als_project_versions VALUES (:project_id,:version,:parent,:message,:created_at,"
                      ":author,:kind,:restored_from,:file_count,:total_bytes,:tree_sha256)", r)
        orch = header.get("orchestrator")
        try:
            if orch:
                c.execute("INSERT OR REPLACE INTO projects(id,title,type,status,memory_json,created_at,updated_at) "
                          "VALUES(?,?,?,?,?,?,?)", (pid, meta["name"], orch.get("type") or "order",
                                                     orch.get("status") or "done", orch.get("memory_json") or "{}",
                                                     orch.get("created_at") or meta["created_at"], meta["updated_at"]))
            else:
                c.execute("INSERT OR IGNORE INTO projects(id,title,type,status,memory_json,created_at,updated_at) "
                          "VALUES(?,?,?,?,?,?,?)", (pid, meta["name"], "order", "done", "{}", meta["created_at"], meta["updated_at"]))
            for a in header.get("artifacts") or []:
                p = a["path"] if Path(a["path"]).is_absolute() else str(root / a["path"])
                c.execute("INSERT INTO artifacts(id,project_id,kind,path,mime,meta_json,created_at) VALUES(?,?,?,?,?,?,?)",
                          (str(uuid4()), pid, a["kind"], p, a["mime"], a.get("meta_json") or "{}", a["created_at"]))
        except sqlite3.OperationalError:
            pass  # БД без таблиц оркестратора — достаточно als_project_*
    _upsert_meta(meta)
    return {"id": pid, "imported_from": old, "versions": len(header.get("versions") or []), "name": meta["name"]}
