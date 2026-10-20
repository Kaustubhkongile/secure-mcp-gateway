# Secure MCP Gateway

A Python-based Model Context Protocol (MCP) server that provides controlled access to service configuration records. It supports approval-based updates and deletions, persistent storage through Supabase, and audit logging.

## Features

- List and retrieve configuration records.
- Submit configuration update requests for approval.
- Submit deletion requests without immediately deleting records.
- Approve or reject pending requests.
- Persist records, approval requests, and audit events in Supabase.
- Record request and approval activity for auditing.
- Validate inputs and restrict update operations.
- Automated unit tests using pytest.

## Tech Stack

- Python
- Model Context Protocol (MCP) SDK
- Supabase PostgreSQL
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
│   └── supabase_client.py
├── scripts/
│   ├── test_approval_rpc.py
│   ├── test_gateway_supabase.py
│   ├── test_request_rpc.py
│   └── test_supabase.py
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
git clone <your-repository-url>
cd secure-mcp-gateway
```

If you are setting up your existing local project, skip this step.

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

Copy `.env.example` to `.env` and fill in your Supabase project URL and server-side API key.

Never commit `.env` or expose a service-role key to clients, source control, or an LLM.

### 5. Configure the database

Create the required database tables and PostgreSQL RPC functions using the SQL definitions developed for this project:

- `config_records`
- `approval_requests`
- `audit_events`
- `create_gateway_request`
- `decide_gateway_request`

Ensure database permissions are configured for the server-side role.

## Run the MCP Server

From the project root, run:

```powershell
python -m app.server
```

Configure your MCP client to use the project's Python interpreter and launch `app.server` from the project directory using the stdio transport.

## Available MCP Tools

- `list_records`
- `get_record`
- `request_record_update`
- `request_record_deletion`
- `get_approval_status`
- `approve_request`
- `reject_request`
- `get_audit_log`

Updates and deletions are submitted as approval requests rather than being applied immediately.

## Run Tests

Run the automated test suite:

```powershell
python -m pytest -q
```

The scripts in `scripts/` exercise database connectivity and integration workflows. Run them only after configuring the required Supabase environment variables and database schema.

## Security Notes

- Keep Supabase server-side credentials in environment variables.
- Do not commit secrets or production data.
- Treat the local reviewer identity as a development-only mechanism, not production authentication.
- Before production use, implement trusted reviewer authentication and authorization.
- Restrict audit-log modification and deletion privileges.
- Validate database permissions, concurrency behavior, and error handling before deployment.

## Disclaimer

This project is intended for development and demonstration. Production deployment requires additional security review, authentication, authorization, and operational hardening.
