"""
Verify the live Supabase schema against what the code actually writes.

supabase_client.py was built from inferred column names. A mismatch doesn't
fail at import or startup — PostgREST reports it as a 400 the moment you
write, i.e. mid-demo. This checks every table and column up front so you
find out now, in seconds, instead of then.

    python check_schema.py

Read-only: it selects, never inserts. Costs nothing. Needs SUPABASE_URL and
SUPABASE_SERVICE_KEY in .env.

The trick used here: PostgREST rejects a select naming a column that
doesn't exist, so a zero-row select is enough to prove a column is present.
That works on empty tables too.
"""
import sys

from app.supabase_client import get_client

# Exactly the columns supabase_client.py reads or writes.
REQUIRED: dict[str, list[str]] = {
    "claims": ["id", "risk_tier"],
    "intake_sessions": ["id", "claim_id", "status"],
    "extracted_fields": ["session_id", "field_name", "field_value", "confidence"],
    "contradictions": [
        "claim_id", "field_name", "claimed_value", "evidence_value",
        "verdict", "detail", "source_url", "confidence",
    ],
    "verdicts": ["claim_id", "risk_score", "risk_tier", "summary"],
    "audit_log": ["claim_id", "event_type", "payload"],
}

# Not required, but get_latest_verdict() prefers created_at for "most
# recent" and falls back to id — which only means "latest" if id is a serial.
RECOMMENDED: dict[str, list[str]] = {
    "verdicts": ["created_at"],
    "extracted_fields": ["created_at"],
    "contradictions": ["created_at"],
}


def column_exists(client, table: str, column: str) -> bool:
    try:
        client.table(table).select(column).limit(1).execute()
        return True
    except Exception:
        return False


def table_exists(client, table: str) -> bool:
    try:
        client.table(table).select("*").limit(1).execute()
        return True
    except Exception:
        return False


def main() -> int:
    client = get_client()
    if client is None:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set in .env — nothing to check.")
        print("Either get them from your teammate's project, or create your own and run schema.sql.")
        return 2

    problems: list[str] = []

    for table, columns in REQUIRED.items():
        if not table_exists(client, table):
            print(f"MISSING TABLE  {table}")
            problems.append(f"table {table} does not exist (or is not exposed via the API)")
            continue

        missing = [c for c in columns if not column_exists(client, table, c)]
        soft_missing = [c for c in RECOMMENDED.get(table, []) if not column_exists(client, table, c)]

        if missing:
            print(f"MISMATCH       {table}: missing {', '.join(missing)}")
            problems.append(f"{table} is missing {', '.join(missing)}")
        else:
            note = f"  (no {', '.join(soft_missing)} — recommended)" if soft_missing else ""
            print(f"OK             {table}{note}")

    print()
    if problems:
        print(f"{len(problems)} problem(s) found:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix by either:")
        print("  a) running schema.sql in the Supabase SQL editor, or")
        print("  b) renaming the keys in app/supabase_client.py to match the real columns.")
        print("     Only the dict keys change — no call sites move.")
        return 1

    print("Schema matches what the code writes. Storage is good to go.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
