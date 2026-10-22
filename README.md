# Secure MCP Gateway

A Python-based Model Context Protocol (MCP) server that provides controlled access to service configuration records. The gateway uses a human-in-the-loop approval workflow to protect configuration updates and deletions, with Supabase-backed persistence, reviewer authentication, and audit logging.

## Features

- Expose configuration records to LLM clients through MCP tools.
- Retrieve individual configuration records and list available records.
- Submit configuration update and deletion requests without immediately applying changes.
- Require an authorized reviewer to approve or reject pending requests.
- Authenticate reviewers using Supabase Auth.
- Enforce reviewer authorization using a configured reviewer identity and database-side checks.
- Apply approved configuration changes through a PostgreSQL RPC function.
- Prevent duplicate decisions on already-processed requests.
- Record request, approval, and rejection activity in an audit log.
- Validate inputs and restrict supported configuration updates.
- Run automated unit tests using pytest.

## Architecture

The project separates LLM-facing tools from reviewer decision-making.

```text
LLM Client
    |
    v
MCP Server (app/server.py)
    |
    v
Gateway / Repository
    |
    v
Supabase PostgreSQL
    |
    +-- Configuration Records
    +-- Approval Requests
    +-- Audit Events

Reviewer
    |
    v
Reviewer API (FastAPI)
    |
    +-- Supabase Auth token validation
    +-- Configured reviewer authorization
    |
    v
decide_gateway_request RPC
    |
    +-- Approve or reject request
    +-- Apply approved configuration change
    +-- Record audit event
```

The MCP server can request changes but does not expose a direct approval tool. Approval and rejection decisions go through the authenticated reviewer API.

## Tech Stack

- Python
- Model Context Protocol (MCP) SDK
- FastAPI
- Supabase Auth and PostgreSQL
- PostgreSQL RPC functions
- pytest
- python-dotenv

## Project Structure

```text
secure-mcp-gateway/
├── app/
│   ├── __init__.py
│   ├── gateway.py
│   ├── repository.py
│   ├── server.py
│   ├── reviewer_api.py
│   └── supabase_client.py
├── scripts/
│   ├── test_approval_rpc.py
│   ├── test_gateway_supabase.py
│   ├── test_request_rpc.py
│   ├── test_supabase.py
│   └── test_reviewer_login.py
├── tests/
│   ├── test_gateway.py
│   └── test_repository.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## Prerequisites

- Python 3.11 or newer, compatible with the dependencies in `pyproject.toml`
- A Supabase project
- Git

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Kaustubhkongile/secure-mcp-gateway.git
cd secure-mcp-gateway
```

### 2. Create and activate a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -e ".[dev]"
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and configure the values for your Supabase project.

The application uses these environment variables:

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Server-side Supabase key used by the repository |
| `SUPABASE_ANON_KEY` | Publishable/anon key used for reviewer authentication and JWT-authenticated API requests |
| `REVIEWER_USER_ID` | Supabase Auth user ID authorized to make reviewer decisions |

Use the appropriate key type supported by your Supabase project. Keep `.env` out of source control.

**Never commit service-role keys, access tokens, passwords, or production credentials.** The publishable/anon key is not a substitute for authorization; database permissions and reviewer checks must enforce access.

### 5. Configure the database

Configure the Supabase database with the schema, permissions, and PostgreSQL functions required by the application.

The implementation uses:

- `config_records`
- `approval_requests`
- `audit_events`
- `private.gateway_reviewers`
- `create_gateway_request`
- `decide_gateway_request`

The reviewer decision function must validate the authenticated user, check reviewer authorization, ensure the request is still pending, apply approved changes transactionally, and record the resulting audit event.

Apply the database definitions and grants appropriate to your project before running the integration workflows.

## Run the MCP Server

From the project root, with the virtual environment activated:

```powershell
python -m app.server
```

Configure your MCP client to launch the server using the project's Python interpreter and the stdio transport.

## Run the Reviewer API

In a separate terminal, activate the virtual environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.reviewer_api:app --host 127.0.0.1 --port 8000
```

The local health endpoint is:

```text
http://127.0.0.1:8000/health
```

The reviewer decision endpoint is:

```text
POST http://127.0.0.1:8000/decisions
```

The decision endpoint expects a valid Supabase Auth access token in the `Authorization: Bearer <token>` header and a JSON request body:

```json
{
  "request_id": "your-pending-request-id",
  "approve": true
}
```

Set `approve` to `false` to reject a request. Only the configured reviewer is authorized, and the database function independently verifies reviewer authorization.

Keep the API bound to localhost for local development. A deployed API requires appropriate HTTPS, deployment secrets, network controls, and operational hardening.

## Available MCP Tools

| Tool | Responsibility |
|---|---|
| `list_records` | List configuration records |
| `get_record` | Retrieve a configuration record |
| `request_record_update` | Submit an update request for approval |
| `request_record_deletion` | Submit a deletion request for approval |
| `get_approval_status` | Check an approval request's status |
| `get_audit_log` | Retrieve audit events |

Update and deletion requests are persisted as pending requests. They do not immediately modify or delete the target configuration.

There is no direct MCP approval tool. Reviewer decisions are handled by the authenticated reviewer API.

## Run Tests

Activate the virtual environment and run the automated test suite:

```powershell
python -m pytest -q
```

**Current verified result:** 27 tests passed.

The scripts in `scripts/` support additional Supabase integration and reviewer-authentication checks. Run them only after configuring the required environment variables and database schema. Some scripts may interact with persistent test data, so use a dedicated development or test project.

## Security Design

- **Human-in-the-loop approval:** Updates and deletions require an explicit reviewer decision.
- **Reviewer authentication:** Supabase Auth validates access tokens.
- **Reviewer authorization:** The API checks the configured reviewer identity, and the database function independently checks reviewer permissions.
- **Duplicate-decision protection:** A request that has already been decided cannot be processed again.
- **Transactional updates:** Approval, configuration changes, and audit recording are handled through a database function.
- **Auditability:** Request creation and reviewer decisions produce persistent audit events.
- **Secret management:** Credentials belong in environment variables, not source control.
- **Restricted operations:** Only explicitly supported operations and input fields should be accepted.

## Limitations and Production Readiness

This project is a development and portfolio demonstration. Passing unit tests and manual workflow checks does not by itself establish production readiness.

Before deployment, review:

- Database grants, row-level security, and function ownership.
- Reviewer onboarding, revocation, and multi-reviewer authorization.
- API rate limiting, request validation, and safe error handling.
- Audit-log retention and protection against unauthorized modification.
- Concurrency behavior, monitoring, and operational recovery.
- HTTPS and secure secret management in the deployment environment.
- Automated integration and security tests against a dedicated test database.

## Disclaimer

This project demonstrates controlled MCP access and human-reviewed configuration changes. It should not be used to manage production systems until the necessary security, reliability, and operational reviews have been completed.
