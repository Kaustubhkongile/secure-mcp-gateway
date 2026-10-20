
import sys

from app.gateway import SecureGateway
from app.supabase_client import create_supabase_client


def main():
    try:
        client = create_supabase_client()
        gateway = SecureGateway(supabase_client=client)

        records = gateway.list_records(limit=10)
        print(f"Database-backed gateway returned {len(records)} records.")

        for record in records:
            print(
                f"{record['config_id']} | "
                f"{record['service_name']} | "
                f"{record['environment']}"
            )

        record = gateway.get_record("cfg-001")
        assert record["config_id"] == "cfg-001"

        print("Single-record lookup passed.")
        print("Real Supabase gateway read test passed.")

    except Exception as exc:
        # Avoid printing credentials or request headers.
        print(f"Test failed: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
