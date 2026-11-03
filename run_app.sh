#!/usr/bin/env bash
# AI Lighting Studio — запуск десктоп-приложения (Electron-окно, dev-режим на Linux).
# Бэкенд: .venv/bin/python -m app (stdio, без HTTP). Данные: data/ (или $ALS_DATA_DIR).
set -euo pipefail
cd "$(dirname "$0")/desktop"
[ -d node_modules ] || npm install
[ -z "${DISPLAY:-}" ] && exec xvfb-run -a -s "-screen 0 1600x1000x24" ./node_modules/electron/dist/electron . --no-sandbox "$@"
exec ./node_modules/electron/dist/electron . --no-sandbox "$@"
