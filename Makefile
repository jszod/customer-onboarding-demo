.DEFAULT_GOAL := up
up down status logs demo demo-reset worker kill-worker restart-worker \
gateway core-banking temporal test verify fixtures histories documents clean deps:
	@$(MAKE) --no-print-directory -C python $@
.PHONY: up down status logs demo demo-reset worker kill-worker restart-worker \
        gateway core-banking temporal test verify fixtures histories documents clean deps
