import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from supabase import create_client

from app.supabase_client import create_supabase_client


app = FastAPI(
    title="Secure MCP Gateway Reviewer API",
    docs_url=None,
    redoc_url=None,
)

# Used only to validate Supabase access tokens.
auth_client = create_supabase_client()

# The public/publishable key is safe for client-style requests.
# Authorization is enforced by the user's JWT and database permissions.
supabase_url = os.getenv("SUPABASE_URL", "").strip()
supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
reviewer_user_id = os.getenv("REVIEWER_USER_ID", "").strip()


from pydantic import BaseModel, Field, StrictBool

class DecisionRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    approve: StrictBool

def authenticate_reviewer(authorization: str | None) -> tuple[str, str]:
    if not reviewer_user_id or not supabase_anon_key or not supabase_url:
        raise HTTPException(
            status_code=503,
            detail="Reviewer authentication is not configured",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        response = auth_client.auth.get_user(token)
        user = getattr(response, "user", None)
        user_id = str(getattr(user, "id", "")) if user else ""
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
        )

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
        )

    if user_id != reviewer_user_id:
        raise HTTPException(status_code=403, detail="Reviewer access denied")

    return user_id, token


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/decisions")
def make_decision(
    decision: DecisionRequest,
    authorization: str | None = Header(default=None),
):
    _, token = authenticate_reviewer(authorization)

    # Make the RPC request using the reviewer's JWT.
    # Do not use the service-role key for this decision call.
    reviewer_client = create_client(supabase_url, supabase_anon_key)
    reviewer_client.postgrest.auth(token)

    try:
        result = reviewer_client.rpc(
            "decide_gateway_request",
            {
                "p_request_id": decision.request_id,
                "p_approve": decision.approve,
            },
        ).execute()
    except Exception as exc:
        # Diagnostic logging for local development only.
        print(
            "Decision RPC failed:",
            type(exc).__name__,
            flush=True,
        )
        raise HTTPException(
            status_code=400,
            detail="Decision could not be processed. Check local server logs.",
        )

    return {"result": result.data}
