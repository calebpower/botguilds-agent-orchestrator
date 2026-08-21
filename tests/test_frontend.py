"""Frontend (dashboard) smoke tests, driven with Playwright.

The workstation is FreeBSD, where Playwright browsers do not run — so these are
``importorskip``-guarded and simply SKIP locally. They run in the reaper gate
(Linux container), which installs the ``frontend`` dependency group + a chromium
browser, so the dashboard UI is exercised end-to-end before a redeploy even though
it can't be launched on the workstation.

Each test launches the real ``ui/server.py`` against an empty SQLite DB (the
dashboard's documented "no data yet" empty state) and drives it with a headless
browser.
"""
import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("playwright")  # FreeBSD workstation: no browser -> skip locally
from playwright.sync_api import Page, expect  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def dashboard(tmp_path_factory):
    """Launch ui/server.py on a free port against an empty DB; yield its base URL."""
    port = _free_port()
    db = tmp_path_factory.mktemp("fe") / "d.db"
    proc = subprocess.Popen(
        [sys.executable, "ui/server.py", "--host", "127.0.0.1",
         "--port", str(port), "--db", str(db)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # wait for the port to accept connections
    for _ in range(150):
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"dashboard exited early (code {proc.returncode}):\n{out}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("dashboard did not open its port in time")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def _seed_char_db(path):
    """A minimal SQLite mirror with one field frame carrying a character, so the
    Party panel has real per-char data to render."""
    import json as _json
    import time
    import zlib
    from steemer import db as _db
    conn = _db.connect({"type": "sqlite", "path": str(path)})
    _db.apply_schema(conn)
    frame = {
        "world": "mines", "tick": 100,
        "guild": {"gold": 500, "chars_here": [], "chars_by_world": {"mines": ["c1"]}},
        "chars": [{
            "char_uid": "c1", "name": "Recruit-1", "pos": [10, 5],
            "hp": 12, "max_hp": 24, "stamina": 30, "max_stamina": 60,
            "level": 3, "xp": 42, "stats": {"str": 2, "vit": 4, "agi": 3},
            "gifts": ["agi"], "equipment": {"hand": "club", "outfit": None},
            "inventory": [{"kind": "potion_red"}, {"kind": "tome"}],
            "carry": {"used": 5, "cap": 20}, "status": [{"kind": "poison"}],
        }],
    }
    conn.execute(
        "INSERT INTO frames (tick, world, received_at, run_id, json) VALUES (?,?,?,?,?)",
        (100, "mines", time.time(), 1, zlib.compress(_json.dumps(frame).encode())))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def dashboard_with_char(tmp_path_factory):
    port = _free_port()
    db = tmp_path_factory.mktemp("fe2") / "d.db"
    _seed_char_db(db)
    proc = subprocess.Popen(
        [sys.executable, "ui/server.py", "--host", "127.0.0.1",
         "--port", str(port), "--db", str(db)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(150):
        if proc.poll() is not None:
            pytest.fail(f"dashboard exited early:\n{proc.stdout.read() if proc.stdout else ''}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("dashboard did not open its port in time")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def _seed_heatmap_db(path):
    """A minimal mirror for the Map heat overlay: tiles (map bounds), a frame with our
    char standing on a tile (OCCUPANCY, so the survivor-bias-corrected 'danger' layer is
    computable), and a death on that same tile (deaths/time -> a finite danger value)."""
    import json as _json
    import time as _time
    import zlib as _zlib
    from steemer import db as _db
    conn = _db.connect({"type": "sqlite", "path": str(path)})
    _db.apply_schema(conn)
    for (x, y) in [(0, 0), (5, 8), (9, 9)]:            # tiles_seen -> world bounds 10x10
        conn.execute("INSERT INTO tiles_seen (world, x, y, kind) VALUES (?,?,?,?)",
                     ("mines", x, y, "floor"))
    frame = {"world": "mines", "tick": 60, "bounds": [10, 10], "guild": {"gold": 100},
             "chars": [{"char_uid": "c1", "pos": [5, 8], "hp": 20, "max_hp": 24, "level": 3,
                        "inventory": [{"kind": "egg"}]}],
             "visible": {"tiles": [[5, 8, "floor"]], "gold": [],
                         "entities": [{"eid": 1, "kind": "wolf", "pos": [6, 8],
                                       "faction": "monster", "hp_frac": 1.0}],
                         "items": [{"kind": "egg", "pos": [7, 8]}]}}
    conn.execute("INSERT INTO frames (tick, world, received_at, run_id, json) VALUES (?,?,?,?,?)",
                 (60, "mines", _time.time(), 1, _zlib.compress(_json.dumps(frame).encode())))
    conn.execute(
        "INSERT INTO events (tick, world, kind, payload_json, run_id) VALUES (?,?,?,?,?)",
        (50, "mines", "death",
         _json.dumps({"char_uid": "c1", "pos": [5, 8], "guild_id": "g_cd0e2a"}), 1))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def dashboard_with_heatmap(tmp_path_factory):
    port = _free_port()
    db = tmp_path_factory.mktemp("fe3") / "d.db"
    _seed_heatmap_db(db)
    proc = subprocess.Popen(
        [sys.executable, "ui/server.py", "--host", "127.0.0.1",
         "--port", str(port), "--db", str(db)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(150):
        if proc.poll() is not None:
            pytest.fail(f"dashboard exited early:\n{proc.stdout.read() if proc.stdout else ''}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("dashboard did not open its port in time")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def test_codex_tab_populates_its_sections(dashboard_with_heatmap, page: Page):
    # the Codex auto-builds from current data: the seeded wolf (predator), mines land, egg
    # item, and the docs-based mechanics all appear across the four sub-panes.
    crashes = []
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.goto(dashboard_with_heatmap, wait_until="domcontentloaded")
    page.locator("button[data-tab='codex']").click()
    expect(page.locator("#tab-codex")).to_be_visible()
    expect(page.locator("#cx-monsters")).to_contain_text("wolf")               # Monsters (default)
    expect(page.locator("#cx-monsters .cls-predator").first).to_contain_text("predator")
    page.locator("#tab-codex .cx-btn[data-cx='lands']").click()
    expect(page.locator("#cx-lands")).to_contain_text("mines")                 # Lands
    page.locator("#tab-codex .cx-btn[data-cx='items']").click()
    expect(page.locator("#cx-items")).to_contain_text("egg")                   # Items
    page.locator("#tab-codex .cx-btn[data-cx='mechanics']").click()
    expect(page.locator("#cx-mechanics")).to_contain_text("Game rules")        # Mechanics (docs)
    assert crashes == [], f"uncaught JS errors: {crashes}"


def test_nav_tab_explains_the_rules_and_the_recorded_ladder(dashboard, page: Page):
    # The explainer is DERIVED, so this asserts both derivations reach the page: the map
    # rules come out of steemer/nav.py (its SOLID vocabulary and a real docstring), and
    # the empty-DB case still renders them -- a fresh checkout with no history must still
    # be able to explain how navigation works. The ladder half is unit-tested against
    # seeded traces in tests/test_nav_explainer.py; here it must merely not crash.
    crashes = []
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.goto(dashboard, wait_until="domcontentloaded")
    page.locator("button[data-tab='nav']").click()
    expect(page.locator("#tab-nav")).to_be_visible()
    expect(page.locator("#nav-rules")).to_contain_text("Blocking tiles")
    expect(page.locator("#nav-rules")).to_contain_text("vein")        # from nav.SOLID
    expect(page.locator("#nav-rules")).to_contain_text("walkable")    # from a real docstring
    expect(page.locator("#nav-ladder")).to_contain_text("priority ladder")
    assert crashes == [], f"uncaught JS errors: {crashes}"


def test_codex_frontier_pane_shows_coverage_and_the_untried_cells(dashboard, page: Page):
    """The Frontier pane renders off an EMPTY database: the vocabulary fixture is committed,
    so the cube and the never-sent verb list exist even with no history — which is also the
    state a fresh checkout is in.

    Asserts the three redundant encodings the palette validator obliged: the legend, the
    glyph, and the frontier table. The status tint alone may not carry meaning (frontier
    amber measured 1.79:1 against the light surface, below 3:1).
    """
    crashes = []
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.goto(dashboard, wait_until="domcontentloaded")
    page.locator("button[data-tab='codex']").click()
    page.locator("#tab-codex .cx-btn[data-cx='frontier']").click()
    expect(page.locator("#cx-frontier")).to_be_visible()
    expect(page.locator("#cx-frontier")).to_contain_text("never been sent")
    expect(page.locator("#cx-frontier")).to_contain_text("The frontier")
    expect(page.locator("#cx-frontier .fr-legend")).to_contain_text("never tried, plausible")
    expect(page.locator("#cx-frontier .fr-bar i").first).to_be_visible()
    assert crashes == [], f"uncaught JS errors: {crashes}"


def test_map_danger_overlay_is_survivor_bias_corrected(dashboard_with_heatmap, page: Page):
    # the heatmap is now a MAP OVERLAY. Selecting the Danger layer fetches /api/heatmap and
    # paints it over the map; #hm-info reports the corrected 'danger = deaths/time' metric
    # (not a raw count) — proving the overlay + the occupancy normalisation are wired.
    crashes = []
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.goto(dashboard_with_heatmap, wait_until="domcontentloaded")
    page.locator("button[data-tab='map']").click()
    expect(page.locator("#tab-map")).to_be_visible()
    page.locator("#m-overlay").select_option("danger")     # -> ensureHeat() fetch + repaint
    expect(page.locator("#hm-info")).to_contain_text("danger")
    expect(page.locator("#hm-info")).to_contain_text("tiles")
    assert crashes == [], f"uncaught JS errors: {crashes}"


def test_party_panel_renders_character_cards(dashboard_with_char, page: Page):
    # the operator's per-character stats panel: clicking Party shows a card per char
    # with a live HP bar, and a poison status chip for a poisoned char.
    page.goto(dashboard_with_char, wait_until="domcontentloaded")
    page.locator("button[data-tab='party']").click()
    card = page.locator("#party-cards .pc")
    expect(card).to_have_count(1)
    expect(card).to_contain_text("Recruit-1")
    expect(card.locator(".bar")).to_have_count(2)          # HP + stamina bars
    expect(card.locator(".chip.pois")).to_contain_text("poison")   # status chip
    # v0.39.0 per-char role chip: the seeded char is level 3 (< GUARDIAN_LEVEL) -> forager
    expect(card.locator(".pc-role.role-forager")).to_contain_text("forager")


def test_timeline_story_mode_narrates_versions(dashboard, page: Page):
    # story mode reads the findings notebook (not the DB), so the empty-db dashboard is
    # fine. Clicking Timeline must render per-version nodes, each carrying a "shipped"
    # hypothesis tag — proves /api/story + renderStory are wired, not a blank card.
    page.goto(dashboard, wait_until="domcontentloaded")
    page.locator("button[data-tab='timeline']").click()
    expect(page.locator("#tab-timeline")).to_be_visible()
    expect(page.locator("#tl-story .sv").first).to_be_visible()   # >=1 version node
    expect(page.locator("#tl-story")).to_contain_text("explorer/")
    expect(page.locator("#tl-story .sv-tag.hyp").first).to_contain_text("shipped")


def test_dashboard_loads_and_renders_the_tab_shell(dashboard, page: Page):
    # the single-page app boots on an EMPTY db without throwing, and the tab bar renders.
    crashes = []
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.goto(dashboard, wait_until="domcontentloaded")
    assert "steemer" in page.title().lower()
    # match by the exact data-tab attribute, not display text — "Map" would substring-match
    # the "Heatmap" button and make the locator ambiguous.
    for tab in ("overview", "party", "decisions", "map", "codex",
                "timeline", "findings", "logs"):
        expect(page.locator(f"button[data-tab='{tab}']")).to_be_visible()
    # an empty db must render the empty state, not crash the JS
    page.wait_for_timeout(500)
    assert crashes == [], f"uncaught JS errors on load: {crashes}"


def test_dashboard_tab_switch_works(dashboard, page: Page):
    # clicking a tab reveals its section and hides the previous one — proves the app is
    # interactive, not a static shell (the hook every future panel test builds on).
    page.goto(dashboard, wait_until="domcontentloaded")
    expect(page.locator("#tab-overview")).to_be_visible()
    page.locator("button[data-tab='decisions']").click()
    expect(page.locator("#tab-decisions")).to_be_visible()
    expect(page.locator("#tab-overview")).to_be_hidden()
