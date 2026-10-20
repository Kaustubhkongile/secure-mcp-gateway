
from app.repository import SupabaseRepository


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, tables, table_name):
        self.tables = tables
        self.table_name = table_name
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, columns):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, count):
        self.max_results = count
        return self

    def order(self, field):
        return self

    def execute(self):
        rows = self.tables.setdefault(self.table_name, [])

        if self.operation == "insert":
            rows.append(self.payload.copy())
            return FakeResponse([self.payload.copy()])

        result = [
            row.copy()
            for row in rows
            if all(row.get(field) == value for field, value in self.filters)
        ]

        return FakeResponse(result[:getattr(self, "max_results", None)])


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, table_name):
        return FakeQuery(self.tables, table_name)


def test_create_and_get_persistent_request():
    repository = SupabaseRepository(FakeSupabase())

    created = repository.create_request(
        operation="update",
        config_id="cfg-001",
        proposed_values={"setting_value": "5"},
        reason="Increase retry limit",
    )

    fetched = repository.get_request(created["request_id"])

    assert fetched["request_id"] == created["request_id"]
    assert fetched["status"] == "pending"
    assert fetched["proposed_values"] == {"setting_value": "5"}


def test_list_pending_requests():
    repository = SupabaseRepository(FakeSupabase())

    first = repository.create_request(
        "update", "cfg-001", {"setting_value": "5"}, "Update retries"
    )
    repository.create_request(
        "delete", "cfg-002", {}, "Remove obsolete configuration"
    )

    pending = repository.list_pending_requests()

    assert len(pending) == 2
    assert {item["request_id"] for item in pending} == {
        first["request_id"],
        pending[1]["request_id"],
    }
    assert all(item["status"] == "pending" for item in pending)


def test_audit_event_can_be_written_and_read():
    repository = SupabaseRepository(FakeSupabase())

    request = repository.create_request(
        "update", "cfg-001", {"setting_value": "5"}, "Test audit"
    )

    repository.record_audit_event(
        event_type="update_requested",
        request_id=request["request_id"],
        actor="mcp-client",
        details={"config_id": "cfg-001"},
    )

    events = repository.get_audit_log(request["request_id"])

    assert len(events) == 1
    assert events[0]["event_type"] == "update_requested"
    assert events[0]["details"]["config_id"] == "cfg-001"


def test_decide_request_calls_database_function():
    class FakeRpcResponse:
        data = {
            "request_id": "req-test",
            "operation": "update",
            "config_id": "cfg-001",
            "status": "approved",
            "decided_by": "local-reviewer",
        }

    class FakeRpcQuery:
        def execute(self):
            return FakeRpcResponse()

    class FakeRpcClient(FakeSupabase):
        def rpc(self, function_name, params):
            assert function_name == "decide_gateway_request"
            assert params == {
                "p_request_id": "req-test",
                "p_approver_id": "local-reviewer",
                "p_approve": True,
            }
            return FakeRpcQuery()

    repository = SupabaseRepository(FakeRpcClient())

    result = repository.decide_request(
        request_id="req-test",
        approver_id="local-reviewer",
        approve=True,
    )

    assert result["status"] == "approved"
    assert result["config_id"] == "cfg-001"

def test_create_request_atomic_calls_database_function():
    class FakeRpcResponse:
        data = {
            "request_id": "req-test",
            "operation": "update",
            "config_id": "cfg-001",
            "proposed_values": {"setting_value": "5"},
            "status": "pending",
            "reason": "Increase retry limit",
        }

    class FakeRpcQuery:
        def execute(self):
            return FakeRpcResponse()

    class FakeRpcClient(FakeSupabase):
        def rpc(self, function_name, params):
            assert function_name == "create_gateway_request"
            assert params == {
                "p_operation": "update",
                "p_config_id": "cfg-001",
                "p_proposed_values": {"setting_value": "5"},
                "p_reason": "Increase retry limit",
            }
            return FakeRpcQuery()

    repository = SupabaseRepository(FakeRpcClient())

    result = repository.create_request_atomic(
        operation="update",
        config_id="cfg-001",
        proposed_values={"setting_value": "5"},
        reason="Increase retry limit",
    )

    assert result["status"] == "pending"
    assert result["request_id"] == "req-test"
