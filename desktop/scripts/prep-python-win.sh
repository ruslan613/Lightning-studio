#!/usr/bin/env bash
# Готовит vendor/python-win: embeddable CPython 3.13 (Windows x64) + win_amd64-колёса из ../requirements.txt.
# Нужен один раз перед `npm run dist` (выполняется на Linux, без wine).
set -euo pipefail
cd "$(dirname "$0")/.."
PYV=3.13.5
PIP=../.venv/bin/pip
mkdir -p vendor && cd vendor
[ -f py-embed.zip ] || curl -sSLo py-embed.zip "https://www.python.org/ftp/python/$PYV/python-$PYV-embed-amd64.zip"
rm -rf python-win wheels && mkdir python-win wheels
(cd python-win && unzip -q ../py-embed.zip)
$PIP download --only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation cp -d wheels -r ../../requirements.txt
$PIP install --no-deps --no-compile --target python-win/Lib/site-packages --platform win_amd64 --python-version 3.13 --only-binary=:all: wheels/*.whl
printf 'python313.zip\n.\nLib/site-packages\n../als\nimport site\n' > python-win/python313._pth
find python-win/Lib/site-packages -type d \( -name tests -o -name __pycache__ \) -prune -exec rm -rf {} +
rm -rf python-win/Lib/site-packages/bin
du -sh python-win
