"""Re-run every number the loop has reported to the operator. Run this each pass.

`uv run python tools/recheck_claims.py`
"""
import sys

import steemer.db as db
import steemer.claims as claims


def main() -> int:
    conn = db.connect(None, readonly=True)
    try:
        results = claims.recheck(conn)
    finally:
        conn.close()
    print(claims.summarise(results))
    return 1 if any(r["status"] == "contradicted" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
