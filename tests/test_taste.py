"""v0.81.0 — taste: pay one stranded herb, decode its kind forever.

The event's true shape has NEVER been observed (the first taste in project history ships
with this version), so the parser is tolerant about field names and these tests document
the GUESSED shapes. If the live event differs, the [taste] raw-event print is the
specimen; what cannot regress silently is the pipeline behind the parse: learn ->
first-write-wins -> persisted -> hydrated into the next process.
"""
import pytest

import steemer.knowledge as knowledge
from steemer.bot import GuildBot
from steemer.storage import Storage


@pytest.fixture(autouse=True)
def _fresh_essence_map():
    """knowledge.ESSENCE is module state; leaking a learned kind between tests would make
    order decide outcomes."""
    added = set(knowledge.ESSENCE) 
    yield
    for k in [k for k in knowledge.ESSENCE if k not in added]:
        del knowledge.ESSENCE[k]


def _bot(storage=None):
    b = GuildBot("explorer", storage=storage)
    b.config = {"party_cap": 5}
    return b


def _taste_frame(ev):
    return {"world": "village", "tick": 9, "events": [ev],
            "guild": {"gold": 5, "chars_here": [], "chars_by_world": {}}, "chars": [
            {"char_uid": "c1", "eid": 7, "hp": 30, "max_hp": 30, "inventory": [],
             "equipment": {}, "stats": {}, "gifts": [], "xp": 0}]}


def test_a_taste_event_decodes_the_kind():
    bot = _bot()
    bot.on_frame(_taste_frame({"kind": "tasted", "eid": 7, "item": "bitterroot",
                               "essence": "vigor"}))
    assert knowledge.essence_of("bitterroot") == "vigor"


def test_the_result_field_spelling_is_forgiven():
    """`result` instead of `essence`, `ingredient` instead of `item` — the shapes we
    could not rule out without ever having seen one."""
    bot = _bot()
    bot.on_frame(_taste_frame({"kind": "taste", "eid": 7, "ingredient": "glimmerweed",
                               "result": "venom"}))
    assert knowledge.essence_of("glimmerweed") == "venom"


def test_a_decoded_kind_is_never_OVERWRITTEN():
    """First-write-wins: bone is a server-documented calibration anchor (vigor), and a
    misparsed event must not flip a pole — that would curdle every future vigor batch."""
    assert knowledge.learn("bone", "venom") is False
    assert knowledge.essence_of("bone") == "vigor"


def test_the_decode_survives_a_restart(tmp_path):
    """Destructive knowledge must outlive the process, or the once-per-kind guard spends
    another herb re-learning it every run."""
    st = Storage(str(tmp_path / "t.db"))
    st.begin_run("sha", "test/0")
    bot = _bot(storage=st)
    bot.on_frame(_taste_frame({"kind": "tasted", "eid": 7, "item": "bitterroot",
                               "essence": "vigor"}))
    del knowledge.ESSENCE["bitterroot"]              # simulate the process dying
    st.conn.commit()                                 # the live path commits on flush
    st.conn.close()                                  # ...and the handle dies with it
    st2 = Storage(str(tmp_path / "t.db"))
    st2.begin_run("sha", "test/0")
    _bot(storage=st2)                                # hydration runs in __init__
    assert knowledge.essence_of("bitterroot") == "vigor"


def test_a_RIVALS_taste_teaches_us_nothing():
    """eid 999 is not ours; the world-wide event stream must not write our essence map —
    rivals may be tasting a different world's vocabulary or poisoning deliberately."""
    bot = _bot()
    bot.on_frame(_taste_frame({"kind": "tasted", "eid": 999, "item": "sungrass",
                               "essence": "vigor"}))
    assert knowledge.essence_of("sungrass") is None
