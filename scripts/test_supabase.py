import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# Load the .env file from the project root.
project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    sys.exit("Missing SUPABASE_URL or SUPABASE_KEY in .env")

try:
    client = create_client(url, key)

    response = (
        client.table("config_records")
        .select("config_id, service_name, environment")
        .limit(5)
        .execute()
    )

    print("Supabase connection successful!")
    print(f"Records retrieved: {len(response.data)}")

    for record in response.data:
        print(record)

except Exception as exc:
    # Avoid printing credentials or request headers.
    print(f"Connection failed: {type(exc).__name__}: {exc}")
    sys.exit(1)
