"""GuildBot — the plumbing between the client and a strategy.

It owns what every strategy needs but should not re-implement: persistent
per-world map memory (frames only show current vision), the per-character
decision-trace lifecycle, and access to server config/guild snapshots. The
strategy decides; the bot remembers and records.
"""

from __future__ import annotations

import json
import time

from typing import Any

from . import nav
from .anomaly import AnomalyMonitor, KpiMonitor

# --- v0.117.0 SERVER-HEALTH BUNKER (operator-directed): a client-side health state
# machine. Signals: (1) FRAME LAG — each frame's arrival wall-time vs the tick-implied
# time from the hello anchor (the same public-clock-offset measurement, computed without
# the public API); (2) POISON RATE — stale_frame/unknown_character rejections per window.
# Grace both ways so characters never stutter on a lag spike: entry needs the lag
# SUSTAINED (or a genuine rejection storm, which is already sustained evidence); exit
# needs a long clean stretch. While bunkered: no embarks (absorbs the 0.116.1 shelter)
# and fielded characters walk home (the strategy's bunker-retreat offer).
HEALTH_LAG_S = 8.0          # v0.117.6: ~32 ticks behind = a lag signal. The first
                            # tuning (2.5s) was calibrated against deep storms; under
                            # the chronic-mild era (offset 12-25, measured ~26%
                            # rejections = playable) it held the guild benched
                            # INDEFINITELY. 8s still catches a deepening storm well
                            # before the 80s paralysis zone; the poison arm (10
                            # rejections/300t) is unchanged and catches genuine
                            # rejection storms regardless of lag.
HEALTH_ENTER_TICKS = 120    # the lag must persist this long before bunkering (~30 s —
                            # a random spike or GC pause never benches the guild)
HEALTH_POISON_N = 10        # >= this many poison rejections within...
HEALTH_POISON_WINDOW = 300  # ...this window = a storm (already-sustained evidence:
                            # normal play sees 0-2 stray stale_frames per window)
HEALTH_EXIT_TICKS = 2000    # every signal clean this long -> back to work (the same
                            # bar as 0.116.1's shelter release)
PROBE_EVERY = 600           # v0.117.3: staleness-probe cadence (one aged 'say' per ~2.5
                            # min, HEALTHY windows only) — maps the server's freshness
                            # window; accept = the say event renders, reject = a
                            # stale_frame error for the probe char
PROBE_AGES = (5, 8, 13, 21, 34, 55)   # v0.117.4: K<=5 measured ACCEPTED (says
                                      # rendered) — the boundary is higher; climb the
                                      # Fibonacci ladder with 5 kept as the control
FWD_PROBE_MIN_TICKS = 4     # v0.118.0: below this the debt estimate is inside the
                            # estimator's own noise — a forward stamp proves nothing
OFFSET_SAMPLE_TTL = 400     # v0.118.1: ticks a differential debt sample (public tick
                            # minus ours, via the track feed) stays authoritative
                            # before lag falls back to anchor integration
from .chatter import Chatter
from .expectation import ExpectationMonitor
from .reasoning import DecisionTrace
from .storage import Storage
from .strategy import FieldContext, Strategy, get_strategy

RETURN_GRACE = 4   # ticks a returned char ignores stale field frames (v0.89.0)
SHADOW_EVERY = 5   # v0.90.0: per-char death-risk shadow cadence (ticks)

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
        # v0.106.0: per-world replenishment clock, for the honest re-embark condition
        # ("the world actually changed since this char proved it empty"). refreshed_at
        # is stamped when _band_refreshed observes a refresh; refresh_eta is the tick
        # the NEXT refresh is due per the last frame we saw (tick + in_ticks) — the
        # fallback that keeps a world we lost eyes on from benching its returners
        # forever (no frames arrive from a world nobody is in).
        self.refreshed_at: dict[str, int] = {}
        self.refresh_eta: dict[str, int] = {}
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
        # v0.89.0 COMMAND HYGIENE. Run #177 sent 17k commands to GHOSTS: 12,384 moves
        # rejected not_in_village (the char had walked home but still appeared in a stale
        # per-world frame) and 4,626 unknown_character (the char was DEAD). Frames arrive
        # per-world each tick; a character in transition is listed in two of them, and the
        # corpse of a dead one lingers in the world frame that has not refreshed. uids are
        # never reused, so the dead set is forever; the returned set is a short grace.
        self._dead: set = set()
        self._returned_at: dict = {}
        # v0.90.0 ML SHADOW (plan glistening-baking-lagoon, Pass 3). Scores are computed
        # and LOGGED; nothing reads them — zero behaviour change until the Pass-4 shadow
        # acceptance rules. All fail-closed: with no artifact deployed, models.available()
        # short-circuits the whole path. Band history feeds the deployed band_forecast
        # model; per-char death-risk waits on a v2 artifact that beats the constants.
        self._band_obs: dict = {}      # world -> [undead_sum, melee_sum, n] this window
        self._band_hist: dict = {}     # world -> up to 4 past danger classes, newest first
        self._ml_last_scored: dict = {}   # uid -> tick of last shadow score
        self._ml_stint: dict = {}         # uid -> [start_tick, last_seen_tick]
        # Tiles worth RE-CHECKING because a refresh has happened since we last looked at
        # them. Kept apart from `known` on purpose: `known` records what we have OBSERVED,
        # and this is a HYPOTHESIS about what a refresh did. Conflating the two would put
        # a fabrication into the map every other behaviour trusts.
        self._recheck: dict[str, set[tuple[int, int]]] = {}
        self.tick = 0
        self.config: dict[str, Any] = {}
        self.guild: dict[str, Any] = {}
        # v0.97.0 HINTS: the sidecar watches the whole map (spectate/track intel) and the
        # bot's chars only see locally. The hint channel closes that gap — the bot reads
        # the sidecar's latest rival positions periodically and exposes them so a strategy
        # can act on map-wide knowledge (the nuisance finding Will across the vale).
        self.rival_hints: dict[str, list[dict[str, Any]]] = {}   # world -> [{guild_id,pos,name}]
        self._hints_at: int = -10 ** 9
        self.client: Any = None   # set by Client
        # Authoritative roster from the public spectate HTTP endpoint. Attached
        # (and its poller started) only by the live runner — None under tests and
        # offline replay, where the strategy falls back to the frame snapshot.
        self.spectate: Any = None
        # Live anomaly self-reporting: watch the action-error stream for a family
        # that spikes (the observable symptom of a desync — see steemer/anomaly.py).
        self.anomaly = AnomalyMonitor()
        # v0.116.0: capability KPIs (fielded-collapse, xp-stall) through the same
        # channel — the 2026-08-26 outage ran 90 min with healthy-looking OUTCOME
        # numbers while the bot could not act; these watch the acting itself.
        self.kpis = KpiMonitor()
        # v0.117.0 server-health state (see the constants above)
        self._health = "ok"
        self._hello_anchor = None       # (tick, wall) re-anchored at every hello
        self._lag_bad_since = None      # tick the CURRENT continuous lag-run started
        self._health_bad_at = None      # last tick ANY signal was bad
        self._poison_ticks = []
        self._rate_samples = []          # (tick, wall) pairs for the measured s/tick
        # v0.61.0: does what we predicted actually happen? Derives a checkable claim from
        # each action we send and resolves it against later frames. See expectation.py --
        # the last four passes each shipped a silent belief-vs-reality mismatch past a
        # green gate, and this is the general form of the two one-off fixes (v0.49's intent
        # latch, v0.50's server-driven learned-block) that each covered a single case.
        self.expect = ExpectationMonitor()
        # v0.81.0: re-load taste-decoded essences. Without this every restart forgets
        # what a destructive probe paid an herb to learn, and the once-per-kind guard
        # would spend another herb re-learning it next run.
        if self.storage is not None:
            try:
                for (fact,) in self.storage.conn.execute(
                        "SELECT fact FROM learned WHERE topic='essence'").fetchall():
                    kind, _, essence = str(fact).partition("=")
                    if kind and essence:
                        from steemer import knowledge
                        knowledge.learn(kind, essence)
            except Exception as e:
                print(f"[taste] essence hydration failed ({e}) — continuing", flush=True)

    # -- client callbacks -----------------------------------------------------

    def on_hello(self, message: dict[str, Any]) -> None:
        self.config = message.get("config", {}) or {}
        self.guild = message.get("guild", {}) or {}
        self.tick = message.get("tick", 0)
        # v0.117.0: re-anchor the frame-lag clock. A fresh hello's tick is current by
        # definition, so lag measured from here is the server's delivery debt only.
        self._hello_anchor = (self.tick, time.monotonic())
        self._lag_bad_since = None
        self._record_phase(self.tick, "session hello")
        # v0.117.2: the config ARCHIVE is insert-only per distinct value, so a key
        # returning to an old value is invisible there (this hid whether the
        # tick_seconds=0.4 advertisement was still live during the 08-25/26 incident).
        # Print the timing-critical keys on EVERY hello — the log carries a timestamped
        # current-value series the archive cannot.
        print(f"[config] tick_seconds={self.config.get('tick_seconds')!r} "
              f"stale_order_ticks={self.config.get('stale_order_ticks')!r}", flush=True)
        # v0.79.1: persist the server config. It carries constants we have repeatedly
        # NEEDED and could not answer offline — `ride_max_tiles` blocked the rail analysis
        # for two passes because nothing ever wrote it down; it lives only in this message
        # and was gone by the time anyone asked.
        #
        # ONE ROW PER KEY, not one JSON blob: the first deploy stored the whole config as
        # a single fact and prod silently truncated it at `learned.fact`'s varchar(255) —
        # a defect SQLite tests cannot see. Scalars become "key=value" (always short);
        # `maps` collapses to its ids. Idempotent per key via record_learned's (topic,
        # fact) primary key, so an unchanged config costs no-ops and a changed one (Will
        # patches the server mid-week) leaves the old and new values side by side with
        # their proved_at timestamps.
        if self.storage is not None and self.config:
            try:
                for key in sorted(self.config):
                    val = self.config[key]
                    if key == "maps" and isinstance(val, list):
                        val = ",".join(str(m.get("id")) for m in val if isinstance(m, dict))
                    elif isinstance(val, (dict, list)):
                        val = json.dumps(val, sort_keys=True)[:200]
                    self.storage.record_learned("server_config", f"{key}={val}"[:255])
            except Exception as e:
                # A failed bookkeeping write must never block the hello — but it must not
                # be silent either, or a broken learned-table write hides until the next
                # time someone needs a config that was never saved.
                print(f"[config] record failed ({e}) — continuing", flush=True)
        hook = getattr(self.strategy, "on_hello", None)
        if callable(hook):
            hook(self, message)

    HINT_REFRESH_TICKS = 8     # read the sidecar's rival positions this often (cheap, cached)

    def _refresh_hints(self) -> None:
        """Pull the sidecar's latest rival-position snapshot (intel kind='track') into
        self.rival_hints, keyed by world. Fail-closed: a read hiccup or a stale/missing
        feed leaves the last hints in place and never touches the frame loop. Staleness of
        the FEED is the sidecar watchdog's job; here we just consume what's fresh."""
        if self.storage is None:
            return
        if self.tick - self._hints_at < self.HINT_REFRESH_TICKS:
            return
        self._hints_at = self.tick
        try:
            import json as _json
            row = self.storage.conn.execute(
                "SELECT tick, payload_json FROM intel WHERE kind='track' "
                "ORDER BY seq DESC LIMIT 1").fetchone()
            if row is None:
                return
            # v0.118.1: the track row's tick IS the public server clock — a
            # DIFFERENTIAL delivery-debt measurement (server tick minus our newest
            # frame tick). The anchor-based integral read a phantom 649s while the
            # true debt was 6 ticks (2026-08-28, oscillating server tick rate) —
            # it fired a spurious debt-heal and fed the FWD probe a +73 stamp.
            # Trust the sample only when the feed is AHEAD of our stream: a dead
            # or quiet sidecar falls behind and disqualifies itself.
            row_tick = row["tick"] if hasattr(row, "keys") else row[0]
            if isinstance(row_tick, int) and row_tick >= self.tick:
                self._offset_sample = (self.tick, row_tick - self.tick)
            payload = row["payload_json"] if hasattr(row, "keys") else row[1]
            d = _json.loads(payload)
            by_world: dict[str, list] = {}
            world = d.get("map")
            for rv in d.get("rivals") or []:
                if rv.get("pos") and rv.get("guild_id"):
                    by_world.setdefault(world, []).append(
                        {"guild_id": rv["guild_id"], "pos": tuple(rv["pos"]),
                         "name": rv.get("name")})
            # only replace the world that this snapshot covers; other worlds' last hints
            # stand until their own snapshot arrives
            if world is not None:
                self.rival_hints[world] = by_world.get(world, [])
        except Exception as e:                        # noqa: BLE001 — hints are advisory
            print(f"[hints] refresh failed ({e.__class__.__name__}) — keeping last",
                  flush=True)

    def server_health(self) -> str:
        """'ok' or 'bunker' — the strategy's read of the health state machine."""
        return self._health

    def _measured_tick_s(self) -> float | None:
        """s/tick measured from our own frame stream (median of the last ~200
        inter-frame slopes). v0.117.5: the 08-25 incident advertised tick_seconds=0.4
        while running 0.25 — a lag detector trusting the advertisement computes
        frames as EARLY and never alarms. Sensors trust measurements."""
        s = self._rate_samples
        if len(s) < 20:
            return None
        # MEDIAN of strided pairwise slopes, not the endpoint slope: a catch-up
        # burst (frames flushed near-instantly after a stall) contributes near-zero
        # slopes that an endpoint estimate absorbs — and with a fixed anchor, a
        # small rate error INTEGRATES into unbounded phantom lag. The median treats
        # the burst as the outlier it is.
        stride = 5
        slopes = []
        for i in range(len(s) - stride):
            (t0, w0), (t1, w1) = s[i], s[i + stride]
            if t1 > t0 and w1 > w0:
                slopes.append((w1 - w0) / (t1 - t0))
        if not slopes:
            return None
        slopes.sort()
        return slopes[len(slopes) // 2]

    def _note_rate(self, tick: int, now: float) -> None:
        s = self._rate_samples
        if not s or tick > s[-1][0]:
            s.append((tick, now))
            if len(s) > 200:
                del s[:len(s) - 200]

    def _lag_estimate(self, tick: int, now: float | None = None) -> float | None:
        """Seconds this frame arrived behind the tick-implied clock, from the hello
        anchor. None before the first hello. Injectable `now` for tests. Uses the
        MEASURED tick rate when available; the advertised value only as the
        cold-start fallback."""
        if self._hello_anchor is None:
            return None
        tick_s = (self._measured_tick_s()
                  or float(self.config.get("tick_seconds", 0.25) or 0.25))
        # v0.118.1: prefer the DIFFERENTIAL debt sample (public tick minus our
        # tick, via the sidecar track feed) over anchor integration. The integral
        # form accumulates phantom lag whenever the server's tick RATE oscillates
        # (measured 3.4->6.1 t/s within minutes on 2026-08-28: anchor said 649s,
        # truth was 6 ticks). Sample-and-hold with a TTL; past it, fall back.
        samp = getattr(self, "_offset_sample", None)
        if samp is not None and 0 <= tick - samp[0] <= OFFSET_SAMPLE_TTL:
            return samp[1] * tick_s
        a_tick, a_wall = self._hello_anchor
        if now is None:
            now = time.monotonic()
        return (now - a_wall) - (tick - a_tick) * tick_s

    def _health_step(self, tick: int, now: float | None = None) -> None:
        self._note_rate(tick, time.monotonic() if now is None else now)
        """Advance the bunker state machine one frame. Grace both directions:
        enter on SUSTAINED lag (HEALTH_ENTER_TICKS) or a poison storm (>=
        HEALTH_POISON_N/HEALTH_POISON_WINDOW — a storm is already sustained
        evidence); exit only after HEALTH_EXIT_TICKS with every signal clean."""
        lag = self._lag_estimate(tick, now)
        lag_bad = lag is not None and lag > HEALTH_LAG_S
        if lag_bad:
            if self._lag_bad_since is None:
                self._lag_bad_since = tick
        else:
            self._lag_bad_since = None
        self._poison_ticks = [t for t in self._poison_ticks
                              if tick - t < HEALTH_POISON_WINDOW]
        poison_bad = len(self._poison_ticks) >= HEALTH_POISON_N
        lag_sustained = (self._lag_bad_since is not None
                         and tick - self._lag_bad_since >= HEALTH_ENTER_TICKS)
        if poison_bad or lag_bad:
            self._health_bad_at = tick
        # v0.117.7 DEBT-HEAL: the frozen-debt deadlock, observed live — a session
        # carrying a constant sub-threshold delivery debt (e.g. 7s vs the 8s arm)
        # keeps the bunker held via jitter re-arming the exit clock, while the
        # shelter prevents the very actions whose rejections would trigger the
        # poison self-heal. A re-hello is PROVEN curative in this era (fresh
        # sessions are born clean), so when bunkered + poison-quiet + standing
        # debt, request one proactively. The client honors it with the heal
        # spacing guard.
        if (self._health == "bunker" and not self._poison_ticks
                and lag is not None and lag > 2.0
                and tick - getattr(self, "_debt_heal_at", -10**9) >= HEALTH_EXIT_TICKS):
            self._debt_heal_at = tick
            self.request_rehello = True
            print(f"[heal] debt-heal requested at t{tick}: bunkered, poison-quiet, "
                  f"standing lag {lag:.1f}s — a fresh session sheds the debt", flush=True)
        if self._health == "ok" and (poison_bad or lag_sustained):
            self._health = "bunker"
            why = ("poison storm "
                   f"{len(self._poison_ticks)}/{HEALTH_POISON_WINDOW}t" if poison_bad
                   else f"lag {lag:.1f}s sustained {tick - self._lag_bad_since}t")
            print(f"[bunker] ENTER at t{tick}: {why} — recalling the field, "
                  "holding embarks", flush=True)
            self._record_phase(tick, why)
        elif self._health == "bunker" and (
                self._health_bad_at is None
                or tick - self._health_bad_at >= HEALTH_EXIT_TICKS):
            self._health = "ok"
            print(f"[bunker] EXIT at t{tick}: all signals clean "
                  f"{HEALTH_EXIT_TICKS}t — resuming normal play", flush=True)
            self._record_phase(tick, f"clean {HEALTH_EXIT_TICKS}t")

    def _maybe_fwd_probe(self, here: list[str]) -> None:
        """v0.118.0 FORWARD-STAMP probe. The field-time blocker is
        stale_order_ticks=0 meeting a standing per-session delivery debt: every
        envelope we send is stamped with a frame tick the server already considers
        old, so play dies within ticks of each bunker exit (six-for-six on
        2026-08-28). Discriminator: one normal say + one say stamped at the
        ESTIMATED CURRENT server tick (frame tick + measured debt), on DIFFERENT
        chars (the proven per-char order rule must not confound), same batch.
        Forward renders while normal is dropped/errored => lag-corrected stamping
        buys back field time with no server fix. Runs only while unhealthy — the
        healthy regime has nothing to measure."""
        if (self._health == "ok" or len(here) < 2
                or self._hello_anchor is None
                or self.tick - getattr(self, "_fwd_probe_at", -10**9) < PROBE_EVERY):
            return
        lag = self._lag_estimate(self.tick)
        if lag is None or lag <= 0:
            return
        tick_s = (self._measured_tick_s()
                  or float(self.config.get("tick_seconds", 0.25) or 0.25))
        off = round(lag / tick_s)
        if off < FWD_PROBE_MIN_TICKS:
            return
        self._fwd_probe_at = self.tick
        print(f"[probe] FWD tick={self.tick} offset~{off}t "
              f"chars={here[0]},{here[1]} — normal + forward-stamped say", flush=True)
        self._probe_pending = (getattr(self, "_probe_pending", None) or []) + [
            {"char_uid": here[0], "action": "say", "text": "fwd-a"},
            {"char_uid": here[1], "action": "say", "text": "fwd-b",
             "_probe_age": -off},
        ]

    def _record_phase(self, tick: int, why: str) -> None:
        """Persist the health phase to the DB bus (an events row, kind=bot_anomaly,
        subtype phase:*) so the dashboard's phase chip reads the bot's actual state
        instead of re-deriving the machine. Best-effort: a failed write must never
        block play."""
        if self.storage is None:
            return
        try:
            self.storage.record_anomaly(tick, f"phase:{self._health}", {"why": why})
        except Exception as e:
            print(f"[phase] record failed ({e}) — continuing", flush=True)

    def on_frame(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        self.tick = frame.get("tick", self.tick)
        self._health_step(self.tick)
        self._refresh_hints()
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
        self.kpis.note_xp(self.tick, sum(1 for e in (frame.get("events") or [])
                                         if e.get("kind") == "xp"))
        if frame.get("world") == "village":
            by_world = guild.get("chars_by_world") or {}
            # v0.117.3 staleness probe (healthy windows only — a probe during a storm
            # measures nothing and adds retry pressure)
            here = guild.get("chars_here") or []
            if (self._health == "ok" and here
                    and self._hello_anchor is not None
                    and self.tick - getattr(self, "_probe_at", -10**9) >= PROBE_EVERY):
                self._probe_at = self.tick
                i = getattr(self, "_probe_i", 0)
                self._probe_i = i + 1
                if i % 4 == 3:
                    # v0.117.5 ORDER DISCRIMINATOR: a fresh say THEN an aged say for
                    # the SAME char in the same batch. A time-window validator accepts
                    # both; an order validator (the reading of `stale_order_ticks`
                    # that fits all data) rejects the aged one because the fresh one
                    # just advanced the char's last-accepted tick.
                    print(f"[probe] PAIR tick={self.tick} char={here[0]} — fresh say "
                          "+ K=5 aged say", flush=True)
                    self._probe_pending = [
                        {"char_uid": here[0], "action": "say", "text": "sync-a"},
                        {"char_uid": here[0], "action": "say", "text": "sync-b",
                         "_probe_age": 5},
                    ]
                else:
                    k = PROBE_AGES[i % len(PROBE_AGES)]
                    print(f"[probe] K={k} tick={self.tick} char={here[0]} — aged say "
                          "sent", flush=True)
                    self._probe_pending = [{"char_uid": here[0], "action": "say",
                                            "text": "sync", "_probe_age": k}]
            self._maybe_fwd_probe(here)
            for a in self.kpis.observe(self.tick,
                                       sum(len(v) for v in by_world.values()),
                                       len(guild.get("chars_here") or []),
                                       sheltering=(self._health == "bunker")):
                self._report_anomaly(a)
            acts = self.strategy.village(self, frame) or []
            probe = getattr(self, "_probe_pending", None)
            if probe is not None:
                self._probe_pending = None
                acts = list(acts) + list(probe)
            return acts
        return self._field(frame)

    def _shadow_observe(self, world: str, frame: dict[str, Any]) -> None:
        """Accumulate this window's band inputs and, when a death-risk artifact exists,
        shadow-score our characters every SHADOW_EVERY ticks. Wrapped whole in the
        fail-closed try: a scoring defect must never reach the frame loop."""
        try:
            from steemer import mlfeat, models
            nf = mlfeat.normalize_frame(frame)
            from steemer.strategy.explorer import THREAT_KINDS, WILDLIFE_SAFE
            mobs = nf["mobs"]
            undead = sum(1 for m in mobs if m["kind"] in THREAT_KINDS)
            melee = sum(1 for m in mobs
                        if m["kind"] not in THREAT_KINDS and m["kind"] not in WILDLIFE_SAFE)
            acc = self._band_obs.setdefault(world, [0.0, 0.0, 0])
            acc[0] += (undead / len(mobs)) if mobs else 0.0
            acc[1] += float(melee)
            acc[2] += 1
            want_death = models.available("death_risk")
            want_stint = models.available("stint_survival")
            if not (want_death or want_stint):
                return
            if want_stint:
                # stint bookkeeping mirrors the extractor exactly: village frames never
                # reach here, so a village trip shows as a tick gap and starts a new stint
                for ch in nf["chars"]:
                    st = self._ml_stint.get(ch["uid"])
                    if st is None or self.tick - st[1] > 1:
                        st = self._ml_stint[ch["uid"]] = [self.tick, self.tick]
                    st[1] = self.tick
            death_scores, stint_scores = {}, {}
            band = {"next_refresh_in": (frame.get("next_refresh") or {}).get("in_ticks"),
                    "undead_frac": acc[0] / acc[2] if acc[2] else 0.0,
                    "melee_preds": acc[1] / acc[2] if acc[2] else 0.0}
            profiles = models.load_profiles()
            for ch in nf["chars"]:
                if self.tick - self._ml_last_scored.get(ch["uid"], -10 ** 9) < SHADOW_EVERY:
                    continue
                drf = mlfeat.death_risk_features(ch, nf, profiles, band)
                scored = False
                if want_death:
                    p = models.score_death_risk(drf)
                    if p is not None:
                        death_scores[ch["uid"]] = round(p, 4)
                        scored = True
                if want_stint:
                    st = self._ml_stint[ch["uid"]]
                    q = models.score_stint(
                        mlfeat.stint_features(ch, nf, profiles, band,
                                              self.tick - st[0]))
                    if q is not None:
                        stint_scores[ch["uid"]] = round(q, 4)
                        scored = True
                if scored:
                    self._ml_last_scored[ch["uid"]] = self.tick
            if (death_scores or stint_scores) and self.storage is not None:
                import time as _time
                from steemer import intel
                for model_name, sc in (("death_risk", death_scores),
                                       ("stint_survival", stint_scores)):
                    if sc:
                        intel.record(self.storage.conn, "model_score", self.tick,
                                     _time.time(),
                                     {"model": model_name, "world": world, "scores": sc})
        except Exception as e:                        # noqa: BLE001 — shadow, fail closed
            print(f"[models] shadow observe failed ({e.__class__.__name__}) — continuing",
                  flush=True)

    def _shadow_band(self, world: str) -> None:
        """A refresh boundary: classify the window that just ENDED, roll the history,
        and shadow-score the forecast for the window that begins now."""
        try:
            from steemer import mlfeat, models
            acc = self._band_obs.pop(world, None)
            if acc and acc[2]:
                cls = mlfeat.band_danger_class(acc[0] / acc[2], acc[1] / acc[2])
                hist = self._band_hist.setdefault(world, [])
                hist.insert(0, cls)
                del hist[4:]
            if not models.available("band_forecast"):
                return
            fc = models.score_band(
                mlfeat.band_features(world, self._band_hist.get(world, []), 0))
            if fc is not None and self.storage is not None:
                import time as _time
                from steemer import intel
                intel.record(self.storage.conn, "model_score", self.tick, _time.time(),
                             {"model": "band_forecast", "world": world,
                              "history": list(self._band_hist.get(world, [])),
                              "forecast": {k: round(v, 4) for k, v in fc.items()}})
        except Exception as e:                        # noqa: BLE001
            print(f"[models] shadow band failed ({e.__class__.__name__}) — continuing",
                  flush=True)

    def _learn_from_events(self, frame: dict[str, Any]) -> None:
        """Positive and negative evidence the SERVER volunteers, for any frame.

        The server refuses and confirms through TWO channels -- action_errors AND events --
        and these are the event-side ones. Scoped to our own eids: the streams are
        world-wide and rivals forge and stagger under loot constantly.
        """
        our_eids = {c["eid"]: c["char_uid"] for c in frame.get("chars", []) or []
                    if c.get("eid") is not None}
        for ev in frame.get("events") or []:
            # v0.88.0: deaths are handled BY THEIR OWN char_uid, before the eid gate —
            # a corpse is never among the frame's chars, so the eid lookup that scopes
            # every other event can never resolve it. The seat ranking prunes instantly;
            # a rival's uid prunes nothing (not in our ledger) and is harmless.
            if ev.get("kind") == "death" and ev.get("char_uid"):
                self._dead.add(ev["char_uid"])
                hook = getattr(self.strategy, "on_char_death", None)
                if callable(hook):
                    # v0.92.1: the death's WORLD and tick ride along — a corpse is the
                    # one danger sensor that never needs two predators in frame at once
                    hook(ev["char_uid"], frame.get("world"), self.tick)
                continue
            if ev.get("kind") == "returned" and ev.get("char_uid"):
                self._returned_at[ev["char_uid"]] = self.tick
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
            elif "taste" in (kind or ""):
                # v0.81.0: the FIRST taste in the project's history was sent this
                # version, so this event's true shape has never been observed. The parser
                # is tolerant about field names and LOUD about the raw payload either
                # way: if it parses, we decode an ingredient forever; if it does not,
                # the print is the specimen the next pass wires exactly. (The per-run
                # once-per-kind guard in the strategy caps the cost of a missed parse at
                # one herb per kind.)
                print(f"[taste] raw event: {ev!r}", flush=True)
                item_kind = ev.get("item") or ev.get("kind_name") or ev.get("ingredient")
                essence = ev.get("essence") or ev.get("result") or ev.get("tell")
                if (isinstance(item_kind, str) and isinstance(essence, str)
                        and 0 < len(essence) <= 24):
                    from steemer import knowledge
                    if knowledge.learn(item_kind, essence):
                        print(f"[taste] DECODED {item_kind} = {essence}", flush=True)
                        if self.storage is not None:
                            try:
                                self.storage.record_learned(
                                    "essence", f"{item_kind}={essence}")
                            except Exception as e:
                                print(f"[taste] record failed ({e})", flush=True)
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
        # v0.117.0: session-poison rejections feed the health machine's storm signal
        # (run 229: 8 stranding deaths incl. our last two leveled chars). One stray
        # rejection is normal play; HEALTH_POISON_N within the window is a storm.
        if message.get("reason") in ("stale_frame", "unknown_character"):
            self._poison_ticks.append(message.get("tick", self.tick))

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
        refreshed = self._band_refreshed(world, frame)
        if refreshed:
            recheck |= {p for p in seen_now if known.get(p) == "chest_open"}
            self._shadow_band(world)
            self.refreshed_at[world] = self.tick          # v0.106.0: replenishment clock
        _nr_ticks = (frame.get("next_refresh") or {}).get("in_ticks")
        if isinstance(_nr_ticks, int):
            self.refresh_eta[world] = self.tick + _nr_ticks

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
                           gold=gold, bodies=bodies, containers=containers, bounds=bounds,
                           fresh=seen_now)

        # Resolve outstanding predictions BEFORE deciding: this frame is the evidence for
        # what we did last time, and a prediction must be judged against the world as it
        # was when it could still have come true.
        chars_now = frame.get("chars", []) or []
        self.expect.observe(self.tick, chars_now)
        alarm = self.expect.alarm(self.tick)
        if alarm is not None:
            self._report_anomaly(alarm)

        self._shadow_observe(world, frame)
        actions: list[dict[str, Any]] = []
        for char in frame.get("chars", []):
            uid = char["char_uid"]
            # v0.89.0: never command a ghost. A dead uid never acts again (uids are not
            # reused); a just-returned one sits out RETURN_GRACE ticks of stale field
            # frames — the village frame commands it the moment it truly arrives.
            if uid in self._dead:
                continue
            if self.tick - self._returned_at.get(uid, -10 ** 9) < RETURN_GRACE:
                continue
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
