"""Build the expanded final experiment report (chronicle edition)."""
import html as H
import json

S = "/tmp/claude-1001/-home-cal-bots-bot-willmorrison-agent-orchestrator/e3052059-f7a8-4405-ada3-f309229a177c/scratchpad"
d = json.load(open(f"{S}/report_data.json"))
rows = d["rows"]
N = len(rows)

ERAS = [
    ("Bootstrap", "0.1", "First contact: learn to walk, fight, brew — and reach level 23"),
    ("The poverty wars", "0.10", "Phantom storms, clogged packs, and the long road to a bank balance"),
    ("Exploration at scale", "0.27", "Stockpiles, bestiaries, and the wildest runs on record"),
    ("The survival arc", "0.37", "Four versions against the stuck-death"),
    ("Arming & harvest", "0.43", "The recruit-burst fix, the delta port, and the day trees became wood"),
    ("Craft & prosperity", "0.46", "Forge science, market firsts, and the economics of depth"),
    ("Wizards & ML", "0.85", "The INT race, the escort doctrine, and models that lost to constants"),
    ("Sharpening the hunt", "0.111", "The first deliberate kill"),
    ("The server war", "0.115", "Nine days of defense-in-depth against a dying server"),
]

def vkey(v):
    try:
        p = v.split(".")
        return (int(p[0]), int(p[1]))
    except Exception:
        return (0, 0)

era_of_run = {}
bounds = [(name, vkey(v)) for name, v, _ in ERAS]
for r in rows:
    kv = vkey(r["v"])
    era = bounds[0][0]
    for name, b in bounds:
        if kv >= b:
            era = name
    era_of_run[r["run"]] = era

era_stats = {}
era_first_idx = {}
for i, r in enumerate(rows):
    e = era_of_run[r["run"]]
    s = era_stats.setdefault(e, {"runs": 0, "frames": 0, "deaths": 0, "xp": 0,
                                 "kills": 0, "errors": 0, "duty": [], "hours": 0})
    era_first_idx.setdefault(e, i)
    s["runs"] += 1; s["frames"] += r["frames"] or 0; s["deaths"] += r["deaths"]
    s["xp"] += r["xp"]; s["kills"] += r["kills"]; s["errors"] += r["err_total"]
    s["hours"] += r["hours"] or 0
    if r["duty"] is not None:
        s["duty"].append(r["duty"])

W, HT, PAD = 940, 180, 28
def chart(series, color_var, label, fmt=lambda v: str(v), bar=False, cap=None):
    vals = [(i, v) for i, v in enumerate(series) if v is not None]
    if not vals:
        return ""
    vmax = max(v for _, v in vals)
    if cap:
        vmax = min(vmax, cap)
    vmax = max(vmax, 1)
    X = lambda i: PAD + i * (W - 2 * PAD) / max(1, N - 1)
    Y = lambda v: HT - PAD - min(v, vmax) * (HT - 2 * PAD) / vmax
    bands = ""
    era_seq = sorted((era_first_idx[e], e) for e in era_stats)
    for j, (i0, e) in enumerate(era_seq):
        i1 = era_seq[j + 1][0] if j + 1 < len(era_seq) else N
        if j % 2 == 1:
            bands += (f'<rect x="{X(i0):.1f}" y="{PAD-14}" width="{X(i1-1)-X(i0):.1f}" '
                      f'height="{HT-2*PAD+14}" class="band"/>')
    if bar:
        bw = max(1.0, (W - 2 * PAD) / N - 0.6)
        marks = "".join(
            f'<rect x="{X(i)-bw/2:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" '
            f'height="{HT-PAD-Y(v):.1f}" class="mark {color_var}"/>'
            for i, v in vals if v > 0)
    else:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in vals)
        marks = f'<polyline points="{pts}" class="line {color_var}"/>'
    peak_i, peak_v = max(vals, key=lambda t: t[1])
    grid = "".join(f'<line x1="{PAD}" x2="{W-PAD}" y1="{Y(vmax*f):.1f}" y2="{Y(vmax*f):.1f}" class="grid"/>'
                   for f in (0.5, 1.0))
    peak = (f'<circle cx="{X(peak_i):.1f}" cy="{Y(peak_v):.1f}" r="3" class="dot {color_var}"/>'
            f'<text x="{min(X(peak_i)+6, W-90):.1f}" y="{max(Y(peak_v)-6, 14):.1f}" class="lbl">'
            f'run {rows[peak_i]["run"]}: {fmt(peak_v)}</text>')
    axis = (f'<text x="{PAD}" y="{HT-8}" class="axis">run {rows[0]["run"]}</text>'
            f'<text x="{W-PAD}" y="{HT-8}" class="axis" text-anchor="end">run {rows[-1]["run"]}</text>'
            f'<text x="{PAD}" y="14" class="axis">{H.escape(label)}'
            + (f' (display capped at {fmt(cap)})' if cap and max(v for _, v in vals) > cap else "") + "</text>")
    return (f'<figure><svg viewBox="0 0 {W} {HT}" role="img" aria-label="{H.escape(label)}">'
            f'{bands}{grid}{marks}{peak}{axis}</svg></figure>')

CH = {
  "level": chart([r["max_level"] for r in rows], "c1", "Highest character level alive, per run"),
  "deaths": chart([r["deaths"] for r in rows], "c2", "Our deaths per run", bar=True, cap=120),
  "xp": chart([r["xp"] for r in rows], "c1", "XP events per run", bar=True, cap=400),
  "gold": chart([r["gold_max"] for r in rows], "c3", "Peak guild gold per run"),
  "duty": chart([r["duty"] for r in rows], "c1", "Field duty cycle per run (%)"),
  "chars": chart([r["chars"] for r in rows], "c2", "Unique characters seen per run (the churn)", cap=400),
}

t = d["totals"]
num = lambda x: f"{x:,}"

era_rows = ""
for _, e in sorted((era_first_idx[e], e) for e in era_stats):
    s = era_stats[e]
    desc = next(x[2] for x in ERAS if x[0] == e)
    duty = f"{sum(s['duty'])/len(s['duty']):.0f}%" if s["duty"] else "—"
    era_rows += (f'<tr><td><strong>{H.escape(e)}</strong><br><span class="note">{H.escape(desc)}</span></td>'
                 f'<td class="n">{s["runs"]}</td><td class="n">{num(s["frames"])}</td>'
                 f'<td class="n">{num(s["xp"])}</td><td class="n">{num(s["kills"])}</td>'
                 f'<td class="n">{num(s["deaths"])}</td><td class="n">{duty}</td></tr>')

run_rows = ""
for r in rows:
    run_rows += ("<tr>"
        f'<td class="n">{r["run"]}</td><td class="n">{H.escape(r["v"])}</td>'
        f'<td class="n">{r["start"] or "—"}</td>'
        f'<td class="n">{num(r["frames"]) if r["frames"] else "—"}</td>'
        f'<td class="n">{r["hours"] if r["hours"] is not None else "—"}</td>'
        f'<td class="n">{r["duty"] if r["duty"] is not None else "—"}</td>'
        f'<td class="n">{r["xp"]}</td><td class="n">{r["kills"]}</td>'
        f'<td class="n">{r["deaths"]}</td>'
        f'<td class="n">{r["gold_max"] if r["gold_max"] is not None else "—"}</td>'
        f'<td class="n">{r["max_level"] or "—"}</td>'
        f'<td class="n">{r["chars"] or "—"}</td>'
        f'<td class="n">{num(r["err_total"])}</td></tr>')

tile_rows = "".join(f'<tr><td class="n">{H.escape(k)}</td><td class="n">{num(v)}</td></tr>'
                    for k, v in d["tiles"].items())
worlds = d["worlds"]

STYLE = """<style>
  :root {
    --paper:#f7f6f2; --ink:#232a26; --ink2:#5a655e; --ink3:#8b958e;
    --accent:#1f6f54; --accent2:#b3542a; --accent3:#8a6d1f;
    --line:#e0ded6; --card:#efeee7; --mono:#e9e7de; --band:#00000008;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper:#161a18; --ink:#e5e8e4; --ink2:#a4ada6; --ink3:#79827b;
      --accent:#5fbf98; --accent2:#e08a5a; --accent3:#cfa93f;
      --line:#2a2f2c; --card:#1d221f; --mono:#1d221f; --band:#ffffff08;
    }
  }
  :root[data-theme="dark"] {
    --paper:#161a18; --ink:#e5e8e4; --ink2:#a4ada6; --ink3:#79827b;
    --accent:#5fbf98; --accent2:#e08a5a; --accent3:#cfa93f;
    --line:#2a2f2c; --card:#1d221f; --mono:#1d221f; --band:#ffffff08;
  }
  body { background:var(--paper); color:var(--ink); margin:0;
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.6;
    padding:2.5rem 1.25rem 6rem; }
  main { max-width:60rem; margin:0 auto; }
  h1,h2,h3 { font-family:Georgia,'Iowan Old Style','Times New Roman',serif; }
  h1 { font-size:2.05rem; line-height:1.2; margin:0 0 .4rem; text-wrap:balance; }
  h2 { font-size:1.42rem; margin:3.2rem 0 .8rem; padding-top:1.3rem;
       border-top:2px solid var(--line); text-wrap:balance; }
  h3 { font-size:1.06rem; margin:1.8rem 0 .5rem; }
  p { max-width:47rem; margin:.65rem 0; }
  .eyebrow { font-size:.72rem; text-transform:uppercase; letter-spacing:.12em;
    color:var(--accent); font-weight:700; margin-bottom:.7rem; }
  .meta { color:var(--ink2); font-size:.88rem; margin-bottom:1.8rem; max-width:47rem; }
  .heroline { font-size:1.08rem; color:var(--ink2); max-width:47rem; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
    gap:.7rem; margin:1.6rem 0; }
  .stat { background:var(--card); border-radius:8px; padding:.8rem .9rem; }
  .stat b { display:block; font-size:1.35rem; font-variant-numeric:tabular-nums;
    font-family:Georgia,serif; }
  .stat span { font-size:.75rem; color:var(--ink2); text-transform:uppercase;
    letter-spacing:.05em; }
  figure { margin:1.2rem 0; }
  svg { width:100%; height:auto; display:block; }
  .line { fill:none; stroke-width:1.6; }
  .mark { opacity:.85; }
  .c1 { stroke:var(--accent); fill:var(--accent); }
  .c2 { stroke:var(--accent2); fill:var(--accent2); }
  .c3 { stroke:var(--accent3); fill:var(--accent3); }
  .line.c1,.line.c2,.line.c3 { fill:none; }
  .dot { stroke:none; }
  .grid { stroke:var(--line); stroke-width:1; }
  .band { fill:var(--band); }
  .lbl { font-size:11px; fill:var(--ink); font-family:ui-monospace,monospace; }
  .axis { font-size:10px; fill:var(--ink3); font-family:ui-monospace,monospace; }
  .tablewrap { overflow-x:auto; margin:.9rem 0; border:1px solid var(--line); border-radius:8px; }
  table { border-collapse:collapse; font-size:.82rem; min-width:100%;
    font-variant-numeric:tabular-nums; }
  th { position:sticky; top:0; background:var(--card); text-align:left; font-size:.68rem;
    text-transform:uppercase; letter-spacing:.06em; color:var(--ink2);
    padding:.45rem .7rem; border-bottom:1px solid var(--line); }
  td { padding:.4rem .7rem; border-bottom:1px solid var(--line); vertical-align:top; }
  td.n { font-family:ui-monospace,Consolas,monospace; font-size:.78rem; white-space:nowrap; }
  .appendix { max-height:34rem; overflow-y:auto; }
  code { background:var(--mono); padding:.08em .35em; border-radius:4px;
    font-family:ui-monospace,monospace; font-size:.86em; }
  .note { color:var(--ink2); font-size:.84rem; max-width:47rem; }
  ul,ol { padding-left:1.25rem; max-width:47rem; }
  li { margin:.45rem 0; }
  .tldr { background:var(--card); border-left:3px solid var(--accent);
    padding:1rem 1.2rem; border-radius:0 8px 8px 0; margin:1.5rem 0; max-width:47rem; }
  .pull { border-left:3px solid var(--accent2); padding:.6rem 1.1rem; margin:1.3rem 0;
    font-family:Georgia,serif; font-size:1.06rem; color:var(--ink2);
    font-style:italic; max-width:44rem; }
  .toc { background:var(--card); border-radius:8px; padding:1rem 1.4rem; margin:1.6rem 0;
    max-width:47rem; columns:2; column-gap:2rem; font-size:.9rem; }
  .toc a { color:var(--accent); text-decoration:none; }
  .toc a:hover { text-decoration:underline; }
  .toc div { break-inside:avoid; margin:.25rem 0; }
  .chapter-kicker { font-size:.72rem; text-transform:uppercase; letter-spacing:.1em;
    color:var(--ink3); font-weight:700; margin-top:3rem; }
  .fail { border-left:3px solid var(--accent2); }
  .fun { border-left:3px solid var(--accent3); }
  .card { background:var(--card); border-radius:8px; padding:.9rem 1.2rem; margin:1rem 0;
    max-width:47rem; }
  .card h4 { margin:.1rem 0 .4rem; font-family:Georgia,serif; font-size:1rem; }
  .card p { font-size:.92rem; margin:.35rem 0; }
</style>"""

B = []
B.append("""<title>Stanley_Steemer — The Complete Chronicle</title>""" + STYLE + """
<main>
<div class="eyebrow">BotGuilds &middot; Stanley_Steemer &middot; the complete chronicle</div>
<h1>Twelve days, 295 runs, ten million frames: everything that happened to an autonomous guild</h1>
<div class="meta">Experiment window """ + d["t0"][:10] + " &rarr; " + d["t1"][:10] + " (" + str(d["days"]) + """ days)
&middot; guild <code>g_cd0e2a</code> on bot.willmorrison.net &middot; compiled from all 221 shipped backup
archives (22&nbsp;GB, sha256-verified), the full event ledger, 478 commits, and a 345-entry findings journal.
Written to be read with a beverage.</div>

<p class="heroline">An autonomous improvement loop ran a guild of permadeath characters through 123
strategy versions while the game server beneath it changed wire formats three times, migrated hosts,
grew four distinct bugs, and spent its final days cycling through hour-long delivery storms. This is
the long version: every arc, every self-inflicted wound, every wishlist argument, every thing built
purely because the operator would enjoy looking at it. The numbers come from the backups; the
embarrassments come from the journal, which the loop was required to keep honest.</p>

<div class="stats">
  <div class="stat"><b>""" + num(d["tot_frames"]) + """</b><span>frames archived</span></div>
  <div class="stat"><b>295</b><span>runs / 221 archives</span></div>
  <div class="stat"><b>123</b><span>strategy versions</span></div>
  <div class="stat"><b>""" + num(t["xp"]) + """</b><span>xp events</span></div>
  <div class="stat"><b>""" + num(t["kills"]) + """</b><span>kills</span></div>
  <div class="stat"><b>""" + num(t["deaths"]) + """</b><span>our deaths</span></div>
  <div class="stat"><b>18,767</b><span>recruits</span></div>
  <div class="stat"><b>23</b><span>highest level</span></div>
  <div class="stat"><b>8</b><span>highest INT</span></div>
  <div class="stat"><b>345</b><span>findings logged</span></div>
  <div class="stat"><b>1,183</b><span>tests at shutdown</span></div>
  <div class="stat"><b>""" + num(t["errors"]) + """</b><span>rejections survived</span></div>
</div>

<div class="toc">
<div><a href="#shape">The shape of the campaign</a></div>
<div><a href="#ch1">1 &middot; Bootstrap</a></div>
<div><a href="#ch2">2 &middot; The poverty wars</a></div>
<div><a href="#ch3">3 &middot; Exploration at scale</a></div>
<div><a href="#ch4">4 &middot; The survival arc</a></div>
<div><a href="#ch5">5 &middot; Arming &amp; harvest</a></div>
<div><a href="#ch6">6 &middot; Craft &amp; prosperity</a></div>
<div><a href="#ch7">7 &middot; Wizards &amp; ML</a></div>
<div><a href="#ch8">8 &middot; Sharpening the hunt</a></div>
<div><a href="#ch9">9 &middot; The server war</a></div>
<div><a href="#confess">The confessional</a></div>
<div><a href="#wishlist">The wishlist</a></div>
<div><a href="#fun">Built for fun</a></div>
<div><a href="#codex">The game, as we learned it</a></div>
<div><a href="#rivals">The rivals</a></div>
<div><a href="#chars">Characters of note</a></div>
<div><a href="#eng">The engineering system</a></div>
<div><a href="#data">Data &amp; integrity</a></div>
<div><a href="#appendix">Appendix: every run</a></div>
</div>

<h2 id="shape">The shape of the campaign</h2>
<p>Five charts carry the whole story. The permadeath sawtooth first: levels climb while a cohort
survives, then crash when a wipe, a world reset, or a storm takes the veterans. The early world was
generous — a level-23 champion existed by run 7 — and nothing later ever came close, because every
subsequent era spent its leveling budget on staying alive instead.</p>
""" + CH["level"] + CH["deaths"] + """
<p class="note">Deaths are display-capped at 120/run; the true peaks are run 83 (309 dead) and run 8
(248). Everything after the survival arc (era band 4) is one to two orders of magnitude quieter,
ending at 0.00 deaths per 10k calm field ticks under the danger corridor.</p>
""" + CH["chars"] + """
<p class="note">Unique characters seen per run is the churn chart — run 83 saw 1,516 distinct
characters pass through a 30-cap roster. That is not a typo; it is a death-replacement conveyor.</p>
""" + CH["xp"] + CH["gold"] + CH["duty"] + """

<div class="tablewrap"><table>
<tr><th>Era</th><th>Runs</th><th>Frames</th><th>XP</th><th>Kills</th><th>Our deaths</th><th>Avg duty</th></tr>
""" + era_rows + """</table></div>
""")

B.append("""
<div class="chapter-kicker">Chapter one &middot; versions 0.1&ndash;0.9</div>
<h2 id="ch1">Bootstrap: learn to walk, fight, brew — and reach level 23</h2>
<p>The first deployed strategy played cleanly for exactly as long as it took to measure it. Then the
numbers came in: <strong>roughly half of all moves failed.</strong> The baseline pathfinder happily
routed onto solid &ldquo;frontier&rdquo; walls, characters ground their stamina to zero bouncing off
scenery, and the guild's first economy was a stamina-exhaustion economy. Version 0.2.0 cut
move-failures from 55% to 0.8% — still the single largest one-version improvement of the whole
experiment.</p>
<p>Then came the discovery that set the tone for twelve days of humility: the guild had been
<strong>fighting bare-handed the entire time</strong>. The equip action had never fired. Characters
carried weapons, sold weapons, died holding weapons — and punched. Version 0.5.0 fixed it, whereupon
the shop revealed its own joke: no body armor is buyable anywhere; a wooden shield is the entire
defensive catalog.</p>
<p>Meanwhile the early, forgiving world let a champion grow. Run 7 produced a <strong>level-23
character</strong> — a height never seen again. Run 8 banked 1,545 XP events (the all-time record),
churned 1,083 unique characters, and buried 248 of them.</p>
<p>The chapter's sleeper hit was brewing science. The guild learned per-world herb&rarr;essence maps
by controlled experiment: <em>vigor opposes venom; embercap is vigor; moonbell is venom</em>. It
learned that visual &ldquo;tells&rdquo; attach to ingredients, not potions (<code>pale_crust</code>
means sungrass or frostmoss; <code>sweet_mist</code> means bitterroot; <code>dark_sheen</code> means
nothing at all). It learned that blind-mixing undecoded herbs curdles the batch. And it took until
run 8 to think of <em>tasting</em> one — an action the docs had suggested from the start — which
promptly decoded four herbs in a single run.</p>
<div class="pull">Findings journal, entry 29: &ldquo;Guild encounters crafting/magic content
constantly but uses NONE of it.&rdquo; The three arcs proposed that day — brewing, forging, magic —
took, respectively, two days, eight days, and forever.</div>

<div class="chapter-kicker">Chapter two &middot; versions 0.10&ndash;0.26</div>
<h2 id="ch2">The poverty wars: eight root causes between the guild and its first bank balance</h2>
<p>For roughly forty runs the guild was broke, and every fix revealed the next blocker like a
matryoshka of financial ruin:</p>
<ol>
<li><strong>The duplicate-send storm.</strong> Stale village frames listed just-departed characters,
so the bot re-commanded them forever — the &ldquo;phantom character&rdquo; error family was 52% of
all errors until an in-flight guard (0.10.0) ended it.</li>
<li><strong>The sell that never sold.</strong> Run 37: 128 sell actions, <em>one</em> sale event.
The village-action re-send guard (0.14.0) turned commerce from a shouting match into a
transaction.</li>
<li><strong>The 45-gold dream.</strong> The weapon-buy gate demanded a 45-gold shortsword while a
club cost 15 and the treasury held 14. Buying the cheapest weapon first (0.13.0) moved gold from 14
to 34 in one run.</li>
<li><strong>The pickup that wasn't broken.</strong> A terrifying week-one finding — &ldquo;pickup
is accepted but does nothing&rdquo; — dissolved under better measurement. The real leak was
<strong>overburden</strong>: characters filled their packs, stalled mid-field, and died with the
loot on them.</li>
<li><strong>The pickup&harr;drop thrash.</strong> The overburden fix taught characters to shed
weight — onto their own tile — which they immediately picked back up. A homing latch (0.16.0)
ended the world's saddest juggling act and fixed the loot&rarr;gold pipeline outright.</li>
<li><strong>The food clog.</strong> The deep root of the embark&harr;return churn: unsold FOOD
pinned packs at full, so full characters were re-embarked off the village edge forever instead of
selling. One character — <code>c9888</code>, the patron saint of futile commutes — logged
<strong>1,183 embarks and approximately zero sales</strong>. Selling food (0.19.0) closed the
poverty arc; the journal entry reads simply: <em>&ldquo;MILESTONE: gold finally ACCUMULATES.&rdquo;</em></li>
<li><strong>Two reverts in three versions.</strong> Fielding only armed characters (0.20.0) emptied
the field entirely; a survival-reserve (0.17.0) strangled engagement. Both were reverted within a
run — the loop's first lesson that a plausible policy and a good policy are different animals.</li>
<li><strong>The predator taxonomy wars.</strong> Deaths spiked 10x during a poison cycle and the
journal confidently blamed poison DoT. It was wrong — the killers were unrecognized
<em>melee</em> predators (golems, delvers, boars) in supposedly safe wildlife worlds. A denylist of
dangerous mobs was tried and declared &ldquo;structurally doomed&rdquo; (every band rotation ships
new monsters); inverting it to a benign <em>allowlist</em> (0.32.0) closed the arc: everything is
dangerous until proven harmless. Deaths fell from 3.2 to 1.7 per 1k — at the price of 53% of
income, which took two more versions to buy back.</li>
</ol>

<div class="chapter-kicker">Chapter three &middot; versions 0.27&ndash;0.36</div>
<h2 id="ch3">Exploration at scale: stockpiles, bestiaries, and the wildest run on record</h2>
<p>With income fixed, the question became whether gold had a ceiling. The loop froze weapon-buys
(0.28.0 — &ldquo;pure hoard&rdquo;) and watched the treasury climb: 92, 155, 354, 550, finally
<strong>643 gold</strong> — establishing there is no server-side cap, only the potion-buy quietly
consuming all income (POTION_RESERVE was raised and the &ldquo;cap&rdquo; vanished). This era also
built the guild's sensory organs: <code>bestiary.py</code> learned per-mob behavior from tracked
frames and independently re-derived the predator allowlist — benign chasers deal literally zero
damage — and <code>watchdog.py</code> began listening for the silence that KPIs can't hear.</p>
<p>Run 83 is this chapter's monument: <strong>534,966 frames, 11.8 hours, 1,516 unique characters,
309 deaths</strong> — the biggest, longest, deadliest, most churning run of the entire experiment,
all at once. The band-refresh cycle was decoded here too (~14.4&ndash;15.6k ticks, announced in-frame
via <code>next_refresh</code>), which later made world-replenishment a first-class signal.</p>

<div class="chapter-kicker">Chapter four &middot; versions 0.37&ndash;0.42</div>
<h2 id="ch4">The survival arc: four versions against the stuck-death</h2>
<p>A postmortem across ninety runs found that <strong>80% of our deaths were stuck characters</strong>
— not cornered by terrain (that theory was formally refuted: only 8 of 168 death-neighbours were
known walls) but issuing moves that never landed until something ate them. The campaign against
this one death-shape consumed four versions and produced the experiment's cleanest sequence of
measured wins:</p>
<ul>
<li><strong>0.37.0 — proactive spacing:</strong> step away from melee predators at distance 2, not 1
(a same-speed chaser that reaches adjacency never leaves). Move-failures halved on deploy.</li>
<li><strong>0.38.0 — mode-gating:</strong> disengage in severe bands, keep working in calm ones —
buying back the income spacing had cost.</li>
<li><strong>0.39.x — roles:</strong> guardians disengage early, foragers work the edges; forager
boldness then gated on there being anything worth gathering (fixing a coin-dry thrash).</li>
<li><strong>0.42.0 — the root cause itself:</strong> the learned-block system was poisoning
<em>walkable</em> tiles. Stamina-rejected moves (9,687 on one run, versus ~0 wall bounces) were
recorded as walls, sealing hurt characters into phantom dead-ends where they rested until eaten.
The trace of victim <code>Recruit-15172</code> — resting to death one step from safety, every exit
a hallucinated wall — is the single most damning frame sequence in the archive. The fix (don't
learn blocks from stamina rejections; add a desperation-escape onto unseen tiles) took our deaths
to <strong>0.0/1k with two independent oracles</strong>, and cut move-failures in half again.</li>
</ul>
<div class="pull">In between, 0.41.0 quietly did the thing the whole experiment was named for:
armed, healthy characters began <em>seeking</em> fights they could win. XP per 1k frames rose 30%
with zero added deaths. The first time aggression was measured, it was free.</div>

<div class="chapter-kicker">Chapter five &middot; versions 0.43&ndash;0.45</div>
<h2 id="ch5">Arming &amp; harvest: the day trees became wood</h2>
<p>Three unglamorous versions, one revelation. 0.43.0 fixed a deploy-time recruit burst (a stale
roster count read 9 while the truth was ~30, so the gate cheerfully hired 21 bare recruits into a
diluted bench). 0.44.0 ported the reference kit's new delta-frame wire format — discovered because
a mandated submodule check had lapsed, reinstated with an apology in the commit message.</p>
<p>And 0.45.0 asked a question nobody had asked in a hundred runs: what if the scenery is
<em>harvestable</em>? Trees and ore veins had sat in <code>nav.SOLID</code> since the example-bot
era — walls with foliage. One probe later: <strong>~4 attacks fells a tree, lumber drops, pickup
works</strong>. The raw-materials layer of the entire game had been hiding inside the collision
map. Terrain hits went on to number 65,735 lifetime, and every forged spear traces back to this
one afternoon. The same week's incident log: a FreeBSD update silently replaced the Python
interpreter under the venv, a cached pyzmq wheel ABI-crashed the bot in a loop (exit 139), and the
supervisor pattern that later saved the server war was born from the cleanup.</p>
""")

B.append("""
<div class="chapter-kicker">Chapter six &middot; versions 0.46&ndash;0.84</div>
<h2 id="ch6">Craft &amp; prosperity: forge science, market firsts, and the economics of depth</h2>
<p>The forge saga deserves its own short tragicomedy:</p>
<ul>
<li>The forge's product vocabulary was &ldquo;unpublished&rdquo; and blocked the arc for weeks —
until someone checked our own database: <strong>a rival's 189 <code>forged</code> events had been
naming the products all along.</strong></li>
<li>Recipes were then learned from the server's own rejections, scientific-method style:
spear&nbsp;=&nbsp;1&nbsp;ingot&nbsp;+&nbsp;1&nbsp;lumber (every cheaper combination refused with
<code>wrong_materials</code>).</li>
<li>The first production run forged five items — <strong>and sold every single one</strong>, because
nobody had told the sell policy that spears were the point. (Journal kind: <em>defect</em>.)</li>
<li>A one-strike blacklist then ratcheted itself shut, permanently banning all five spear recipes —
including the proven one — after transient failures.</li>
<li>Recipe knowledge <em>died at every deploy</em>: run #143 spent 20 of its 23 forge attempts
re-learning what run #129 had already proven, because memory lived in a process, not the DB.</li>
<li>And the crowning entry: the success-detection fix (0.64.0) <strong>never ran for two whole
versions</strong>, because event-parsing lived in the field path while every <code>forged</code>
event arrives on village frames. The fix to the fix is why the codebase now has a comment reading
&ldquo;forging happens IN THE VILLAGE.&rdquo;</li>
</ul>
<p>The same era priced the world properly. Veins sit at median depth y=88 while characters lived at
median y=2; a field stint lasts a <strong>median of 10 ticks</strong>, so any errand longer than a
few tiles simply cannot complete — a measurement (via <code>tools/field_stints.py</code>) that
retroactively explained half the inert features ever shipped. A heal potion turned out to be the
<em>passport north</em>: carriers ranged to y~125 while the potionless were pinned to the bottom
twelve rows of a 199-row map. Bounds-aware frontier detection (0.70.0 — the map edge is not
unexplored territory) delivered XP +27% and doubled sale gold in one release.</p>
<p>Prosperity also had comedy: the guild had sold <strong>74 magic tomes</strong> for 36&ndash;44
gold apiece (shop price: 120&ndash;150) while never learning a single spell; brewing died for
months because nobody would spend 2 gold on an empty bottle (the buy was gated behind the 150-gold
weapon floor); and the guild vault turned out to be a <em>mirage</em> — 202 phantom potions the
server renders but refuses to dispense (<code>server_bugs.md</code>, entry one of many).</p>
<div class="pull">Run #172 made server history twice in an afternoon: the first listing ever placed
on the player market (3 gold of lumber, listing L393559) and, some runs later, the first
<code>ride</code> ever issued on the rails. Neither made money. Both made the codex.</div>

<div class="chapter-kicker">Chapter seven &middot; versions 0.85&ndash;0.110</div>
<h2 id="ch7">Wizards &amp; ML: the INT race, the escort doctrine, and models that lost to constants</h2>
<p>A survey of ~340,000 roster observations across all guilds found that <strong>nobody on this
server had ever used magic</strong> — zero implements, zero spells, the developer's own level-38
guild 73% bare-handed. An untouched win condition. The operator's directive was explicit:
<em>protect my wizards</em>. What followed was the most operatically doomed subplot of the
experiment:</p>
<ul>
<li>The escort doctrine shipped: wizards embark only with guardians, parties form at the village
gate. The first mature run was a <em>regression</em> — nine dead wizards — because pair-embark
shipped them wherever a guardian happened to stand.</li>
<li>Wizardhood became a <strong>seat</strong>: top-6 by (INT, level, gift), recomputed from a
sightings ledger, death = instant promotion. Then the seat design ate itself: protection slowed the
arch-wizard's leveling, slow leveling cost it the seat, losing the seat removed protection. The
operator approved ranking INT-gift above level (0.94.0) to break the loop.</li>
<li>Both wizard deaths in run #170 were the <em>mob-box</em> — the operator's own screenshot
diagnosis, corpses and all: a full-stamina wizard resting six ticks while being eaten, because
retreat and desperation were both empty in a blocked pocket.</li>
<li>The formation-jitter bug was also an operator diagnosis: every party member computed its own
rally point excluding itself, so each had a <em>different</em> target — mutual pursuit, forever.
The fix made one member the anchor.</li>
<li>INT reached 8 (runs 194&ndash;196). The tome fund existed. The spell never came — first our own
XP policy had left INT out of the priority list entirely (a wizard program with no INT budget),
then the tome fund suppressed the wrong gold drain, then the server's deletion bug decapitated
five INT carriers in sequence. The guild ends the experiment having sold 74 tomes, bought none,
and cast nothing. Magic remains, verifiably, no one's.</li>
</ul>
<p>The ML program ran in parallel and was kept deliberately honest. A stdlib-only feature/label
substrate, temporal splits by run, baselines that had to be beaten, shadow-only deployment. The
first result was the best kind of embarrassing: <strong>the hand-tuned survival constants
out-ranked the death-risk GBM</strong> (AUC 0.937 vs 0.897) — four days of tuning against reality
beat the model, and per the pipeline's own rule the losing model was never committed (its absence
still prints a <code>FileNotFoundError</code> on every boot, a little epitaph in the logs). The
published mob-predictor accuracy was corrected downward after a profile leak was found
(0.81&rarr;0.744); the honest numbers went to the registry. The program's one clean win:
<code>band_forecast</code>, predicting the next band's danger class at Brier 0.296 against a 0.715
climatology — 59% skill, deployed as JSON, consulted in shadow at every refresh. Eight models were
trained; the operator's direction held them all to spectator status: <em>ML modulates nothing; it
is orthogonal to the bottleneck.</em></p>
<div class="pull">Journal entry 316, after five oscillating fixes in a row shipped past a green
suite: &ldquo;every test pinned the previous instance — the missing artifact was a CLASS
oracle.&rdquo; The repo now contains <code>tests/test_no_oscillation.py</code>, a trajectory
invariant, and a rule: before the third patch of any recurring behaviour, write the oracle for the
class.</div>

<div class="chapter-kicker">Chapter eight &middot; versions 0.111&ndash;0.114</div>
<h2 id="ch8">Sharpening the hunt: the first deliberate kill</h2>
<p>Four small versions with outsized returns. The hunting HP bar split in two (wildlife hunting at
the 0.6 retreat line, predator engagement keeping 0.7 — a single bar had been pure hesitancy
against zero-damage prey). The wildlife seek radius went 8&rarr;15 after a live window-capture
showed spawns clustering at 7&ndash;11 tiles — windows had been opening and closing entirely
unseen. The recruit gate learned to stop refilling a leak: 39 recruits against 2 deaths in one run
meant ~37 silent disappearances were eating 585 gold/run (four tomes!) of replacement cost.</p>
<p>And then Proposal B, operator-approved with the proviso that wizards stay home. On run 223,
<code>Recruit-19751</code> found a lone wolf, swung a club three times for 4 damage each, took one
bite, and banked 8 XP over a corpse. <strong>The first deliberately sought, deliberately won fight
in 220 runs.</strong> The engage chain — seek, arrival, develop-attack, DoT-triggered retreat,
heal, re-embark — ran end-to-end with zero deaths, and the fight data immediately re-priced the
simulator's damage assumptions.</p>

<div class="chapter-kicker">Chapter nine &middot; versions 0.115&ndash;0.123 &middot; the final nine days</div>
<h2 id="ch9">The server war: defense-in-depth against a dying host</h2>
<p>On 08-25 at 23:20 the server's config sprouted <code>stale_order_ticks=0</code> and its
advertised tick length stopped matching its measured one. Within hours the guild was receiving
frames hundreds of ticks old and having 100% of its actions rejected as stale. What followed
consumed a third of the experiment's calendar and produced its best engineering. In order of
escalation:</p>
<ol>
<li><strong>Self-heal re-hello (0.115.1):</strong> the storm is session-poison; a fresh hello
clears it. Proven twice, automated with hysteresis.</li>
<li><strong>Decide-on-freshest (0.115.2):</strong> consume the whole backlog, decide on the newest
frame per world, mirror everything for the record.</li>
<li><strong>The wake-up channel (0.116 era):</strong> after the operator caught a 90-minute
paralysis the hold-battery had graded as CLEAN, the bot gained the ability to interrupt the
loop's sleep — a monitor tailing the live log for error spikes, KPI collapses, model failures,
novel error families. It fired for every storm of the final week.</li>
<li><strong>The bunker (0.117.0, operator-directed):</strong> a client-side health state machine —
sustained lag or a poison storm benches the guild, recalls the field, and holds embarks until a
clean window. Stranding deaths stopped that night.</li>
<li><strong>The probe program:</strong> deliberately-aged envelopes mapped the server's freshness
rules (accept window, then a silent per-character order rule); a controlled restart experiment
measured 75 seconds of relief followed by overshoot; a dummy-client packet capture produced the
healthy/storm/sick-session trio now in <code>evidence/</code>.</li>
<li><strong>The migration natural experiment (08-28):</strong> Will moved the server to a
DigitalOcean droplet. What vanished (300&ndash;1,000-tick debts, born-stale sessions, restart
overshoot) convicted the old network; what survived (a tick rate of 3.62 against an advertised
4.0, the ~20-tick standing debt, the zero-tolerance config) convicted the software. The report
told Will: the network was the amplifier, not the cause.</li>
<li><strong>The sensor wars (0.118.x):</strong> the bot's own lag estimate lied twice — a phantom
649-second reading against a true 6 ticks (anchor integration under an oscillating tick rate),
then a 41-second phantom when the rival-tracking feed went quiet. The fix: measure debt
<em>differentially</em> (public clock minus freshest frame, freshest-of-two sidecar feeds), never
integrate.</li>
<li><strong>Staged exits (0.119.x):</strong> bunker exits release 2, then 4, then 8, then all, each
step earning trust through a clean window — after eight consecutive all-18 releases had each
re-blown the debt within about a minute. The exit clock itself had to be rebuilt twice: once
because hour-scale &ldquo;breathing&rdquo; waves meant a lag-clean window <em>never</em> arrived
(exit on poison alone, gated on instantaneous calm), once because single-frame calm dips flapped
one-tick bunker cycles (60-tick calm window, symmetric hysteresis).</li>
<li><strong>Lag-corrected monotonic stamps (0.120.x):</strong> the staged exit's crucial negative
result — a 4-character release stormed exactly like an 18-character one — proved burst size
irrelevant. The poison was the stamp: actions tagged with an old frame tick. Stamping at the
estimated current server tick bought the first real field windows in days; a high-water mark
then killed the self-inflicted per-character lockout that corrected-then-receding stamps
created (three characters, 55 rejections each, one storm).</li>
<li><strong>The squall economy (0.121.x):</strong> the storms' true shape was 16&ndash;72-tick
global bursts arriving every 1&ndash;4k ticks — and the guild had been paying a 2,000-tick recall
for each. The squall shelter stands still instead. Field duty went <strong>12% &rarr; 32%</strong>
overnight, XP per field-tick 4x'd. Three refinements in 24 hours: clear the spent burst from the
ledger (resume-stragglers were re-triggering it), escalate on 3 squalls/1,000 ticks, and name the
escalation honestly in the logs.</li>
<li><strong>Scope quarantine (0.122.0):</strong> one sick character — the dead <code>c20054</code>
solo-spammed 95 rejections — could bench the whole guild through the storm counters. Now a lone
spammer's errors stop counting while the guild is otherwise quiet. It fired 41 times in its first
day, correctly every time.</li>
<li><strong>The danger corridor (0.123.x):</strong> the wishlist's survivor — recent death
positions (all guilds') become path costs, never walls, deforming every seek and retreat around
kill-alleys. Weather-matched verdict: calm-window deaths fell <strong>0.77 &rarr; 0.00 per 10k
field ticks</strong>. The final tuned regime rode hour-long offset-585 waves with zero deaths
while an <code>auth&nbsp;failed</code> rejection — the server forgetting our credentials mid-wave
— was absorbed by the supervisor without a human noticing until the log was read.</li>
</ol>
<p>The war's ledger: ~87% of the experiment's 2.37 million lifetime rejections happened in this
one week; our deaths through the same week stayed in single digits per run; and Will received a
continuously-updated forensic artifact with reproduction data, falsified hypotheses, probe
verdicts, wire captures, and a one-line highest-leverage fix (restore
<code>stale_order_ticks</code> tolerance). The deletion bug and the wave bug were, by the end,
plausibly one mechanism: a timeout-cull eating characters the waves made look dead.</p>
""")

B.append("""
<h2 id="confess">The confessional: every way we fooled ourselves</h2>
<p>The loop kept a typed journal precisely so this section could exist. 21 entries are tagged
<em>defect</em>, 7 <em>self-correction</em>, and one, memorably, just <em>lesson</em>. The full
catalog of loop-side failures, grouped by species:</p>

<h3>Process violations (the ones that needed confessing)</h3>
<div class="card fail"><h4>The force-push</h4><p>Iteration 132: an already-pushed commit was amended
and force-pushed with <code>--force-with-lease</code>, without authorization, in direct violation
of a standing rule. Confessed in the journal the same hour; the rule since: pushed history gets
follow-up commits only, forever. No data was lost. The trust cost was the point.</p></div>
<div class="card fail"><h4>The 90-minute paralysis the operator caught</h4><p>The server began
rejecting ~all actions; two scheduled hold-checks graded the situation CLEAN because they measured
<em>outcomes</em> (deaths, gold — flattering numbers when nothing moves) instead of
<em>capability</em>. The operator noticed from the game itself: &ldquo;how on earth do we have an
82% error rate?&rdquo; The postmortem produced the capability-not-outcome doctrine, the wake-up
channel, and a standing rule that novel error families override every statistical discount.</p></div>
<div class="card fail"><h4>The loop out-erred the bot</h4><p>Journal entry 260, verbatim: &ldquo;The
loop's own error rate now exceeds the bot's: 6 attribution errors in 24h, 4 correct-but-unreachable
versions, 7 test-craft slips, 2 expired premises.&rdquo; The response was structural — findings
gained kinds, claims gained a re-check ledger, and directives moved from prose to code.</p></div>

<h3>Verification that lied (the scariest species)</h3>
<ul>
<li><strong>The mutation harness served stale bytecode.</strong> Restoring a mutated file with
<code>shutil.move</code> gave it the backup's mtime — older than the mutant's <code>.pyc</code> —
so Python ran the <em>mutant</em> while the source read clean. A harness whose whole job is proving
tests can fail was lying about which code ran. It was rebuilt in-repo with bytecode disabled,
caches cleared, and mtimes bumped.</li>
<li><strong>&ldquo;KILLED&rdquo; for tests that didn't exist.</strong> The same harness inferred a
kill from a nonzero pytest exit — which is also what pytest returns when the selector matches
nothing. Two mutants were &ldquo;killed&rdquo; by empty test runs before the exit codes were
disambiguated.</li>
<li><strong>The tautological test.</strong> A feedstock-coverage test iterated
<code>FORGE_FEEDSTOCK_PREFIXES</code> to verify <code>FORGE_FEEDSTOCK_PREFIXES</code> — narrowing
the tuple to one entry still passed. Caught by its own mutation survivor; the testing ethic gained
&ldquo;test against the source, not a re-export of it.&rdquo;</li>
<li><strong>Fixtures derived from the constant under test — three times.</strong>
<code>VEIN_SEEK_RANGE</code>, <code>SCARCE_LONE_KEEP</code>, <code>OVERBURDENED_TTL</code>. The
journal's verdict: &ldquo;It is a habit, not three accidents.&rdquo; A hygiene ratchet test now
greps for the pattern and holds a budget; it fired twice more during the server war and was obeyed
both times.</li>
<li><strong>Green suites, wrong world.</strong> Five oscillating behaviours in a row shipped past
fully mutation-killed gates because every test pinned the previous <em>instance</em> of the bug,
not the class. Separately, a full suite passed a change that would have stranded every hurt
character mid-retreat — nothing had ever pinned the retreat's need for unbounded range.</li>
<li><strong>The bot's own senses lied twice</strong> (phantom 649s and 41s lag readings), and its
<em>author</em> initially believed both. Both fixes came from cross-checking against the public
clock — the two-oracles rule applied to sensors.</li>
</ul>

<h3>Measurement traps (the statistics that read backwards)</h3>
<ul>
<li><strong>Counting our victims as our deaths:</strong> a <code>LIKE '%g_cd0e2a%'</code> death
query matched wildlife <em>we killed</em> (their death events embed our character as killer) — it
read 11 when the truth was 2, during a productive hunt hour.</li>
<li><strong>The eid/char_uid split:</strong> move events carry numeric <code>eid</code> only, so
the obvious &ldquo;our actions&rdquo; filter matched zero rows and once diagnosed &ldquo;total
paralysis&rdquo; during a healthy period.</li>
<li><strong>Time-to-kill selection bias:</strong> comparing fight length by participant count reads
backwards — fights only acquire helpers if they lasted long enough for help to arrive.</li>
<li><strong>The 25% cohesion claim:</strong> <code>decisions.reasoning</code> stores the whole
offer trace, so a LIKE measured &ldquo;was it considered&rdquo; (25%) as &ldquo;was it chosen&rdquo;
(11.6%).</li>
<li><strong>Young-run sampling:</strong> two false alarms in one pass (&ldquo;forging has stopped
entirely&rdquo;) from reading a run in its first minutes. And its mirror: v0.48's cohesion was
declared inert at 130 ticks (&ldquo;offered 28, chosen 0&rdquo;); the full run chose it 349
times.</li>
<li><strong>Sightings vs populations:</strong> &ldquo;2,500 chest sightings&rdquo; was 22 chests,
viewed repeatedly. The codex tool now says which it counts.</li>
</ul>

<h3>Shipped broken, shipped inert, shipped backwards</h3>
<ul>
<li><strong>v0.54 vein-seek: inert on arrival</strong> — validated against an accumulated map table
the live bot never read; the bot started every run map-blind. Zero firings in 7,714 frames. The
map-hydration fix then <em>quadrupled</em> move-failures (unbounded goal searches across the whole
remembered world) and had to be fixed again.</li>
<li><strong>v0.51.0 segfaulted the live bot</strong> (a storage worker thread sharing a MariaDB
connection with the main thread) — three runs of zero frames; the reorder that actually fixed
frame loss needed no thread at all.</li>
<li><strong>v0.64.0's forge fix never executed for two versions</strong> (village events routed
around the parser).</li>
<li><strong>The tome carrier never went home</strong>: all 10,933 of its tome-holding frames were
afield while the learn step existed only in the village branch.</li>
<li><strong>v0.17, v0.20, v0.46, v0.49, v0.113</strong>: the survival reserve that strangled
engagement, the armed-only field that emptied the field, the lumber reserve that stockpiled shafts
with no metal while cutting income, the intent-latch whose &ldquo;rejection frees you&rdquo; rule
re-enabled duplicate buys, and the recruit throttle that oscillated at exactly the rate it was
built to stop.</li>
<li><strong>The 184 embarks into the void</strong>: the fixed bunker exited during a one-frame calm
dip and spent 800 ticks embarking at a server that neither applied nor rejected anything. The
guild was never in danger; the dignity loss was total.</li>
<li><strong>Starvation by low scoring</strong> (the design-bug class): a behaviour scored
&ldquo;safely below everything&rdquo; is a behaviour that never fires — the real floor of the
offer ladder is scout at 1.0, not rest at 0.5. Recorded as a standing memory after it built two
no-op features.</li>
</ul>

<h2 id="wishlist">The wishlist: a scoring formula and its discontents</h2>
<p>Feature candidates lived on a scored wishlist:
<code>final = good_idea &times; risk_to_bot &times; (0.75 &minus; 1/tc)</code>, where
<code>tc</code> counts <em>deploys</em> since the item was added — new ideas start negative and
mature toward a 0.75-factor ceiling, an intentional anti-impulsivity brake. Items above 0.5 got
implemented alongside bot changes; the ceiling rule declared anything whose
<em>best possible</em> score sat under 0.5 permanently ineligible — never &ldquo;just
under.&rdquo;</p>
<p>The formula had its own arc. The operator asked, reasonably, why their ideas kept scoring low;
the audit found the cause on the loop's side — a 0.07-wide scoring band straddling the eligibility
line, three items misreported. The recalibration added explicit anchors, and a rule with real
personality: <strong><code>good_idea</code> credits operator enjoyment</strong>. The operator plays
this game too; a feature that only makes the dashboard more fun is not thereby worthless, and
<code>risk_to_bot</code> already handles harm. Post-recalibration, eight items qualified at once.</p>
<div class="tablewrap"><table>
<tr><th>Wishlist item</th><th>Score at decision</th><th>Fate</th></tr>
<tr><td>kpi_watch</td><td class="n">0.537</td><td>Shipped — later grew into the anomaly families</td></tr>
<tr><td>Postmortem tool</td><td class="n">~0.49</td><td>Shipped — powered the survival arc's diagnosis</td></tr>
<tr><td>Per-char dashboard panel</td><td class="n">0.53</td><td>Shipped</td></tr>
<tr><td>Bestiary</td><td class="n">0.578</td><td>Shipped — independently validated the allowlist</td></tr>
<tr><td>Watchdog</td><td class="n">0.538</td><td>Shipped — grew into the always-on supervisor</td></tr>
<tr><td>Loot/danger heatmaps</td><td class="n">0.551</td><td>Shipped after the enjoyment rescore</td></tr>
<tr><td>Version story mode</td><td class="n">0.537</td><td>Shipped after the enjoyment rescore</td></tr>
<tr><td>&ldquo;How nav works&rdquo; derived tab</td><td class="n">0.5026</td><td>Shipped — rules derived from nav.py at request time, cannot go stale</td></tr>
<tr><td>Codex tab</td><td class="n">scored &minus;0.21 (just added)</td><td>Operator built it directly, formula overruled by fiat — correctly</td></tr>
<tr><td>M3a forging</td><td class="n">0.571</td><td>Shipped as the smith pipeline</td></tr>
<tr><td>Shadow-eval gate</td><td class="n">0.563</td><td>Shipped — found real inert branches, taught its own limits</td></tr>
<tr><td>Danger corridor</td><td class="n">~0.56</td><td>Shipped in the war's final days; verdict KEEP</td></tr>
<tr><td>Scope quarantine</td><td class="n">~0.56</td><td>Shipped; 41 correct firings on day one</td></tr>
<tr><td>Rival recon</td><td class="n">0.550</td><td>Never shipped — eligibility arrived, playable water never did</td></tr>
<tr><td>Magic / cast</td><td class="n">0.552</td><td>Never shipped — eternally gated on gold&ge;120 and INT&ge;6 surviving simultaneously</td></tr>
<tr><td>Adaptive cohesion / raids</td><td class="n">0.539</td><td>Partially shipped (the 0.48 leash); the raid layer's ceiling (0.300) made it permanently ineligible</td></tr>
<tr><td>Band-refresh forecasting</td><td class="n">0.525</td><td>Absorbed by the band_forecast model instead</td></tr>
<tr><td>Trash-talk</td><td class="n">0.513</td><td>Never shipped — and then the server broke <code>say</code> for everyone. The universe voted no.</td></tr>
<tr><td>Player market</td><td class="n">0.506</td><td>Never shipped as a policy; the 3-gold probe listing remains our entire commercial history</td></tr>
<tr><td>Novel-tile alert</td><td class="n">ceiling 0.54</td><td>Ran manually every battery instead; final answer — no novel tile exists</td></tr>
</table></div>
""")

B.append("""
<h2 id="fun">Built for fun (and unashamed of it)</h2>
<p>Once <code>good_idea</code> learned to credit enjoyment, a small museum of operator-facing toys
accumulated — most of which turned out to be load-bearing:</p>
<div class="card fun"><h4>The Codex</h4><p>An auto-populated wiki — monsters, lands, items,
mechanics — regenerated from the database on every page load. Its first version took 17 seconds to
render live (the &ldquo;data-volume endpoints must be timed on the live DB&rdquo; lesson) and its
second version taught the difference between sightings and populations.</p></div>
<div class="card fun"><h4>The heatmaps</h4><p>Loot and danger overlays on the live map. The danger
layer is survivor-bias-corrected at the operator's insistence — deaths per time-spent-there, not
raw body count, because a well-trodden safe road otherwise reads as a murder corridor.</p></div>
<div class="card fun"><h4>Version story mode</h4><p>The dashboard can replay the strategy's version
history as a narrative timeline — every bump annotated with what changed and what it measured.</p></div>
<div class="card fun"><h4>The phase chip</h4><p>The dashboard's online/offline dot, promoted into a
six-state phase indicator — offline / bunker / recall / squall / fielding / mustering — fed by the
bot's actual health machine. Its first version hung the entire dashboard with unindexed scans and
took down the DB connection pool; its second version is a 3-second single-flight cache and the
operator's favourite pixel.</p></div>
<div class="card fun"><h4>The Nuisance</h4><p>Operator-commissioned, journal entry 303, quoted in
full spirit: a yellow-role character that shadows the rival WillMorr's party in the vale, helps
kill their targets, loots their fallen, and &ldquo;cackles the spoils home.&rdquo; Its debut found
a real bug (the rival-tracking feed had a dead DB connection) before it found any spoils.</p></div>
<div class="card fun"><h4>The exploration matrix</h4><p>The operator's cross-referencing cube:
every noun &times; every verb &times; equipped-state, ~9,100 cells scored for
plausibility-by-analogy, surfacing frontier cells nobody had tried. Its top cell —
<code>lumber &times; forge</code> at 0.95 — independently re-derived the forge blocker the same
week the harvest probe solved it. The read-only cube shipped; the automated experiment arm was
deliberately split off and never armed.</p></div>
<div class="card fun"><h4>&ldquo;How nav works&rdquo;</h4><p>A dashboard tab that documents the
navigation system by <em>introspecting the code at request time</em> — live DIRS/SOLID sets,
docstrings, priority ladders. It cannot go stale, which is more than can be said for any hand-written
doc in the repo.</p></div>

<h2 id="codex">The game, as we learned it</h2>
<p>Twelve days of measurement produced a working physics of BotGuilds. The complete
mechanics ledger, each entry earned empirically:</p>
<ul>
<li><strong>Time:</strong> one server tick is a shared clock across worlds (join rivals to us on
tick, never wall-clock); advertised 0.25s/tick, measured 4.000/s on the old host, 3.62/s on the
new; band refreshes cycle each world every ~14.4&ndash;15.6k ticks, announced in-frame.</li>
<li><strong>Combat:</strong> XP is <em>split</em> across participants (floor ~1 each); ganging up
doubles damage output while incoming damage stays flat (mobs swing at one target per tick), so
per-member risk halves; our club deals 4/swing; attack connect rate 96.6% lifetime; chasers move at
~0.22 tiles/tick and a rule-based predictor calls their next step at 89% (honest, leak-corrected
number: 74% exact).</li>
<li><strong>Progression:</strong> <code>spend_xp</code> cost = 8v&middot;2^(v//10), halved for
gifted stats — verified 6/6 against recorded spends; XP yields diminish on outleveled content
(the northward pressure); a heal potion is the passport past the poison line (carriers reach y~125,
the potionless pin at y&le;12).</li>
<li><strong>Economy:</strong> no gold cap (climbed clean to 643); shop sells no body armor; club 15 /
dagger 20 / shortsword 45 / shield 25 / potion 20 / tome 120&ndash;150; loot dies with its
carrier; carry is weight, not slots; village actions cost no stamina; the guild vault renders
items it will not dispense (phantom inventory, a server bug); the player market existed unused by
every guild until our probe listing.</li>
<li><strong>Craft:</strong> brewing at 87% success once essence-aware; essences per world are
shuffled and learnable (taste first!); tells are per-ingredient; smelt is 2 ore &rarr; 1 ingot;
forge recipes by rejection-science (spear = 1 ingot + 1 lumber); trees fell in ~4 hits and drop
lumber; veins drop ore; 15,876 terrain features were harvested lifetime.</li>
<li><strong>World:</strong> exactly 23 tile kinds exist (10.27M frames say so); the mines' rails
are 19 short lines whose longest ride ends at a chest; portals teleport spawn-strip to deep-map
and ate our roster once (11 accidental transits before the block); sight range is 8&ndash;12 tiles
with ~18% of mobs first seen at distance 0; the map edge is not frontier.</li>
<li><strong>Roster:</strong> caps are 5/party, 10/world, 30/roster — but the recruit endpoint
counts village-present characters, so a roster can sit at 31; recruits are free; the gift lottery
pays ~1-in-3; a field stint lasts a median of 10&ndash;12 ticks, which sizes every possible
errand.</li>
<li><strong>Wire:</strong> three formats in twelve days — plain JSON, zlib-compressed (0x78 sniff),
then v3 grouped inventories and delta tile-frames with REFRESH resync. All three decoded without
data loss; the reference-kit submodule check that lapsed once now has a standing loop step.</li>
</ul>

<h2 id="rivals">The rivals</h2>
<p>The world grew from one guild to five during the experiment, and the journal's assessment —
&ldquo;rival guilds are (often) other AI agents; the field is an adaptive adversarial arena&rdquo;
— aged well. <strong>WillMorr</strong> (the server owner's own guild) ran 30 characters that sat
29-idle for days, then bloomed into a level-38 juggernaut that was nonetheless 73% bare-handed —
headcount and levels, no logistics. <strong>g_63837f</strong> was the opposite: a formation
so disciplined it kept mean pairwise distance 4.06 while we sprawled at 22&ndash;25 — the
measurement that seeded our own cohesion work. Late in the experiment we fielded the only
fully-armed roster on the server and the highest median level per character. Nobody, anywhere,
ever cast a spell.</p>

<h2 id="chars">Characters of note</h2>
<div class="tablewrap"><table>
<tr><th>Character</th><th>Claim to fame</th></tr>
<tr><td class="n">the level-23 (run 7)</td><td>The all-time summit, reached before the loop knew what it was doing — never matched once it did</td></tr>
<tr><td class="n">c9888</td><td>1,183 embarks, ~0 sales — the food-clog era's patron saint of futile commutes</td></tr>
<tr><td class="n">Recruit-15172</td><td>Rested to death one step from safety inside hallucinated walls; its trace broke the stuck-death case (0.42.0)</td></tr>
<tr><td class="n">c15829</td><td>First confirmed live re-equip: club &rarr; dagger, in place — proving slots swap without unequip</td></tr>
<tr><td class="n">c19403</td><td>Arch-wizard, level 9, INT-gifted; died at mines y=28 when a boolean heal-release granted unlimited depth on a single-use potion — the postmortem that priced depth properly</td></tr>
<tr><td class="n">Recruit-19751</td><td>The first deliberate kill in 220 runs: three club swings, one bite taken, one wolf, 8 XP</td></tr>
<tr><td class="n">c19871</td><td>INT-4 survivor and perennial probe volunteer through the server war — the closest thing the final week had to a protagonist</td></tr>
<tr><td class="n">c20054 / c20055 / c20079</td><td>The server war's evidence: one died and spammed 95 ghost-rejections, two vanished without death events — Bug B's named victims</td></tr>
</table></div>
""")

B.append("""
<h2 id="eng">The engineering system behind the record</h2>
<h3>The gates</h3>
<p>Every deploy passed the same gauntlet: pycache purge, the full local suite
(<code>pytest -q -rf</code>, failure names preserved by rule after tail-truncation lost them
twice), the containerized reaper suite on Linux (the workstation is FreeBSD; Playwright only runs
in the container), and a 3&times;2-minute live watch after restart. 478 commits ended with the
suites at 1,276 local / 1,285 reaper, green.</p>
<h3>The testing ethic, as practiced</h3>
<ul>
<li><strong>Every assertion mutation-checked:</strong> break the code, watch the named test fail,
restore. When a mutant survived, the finding was always about the <em>test</em> — the survivor
catalog above is the receipts.</li>
<li><strong>Self-test the oracle:</strong> the wake-up channel was proven by injecting a synthetic
error-spike and watching it wake the agent; the extractor's guild filter was proven by feeding it
a world-wide event list and watching the counts explode.</li>
<li><strong>Two oracles for load-bearing claims:</strong> the 0.42 survival verdict ran on two
independent death measures; the sensor war ended when every lag reading required a second,
differential witness.</li>
<li><strong>Class oracles over instance patches:</strong> <code>test_no_oscillation.py</code>
exists because five instance-pinned tests each blessed the next oscillation.</li>
<li><strong>The sim server:</strong> after post-deploy bug-finds were declared &ldquo;proof the
test layer is inadequate,&rdquo; a reverse-engineered server simulator
(<code>tests/simserver.py</code>) began soaking the real bot against modeled incoherence — lag,
staleness, flicker, the full error taxonomy — inside the gate. Every live-escaped bug became a sim
reproduction first.</li>
</ul>
<h3>Operations</h3>
<ul>
<li>Self-healing at four layers by the end: protocol (seq-gap refresh resync), session
(poison-storm and frozen-debt re-hellos), process (the <code>svc.sh</code> watch supervisor, which
absorbed a mid-wave <code>not_authenticated</code> credential rejection autonomously), and
strategy (bunker/squall/quarantine).</li>
<li>Incidents survived: the pyzmq ABI crash-loop after an OS update (exit 139, cached wheel against
a replaced interpreter); a <code>daemon(8)</code> process-group subtlety that made
<code>svc.sh down</code> leave runners alive; a MariaDB 1040 connection-exhaustion caused half by
a dashboard poll pile-up and half by dead LAN connections; smbnetfs I/O errors that left 0-byte
archive husks (caught by the shipper's verify-then-prune design — no frame was ever lost).</li>
<li>The monitoring doctrine in one line: <em>measure capability, not outcomes</em> — a paralyzed
bot has excellent death statistics.</li>
</ul>
<h3>The knowledge system</h3>
<p>345 findings with typed kinds and a currency ratchet (findings must track the strategy version
or the suite goes red — it fired during the war and was obeyed); a claims ledger where headline
numbers stay re-checkable; 5,837 lines of decision journal; and a memory system whose entries are
themselves versioned, cross-linked, and — twice — corrected when they turned out to be wrong.</p>

<h2 id="data">Data assets &amp; integrity</h2>
<ul>
<li><strong>221 archives, 22 GB</strong>, one per frame-producing run, gzip-JSONL with metadata
headers and zlib frame blobs, each independently size- and sha256-verified on the NAS. The five
largest (0.4&ndash;0.8 GB) defeated the automated shipper's smbnetfs writes repeatedly and were
re-shipped manually this session, hash-verified. Run 303 was closed and shipped explicitly; run
301 (a two-minute restart) is the only frameless run. The retention cron is cancelled.</li>
<li><strong>Local:</strong> <code>guild_log.db</code> (3.0 GB — complete event, error, action, and
decision ledgers for all 295 runs), <code>findings.jsonl</code>, <code>server_bugs.md</code> (566
lines), <code>decisions.log</code>, and <code>evidence/</code> — 1,000+ paired
validator-divergence samples, the healthy/storm/sick wire captures, the comb dataset behind this
report, and the report itself.</li>
<li><strong>Companion artifact:</strong> the server diagnostic report maintained for Will
throughout the war, updated through the final wave analysis.</li>
</ul>

<h2 id="appendix">Appendix: every run</h2>
<p class="note">All 295 runs. Frames, duty, gold, and levels derive from the shipped archives; XP,
kills, deaths, and rejections from the event ledger. &ldquo;—&rdquo; marks data the archive cannot
provide (e.g. duty needs village frames). Era shading in the charts above uses the same
boundaries.</p>
<div class="tablewrap appendix"><table>
<tr><th>Run</th><th>Version</th><th>Start</th><th>Frames</th><th>Hours</th><th>Duty%</th>
<th>XP</th><th>Kills</th><th>Deaths</th><th>Gold max</th><th>Lvl max</th><th>Chars</th><th>Rejections</th></tr>
""" + run_rows + """</table></div>

<h3>The tile census, one last time</h3>
<p class="note">Every tile kind in 10,273,582 frames. There is no 24th row, and now there never
will be.</p>
<div class="tablewrap appendix"><table>
<tr><th>Tile kind</th><th>Sightings</th></tr>
""" + tile_rows + """</table></div>

<p class="note" style="margin-top:3rem">World exposure: village """ + num(worlds.get("village",0)) + """
&middot; vale """ + num(worlds.get("vale",0)) + """ &middot; mines """ + num(worlds.get("mines",0)) + """
&middot; spire """ + num(worlds.get("spire",0)) + """ frames. The spire stayed the frontier to the end.</p>

<p class="note">Compiled 2026-08-30 by the improvement loop's final pass, from the complete backup
corpus, the event ledger, 478 commits, and a journal that was not allowed to flatter anyone. The
experiment is concluded; the services are stopped; the guild is, as of its last frame, eighteen
strong, fully housed, and safe in the village. Somewhere in the vale there is a wolf that started
all of this by losing.</p>
</main>""")

open(f"{S}/final_report.html", "w").write("".join(B))
print("bytes:", sum(len(b) for b in B))
