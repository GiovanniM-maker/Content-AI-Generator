"""Database abstraction layer — Supabase PostgreSQL via PostgREST.

All CRUD operations for the Content AI Generator SaaS.
Uses the service_role key server-side (bypasses RLS).
Every query is scoped by user_id for multi-tenant isolation.
"""

import os
from datetime import datetime, timezone

from supabase import create_client, Client


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
    result = (
        _sb().table("schedules")
        .update(updates)
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
    result = (
        _sb().table("notifications")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def get_unread_count(user_id: str) -> int:
    """Get count of unread notifications."""
    result = (
        _sb().table("notifications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("read", False)
        .execute()
    )
    return result.count or 0


def create_notification(user_id: str, ntype: str, title: str, body: str = "") -> dict:
    """Create a new notification for a user."""
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


def mark_notification_read(user_id: str, notification_id: str) -> bool:
    """Mark a single notification as read."""
    result = (
        _sb().table("notifications")
        .update({"read": True})
        .eq("user_id", user_id)
        .eq("id", notification_id)
        .execute()
    )
    return bool(result.data)


def mark_all_notifications_read(user_id: str) -> int:
    """Mark all unread notifications as read. Returns count marked."""
    result = (
        _sb().table("notifications")
        .update({"read": True})
        .eq("user_id", user_id)
        .eq("read", False)
        .execute()
    )
    return len(result.data) if result.data else 0


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


def update_profile(user_id: str, updates: dict):
    allowed = {
        "full_name", "avatar_url", "plan", "stripe_customer_id",
        "openrouter_api_key_enc", "serper_api_key_enc", "fal_key_enc",
        "ntfy_topic", "beehiiv_pub_id",
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
