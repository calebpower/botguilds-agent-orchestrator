# How we work together

_A living document. Started 2026-08-22, at loop iteration 85 / `explorer/0.72.0` / run #151._

The operator's reason for it, in their own words: *"Part of the motivation of this project
is so I learn how to work with you best and I'd like a record of that."*

So this is not a style guide and not generic advice about AI agents. It is a record of the
working practices that this repository actually produced, each one traceable to the pass
that forced it — a version number, a run number, a commit, a measured figure. Where a
practice was learned by getting something wrong, the wrong thing is named. Two audiences:
a human who wants to run long-lived autonomous work with an agent, and the next Claude
session, which will arrive with no memory of any of this.

**Adding to it.** Append a dated entry under the relevant practice, or add a new
`## Practice — <name>` section. Every claim needs a citation you could check: a version, a
run, a commit sha, or a `decisions.log` iteration. A practice nobody can point to evidence
for does not belong here; delete it rather than let it decorate the page.

---

## The shape of the work

The bot ("Stanley_Steemer") plays a live, shared, persistent multiplayer game. It runs
detached from the Claude session — `redeploy.sh` reparents it to init — so the game keeps
being played whether or not anyone is improving it. That separation is the founding safety
property, recorded on 2026-08-17 01:06 when the usage-cap failure mode was designed: *a cap
pauses improvement, never play.*

Around that runs the improvement loop (`orchestrator/loop.md`), self-paced at hours per
iteration, not minutes. One pass:

> **measure → diagnose → ship ONE lever → mutation-checked tests → gate → self-deploy → record**

Scale as of this writing: 85 iterations across six days (go-live 2026-08-17 00:14 on
`explorer/0.1.0`, run window #2), 76 strategy versions with their own release commit, 281
commits total, 151 run windows, 4,003 lines of `decisions.log`, 260 entries in
`findings.jsonl`, 811 tests in the gate. Zero of those commits carry a generated trailer, and all 281 are authored as the
repository's configured user — the operator's standing rule, held without exception.

---

## Practice — one lever per pass, because attribution is the scarce resource

The world is shared, persistent and noisy. There is no clean A/B: one guild per session, and
the ground itself changes underneath a measurement. So the loop buys attribution the only
way available — sequential before/after windows on *rate* metrics, with the strategy version
and git sha recorded in the `runs` table as the timeline.

That only works if one thing changes at a time, and the cost of breaking the rule is on the
record from the fourth iteration. `0.5.0` (2026-08-17 03:21, equip-carried-gear) shipped
ahead of `0.4.0`'s isolated measurement because the operator had spotted characters fighting
bare-handed. The entry says so plainly — *"Attribution caveat: shipped ahead of 0.4.0's
isolated measurement, so spend_xp got only a short window"* — and the next measurement could
only report `0.4.0+0.5.0` combined. Deliberate, logged, and paid for.

Two corollaries the record forced. **Say how it would be falsified, before deploying:**
nearly every strategy entry carries an explicit falsification clause written *before* the
window exists (`0.28.0`: *"the falsifiable prediction is that run #84+ gold climbs
MONOTONICALLY and BREAKS 529"*; `0.48.1`: mean pairwise distance must fall in dangerous
worlds and stay flat in safe ones, and `move_failed` must not rise). Writing the criterion
first is what makes a later "it worked" checkable rather than a story fitted to the data.
And **a swing inside noise is not a result** — iter 71 lost its measurement entirely to a
band refresh that collapsed ground loot 18× mid-window, and recorded *"0.59.0 is deployed
and gated but its effect is UNMEASURABLE in this band"* rather than a verdict.

---

## Practice — what blocks, and what must never block

These are opposite rules that live together, and getting them the wrong way round is the
failure that cost this project the most wall-clock time.

**Never block on the operator.** On 2026-08-20 an `AskUserQuestion` about freezing the
club-buy left the loop hung and *the game ran roughly two days with zero strategy updates*.
The operator's correction, quoted in `memory/never-hang-the-loop.md`: **"if you don't hear an
answer from me within ten minutes, you need to execute with your best judgement"** — plus
*"immediately give me a status update."* Since then the loop surfaces the decision, proceeds
on best judgment where the action is reversible, and leads the next turn with concrete state
(bot alive? gold? what changed?) rather than an apology. `0.28.0`, `0.29.0`, `0.30.0`,
`0.31.0` and `0.32.0` all carry the note *"Decided autonomously (10-min rule)"*.

The same incident taught a second thing: identify a suspicious process by PPID before
treating it as rogue. The "second rogue worker" apparently kick-warring the deploy was the
loop's *own* hung session (pid 50412) — hung precisely because it was blocked on the
operator. The safety classifier that refused to let it be killed was right.

**Some things do block, absolutely.** The redeploy — the one irreversible outward step —
happens only after local pytest, the reaper container gate, and a commit. That ordering is
stated as a safety invariant (2026-08-17 01:06) so that an interruption at any earlier point
costs at most an uncommitted improvement, never a broken live bot. "Do not redeploy on a red
gate" is in `loop.md` step 6 and has not been bent. Likewise mutation-checking a new
assertion is not optional; it has caught defects on nearly every pass and is discussed below.

**Where an answer would help but is slow, check the premise instead.** iter 63: the operator
delegated the "gold sink" call; the premise was checked twice before advising, and *it
changed the lever twice over.* Gold really was pinned at ~145 against a 200 armour floor —
but the cause was not "too many clubs for bare recruits", it was one character buying six
clubs at exactly `VILLAGE_ACTION_COOLDOWN` apart. The lever went from an economy policy
change to a bug fix: much safer, much clearer.

---

## Practice — the wishlist, and a scoring formula with teeth

The operator instituted this on 2026-08-20 (iter 23) after watching 21 deploys ship zero
wishlist items. It is a forcing function, not a ranking exercise.

```
final = good_idea × risk_to_bot × (0.75 − 1/tc)
```

- `good_idea` — 0..1, subjective, anchored (below).
- `risk_to_bot` — 0..1, 1 = safe. **Risk to the *bot*** — not to the platform, not to the
  deliverable, not "how hard is this to verify". A dashboard runs in a separate process and
  cannot hurt the bot's play; docking it for being a big front-end build is the mistake that
  wrongly suppressed the per-character stats panel to 0.481 (corrected: 0.53, shipped).
- `tc` — **deploys** since the item was added, not loop passes. A pass that ships no deploy
  does not advance it.

**Why an ageing term exists.** At `tc=1` the third factor is −0.25, so a freshly-added item
scores negative and cannot be implemented the turn it is proposed; pressure then grows the
longer it sits — deliberate friction against chasing the newest idea. The corollary is
enforced: when magic/casting split off after `0.63.0` shipped the acquisition half, it
re-entered *"at tc=1 rather than inheriting fifty passes of age it did not earn"* (commit
0d9b4a2). A **split** item, though, *inherits* its `add_minor` — resetting the clock would
punish an idea for having waited.

**The ceiling rule — the most important line on the page.** The age factor saturates at
0.75, so `ceiling = good_idea × risk_to_bot × 0.75`. An item whose ceiling is under 0.5 can
never qualify at any age. It is **INELIGIBLE**, and must be reported that way. For many
passes it was instead reported as "just under 0.5", which reads as "coming soon" and means
"never".
At a typical `risk_to_bot` of 0.97, `good_idea` must exceed 0.687 for an item ever to be
built. Three items were being misreported this way when the rule was written down.

**The recalibration, and what prompted it.** On 2026-08-21 the operator asked why their ideas
kept scoring low. The fault was in the scale, not the ideas: seven of ten items sat inside a
**0.07-wide band straddling the eligibility line** — *a coin flip with a decimal point*.
Three failure modes, all in the scorer:

1. *Band compression.* A scoring band narrower than the decision it drives is not a
   measurement.
2. *Anchoring.* "how-nav" appears 18 times in `decisions.log` creeping 0.496 → 0.502 while
   only `tc` moved. `good_idea` must be re-examined each pass, not just aged.
3. *Visibility bias.* Everything scored ≥0.85 was framed as engineering; everything parked
   at the bottom was something the operator would **see or enjoy**.

That third one is a standing rule, and it had already been corrected once and drifted back:
**`good_idea` credits operator enjoyment and visibility.** The operator plays this game too.
Do not dock for "aesthetic, doesn't help the bot" — `risk_to_bot` is what handles harm. Do
dock for genuine quality limits: stale data, fragility, speculation, bundling. The
enjoyment-credited rescore lifted version story-mode 0.55 → 0.78 and trash-talk 0.50 → 0.75,
and shipped the loot/danger heatmaps (0.551) and story mode (0.537).

Recalibration moved **6 items up and 2 down, mean +0.026, spread ×1.25** — discrimination,
not inflation. That ratio is the check: *if a recalibration only moves things up, it is
inflation.*

**Never bundle slices of different risk under one score.** Two worked examples, one day
apart. The exploration matrix, bundled, scored `0.88 × 0.80` — ceiling 0.528, clearing 0.5
only at `tc=26`: the read-only analysis half held hostage for ~26 deploys by risk belonging
entirely to the half that issues untried actions on live characters. Split, (A) is
`0.85 × 1.00`, ceiling 0.6375, clearing 0.5 at `tc=7` — and it duly shipped once it crossed; (B) is `0.88 × 0.70`, ceiling 0.462, which **never** clears,
the formula correctly saying "this always needs an explicit operator override." The Campaign
Layer likewise scored `good_idea` 0.80 — never the problem — but `risk_to_bot` 0.50, earned
entirely by its per-character A/B harness, gave the whole entry a ceiling of 0.300:
permanently ineligible from the day it was scored, and present in only **4 of 20** score
tables. Splitting out "coordinated raids" gives `0.88 × 0.85 = 0.539`, which qualified and
shipped as `0.48.0`/`0.48.1`.

The anti-bundling rule was written into memory in the morning and the Campaign Layer was
scored as a bundle in the very rescore that fixed everything else. Hence: **when a scoring
rule is learned, sweep the whole list with it — the old items, not just the newest one.**

**The cheap mechanical check.** The score table must contain exactly one row per open item.
Counting them takes seconds, and it exists because an omission is worse than a wrong number
and far harder to notice.

**A score is a priority hint, not a veto.** The sidecar-watchdog item sat at 0.34 and shipped
anyway on 2026-08-21, as part of the outage response, because an incident made it urgent.

---

## Practice — mutation-check every assertion, and self-test the oracle

The house rule is from `~/.claude/CLAUDE.md`: after writing a test, break the thing it covers
and confirm it fails; then restore. Every version entry in this log reports its mutant count
(`0.72.0`: 10 tests, 8 mutants killed; `0.61.0`: 22 tests, 19 mutants).

It earns its keep by catching *the test author*, repeatedly and in the same ways:


- **Tests that pass for the wrong reason.** The cohesion wiring test placed the ally NORTH —
  but "push north into unexplored ground" is also on the ladder and also moves north, so a
  passing test proved nothing; moving the ally WEST makes the direction unambiguous. And a
  mutant letting a character count *itself* as an ally sailed through a test that only
  asserted "does not crash".
- **Tests derived from the constant they check.** The feedstock test iterated
  `FORGE_FEEDSTOCK_PREFIXES` to validate `FORGE_FEEDSTOCK_PREFIXES`. Then `VEIN_SEEK_RANGE`,
  `SCARCE_LONE_KEEP`, `OVERBURDENED_TTL`, `FORGE_FAIL_LIMIT` — *"It is a habit, not three
  accidents."* The remedy: hardcode the policy claim ("+5 ticks still refused, +500 long
  gone") and pin the constant's band in a separate test.
- **Doubles that drift from the real thing**, now replaced by the real `DecisionTrace` and
  the real `GuildBot`; and **a guard mutation proved genuinely redundant**, deleted rather
  than tested around (`0.53.0`).

**And the oracle itself lied twice, in one session.** This matters more than any feature it
was checking.

1. The ad-hoc mutation scripts restored sources with `shutil.move`, giving the file the
   *backup's* mtime — older than the `.pyc` compiled from the mutant — so CPython served the
   **mutant's bytecode** afterwards and consecutive mutants could report each other's
   results. Symptom: the source visibly said `if live:` while behaviour was unmistakably
   `if True:`.
2. `tools/mutate.py` inferred "killed" from a nonzero pytest exit — and pytest also exits
   nonzero when the selector matches nothing. Two mutants were reported KILLED against test
   names that **did not exist** (iter 68).

Both failures were in the oracle, not the code. The fixes are executable: the harness now
lives in the repo with its own tests, sets `PYTHONDONTWRITEBYTECODE=1`, clears `__pycache__`
per mutant, runs `-p no:cacheprovider`, `os.utime`s on restore, and **runs each selector
clean before mutating, refusing to score it unless it passes unmutated** — verified by
feeding it a deliberately nonexistent selector, which it now skips. All 21 mutants from the
affected session were re-run under the fix; all killed. The results had been right, but
nobody could have known that until the harness could be trusted.

**The limit of mutation testing, learned the hard way.** Every regression that shipped on
2026-08-21 passed a green **and fully mutation-killed** gate. `0.46.0`'s input space was
(has lumber, has metal) and only the lumber axis was tested; `0.49.0`'s was 17 distinct
`reason` values, two tested and one of those classified wrong. **Mutation proves a test is
sensitive to code changes; it says nothing about whether the tests cover the input space.**
The countermeasure is `steemer/vocabulary.py`, which harvests the real vocabularies from
project history (17 reasons, 23 tile kinds, 25 items, 26 verbs of which 14 have ever been
sent) into a frozen reviewed fixture, and property tests that run over all of it — verified
by restoring `0.49`'s clause, which the new test kills. And enumeration is only half:
asserting `freed == (reason in INTENT_RETRY_DIFFERS)` is derived from the constant it checks,
so a *wrong* classification survived it. The 17 reasons are now also partitioned **by hand**,
one line of reasoning each. *Enumeration catches "the code ignores the rule"; deliberate
duplication catches "the rule is wrong".*

---

## Practice — write directives that can fail, not prose that can be read past

This is the sharpest process lesson in the repository, and it is visible as a controlled
experiment nobody designed.

`orchestrator/loop.md` has carried a **"Metric attribution"** section since commit `a60a206`
on 2026-08-17 00:05 — nine minutes before the bot went live. It is good prose. It says the
world is noisy, to use sequential rate windows, and to state uncertainty honestly.

In the five days after it was written, at least eleven attribution errors went into production
diagnoses anyway:

| pass | the error |
|---|---|
| iter 2 | `deaths/recruit` used as a survival oracle — it is structurally near-constant, since each death triggers a refill recruit |
| 08-18 | "MariaDB stalls under live play" — a reused `REPEATABLE READ` connection froze its MVCC snapshot; two healthy runs were killed on it |
| iter 62 | `0.48.0` cohesion called INERT from "offered 28, chosen 0" taken ~130 ticks after deploy; over the full run: offered 688, **chosen 349** |
| iter 67 | "fielded collapsed 10→6" — computed from `chars_by_world`, which is empty in field frames |
| iter 67 | "recruits spiked to 110" — a duration artifact; per 1k frames it was 1.46 vs 1.11 |
| iter 67 | "all 31 gaps are in vale, therefore server-side" — `seq` is global and round-robins worlds. Already **filed as a server bug**; retracted before anyone acted on it |
| iter 71 | run #136's collapse called a `0.59.0` regression; replaying the same 400 frames through both versions gave **byte-identical** actions |
| iter 72 | the blind spot sized at "2,500–4,600 chest_open sightings" — the real population is **22 distinct chests** |
| iter 77 | "97% of forge opportunities missed" — a *stateless* replay, which cannot know what the live instance had learned |
| iter 78 | `0.64.0` "confirmed" at forge success 35%→68% — both figures counted **rival** forges; ours was flat at 33/26/21/17% |
| iter 80 | "forging has stopped entirely" and "terrain_hit collapsed 519→8" — both from sampling a run in its first minutes |

Reading a paragraph about attribution does not prevent any of these. What prevented
recurrence, every time, was something that could **fail**:

- `shadow.MIN_DECISIONS = 2000` (`steemer/shadow.py:114`) — the shadow-eval gate now
  *refuses to rule* below a sample that could outlast a warm-up. The comment on the line is
  the lesson. An INERT verdict from a short window reads as evidence when it is only
  ignorance.
- `tools/mutate.py`'s clean-run-before-mutate check, with `tests/test_mutate.py` driving it
  to report a **survivor** — because a harness only ever observed reporting KILLED proves
  nothing.
- `steemer/vocabulary.py` + `tests/test_vocabulary_coverage.py` — the input-space
  countermeasure above.
- `steemer/expectation.py` (`0.61.0`) — the bot derives a checkable claim from every action
  it sends and resolves it against later frames. It found a real defect on its first run over
  real data: `pickup` confirmed 90 times against **811 violations**.
- `.githooks/pre-commit` — hard-blocks `guild_token.json` and any file carrying a real-looking
  guild credential. `.gitignore` stops an accidental `git add`; `git add -f` bypasses it; the
  hook does not. It also caught a 55 MB core dump during the `0.51.0` segfault.
- The wishlist's "exactly one row per open item" count.

The pattern is worth stating flatly, because it is the transferable one: **a rule that lives
only as prose is a rule the next tired pass will read past. Put it where it can go red.**

---

## Practice — self-corrections and negative results are artifacts, not embarrassments

`findings.jsonl` has explicit `kind: self-correction` (7 entries) and `kind: process` (8)
alongside the 89 discoveries. Corrections are written *next to* the thing they correct, and
the correction is often flagged as the more useful half of the entry: iter 71's heading is
literally *"THEN I MISDIAGNOSED, AND THE CORRECTION IS THE USEFUL PART."*

Retractions escalate rather than quietly disappear. iter 78 reported `0.64.0` confirmed;
a `*** CORRECTION to iter 78 ***` block follows it in place; then iter 79 *replaces the
correction itself* — the softer story ("structurally right but bought no measured gain") was
still wrong, because `0.64.0` had never executed at all. Three layers, all preserved, in
order.

**Negative results are recorded so they are not re-litigated.** The best example is
`MOVE_STAMINA_SAFETY` (iter 83). 55% of decisions are `rest`, and the traces read "wanted
move but stamina 18 < ~30", which looks like a 1.5× margin wasting half the game. It was
re-tested and **deliberately not changed**: moves still fail `not_enough_stamina` at shown
stamina up to 29–30 (median 26–28) on runs #147/#148, exactly as `v0.9.0` measured; a move
costs ~15 and rest regenerates 10–12/tick. Resting most ticks is inherent to the stamina
economy. The constant stays, with fresh evidence attached, and the finding is in `HANDOFF.md`
under **"NEGATIVE RESULT — do not re-litigate."** The same pass notes the point of the
exercise: *two constants were re-tested that week; one had expired (`POTION_RESERVE`), one
had not — and you cannot tell which without looking.*

Other things recorded because they are *not* to be redone:

- **Do not rebuild the async storage mirror.** `0.51.0` moved storage writes to a worker
  thread; the MariaDB connection was also used from the main thread and it **segfaulted the
  live bot** (exit 139, zero frames across runs #124–126). `0.51.1` reverted it and kept only
  the free half — decide and send *before* recording — and that alone was the entire fix:
  run #128 took 85,319 frames with **0 gaps and 0.0% loss** against #120's 3.7% over 31 gaps.
  A test pins that `run()` does not construct one; the wishlist item was closed by
  measurement rather than by building the thing.
- **A test that now asserts the opposite of what it did** (`0.69.0`).
  `test_the_potion_buy_really_is_out_of_reach_at_our_gold` existed to justify `0.58.0`, and
  its premise is what `0.69.0` changed. Rewritten to assert what survives — a bottle is 2
  gold against a potion's 20 — rather than deleted or left contradicting the system.
- **Leads dissolved cheaply, before becoming levers** (iter 62). "We rest 65–70% of ticks" is
  the game's designed pacing (docs/04 predicts 75–80%); "124 recalled events" were almost all
  rivals, by `char_uid` prefix. One read of the docs and one ownership filter, against a whole
  lever nearly built on each.

---

## Practice — commit messages are the reasoning record

The commit bodies here are unusually long because they carry the argument, not the diff.
`0.72.0`'s subject is *"a rally must converge — cohesion was 25% of decisions and achieved
nothing"*; `0.70.0`'s is *"the map edge is not a frontier, and believing it was kept us
shallow"*. A reader six months out gets the reasoning without the log. Two rules attached.

**Long messages go through a heredoc and `git commit -F`, never an inline `-m`** — a practice
fix from a specific failure. Commit `0d9b4a2`'s body reads *"A tome carries , not , so
`_should_sell` filed it under 'pure loot -> bank it'"*; it should read "carries `use`, not
`equip`", but the backticks inside a double-quoted `-m` were taken as command substitution and
their empty output replaced both words. Every long message already used a file; this was the
one short one that did not.

**Pushed history is not rewritten.** `0d9b4a2` was already pushed, so it stands as written,
and commit `11434dd` records the correction beside it: *"The commit is pushed, so it stands;
the correction lives in decisions.log."* The operator's standing grant covers `git push` to
origin/main once the gate is green — and explicitly does **not** cover force-push, tags, PRs
or remote changes. Authorising one push is not authorising the next.

The same discipline applies outside this repo. Server bugs go to `server_bugs.md`,
reaper-framework bugs to `/home/cal/reaper_bugs.md`, and `/home/cal/reaper` is never
modified. When the "all gaps are in vale, therefore server-side" claim turned out to rest on
an unchecked assumption about `seq`, the filed report was **retracted before anyone acted on
it** — the note in `findings.jsonl` reads *"Never file a report against a third party on an
unverified assumption."*

---

## Practice — surviving the context reset

Long autonomous work outlives the session that does it. Three artifacts carry state across:

- **`HANDOFF.md`** — the on-ramp, written 2026-08-21 for a fresh session after the model was
  updated mid-project. It leads with where things stand *right now* (live version, run, sha,
  services up), then the hard-won rules in ⚠-marked blocks. It is deliberately *lossy*: it
  keeps what a new session would hurt itself by not knowing and points at `decisions.log` for
  the rest.
- **`decisions.log`** — the narrative, one block per pass, newest last, never edited in
  place. Corrections append.
- **`findings.jsonl`** — the lab notebook, four kinds from cold fact to idle wondering:
  `discovery` (a confirmed one must carry evidence), `question` (a fact-in-waiting with no
  test yet — this kind exists *because* a durable game fact learned in conversation once
  slipped through unlogged), `conjecture` (must carry a falsification test, the same rule as
  "every fix ships with a test"), `consideration`. `loop.md` requires **curation** every
  pass, not just appending — *"append-only rot ... is the failure mode here."*

Plus the memory files under `~/.claude/projects/.../memory/`, loaded automatically at session
start, holding the operator's standing rules (`never-hang-the-loop`, `push-authorization`,
`wishlist-scoring`) and the accumulated traps (`verification-traps`, `event-attribution`,
`deploy-and-backend-gotchas`). The division that has worked: **operator rules and
cross-session traps go to memory; project narrative stays in the repo.**

---

## Recurring failure modes — what the operator can watch for

These are the shapes that recur. Each has bitten more than once, which is why they are here
rather than in a single log entry.

**1. "Correct but unreachable" — four instances, one shape.** The single most expensive
pattern in the project.

| version | the lever | where it was not |
|---|---|---|
| `0.54.0` | vein-seek | validated against a map read from the `tiles_seen` **table**; `bot.known` starts empty every run and the table had no reader at all |
| `0.64.0` | forge proof rule | event parsing lived inside `_field()`, and **every `forged` event arrives on a village frame** |
| `0.67.0` | INT investment | keyed on a refusal held in process memory, which dies at every deploy |
| `0.68.0` | tome learn step | lived only in `village()`; the tome holder spent all 10,933 of its tome-carrying frames in vale |

The suite passed in every case — *"the chain was broken in the MIDDLE, where both ends test
clean."* The rule now in `HANDOFF.md`: **"it is implemented" is not an answer to "why is
nothing happening". Ask WHERE it runs and FOR WHOM** — name the frame the behaviour fires on
and the character it fires for, and check that character gets there. Corollary: **when a fix
shows no effect, first ask whether it executed, before interpreting any numbers at all.**

**2. Premise rot in constants.** A constant's justification is a claim about the world, and
claims expire. `POTION_RESERVE` was raised 100 → 600 in `v0.35.0` on good evidence (heals
were 99.6% free-brewed, 4,511 drinks against 16 buys). By `0.69.0` the guild brewed **seven**
`potion_red` per ~180k frames, gold ran 156–200, and the buy needed 620 — *unreachable by
arithmetic for the entire life of the reserve*. `v0.8.0`'s stranded-singleton sell rule was
the same story: right for abundant items, exactly wrong for the scarce input to a blocked
chain. Both read persuasively in their comments; **nothing watched either.**

**3. Sightings versus population.** A frame stream makes any sighting count trivially large.
"2,500–4,600 `chest_open` sightings per bucket" became, on a distinct-count, **22 chests in
the entire map**, with a peak of two simultaneous recheck targets. *Collapse to the distinct
entities before sizing an opportunity — `GROUP BY` the identity, not the observation.*

**4. Ownership filtering of world-wide event streams.** `forged`, `death`, `sale` and the
rest carry **every guild's** actions. `0.64.0` was reported confirmed on forge success
35% → 68%; both figures counted rivals (run #141's `forged` items included pickaxe ×5 and
sickle ×3, which we never attempted). Filtered to our own eids the series is flat: 33 / 26 /
21 / 17%. The sting is that ownership filtering had been applied *correctly to deaths one
pass earlier*. It is **the first step for any event-derived metric**, not a case-by-case
reminder. A related trap: `eid` (numeric) and `char_uid` (string) are different namespaces,
so the obvious "events for our roster" join matches nothing and reports zero.

**5. The catch-all branch that silently eats every new mechanic — four for four.**
`_should_sell` ends in "nothing recognised → bank it", and every mechanic unlocked adds an
item it misfiles: lumber and ingots (fixed `0.46`), `bone` and raw `ore` (`0.59`), and **74
tomes** (`0.63`) sold at 36–44 gold against a 120–150 shop price — while "magic is
unaffordable" sat at the top of the wishlist for fifty passes and not one spell had ever been
learned. **When a chain looks blocked on supply, check what we sell before believing we
cannot get it.**

**6. Harnesses that measure a different system than the one running.** A replay with a fresh
strategy per frame claimed 97% of forge opportunities were missed; one *stateful* instance
over the same run reproduced the live counts exactly (forge 18 vs 18, smelt 11 vs 11) and
found the real cause. Cousin rule: before blaming a live change on a code change, **replay
the same frames through both versions** — doing that gave byte-identical output and refuted
the diagnosis. And a run under ~20k frames cannot support "something stopped": two false
alarms came from minutes-old samples whose full-run figures were unremarkable (`terrain_hit`
114.6 → 101.3 per 10k). `shadow.MIN_DECISIONS` already encoded that, and was applied only to
the shadow harness, not to ad-hoc SQL.

**7. Chasing a moving target and calling it convergence.** `0.48.0`'s cohesion closed on the
*nearest ally*, which is mutual pursuit. On run #150 it was **25% of all decisions**
(31,540 / 125,971); one character logged **482 consecutive** cohesion decisions with the ally
distance reading 13, 9, 8, 7, 6, 8, 8, 6, 8. With rest at ~47%, roughly 72% of decisions
produced no progress. `0.72.0` rallies to the group's *centre* — a fixed point. The rule:
**any "move toward the nearest X" where X also moves is a chase, not a convergence.** Note
also how it was found: by tracing one character's consecutive decisions, which no aggregate
would have shown.

---

## What did not work, and what was abandoned

Recorded because a list of wins is not a record.

**Reverted or inert:** `0.17.0` survival reserve (reverted in `0.18.0`), `0.20.0`
armed-only-field (emptied the field, reverted in `0.21.0`), `0.22.0` spend_xp (confirmed
inert one pass later), `0.51.0` async storage mirror (segfaulted the live bot).

- **The hardcoded predator denylist** (`0.30.0`/`0.31.0`) — structurally doomed. It zeroed the
  known killers and deaths *rose*, because a fresh band brought new predators that were in no
  list. `0.32.0` inverted it to a benign allowlist: unknown means avoid. *A hardcoded list is
  always a cycle behind.*
- **The obvious visualisation, twice.** A heatmap of all 9,100 matrix cells would have been
  dominated by the default prior and said nothing; three narrower views were built instead.
  The danger heatmap was likewise reworked to occupancy-normalise, since raw death counts are
  survivor-biased.
- **Blind reference-kit merges.** The upstream submodule is reviewed and **hand-ported**
  (`0.44.0`), never merged. The per-pass drift check had lapsed and the kit was three commits
  ahead before anyone noticed; it is a standing loop step again.
- **Guessing at content.** `forge` was deferred from v0.10.0 to v0.52.0 because the `product` name was
  "unpublished" — and it sat in our own database the whole time, in 189 rival
  `forged`/`forge_started` events. The recipe *quantities*, still undocumented, were then
  learned from the server's own `wrong_materials` refusals. **The errors are the
  documentation.**

---

## Entries

_Append dated notes here as practices change. Keep the citation discipline._

- **2026-08-22 — document started** at iter 85 / `explorer/0.72.0` / run #151, on the
  operator's request for a record of how the two of us work. Everything above is drawn from
  `decisions.log` (iters 1–85), `findings.jsonl` (260 entries), `wishlist.md`,
  `orchestrator/loop.md`, `HANDOFF.md`, the 281-commit history, and the memory files.
