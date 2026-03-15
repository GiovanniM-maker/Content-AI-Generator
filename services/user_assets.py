"""User asset management — upload, store, and retrieve reusable image assets.

Users can upload their own assets (logo, product image, texture, photo)
for use in carousel generation.  Assets are stored in Supabase Storage
and tracked in the ``user_assets`` table with typed metadata.

Storage bucket: ``template-assets``
Path pattern:   ``{user_id}/user-assets/{uuid}.{ext}``
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import db as _db

log = logging.getLogger(__name__)

USER_ASSETS_TABLE = "user_assets"

VALID_ASSET_TYPES = ("logo", "product", "photo", "texture", "other")
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


# ---------------------------------------------------------------------------
# Table bootstrap (safe to call repeatedly)
# ---------------------------------------------------------------------------

def _ensure_table() -> None:
    """Create user_assets table if it doesn't exist."""
    try:
        _db._sb().rpc(
            "exec_sql",
            {
                "query": """
                CREATE TABLE IF NOT EXISTS user_assets (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id     TEXT NOT NULL,
                    type        TEXT NOT NULL DEFAULT 'other',
                    url         TEXT NOT NULL,
                    filename    TEXT NOT NULL DEFAULT '',
                    tags        JSONB DEFAULT '[]'::jsonb,
                    created_at  TIMESTAMPTZ DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_user_assets_user
                    ON user_assets(user_id);
                """
            },
        ).execute()
    except Exception as exc:
        log.debug("[user_assets] table init skipped: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_user_asset(
    user_id: str,
    file_bytes: bytes,
    filename: str,
    asset_type: str = "other",
    tags: list[str] | None = None,
) -> dict:
    """Upload a user asset file and store metadata.

    Args:
        user_id: Owner.
        file_bytes: Raw image bytes.
        filename: Original filename (used for extension detection).
        asset_type: One of ``VALID_ASSET_TYPES``.
        tags: Optional tags for searchability.

    Returns:
        Asset metadata dict with id, url, type, etc.

    Raises:
        ValueError: If file is too large, wrong type, or invalid extension.
    """
    # Validate size
    if len(file_bytes) > MAX_FILE_SIZE:
        raise ValueError(f"File too large. Maximum {MAX_FILE_SIZE // (1024*1024)}MB.")

    # Validate extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Validate asset type
    if asset_type not in VALID_ASSET_TYPES:
        asset_type = "other"

    tags = tags or []
    asset_id = uuid.uuid4().hex

    # Upload to Supabase Storage
    _db.ensure_template_assets_bucket()
    storage_name = f"asset_{asset_id}{ext}"
    storage_path = f"{user_id}/user-assets/{storage_name}"
    content_type = CONTENT_TYPES.get(ext, "image/png")

    _db._sb().storage.from_(_db.TEMPLATE_ASSETS_BUCKET).upload(
        storage_path,
        file_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    url = _db._sb().storage.from_(
        _db.TEMPLATE_ASSETS_BUCKET
    ).get_public_url(storage_path).rstrip("?")

    log.info("[user_assets] uploaded %s → %s (type=%s)", filename, url, asset_type)

    # Store metadata
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": asset_id,
        "user_id": user_id,
        "type": asset_type,
        "url": url,
        "filename": filename,
        "tags": tags,
        "created_at": now,
    }

    try:
        _db._sb().table(USER_ASSETS_TABLE).insert(meta).execute()
    except Exception:
        _ensure_table()
        try:
            _db._sb().table(USER_ASSETS_TABLE).insert(meta).execute()
        except Exception as exc:
            log.error("[user_assets] metadata insert failed (non-fatal): %s", exc)

    return meta


def list_user_assets(
    user_id: str,
    asset_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return user assets, newest first. Optionally filter by type."""
    try:
        q = (
            _db._sb()
            .table(USER_ASSETS_TABLE)
            .select("*")
            .eq("user_id", user_id)
        )
        if asset_type and asset_type in VALID_ASSET_TYPES:
            q = q.eq("type", asset_type)
        resp = q.order("created_at", desc=True).limit(limit).execute()
        return resp.data or []
    except Exception as exc:
        log.warning("[user_assets] list failed: %s", exc)
        return []


def get_user_asset(user_id: str, asset_id: str) -> dict | None:
    """Get a single asset by ID (with ownership check)."""
    try:
        resp = (
            _db._sb()
            .table(USER_ASSETS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("id", asset_id)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as exc:
        log.warning("[user_assets] get failed: %s", exc)
        return None


def delete_user_asset(user_id: str, asset_id: str) -> bool:
    """Delete a user asset (metadata + storage file)."""
    asset = get_user_asset(user_id, asset_id)
    if not asset:
        return False

    # Delete from storage
    url = asset.get("url", "")
    if url:
        # Extract storage path from URL
        bucket_marker = f"/{_db.TEMPLATE_ASSETS_BUCKET}/"
        idx = url.find(bucket_marker)
        if idx != -1:
            storage_path = url[idx + len(bucket_marker):]
            try:
                _db._sb().storage.from_(
                    _db.TEMPLATE_ASSETS_BUCKET
                ).remove([storage_path])
            except Exception as exc:
                log.warning("[user_assets] storage delete failed: %s", exc)

    # Delete metadata
    try:
        _db._sb().table(USER_ASSETS_TABLE).delete().eq(
            "user_id", user_id
        ).eq("id", asset_id).execute()
        return True
    except Exception as exc:
        log.warning("[user_assets] metadata delete failed: %s", exc)
        return False
