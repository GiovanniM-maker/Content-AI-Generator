"""Database abstraction layer — Supabase PostgreSQL via PostgREST.

All CRUD operations for the Content AI Generator SaaS.
Uses the service_role key server-side (bypasses RLS).
Every query is scoped by user_id for multi-tenant isolation.
"""

import os
import uuid
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAROUSEL_BUCKET = "carousel-images"

# Retention days per plan (for automatic cleanup)
RETENTION_DAYS = {
    "free": 1,       # 24 hours
    "pro": 30,
    "business": 90,
}


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client: Client | None = None


def _sb() -> Client:
    """Get or create the Supabase client (lazy init)."""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment. "
                "See .env.example for required variables."
            )
        _client = create_client(url, key)
    return _client


def is_configured() -> bool:
    """Check if Supabase environment variables are set."""
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))


# =========================================================================
# STORAGE — Carousel images on Supabase Storage
# =========================================================================

TEMPLATE_ASSETS_BUCKET = "template-assets"
TEMPLATE_PREVIEWS_BUCKET = "template-previews"


def upload_template_asset(user_id: str, template_id: str, filename: str,
                          file_bytes: bytes, content_type: str = "image/png") -> str:
    """Upload an asset (logo, image) for a template.

    Path: {user_id}/{template_id}/{filename}
    Returns the full public URL.
    """
    path = f"{user_id}/{template_id}/{filename}"
    _sb().storage.from_(TEMPLATE_ASSETS_BUCKET).upload(
        path,
        file_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    url = _sb().storage.from_(TEMPLATE_ASSETS_BUCKET).get_public_url(path)
    return url.rstrip("?")


def ensure_template_previews_bucket():
    """Create the template-previews Storage bucket if it doesn't exist."""
    try:
        _sb().storage.create_bucket(
            TEMPLATE_PREVIEWS_BUCKET,
            options={"public": True},
        )
    except Exception:
        pass  # Already exists


def upload_template_preview_image(
    template_id: str, slide_type: str, png_bytes: bytes
) -> str:
    """Upload a rendered preview thumbnail to Storage.

    Path: {template_id}/{slide_type}.png
    Returns the full public URL.
    """
    path = f"{template_id}/{slide_type}.png"
    _sb().storage.from_(TEMPLATE_PREVIEWS_BUCKET).upload(
        path,
        png_bytes,
        file_options={"content-type": "image/png", "upsert": "true"},
    )
    url = _sb().storage.from_(TEMPLATE_PREVIEWS_BUCKET).get_public_url(path)
    return url.rstrip("?")


def update_preset_thumbnail_url(preset_id: str, urls_json: str):
    """Update thumbnail_url for a preset template (JSON string of slide URLs)."""
    _sb().table("preset_templates").update(
        {"thumbnail_url": urls_json}
    ).eq("id", preset_id).execute()


def upload_carousel_image(user_id: str, session_id: str, slide_index: int, png_bytes: bytes) -> str:
    """Upload a carousel PNG to Supabase Storage.

    Path: {user_id}/{session_id}/slide_{index}.png
    Returns the full public URL.
    """
    path = f"{user_id}/{session_id}/slide_{slide_index}.png"
    _sb().storage.from_(CAROUSEL_BUCKET).upload(
        path,
        png_bytes,
        file_options={"content-type": "image/png", "upsert": "true"},
    )
    url = _sb().storage.from_(CAROUSEL_BUCKET).get_public_url(path)
    # Strip trailing '?' that Supabase sometimes appends
    return url.rstrip("?")


def upload_carousel_images_batch(user_id: str, session_id: str, png_list: list[bytes]) -> list[str]:
    """Upload multiple carousel slide PNGs. Returns list of public URLs."""
    urls = []
    for i, png_bytes in enumerate(png_list):
        url = upload_carousel_image(user_id, session_id, i + 1, png_bytes)
        urls.append(url)
    return urls


def delete_carousel_images(user_id: str, session_id: str, num_slides: int = 20):
    """Delete all carousel images for a session from Storage."""
    paths = [f"{user_id}/{session_id}/slide_{i}.png" for i in range(1, num_slides + 1)]
    try:
        _sb().storage.from_(CAROUSEL_BUCKET).remove(paths)
    except Exception:
        pass  # Best-effort cleanup


def delete_user_carousel_folder(user_id: str):
    """Delete all carousel images for a user (used in retention cleanup)."""
    try:
        files = _sb().storage.from_(CAROUSEL_BUCKET).list(user_id)
        if files:
            # List all sub-folders (session IDs)
            for folder in files:
                folder_name = folder.get("name") or folder.get("id", "")
                if folder_name:
                    sub_path = f"{user_id}/{folder_name}"
                    sub_files = _sb().storage.from_(CAROUSEL_BUCKET).list(sub_path)
                    if sub_files:
                        paths = [f"{sub_path}/{f['name']}" for f in sub_files if f.get("name")]
                        if paths:
                            _sb().storage.from_(CAROUSEL_BUCKET).remove(paths)
    except Exception:
        pass


# =========================================================================
# RETENTION — Expired session cleanup
# =========================================================================

def get_expired_sessions(plan: str, user_id: str) -> list[dict]:
    """Get sessions older than the retention period for the given plan."""
    days = RETENTION_DAYS.get(plan, 1)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        _sb().table("sessions")
        .select("id, user_id, carousel_images")
        .eq("user_id", user_id)
        .lt("created_at", cutoff)
        .execute()
    )
    return result.data or []


def get_all_users_with_sessions() -> list[dict]:
    """Get distinct user_ids that have sessions (for retention cleanup)."""
    result = (
        _sb().table("sessions")
        .select("user_id")
        .execute()
    )
    seen = set()
    users = []
    for row in result.data or []:
        uid = row["user_id"]
        if uid not in seen:
            seen.add(uid)
            users.append({"user_id": uid})
    return users


def delete_sessions_batch(session_ids: list[str]) -> int:
    """Delete multiple sessions by ID. Returns count deleted."""
    if not session_ids:
        return 0
    result = (
        _sb().table("sessions")
        .delete()
        .in_("id", session_ids)
        .execute()
    )
    return len(result.data) if result.data else 0


# =========================================================================
# ARTICLES
# =========================================================================

def get_articles(user_id: str, min_score: int = 0) -> list[dict]:
    """Get all articles for a user, optionally filtered by minimum score."""
    q = _sb().table("articles").select("*").eq("user_id", user_id)
    if min_score:
        q = q.gte("score", min_score)
    result = q.order("score", desc=True).execute()
    return result.data


def get_article_urls(user_id: str) -> set[str]:
    """Get set of existing article URLs for deduplication."""
    result = (
        _sb().table("articles")
        .select("url")
        .eq("user_id", user_id)
        .execute()
    )
    return {r["url"] for r in result.data if r.get("url")}


def insert_articles(user_id: str, articles: list[dict]):
    """Insert new scored articles (batch insert in chunks of 50)."""
    if not articles:
        return
    rows = []
    for art in articles:
        rows.append({
            "user_id": user_id,
            "url": art.get("url"),
            "title": art.get("title"),
            "description": art.get("description"),
            "source": art.get("source"),
            "feed_category": art.get("feed_category"),
            "published": art.get("published"),
            "category": art.get("category"),
            "score": art.get("score", 5),
            "summary": art.get("summary"),
            "scored_at": art.get("scored_at"),
            "base_score": art.get("base_score"),
            "boost": art.get("boost"),
            "source_mode": art.get("source_mode", "rss"),
            "link": art.get("link"),
            "score_reason": art.get("score_reason"),
            "custom_text": art.get("custom_text"),
        })
    for i in range(0, len(rows), 50):
        _sb().table("articles").insert(rows[i:i + 50]).execute()


# =========================================================================
# SESSIONS
# =========================================================================

def _session_row_to_dict(row: dict) -> dict:
    """Convert a DB row to the frontend-compatible session dict."""
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "article": row.get("article") or {},
        "topics": row.get("topics") or [],
        "opinion": row.get("opinion", ""),
        "content": row.get("content") or {},
        "carousel_images": row.get("carousel_images") or {},
        "platforms": row.get("platforms") or [],
    }


def get_sessions(user_id: str) -> list[dict]:
    result = (
        _sb().table("sessions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [_session_row_to_dict(r) for r in result.data]


def get_session(user_id: str, session_id: str) -> dict | None:
    result = (
        _sb().table("sessions")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", session_id)
        .execute()
    )
    if result.data:
        return _session_row_to_dict(result.data[0])
    return None


def insert_session(user_id: str, data: dict) -> dict:
    row = {
        "user_id": user_id,
        "article": data.get("article", {}),
        "topics": data.get("topics", []),
        "opinion": data.get("opinion", ""),
        "content": data.get("content", {}),
        "carousel_images": data.get("carousel_images", {}),
        "platforms": data.get("platforms", []),
    }
    result = _sb().table("sessions").insert(row).execute()
    return _session_row_to_dict(result.data[0])


def update_session(user_id: str, session_id: str, updates: dict) -> dict | None:
    """Update a session. Only provided fields are changed."""
    allowed = {"content", "carousel_images", "article", "topics", "opinion", "platforms"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return get_session(user_id, session_id)
    result = (
        _sb().table("sessions")
        .update(filtered)
        .eq("user_id", user_id)
        .eq("id", session_id)
        .execute()
    )
    if result.data:
        return _session_row_to_dict(result.data[0])
    return None


def delete_session(user_id: str, session_id: str) -> bool:
    result = (
        _sb().table("sessions")
        .delete()
        .eq("user_id", user_id)
        .eq("id", session_id)
        .execute()
    )
    return bool(result.data)


# =========================================================================
# SCHEDULES
# =========================================================================

def get_schedules(user_id: str) -> list[dict]:
    result = (
        _sb().table("schedules")
        .select("*")
        .eq("user_id", user_id)
        .order("scheduled_at")
        .execute()
    )
    return result.data


def insert_schedule(user_id: str, data: dict) -> dict:
    row = {
        "user_id": user_id,
        "platform": data.get("platform", ""),
        "title": data.get("title", ""),
        "content_preview": (data.get("content_preview", "") or "")[:200],
        "content_key": data.get("content_key", ""),
        "session_id": data.get("session_id") or None,
        "scheduled_at": data.get("scheduled_at"),
        "status": "pending",
    }
    result = _sb().table("schedules").insert(row).execute()
    return result.data[0]


def insert_schedules_bulk(user_id: str, items: list[dict], scheduled_at: str) -> list[dict]:
    rows = []
    for item in items:
        rows.append({
            "user_id": user_id,
            "platform": item.get("platform", ""),
            "title": item.get("title", ""),
            "content_preview": (item.get("content_preview", "") or "")[:200],
            "content_key": item.get("content_key", ""),
            "session_id": item.get("session_id") or None,
            "scheduled_at": scheduled_at,
            "status": "pending",
        })
    result = _sb().table("schedules").insert(rows).execute()
    return result.data


def delete_schedule(user_id: str, item_id: str) -> bool:
    result = (
        _sb().table("schedules")
        .delete()
        .eq("user_id", user_id)
        .eq("id", item_id)
        .execute()
    )
    return bool(result.data)


def update_schedule(user_id: str, item_id: str, updates: dict) -> bool:
    """Update schedule fields (status, notified_at, published_at, etc.)."""
    allowed = {"status", "notified_at", "published_at", "scheduled_at"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return False
    result = (
        _sb().table("schedules")
        .update(filtered)
        .eq("user_id", user_id)
        .eq("id", item_id)
        .execute()
    )
    return bool(result.data)


def get_schedule_item(user_id: str, item_id: str) -> dict | None:
    result = (
        _sb().table("schedules")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", item_id)
        .execute()
    )
    return result.data[0] if result.data else None


def get_all_pending_schedules() -> list[dict]:
    """Get ALL pending schedules across all users (for background checker).
    Uses service_role key which bypasses RLS."""
    result = (
        _sb().table("schedules")
        .select("*")
        .eq("status", "pending")
        .execute()
    )
    return result.data


# =========================================================================
# FEEDBACK
# =========================================================================

def get_all_feedback(user_id: str) -> dict:
    """Get all feedback grouped by format_type: {format: [entries]}."""
    result = (
        _sb().table("feedback")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    grouped: dict[str, list] = {}
    for row in result.data:
        fmt = row["format_type"]
        if fmt not in grouped:
            grouped[fmt] = []
        grouped[fmt].append({
            "id": row["id"],
            "feedback": row["feedback"],
            "created_at": row["created_at"],
            "enriched_at": row.get("enriched_at"),
        })
    return grouped


def get_feedback_by_format(user_id: str, format_type: str) -> list[dict]:
    result = (
        _sb().table("feedback")
        .select("*")
        .eq("user_id", user_id)
        .eq("format_type", format_type)
        .order("created_at")
        .execute()
    )
    return [
        {
            "id": r["id"],
            "feedback": r["feedback"],
            "created_at": r["created_at"],
            "enriched_at": r.get("enriched_at"),
        }
        for r in result.data
    ]


def get_feedback_by_ids(user_id: str, feedback_ids: list[str]) -> list[dict]:
    """Get specific feedback entries by their IDs."""
    result = (
        _sb().table("feedback")
        .select("*")
        .eq("user_id", user_id)
        .in_("id", feedback_ids)
        .execute()
    )
    return [
        {
            "id": r["id"],
            "feedback": r["feedback"],
            "format_type": r["format_type"],
            "created_at": r["created_at"],
        }
        for r in result.data
    ]


def add_feedback(user_id: str, format_type: str, feedback_text: str) -> dict:
    result = (
        _sb().table("feedback")
        .insert({
            "user_id": user_id,
            "format_type": format_type,
            "feedback": feedback_text,
        })
        .execute()
    )
    return result.data[0]


def delete_feedback(user_id: str, feedback_id: str) -> bool:
    result = (
        _sb().table("feedback")
        .delete()
        .eq("user_id", user_id)
        .eq("id", feedback_id)
        .execute()
    )
    return bool(result.data)


def mark_feedback_enriched(user_id: str, feedback_ids: list[str]):
    """Mark feedback entries as used for prompt enrichment."""
    now = datetime.now(timezone.utc).isoformat()
    (
        _sb().table("feedback")
        .update({"enriched_at": now})
        .eq("user_id", user_id)
        .in_("id", feedback_ids)
        .execute()
    )


# =========================================================================
# FEEDS CONFIG
# =========================================================================

def get_feeds_config(user_id: str) -> dict:
    """Get RSS feed configuration. Returns {categories: {...}}."""
    result = (
        _sb().table("feeds_config")
        .select("categories")
        .eq("user_id", user_id)
        .execute()
    )
    if result.data:
        cats = result.data[0].get("categories") or {}
        return {"categories": cats}
    return {"categories": {}}


def save_feeds_config(user_id: str, config: dict):
    """Save entire feeds configuration (upsert)."""
    categories = config.get("categories", {})
    (
        _sb().table("feeds_config")
        .upsert({
            "user_id": user_id,
            "categories": categories,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id")
        .execute()
    )


# =========================================================================
# PIPELINE LOGS
# =========================================================================

def get_pipeline_logs(user_id: str, level: str | None = None, limit: int = 500) -> list[dict]:
    q = (
        _sb().table("pipeline_logs")
        .select("*")
        .eq("user_id", user_id)
    )
    if level:
        q = q.eq("level", level)
    result = q.order("created_at", desc=True).limit(limit).execute()
    return result.data


def add_pipeline_log(user_id: str, level: str, message: str, extra: dict | None = None):
    row = {
        "user_id": user_id,
        "level": level,
        "message": message,
    }
    if extra:
        row["extra"] = extra
    try:
        _sb().table("pipeline_logs").insert(row).execute()
    except Exception as e:
        import sys
        print(f"[PIPELINE LOG ERROR] {level}: {message} — DB error: {e}", file=sys.stderr)


# =========================================================================
# PROMPT LOGS
# =========================================================================

def get_prompt_logs(user_id: str) -> list[dict]:
    result = (
        _sb().table("prompt_logs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return result.data


def get_latest_prompt_version(user_id: str, prompt_name: str) -> dict | None:
    result = (
        _sb().table("prompt_logs")
        .select("*")
        .eq("user_id", user_id)
        .eq("prompt_name", prompt_name)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_prompt_version_count(user_id: str, prompt_name: str) -> int:
    result = (
        _sb().table("prompt_logs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("prompt_name", prompt_name)
        .execute()
    )
    return result.count or 0


def add_prompt_log(user_id: str, prompt_name: str, version: int, content: str, trigger: str = "init"):
    try:
        _sb().table("prompt_logs").insert({
            "user_id": user_id,
            "prompt_name": prompt_name,
            "version": version,
            "content": content,
            "trigger": trigger,
        }).execute()
    except Exception:
        pass


# =========================================================================
# USER PROMPTS (per-user active prompts)
# =========================================================================

def get_user_prompt(user_id: str, prompt_name: str) -> dict | None:
    """Get a single active prompt for a user by name."""
    result = (
        _sb().table("user_prompts")
        .select("*")
        .eq("user_id", user_id)
        .eq("prompt_name", prompt_name)
        .execute()
    )
    return result.data[0] if result.data else None


def get_all_user_prompts(user_id: str) -> dict[str, str]:
    """Get all active prompts for a user. Returns {prompt_name: content}."""
    result = (
        _sb().table("user_prompts")
        .select("prompt_name, content")
        .eq("user_id", user_id)
        .execute()
    )
    return {r["prompt_name"]: r["content"] for r in result.data}


def upsert_user_prompt(user_id: str, prompt_name: str, content: str, is_base: bool = False):
    """Insert or update a user's prompt."""
    _sb().table("user_prompts").upsert({
        "user_id": user_id,
        "prompt_name": prompt_name,
        "content": content,
        "is_base": is_base,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id,prompt_name").execute()


def init_user_prompts(user_id: str, base_prompts: dict[str, str]):
    """Copy base prompts to user_prompts if the user has none yet. Idempotent."""
    existing = get_all_user_prompts(user_id)
    if existing:
        return  # already initialized
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for name, content in base_prompts.items():
        rows.append({
            "user_id": user_id,
            "prompt_name": name,
            "content": content,
            "is_base": True,
            "created_at": now,
            "updated_at": now,
        })
    if rows:
        try:
            _sb().table("user_prompts").insert(rows).execute()
        except Exception:
            pass  # race condition or table not ready


# =========================================================================
# NOTIFICATIONS
# =========================================================================

def get_notifications(user_id: str, limit: int = 30) -> list[dict]:
    """Get recent notifications for a user, newest first."""
    try:
        result = (
            _sb().table("notifications")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data
    except Exception:
        return []


def get_unread_count(user_id: str) -> int:
    """Get count of unread notifications."""
    try:
        result = (
            _sb().table("notifications")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("read", False)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0


def create_notification(user_id: str, ntype: str, title: str, body: str = "") -> dict:
    """Create a new notification for a user."""
    try:
        result = (
            _sb().table("notifications")
            .insert({
                "user_id": user_id,
                "type": ntype,
                "title": title,
                "body": body,
            })
            .execute()
        )
        return result.data[0] if result.data else {}
    except Exception:
        return {}


def mark_notification_read(user_id: str, notification_id: str) -> bool:
    """Mark a single notification as read."""
    try:
        result = (
            _sb().table("notifications")
            .update({"read": True})
            .eq("user_id", user_id)
            .eq("id", notification_id)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


def mark_all_notifications_read(user_id: str) -> int:
    """Mark all unread notifications as read. Returns count marked."""
    try:
        result = (
            _sb().table("notifications")
            .update({"read": True})
            .eq("user_id", user_id)
            .eq("read", False)
            .execute()
        )
        return len(result.data) if result.data else 0
    except Exception:
        return 0


# =========================================================================
# SELECTION PREFERENCES
# =========================================================================

def get_selection_prefs(user_id: str) -> dict:
    result = (
        _sb().table("selection_prefs")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    if result.data:
        row = result.data[0]
        return {
            "source_counts": row.get("source_counts") or {},
            "category_counts": row.get("category_counts") or {},
            "keyword_counts": row.get("keyword_counts") or {},
            "total_selections": row.get("total_selections", 0),
            "updated_at": row.get("updated_at"),
        }
    return {
        "source_counts": {},
        "category_counts": {},
        "keyword_counts": {},
        "total_selections": 0,
        "updated_at": None,
    }


def save_selection_prefs(user_id: str, prefs: dict):
    (
        _sb().table("selection_prefs")
        .upsert({
            "user_id": user_id,
            "source_counts": prefs.get("source_counts", {}),
            "category_counts": prefs.get("category_counts", {}),
            "keyword_counts": prefs.get("keyword_counts", {}),
            "total_selections": prefs.get("total_selections", 0),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id")
        .execute()
    )


# =========================================================================
# WEEKLY STATUS
# =========================================================================

def get_weekly_status(user_id: str, week_key: str) -> dict:
    """Get weekly status for a specific week. Returns {week, platforms: {...}}."""
    result = (
        _sb().table("weekly_status")
        .select("*")
        .eq("user_id", user_id)
        .eq("week_key", week_key)
        .execute()
    )
    platforms = {}
    for row in result.data:
        platforms[row["platform"]] = {
            "generated": row.get("generated", 0),
            "approved": row.get("approved", 0),
            "scheduled": row.get("scheduled", 0),
            "published": row.get("published", 0),
        }
    return {"week": week_key, "platforms": platforms}


def increment_weekly_counter(user_id: str, week_key: str, platform: str, action: str):
    """Increment a weekly status counter using PostgreSQL function."""
    try:
        _sb().rpc("increment_weekly_status", {
            "p_user_id": user_id,
            "p_week_key": week_key,
            "p_platform": platform,
            "p_action": action,
        }).execute()
    except Exception:
        # Fallback: read-modify-write
        result = (
            _sb().table("weekly_status")
            .select("*")
            .eq("user_id", user_id)
            .eq("week_key", week_key)
            .eq("platform", platform)
            .execute()
        )
        if result.data:
            row = result.data[0]
            new_val = row.get(action, 0) + 1
            (
                _sb().table("weekly_status")
                .update({action: new_val})
                .eq("id", row["id"])
                .execute()
            )
        else:
            row = {
                "user_id": user_id,
                "week_key": week_key,
                "platform": platform,
                action: 1,
            }
            _sb().table("weekly_status").insert(row).execute()


# =========================================================================
# PROFILES
# =========================================================================

def get_profile(user_id: str) -> dict | None:
    result = (
        _sb().table("profiles")
        .select("*")
        .eq("id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def increment_generation_count(user_id: str) -> dict:
    """Increment the user's generation counters (lifetime + monthly) atomically.

    Uses a PostgreSQL RPC function to avoid race conditions.
    Falls back to read-modify-write if RPC is not available.

    Returns {"generation_count": int, "generation_count_monthly": int, "month": str}.
    """
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")

    try:
        # Atomic increment via PostgreSQL function
        result = _sb().rpc("increment_generation_count", {
            "p_user_id": user_id,
            "p_current_month": current_month,
        }).execute()
        if result.data:
            row = result.data[0]
            return {
                "generation_count": row.get("new_lifetime", 0),
                "generation_count_monthly": row.get("new_monthly", 0),
                "month": current_month,
            }
    except Exception:
        pass  # Fall through to non-atomic fallback

    # Fallback: read-modify-write (non-atomic, kept for backwards compatibility)
    profile = get_profile(user_id)
    if not profile:
        return {"generation_count": 0, "generation_count_monthly": 0, "month": current_month}

    lifetime = (profile.get("generation_count") or 0) + 1
    stored_month = profile.get("generation_count_month") or ""
    monthly = profile.get("generation_count_monthly") or 0

    if stored_month == current_month:
        monthly += 1
    else:
        monthly = 1

    _sb().table("profiles").update({
        "generation_count": lifetime,
        "generation_count_monthly": monthly,
        "generation_count_month": current_month,
        "updated_at": now.isoformat(),
    }).eq("id", user_id).execute()

    return {"generation_count": lifetime, "generation_count_monthly": monthly, "month": current_month}


def get_generation_counts(user_id: str) -> dict:
    """Get current generation counts for a user.

    Returns {"lifetime": int, "monthly": int, "month": str}.
    """
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")

    profile = get_profile(user_id)
    if not profile:
        return {"lifetime": 0, "monthly": 0, "month": current_month}

    lifetime = profile.get("generation_count") or 0
    stored_month = profile.get("generation_count_month") or ""
    monthly = profile.get("generation_count_monthly") or 0

    # If stored month doesn't match current month, monthly count is effectively 0
    if stored_month != current_month:
        monthly = 0

    return {"lifetime": lifetime, "monthly": monthly, "month": current_month}


def update_profile(user_id: str, updates: dict):
    allowed = {
        "full_name", "avatar_url", "plan", "stripe_customer_id",
        "openrouter_api_key_enc", "serper_api_key_enc", "fal_key_enc",
        "ntfy_topic", "beehiiv_pub_id",
        "generation_count", "generation_count_monthly", "generation_count_month",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return
    filtered["updated_at"] = datetime.now(timezone.utc).isoformat()
    _sb().table("profiles").update(filtered).eq("id", user_id).execute()


# =========================================================================
# SUBSCRIPTIONS
# =========================================================================

def get_subscription(user_id: str) -> dict | None:
    result = (
        _sb().table("subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def upsert_subscription(user_id: str, data: dict):
    row = {"user_id": user_id, **data}
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    _sb().table("subscriptions").upsert(row, on_conflict="user_id").execute()


# =========================================================================
# USER TEMPLATES
# =========================================================================

def get_user_templates(user_id: str, template_type: str = None) -> list[dict]:
    """Get all templates for a user, optionally filtered by type."""
    q = _sb().table("user_templates").select("*").eq("user_id", user_id)
    if template_type:
        q = q.eq("template_type", template_type)
    result = q.order("created_at", desc=True).execute()
    return result.data or []


def get_user_template_by_id(user_id: str, template_id: str) -> dict | None:
    """Get a single template by ID (with ownership check)."""
    result = (
        _sb().table("user_templates")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", template_id)
        .execute()
    )
    return result.data[0] if result.data else None


def count_user_templates(user_id: str) -> int:
    """Count total templates for a user (for plan limit check)."""
    result = (
        _sb().table("user_templates")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    return result.count or 0


def create_user_template(
    user_id: str,
    template_type: str,
    name: str,
    html_content: str = "",
    aspect_ratio: str = "1:1",
    chat_history: list = None,
    components: dict = None,
    style_rules: dict = None,
) -> dict:
    """Create a new user template."""
    row = {
        "user_id": user_id,
        "template_type": template_type,
        "name": name,
        "html_content": html_content,
        "aspect_ratio": aspect_ratio,
        "chat_history": chat_history or [],
        "components": components or {},
    }
    if style_rules is not None:
        row["style_rules"] = style_rules
    result = _sb().table("user_templates").insert(row).execute()
    return result.data[0] if result.data else {}


def update_user_template(
    template_id: str,
    user_id: str,
    html_content: str = None,
    chat_history: list = None,
    name: str = None,
    components: dict = None,
    style_rules: dict = None,
) -> dict:
    """Update an existing user template (with ownership check)."""
    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if html_content is not None:
        updates["html_content"] = html_content
    if chat_history is not None:
        updates["chat_history"] = chat_history
    if name is not None:
        updates["name"] = name
    if components is not None:
        updates["components"] = components
    if style_rules is not None:
        updates["style_rules"] = style_rules
    result = (
        _sb().table("user_templates")
        .update(updates)
        .eq("id", template_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else {}


def delete_user_template(template_id: str, user_id: str) -> bool:
    """Delete a user template (with ownership check)."""
    result = (
        _sb().table("user_templates")
        .delete()
        .eq("id", template_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(result.data)


def get_preset_templates(template_type: str = None) -> list[dict]:
    """Get all preset templates, optionally filtered by type."""
    q = _sb().table("preset_templates").select("*")
    if template_type:
        q = q.eq("template_type", template_type)
    result = q.order("name").execute()
    return result.data or []


def get_preset_template_by_id(preset_id: str) -> dict | None:
    """Get a single preset template by ID."""
    result = (
        _sb().table("preset_templates")
        .select("*")
        .eq("id", preset_id)
        .execute()
    )
    return result.data[0] if result.data else None


# =========================================================================
# AUTH HELPERS (for setup)
# =========================================================================

def create_admin_user(email: str, password: str) -> dict:
    """Create an admin/test user via Supabase Auth Admin API."""
    result = _sb().auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"full_name": "Admin"},
    })
    return {"id": result.user.id, "email": result.user.email}
