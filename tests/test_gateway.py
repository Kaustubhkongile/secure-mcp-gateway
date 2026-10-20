
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
