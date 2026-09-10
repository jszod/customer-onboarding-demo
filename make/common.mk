# Every target is defined HERE, once (§14, §15). The root `Makefile` and
# `python/Makefile` are one-line includes of this file, and a second SDK's
# makefile would be a third. Nothing forwards, so no target list is written
# twice and none can go missing from a copy.
#
# `$(lastword $(MAKEFILE_LIST))` is this file as the includer spelled it --
# `make/common.mk` from the root, `../make/common.mk` from python/ -- so ROOT
# is the repo root from either entry point. Every recipe below uses it rather
# than the working directory, which is what makes that true.
ROOT := $(shell cd $(dir $(lastword $(MAKEFILE_LIST)))/.. && pwd)

# An include has no first target of its own to become the default, and the
# first one here is `deps`. Say it instead of inheriting it.
.DEFAULT_GOAL := up

# Local configuration: `cp .env.example .env`, then edit. Optional -- the
# leading `-` means a missing file is not an error, so a fresh clone still
# reaches `make verify` with no `.env` and no key (§16.7).
#
# `export` with no arguments hands every variable to the recipes' subprocesses,
# which is the point: the worker, gateway and core banking service are each
# started by a recipe here and read their config from the environment. Recipes
# that set a variable inline still win -- `test` and `verify` force
# FIXTURE_MODE=1 and DEMO_STEP_MS=0 that way, so a stale `.env` can neither
# turn the suite live nor make it pay the demo's pacing. Any future knob that
# slows or redirects a run belongs in that inline list too: `export` hands the
# whole `.env` to every recipe, so opting the suite OUT is the only protection
# (a `DEMO_STEP_MS=2500` in `.env` took `make verify` from 32s to 2m35s).
-include $(ROOT)/.env
export
.PHONY: up down status logs demo demo-reset temporal gateway core-banking \
        worker kill-worker restart-worker test verify fixtures histories documents clean deps

deps:
	cd $(ROOT) && uv sync

up: temporal core-banking gateway worker
	@echo ""
	@echo "  console      → http://localhost:8000"
	@echo "  temporal UI  → http://localhost:8233"
	@echo "  core banking → http://localhost:8001/ledger"

demo: demo-reset up
	@echo "  ready — click Submit on the console"

# The four start targets delegate to one script, and that indirection is the
# whole point: a recipe that greps for `[t]emporal server start-dev` while also
# CONTAINING `temporal server start-dev` matches its own shell, so the guard
# always said "already running" and `make up` started nothing. R-001 fixed the
# pattern; the start command needed a file to live in. See R-025 and
# make/start.sh.
temporal:
	@$(ROOT)/make/start.sh temporal

core-banking:
	@$(ROOT)/make/start.sh core-banking

gateway:
	@$(ROOT)/make/start.sh gateway

worker:
	@$(ROOT)/make/start.sh worker

kill-worker:
	-pkill -f "[p]ython.worker"
	@echo "worker killed — the workflow survives this. restart with: make worker"

restart-worker: kill-worker worker

down: kill-worker
	-pkill -f "[w]eb.gateway:app"
	-pkill -f "[c]ore_banking.app:app"
	-pkill -f "[t]emporal server start-dev"

status:
	@printf "temporal     : "; pgrep -f "[t]emporal server start-dev" >/dev/null 2>&1 && echo "running (:7233, UI :8233)" || echo "stopped"
	@printf "core banking : "; pgrep -f "[c]ore_banking.app:app" >/dev/null 2>&1 && echo "running (:8001)" || echo "stopped"
	@printf "gateway      : "; pgrep -f "[w]eb.gateway:app" >/dev/null 2>&1 && echo "running (:8000)" || echo "stopped"
	@printf "worker       : "; pgrep -f "[p]ython.worker" >/dev/null 2>&1 && echo "running" || echo "stopped"

logs:
	tail -f /tmp/onboarding-*.log

test:
	cd $(ROOT) && FIXTURE_MODE=1 DEMO_STEP_MS=0 uv run pytest -v

# The definition of done: the suite is GREEN and nothing is skipped. Both
# halves matter, and the first one is easy to lose -- piping pytest into `tee`
# hands the shell tee's exit status, so a failing suite with no skips read as
# VERIFY OK and exited 0. `pipefail` is not in POSIX sh and this Makefile does
# not pick its shell, so the status travels through a file instead.
verify:
	cd $(ROOT) && { FIXTURE_MODE=1 DEMO_STEP_MS=0 uv run pytest -v -p no:randomly \
	      --override-ini=addopts= -rs 2>&1; \
	    echo $$? > /tmp/onboarding-verify.status; } \
	    | tee /tmp/onboarding-verify.log; \
	  if [ "$$(cat /tmp/onboarding-verify.status)" -ne 0 ]; then \
	    echo "VERIFY FAILED: the suite is not green"; exit 1; \
	  fi; \
	  if grep -qE "^SKIPPED \[|[0-9]+ skipped" /tmp/onboarding-verify.log; then \
	    echo "VERIFY FAILED: skipped tests remain (§16.8)"; exit 1; \
	  fi; \
	  echo "VERIFY OK: 23/23 scenarios implemented and passing"

documents:
	cd $(ROOT) && uv run python tools/make_documents.py

fixtures:
	cd $(ROOT) && uv run python tools/record_fixtures.py

# Keyless by DEFAULT, not by force: §16.7 captures histories through the
# recorded fixtures, so a run is reproducible. `FIXTURE_MODE=0 make histories`
# still captures against the live API deliberately. The worker has to be
# brought up the same way -- histories/README.md records which it was.
histories:
	cd $(ROOT) && FIXTURE_MODE=$${FIXTURE_MODE:-1} uv run python tools/capture_histories.py

# `.llm_down` is the §10.4 outage toggle. It sits beside `.store` rather than
# inside it (the flag path is DOCUMENT_STORE's PARENT, which defaults to the
# repo root), so `rm -rf .store` does not take it -- and an outage toggled on
# during one demo would still be on at the start of the next.
demo-reset:
	rm -rf $(ROOT)/.store $(ROOT)/outbox $(ROOT)/core_banking/ledger.db \
	       $(ROOT)/.llm_down
	@echo "application state cleared"

clean: down demo-reset
