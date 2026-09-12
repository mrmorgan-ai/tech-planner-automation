SHELL := /bin/bash
API_PORT ?= 8788
WEB_PORT ?= 5173
RUN_DIR := .dev

# Two processes: the API runs in the real Workers runtime against a local D1
# file, and Vite serves the web app and proxies /api to it, so the browser stays
# single-origin exactly as it will in production.

.PHONY: start stop

# start: build, migrate the local database, and run the API and the web app.
start:
	@mkdir -p $(RUN_DIR)
	@for port in $(API_PORT) $(WEB_PORT); do \
		if lsof -nP -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1; then \
			echo "port $$port is already in use:"; \
			lsof -nP -iTCP:$$port -sTCP:LISTEN | tail -n +2 | sed 's/^/  /'; \
			echo "run 'make stop' if it is ours, or free it yourself if it is not."; \
			exit 1; \
		fi; \
	done
	@echo "→ building the web assets"
	@npm run build >/dev/null
	@echo "→ applying migrations to the local database"
	@npx wrangler d1 migrations apply planify --local >/dev/null 2>&1
	@echo "→ starting the API on $(API_PORT)"
	@npx wrangler pages dev --port $(API_PORT) > $(RUN_DIR)/api.log 2>&1 & echo $$! > $(RUN_DIR)/api.pid
	@echo "→ starting the web app on $(WEB_PORT)"
	@npx vite --port $(WEB_PORT) --strictPort > $(RUN_DIR)/web.log 2>&1 & echo $$! > $(RUN_DIR)/web.pid
	@ready=1; \
	for i in $$(seq 1 60); do \
		curl -s --max-time 2 http://127.0.0.1:$(API_PORT)/api/health >/dev/null 2>&1 && { ready=0; break; }; \
		sleep 1; \
	done; \
	if [ $$ready -ne 0 ]; then \
		echo "the API never answered on $(API_PORT). Last lines of $(RUN_DIR)/api.log:"; \
		tail -n 15 $(RUN_DIR)/api.log | sed 's/^/  /'; \
		exit 1; \
	fi
	@ready=1; \
	for i in $$(seq 1 60); do \
		curl -s --max-time 2 -o /dev/null http://127.0.0.1:$(WEB_PORT)/ && { ready=0; break; }; \
		sleep 1; \
	done; \
	if [ $$ready -ne 0 ]; then \
		echo "the web app never answered on $(WEB_PORT). Last lines of $(RUN_DIR)/web.log:"; \
		tail -n 15 $(RUN_DIR)/web.log | sed 's/^/  /'; \
		exit 1; \
	fi
	@items=$$(curl -s --max-time 5 http://127.0.0.1:$(API_PORT)/api/health | sed -n 's/.*"items":\([0-9]*\).*/\1/p'); \
	echo; \
	if [ "$$items" = "0" ] || [ -z "$$items" ]; then \
		echo "the database has no items yet. Load a roadmap with:"; \
		echo "  npm run seed:sql && npx wrangler d1 execute planify --local --file build/seed.sql"; \
	else \
		echo "$$items items loaded"; \
	fi
	@echo "app  http://127.0.0.1:$(WEB_PORT)"
	@echo "api  http://127.0.0.1:$(API_PORT)/api/state"
	@echo "logs $(RUN_DIR)/api.log · $(RUN_DIR)/web.log"

# stop: stop only what start launched. Never a broad pkill: a development
# machine usually has other servers running, and some of them are on these
# ports.
stop:
	@stopped=0; \
	for entry in api:$(API_PORT) web:$(WEB_PORT); do \
		name=$${entry%%:*}; port=$${entry##*:}; \
		file=$(RUN_DIR)/$$name.pid; \
		[ -f "$$file" ] || continue; \
		pid=$$(cat $$file); \
		if kill -0 $$pid 2>/dev/null; then \
			if ps -p $$pid -o command= | grep -qE 'wrangler|vite'; then \
				pkill -P $$pid 2>/dev/null || true; \
				kill $$pid 2>/dev/null || true; \
				echo "stopped $$name (pid $$pid)"; \
				stopped=1; \
			else \
				echo "pid $$pid is no longer ours — leaving it alone"; \
			fi; \
		fi; \
		rm -f $$file; \
	done; \
	[ $$stopped -eq 1 ] || echo "nothing of ours was running"
	@# Vite ignores SIGTERM, so a child can outlive the parent we just killed.
	@# The port is the honest check, and only a process from this project's
	@# node_modules is ever escalated to SIGKILL.
	@for port in $(API_PORT) $(WEB_PORT); do \
		for i in 1 2 3 4 5; do \
			lsof -nP -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1 || break; \
			sleep 1; \
		done; \
		lsof -nP -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1 || continue; \
		holder=$$(lsof -nP -iTCP:$$port -sTCP:LISTEN -t | head -1); \
		if ps -p $$holder -o command= | grep -q "$(CURDIR)/node_modules"; then \
			kill -9 $$holder 2>/dev/null || true; \
			echo "port $$port needed SIGKILL (pid $$holder)"; \
		else \
			echo "port $$port is held by a process we did not start:"; \
			ps -p $$holder -o pid=,command= | cut -c1-120 | sed 's/^/  /'; \
		fi; \
	done
