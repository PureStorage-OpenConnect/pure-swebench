#!/usr/bin/env python3
"""RETIRED: legacy W23 invalidation CLI.

W37 split comments/hints from scoring decisions:
  * note       = comments / machine hints / LLM findings; never affects ranking
  * run_exclusion = human-controlled scoring exclusion; row exists => excluded

Normal workflow is now the dashboard:
  * /run        -> add notes; mark a run valid/invalid
  * /validation -> review notes needing attention and invalid run decisions

For rare emergency/batch repair, use sqlite directly against bench-db/bench.db.
This stub intentionally does not mutate the legacy `invalidation` table; that table
is preserved only as grandfathered evidence migrated into note + run_exclusion.
"""
import sys


def main():
    msg = (__doc__ or "annotate.py retired").strip()
    print(msg, file=sys.stderr)
    if len(sys.argv) > 1 and sys.argv[1] in {"list", "show"}:
        print("\nUseful sqlite examples:", file=sys.stderr)
        print("  sqlite3 bench-db/bench.db 'select id,subject_type,subject_id,source,body from note order by id desc limit 20'", file=sys.stderr)
        print("  sqlite3 bench-db/bench.db 'select * from run_exclusion order by decided_at desc limit 20'", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
