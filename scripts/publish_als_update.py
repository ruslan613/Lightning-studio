#!/usr/bin/env python3
"""Publish AI Lighting Studio status into Gilil On (als_updates bridge)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8788/api/als/agent-update"
DEFAULT_TOKEN = "gilil-als-local"


def _read_env_port() -> int | None:
    candidates = [
        Path("/workspace/artifacts/gilil-on-desktop/server/.env"),
        Path(__file__).resolve().parents[2] / "gilil-on-desktop" / "server" / ".env",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PORT="):
                    return int(line.split("=", 1)[1].strip().strip("\"'"))
        except Exception:
            pass
    return None


def _default_url() -> str:
    port = _read_env_port() or int(os.environ.get("GILIL_ON_PORT") or 8788)
    return f"http://127.0.0.1:{port}/api/als/agent-update"


def _load_payload(args: argparse.Namespace) -> dict:
    data: dict = {}
    if args.json_file:
        data.update(json.loads(Path(args.json_file).read_text(encoding="utf-8")))
    if args.stdin or (not sys.stdin.isatty() and not any(
        [args.week, args.status, args.title, args.body, args.json_file]
    )):
        raw = sys.stdin.read().strip()
        if raw:
            data.update(json.loads(raw))
    for key, val in {
        "week": args.week,
        "status": args.status,
        "accept": args.accept,
        "title": args.title,
        "body": args.body,
        "how_to_run": args.how_to_run,
        "author": args.author,
    }.items():
        if val is not None:
            data[key] = val
    if args.path:
        data["paths"] = list(args.path)
    data.setdefault("week", "week2")
    data.setdefault("status", "in_progress")
    data.setdefault("accept", "")
    data.setdefault("title", "")
    data.setdefault("body", "")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="POST ALS update to Gilil On")
    ap.add_argument("--url", default=os.environ.get("ALS_BRIDGE_URL") or _default_url())
    ap.add_argument(
        "--token",
        default=os.environ.get("ALS_BRIDGE_TOKEN") or DEFAULT_TOKEN,
    )
    ap.add_argument("--week")
    ap.add_argument("--status", choices=["in_progress", "done", "blocked"])
    ap.add_argument("--accept", choices=["PASS", "FAIL", ""])
    ap.add_argument("--title")
    ap.add_argument("--body")
    ap.add_argument("--how-to-run", dest="how_to_run")
    ap.add_argument("--author", default="agent")
    ap.add_argument("--path", action="append", default=[])
    ap.add_argument("--json-file")
    ap.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    args = ap.parse_args()

    payload = _load_payload(args)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "X-ALS-Token": args.token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            print(raw)
            data = json.loads(raw)
            if not data.get("ok"):
                return 1
            item = data.get("item") or {}
            print(
                f"OK id={item.get('id')} week={item.get('week')} "
                f"status={item.get('status')} accept={item.get('accept')}",
                file=sys.stderr,
            )
            return 0
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {err}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
