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


def test_dashboard_loads_and_renders_the_tab_shell(dashboard, page: Page):
    # the single-page app boots on an EMPTY db without throwing, and the tab bar renders.
    crashes = []
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.goto(dashboard, wait_until="domcontentloaded")
    assert "steemer" in page.title().lower()
    for tab in ("Overview", "Decisions", "Map", "Timeline", "Findings", "Logs"):
        expect(page.locator("button[data-tab]", has_text=tab)).to_be_visible()
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
