import json

from mcp.server import MCPServer

from app.gateway import GatewayError, SecureGateway
from app.repository import SupabaseRepository
from app.supabase_client import create_supabase_client



# Create the MCP server and the gateway business-logic instance.
mcp = MCPServer(
    "Secure MCP Gateway",
    instructions=(
        "Provide controlled access to synthetic service configuration records. "
        "Updates and deletions only create pending approval requests. "
        "Never claim a requested mutation has executed."
    ),
)

supabase = create_supabase_client()
gateway = SecureGateway(supabase_client=supabase)
repository = SupabaseRepository(supabase)


@mcp.tool()
def list_records(
    service_name: str | None = None,
    environment: str | None = None,
    limit: int = 20,
) -> str:
    """List synthetic configuration records with optional filters."""
    try:
        records = gateway.list_records(
            service_name=service_name,
            environment=environment,
            limit=limit,
        )
        return json.dumps({"records": records})
    except GatewayError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def get_record(config_id: str) -> str:
    """Retrieve a synthetic configuration record by its ID."""
    try:
        record = gateway.get_record(config_id)
        return json.dumps({"record": record})
    except GatewayError as exc:
        return json.dumps({"error": str(exc)})



@mcp.tool()
def request_record_update(
    config_id: str,
    proposed_values: dict[str, str],
    reason: str,
) -> str:
    """Create a persistent update request requiring approval."""
    try:
        request = repository.create_request_atomic(
            operation="update",
            config_id=config_id,
            proposed_values=proposed_values,
            reason=reason,
        )

        return json.dumps({
            "message": "Approval required. No data was changed.",
            "request": request,
            "current_record": gateway.get_record(config_id),
        })
    except GatewayError as exc:
        return json.dumps({"error": str(exc)})
    except Exception:
        return json.dumps({"error": "request creation failed"})



@mcp.tool()
def request_record_deletion(config_id: str, reason: str) -> str:
    """Create a persistent deletion request requiring approval."""
    try:
        request = repository.create_request_atomic(
            operation="delete",
            config_id=config_id,
            proposed_values={},
            reason=reason,
        )

        return json.dumps({
            "message": "Approval required. No data was deleted.",
            "request": request,
        })
    except GatewayError as exc:
        return json.dumps({"error": str(exc)})
    except Exception:
        return json.dumps({"error": "request creation failed"})

@mcp.tool()
def get_approval_status(request_id: str) -> str:
    """Retrieve persistent approval status."""
    try:
        request = repository.get_request(request_id)
        return json.dumps({"request": request})
    except GatewayError as exc:
        return json.dumps({"error": str(exc)})
    except Exception:
        return json.dumps({"error": "failed to retrieve approval status"})

@mcp.tool()
def get_audit_log(request_id: str | None = None) -> str:
    """Read persistent audit events, optionally filtered by request ID."""
    try:
        events = repository.get_audit_log(request_id=request_id)
        return json.dumps({"events": events})
    except Exception:
        return json.dumps({"error": "failed to retrieve audit log"})


if __name__ == "__main__":
    mcp.run()
