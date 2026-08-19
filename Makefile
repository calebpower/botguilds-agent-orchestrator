# steemer — convenience wrapper around the commands documented in README.md.
# Every target is a thin shim over the underlying tool (uv, the *.sh scripts,
# reaper); nothing here hides behaviour the README doesn't describe.
#
# Portable to both BSD make (the default on this FreeBSD host) and GNU make, so
# it avoids GNU-only features (.DEFAULT_GOAL, MAKEFILE_LIST): `help` is simply
# the first target, which both flavours treat as the default, and the self-doc
# grep reads the literally-named `Makefile`.
#
# Quick start:
#   make sync            # set up the uv environment
#   make config          # create config.toml from the template (MariaDB opt-in)
#   make run             # play live
#   make test            # unit + frame-replay battery
#   make help            # list every target
#
# Overridable variables (make VAR=value target):
#   NOTE      redeploy annotation           (default: "manual redeploy")
#   GUIDANCE  one-off guidance for `apply`   (default: none)
#   WORLD     world filter for `replay`      (default: vale)
#   HOST PORT dashboard bind                 (default: 0.0.0.0 8800)
#   ARGS      extra args passed to run/run-live/redeploy

NOTE     ?= manual redeploy
GUIDANCE ?=
WORLD    ?= vale
HOST     ?= 0.0.0.0
PORT     ?= 8800
ARGS     ?=

# ---- meta (first target = default on both make flavours) ------------------

.PHONY: help
help: ## List every target with its description
	@echo "steemer targets (see README.md for detail):"
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' Makefile \
		| sort \
		| awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---- setup ----------------------------------------------------------------

.PHONY: sync
sync: ## Set up / sync the uv-managed environment
	uv sync

.PHONY: config
config: ## Create config.toml from config.example.toml (never overwrites)
	@if [ -f config.toml ]; then \
		echo "config.toml already exists — leaving it untouched."; \
	else \
		cp config.example.toml config.toml; \
		echo "Created config.toml from template — set the MariaDB password (or switch type to sqlite)."; \
	fi

# ---- running (without Claude) ---------------------------------------------

.PHONY: run
run: ## Play live once (reads config.toml for the backend, guild_token.json for creds)
	uv run python -m steemer.runner $(ARGS)

.PHONY: run-live
run-live: ## Play always-on with crash auto-restart (POSIX supervisor)
	./run-live.sh $(ARGS)

.PHONY: redeploy
redeploy: ## Hot-redeploy the live bot, detached (after commit + reaper test); NOTE="..."
	./redeploy.sh --note "$(NOTE)" $(ARGS)

.PHONY: replay
replay: ## Replay recorded history through the current decision engine; WORLD=vale
	uv run python -m steemer.replay --world $(WORLD) -v

.PHONY: dashboard
dashboard: ## Serve the read-only web dashboard; HOST=/PORT= to change bind
	uv run python ui/server.py --host $(HOST) --port $(PORT)

.PHONY: sidecar
sidecar: ## Web sidecar (foreground): rainbow guild color + intel polling -> DB
	uv run python tools/web_sidecar.py $(ARGS)

# ---- service control (detached daemons via svc.sh) ------------------------
# Each service — bot (game runner), web (sidecar), dash (dashboard) — has
# up / down / restart. `restart` = down then up (picks up new on-disk code).
# The bare up / down / restart act on ALL THREE.
#
# NOTE on `make X-up` from a REAPING parent: BSD make (bmake) signals its job's
# process group when it is itself killed. In an ordinary interactive shell
# `make bot-up` exits cleanly and the svc.sh daemon detaches and survives. But when
# make is launched inside a context that hard-kills the command's process tree on
# completion (e.g. an automation/agent harness), that kill races the daemon's
# detach and can take it down — nohup does not help (the signal is not SIGHUP). In
# that situation call `./svc.sh up bot` DIRECTLY instead of `make bot-up`: without
# the extra make layer the daemon reparents to init and stays up (verified).

.PHONY: bot-up bot-down bot-restart
bot-up: ## Start the game bot, detached (from a reaping harness use ./svc.sh up bot)
	./svc.sh up bot
bot-down: ## Stop the game bot
	./svc.sh down bot
bot-restart: ## Restart the game bot (pick up new code)
	./svc.sh restart bot

.PHONY: web-up web-down web-restart
web-up: ## Start the web sidecar, detached
	./svc.sh up web
web-down: ## Stop the web sidecar
	./svc.sh down web
web-restart: ## Restart the web sidecar
	./svc.sh restart web

.PHONY: dash-up dash-down dash-restart
dash-up: ## Start the dashboard, detached; DASH_HOST=/DASH_PORT= to change bind
	./svc.sh up dash
dash-down: ## Stop the dashboard
	./svc.sh down dash
dash-restart: ## Restart the dashboard
	./svc.sh restart dash

.PHONY: up down restart status
up: bot-up web-up dash-up          ## Start all three (bot + web + dash)
down: bot-down web-down dash-down  ## Stop all three
restart: bot-restart web-restart dash-restart  ## Restart all three
status: ## Show up/down for all three
	@./svc.sh status bot; ./svc.sh status web; ./svc.sh status dash

# ---- the improvement loop -------------------------------------------------

.PHONY: test
test: ## Run the unit + frame-replay battery locally
	uv run pytest -q

.PHONY: reaper-test
reaper-test: ## Run the same battery in the pinned reaper container (pre-redeploy gate)
	reaper test

.PHONY: snapshot
snapshot: ## Print the KPI snapshot the analyze phase consumes
	uv run tools/analyze.py --compact

.PHONY: analyze
analyze: ## One iteration — ANALYZE phase (headless; writes orchestrator/advice.md)
	./analyze-iteration.sh

.PHONY: apply
apply: ## One iteration — APPLY phase (supervised); GUIDANCE="..." to override advice
	./apply-iteration.sh $(GUIDANCE)
