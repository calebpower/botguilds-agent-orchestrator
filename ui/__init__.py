"""ui — a read-only web dashboard over the bot's ``guild_log.db``.

Stdlib-only (``http.server`` + ``sqlite3``), importing only the existing
:mod:`steemer` package for the schema helpers and KPI snapshot. It opens the DB
read-only (``mode=ro``) so it coexists with the live writer under WAL, and never
touches game credentials. Run it with ``uv run python ui/server.py``.
"""
