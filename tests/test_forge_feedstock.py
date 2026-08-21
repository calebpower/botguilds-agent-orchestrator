"""v0.46.0 — forge feedstock is reserved from the sell policy.

The defect this file exists for, measured on run #113: 0.45 taught characters to chop
trees and they chopped 282 of them — then SOLD 189 lumber, 4 ore, and even 2 INGOTS the
guild had deliberately smelted. `_should_sell` classified them as "pure loot -> bank it",
because lumber and ingots carry no `uses` the strategy recognises. The whole harvest went
to the shop counter instead of the forge, so building "seek more resources" first would
have poured material through an open door.

The reserve is BOUNDED, and that bound is tested from both sides: an unbounded keep-rule
is the v0.19.0 regression, where an unsold pack pinned characters `full` forever and drove
the embark<->return thrash that stopped gold ever accumulating.
"""
from steemer.strategy.explorer import Explorer, FORGE_RESERVE_PER_CHAR


def _it(kind, n, **kw):
    return dict(kind=kind, item_id=f"{kind}-{n}", tier=1, **kw)


def _ss(exp, item, keep):
    return exp._should_sell(item, {}, brew_keep=set(), smelt_keep=set(),
                            feedstock_keep=keep)


# ---- the leak itself --------------------------------------------------------

def test_lumber_is_KEPT_when_there_is_METAL_to_forge_it_onto():
    """The exact run-#113 sale — `selling lumber (tier 1) to bank gold`, 189 times —
    but only once the character holds metal (v0.47.0; see the pair below)."""
    exp = Explorer()
    inv = [_it("lumber", 1), _it("ingot_copper", 1)]
    keep = Explorer._feedstock_keep_ids(inv)
    assert _ss(exp, inv[0], keep) is False


def test_lumber_with_NO_metal_is_SOLD_not_stockpiled():
    """v0.47.0, correcting v0.46.0 within one run. A forge needs ingots AND lumber; with
    no metal a reserved shaft is dead weight AND lost income. 0.46 reserved it anyway,
    cutting our main income stream while gold sat at 139 — under the 150 weapon floor —
    so nothing could be armed and nothing could be forged either."""
    exp = Explorer()
    inv = [_it("lumber", 1)]
    keep = Explorer._feedstock_keep_ids(inv)
    assert _ss(exp, inv[0], keep) is True


def test_an_ORE_PAIR_counts_as_metal_because_it_can_still_smelt():
    exp = Explorer()
    pair = [_it("ore_copper", 1, uses=["smelt"]), _it("ore_copper", 2, uses=["smelt"])]
    inv = [_it("lumber", 1)] + pair
    assert _ss(exp, inv[0], Explorer._feedstock_keep_ids(inv)) is False
    # ...but a LONE ore cannot smelt, so it is not metal and the shaft still sells.
    lone = [_it("lumber", 1), _it("ore_copper", 1, uses=["smelt"])]
    assert _ss(exp, lone[0], Explorer._feedstock_keep_ids(lone)) is True


def test_an_ingot_is_KEPT_the_forge_feedstock_we_smelted_on_purpose():
    """We ran 11 smelts to turn ore into ingots and then sold two of them. An item the
    strategy spent an action creating must not be classified as pure loot."""
    exp = Explorer()
    inv = [_it("ingot_copper", 1)]
    keep = Explorer._feedstock_keep_ids(inv)
    assert _ss(exp, inv[0], keep) is False


# Deliberately duplicated here rather than imported. Iterating FORGE_FEEDSTOCK_PREFIXES
# to check FORGE_FEEDSTOCK_PREFIXES is a test derived from the structure it is checking —
# it agrees with itself no matter what the constant says, and a mutation that narrowed the
# tuple to ("lumber",) SURVIVED that version of this test. These are the concrete item
# kinds the forge chain needs, written out so the duplication IS the check.
MUST_RESERVE = ("lumber", "ingot_copper", "flux")


def test_the_kinds_the_forge_chain_needs_are_actually_reserved():
    """Named independently of the constant, so narrowing the constant fails here."""
    exp = Explorer()
    for kind in MUST_RESERVE:
        # metal present, so the shaft rule (v0.47.0) is satisfied for every kind
        inv = [_it(kind, 1), _it("ingot_tin", 9)]
        keep = Explorer._feedstock_keep_ids(inv)
        assert _ss(exp, inv[0], keep) is False, f"{kind} was not reserved"


def test_metal_itself_is_reserved_even_with_no_lumber():
    """Ingots and flux are scarce, directly forgeable, and worth almost nothing sold, so
    unlike the shaft they are reserved unconditionally — we sold 2 ingots on #113."""
    exp = Explorer()
    for kind in ("ingot_copper", "flux"):
        inv = [_it(kind, 1)]
        assert _ss(exp, inv[0], Explorer._feedstock_keep_ids(inv)) is False, kind


# ---- the bound, from both sides --------------------------------------------

def test_surplus_above_the_reserve_still_SELLS():
    """The other side of the claim. Reserving everything is the v0.19.0 carry clog, so
    only the first FORGE_RESERVE_PER_CHAR of a kind are kept."""
    exp = Explorer()
    inv = ([_it("lumber", i) for i in range(FORGE_RESERVE_PER_CHAR + 3)]
           + [_it("ingot_copper", 99)])          # metal present so the shaft is reservable
    keep = Explorer._feedstock_keep_ids(inv)
    keep = {k for k in keep if k.startswith("lumber")}
    assert len(keep) == FORGE_RESERVE_PER_CHAR
    lumber = [i for i in inv if i["kind"] == "lumber"]
    full = Explorer._feedstock_keep_ids(inv)
    kept = [i for i in lumber if not _ss(exp, i, full)]
    sold = [i for i in lumber if _ss(exp, i, full)]
    assert len(kept) == FORGE_RESERVE_PER_CHAR and len(sold) == 3


def test_the_reserve_is_PER_KIND_not_a_shared_budget():
    """Lumber and ingots are both needed to forge, so one must not crowd out the other."""
    inv = ([_it("lumber", i) for i in range(FORGE_RESERVE_PER_CHAR)]
           + [_it("ingot_copper", i) for i in range(FORGE_RESERVE_PER_CHAR)])
    keep = Explorer._feedstock_keep_ids(inv)
    assert len(keep) == 2 * FORGE_RESERVE_PER_CHAR


def test_selection_is_deterministic_so_a_replay_reproduces_it():
    inv = ([_it("lumber", i) for i in range(FORGE_RESERVE_PER_CHAR + 2)]
           + [_it("ingot_copper", 77)])
    assert Explorer._feedstock_keep_ids(inv) == Explorer._feedstock_keep_ids(inv)


# ---- the rest of the sell policy must be untouched -------------------------

def test_ordinary_loot_is_still_banked():
    """The reserve must not become a general hoarding rule — that is the regression it
    is most likely to cause."""
    exp = Explorer()
    keep = Explorer._feedstock_keep_ids([])
    assert _ss(exp, _it("bone", 1), keep) is True
    assert _ss(exp, _it("meat", 1, uses=["drink"]), keep) is True
    assert _ss(exp, _it("egg", 1, uses=["drink"]), keep) is True


def test_medicinal_drinks_and_KEEP_supplies_are_unaffected():
    exp = Explorer()
    keep = Explorer._feedstock_keep_ids([])
    assert _ss(exp, _it("potion_red", 1, uses=["drink"]), keep) is False
    assert _ss(exp, _it("potion_blue", 1, uses=["drink"]), keep) is False


def test_paired_ore_still_smelts_and_stranded_ore_still_sells():
    """Ore keeps its OWN rule (`smelt_keep`) — the feedstock branch sits after it, so a
    lone unpairable ore is still sold rather than hoarded by the new reserve."""
    exp = Explorer()
    ore = _it("ore_copper", 1, uses=["smelt"])
    keep = Explorer._feedstock_keep_ids([ore])
    assert exp._should_sell(ore, {}, brew_keep=set(), smelt_keep=set(),
                            feedstock_keep=keep) is True          # stranded -> sell
    assert exp._should_sell(ore, {}, brew_keep=set(), smelt_keep={"ore_copper-1"},
                            feedstock_keep=keep) is False         # pairable -> smelt


def test_the_old_call_signature_still_works():
    """`feedstock_keep` defaults, so callers that predate it (and the existing brewing
    tests) keep their meaning rather than silently reserving nothing-or-everything."""
    exp = Explorer()
    assert exp._should_sell(_it("bone", 1), {}, set(), set()) is True
