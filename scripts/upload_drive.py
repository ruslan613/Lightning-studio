#!/usr/bin/env python3
"""Загрузка собранных exe в Google Drive через сервисный аккаунт (для CI).

env: GOOGLE_SERVICE_ACCOUNT_JSON — JSON ключ сервисного аккаунта (содержимое, не путь);
     DRIVE_FOLDER_ID — id папки Drive, расшаренной на e-mail сервисного аккаунта (Editor).
usage: python scripts/upload_drive.py desktop/dist/*.exe [--subfolder v0.5.0]
Повторная загрузка файла с тем же именем обновляет его (новая ревизия), а не плодит дубли.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

def _force_utf8_stdio() -> None:
    """Avoid UnicodeEncodeError when printing Cyrillic on Windows cp1252 consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


_force_utf8_stdio()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--subfolder", default="")
    a = ap.parse_args()
    sa, folder = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"), os.environ.get("DRIVE_FOLDER_ID")
    if not sa or not folder:
        print("GOOGLE_SERVICE_ACCOUNT_JSON / DRIVE_FOLDER_ID не заданы — загрузка пропущена")
        return 0
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa), scopes=["https://www.googleapis.com/auth/drive"])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    kw = {"supportsAllDrives": True}
    lkw = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}

    def find(name: str, parent: str, mime: str | None = None) -> str | None:
        q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and '{parent}' in parents and trashed = false"
        if mime:
            q += f" and mimeType = '{mime}'"
        r = drive.files().list(q=q, fields="files(id)", **lkw).execute().get("files", [])
        return r[0]["id"] if r else None

    target = folder
    if a.subfolder:
        fm = "application/vnd.google-apps.folder"
        target = find(a.subfolder, folder, fm) or drive.files().create(
            body={"name": a.subfolder, "mimeType": fm, "parents": [folder]}, fields="id", **kw).execute()["id"]
    for f in a.files:
        p = Path(f)
        if not p.is_file():
            print(f"skip (нет файла): {p}")
            continue
        media = MediaFileUpload(str(p), resumable=True, chunksize=16 << 20)
        fid = find(p.name, target)
        if fid:
            r = drive.files().update(fileId=fid, media_body=media, fields="id,webViewLink", **kw).execute()
        else:
            r = drive.files().create(body={"name": p.name, "parents": [target]}, media_body=media,
                                     fields="id,webViewLink", **kw).execute()
        print(f"uploaded {p.name} ({p.stat().st_size / 1e6:.1f} MB) → {r.get('webViewLink')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
