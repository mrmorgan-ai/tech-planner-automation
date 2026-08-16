# tech-planner — development entry points.
#
# Everything runs through `uv`. There is no pip, no requirements.txt and no
# hand-managed venv: `uv run` creates and syncs the environment on demand, so
# every target below works from a fresh clone with only `uv` installed.
#
# Recipes stay to one command per line on purpose. macOS ships GNU Make 3.81,
# which predates `.ONESHELL`, so multi-line shell constructs are not portable
# here — anything longer than a line lives in scripts/ instead.

UV      ?= uv
RUN     := $(UV) run
PLANNER := $(RUN) tech-planner
CONFIG  ?= config/settings.py

# The requirement used by `make plan`. Override it:
#   make plan REQ="Add rate limiting to the public API"
# Planning knobs, all optional: CADENCE=annual|quarterly|sprint, SPRINT="Sprint 13",
# BUFFER=1.25, CAPACITY=48.
CADENCE  ?=
SPRINT   ?=
BUFFER   ?=
CAPACITY ?=
PLAN_ARGS = $(if $(CADENCE),--cadence $(CADENCE)) $(if $(SPRINT),--sprint "$(SPRINT)") $(if $(BUFFER),--buffer $(BUFFER)) $(if $(CAPACITY),--capacity $(CAPACITY))

REQ ?= Add a health check endpoint at /healthz that reports database connectivity and returns 200 or 503. Keep it to one Epic, one Feature, one User Story.

.DEFAULT_GOAL := help
.PHONY: help install config check rules policy prompt doctor \
        plan plan-yes capacity sessions session clean reset

## ---------------------------------------------------------------------------
## Getting started
## ---------------------------------------------------------------------------

help: ## Show this help
	@echo "tech-planner"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  CONFIG=$(CONFIG)"
	@echo "  Override the requirement:  make plan REQ=\"...\""

install: ## Create the environment and install the project
	$(UV) sync

config: ## Create config/settings.py from the example, if absent
	@test -f $(CONFIG) && echo "$(CONFIG) already exists — leaving it alone" || (cp config/settings.example.py $(CONFIG) && echo "created $(CONFIG) — fill in your backend details")

## ---------------------------------------------------------------------------
## Checking the logic
##
## These spawn no agent and contact nothing. They are the fast loop: they
## exercise the parts that hold the guarantees, without spending a model call
## or touching a work-tracking board. `doctor` is the slow one — it starts the
## real runtime.
## ---------------------------------------------------------------------------

check: ## Fast offline check: modules import, config valid, approval gate intact
	@$(RUN) python scripts/check.py $(CONFIG)
	@$(MAKE) --no-print-directory rules

rules: ## Show what the planning rules catch on a deliberately bad plan
	@$(RUN) python scripts/rules_demo.py

policy: ## Show what each pass may do — the approval gate, resolved
	@$(PLANNER) --config $(CONFIG) policy

prompt: ## Show the assembled system prompt the agent receives
	@$(PLANNER) --config $(CONFIG) prompt

doctor: ## Start the real runtime and report what it can reach (slow)
	@$(PLANNER) --config $(CONFIG) doctor

## ---------------------------------------------------------------------------
## Running it
## ---------------------------------------------------------------------------

plan: ## Plan REQ and stop at the approval prompt
	@$(PLANNER) --config $(CONFIG) plan $(PLAN_ARGS) "$(REQ)"

plan-yes: ## Plan REQ and create the items unprompted — this writes to the backend
	@$(PLANNER) --config $(CONFIG) plan $(PLAN_ARGS) "$(REQ)" --yes

capacity: ## Show or set per-sprint capacity: make capacity SPRINT="Sprint 13" CAPACITY=48
	@$(PLANNER) --config $(CONFIG) capacity $(if $(SPRINT),"$(SPRINT)") $(CAPACITY)

sessions: ## List past planning sessions
	@$(PLANNER) --config $(CONFIG) sessions

session: ## Show one session's stored record: make session ID=<uuid>
	@test -n "$(ID)" || (echo "usage: make session ID=<session-uuid>"; exit 1)
	@cat .tech-planner/sessions/$(ID).json

## ---------------------------------------------------------------------------
## Housekeeping
## ---------------------------------------------------------------------------

clean: ## Remove caches and the agent's scratch workspace
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '*.egg-info' -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .ruff_cache .mypy_cache
	@find workspace -mindepth 1 ! -name .gitkeep -delete 2>/dev/null || true
	@echo "cleaned"

reset: clean ## Also delete every saved planning session
	@rm -rf .tech-planner
	@echo "sessions deleted"
