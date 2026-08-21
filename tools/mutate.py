"""Mutation-test harness: break a thing, assert the named test FAILS, restore.

The testing ethic requires every new assertion be mutation-checked — a test never observed
failing is a test whose value is unmeasured. This is the runner for that, and it lives in
the repo rather than in a scratch script because of the bug below, which survived a whole
session precisely BECAUSE the harness was re-written ad hoc each time.

    from tools.mutate import run
    run([(path, old_text, new_text, "tests/x.py::test_y", "what this breaks"), ...])

THE BYTECODE TRAP (found 2026-08-21, and it made the harness lie):
restoring a mutated source with ``shutil.move`` gives the file the backup's mtime, which is
OLDER than the ``.pyc`` compiled from the mutant — so CPython happily served the MUTANT's
bytecode to subsequent runs. Two consecutive mutants could report each other's results, and
a harness whose whole job is to prove your tests can fail is worthless if it can silently
lie about which code ran. Symptom when it bites: source visibly says one thing, behaviour
is unmistakably the other.

Fixed with belt and braces rather than by reasoning about invalidation rules:
``PYTHONDONTWRITEBYTECODE=1`` so no .pyc is written at all, ``__pycache__`` cleared before
each mutant, ``-p no:cacheprovider`` so pytest keeps no state either, and ``os.utime`` on
the restored file so it is newer than anything that could have been cached.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from typing import Iterable, Sequence

Mutant = tuple[str, str, str, str, str]      # path, old, new, pytest selector, label


def _clear_pycache() -> None:
    for d in glob.glob("**/__pycache__", recursive=True):
        shutil.rmtree(d, ignore_errors=True)


def run(mutants: Iterable[Mutant], timeout: int = 900) -> int:
    """Apply each mutant, run its tests, restore. Returns 1 if any mutant SURVIVED.

    A survivor is not a failure of the code — it is a failure of the TEST, and usually
    means the test asserts something the mutation cannot change (a tautology, a case no
    other branch could produce, or an outcome reachable two ways).
    """
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    survivors: list[str] = []
    for path, old, new, selector, label in mutants:
        _clear_pycache()
        src = open(path).read()
        if old not in src:
            print(f"SKIP(anchor missing) {label}", flush=True)
            survivors.append(f"{label} (anchor missing)")
            continue
        shutil.copy(path, path + ".mutbak")
        open(path, "w").write(src.replace(old, new, 1))
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 *selector.split()],
                capture_output=True, text=True, timeout=timeout, env=env)
            killed = r.returncode != 0
            print(f"{'KILLED  ' if killed else 'SURVIVED'} {label}", flush=True)
            if not killed:
                survivors.append(label)
        finally:
            shutil.move(path + ".mutbak", path)
            os.utime(path, None)          # restored source must be NEWER than any cache
    _clear_pycache()
    print("\nALL MUTANTS KILLED" if not survivors
          else f"\nSURVIVORS ({len(survivors)}): {survivors}")
    return 1 if survivors else 0
