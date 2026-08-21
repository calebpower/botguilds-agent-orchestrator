"""GuildBot — the plumbing between the client and a strategy.

It owns what every strategy needs but should not re-implement: persistent
per-world map memory (frames only show current vision), the per-character
decision-trace lifecycle, and access to server config/guild snapshots. The
strategy decides; the bot remembers and records.
"""

from __future__ import annotations

from typing import Any

from . import nav
from .anomaly import AnomalyMonitor
from .reasoning import DecisionTrace
from .storage import Storage
from .strategy import FieldContext, Strategy, get_strategy

CONTAINER_KINDS = frozenset({"chest", "safe"})

# A tile a char bounced off (issued a move but didn't move — a move_failed) is
# treated as blocked for this many ticks, so nav routes around it instead of
# re-issuing the same doomed move forever (the freeze that starved field
# productivity: chars stuck against a wall, 0 loot/xp). A TTL, not permanent — a
# real wall re-bounces and refreshes it; a transient body-tile clears once
# nothing re-blocks it.
STUCK_BLOCK_TTL = 150


class GuildBot:
    def __init__(self, strategy: Strategy | str = "explorer", storage: Storage | None = None):
        self.strategy: Strategy = get_strategy(strategy) if isinstance(strategy, str) else strategy
        self.storage = storage
        self.known: dict[str, dict[tuple[int, int], str]] = {}   # world -> tiles
        # v0.55.0: HYDRATE that map from storage. Without this the bot starts every run
        # map-blind, and v0.54.0's vein-seek measured what that costs: it never fired ONCE
        # in 7,714 frames, because the 85 vein tiles it was built to walk to live in the
        # accumulated map and a fresh run has seen almost none of them. (Run #130 saw 2
        # unique vein positions across 32k frames; the database knows 85.) Best-effort by
        # design — a bot with no storage, a read-only replay, or a schema that predates the
        # table must still start, just map-blind as before.
        if storage is not None:
            try:
                self.known = storage.load_known_tiles()
            except Exception as e:      # pragma: no cover - exercised by the None path
                print(f"[map] could not hydrate known tiles ({e}) — starting map-blind",
                      flush=True)
        # Per-world tiles a move_failed event says we could not enter, with the tick
        # it last bounced (expired after STUCK_BLOCK_TTL). v0.50.0 removed the
        # position-inference that used to feed this: see on_frame.
        self._learned_blocked: dict[str, dict[tuple[int, int], int]] = {}
        # v0.56.0: per-world tiles seen since THIS process started. The hydrated map
        # cannot distinguish "there is ground here" (durable) from "there is a chest
        # here" (was true once); this set is how the second kind stays honest.
        self._seen_this_run: dict[str, set[tuple[int, int]]] = {}
        # v0.60.0 BAND REFRESH. Each world cycles through bands and periodically REFRESHES,
        # and the frame tells us where in that cycle we are: `next_refresh: {band, in_ticks}`.
        # We had ignored the field entirely, which cost iter 71 its measurement -- a refresh
        # collapsed ground loot 18x and a starving band was indistinguishable from a broken
        # bot. Per world: the last (band, in_ticks) we saw.
        self._band: dict[str, tuple[Any, Any]] = {}
        # Tiles worth RE-CHECKING because a refresh has happened since we last looked at
        # them. Kept apart from `known` on purpose: `known` records what we have OBSERVED,
        # and this is a HYPOTHESIS about what a refresh did. Conflating the two would put
        # a fabrication into the map every other behaviour trusts.
        self._recheck: dict[str, set[tuple[int, int]]] = {}
        self.tick = 0
        self.config: dict[str, Any] = {}
        self.guild: dict[str, Any] = {}
        self.client: Any = None   # set by Client
        # Authoritative roster from the public spectate HTTP endpoint. Attached
        # (and its poller started) only by the live runner — None under tests and
        # offline replay, where the strategy falls back to the frame snapshot.
        self.spectate: Any = None
        # Live anomaly self-reporting: watch the action-error stream for a family
        # that spikes (the observable symptom of a desync — see steemer/anomaly.py).
        self.anomaly = AnomalyMonitor()

    # -- client callbacks -----------------------------------------------------

    def on_hello(self, message: dict[str, Any]) -> None:
        self.config = message.get("config", {}) or {}
        self.guild = message.get("guild", {}) or {}
        self.tick = message.get("tick", 0)
        hook = getattr(self.strategy, "on_hello", None)
        if callable(hook):
            hook(self, message)

    def on_frame(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        self.tick = frame.get("tick", self.tick)
        if frame.get("world") == "village":
            return self.strategy.village(self, frame) or []
        return self._field(frame)

    def _band_refreshed(self, world: str, frame: dict[str, Any]) -> bool:
        """Did this world just refresh? Compares the frame's `next_refresh` to the last one
        we saw for this world.

        Two independent tells, because either alone misses cases: the BAND NUMBER changes,
        or `in_ticks` JUMPS UP (a countdown only ever falls, so a rise is a new cycle --
        run #136 showed jumps like 1 -> 2760). The first sighting for a world is never a
        refresh; we have nothing to compare it to and treating it as one would fire on
        every deploy.
        """
        nr = frame.get("next_refresh")
        if not isinstance(nr, dict):
            return False
        band, in_ticks = nr.get("band"), nr.get("in_ticks")
        prev = self._band.get(world)
        self._band[world] = (band, in_ticks)
        if prev is None:
            return False
        prev_band, prev_ticks = prev
        if band != prev_band:
            return True
        return (isinstance(in_ticks, int) and isinstance(prev_ticks, int)
                and in_ticks > prev_ticks)

    def on_action_error(self, message: dict[str, Any]) -> None:
        # v0.50.0: the per-char "why did the last move fail" bookkeeping is gone with
        # the position-inference it existed to qualify. Blocking is now driven by the
        # server's `move_failed` event alone, which cannot be confused with a stamina
        # bounce because a stamina rejection does not emit one.
        # The client already mirrors errors to storage; give the strategy a look.
        hook = getattr(self.strategy, "on_action_error", None)
        if callable(hook):
            hook(self, message)
        # ...and let the anomaly monitor watch the failure stream for a spike.
        a = self.anomaly.record(message.get("tick", self.tick), message.get("reason"))
        if a is not None:
            self._report_anomaly(a)

    # -- anomaly self-reporting ----------------------------------------------

    def _report_anomaly(self, a: dict[str, Any]) -> None:
        """Surface a detected anomaly to stdout (visible live in the screen log)
        and a queryable ``bot_anomaly`` event (which the dashboard shows via the
        snapshot's ``anomalies_recent`` and the analysis loop folds into the
        notebook). We deliberately do NOT append to findings.jsonl from the live
        bot: that file is the loop's curated notebook, and a runtime writer would
        race the loop's rewrites and dirty the working tree. Best-effort:
        observability must never stop the bot playing."""
        sub = a["subtype"]
        print(f"[anomaly] {sub} @tick {self.tick}: {a.get('detail')}", flush=True)
        if self.storage is not None:
            try:
                self.storage.record_anomaly(self.tick, sub, a)
            except Exception as e:
                print(f"[anomaly] record failed ({e}) — continuing", flush=True)

    # -- field frame ----------------------------------------------------------

    def _field(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        world = frame["world"]
        known = self.known.setdefault(world, {})
        # v0.56.0: tiles seen THIS RUN, tracked apart from the hydrated map. Remembered
        # TERRAIN is durable and worth routing over; remembered CONTENTS are not, and
        # conflating the two is what v0.55.0 got wrong -- see `containers` below.
        seen_now = self._seen_this_run.setdefault(world, set())
        visible = frame.get("visible", {}) or {}
        recheck = self._recheck.setdefault(world, set())
        for t in visible.get("tiles", []):
            known[(t[0], t[1])] = t[2]
            seen_now.add((t[0], t[1]))
            # Looking at a tile ANSWERS the hypothesis, whichever way it fell: if it
            # refilled it is a container again by kind, and if it did not there is nothing
            # to go back for. Either way the guess has served its purpose.
            recheck.discard((t[0], t[1]))

        # A refresh REFILLS chests (run #136: `chest` sightings spike to 424 in the
        # loot-rich bucket against 14-80 elsewhere), but our map still says `chest_open`
        # for every one we emptied, and an opened chest is not a container -- so we would
        # never go back and would only notice one by walking past it. On a refresh, every
        # chest we have emptied in this world becomes worth a second look.
        if self._band_refreshed(world, frame):
            recheck |= {p for p in seen_now if known.get(p) == "chest_open"}

        enemies = {tuple(e["pos"]): e for e in visible.get("entities", [])
                   if e.get("faction") == "monster"}
        loot = {tuple(i["pos"]) for i in visible.get("items", [])}
        gold = {tuple(g["pos"]) for g in visible.get("gold", [])}
        # characters (ours and rivals') block a step as hard as a wall, and a
        # bounced move still costs stamina.
        bodies = {tuple(c["pos"]) for c in frame.get("chars", [])}
        bodies |= {tuple(e["pos"]) for e in visible.get("entities", [])
                   if e.get("faction") == "guild"}
        # Only chests seen THIS RUN. v0.55.0 hydrated `known` from storage, and because
        # this line derives targets from `known` it silently promoted chest-beelining from
        # a local errand to a map-wide one: characters set off across the whole remembered
        # map (at score 4.5) toward chests recorded in earlier runs, most already opened.
        # Measured on run #132 -- move failures went 5.2% -> 21.6% of moves, and 50 of the
        # 118 failures attributable to a specific character's own decision were "beeline to
        # a chest". A chest is CONTENT: it gets opened, and it refills on the band's own
        # schedule, so a sighting from a previous run is not evidence it is there now.
        # Terrain keeps the full hydrated map; only this target set is scoped to the run,
        # which is exactly the pre-0.55.0 behaviour.
        containers = {p for p in seen_now if known.get(p) in CONTAINER_KINDS} | recheck

        # Learned-blocked tiles (chars that bounced here recently) also block nav,
        # so a char that hit a wall stops re-issuing the same doomed move. Expire
        # stale entries as we go.
        learned = self._learned_blocked.setdefault(world, {})
        for t in [t for t, tk in learned.items() if self.tick - tk >= STUCK_BLOCK_TTL]:
            del learned[t]

        # v0.50.0 — learn blocked tiles from the SERVER'S OWN `move_failed` event, which
        # names the character and the exact tile it could not enter. Positive evidence.
        #
        # Until now a tile was blacklisted whenever a character's position merely LOOKED
        # unchanged after a move. Frames are stale, so that is not evidence of a bounce —
        # and three stale frames in a row seal every exit. Both of our most recent deaths
        # were this, with the same signature: a hurt character at FULL stamina, walkable
        # floor beside it, and `rest` (0.5) the only offer left because retreat AND the
        # desperation escape could find no unblocked neighbour. Traced on Recruit-15469
        # (vale, tick 1413613): move S at 1413599, E at 1413600, W at 1413601 each looked
        # unlanded, blacklisting (7,35), (8,36) and (6,36) for STUCK_BLOCK_TTL; a
        # crab_green held the fourth side. It then rested for ten ticks and bled out at
        # 56/56 stamina.
        #
        # This is the v0.42.0 stuck-death returning through the door v0.42.0 did not
        # close: that fix excluded `not_enough_stamina` specifically, but the
        # NO-ERROR-AT-ALL path still blacklisted, and there were zero errors in either
        # fatal window. Inference from absence is the bug; only the event is evidence.
        our_eids = {c["eid"]: c["char_uid"] for c in frame.get("chars", [])
                    if c.get("eid") is not None}
        for ev in frame.get("events") or []:
            if ev.get("kind") != "move_failed" or ev.get("eid") not in our_eids:
                continue
            to = ev.get("to")
            if isinstance(to, (list, tuple)) and len(to) == 2:
                learned[(to[0], to[1])] = self.tick

        bodies |= set(learned)

        ctx = FieldContext(world=world, known=known, enemies=enemies, loot=loot,
                           gold=gold, bodies=bodies, containers=containers)

        actions: list[dict[str, Any]] = []
        for char in frame.get("chars", []):
            uid = char["char_uid"]
            cur = (char["pos"][0], char["pos"][1])
            trace = DecisionTrace(tick=self.tick, world=world, char_uid=uid)
            self.strategy.act(self, char, frame, ctx, trace)
            action = trace.decide()
            trace.record(self.storage, self.strategy.version)

            moved_dir = None
            if action:
                actions.append(action)
                # Reserve this character's move destination so a later character
                # in the same frame won't pick the same tile — two of our own
                # moving onto one tile is a bounce (move_failed) for one of them.
                if action.get("action") == "move" and action.get("dir") in nav.DIRS:
                    moved_dir = action["dir"]
                    dx, dy = nav.DIRS[moved_dir]
                    ctx.bodies.add((cur[0] + dx, cur[1] + dy))
        return actions
