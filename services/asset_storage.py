"""Asset storage service — generate, store, and manage reusable image assets.

Assets are AI-generated images stored in Supabase Storage.  Each asset is
linked to a user and tagged with the prompt that created it so it can be
reused across multiple carousels.

Storage bucket: ``template-assets``
Path pattern:   ``{user_id}/carousel-assets/{uuid}.png``
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import db as _db
from services.image_generator import _generate_image_openrouter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata table — lives alongside the binary assets in Supabase
# ---------------------------------------------------------------------------

ASSETS_TABLE = "carousel_assets"


def _ensure_assets_table() -> None:
    """Create the carousel_assets table if it doesn't exist.

    Runs a safe CREATE TABLE IF NOT EXISTS via Supabase's RPC.
    If RPC isn't available we silently fall back (the table may already exist).
    """
    try:
        _db._sb().rpc(
            "exec_sql",
            {
                "query": """
                CREATE TABLE IF NOT EXISTS carousel_assets (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id     TEXT NOT NULL,
                    prompt      TEXT NOT NULL,
                    image_url   TEXT NOT NULL,
                    tags        JSONB DEFAULT '[]'::jsonb,
                    created_at  TIMESTAMPTZ DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_carousel_assets_user
                    ON carousel_assets(user_id);
                """
            },
        ).execute()
    except Exception as exc:
        log.debug("[asset_storage] table init skipped (may already exist): %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_and_store_asset(
    prompt: str,
    user_id: str,
    tags: list[str] | None = None,
) -> dict:
    """Generate a single image asset and persist it.

    Returns::

        {
            "id": "<uuid>",
            "user_id": "...",
            "prompt": "...",
            "image_url": "https://...supabase.../...",
            "tags": ["marble", "dark"],
            "created_at": "2026-..."
        }
    """
    tags = tags or []
    asset_id = uuid.uuid4().hex

    log.info("[asset_storage] generating asset for user=%s prompt=%s",
             user_id[:8], prompt[:120])

    # 1) Generate image bytes via OpenRouter
    image_bytes = _generate_image_openrouter(prompt)
    log.info("[asset_storage] generated %d bytes", len(image_bytes))

    # 2) Upload to Supabase Storage
    _db.ensure_template_assets_bucket()
    filename = f"asset_{asset_id}.png"
    storage_path = f"{user_id}/carousel-assets/{filename}"
    _db._sb().storage.from_(_db.TEMPLATE_ASSETS_BUCKET).upload(
        storage_path,
        image_bytes,
        file_options={"content-type": "image/png", "upsert": "true"},
    )
    image_url = _db._sb().storage.from_(
        _db.TEMPLATE_ASSETS_BUCKET
    ).get_public_url(storage_path).rstrip("?")

    log.info("[asset_storage] uploaded → %s", image_url)

    # 3) Store metadata
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": asset_id,
        "user_id": user_id,
        "prompt": prompt,
        "image_url": image_url,
        "tags": tags,
        "created_at": now,
    }
    try:
        _db._sb().table(ASSETS_TABLE).insert(meta).execute()
    except Exception as exc:
        # Table might not exist yet — try once to create it and retry
        log.warning("[asset_storage] insert failed, attempting table init: %s", exc)
        _ensure_assets_table()
        try:
            _db._sb().table(ASSETS_TABLE).insert(meta).execute()
        except Exception as exc2:
            log.error("[asset_storage] metadata insert failed (non-fatal): %s", exc2)

    return meta


def generate_assets_batch(
    prompts: list[str],
    user_id: str,
    tags: list[str] | None = None,
) -> list[dict]:
    """Generate multiple assets sequentially and return their metadata."""
    results = []
    for prompt in prompts:
        try:
            asset = generate_and_store_asset(prompt, user_id, tags=tags)
            results.append(asset)
        except Exception as exc:
            log.error("[asset_storage] batch item failed (prompt=%s): %s",
                      prompt[:80], exc)
            results.append({"error": str(exc), "prompt": prompt})
    return results


def list_user_assets(user_id: str, limit: int = 50) -> list[dict]:
    """Return recent assets for a user (newest first)."""
    try:
        resp = (
            _db._sb()
            .table(ASSETS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        log.warning("[asset_storage] list_user_assets failed: %s", exc)
        return []
