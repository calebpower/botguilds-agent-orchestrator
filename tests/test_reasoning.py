"""Decision traces: scoring, choice, rendering, and persistence."""

from steemer.reasoning import DecisionTrace


def _trace():
    t = DecisionTrace(tick=1, world="vale", char_uid="c1")
    t.observe("hp 30/30")
    t.consider({"action": "move", "dir": "N"}, 2.0, "explore")
    t.consider({"action": "attack", "target": [1, 0]}, 8.0, "kill the rat")
    t.consider(None, 0.5, "rest")
    return t


def test_decide_picks_highest_score():
    t = _trace()
    chosen = t.decide()
    assert chosen == {"action": "attack", "target": [1, 0]}
    assert t.chosen.why == "kill the rat"


def test_decide_returns_none_when_no_candidates():
    t = DecisionTrace(tick=1, world="vale", char_uid="c1")
    assert t.decide() is None
    assert t.chosen is not None and t.chosen.action is None


def test_reasoning_text_marks_the_choice_and_lists_alternatives():
    t = _trace()
    t.decide()
    text = t.reasoning_text()
    assert "saw: hp 30/30" in text
    assert "→ [+8.0] attack" in text        # the chosen candidate is marked
    assert "kill the rat" in text
    assert "explore" in text                # alternatives are shown too


def test_alternatives_are_ranked_and_flag_the_choice():
    t = _trace()
    t.decide()
    alts = t.alternatives()
    assert [a["score"] for a in alts] == [8.0, 2.0, 0.5]     # descending
    assert alts[0]["chosen"] is True
    assert all(a["chosen"] is False for a in alts[1:])


def test_record_persists_via_storage():
    calls = []

    class FakeStorage:
        def record_decision(self, **kw):
            calls.append(kw)

    t = _trace()
    t.decide()
    t.record(FakeStorage(), "explorer/test")
    assert len(calls) == 1
    kw = calls[0]
    assert kw["tick"] == 1 and kw["char_uid"] == "c1"
    assert kw["chosen"] == {"action": "attack", "target": [1, 0]}
    assert kw["strategy_version"] == "explorer/test"
    assert "kill the rat" in kw["reasoning"]


def test_record_is_noop_without_storage():
    t = _trace()
    t.decide()
    t.record(None, "explorer/test")   # must not raise
