"""Cross-run KPI regression alarm (wishlist item, shipped 2026-08-20).

The direct meta-fix for the blindness that let ``move_failed`` rot unnoticed for 8
runs: after each run, compute a handful of key productivity/health KPIs and compare
them against the prior run, flagging any that REGRESSED beyond a threshold. Read-only
over the frames/events mirror — it never touches the live strategy or the bot, so it
is safe to run in the improvement loop every pass.

Two layers, split so the judgement is unit-testable without a database:

* :func:`flag_regressions` — PURE: given two ``{kpi: value}`` snapshots and a spec of
  each KPI's direction + thresholds, return the regressions worth surfacing.
* :func:`compute_run_kpis` — reads a run's KPIs from the DB mirror.
* :func:`check_latest` — convenience: compute the latest run vs the prior and flag.

A regression must clear BOTH a relative threshold (moved this fraction of baseline)
AND an absolute floor (moved at least this much), so a run with tiny counts doesn't
raise noise. ``undead_frac`` is carried as CONTEXT (never flagged) because deaths and
income swing with the world's poison level — the alarm reports it so a flagged
income/deaths change can be read against it rather than mistaken for a code regression.
"""
from __future__ import annotations

from typing import Any


# kpi -> (higher_is_better, min_abs_change, rel_threshold_frac). A KPI absent here is
# treated as CONTEXT (reported, never flagged) — see CONTEXT_KPIS.
KPI_SPECS: dict[str, tuple[bool, float, float]] = {
    "deaths_per_1k":       (False, 0.20, 0.25),
    "move_failed_per_1k":  (False, 1.00, 0.30),
    # v0.35.0-era fix: FLAG the per-1k RATES, never the cumulative totals. Comparing a
    # 30k mid-run to a 64k full run made income_total/chest_opens look -65% when the
    # per-frame rate was ~flat — run length confounded the alarm and nearly caused a
    # misread. Rates are frame-normalised so they compare cleanly across run lengths.
    "income_per_1k":       (True,  1.00, 0.25),
    "gold_mean":           (True,  10.0, 0.20),
    "chest_opens_per_1k":  (True,  0.03, 0.30),
}

# Reported alongside the KPIs to contextualise them; never itself flagged. The cumulative
# totals stay here (useful to see) but are NOT flagged — only their per-1k rates are.
CONTEXT_KPIS = ("undead_frac", "frames", "income_total", "chest_opens")


def flag_regressions(
    prev: dict[str, float],
    curr: dict[str, float],
    specs: dict[str, tuple[bool, float, float]] = KPI_SPECS,
) -> list[dict[str, Any]]:
    """Return the KPIs in ``curr`` that regressed vs ``prev`` past their thresholds,
    worst first. A KPI missing from either snapshot, or in the right direction, or
    below its absolute/relative floors, is not flagged."""
    out: list[dict[str, Any]] = []
    for kpi, (higher_better, min_abs, rel) in specs.items():
        if kpi not in prev or kpi not in curr:
            continue
        p, c = float(prev[kpi]), float(curr[kpi])
        delta = c - p
        worse = (delta < 0) if higher_better else (delta > 0)
        if not worse or abs(delta) < min_abs:
            continue
        base = abs(p) or 1.0
        frac = abs(delta) / base
        if frac >= rel:
            out.append({
                "kpi": kpi,
                "prev": round(p, 2),
                "curr": round(c, 2),
                "pct": round(100.0 * (delta / base), 1),
                # how many multiples of the alerting threshold it cleared
                "severity": round(frac / rel, 2),
            })
    out.sort(key=lambda d: -d["severity"])
    return out


def compute_run_kpis(conn: Any, run_id: int) -> dict[str, float]:
    """Read one run's KPIs from the DB mirror. Cheap event-count KPIs plus gold_mean
    from the village frames and undead_frac (context) from a sampled field walk."""
    from . import protocol

    n = conn.execute(
        "SELECT COUNT(*) c FROM frames WHERE run_id=%s", (run_id,)
    ).fetchone()["c"] or 0
    if not n:
        return {"frames": 0}

    def ev_count(kind: str) -> int:
        return conn.execute(
            "SELECT COUNT(*) c FROM events WHERE run_id=%s AND kind=%s", (run_id, kind)
        ).fetchone()["c"] or 0

    def ev_gold_sum(kind: str, field: str) -> int:
        import json as _json
        tot = 0
        for row in conn.execute(
            "SELECT payload_json FROM events WHERE run_id=%s AND kind=%s", (run_id, kind)
        ).fetchall():
            pj = row["payload_json"]
            p = _json.loads(pj) if isinstance(pj, str) else pj
            tot += p.get(field, 0) or 0
        return tot

    kpis: dict[str, float] = {"frames": float(n)}
    kpis["deaths_per_1k"] = 1000.0 * ev_count("death") / n
    kpis["move_failed_per_1k"] = 1000.0 * ev_count("move_failed") / n
    opens = ev_count("opened")
    kpis["chest_opens"] = float(opens)                 # context (cumulative)
    kpis["chest_opens_per_1k"] = 1000.0 * opens / n    # flagged (rate)
    income = float(
        ev_gold_sum("sale", "gold") + ev_gold_sum("gold", "amount")
        + ev_gold_sum("opened", "gold")
    )
    kpis["income_total"] = income                      # context (cumulative)
    kpis["income_per_1k"] = 1000.0 * income / n        # flagged (rate)

    # gold_mean from village frames (guild.gold snapshots)
    golds: list[int] = []
    for row in conn.execute(
        "SELECT json FROM frames WHERE run_id=%s AND world='village' ORDER BY seq ASC",
        (run_id,),
    ).fetchall():
        raw = row["json"]
        raw = raw.encode("latin-1") if isinstance(raw, str) else raw
        try:
            g = (protocol.decode(raw).get("guild") or {}).get("gold")
        except Exception:
            continue
        if g is not None:
            golds.append(g)
    if golds:
        kpis["gold_mean"] = sum(golds) / len(golds)

    # undead_frac (context) — sampled entities across the non-village worlds
    THREAT = {"cultist", "zombie", "ghoul", "vampire_bat", "cinder_wisp", "skeleton",
              "wraith", "lich", "ghast", "specter", "revenant"}
    tot = un = 0
    rows = conn.execute(
        "SELECT json FROM frames WHERE run_id=%s AND world<>'village' ORDER BY seq ASC",
        (run_id,),
    ).fetchall()
    step = max(1, len(rows) // 400)
    for row in rows[::step]:
        raw = row["json"]
        raw = raw.encode("latin-1") if isinstance(raw, str) else raw
        try:
            f = protocol.decode(raw)
        except Exception:
            continue
        for e in (f.get("visible") or {}).get("entities") or []:
            k = e.get("kind")
            if k and k != "char" and not str(k).startswith("g_"):
                tot += 1
                un += 1 if k in THREAT else 0
    if tot:
        kpis["undead_frac"] = round(100.0 * un / tot, 1)
    return kpis


def check_latest(conn: Any) -> dict[str, Any]:
    """Compute the latest run vs the prior and flag regressions. Returns a report
    dict: the two run ids, both KPI snapshots, and the flagged regressions."""
    rows = conn.execute(
        "SELECT DISTINCT run_id FROM frames ORDER BY run_id DESC LIMIT 2"
    ).fetchall()
    if len(rows) < 2:
        return {"error": "need at least two runs"}
    curr_id, prev_id = rows[0]["run_id"], rows[1]["run_id"]
    curr = compute_run_kpis(conn, curr_id)
    prev = compute_run_kpis(conn, prev_id)
    return {
        "prev_run": prev_id, "curr_run": curr_id,
        "prev": prev, "curr": curr,
        "regressions": flag_regressions(prev, curr),
    }
