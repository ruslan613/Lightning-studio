#!/usr/bin/env bash
# Week-1 acceptance: orchestrator demo + CLI --stub + SQLite checks
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
DB="${ROOT}/data/projects.db"
PASS=1

echo "=== [1] python -m orchestrator.orchestrator ==="
OUT1="$("$PY" -m orchestrator.orchestrator 2>&1)"
EC1=$?
echo "$OUT1"
if [[ $EC1 -ne 0 ]] || ! echo "$OUT1" | grep -q 'final_status=done'; then
  echo "FAIL: orchestrator demo (exit=$EC1)"
  PASS=0
else
  echo "OK: orchestrator demo"
fi

echo "=== [2] python -m orchestrator.cli run --stub ==="
OUT2="$("$PY" -m orchestrator.cli run "Неделя 1 приёмка" --stub 2>&1)"
EC2=$?
echo "$OUT2"
if [[ $EC2 -ne 0 ]] || ! echo "$OUT2" | grep -q 'final_status=done'; then
  echo "FAIL: cli --stub (exit=$EC2)"
  PASS=0
else
  echo "OK: cli --stub"
fi

echo "=== [3] SQLite checks ==="
if [[ ! -f "$DB" ]]; then
  echo "FAIL: missing db $DB"
  PASS=0
else
  TASKS_DONE="$("$PY" - <<PY
import sqlite3
c=sqlite3.connect("$DB")
print(c.execute("SELECT count(*) FROM tasks WHERE status='done'").fetchone()[0])
PY
)"
  ARTS="$("$PY" - <<PY
import sqlite3
c=sqlite3.connect("$DB")
print(c.execute("SELECT count(*) FROM artifacts").fetchone()[0])
PY
)"
  echo "tasks_done=$TASKS_DONE artifacts=$ARTS"
  if [[ "$TASKS_DONE" -lt 1 ]] || [[ "$ARTS" -lt 1 ]]; then
    echo "FAIL: need tasks done>=1 and artifacts>0"
    PASS=0
  else
    echo "OK: sqlite"
  fi
fi

if [[ $PASS -eq 1 ]]; then
  echo "ACCEPT_WEEK1=PASS"
  exit 0
else
  echo "ACCEPT_WEEK1=FAIL"
  exit 1
fi
