"""The claim ledger — the expectation detector, pointed at the loop instead of the bot.

v0.61.0 taught the bot to ask "did what we predicted actually happen?". This asks the same of
the numbers the loop REPORTS, because the loop's own error rate is currently the larger one.

The motivating case: a forge success rate of "35% -> 68%" was reported as confirming v0.64.0.
Both figures counted rival forges (13 world-wide against 4 of ours on run #141). It survived a
whole pass and was caught by accident. Re-running the same question through `steemer.attribution`,
where ownership filtering is the default, contradicts it immediately — and the frames are
immutable history, so a disagreement can only mean the original was wrong.

A claim therefore records the QUESTION, not just the answer. Prose cannot be re-checked.
"""
import json

import pytest

import steemer.claims as claims
from steemer.storage import Storage


@pytest.fixture()
def conn(tmp_path):
    st = Storage(str(tmp_path / "c.db"))
    st.begin_run("sha", "test/0")
    st.conn.execute(
        "INSERT INTO decisions(tick, world, char_uid, action, chosen_json, "
        "alternatives_json, reasoning, strategy_version, run_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (1, "vale", "g_us_c1", "move", "{}", "[]", "why", "test/0", st.run_id))
    chars = [{"char_uid": "g_us_c7", "eid": 7, "pos": [0, 0]}]
    st.conn.executemany(
        "INSERT INTO frames(seq, tick, world, received_at, run_id, json) VALUES(?,?,?,?,?,?)",
        [(i, i, "vale", 0.0, st.run_id,
          json.dumps({"world": "vale", "chars": chars, "visible": {"items": []}}))
         for i in range(30_000)])
    # one forge of ours, two by a rival: the run-#141 shape in miniature
    for eid in (7, 999, 999):
        st.conn.execute(
            "INSERT INTO events(tick, world, kind, payload_json, run_id) VALUES(?,?,?,?,?)",
            (1, "vale", "forged", json.dumps({"eid": eid}), st.run_id))
    st.conn.commit()
    import steemer.attribution as m
    m._EID_CACHE.clear()
    return st.conn


@pytest.fixture()
def ledger(tmp_path):
    return str(tmp_path / "claims.jsonl")


# ---- it catches the mistake it was built for ---------------------------------

def test_a_claim_that_counted_RIVALS_is_contradicted(conn, ledger):
    """The retraction, caught one tick later instead of by accident a pass later. Three
    forges happened in the world; one was ours. Reporting three is the original error."""
    claims.record("forge count", "event_count",
                  {"run_id": 1, "kind": "forged"}, value=3,
                  iteration="iter-78", path=ledger)
    [v] = claims.recheck(conn, ledger)
    assert v["status"] == "contradicted"
    assert v["recorded"] == 3 and v["recomputed"] == 1


def test_a_correct_claim_is_confirmed(conn, ledger):
    claims.record("forge count", "event_count",
                  {"run_id": 1, "kind": "forged"}, value=1, path=ledger)
    [v] = claims.recheck(conn, ledger)
    assert v["status"] == "confirmed"


def test_small_drift_is_tolerated(conn, ledger):
    """`rate_per` divides by a frame count that grows while a run is live, so a claim
    recorded mid-run legitimately moves a little. Zero tolerance would be wrong in the
    other direction and would cry wolf every pass."""
    claims.record("frames", "frame_count", {"run_id": 1}, value=30_000 * 1.01, path=ledger)
    [v] = claims.recheck(conn, ledger, tolerance=0.05)
    assert v["status"] == "confirmed"
    [v2] = claims.recheck(conn, ledger, tolerance=0.001)
    assert v2["status"] == "contradicted"


# ---- three-valued, for the same reason the bot's detector is -----------------

def test_an_uncheckable_claim_EXPIRES_rather_than_failing(conn, ledger):
    """A pruned run or a changed schema is housekeeping, not a wrong number. Folding the
    two together would turn maintenance into false alarms — the mistake the bot's detector
    already refuses to make with `expired`."""
    claims.record("gone", "frame_count", {"run_id": 9999}, value=5, path=ledger)
    [v] = claims.recheck(conn, ledger)
    assert v["status"] == "unavailable"
    assert "recomputed" not in v


def test_an_unknown_check_is_unavailable_not_contradicted(conn, ledger):
    with open(ledger, "a") as fh:
        fh.write(json.dumps({"at": 0, "claim": "x", "check": "no_such_fn",
                             "kwargs": {}, "value": 1}) + "\n")
    [v] = claims.recheck(conn, ledger)
    assert v["status"] == "unavailable"
    # ...and says WHY in terms a reader can act on. Letting the generic exception handler
    # catch it would also yield "unavailable", but with "TypeError: 'NoneType' object is
    # not callable" — which sends the next reader debugging the ledger instead of fixing
    # the claim.
    assert "no_such_fn" in v["detail"]


# ---- the ledger cannot launder a bad query ------------------------------------

def test_only_vetted_checks_can_be_recorded(ledger):
    """A ledger that could call anything would let the same bad ad-hoc query be re-run and
    agree with itself. Claims must go through `steemer.attribution`, where ownership filtering
    and maturity checks are the defaults."""
    with pytest.raises(ValueError):
        claims.record("anything", "os.system", {}, value=1, path=ledger)


def test_the_summary_names_every_contradiction(conn, ledger):
    """A verdict nobody reads is not a check. The summary must surface the bad ones by
    name, with both numbers."""
    claims.record("forge count", "event_count",
                  {"run_id": 1, "kind": "forged"}, value=3,
                  iteration="iter-78", path=ledger)
    out = claims.summarise(claims.recheck(conn, ledger))
    assert "CONTRADICTED" in out and "iter-78" in out
    assert "3" in out and "1" in out


def test_an_empty_ledger_is_quiet(conn, ledger):
    assert claims.recheck(conn, ledger) == []
    assert "claims: 0" in claims.summarise([])
