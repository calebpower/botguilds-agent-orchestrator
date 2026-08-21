"""The exploration matrix, slice (A): the cube and the frontier.

Tests assert the CLAIMS the priors are supposed to encode — relative plausibility between
concrete cells — rather than "family X matched", which would just re-export the predicate
table into the test file and agree with itself.
"""
# `tested_cells` is aliased on import: pytest collects any module-level name starting
# with `test`, and would otherwise try to RUN the function as a test case.
from steemer.matrix import (prior_for, frontier, say_wordlist, build,
                            tested_cells as build_tested_cells,
                            DEFAULT_PRIOR, EQUIP_SENSITIVE_VERBS, FOLKLORE_WORDS)

CTX = {"uses": {"lumber": ["forge"], "moonbell": ["brew", "taste"],
                "potion_red": ["drink"], "club": ["equip", "attack"]},
       "equippable": {"club", "spear"},
       "tiles": {"tree", "rock", "floor", "vein", "portal", "safe", "grave", "wall"}}


# ---- priors: relative claims, not family names -------------------------------

def test_a_blade_on_a_tree_outranks_bare_hands_which_outranks_hitting_the_floor():
    """The ordering IS the claim. 0.45 confirmed the bare-handed tree cell live, so it must
    sit high; hitting the ground is not a mechanic in anything."""
    axe = prior_for("tree", "attack", "axe", CTX)[0]
    bare = prior_for("tree", "attack", "none", CTX)[0]
    floor = prior_for("floor", "attack", "none", CTX)[0]
    assert axe > bare > floor


def test_a_pickaxe_on_a_vein_outranks_a_pickaxe_on_the_floor():
    assert prior_for("vein", "attack", "pickaxe", CTX)[0] > \
           prior_for("floor", "attack", "pickaxe", CTX)[0]


def test_an_items_OWN_declared_use_is_the_strongest_evidence():
    """`lumber` declares uses:['forge']. A declaration by the game beats any analogy we
    could draw, so it must outrank every heuristic family."""
    declared = prior_for("lumber", "forge", "none", CTX)[0]
    analogy = prior_for("portal", "say", "none", CTX)[0]
    assert declared > analogy >= 0.5


def test_speaking_at_a_sealed_thing_beats_speaking_at_the_floor():
    assert prior_for("safe", "say", "none", CTX)[0] > prior_for("floor", "say", "none", CTX)[0]


def test_an_unclassified_pairing_gets_the_default_and_says_so():
    p, why = prior_for("lily", "recruit", "none", CTX)
    assert p == DEFAULT_PRIOR and "no family" in why


def test_a_malformed_context_does_not_break_scoring():
    """The game is an evolving target, and the vocabulary is harvested JSON — a null where a
    dict was expected must not crash the cube.

    An EMPTY dict is not enough to exercise this: every predicate uses `.get(k, {})`, so it
    survives on its own and a mutant removing the guard passed. A None VALUE is what
    actually raises, and is what a stale or partial harvest looks like."""
    # The verb matters: the ctx-reading predicates all short-circuit on their verb test
    # (`v == "use" and ...`), so scoring an `attack` never touches the malformed dict at all
    # and a mutant removing the guard passed. These are the verbs that DO read ctx.
    for verb in ("use", "forge", "brew", "smelt", "equip"):
        for bad in ({}, {"uses": None}, {"equippable": None}, {"uses": {"lumber": None}}):
            p, _ = prior_for("lumber", verb, "axe", bad)
            assert isinstance(p, float), (verb, bad)


# ---- the frontier ------------------------------------------------------------

NOUNS = ["tree", "portal", "lumber", "floor"]
VERBS = ["attack", "say", "forge", "move"]
EQUIPS = ["none", "axe", "club"]


def test_a_verb_we_have_ALREADY_sent_is_not_on_the_frontier():
    """The frontier is what we have NEVER tried — its whole purpose."""
    tested = {("*", "attack"): {"sent": 5, "errors": {}}}
    cells = frontier(NOUNS, VERBS, EQUIPS, tested, CTX)
    assert not any(c["verb"] == "attack" for c in cells)


def test_the_equip_axis_COLLAPSES_for_a_verb_it_cannot_affect():
    """Brewing does not care which sword you carry. Reporting the same cell once per
    equippable buried the real frontier under 7x duplicates on the first live run."""
    cells = frontier(["lumber"], ["forge"], EQUIPS, {}, CTX)
    assert len(cells) == 1 and cells[0]["equipped"] == "any"


def test_the_equip_axis_is_KEPT_for_a_verb_it_does_affect():
    """`attack` varies by tool, so the axis must expand rather than collapse to "any".
    Note min_prior=0: at the default threshold a CLUB on a tree is correctly filtered out
    (it is neither bladed nor a mining tool), which is a fact about the priors and would
    make this a test of the wrong thing."""
    cells = frontier(["tree"], ["attack"], EQUIPS, {}, CTX, min_prior=0.0)
    assert {c["equipped"] for c in cells} == set(EQUIPS)
    assert "attack" in EQUIP_SENSITIVE_VERBS
    assert all(c["equipped"] != "any" for c in cells)


def test_the_frontier_is_ordered_most_plausible_first():
    cells = frontier(NOUNS, VERBS, EQUIPS, {}, CTX)
    assert cells == sorted(cells, key=lambda c: (-c["prior"], c["noun"], c["verb"],
                                                 c["equipped"]))


def test_low_plausibility_cells_are_filtered_out():
    cells = frontier(["floor"], ["attack"], ["none"], {}, CTX, min_prior=0.5)
    assert cells == []


def test_every_frontier_cell_carries_its_REASONING():
    """A bare score is not actionable — the operator has to be able to judge the claim."""
    for c in frontier(NOUNS, VERBS, EQUIPS, {}, CTX):
        assert c["why"] and len(c["why"]) > 10


# ---- the say axis ------------------------------------------------------------

def test_words_the_WORLD_gave_us_rank_above_imported_folklore():
    words = say_wordlist(in_world=["mellon", "grimhold"])
    assert words[0] == "mellon" and words[1] == "grimhold"
    assert words.index("grimhold") < words.index("xyzzy")


def test_the_wordlist_deduplicates_across_both_sources():
    words = say_wordlist(in_world=["open", "open"])
    assert words.count("open") == 1
    assert set(FOLKLORE_WORDS) <= set(words)


# ---- assembly ----------------------------------------------------------------

def test_build_reports_cube_size_and_the_untouched_verbs():
    voc = {"tiles": ["tree", "portal"], "items": ["lumber"], "mobs": [],
           "verbs_protocol": ["attack", "say", "forge"], "equippable": ["axe"],
           "uses_by_kind": {"lumber": ["forge"]}, "verbs_never_sent": ["say", "forge"]}
    rep = build(voc, tested={}, min_prior=0.5)
    assert rep["nouns"] == 3 and rep["verbs"] == 3 and rep["equips"] == 2
    assert rep["cells_total"] == 18
    assert rep["verbs_never_sent"] == ["forge", "say"]
    assert rep["frontier_size"] == len(rep["frontier"]) > 0


class _Conn:
    """Minimal stand-in: the DISTINCT query returns a verb the recent-rows window omits."""
    def __init__(self):
        self.n = 0

    def execute(self, sql, params=()):
        self.n += 1
        class _R:
            def __init__(self, rows): self._r = rows
            def fetchall(self_inner): return self_inner._r
        if "DISTINCT action" in sql:
            return _R([("brew",), ("move",)])
        if "payload_json" in sql:
            return _R([("move", '{"dir": "N"}')])          # brew is NOT in this window
        return _R([])


def test_a_rarely_sent_verb_still_counts_as_TRIED():
    """`brew` has only ~474 lifetime sends and fell outside a 200k-row window on the first
    live run, so the frontier wrongly reported brewing as never attempted."""
    tested = build_tested_cells(_Conn())
    assert ("*", "brew") in tested
    assert not any(c["verb"] == "brew"
                   for c in frontier(["moonbell"], ["brew"], ["none"], tested, CTX))
