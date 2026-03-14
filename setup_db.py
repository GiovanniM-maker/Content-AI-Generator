#!/usr/bin/env python3
"""
Content AI Generator — Database Setup Script

This script:
1. Creates a default admin user via Supabase Auth
2. Saves the user ID to .env as DEFAULT_USER_ID
3. Verifies database tables are accessible

PREREQUISITES:
  - Run schema.sql in Supabase Dashboard → SQL Editor FIRST
  - Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env

Usage:
  python setup_db.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Check required env vars
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    print("See .env.example for required variables.")
    sys.exit(1)

import db


def update_env_file(key: str, value: str):
    """Add or update a key in the .env file."""
    env_path = Path(__file__).parent / ".env"
    lines = []
    found = False

    if env_path.exists():
        lines = env_path.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


def main():
    print("=" * 60)
    print("Content AI Generator — Database Setup")
    print("=" * 60)

    # Step 1: Check if DEFAULT_USER_ID already exists
    existing_uid = os.getenv("DEFAULT_USER_ID", "")
    if existing_uid and existing_uid != "00000000-0000-0000-0000-000000000000":
        print(f"\n✓ DEFAULT_USER_ID already set: {existing_uid}")
        print("  Skipping user creation.")
        user_id = existing_uid
    else:
        # Step 2: Create default admin user
        print("\n→ Creating default admin user...")
        email = "admin@content-ai.local"
        password = "ContentAI2026!"  # Only for initial setup/testing

        try:
            result = db.create_admin_user(email, password)
            user_id = str(result["id"])
            print(f"  ✓ User created: {result['email']} (ID: {user_id})")
        except Exception as e:
            err_str = str(e)
            if "already been registered" in err_str or "already exists" in err_str:
                print(f"  ⚠ User {email} already exists.")
                # Try to find the existing user
                try:
                    users = db._sb().auth.admin.list_users()
                    for u in users:
                        if getattr(u, 'email', None) == email:
                            user_id = str(u.id)
                            print(f"  ✓ Found existing user ID: {user_id}")
                            break
                    else:
                        print("  ERROR: Could not find existing user ID.")
                        print("  Set DEFAULT_USER_ID manually in .env")
                        sys.exit(1)
                except Exception as e2:
                    print(f"  ERROR listing users: {e2}")
                    sys.exit(1)
            else:
                print(f"  ERROR creating user: {e}")
                sys.exit(1)

        # Save to .env
        update_env_file("DEFAULT_USER_ID", user_id)
        print(f"  ✓ Saved DEFAULT_USER_ID to .env")

    # Step 3: Verify tables exist
    print("\n→ Verifying database tables...")
    tables = [
        "profiles", "subscriptions", "articles", "sessions",
        "schedules", "feedback", "feeds_config", "pipeline_logs",
        "prompt_logs", "selection_prefs", "weekly_status",
        "user_prompts", "notifications",
    ]
    all_ok = True
    for table in tables:
        try:
            db._sb().table(table).select("id").limit(1).execute()
            print(f"  ✓ {table}")
        except Exception as e:
            print(f"  ✗ {table} — {e}")
            all_ok = False

    if not all_ok:
        print("\n⚠ Some tables are missing!")
        print("  Please run schema.sql in Supabase Dashboard → SQL Editor")
        print("  Then re-run this script.")
        sys.exit(1)

    # Step 4: Verify the trigger created profile/subscription/config for the user
    print("\n→ Verifying user setup data...")
    profile = db.get_profile(user_id)
    if profile:
        print(f"  ✓ Profile exists (plan: {profile.get('plan', 'unknown')})")
    else:
        print("  ⚠ Profile not found — trigger may not have fired.")
        print("    This is OK if the user was created before the trigger was set up.")

    sub = db.get_subscription(user_id)
    if sub:
        print(f"  ✓ Subscription exists (plan: {sub.get('plan', 'unknown')}, status: {sub.get('status', 'unknown')})")
    else:
        print("  ⚠ Subscription not found")

    config = db.get_feeds_config(user_id)
    print(f"  ✓ Feeds config exists (categories: {len(config.get('categories', {}))})")

    prefs = db.get_selection_prefs(user_id)
    print(f"  ✓ Selection prefs exist (total_selections: {prefs.get('total_selections', 0)})")

    print("\n" + "=" * 60)
    print("✓ Setup complete!")
    print(f"  Default user ID: {user_id}")
    print(f"  Supabase project: {SUPABASE_URL}")
    print("\nYou can now start the app with: python app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
