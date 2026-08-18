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
sidecar: ## Web sidecar: rainbow guild color + intel polling (allies/rivals/tiles) -> DB
	uv run python tools/web_sidecar.py $(ARGS)

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
