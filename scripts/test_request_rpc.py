
import sys
from uuid import uuid4

from app.repository import SupabaseRepository
from app.supabase_client import create_supabase_client


def main():
    client = create_supabase_client()
    repository = SupabaseRepository(client)

    config_id = f"cfg-test-{uuid4().hex[:12]}"
    request_id = None

    try:
        # Create isolated test configuration.
        client.table("config_records").insert({
            "config_id": config_id,
            "service_name": "test-service",
            "environment": "dev",
            "setting_key": "retry_limit",
            "setting_value": "3",
            "sensitive": False,
            "version": 1,
        }).execute()

        # Request creation and audit insertion happen in one RPC.
        request = repository.create_request_atomic(
            operation="update",
            config_id=config_id,
            proposed_values={"setting_value": "5"},
            reason="Testing atomic request creation",
        )
        request_id = request["request_id"]

        assert request["status"] == "pending"
        print("1. Persistent request created.")

        # Verify that the audit event was committed too.
        events = repository.get_audit_log(request_id)

        assert any(
            event["event_type"] == "update_requested"
            for event in events
        )
        print("2. Audit event verified.")

        # Ensure creating a request did not modify the record.
        record = (
            client.table("config_records")
            .select("*")
            .eq("config_id", config_id)
            .single()
            .execute()
            .data
        )

        assert record["setting_value"] == "3"
        assert record["version"] == 1
        print("3. Original configuration remains unchanged.")
        print("Real request-creation RPC test passed.")

    except Exception as exc:
        print(f"Test failed: {type(exc).__name__}: {exc}")
        sys.exit(1)

    finally:
        # Clean up only this test's data.
        try:
            if request_id:
                client.table("audit_events").delete().eq(
                    "request_id", request_id
                ).execute()

                client.table("approval_requests").delete().eq(
                    "request_id", request_id
                ).execute()

            client.table("config_records").delete().eq(
                "config_id", config_id
            ).execute()

            print("Test data cleanup completed.")

        except Exception as exc:
            print(
                f"WARNING: cleanup failed: {type(exc).__name__}: {exc}"
            )


if __name__ == "__main__":
    main()
