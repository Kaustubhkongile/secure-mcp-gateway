import json
from unittest.mock import Mock
import runpy
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.routing import Route

import pytest

import app.server as server
from app.gateway import GatewayError


@pytest.fixture
def mocks(monkeypatch):
    gateway = Mock()
    repository = Mock()

    monkeypatch.setattr(server, "gateway", gateway)
    monkeypatch.setattr(server, "repository", repository)

    return gateway, repository


def decode(result):
    return json.loads(result)


def test_list_records_returns_json_records(mocks):
    gateway, _ = mocks
    gateway.list_records.return_value = [
        {"config_id": "cfg-001", "service_name": "billing-api"}
    ]

    result = decode(server.list_records(environment="dev", limit=10))

    assert result["records"][0]["config_id"] == "cfg-001"
    gateway.list_records.assert_called_once_with(
        service_name=None,
        environment="dev",
        limit=10,
    )


def test_list_records_handles_gateway_error(mocks):
    gateway, _ = mocks
    gateway.list_records.side_effect = GatewayError("invalid limit")

    assert decode(server.list_records(limit=101)) == {
        "error": "invalid limit"
    }


def test_get_record_returns_json_record(mocks):
    gateway, _ = mocks
    gateway.get_record.return_value = {"config_id": "cfg-001"}

    assert decode(server.get_record("cfg-001")) == {
        "record": {"config_id": "cfg-001"}
    }


def test_get_record_handles_missing_record(mocks):
    gateway, _ = mocks
    gateway.get_record.side_effect = GatewayError("record not found")

    assert decode(server.get_record("missing")) == {
        "error": "record not found"
    }


def test_request_record_update_creates_pending_request(mocks):
    gateway, repository = mocks
    repository.create_request_atomic.return_value = {
        "request_id": "req-001",
        "status": "pending",
    }
    gateway.get_record.return_value = {"config_id": "cfg-001"}

    result = decode(
        server.request_record_update(
            "cfg-001",
            {"setting_value": "5"},
            "Increase retry limit",
        )
    )

    assert result["request"]["status"] == "pending"
    assert result["current_record"]["config_id"] == "cfg-001"
    assert "No data was changed" in result["message"]
    repository.create_request_atomic.assert_called_once_with(
        operation="update",
        config_id="cfg-001",
        proposed_values={"setting_value": "5"},
        reason="Increase retry limit",
    )


def test_request_record_update_handles_gateway_error(mocks):
    _, repository = mocks
    repository.create_request_atomic.side_effect = GatewayError(
        "record not found"
    )

    assert decode(
        server.request_record_update(
            "missing",
            {"setting_value": "5"},
            "Update configuration",
        )
    ) == {"error": "record not found"}


def test_request_record_update_handles_unexpected_error(mocks):
    _, repository = mocks
    repository.create_request_atomic.side_effect = RuntimeError("database down")

    assert decode(
        server.request_record_update(
            "cfg-001",
            {"setting_value": "5"},
            "Update configuration",
        )
    ) == {"error": "request creation failed"}


def test_request_record_deletion_creates_pending_request(mocks):
    _, repository = mocks
    repository.create_request_atomic.return_value = {
        "request_id": "req-002",
        "status": "pending",
    }

    result = decode(
        server.request_record_deletion(
            "cfg-001",
            "Remove obsolete configuration",
        )
    )

    assert result["request"]["status"] == "pending"
    assert "No data was deleted" in result["message"]
    repository.create_request_atomic.assert_called_once_with(
        operation="delete",
        config_id="cfg-001",
        proposed_values={},
        reason="Remove obsolete configuration",
    )


def test_request_record_deletion_handles_unexpected_error(mocks):
    _, repository = mocks
    repository.create_request_atomic.side_effect = RuntimeError("database down")

    assert decode(
        server.request_record_deletion("cfg-001", "Delete configuration")
    ) == {"error": "request creation failed"}


def test_get_approval_status_returns_request(mocks):
    _, repository = mocks
    repository.get_request.return_value = {
        "request_id": "req-001",
        "status": "pending",
    }

    assert decode(server.get_approval_status("req-001")) == {
        "request": {"request_id": "req-001", "status": "pending"}
    }


def test_get_approval_status_handles_gateway_error(mocks):
    _, repository = mocks
    repository.get_request.side_effect = GatewayError(
        "approval request not found"
    )

    assert decode(server.get_approval_status("missing")) == {
        "error": "approval request not found"
    }


def test_get_approval_status_handles_unexpected_error(mocks):
    _, repository = mocks
    repository.get_request.side_effect = RuntimeError("database down")

    assert decode(server.get_approval_status("req-001")) == {
        "error": "failed to retrieve approval status"
    }


def test_get_audit_log_returns_events(mocks):
    _, repository = mocks
    repository.get_audit_log.return_value = [
        {"event_type": "update_requested", "request_id": "req-001"}
    ]

    result = decode(server.get_audit_log("req-001"))

    assert result["events"][0]["event_type"] == "update_requested"
    repository.get_audit_log.assert_called_once_with(request_id="req-001")


def test_get_audit_log_handles_unexpected_error(mocks):
    _, repository = mocks
    repository.get_audit_log.side_effect = RuntimeError("database down")

    assert decode(server.get_audit_log()) == {
        "error": "failed to retrieve audit log"
    }

def test_http_transport_starts_with_render_configuration(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("PORT", "12345")

    fake_app = Starlette()

    with (
    patch.object(server.mcp, "streamable_http_app", return_value=fake_app) as create_app,
    patch("uvicorn.run") as run_server,
    ):
        server.run_server()

    create_app.assert_called_once_with(
        host="0.0.0.0",
        streamable_http_path="/mcp",
    )

    assert any(
    item.cls is server.MCPBearerAuthMiddleware
    for item in fake_app.user_middleware
    )

    args, kwargs = run_server.call_args

    assert args[0] is fake_app
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 12345


def test_http_transport_registers_health_endpoint(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")

    fake_app = Starlette()

    with (
        patch.object(server.mcp, "streamable_http_app", return_value=fake_app),
        patch("uvicorn.run"),
        patch.object(server, "MCPBearerAuthMiddleware"),
    ):
        server.run_server()

    health_routes = [
        route
        for route in fake_app.routes
        if isinstance(route, Route) and route.path == "/health"
    ]

    assert len(health_routes) == 1
    assert health_routes[0].methods == {"GET", "HEAD"}


def test_default_transport_uses_stdio(monkeypatch):
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)

    with patch.object(server.mcp, "run") as run_mcp:
        server.run_server()

    run_mcp.assert_called_once_with(transport="stdio")
