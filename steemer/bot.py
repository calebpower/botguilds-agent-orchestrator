"""GuildBot — the plumbing between the client and a strategy.

It owns what every strategy needs but should not re-implement: persistent
per-world map memory (frames only show current vision), the per-character
decision-trace lifecycle, and access to server config/guild snapshots. The
strategy decides; the bot remembers and records.
"""

from __future__ import annotations

import json

from typing import Any

from . import nav
from .anomaly import AnomalyMonitor
from .chatter import Chatter
from .expectation import ExpectationMonitor
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

# v0.62.0: how long the server's `overburdened` refusal keeps a character out of the
# looting branches. Short, because shedding one item ends the condition and the server
# re-asserts it on the very next attempt if it has not.
OVERBURDENED_TTL = 60

# v0.64.0: how long a `forged` event stays fresh enough to credit the recipe that
# character last attempted. A forge takes 10-14 ticks by its own `forge_started` event,
# so this only has to outlive the craft, not the run.
FORGED_TTL = 40


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
        # v0.62.0: characters the SERVER has told us are overburdened, and the tick it last
        # said so. Found by the v0.61.0 expectation detector: `pickup` confirmed 90 times
        # against 811 violations, and every one of the 1,164 `overburdened` events was the
        # same character in the same state -- carry (19, 21), two free -- retrying forever.
        # Our fullness test counts SLOTS (`used >= cap - 1`) while capacity is spent in
        # BULK, so a character with two free could not take a bulk-3 item, was not "full"
        # by our rule (needs 20), and was not shedding either (needs 21). It sat in the gap.
        self._overburdened: dict[str, int] = {}
        # uid -> tick of the most recent `forged` event for that character (v0.64.0).
        self._forged: dict[str, int] = {}
        # Flavour text (v0.74.0). Lives on the bot because the bot is where
        # events arrive already attributed to us.
        self.chatter = Chatter()
        # Last treasury figure the server told us. Only VILLAGE frames carry it, so a
        # character in the field has none — and None must stay None rather than becoming a
        # zero we would then broadcast as fact (v0.75.1).
        self.guild_gold: int | None = None
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
        # v0.61.0: does what we predicted actually happen? Derives a checkable claim from
        # each action we send and resolves it against later frames. See expectation.py --
        # the last four passes each shipped a silent belief-vs-reality mismatch past a
        # green gate, and this is the general form of the two one-off fixes (v0.49's intent
        # latch, v0.50's server-driven learned-block) that each covered a single case.
        self.expect = ExpectationMonitor()

    # -- client callbacks -----------------------------------------------------

    def on_hello(self, message: dict[str, Any]) -> None:
        self.config = message.get("config", {}) or {}
        self.guild = message.get("guild", {}) or {}
        self.tick = message.get("tick", 0)
        # v0.79.1: persist the server config. It carries constants we have repeatedly
        # NEEDED and could not answer offline — `ride_max_tiles` blocked the rail analysis
        # for two passes because nothing ever wrote it down; it lives only in this message
        # and was gone by the time anyone asked. Recorded through `record_learned`, which
        # is idempotent on (topic, fact), so an unchanged config costs one no-op row and a
        # CHANGED config (Will patches the server mid-week) leaves both versions visible
        # with their proved_at timestamps.
        if self.storage is not None and self.config:
            try:
                self.storage.record_learned(
                    "server_config", json.dumps(self.config, sort_keys=True))
            except Exception as e:
                # A failed bookkeeping write must never block the hello — but it must not
                # be silent either, or a broken learned-table write hides until the next
                # time someone needs a config that was never saved.
                print(f"[config] record failed ({e}) — continuing", flush=True)
        hook = getattr(self.strategy, "on_hello", None)
        if callable(hook):
            hook(self, message)

    def on_frame(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        self.tick = frame.get("tick", self.tick)
        # v0.66.1: learn from events on EVERY frame, village included.
        #
        # This lived inside _field(), and village frames never reach _field() -- they route
        # straight to strategy.village(). Forging happens IN THE VILLAGE, so all six
        # `forged` events in runs #143-#144 arrived on village frames and were never seen:
        # `_forged` stayed empty, `recently_forged` was always False, and v0.64.0's
        # proof-outranks-refusal rule NEVER FIRED LIVE. That is why the corrected forge
        # success rate showed no improvement from it -- the fix was not running.
        guild = frame.get("guild") or {}
        if "gold" in guild:
            self.guild_gold = guild["gold"]
        self._learn_from_events(frame)
        if frame.get("world") == "village":
            return self.strategy.village(self, frame) or []
        return self._field(frame)

    def _learn_from_events(self, frame: dict[str, Any]) -> None:
        """Positive and negative evidence the SERVER volunteers, for any frame.

        The server refuses and confirms through TWO channels -- action_errors AND events --
        and these are the event-side ones. Scoped to our own eids: the streams are
        world-wide and rivals forge and stagger under loot constantly.
        """
        our_eids = {c["eid"]: c["char_uid"] for c in frame.get("chars", []) or []
                    if c.get("eid") is not None}
        for ev in frame.get("events") or []:
            uid = our_eids.get(ev.get("eid"))
            if uid is None:
                continue
            kind = ev.get("kind")
            if kind == "overburdened":
                self._overburdened[uid] = self.tick
            elif kind == "forged":
                self._forged[uid] = self.tick
            # v0.74.0: feed the chatter HERE, where every frame lands and ownership has
            # already been resolved. Hooking it into `village()` instead would repeat
            # 0.64.0's mistake exactly — that parser sat in the field path, never saw the
            # `forged` events it was written for, and shipped inert for two versions.
            mine = dict(ev)
            mine["char_uid"] = uid
            mine.setdefault("world", frame.get("world"))
            self.chatter.note_events([mine])

    def recently_overburdened(self, uid: str) -> bool:
        """Has the server refused this character a pickup for weight, recently?

        A TTL rather than a latch: once the character sheds something the condition is
        gone, and a permanent flag would suppress looting for the rest of the run. The
        server re-asserts it immediately if it is still true, exactly as a real wall
        re-bounces a move (v0.42.0's STUCK_BLOCK reasoning).
        """
        at = self._overburdened.get(uid)
        return at is not None and self.tick - at < OVERBURDENED_TTL

    def recently_forged(self, uid: str) -> bool:
        """Did this character just complete a forge? Proof that its last attempted recipe
        is real, which is the only positive evidence the forge ladder ever gets."""
        at = self._forged.get(uid)
        return at is not None and self.tick - at < FORGED_TTL

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
            # v0.62.0: the server refuses through TWO channels -- action_errors AND events --
            # and we had only ever watched one. `overburdened` is an EVENT, which is why
            # every action_error query came back clean while 1,164 pickups died on it.
            # v0.64.0: a `forged` event is PROOF that whatever recipe that character last
            # attempted actually works. The strategy needs it because `wrong_materials` is
            # not deterministic in the variables we key on -- run #140 shows the identical
            # (product, kinds, quantities) both succeeding and failing -- so failures alone
            # progressively condemned recipes we had already seen work.
            if ev.get("kind") != "move_failed" or ev.get("eid") not in our_eids:
                continue
            to = ev.get("to")
            if isinstance(to, (list, tuple)) and len(to) == 2:
                learned[(to[0], to[1])] = self.tick

        bodies |= set(learned)

        b = frame.get("bounds")
        bounds = (b[0], b[1]) if isinstance(b, (list, tuple)) and len(b) == 2 else None
        ctx = FieldContext(world=world, known=known, enemies=enemies, loot=loot,
                           gold=gold, bodies=bodies, containers=containers, bounds=bounds)

        # Resolve outstanding predictions BEFORE deciding: this frame is the evidence for
        # what we did last time, and a prediction must be judged against the world as it
        # was when it could still have come true.
        chars_now = frame.get("chars", []) or []
        self.expect.observe(self.tick, chars_now)
        alarm = self.expect.alarm(self.tick)
        if alarm is not None:
            self._report_anomaly(alarm)

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
                if action.get("action") == "say":
                    # Commit only now: the offer merely asked, and it loses most ticks.
                    self.chatter.commit(self.tick)
                # Reserve this character's move destination so a later character
                # in the same frame won't pick the same tile — two of our own
                # moving onto one tile is a bounce (move_failed) for one of them.
                if action.get("action") == "move" and action.get("dir") in nav.DIRS:
                    moved_dir = action["dir"]
                    dx, dy = nav.DIRS[moved_dir]
                    ctx.bodies.add((cur[0] + dx, cur[1] + dy))
        # Derive a prediction from each action we are about to send, against the character
        # state we are sending it FROM -- the "before" a violation is measured against.
        self.expect.record_actions(self.tick, actions, chars_now)
        return actions
