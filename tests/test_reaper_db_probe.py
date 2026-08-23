"""Connectivity canary: can this environment reach MariaDB over the LAN as reaper_ro?

Written when the operator exposed the DB for reaper-hosted model training (2026-08-23).
Runs anywhere: on the workstation it proves the non-localhost bind path; inside a reaper
VM it proves the training session's actual route (VM -> LAN -> MariaDB, SELECT-only).
Skips without failing when the git-ignored credential file is absent (fresh clones, CI
without the secret) — absence of credentials is not a connectivity defect.
"""
import os

import pytest

CREDS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "reaper_db.toml")


def _creds():
    import tomllib
    with open(CREDS, "rb") as fh:
        return tomllib.load(fh)


@pytest.mark.skipif(not os.path.exists(CREDS), reason="no reaper_db.toml (secret not synced)")
def test_reaper_ro_can_reach_mariadb_over_the_lan():
    import mysql.connector
    c = _creds()
    conn = mysql.connector.connect(host=c["host"], port=c["port"], user=c["user"],
                                   password=c["password"], database=c["database"],
                                   connection_timeout=8)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM runs")
    (n,) = cur.fetchone()
    assert n > 0, "connected but the schema looks empty"
    # SELECT-only, verified from the inside: a write must be refused.
    with pytest.raises(mysql.connector.Error):
        cur.execute("CREATE TABLE _reaper_probe (x INT)")
    conn.close()
