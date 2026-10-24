
import pytest

from app.gateway import GatewayError, SecureGateway


@pytest.fixture
def gateway():
    return SecureGateway()


def test_list_records(gateway):
    records = gateway.list_records()

    assert len(records) == 3


def test_filter_records_by_environment(gateway):
    records = gateway.list_records(environment="prod")

    assert len(records) == 1
    assert records[0]["config_id"] == "cfg-003"


def test_get_existing_record(gateway):
    record = gateway.get_record("cfg-001")

    assert record["service_name"] == "billing-api"


def test_unknown_record_is_rejected(gateway):
    with pytest.raises(GatewayError):
        gateway.get_record("unknown")


def test_update_creates_pending_request(gateway):
    before = gateway.get_record("cfg-001")

    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Increase retry limit",
    )

    after = gateway.get_record("cfg-001")

    assert result["request"]["status"] == "pending"
    assert before == after


def test_delete_does_not_delete_record(gateway):
    result = gateway.request_delete(
        "cfg-001",
        "Request removal for review",
    )

    assert result["request"]["status"] == "pending"
    assert gateway.get_record("cfg-001")["config_id"] == "cfg-001"


def test_protected_fields_cannot_be_updated(gateway):
    with pytest.raises(GatewayError):
        gateway.request_update(
            "cfg-001",
            {"environment": "prod"},
            "Attempt to change environment",
        )


def test_invalid_limit_is_rejected(gateway):
    with pytest.raises(GatewayError):
        gateway.list_records(limit=101)


def test_approving_update_changes_record(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test approval",
    )
    request_id = result["request"]["request_id"]

    approved = gateway.approve_request(request_id, "local-reviewer")

    assert approved["request"]["status"] == "approved"
    assert approved["request"]["decided_by"] == "local-reviewer"
    assert gateway.get_record("cfg-001")["setting_value"] == "5"
    assert gateway.get_record("cfg-001")["version"] == 2


def test_rejecting_update_keeps_record_unchanged(gateway):
    before = gateway.get_record("cfg-001")
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test rejection",
    )

    gateway.reject_request(result["request"]["request_id"], "local-reviewer")

    assert gateway.get_record("cfg-001") == before
    assert gateway.get_request_status(
        result["request"]["request_id"]
    )["status"] == "rejected"


def test_approving_deletion_removes_record(gateway):
    result = gateway.request_delete("cfg-001", "Test deletion")
    request_id = result["request"]["request_id"]

    gateway.approve_request(request_id, "local-reviewer")

    with pytest.raises(GatewayError, match="record not found"):
        gateway.get_record("cfg-001")


def test_rejecting_deletion_preserves_record(gateway):
    result = gateway.request_delete("cfg-001", "Test deletion rejection")

    gateway.reject_request(result["request"]["request_id"], "local-reviewer")

    assert gateway.get_record("cfg-001")["config_id"] == "cfg-001"


def test_request_cannot_be_decided_twice(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test duplicate decision",
    )
    request_id = result["request"]["request_id"]

    gateway.approve_request(request_id, "local-reviewer")

    with pytest.raises(GatewayError, match="already been decided"):
        gateway.approve_request(request_id, "local-reviewer")


def test_approval_requires_approver_id(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test missing approver",
    )

    with pytest.raises(GatewayError, match="approver_id is required"):
        gateway.approve_request(result["request"]["request_id"], " ")


def test_unauthorized_approver_cannot_approve(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test unauthorized approval",
    )
    request_id = result["request"]["request_id"]

    with pytest.raises(GatewayError, match="not authorized"):
        gateway.approve_request(request_id, "unknown-user")

    assert gateway.get_request_status(request_id)["status"] == "pending"
    assert gateway.get_record("cfg-001")["setting_value"] == "3"



def test_audit_log_records_request_and_approval(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Audit test",
    )
    request_id = result["request"]["request_id"]

    gateway.approve_request(request_id, "local-reviewer")
    events = gateway.get_audit_log(request_id)

    assert [event["event_type"] for event in events] == [
        "update_requested",
        "request_approved",
    ]
    assert events[1]["actor"] == "local-reviewer"
    assert events[0]["event_id"] != events[1]["event_id"]
    assert events[0]["timestamp"]


def test_audit_log_records_rejection(gateway):
    result = gateway.request_delete("cfg-001", "Audit rejection test")
    request_id = result["request"]["request_id"]

    gateway.reject_request(request_id, "local-reviewer")
    events = gateway.get_audit_log(request_id)

    assert [event["event_type"] for event in events] == [
        "delete_requested",
        "request_rejected",
    ]
    assert gateway.get_record("cfg-001")["config_id"] == "cfg-001"


def test_audit_log_returns_copies(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Audit copy test",
    )
    request_id = result["request"]["request_id"]

    events = gateway.get_audit_log(request_id)
    events[0]["event_type"] = "tampered"
    events[0]["details"]["config_id"] = "tampered"

    original = gateway.get_audit_log(request_id)[0]

    assert original["event_type"] == "update_requested"
    assert original["details"]["config_id"] == "cfg-001"


class FakeSupabaseResponse:
    def __init__(self, data):
        self.data = data


class FakeSupabaseQuery:
    def __init__(self, records):
        self.records = records
        self.filters = []
        self.max_results = None

    def select(self, columns):
        return self

    def ilike(self, field, pattern):
        self.filters.append(("ilike", field, pattern))
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def limit(self, value):
        self.max_results = value
        return self

    def execute(self):
        results = self.records.copy()

        for operation, field, value in self.filters:
            if operation == "eq":
                results = [
                    record for record in results
                    if record[field] == value
                ]
            elif operation == "ilike":
                search_term = value.strip("%").casefold()
                results = [
                    record for record in results
                    if search_term in record[field].casefold()
                ]

        return FakeSupabaseResponse(
            results[:self.max_results]
        )


class FakeSupabaseClient:
    def __init__(self, records):
        self.records = records

    def table(self, table_name):
        assert table_name == "config_records"
        return FakeSupabaseQuery(self.records)


def test_list_records_reads_from_supabase():
    records = [{
        "config_id": "cfg-db-001",
        "service_name": "orders-api",
        "environment": "dev",
        "setting_key": "retry_limit",
        "setting_value": "4",
        "sensitive": False,
        "version": 1,
    }]

    gateway = SecureGateway(
        supabase_client=FakeSupabaseClient(records)
    )

    result = gateway.list_records()

    assert len(result) == 1
    assert result[0]["config_id"] == "cfg-db-001"


def test_list_records_filters_supabase_results():
    records = [
        {
            "config_id": "cfg-db-001",
            "service_name": "orders-api",
            "environment": "dev",
        },
        {
            "config_id": "cfg-db-002",
            "service_name": "billing-api",
            "environment": "prod",
        },
    ]

    gateway = SecureGateway(
        supabase_client=FakeSupabaseClient(records)
    )

    result = gateway.list_records(
        service_name="BILLING",
        environment="prod",
    )

    assert len(result) == 1
    assert result[0]["config_id"] == "cfg-db-002"


def test_get_record_reads_from_supabase():
    records = [{
        "config_id": "cfg-db-001",
        "service_name": "orders-api",
        "environment": "dev",
        "setting_key": "retry_limit",
        "setting_value": "4",
        "sensitive": False,
        "version": 1,
    }]

    gateway = SecureGateway(
        supabase_client=FakeSupabaseClient(records)
    )

    result = gateway.get_record("cfg-db-001")

    assert result["setting_value"] == "4"


def test_get_record_raises_for_missing_supabase_record():
    gateway = SecureGateway(
        supabase_client=FakeSupabaseClient([])
    )

    with pytest.raises(GatewayError, match="record not found"):
        gateway.get_record("missing-config")

@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_invalid_limit_boundaries_are_rejected(gateway, limit):
    with pytest.raises(GatewayError):
        gateway.list_records(limit=limit)

@pytest.mark.parametrize("limit", [True, False, 1.5, "10", None])
def test_non_integer_limits_are_rejected(gateway, limit):
    with pytest.raises(GatewayError):
        gateway.list_records(limit=limit)

@pytest.mark.parametrize("environment", ["production", "test", ""])
def test_invalid_environments_are_rejected(gateway, environment):
    with pytest.raises(GatewayError, match="environment"):
        gateway.list_records(environment=environment)

@pytest.mark.parametrize("service_name", [123, [], {}, True])
def test_non_string_service_names_are_rejected(gateway, service_name):
    with pytest.raises(GatewayError, match="service_name"):
        gateway.list_records(service_name=service_name)

@pytest.mark.parametrize("reason", ["", "   ", None, 123])
def test_invalid_update_reasons_are_rejected(gateway, reason):
    with pytest.raises(GatewayError):
        gateway.request_update(
            "cfg-001",
            {"setting_value": "5"},
            reason,
        )

def test_update_reason_over_maximum_length_is_rejected(gateway):
    with pytest.raises(GatewayError):
        gateway.request_update(
            "cfg-001",
            {"setting_value": "5"},
            "x" * 501,
        )

@pytest.mark.parametrize("values", [{}, [], None, "5"])
def test_invalid_update_payload_shapes_are_rejected(gateway, values):
    with pytest.raises(GatewayError):
        gateway.request_update("cfg-001", values, "Validation test")

@pytest.mark.parametrize("value", [None, 123, True, [], {}, "x" * 1001])
def test_invalid_update_values_are_rejected(gateway, value):
    with pytest.raises(GatewayError):
        gateway.request_update(
            "cfg-001",
            {"setting_value": value},
            "Validation test",
        )

def test_update_value_at_maximum_length_is_accepted(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "x" * 1000},
        "Boundary test",
    )

    assert result["request"]["status"] == "pending"
    assert len(result["request"]["proposed_values"]["setting_value"]) == 1000

def test_update_request_for_unknown_record_is_rejected(gateway):
    with pytest.raises(GatewayError, match="record not found"):
        gateway.request_update(
            "unknown",
            {"setting_value": "5"},
            "Validation test",
        )

def test_delete_request_for_unknown_record_is_rejected(gateway):
    with pytest.raises(GatewayError, match="record not found"):
        gateway.request_delete("unknown", "Validation test")

def test_request_status_for_unknown_request_is_rejected(gateway):
    with pytest.raises(GatewayError, match="approval request not found"):
        gateway.get_request_status("req-does-not-exist")

@pytest.mark.parametrize("limit", [True, False, 0, 101, 1.5, "10"])
def test_list_records_rejects_invalid_limits(limit):
    gateway = SecureGateway()

    with pytest.raises(GatewayError):
        gateway.list_records(limit=limit)


def test_list_records_rejects_non_string_service_name():
    gateway = SecureGateway()

    with pytest.raises(GatewayError, match="service_name must be a string"):
        gateway.list_records(service_name=123)


def test_list_records_matches_service_name_case_insensitively():
    gateway = SecureGateway()

    records = gateway.list_records(service_name="BILLING")

    assert len(records) == 1
    assert records[0]["service_name"] == "billing-api"


def test_list_records_filters_by_environment():
    gateway = SecureGateway()

    records = gateway.list_records(environment="staging")

    assert all(record["environment"] == "staging" for record in records)
    assert len(records) == 1


def test_get_record_returns_a_copy():
    gateway = SecureGateway()

    record = gateway.get_record("cfg-001")
    record["setting_value"] = "modified"

    assert gateway.get_record("cfg-001")["setting_value"] == "3"


def test_approve_request_rejects_unauthorized_approver():
    gateway = SecureGateway()
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Update retry limit",
    )
    request_id = result["request"]["request_id"]

    with pytest.raises(GatewayError, match="approver is not authorized"):
        gateway.approve_request(request_id, "unauthorized-user")


def test_reject_request_rejects_unauthorized_approver():
    gateway = SecureGateway()
    result = gateway.request_delete("cfg-001", "Remove test configuration")
    request_id = result["request"]["request_id"]

    with pytest.raises(GatewayError, match="approver is not authorized"):
        gateway.reject_request(request_id, "unauthorized-user")


def test_reject_request_does_not_change_record():
    gateway = SecureGateway()
    original = gateway.get_record("cfg-001").copy()

    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Update retry limit",
    )
    request_id = result["request"]["request_id"]

    gateway.reject_request(request_id, "local-reviewer")

    assert gateway.get_record("cfg-001") == original
    assert gateway.get_request_status(request_id)["status"] == "rejected"


def test_approve_request_rejects_unknown_request(gateway):
    with pytest.raises(GatewayError, match="approval request not found"):
        gateway.approve_request("req-missing", "local-reviewer")


def test_reject_request_rejects_unknown_request(gateway):
    with pytest.raises(GatewayError, match="approval request not found"):
        gateway.reject_request("req-missing", "local-reviewer")


def test_approve_request_rejects_record_that_no_longer_exists(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test missing record",
    )
    request_id = result["request"]["request_id"]

    # Simulate the record disappearing after the request was created.
    del gateway._records["cfg-001"]

    with pytest.raises(GatewayError, match="record no longer exists"):
        gateway.approve_request(request_id, "local-reviewer")


def test_approve_request_rejects_unsupported_operation(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test unsupported operation",
    )
    request_id = result["request"]["request_id"]

    # Simulate a corrupted or unexpected stored request.
    gateway._requests[request_id]["operation"] = "unsupported"

    with pytest.raises(GatewayError, match="unsupported operation"):
        gateway.approve_request(request_id, "local-reviewer")


def test_reject_request_rejects_already_decided_request(gateway):
    result = gateway.request_update(
        "cfg-001",
        {"setting_value": "5"},
        "Test duplicate rejection",
    )
    request_id = result["request"]["request_id"]

    gateway.reject_request(request_id, "local-reviewer")

    with pytest.raises(GatewayError, match="already been decided"):
        gateway.reject_request(request_id, "local-reviewer")
