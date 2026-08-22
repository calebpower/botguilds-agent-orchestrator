"""v0.66.0 — proven recipes must outlive the process that proved them.

Run #143 paid the bill in full: ONE character spent 20 of the run's 23 forge attempts
re-walking the ladder from scratch — `shield_iron` at (1,1) four times, (2,1) three times,
(1,2) three times, (2,2) three times, all failing — before reaching `spear` (1,1), which
worked immediately. Run #129 had already PROVEN that `shield_iron` needs (3, 1); this
character was holding two ingots, so every quantity it could afford was known-wrong before
it started. That tuition is paid again on every deploy, and we redeploy several times a day.

Two halves. Proven recipes now persist and are hydrated at startup, and once a product has a
proven quantity that is the ONLY one worth sending — if it is unaffordable right now, the
product is simply not on today's menu.

ONLY POSITIVE FACTS ARE PERSISTED, and that is deliberate. `wrong_materials` is not
deterministic in what we key on (identical product, kinds and quantities both succeed and
fail within one run), so a persisted FAILURE would carry a wrong belief into every future
run — the mistake v0.55.0 made when it let remembered chest CONTENTS drive targets.
"""
from steemer.storage import Storage
from steemer.strategy.explorer import Explorer, FORGE_RECIPES


class _Bot:
    tick = 500
    config: dict = {}

    def __init__(self, storage=None):
        self.storage = storage
        self._forged = {}

    def recently_forged(self, uid):
        return uid in self._forged


def _ing(n=1, kind="ingot_copper"):
    return [{"kind": kind, "item_id": f"{kind}-{i}", "uses": ["forge"]} for i in range(n)]


def _lum(n=1):
    return [{"kind": "lumber", "item_id": f"lumber-{i}", "uses": ["forge"]} for i in range(n)]


EMPTY = {s: None for s in ("hand", "offhand", "outfit", "trinket", "boots")}


def _store():
    st = Storage(":memory:")
    st.begin_run("sha", "test/0")
    return st


# ---- the round trip ----------------------------------------------------------

def test_a_proven_recipe_is_persisted_and_survives_a_new_process():
    st = _store()
    first = Explorer()
    first._prove_forge(_Bot(st), ("spear", 1, 1))

    second = Explorer()                      # a fresh deploy
    assert ("spear", 1, 1) not in second._forge_proven
    second._hydrate_forge(_Bot(st))
    assert ("spear", 1, 1) in second._forge_proven


def test_hydration_happens_once_and_not_on_every_village_frame():
    st = _store()
    exp = Explorer()
    exp._hydrate_forge(_Bot(st))
    st.record_learned(Explorer.FORGE_TOPIC, "dagger:2:2")
    exp._hydrate_forge(_Bot(st))
    assert ("dagger", 2, 2) not in exp._forge_proven, "one load per process, not per frame"


def test_only_POSITIVE_facts_are_persisted():
    """A persisted failure would carry a wrong belief into every future run, and
    `wrong_materials` has already been shown unreliable."""
    st = _store()
    exp = Explorer()
    exp._forge_attempt["u1"] = ("spear", 3, 1)
    exp.on_action_error(None, {"action": "forge", "char_uid": "u1",
                               "reason": "wrong_materials"})
    assert st.load_learned(Explorer.FORGE_TOPIC) == set()


def test_a_bot_without_storage_still_forges_AND_stays_quiet(capsys):
    """Two claims, and the second is why the `is None` guard exists at all: an offline
    replay must forge from memory AND not print a persistence failure every time it proves
    something. Reaching the writer with None and letting the except clause catch the
    AttributeError would also "work", noisily. (Same lesson as the v0.55.0 map hydration.)"""
    exp = Explorer()
    exp._hydrate_forge(_Bot(None))
    exp._prove_forge(_Bot(None), ("spear", 1, 1))
    assert ("spear", 1, 1) in exp._forge_proven, "memory still works without a database"
    out = capsys.readouterr().out
    assert "could not persist" not in out and "could not load" not in out


def test_topics_are_kept_apart():
    """`learned` is a general table; a fact proven about something else must never be
    read back as a forge recipe."""
    st = _store()
    st.record_learned("something_else", "spear:9:9")
    st.record_learned(Explorer.FORGE_TOPIC, "spear:1:1")
    exp = Explorer()
    exp._hydrate_forge(_Bot(st))
    assert exp._forge_proven == {("spear", 1, 1)}


def test_a_broken_store_does_not_stop_the_bot():
    class Broken:
        def load_learned(self, topic):
            raise RuntimeError("no such table: learned")

        def record_learned(self, topic, fact):
            raise RuntimeError("no such table: learned")

    exp = Explorer()
    exp._hydrate_forge(_Bot(Broken()))
    exp._prove_forge(_Bot(Broken()), ("spear", 1, 1))
    assert ("spear", 1, 1) in exp._forge_proven


def test_a_malformed_stored_fact_is_ignored_rather_than_crashing():
    st = _store()
    st.record_learned(Explorer.FORGE_TOPIC, "not-a-recipe")
    st.record_learned(Explorer.FORGE_TOPIC, "spear:x:1")
    st.record_learned(Explorer.FORGE_TOPIC, "spear:1:1")
    exp = Explorer()
    exp._hydrate_forge(_Bot(st))
    assert exp._forge_proven == {("spear", 1, 1)}


def test_the_fact_encoding_round_trips():
    for recipe in (("spear", 1, 1), ("shield_iron", 3, 1)):
        assert Explorer._fact_recipe(Explorer._recipe_fact(recipe)) == recipe


# ---- what knowing it changes -------------------------------------------------

def test_a_proven_quantity_is_the_only_one_tried_for_that_product():
    """The run-#143 repair. Knowing shield_iron needs (3,1), a character holding two
    ingots must not spend thirteen attempts proving that (1,1), (2,1), (1,2) and (2,2)
    all fail — that product is simply not on today's menu."""
    exp = Explorer()
    exp._forge_proven.add(("shield_iron", 3, 1))
    got = exp._choose_forge(_ing(2) + _lum(2), dict(EMPTY), stamina=40)
    assert got is None or got[0][0] != "shield_iron"


def test_the_proven_quantity_IS_sent_once_affordable():
    """The other side of the boundary — otherwise the test above would pass just as well
    if the product had been dropped altogether."""
    exp = Explorer()
    exp._forge_proven.add(("shield_iron", 3, 1))
    got = exp._choose_forge(_ing(3) + _lum(2), dict(EMPTY), stamina=40)
    assert got is not None and got[0] == ("shield_iron", 3, 1)


def test_an_unproven_product_still_walks_the_whole_ladder():
    """Discovery must survive the optimisation: a product we know nothing about is still
    explored, or nothing new is ever learned."""
    exp = Explorer()
    exp._forge_proven.add(("shield_iron", 3, 1))
    # shield_iron is WORN, so the ladder moves past the proven product to an unproven one.
    # Without this the proven-and-affordable shield_iron is simply offered first and the
    # test never reaches the behaviour it is named for.
    eqp = dict(EMPTY, offhand={"kind": "shield_iron"})
    seen = set()
    for _ in range(len(FORGE_RECIPES) + 2):
        got = exp._choose_forge(_ing(3) + _lum(3), eqp, stamina=40)
        if got is None:
            break
        seen.add(got[0])
        exp._forge_failed.add(got[0])
    quantities = {r[1:] for r in seen if r[0] != "shield_iron"}
    assert len(quantities) > 1, f"an unproven product tried only one quantity: {seen}"
