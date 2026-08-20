#!/bin/sh
# set-guild-color.sh — POST an ARBITRARY value to /api/guild/color using this guild's
# WRITE credentials, WITHOUT validating the value client-side. For testing whether the
# *server* validates the guild colour (see server_bugs.md SEC-3: the web client renders
# the colour into element.style.background, so an unvalidated value like url(...) would
# be a stored CSS-injection).
#
# The value you pass is sent verbatim as the JSON "color" string — the only processing
# is JSON-escaping so the request stays well-formed. Nothing about the colour itself is
# checked. It prints the login status and the /api/guild/color response + HTTP code so
# you can see whether the server accepted it; then load the spectate page to see how it
# renders. Reset any time with a normal hex, e.g.  ./tools/set-guild-color.sh '#80ff00'
#
# Usage:
#   ./tools/set-guild-color.sh '<colour value>'
# Examples:
#   ./tools/set-guild-color.sh '#ff0000'
#   ./tools/set-guild-color.sh 'url(https://example.com/pixel.png)'
#   ./tools/set-guild-color.sh 'red; background-image: url(//example.com/x)'
#
# Credentials come from guild_token.json (override with GUILD_TOKEN_FILE=...); the HTTPS
# host is derived from that file's `server` (tcp://host:port -> https://host).
set -eu

TOKEN_FILE="${GUILD_TOKEN_FILE:-guild_token.json}"
[ "$#" -ge 1 ] || { echo "usage: $0 '<colour value>'" >&2; exit 2; }
COLOR="$1"

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"   # repo root (so guild_token.json resolves)
[ -f "$TOKEN_FILE" ] || { echo "no $TOKEN_FILE (set GUILD_TOKEN_FILE=...)" >&2; exit 1; }

# guild_id + token + https base, straight from the token file. (token is used but never printed)
eval "$(uv run python - "$TOKEN_FILE" <<'PY'
import json, sys, shlex
from urllib.parse import urlparse
d = json.load(open(sys.argv[1]))
host = urlparse(d.get("server", "")).hostname or "bot.willmorrison.net"
print("GUILD_ID=" + shlex.quote(d["guild_id"]))
print("TOKEN="    + shlex.quote(d["token"]))
print("BASE="     + shlex.quote("https://" + host))
PY
)"

COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT

# 1) login -> session cookie (same creds as the ZeroMQ hello)
login_body="$(uv run python -c 'import json,sys; print(json.dumps({"guild_id":sys.argv[1],"token":sys.argv[2]}))' "$GUILD_ID" "$TOKEN")"
echo "== POST $BASE/api/login (guild $GUILD_ID) =="
curl -sS -c "$COOKIES" -H 'content-type: application/json' \
     --data-binary "$login_body" -w '\n-> HTTP %{http_code}\n' "$BASE/api/login" || true

# 2) POST the RAW colour value with the session cookie (no colour validation)
color_body="$(uv run python -c 'import json,sys; print(json.dumps({"color":sys.argv[1]}))' "$COLOR")"
echo
echo "== POST $BASE/api/guild/color  color=[$COLOR] =="
curl -sS -b "$COOKIES" -H 'content-type: application/json' \
     --data-binary "$color_body" -w '\n-> HTTP %{http_code}\n' "$BASE/api/guild/color" || true
