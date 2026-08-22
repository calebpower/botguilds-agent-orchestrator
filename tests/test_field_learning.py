"""v0.68.0 — learn a spell form in the FIELD, not only in the village.

Run #146 held the whole chain up to one assumption. The character carrying `tome_field`
spent **all 10,933 of its tome-carrying frames in vale and never once entered the village**.
The learn step lived only in `village()`, so it never learned — and, worse, never earned the
`stat_requirement` refusal that v0.67.0's INT investment keys on. Nothing downstream fires
for a character that does not come home.

`use` is not a village verb: it is already how potions are drunk in the field. So the offer
belongs there too, scored to fill an idle tick and never to compete with survival.

This is the fourth time a link in this chain has been correct and unreachable (v0.54 seek,
v0.64 proof rule, v0.67 INT, now the learn step). The shape repeats: code that runs in one
place, for a character that is somewhere else.
"""
from steemer.reasoning import DecisionTrace
from steemer.strategy.base import FieldContext
from steemer.strategy.explorer import Explorer


class _Bot:
    config: dict = {}

    def __init__(self, tick=500):
        self.tick = tick
        self.storage = None

    def recently_overburdened(self, uid):
        return False

    def recently_forged(self, uid):
        return False


def _tome(kind="tome_bolt"):
    return {"kind": kind, "item_id": f"{kind}-1", "uses": ["use"]}


def _char(inv=None, spells=(), cap=1, hp=30):
    return {"char_uid": "u1", "eid": 7, "pos": [1, 1], "hp": hp, "max_hp": 30,
            "stamina": 40, "level": 3, "stats": {"int": 2}, "gifts": [],
            "carry": {"used": 2, "cap": 21}, "statuses": [],
            "spells": list(spells), "spell_cap": cap,
            "inventory": inv if inv is not None else [_tome()],
            "equipment": {"hand": {"kind": "club"}}}


def _offers(exp, char, bot=None):
    trace = DecisionTrace(tick=500, world="vale", char_uid=char["char_uid"])
    ctx = FieldContext(world="vale", known={(1, 1): "floor", (1, 2): "floor",
                                            (2, 1): "floor", (0, 1): "floor"})
    exp.act(bot or _Bot(), char, {"world": "vale", "tick": 500}, ctx, trace)
    return [(c.action or {}, c.score, c.why) for c in trace.candidates]


def _uses(offers):
    return [(a, s, w) for a, s, w in offers if a.get("action") == "use"]


# ---- it learns without going home --------------------------------------------

def test_a_field_character_carrying_a_tome_offers_to_learn_it():
    """The defect: 10,933 frames holding a tome in vale, never once home."""
    got = _uses(_offers(Explorer(), _char()))
    assert got, "a tome in the field must be learnable there"
    assert got[0][0]["item_id"] == "tome_bolt-1"


def test_it_is_scored_to_fill_an_idle_tick_not_to_compete_with_survival():
    """Below adjacent harvest (3.3) and everything urgent; above the frontier push (2.5)."""
    score = _uses(_offers(Explorer(), _char()))[0][1]
    assert 2.5 < score < 3.3


def test_a_character_at_its_spell_cap_does_not_offer():
    assert _uses(_offers(Explorer(), _char(spells=("bolt",), cap=1))) == []


def test_a_character_carrying_no_tome_does_not_offer():
    assert _uses(_offers(Explorer(), _char(inv=[{"kind": "club", "item_id": "c1"}]))) == []


def test_a_refused_tome_is_not_re_offered_in_the_field():
    """The same learn-by-rejection that governs the village step — otherwise a character
    that cannot meet the INT gate re-issues `use` every single tick it is idle."""
    exp = Explorer()
    exp._stat_total["u1"] = 6
    assert _uses(_offers(exp, _char()))
    exp.on_action_error(None, {"char_uid": "u1", "action": "use",
                               "reason": "stat_requirement"})
    assert _uses(_offers(exp, _char())) == []


def test_the_refusal_marks_the_character_as_wanting_INT():
    """The link that was never reached: a field refusal is what tells v0.67.0's XP policy
    this character needs INT. Without a field offer there is no refusal and no investment."""
    exp = Explorer()
    exp._stat_total["u1"] = 6
    _offers(exp, _char())
    exp.on_action_error(None, {"char_uid": "u1", "action": "use",
                               "reason": "stat_requirement"})
    assert exp._needs_int("u1", [_tome()]) is True


# ---- it must not fire when the character is in trouble -----------------------

def test_a_hurt_character_does_not_stop_to_read():
    """Reached only inside the safe, non-homing branch — a hurt character is heading home
    or drinking, and a spell form can wait."""
    assert _uses(_offers(Explorer(), _char(hp=5))) == []
