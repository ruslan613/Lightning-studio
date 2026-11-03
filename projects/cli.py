"""CLI: python -m projects <cmd> ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projects import core  # noqa: E402


def _v(x: str | None):
    return None if x in (None, "", "working", "0") else int(str(x).lstrip("v"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m projects", description="Версии проектов AI Lighting Studio")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    p = sp.add_parser("create"); p.add_argument("name")
    p = sp.add_parser("show"); p.add_argument("id")
    p = sp.add_parser("rename"); p.add_argument("id"); p.add_argument("name")
    p = sp.add_parser("save"); p.add_argument("id"); p.add_argument("-m", "--message", default="")
    p = sp.add_parser("log"); p.add_argument("id")
    p = sp.add_parser("diff"); p.add_argument("id"); p.add_argument("a"); p.add_argument("b", nargs="?", default="working")
    p = sp.add_parser("checkout"); p.add_argument("id"); p.add_argument("version"); p.add_argument("-m", "--message")
    p = sp.add_parser("verify"); p.add_argument("id"); p.add_argument("version")
    p = sp.add_parser("export"); p.add_argument("id"); p.add_argument("dest")
    p = sp.add_parser("import"); p.add_argument("file"); p.add_argument("--new-id", action="store_true", default=None)
    a = ap.parse_args(argv)
    try:
        r = {
            "list": lambda: core.list_projects(),
            "create": lambda: core.create(a.name),
            "show": lambda: core.load(a.id),
            "rename": lambda: core.rename_project(a.id, a.name),
            "save": lambda: {k: v for k, v in core.save_version(a.id, a.message).items() if k != "files"},
            "log": lambda: core.list_versions(a.id),
            "diff": lambda: core.diff_versions(a.id, _v(a.a), _v(a.b)),
            "checkout": lambda: {k: v for k, v in core.checkout_version(a.id, _v(a.version), a.message).items() if k != "files"},
            "verify": lambda: core.verify_version(a.id, _v(a.version)),
            "export": lambda: core.export_project(a.id, a.dest),
            "import": lambda: core.import_project(a.file, new_id=a.new_id),
        }[a.cmd]()
    except core.ProjectError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0
