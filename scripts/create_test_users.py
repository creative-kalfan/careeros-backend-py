"""Create (or update) the test users needed by tests/test_auth.py.

Uses the Supabase service role key to create a regular user and an admin user
in the live Supabase project, and sets the admin user's profile role to 'admin'.

Usage:
    python scripts/create_test_users.py

Reads credentials from the .env file (NEXT_PUBLIC_SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, TEST_USER_EMAIL, TEST_USER_PASSWORD,
TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


def main() -> None:
    url = _required("NEXT_PUBLIC_SUPABASE_URL")
    service_role_key = _required("SUPABASE_SERVICE_ROLE_KEY")
    user_email = _required("TEST_USER_EMAIL")
    user_password = _required("TEST_USER_PASSWORD")
    admin_email = _required("TEST_ADMIN_EMAIL")
    admin_password = _required("TEST_ADMIN_PASSWORD")

    # Service-role client bypasses RLS, so we can create users and update roles.
    supabase = create_client(url, service_role_key)

    # --- Create the regular test user ---
    print(f"Creating/updating regular test user: {user_email}")
    try:
        res = supabase.auth.admin.create_user(
            {
                "email": user_email,
                "password": user_password,
                "email_confirm": True,
            }
        )
        user_id = res.user.id
        print(f"  Created user id: {user_id}")
    except Exception as exc:
        # User may already exist — try to look it up by email.
        print(f"  create_user failed ({exc}); attempting lookup by email")
        listed = supabase.auth.admin.list_users()
        user_id = None
        for u in listed.users:
            if u.email == user_email:
                user_id = u.id
                break
        if not user_id:
            raise SystemExit(f"Could not create or find test user {user_email}: {exc}")
        print(f"  Found existing user id: {user_id}")

    # Ensure the regular user's profile role is 'user' (idempotent).
    supabase.table("profiles").upsert(
        {"id": user_id, "email": user_email, "role": "user"},
        on_conflict="id",
    ).execute()
    print("  Profile role set to 'user'")

    # --- Create the admin test user ---
    print(f"Creating/updating admin test user: {admin_email}")
    try:
        res = supabase.auth.admin.create_user(
            {
                "email": admin_email,
                "password": admin_password,
                "email_confirm": True,
            }
        )
        admin_id = res.user.id
        print(f"  Created admin id: {admin_id}")
    except Exception as exc:
        print(f"  create_user failed ({exc}); attempting lookup by email")
        listed = supabase.auth.admin.list_users()
        admin_id = None
        for u in listed.users:
            if u.email == admin_email:
                admin_id = u.id
                break
        if not admin_id:
            raise SystemExit(f"Could not create or find admin user {admin_email}: {exc}")
        print(f"  Found existing admin id: {admin_id}")

    # Set the admin user's profile role to 'admin' (idempotent).
    supabase.table("profiles").upsert(
        {"id": admin_id, "email": admin_email, "role": "admin"},
        on_conflict="id",
    ).execute()
    print("  Profile role set to 'admin'")

    print("\nDone. Test users are ready.")


if __name__ == "__main__":
    main()