#!/usr/bin/env bash
# The entry point that assumes nothing. §14.1.
#
# Runs on macOS, Linux, and Windows under Git Bash. `make` calls this script
# rather than reimplementing it, so there is one behaviour and two front doors.
#
# Two things here are load-bearing and were measured, not guessed:
#
#  * The venv interpreter is started DIRECTLY, never through `uv run`. `uv run`
#    forks a child python and the CHILD binds the port, so `$!` would record uv
#    and killing it would orphan the listener -- which surfaces one step later
#    as the next `up` failing on a bound port. Started directly, `$!` is the
#    process that owns the port.
#  * Liveness is `kill -0` against a recorded pid, never a command-line-search
#    tool. Git Bash has no procps, and that kind of guard is what cost R-001
#    and R-025 -- it matched its own command line, so `make up` printed the
#    URLs having started nothing for eight tasks.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
RUN="$ROOT/.run"
mkdir -p "$RUN"

pidfile() { printf '%s/%s.pid' "$RUN" "$1"; }
logfile() { printf '%s/%s.log' "$RUN" "$1"; }

label() {
  case $1 in
    temporal) printf 'temporal    ' ;;
    core)     printf 'core banking' ;;
    gateway)  printf 'gateway     ' ;;
    worker)   printf 'worker      ' ;;
  esac
}

venv_python() {
  if   [ -x "$ROOT/.venv/bin/python" ];         then printf '%s' "$ROOT/.venv/bin/python"
  elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then printf '%s' "$ROOT/.venv/Scripts/python.exe"
  else return 1
  fi
}

ensure_venv() {
  venv_python >/dev/null 2>&1 && return 0
  command -v uv >/dev/null 2>&1 || {
    echo "uv is not on PATH. See the README's Setup section." >&2
    exit 1
  }
  echo "  creating the virtualenv (uv sync)..."
  uv sync
  venv_python >/dev/null 2>&1 || {
    echo "uv sync finished but no venv interpreter appeared" >&2
    exit 1
  }
}

# A pid file outlives the process that wrote it (§14.1), so ask the OS.
alive() {
  local f pid
  f=$(pidfile "$1")
  [ -f "$f" ] || return 1
  pid=$(cat "$f" 2>/dev/null || true)
  [ -n "${pid:-}" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

spawn() {                       # spawn <name> <command...>
  local name=$1; shift
  if alive "$name"; then
    echo "  $(label "$name") already running"
    return 0
  fi
  rm -f "$(pidfile "$name")"    # a stale file must never block a start
  nohup "$@" > "$(logfile "$name")" 2>&1 &
  printf '%s\n' "$!" > "$(pidfile "$name")"
  echo "  $(label "$name") started"
}

stop() {                        # stop <name>
  local f pid
  f=$(pidfile "$1")
  if alive "$1"; then
    pid=$(cat "$f")
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.3
    done
    kill -9 "$pid" 2>/dev/null || true
    echo "  $(label "$1") stopped"
  fi
  rm -f "$f"
}

cmd_up() {
  ensure_venv
  local py; py=$(venv_python)

  command -v temporal >/dev/null 2>&1 || {
    echo "The Temporal CLI is not on PATH. See the README's Setup section:" >&2
    echo "  macOS   brew install temporal" >&2
    echo "  Windows winget install Temporal.Temporal" >&2
    exit 1
  }
  spawn temporal temporal server start-dev --ui-port 8233
  sleep 3
  spawn core    "$py" -m uvicorn core_banking.app:app --port 8001
  spawn gateway "$py" -m uvicorn web.gateway:app --port 8000
  spawn worker  "$py" -m python.worker
  echo ""
  echo "  console      -> http://localhost:8000"
  echo "  temporal UI  -> http://localhost:8233"
  echo "  core banking -> http://localhost:8001/ledger"
}

cmd_down()   { for n in worker gateway core temporal; do stop "$n"; done; }
cmd_status() {
  for n in temporal core gateway worker; do
    if alive "$n"; then printf '%s: running (pid %s)\n' "$(label "$n")" "$(cat "$(pidfile "$n")")"
    else                printf '%s: stopped\n' "$(label "$n")"
    fi
  done
}
cmd_reset() {
  rm -rf "$ROOT/.store" "$ROOT/outbox" "$ROOT/core_banking/ledger.db" "$ROOT/.llm_down"
  echo "application state cleared"
}
cmd_restart_worker() {
  stop worker
  ensure_venv
  spawn worker "$(venv_python)" -m python.worker
  echo "  the workflow survives this"
}

cmd_logs() { tail -f "$RUN"/*.log; }

case "${1:-}" in
  demo)           cmd_reset; cmd_up ;;
  up)             cmd_up ;;
  logs)           cmd_logs ;;
  down)           cmd_down ;;
  status)         cmd_status ;;
  reset)          cmd_reset ;;
  restart-worker) cmd_restart_worker ;;
  *)
    cat >&2 <<'USAGE'
usage: bash ./demo.sh <command>

  demo            reset state, start everything, print the URLs  <- start here
  up              start Temporal, core banking, gateway and worker
  down            stop everything this script started
  status          which of the four are running
  logs            tail all four process logs
  reset           clear state so you can Submit again -- no restart needed
  restart-worker  the worker-kill beat: prove the workflow survives it

Run `make help` instead if you have make.
USAGE
    exit 2
    ;;
esac
