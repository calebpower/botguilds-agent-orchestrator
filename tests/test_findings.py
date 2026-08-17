"""The lab-notebook schema: validation discipline, append, and robust load."""

import json

import pytest

from steemer import findings


def test_validate_accepts_well_formed():
    assert findings.validate(
        {"kind": "discovery", "status": "confirmed", "title": "x", "evidence": "seen"}) is None
    assert findings.validate(
        {"kind": "conjecture", "status": "open", "title": "y",
         "test": "cast and read weave", "confidence": "medium"}) is None
    assert findings.validate(
        {"kind": "consideration", "status": "open", "title": "z"}) is None


def test_validate_rejects_bad_shapes():
    assert findings.validate({"kind": "x", "status": "open", "title": "t"}) == "bad_kind"
    assert findings.validate({"kind": "discovery", "status": "x", "title": "t"}) == "bad_status"
    assert findings.validate({"kind": "discovery", "status": "open"}) == "missing_title"


def test_conjecture_requires_test_and_confidence():
    # a conjecture without a falsification test is just noise
    assert findings.validate(
        {"kind": "conjecture", "status": "open", "title": "t", "confidence": "low"}
    ) == "conjecture_needs_test"
    assert findings.validate(
        {"kind": "conjecture", "status": "open", "title": "t", "test": "do X"}
    ) == "conjecture_needs_confidence"


def test_confirmed_discovery_requires_evidence():
    assert findings.validate(
        {"kind": "discovery", "status": "confirmed", "title": "t"}
    ) == "confirmed_discovery_needs_evidence"
    # an *open* discovery need not have evidence yet
    assert findings.validate(
        {"kind": "discovery", "status": "open", "title": "t"}) is None


def test_append_stamps_timestamps_and_roundtrips(tmp_path):
    p = str(tmp_path / "f.jsonl")
    findings.append({"kind": "consideration", "status": "open",
                     "title": "specialize per map"}, path=p)
    rows = findings.load(p)
    assert len(rows) == 1
    assert rows[0]["title"] == "specialize per map"
    assert rows[0]["created"] and rows[0]["updated"]
    assert rows[0]["tags"] == []


def test_append_refuses_invalid(tmp_path):
    p = str(tmp_path / "f.jsonl")
    with pytest.raises(ValueError):
        findings.append({"kind": "conjecture", "status": "open", "title": "no test"}, path=p)
    assert findings.load(p) == []       # nothing written


def test_load_skips_malformed_lines(tmp_path):
    p = tmp_path / "f.jsonl"
    p.write_text('{"kind":"discovery","status":"open","title":"ok"}\n'
                 'not json at all\n'
                 '\n'
                 '{"kind":"consideration","status":"open","title":"ok2"}\n')
    rows = findings.load(str(p))
    assert [r["title"] for r in rows] == ["ok", "ok2"]
