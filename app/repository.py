from uuid import uuid4

from app.gateway import GatewayError


class SupabaseRepository:
    """Persistence operations for Secure MCP Gateway."""

    def __init__(self, client):
        self._client = client

    def create_request(
        self,
        operation,
        config_id,
        proposed_values,
        reason,
        requested_by="mcp-client",
    ):
        request_id = f"req-{uuid4()}"

        payload = {
            "request_id": request_id,
            "operation": operation,
            "config_id": config_id,
            "proposed_values": proposed_values,
            "status": "pending",
            "reason": reason,
            "requested_by": requested_by,
        }

        response = (
            self._client.table("approval_requests")
            .insert(payload)
            .execute()
        )

        if not response.data:
            raise GatewayError("failed to persist approval request")

        return response.data[0].copy()

    def get_request(self, request_id):
        response = (
            self._client.table("approval_requests")
            .select("*")
            .eq("request_id", request_id)
            .limit(1)
            .execute()
        )

        if not response.data:
            raise GatewayError("approval request not found")

        return response.data[0].copy()

    def list_pending_requests(self):
        response = (
            self._client.table("approval_requests")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .execute()
        )

        return [request.copy() for request in response.data]

    def record_audit_event(
        self,
        event_type,
        request_id,
        actor,
        details=None,
    ):
        payload = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "request_id": request_id,
            "actor": actor,
            "details": details or {},
        }

        response = (
            self._client.table("audit_events")
            .insert(payload)
            .execute()
        )

        if not response.data:
            raise GatewayError("failed to persist audit event")

        return response.data[0].copy()

    def get_audit_log(self, request_id=None):
        query = (
            self._client.table("audit_events")
            .select("*")
            .order("created_at")
        )

        if request_id is not None:
            query = query.eq("request_id", request_id)

        response = query.execute()
        return [event.copy() for event in response.data]


    def decide_request(self, request_id, approver_id, approve):
        """Atomically approve or reject a request in PostgreSQL."""
        if not isinstance(approve, bool):
            raise GatewayError("approval decision must be a boolean")

        try:
            response = self._client.rpc(
                "decide_gateway_request",
                {
                    "p_request_id": request_id,
                    "p_approver_id": approver_id,
                    "p_approve": approve,
                },
            ).execute()
        except Exception as exc:
            # Do not expose database details or credentials to MCP clients.
            raise GatewayError(
                "database approval decision failed"
            ) from exc

        if response.data is None:
            raise GatewayError("database returned no decision result")

        return response.data

    def create_request_atomic(
        self,
        operation,
        config_id,
        proposed_values,
        reason,
    ):
        """Create a pending request and its audit event atomically."""
        if operation not in {"update", "delete"}:
            raise GatewayError("unsupported operation")

        try:
            response = self._client.rpc(
                "create_gateway_request",
                {
                    "p_operation": operation,
                    "p_config_id": config_id,
                    "p_proposed_values": proposed_values,
                    "p_reason": reason,
                },
            ).execute()
        except Exception as exc:
            raise GatewayError(
                "failed to create persistent approval request"
            ) from exc

        if not response.data:
            raise GatewayError("database returned no request result")

        return response.data
