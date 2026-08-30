"""Pair not_in_village rejections with a same-second public-roster snapshot.
Runs ~4h, seq-tail polling only (cheap); exits with a summary line."""
import json, time, urllib.request
from steemer import db

conn = db.connect(None, readonly=True)
last = conn.execute("SELECT MAX(seq) FROM action_errors").fetchone()[0] or 0
out = open("/tmp/claude-1001/-home-cal-bots-bot-willmorrison-agent-orchestrator/e3052059-f7a8-4405-ada3-f309229a177c/scratchpad/niv_watch.jsonl", "a")
pairs = 0
t_end = time.time() + 4 * 3600
while time.time() < t_end:
    try:
        rows = conn.execute("""SELECT seq, tick, char_uid, reason FROM action_errors
            WHERE seq > ? AND reason='not_in_village' ORDER BY seq LIMIT 20""",
            (last,)).fetchall()
        mx = conn.execute("SELECT MAX(seq) FROM action_errors").fetchone()[0] or last
        if rows:
            with urllib.request.urlopen(
                    "https://bot.willmorrison.net/api/spectate/guilds", timeout=6) as r:
                dd = json.loads(r.read())
            ours = next((g for g in dd.get("guilds", [])
                         if g.get("guild_id") == "g_cd0e2a"), {})
            worlds = {c["char_uid"]: c.get("world") for c in ours.get("roster") or []}
            for s, tick, cu, reason in rows:
                rec = {"err_tick": tick, "char": cu, "api_tick": dd.get("tick"),
                       "api_world": worlds.get(cu), "wall": time.time()}
                out.write(json.dumps(rec) + "\n")
                pairs += 1
            out.flush()
        last = mx
    except Exception as e:
        out.write(json.dumps({"watch_err": str(e), "wall": time.time()}) + "\n")
        out.flush()
        try:
            conn = db.connect(None, readonly=True)
        except Exception:
            pass
    time.sleep(5)
print(f"niv_watch done: {pairs} paired rejections logged")
