"""End-to-end tests for the two supervision defects found on 2026-08-21.

Both are shell, and both were invisible in exactly the way that makes an outage long:

1. `svc.sh down` signalled `-$pid`, but under daemon(8) the pidfile records the CHILD
   while the process-group LEADER is daemon itself. `kill -- -$child` targets a group
   that does not exist, so the fallback killed only run-live.sh and left `uv`/python
   playing on — the "svc.sh down bot leaves steemer.runner alive" gotcha, and the
   kick-wars that followed a redeploy.
2. `run-live.sh` respawned a segfaulting runner forever in silence, so a bot that had
   not written a frame in an hour still looked "up".

Each test drives the real script; none of them touch the live services (everything runs
against a COPY of the script in a tmpdir, which is where its `cd $(dirname $0)` lands).
"""
import os
import shutil
import subprocess
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# svc.sh resolves process groups and ownership through ps(1). Where ps is missing (a slim
# container), svc.sh refuses to act -- correct, but it means these tests would be asserting
# the refusal, not the logic. Skip explicitly and say so, rather than pass vacuously. The
# reaper gate installs procps precisely so this never skips there.
_HAVE_PS = subprocess.run(["sh", "-c", "ps -o pid= -p $$"],
                          capture_output=True).returncode == 0
needs_ps = pytest.mark.skipif(
    not _HAVE_PS, reason="ps(1) unavailable: svc.sh's group/ownership logic is unreachable")


def _copy(script, tmp_path):
    dst = tmp_path / os.path.basename(script)
    shutil.copy(os.path.join(ROOT, script), dst)
    os.chmod(dst, 0o755)
    (tmp_path / "run").mkdir(exist_ok=True)
    return dst


# --------------------------------------------------------------------------- #
# 1. svc.sh must resolve the real process GROUP, not assume pid == pgid
# --------------------------------------------------------------------------- #

@pytest.fixture
def group_leader():
    """A detached process group: a leader plus a child, mirroring daemon(8)+run-live.sh.

    `start_new_session=True` makes the leader a session/group leader, so its child's pgid
    is the LEADER's pid and differs from the child's own pid — the precise shape that
    broke the old `kill -- -$pid`.
    """
    leader = subprocess.Popen(["sh", "-c", "sleep 30 & sleep 30"], start_new_session=True)
    time.sleep(0.7)
    yield leader
    try:
        os.killpg(os.getpgid(leader.pid), 9)
    except OSError:
        pass
    leader.wait(timeout=5)


@needs_ps
def test_svc_pgid_resolves_the_group_leader_not_the_recorded_pid(tmp_path, group_leader):
    child = subprocess.run(["ps", "-axo", "pid,ppid"], capture_output=True, text=True)
    kids = [int(l.split()[0]) for l in child.stdout.splitlines()[1:]
            if len(l.split()) == 2 and l.split()[1].isdigit()
            and int(l.split()[1]) == group_leader.pid]
    assert kids, "fixture produced no child process"
    kid = kids[0]
    real_pgid = os.getpgid(kid)
    # The bug in one line: the child's own pid is NOT its process group.
    assert real_pgid != kid, "fixture did not reproduce the pid != pgid shape"

    svc = _copy("svc.sh", tmp_path)
    (tmp_path / "run" / "watch.pid").write_text(str(kid))
    r = subprocess.run([str(svc), "pgid", "watch"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(real_pgid), (
        f"svc.sh resolved {r.stdout.strip()}, but the group is {real_pgid} "
        f"(recorded pid was {kid}) — a group signal would miss the workers")


@needs_ps
def test_svc_down_refuses_a_pidfile_that_is_not_ours(tmp_path):
    """A stale pidfile whose pid the OS recycled must NOT get a whole process tree killed.

    Without the marker guard, `down` would signal the group of whatever now owns that pid.
    """
    # start_new_session: keep the victim in a session of its own. Sharing the test
    # runner's process group would let a MUTATED svc.sh (guard removed) signal pytest --
    # which is exactly what happened the first time this was mutation-checked.
    victim = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        svc = _copy("svc.sh", tmp_path)
        (tmp_path / "run" / "watch.pid").write_text(str(victim.pid))
        r = subprocess.run([str(svc), "down", "watch"], capture_output=True, text=True)
        assert r.returncode == 1
        assert "not ours" in r.stderr
        # Two oracles for the claim "we did not kill it": the process is still alive AND
        # it has not reaped an exit status.
        assert victim.poll() is None
        assert os.path.exists(f"/proc/{victim.pid}") or _alive(victim.pid)
        # ...and the misleading pidfile is cleared rather than left to mislead again.
        assert not (tmp_path / "run" / "watch.pid").exists()
    finally:
        victim.kill()
        victim.wait(timeout=5)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@needs_ps
def test_svc_down_refuses_to_signal_its_own_process_group(tmp_path):
    """Defence in depth behind the marker guard: even for a pidfile that LOOKS like ours,
    `down` must not signal the group it is itself running in.

    The whole thing runs inside its own session, so the blast radius of a regression here
    is this test's session -- not the suite. The victim's command line carries the `watch`
    service marker, so the marker guard passes and this guard is the only thing left.
    """
    svc = _copy("svc.sh", tmp_path)
    # >/dev/null on the background job: it would otherwise inherit the pipe and hold it
    # open for its whole life, so communicate() could never see EOF.
    # `; :` defeats sh's single-command exec optimisation, which would otherwise replace
    # the shell with `sleep 30` and drop the $0 that carries the service marker.
    script = (f"sh -c 'sleep 30; :' healthcheck.py >/dev/null 2>&1 & echo $! > run/watch.pid; "
              f"exec {svc} down watch")
    p = subprocess.Popen(["sh", "-c", script], cwd=tmp_path, start_new_session=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=30)
    try:
        assert p.returncode == 1, f"expected a refusal, got {p.returncode}: {out} {err}"
        assert "shares MY process group" in err
        victim = int((tmp_path / "run" / "watch.pid").read_text().strip())
        assert _alive(victim), "svc.sh killed a process in its own group"
    finally:
        try:
            pid = int((tmp_path / "run" / "watch.pid").read_text().strip())
            os.killpg(os.getpgid(pid), 9)
        except (OSError, ValueError, FileNotFoundError):
            pass


def test_svc_down_without_ps_refuses_instead_of_reporting_a_live_service_stale(tmp_path):
    """The gate's own find: with no ps(1), `down` used to print "stale ... pid gone" for a
    process that was very much alive, stop nothing, and exit 0 — a stop command failing
    OPEN while reporting success. Existence must come from `kill -0`, not from ps.

    Simulated by shadowing ps with a stub that always fails, which is what an absent
    binary looks like to the script.
    """
    victim = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        svc = _copy("svc.sh", tmp_path)
        binp = tmp_path / "nops"
        binp.mkdir()
        (binp / "ps").write_text("#!/bin/sh\nexit 1\n")
        os.chmod(binp / "ps", 0o755)
        (tmp_path / "run" / "watch.pid").write_text(str(victim.pid))
        env = dict(os.environ, PATH=f"{binp}:{os.environ['PATH']}")
        r = subprocess.run([str(svc), "down", "watch"], capture_output=True, text=True,
                           env=env, timeout=30)
        assert r.returncode == 1, f"expected a refusal, got {r.returncode}: {r.stdout}"
        assert "ps(1) is unavailable" in r.stderr
        assert "stale" not in r.stdout, "a live process was reported as a stale pidfile"
        # Two oracles that it really was left alone: still alive, and its pidfile kept
        # (removing it would strand the service beyond any later `down`).
        assert _alive(victim.pid)
        assert (tmp_path / "run" / "watch.pid").exists()
    finally:
        victim.kill()
        victim.wait(timeout=5)


def test_svc_down_reports_a_missing_process_as_stale(tmp_path):
    svc = _copy("svc.sh", tmp_path)
    # A pid that certainly does not exist (max_pid+ ; reserved range on every unix here).
    (tmp_path / "run" / "watch.pid").write_text("999999")
    r = subprocess.run([str(svc), "down", "watch"], capture_output=True, text=True)
    assert r.returncode == 0 and "stale" in r.stdout


# --------------------------------------------------------------------------- #
# 2. run-live.sh must make a crash-LOOP visible instead of respawning in silence
# --------------------------------------------------------------------------- #

def _runlive_env(tmp_path, uv_body, **extra):
    """A copy of run-live.sh whose `uv` is a stub — so the loop's own behaviour is under
    test without ever launching the real runner or touching the live DB."""
    _copy("run-live.sh", tmp_path)
    binp = tmp_path / "bin"
    binp.mkdir(exist_ok=True)
    uv = binp / "uv"
    uv.write_text("#!/bin/sh\n" + uv_body + "\n")
    os.chmod(uv, 0o755)
    env = dict(os.environ, PATH=f"{binp}:{os.environ['PATH']}", **extra)
    return env


def test_a_fast_crash_loop_writes_the_marker(tmp_path):
    """THE regression: a runner that segfaults on every start used to leave no trace but a
    log line, so `svc.sh status` reported a healthy bot for as long as nobody looked."""
    env = _runlive_env(tmp_path, "exit 139",
                       STEEMER_CRASHLOOP_N="2", STEEMER_FAST_FAIL_S="20")
    p = subprocess.Popen(["./run-live.sh"], cwd=tmp_path, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    marker = tmp_path / "run" / "bot.crashloop"
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not marker.exists():
            time.sleep(0.2)
        assert marker.exists(), "no crash-loop marker after repeated instant failures"
        body = marker.read_text()
        assert "exit=139" in body and "consecutive_fast_failures=" in body
    finally:
        p.kill()
        p.wait(timeout=5)


def test_a_runner_that_actually_RUNS_never_trips_the_marker(tmp_path):
    """The other side of the oracle. A crash after a real stretch of play is not a loop;
    marking it would make the signal worthless."""
    env = _runlive_env(tmp_path, "sleep 2; exit 1",
                       STEEMER_CRASHLOOP_N="2", STEEMER_FAST_FAIL_S="1")
    p = subprocess.Popen(["./run-live.sh"], cwd=tmp_path, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(9)          # several restarts, each living longer than FAST_FAIL_S
        assert not (tmp_path / "run" / "bot.crashloop").exists()
    finally:
        p.kill()
        p.wait(timeout=5)


def test_a_real_run_RESETS_the_fast_failure_count(tmp_path):
    """A successful stretch of play must clear the tally, not merely fail to add to it.

    Without the reset the counter is a lifetime total, so unrelated crashes hours apart
    accumulate into a false 'crash-loop' -- and the marker stops meaning anything.
    Sequence below: 2 fast failures, then a real run, then 1 more fast failure. That is 3
    fast failures in total (== CRASHLOOP_N) but never 3 in a ROW, so a correct supervisor
    stays quiet and an un-reset one marks.
    """
    stub = (
        'n=$(cat attempts 2>/dev/null || echo 0); n=$((n + 1)); echo $n > attempts\n'
        'if [ "$n" -le 2 ]; then exit 1; fi\n'          # two instant failures
        'if [ "$n" -eq 4 ]; then exit 1; fi\n'          # one more, after a real run
        'sleep 3; exit 1\n'                             # every other attempt really runs
    )
    env = _runlive_env(tmp_path, stub, STEEMER_CRASHLOOP_N="3", STEEMER_FAST_FAIL_S="2")
    p = subprocess.Popen(["./run-live.sh"], cwd=tmp_path, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        def _attempts():
            # Guarded: the stub has not run yet on the first poll, and can be caught
            # mid-write; neither is a test failure.
            try:
                return int((tmp_path / "attempts").read_text().strip() or 0)
            except (FileNotFoundError, ValueError):
                return 0

        deadline = time.time() + 40
        while time.time() < deadline and _attempts() < 5:
            time.sleep(0.3)
        assert _attempts() >= 5, f"stub only reached attempt {_attempts()}"
        assert not (tmp_path / "run" / "bot.crashloop").exists(), (
            "3 fast failures spread across real runs were counted as a crash-loop")
    finally:
        p.kill()
        p.wait(timeout=5)


def test_a_clean_exit_stops_the_supervisor_and_clears_the_marker(tmp_path):
    env = _runlive_env(tmp_path, "exit 0")
    (tmp_path / "run").mkdir(exist_ok=True)
    (tmp_path / "run" / "bot.crashloop").write_text("stale marker from a past episode\n")
    r = subprocess.run(["./run-live.sh"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "supervisor stopping" in r.stdout
    assert not (tmp_path / "run" / "bot.crashloop").exists()


def test_the_supervisor_clears_a_STALE_crashloop_marker(tmp_path, monkeypatch):
    """run-live.sh writes run/bot.crashloop on repeated fast failures, but only clears it
    when the runner next EXITS having played — so a bot that recovered and has been healthy
    for hours still reports CRASH-LOOP. Seen for real after the v0.51.0 revert: run #128 was
    writing frames at 0.3s staleness while `svc.sh status bot` still announced a crash-loop
    from an hour earlier.

    The supervisor checks frame freshness every pass, which IS the evidence, so it clears it.
    """
    import tools.healthcheck as hc

    marker = tmp_path / "run" / "bot.crashloop"
    marker.parent.mkdir(parents=True)
    marker.write_text("2026-08-21 11:05:54 exit=139 consecutive_fast_failures=5\n")
    monkeypatch.setattr(hc, "ROOT", str(tmp_path))
    monkeypatch.setattr(hc.db, "connect", lambda *a, **k: _NullConn())
    monkeypatch.setattr(hc.health, "collect", lambda *a, **k: {
        "bot": {"ok": True, "level": "ok", "status": "alive", "age_s": 0.3},
        "web": {"ok": True, "level": "ok", "status": "alive", "age_s": 1.0},
        "dash": {"ok": True, "level": "ok", "status": "listening", "age_s": None}})
    hc.one_pass(fix=False, dry_run=True, last_restart_at={}, dash_port=1, cooldown_s=1)
    assert not marker.exists(), "a healthy bot still carried a crash-loop marker"


def test_the_supervisor_does_NOT_clear_the_marker_while_the_bot_is_DEAD(tmp_path, monkeypatch):
    """The other side, and the one that matters: the marker is how a human finds out a
    crash-loop happened. Clearing it while the bot is still down would erase the only
    breadcrumb."""
    import tools.healthcheck as hc

    marker = tmp_path / "run" / "bot.crashloop"
    marker.parent.mkdir(parents=True)
    marker.write_text("exit=139\n")
    monkeypatch.setattr(hc, "ROOT", str(tmp_path))
    monkeypatch.setattr(hc.db, "connect", lambda *a, **k: _NullConn())
    monkeypatch.setattr(hc.health, "collect", lambda *a, **k: {
        "bot": {"ok": False, "level": "critical", "status": "dead", "age_s": 9000},
        "web": {"ok": True, "level": "ok", "status": "alive", "age_s": 1.0},
        "dash": {"ok": True, "level": "ok", "status": "listening", "age_s": None}})
    monkeypatch.setattr(hc.health, "smoke_venv", lambda *a, **k: {"ok": True, "detail": "x"})
    hc.one_pass(fix=False, dry_run=True, last_restart_at={}, dash_port=1, cooldown_s=1)
    assert marker.exists(), "the crash-loop breadcrumb was erased while the bot was down"


class _NullConn:
    def execute(self, *a, **k):
        class _C:
            def fetchone(self): return None
            def fetchall(self): return []
        return _C()
    def close(self): pass
