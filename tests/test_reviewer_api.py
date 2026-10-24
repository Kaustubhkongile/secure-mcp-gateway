
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app.reviewer_api as reviewer_api


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        reviewer_api,
        "reviewer_user_id",
        "trusted-reviewer",
    )
    monkeypatch.setattr(reviewer_api, "supabase_url", "https://example.test")
    monkeypatch.setattr(reviewer_api, "supabase_anon_key", "test-public-key")

    reviewer_api.auth_client = Mock()
    reviewer_api.create_client = Mock()

    return TestClient(reviewer_api.app)


def configure_authenticated_reviewer(client, user_id="trusted-reviewer"):
    reviewer_api.auth_client.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )


def test_health_endpoint_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_decision_requires_authorization_header(client):
    response = client.post(
        "/decisions",
        json={"request_id": "req-123", "approve": True},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.parametrize(
    "authorization",
    ["Basic abc", "Bearer ", "invalid-token"],
)
def test_invalid_authorization_is_rejected(client, authorization):
    response = client.post(
        "/decisions",
        headers={"Authorization": authorization},
        json={"request_id": "req-123", "approve": True},
    )

    assert response.status_code == 401


def test_expired_or_invalid_token_is_rejected(client):
    reviewer_api.auth_client.auth.get_user.side_effect = Exception("invalid token")

    response = client.post(
        "/decisions",
        headers={"Authorization": "Bearer invalid"},
        json={"request_id": "req-123", "approve": True},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired access token"


def test_user_without_reviewer_access_is_forbidden(client):
    configure_authenticated_reviewer(client, "ordinary-user")

    response = client.post(
        "/decisions",
        headers={"Authorization": "Bearer valid-token"},
        json={"request_id": "req-123", "approve": True},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Reviewer access denied"
    reviewer_api.create_client.assert_not_called()


def test_missing_reviewer_configuration_returns_503(client, monkeypatch):
    monkeypatch.setattr(reviewer_api, "reviewer_user_id", "")

    response = client.post(
        "/decisions",
        headers={"Authorization": "Bearer valid-token"},
        json={"request_id": "req-123", "approve": True},
    )

    assert response.status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"approve": True},
        {"request_id": "", "approve": True},
        {"request_id": "x" * 101, "approve": True},
        {"request_id": "req-123"},
        {"request_id": "req-123", "approve": "yes"},
    ],
)

def test_invalid_decision_payload_is_rejected(client, payload):
    configure_authenticated_reviewer(client)

    response = client.post(
        "/decisions",
        headers={"Authorization": "Bearer valid-token"},
        json=payload,
    )

    print(response.status_code, response.text)
    assert response.status_code == 422

@pytest.mark.parametrize("approve", [True, False])
def test_reviewer_decision_calls_database_rpc(client, approve):
    configure_authenticated_reviewer(client)

    rpc_response = SimpleNamespace(data={
        "request_id": "req-123",
        "status": "approved" if approve else "rejected",
    })

    rpc_query = Mock()
    rpc_query.execute.return_value = rpc_response

    reviewer_client = Mock()
    reviewer_client.rpc.return_value = rpc_query
    reviewer_api.create_client.return_value = reviewer_client

    response = client.post(
        "/decisions",
        headers={"Authorization": "Bearer reviewer-token"},
        json={"request_id": "req-123", "approve": approve},
    )

    assert response.status_code == 200
    assert response.json()["result"]["status"] == (
        "approved" if approve else "rejected"
    )
    reviewer_client.postgrest.auth.assert_called_once_with("reviewer-token")
    reviewer_client.rpc.assert_called_once_with(
        "decide_gateway_request",
        {
            "p_request_id": "req-123",
            "p_approve": approve,
        },
    )


def test_database_rpc_failure_returns_safe_error(client, capsys):
    configure_authenticated_reviewer(client)

    reviewer_client = Mock()
    reviewer_client.rpc.side_effect = RuntimeError("sensitive database details")
    reviewer_api.create_client.return_value = reviewer_client

    response = client.post(
        "/decisions",
        headers={"Authorization": "Bearer reviewer-token"},
        json={"request_id": "req-123", "approve": True},
    )

    assert response.status_code == 400
    assert "sensitive database details" not in response.text
    assert "RuntimeError" in capsys.readouterr().out
