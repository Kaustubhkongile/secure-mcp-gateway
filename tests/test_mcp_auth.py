
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.mcp_auth import MCPBearerAuthMiddleware


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-secret-token")

    app = Starlette()

    async def mcp_endpoint(request):
        return JSONResponse({"status": "mcp reached"})

    async def health_endpoint(request):
        return JSONResponse({"status": "ok"})

    app.add_route("/mcp", mcp_endpoint, methods=["POST"])
    app.add_route("/health", health_endpoint, methods=["GET"])
    app.add_middleware(MCPBearerAuthMiddleware)

    return TestClient(app)


def test_missing_token_is_rejected(client):
    response = client.post("/mcp")

    assert response.status_code == 401
    assert response.json()["error"] == "Unauthorized"


def test_invalid_token_is_rejected(client):
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_valid_token_is_accepted(client):
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-secret-token"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "mcp reached"


def test_missing_server_token_returns_503(client, monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN")

    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-secret-token"},
    )

    assert response.status_code == 503


def test_health_endpoint_does_not_require_token(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
