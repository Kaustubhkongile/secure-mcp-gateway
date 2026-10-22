import json
import os
import urllib.error
import urllib.request
from getpass import getpass

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(".env")

url = os.environ["SUPABASE_URL"]
anon_key = os.environ["SUPABASE_ANON_KEY"]
expected_user_id = os.environ["REVIEWER_USER_ID"].strip()

email = input("Test user email: ").strip()
password = getpass("Test user password: ")

client = create_client(url, anon_key)

try:
    response = client.auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    user = response.user
    session = response.session

    print("Login successful:", bool(user and session))
    print(
        "Reviewer ID matches configuration:",
        bool(user and str(user.id) == expected_user_id),
    )
    print("Access token obtained:", bool(session and session.access_token))

    if not user or not session or not session.access_token:
        raise SystemExit("Login failed; stopping test.")

    request_id = input("Approval request ID to test: ").strip()
    decision = input("Decision (approve/reject): ").strip().lower()

    if not request_id or decision not in {"approve", "reject"}:
        raise SystemExit("Enter a request ID and approve or reject.")

    payload = json.dumps({
        "request_id": request_id,
        "approve": decision == "approve",
    }).encode("utf-8")

    request = urllib.request.Request(
        "http://127.0.0.1:8000/decisions",
        data=payload,
        headers={
            "Authorization": f"Bearer {session.access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as result:
            print("API HTTP status:", result.status)
            print("Response:", result.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("API HTTP status:", exc.code)
        print("Response:", exc.read().decode("utf-8"))

except SystemExit:
    raise
except Exception as exc:
    print("Test failed:", type(exc).__name__)
