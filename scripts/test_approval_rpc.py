
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
        # Create isolated test data.
        client.table("config_records").insert({
            "config_id": config_id,
            "service_name": "test-service",
            "environment": "dev",
            "setting_key": "retry_limit",
            "setting_value": "3",
            "sensitive": False,
            "version": 1,
        }).execute()

        request = repository.create_request(
            operation="update",
            config_id=config_id,
            proposed_values={"setting_value": "5"},
            reason="Testing transactional approval",
        )
        request_id = request["request_id"]
        print("1. Pending approval request created.")

        # Ask PostgreSQL to approve the request transactionally.
        result = repository.decide_request(
            request_id=request_id,
            approver_id="local-reviewer",
            approve=True,
        )
        print("2. RPC decision:", result)

        assert result["status"] == "approved"

        # Verify the configuration change persisted.
        record = (
            client.table("config_records")
            .select("*")
            .eq("config_id", config_id)
            .single()
            .execute()
            .data
        )

        assert record["setting_value"] == "5"
        assert record["version"] == 2
        print("3. Configuration update verified.")

        # Verify the decision was audited.
        events = repository.get_audit_log(request_id)

        assert any(
            event["event_type"] == "request_approved"
            for event in events
        )
        print("4. Audit event verified.")
        print("Real Supabase approval RPC test passed.")

    except Exception as exc:
        print(f"Integration test failed: {type(exc).__name__}: {exc}")
        sys.exit(1)

    finally:
        # Remove only this test's data.
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
        except Exception as cleanup_error:
            print(
                "Warning: test data cleanup failed:",
                type(cleanup_error).__name__,
            )


if __name__ == "__main__":
    main()
