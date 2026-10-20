from uuid import uuid4
from datetime import datetime, timezone


class GatewayError(Exception):
    """Raised when a gateway operation violates its rules."""


class SecureGateway:
    """Controls access to synthetic service configuration records."""

    ALLOWED_UPDATE_FIELDS = {"setting_value"}
    MAX_REASON_LENGTH = 500

    # Trusted identities for local development only.
    APPROVED_APPROVER_IDS = {"local-reviewer"}

    def __init__(self, supabase_client=None):
        # Synthetic data for local development.
        # No real company or production data is used.
        self._supabase = supabase_client
        self._records = {
            "cfg-001": {
                "config_id": "cfg-001",
                "service_name": "billing-api",
                "environment": "dev",
                "setting_key": "retry_limit",
                "setting_value": "3",
                "sensitive": False,
                "version": 1,
            },
            "cfg-002": {
                "config_id": "cfg-002",
                "service_name": "payments-api",
                "environment": "staging",
                "setting_key": "maintenance_mode",
                "setting_value": "false",
                "sensitive": True,
                "version": 1,
            },
            "cfg-003": {
                "config_id": "cfg-003",
                "service_name": "identity-api",
                "environment": "prod",
                "setting_key": "token_ttl_minutes",
                "setting_value": "15",
                "sensitive": True,
                "version": 1,
            },
        }

        # Pending requests are stored separately from the records.
        self._requests = {} #empty collection of approval requests

        self._audit_log = []
    def list_records(
        self,
        service_name=None,
        environment=None,
        limit=20,
    ):
        """Return records matching the requested filters."""

        if not isinstance(limit, int) or isinstance(limit, bool):
            raise GatewayError("limit must be an integer")

        if not 1 <= limit <= 100:
            raise GatewayError("limit must be between 1 and 100")

        allowed_environments = {"dev", "staging", "prod"}

        if (
            environment is not None
            and environment not in allowed_environments
        ):
            raise GatewayError(
                "environment must be dev, staging, or prod"
            )


        if self._supabase is not None:
            query = self._supabase.table("config_records").select("*")

            if service_name is not None:
                if not isinstance(service_name, str):
                    raise GatewayError("service_name must be a string")

                query = query.ilike(
                    "service_name", f"%{service_name.strip()}%"
                )

            if environment is not None:
                query = query.eq("environment", environment)

            response = query.limit(limit).execute()
            return response.data

        records = list(self._records.values())


        if service_name is not None:
            if not isinstance(service_name, str):
                raise GatewayError("service_name must be a string")

            search_term = service_name.strip().casefold()
            records = [
                record
                for record in records
                if search_term in record["service_name"].casefold()
            ]

        if environment is not None:
            records = [
                record
                for record in records
                if record["environment"] == environment
            ]

        # Return copies so callers cannot modify internal records.
        return [record.copy() for record in records[:limit]]


    def get_record(self, config_id):
        """Return a single record by its ID."""

        if self._supabase is not None:
            response = (self._supabase.table("config_records").select("*").eq("config_id", config_id).limit(1).execute())
            if not response.data:
                raise GatewayError("record not found")

            return response.data[0].copy()
        record = self._records.get(config_id)

        if record is None:
            raise GatewayError("record not found")

        return record.copy()


    def request_update(self, config_id, proposed_values, reason):
        """Create a pending update request without changing any data."""

        if config_id not in self._records:
            raise GatewayError("record not found")

        self._validate_reason(reason)

        if not isinstance(proposed_values, dict) or not proposed_values:
            raise GatewayError("at least one proposed field is required")

        unexpected_fields = (
            set(proposed_values) - self.ALLOWED_UPDATE_FIELDS
        )

        if unexpected_fields:
            raise GatewayError(
                "updates may only change: "
                + ", ".join(sorted(self.ALLOWED_UPDATE_FIELDS))
            )

        for value in proposed_values.values():
            if not isinstance(value, str) or len(value) > 1000:
                raise GatewayError(
                    "each proposed value must be a string "
                    "of at most 1000 characters"
                )

        request_id = f"req-{uuid4()}"

        request = {
            "request_id": request_id,
            "operation": "update",
            "config_id": config_id,
            "proposed_values": proposed_values.copy(),
            "status": "pending",
            "reason": reason.strip(),
        }

        self._requests[request_id] = request

        self._record_audit_event(
    event_type="update_requested",
    request_id=request_id,
    actor="mcp-client",
    details={"config_id": config_id},
)

        return {
            "message": "Approval required. No data was changed.",
            "request": request.copy(),
            "current_record": self.get_record(config_id),
        }

    def request_delete(self, config_id, reason):
        """Create a pending deletion request without deleting anything."""

        if config_id not in self._records:
            raise GatewayError("record not found")

        self._validate_reason(reason)

        request_id = f"req-{uuid4()}"

        request = {
            "request_id": request_id,
            "operation": "delete",
            "config_id": config_id,
            "proposed_values": {},
            "status": "pending",
            "reason": reason.strip(),
        }

        self._requests[request_id] = request

        self._record_audit_event(
    event_type="delete_requested",
    request_id=request_id,
    actor="mcp-client",
    details={"config_id": config_id},
)

        return {
            "message": "Approval required. No data was deleted.",
            "request": request.copy(),
        }

    def get_request_status(self, request_id):
        """Retrieve the status of an approval request."""

        request = self._requests.get(request_id)

        if request is None:
            raise GatewayError("approval request not found")

        return request.copy()

    def list_pending_requests(self):
        """List pending requests for local development."""

        return [
            request.copy()
            for request in self._requests.values()
            if request["status"] == "pending"
        ]


    def approve_request(self, request_id, approver_id):
        """Approve a pending request and apply its operation."""

        self._validate_approver(approver_id)

        request = self._requests.get(request_id)

        if request is None:
            raise GatewayError("approval request not found")

        if request["status"] != "pending":
            raise GatewayError("request has already been decided")

        config_id = request["config_id"]
        record = self._records.get(config_id)

        # The record may have been removed since the request was created.
        if record is None:
            raise GatewayError("record no longer exists")

        if request["operation"] == "update":
            request["previous_values"] = {
                field: record[field]
                for field in request["proposed_values"]
            }
            record.update(request["proposed_values"])
            record["version"] += 1

        elif request["operation"] == "delete":
            del self._records[config_id]

        else:
            raise GatewayError("unsupported operation")

        request["status"] = "approved"
        request["decided_by"] = approver_id.strip()
        request["decided_at"] = datetime.now(timezone.utc).isoformat()

        self._record_audit_event(
    event_type="request_approved",
    request_id=request_id,
    actor=approver_id.strip(),
    details={
        "operation": request["operation"],
        "config_id": config_id,
    },
)

        return {
            "message": "Request approved and operation applied.",
            "request": request.copy(),
        }

    def reject_request(self, request_id, approver_id):
        """Reject a pending request without changing its record."""

        self._validate_approver(approver_id)

        request = self._requests.get(request_id)

        if request is None:
            raise GatewayError("approval request not found")

        if request["status"] != "pending":
            raise GatewayError("request has already been decided")

        request["status"] = "rejected"
        request["decided_by"] = approver_id.strip()
        request["decided_at"] = datetime.now(timezone.utc).isoformat()

        self._record_audit_event(
    event_type="request_rejected",
    request_id=request_id,
    actor=approver_id.strip(),
    details={
        "operation": request["operation"],
        "config_id": request["config_id"],
    },
)

        return {
            "message": "Request rejected. No data was changed.",
            "request": request.copy(),
        }


    def _validate_reason(self, reason):
        if not isinstance(reason, str):
            raise GatewayError("reason must be a string")

        if not reason.strip() or len(reason) > self.MAX_REASON_LENGTH:
            raise GatewayError(
                "reason must contain 1â€“500 characters"
            )


    def _validate_approver(self, approver_id):
        """Validate an approver against the local trusted allowlist."""

        if not isinstance(approver_id, str) or not approver_id.strip():
            raise GatewayError("approver_id is required")

        if approver_id.strip() not in self.APPROVED_APPROVER_IDS:
            raise GatewayError("approver is not authorized")


    def _record_audit_event(
        self,
        event_type,
        request_id,
        actor,
        details=None,
    ):
        """Append an audit event to the local audit log."""

        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "request_id": request_id,
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details.copy() if details else {},
        }

        self._audit_log.append(event)


    def get_audit_log(self, request_id=None):
        """Return copies of audit events, optionally filtered by request."""

        events = self._audit_log

        if request_id is not None:
            events = [
                event
                for event in events
                if event["request_id"] == request_id
            ]

        return [
            {
                **event,
                "details": event["details"].copy(),
            }
            for event in events
        ]