#!/usr/bin/env python3
"""Seed RSS feeds for a specific user account.

Populates the user's feeds_config with ALL categories from FEED_CATALOG.
Usage:
    python3 scripts/seed_feeds.py
"""

import os
import sys
from datetime import datetime, timezone

# Add parent directory to path so we can import from the project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from supabase import create_client

# ── Config ──────────────────────────────────────────────────────────────────
TARGET_EMAIL = "giovanni.mavilla.grz@gmail.com"

# Import the catalog from app.py
from app import FEED_CATALOG


def main():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("❌ SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    sb = create_client(url, key)

    # 1. Find user by email in auth.users via profiles table
    print(f"🔍 Cerco profilo per {TARGET_EMAIL}...")
    resp = sb.table("profiles").select("id, email, full_name").eq("email", TARGET_EMAIL).execute()

    if not resp.data:
        print(f"❌ Nessun profilo trovato per {TARGET_EMAIL}")
        print("   Assicurati che l'utente si sia registrato almeno una volta.")
        sys.exit(1)

    user = resp.data[0]
    user_id = user["id"]
    print(f"✅ Trovato: {user.get('full_name', 'N/A')} (id: {user_id})")

    # 2. Build full config from FEED_CATALOG
    categories = {}
    total_feeds = 0
    for cat_name, feeds in FEED_CATALOG.items():
        categories[cat_name] = [{"url": f["url"], "name": f["name"]} for f in feeds]
        total_feeds += len(feeds)

    print(f"📦 Preparati {total_feeds} feed in {len(categories)} categorie")

    # 3. Upsert feeds_config
    sb.table("feeds_config").upsert(
        {
            "user_id": user_id,
            "categories": categories,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id",
    ).execute()

    print(f"✅ feeds_config aggiornato per {TARGET_EMAIL}")
    print(f"   Categorie: {len(categories)}")
    print(f"   Feed totali: {total_feeds}")
    print()
    for cat_name, feeds in categories.items():
        print(f"   • {cat_name}: {len(feeds)} feed")


if __name__ == "__main__":
    main()
