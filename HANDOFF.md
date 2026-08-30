# HANDOFF — experiment concluded 2026-08-30 ~00:55

The operator ended the experiment. All services are STOPPED (bot, web sidecar, dash,
watch supervisor) and the loop's wakeups are cancelled. This file is the final state
summary for analysis.

## Final deployed version

explorer/0.123.1 (commit lineage through 478049b; docs/evidence commits after).
Suites at shutdown: 1276 local / 1285 reaper, all green; every shipped assertion
mutation-checked via tools/mutate.py.

## The final arc (08-28 -> 08-30): from 0% field time to wave-riding

The server (Will's, post-migration to a DigitalOcean droplet) never became healthy;
the bot learned to live with it. Levers shipped, in order, each measured live:

- 0.118.x  FWD stamp probe + DIFFERENTIAL debt sensor (public tick - our tick via
           track+spectate feeds; the anchor integral lied under oscillating tick rate)
- 0.119.x  STAGED EXIT (afield budget 2/4/8/all per 300t clean) + exit clock on
           poison alone with instantaneous-then-calm-window lag gates
- 0.120.x  LAG-CORRECTED MONOTONIC ACTION STAMPS (envelope tick + offset, high-water
           mark; killed the per-char order-rule lockout) -> first real field windows
- 0.121.x  SQUALL SHELTER (stand still through 16-72t rejection bursts; bunker only
           for spread>150t / 3 squalls/1000t) -> duty 12% -> 32% step change
- 0.122.0  SCOPE QUARANTINE (lone-char rejection spam stops feeding health counters)
- 0.123.x  DANGER CORRIDOR (death-history tiles as path cost; verdict KEEP:
           0.77 -> 0.00 deaths/10k calm field ticks) + breathing-wave sustained-lag fix

Final regime: duty 60-100% between waves, deaths ~1/run, roster self-healing at 18.

## Server bugs (for Will) — full dossier in server_bugs.md + evidence/

Artifact (kept current): https://claude.ai/code/artifact/562be78d-1b4f-4e63-9c24-33419fdec7eb
- Bug A frame-delivery lag: post-migration it became ~4-hourly DEEP WAVES (offsets
  200-585, hour-scale, deepening through 08-29). Tick-rate shortfall 3.62 vs 4.0.
- Bug B silent deletions: REDUCED ~50x by the migration but accelerating with wave
  severity (~6 post-move, 4 in one run on 08-29) — likely a timeout-cull fed by the
  wave bug (one mechanism).
- Validator divergence: not_in_village/unknown_character rejections while every
  readable view says village — evidence/niv_watch.jsonl holds 1000+ paired samples
  (rejection vs same-second public roster), 100% contradictions.
- not_authenticated on re-hello mid-wave (once); supervisor self-recovered.
- stale_order_ticks=0 remains the config multiplier; restoring tolerance is still
  the highest-leverage server fix.

## Evidence bundle (evidence/)

niv_watch.jsonl (paired divergence samples), capture*.jsonl (wire captures: healthy /
storm / sick-session), niv_watch.py (the pairing watcher), server-bug-report.html
(the artifact source). Findings ledger: findings.jsonl. Ops journal: server_bugs.md.

## Restart procedure (if ever revived)

./svc.sh up watch (supervisor brings up bot), ./svc.sh up web, ./svc.sh up dash;
re-arm the alert monitor (scratchpad/alert_monitor.sh pattern — session-scoped,
must be re-created); gates: pycache purge -> uv run pytest -q -rf -> reaper test.
