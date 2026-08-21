"""The mutation harness itself (tools/mutate.py).

Self-testing the oracle: a harness that cannot report a survivor is indistinguishable from
one that always passes, and this one DID lie for a whole session (serving a mutant's stale
bytecode after restore). So it is driven from both sides against a throwaway module, and
the restore is checked byte-for-byte.
"""
import os
import subprocess
import sys
import textwrap

import tools.mutate as mut


def _write(tmp_path, body, test_body):
    mod = tmp_path / "subject.py"
    mod.write_text(textwrap.dedent(body))
    t = tmp_path / "test_subject.py"
    t.write_text(textwrap.dedent(test_body))
    return mod, t


def test_it_reports_KILLED_when_the_test_catches_the_mutation(tmp_path, monkeypatch):
    mod, t = _write(tmp_path, "def f():\n    return 1\n",
                    "from subject import f\ndef test_f():\n    assert f() == 1\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    rc = mut.run([(str(mod), "return 1", "return 2", str(t), "f returns the wrong number")])
    assert rc == 0


def test_it_reports_SURVIVED_when_the_test_cannot_see_the_mutation(tmp_path, monkeypatch):
    """The side that matters. A harness only ever observed reporting KILLED tells you
    nothing about whether it can detect a weak test."""
    mod, t = _write(tmp_path, "def f():\n    return 1\n",
                    "from subject import f\ndef test_f():\n    assert f() is not None\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    rc = mut.run([(str(mod), "return 1", "return 2", str(t), "tautological test")])
    assert rc == 1


def test_a_missing_anchor_is_reported_not_silently_skipped(tmp_path, monkeypatch):
    """A mutant whose anchor no longer matches the source has tested NOTHING; counting it
    as killed would quietly shrink the suite as code moves."""
    mod, t = _write(tmp_path, "def f():\n    return 1\n",
                    "from subject import f\ndef test_f():\n    assert f() == 1\n")
    monkeypatch.chdir(tmp_path)
    rc = mut.run([(str(mod), "text that is not present", "x", str(t), "stale anchor")])
    assert rc == 1


def test_the_source_is_restored_byte_for_byte(tmp_path, monkeypatch):
    body = "def f():\n    return 1\n"
    mod, t = _write(tmp_path, body, "from subject import f\ndef test_f():\n    assert f() == 1\n")
    before = mod.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    mut.run([(str(mod), "return 1", "return 2", str(t), "restore check")])
    assert mod.read_bytes() == before
    assert not os.path.exists(str(mod) + ".mutbak")


def test_the_restored_file_is_newer_than_any_cached_bytecode(tmp_path, monkeypatch):
    """THE bug, encoded. shutil.move gave the restored file the BACKUP's mtime — older than
    the .pyc built from the mutant — so CPython served the mutant's bytecode afterwards."""
    mod, t = _write(tmp_path, "def f():\n    return 1\n",
                    "from subject import f\ndef test_f():\n    assert f() == 1\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    start = os.stat(mod).st_mtime
    mut.run([(str(mod), "return 1", "return 2", str(t), "mtime check")])
    assert os.stat(mod).st_mtime >= start
