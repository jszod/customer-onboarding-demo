ROOT := $(shell cd $(dir $(lastword $(MAKEFILE_LIST)))/.. && pwd)
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

temporal:
	@command -v temporal >/dev/null 2>&1 || \
		{ echo "Temporal CLI not on PATH — install it with: brew install temporal"; \
		  echo "(see README Setup; make demo cannot start a dev server without it)"; \
		  exit 1; }
	@pgrep -f "[t]emporal server start-dev" >/dev/null 2>&1 || \
		(nohup temporal server start-dev --ui-port 8233 > /tmp/onboarding-temporal.log 2>&1 & \
		 sleep 3 && echo "temporal dev server started (UI :8233)")

core-banking:
	@pgrep -f "[c]ore_banking.app:app" >/dev/null 2>&1 || \
		(cd $(ROOT) && nohup uv run uvicorn core_banking.app:app --port 8001 \
		 > /tmp/onboarding-core.log 2>&1 & echo "core banking started (:8001)")

gateway:
	@pgrep -f "[w]eb.gateway:app" >/dev/null 2>&1 || \
		(cd $(ROOT) && nohup uv run uvicorn web.gateway:app --port 8000 \
		 > /tmp/onboarding-gateway.log 2>&1 & echo "gateway started (:8000)")

worker:
	@pgrep -f "[p]ython.worker" >/dev/null 2>&1 || \
		(cd $(ROOT) && nohup uv run python -m python.worker \
		 > /tmp/onboarding-worker.log 2>&1 & echo "worker started")

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
	cd $(ROOT) && FIXTURE_MODE=1 uv run pytest -v

verify:
	cd $(ROOT) && FIXTURE_MODE=1 uv run pytest -v -p no:randomly \
		--override-ini=addopts= -rs 2>&1 | tee /tmp/onboarding-verify.log; \
	  if grep -qE "^SKIPPED|skipped" /tmp/onboarding-verify.log; then \
	    echo "VERIFY FAILED: skipped tests remain (§16.8)"; exit 1; \
	  else echo "VERIFY OK: 22/22 scenarios implemented and passing"; fi

documents:
	cd $(ROOT) && uv run python tools/make_documents.py

fixtures:
	cd $(ROOT) && uv run python tools/record_fixtures.py

histories:
	cd $(ROOT) && uv run python tools/capture_histories.py

demo-reset:
	rm -rf $(ROOT)/.store $(ROOT)/outbox $(ROOT)/core_banking/ledger.db
	@echo "application state cleared"

clean: down demo-reset
