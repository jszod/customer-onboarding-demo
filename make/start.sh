#!/bin/sh
# Starts one of the four stack processes, if it is not already running.
#
# WHY THIS IS A SCRIPT and not four `make` recipes: `pgrep -f` matches whole
# command lines, so a recipe that both greps for a pattern AND contains the
# command it would start matches its own shell -- the guard concludes "already
# running", the `||` branch never fires, and `make up` prints the URLs having
# started nothing. R-001 fixed the half of this that `make status` exposed (the
# pattern itself, hence `[t]emporal`); the start targets kept the other half,
# because there the command text is in the command line too.
#
# In a script the start command lives in a FILE, and a file's contents are not
# a command line: this process shows up as `sh make/start.sh temporal`, which
# no guard pattern matches. See R-025.
#
# Idempotent, per §14: running it twice starts one process.
set -eu

name=${1:?usage: start.sh temporal|core-banking|gateway|worker}
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

running() { pgrep -f "$1" >/dev/null 2>&1; }

case "$name" in
temporal)
    command -v temporal >/dev/null 2>&1 || {
        echo "Temporal CLI not on PATH — install it with: brew install temporal"
        echo "(see README Setup; make demo cannot start a dev server without it)"
        exit 1
    }
    running '[t]emporal server start-dev' && exit 0
    nohup temporal server start-dev --ui-port 8233 \
        > /tmp/onboarding-temporal.log 2>&1 &
    sleep 3
    echo "temporal dev server started (UI :8233)"
    ;;
core-banking)
    running '[c]ore_banking.app:app' && exit 0
    nohup uv run uvicorn core_banking.app:app --port 8001 \
        > /tmp/onboarding-core.log 2>&1 &
    echo "core banking started (:8001)"
    ;;
gateway)
    running '[w]eb.gateway:app' && exit 0
    nohup uv run uvicorn web.gateway:app --port 8000 \
        > /tmp/onboarding-gateway.log 2>&1 &
    echo "gateway started (:8000)"
    ;;
worker)
    running '[p]ython.worker' && exit 0
    nohup uv run python -m python.worker \
        > /tmp/onboarding-worker.log 2>&1 &
    echo "worker started"
    ;;
*)
    echo "unknown process: $name" >&2
    exit 2
    ;;
esac
