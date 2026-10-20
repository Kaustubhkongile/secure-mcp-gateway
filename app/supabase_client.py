import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client


def create_supabase_client():
    """Create a Supabase client using server-side environment variables."""
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be configured."
        )

    return create_client(url, key)
