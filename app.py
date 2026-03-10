#!/usr/bin/env python3
"""Content Creation Dashboard — Flask backend (Supabase edition)."""

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Response, stream_with_context, g

import db
import auth
import payments
import security

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())

BASE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Security initialization
# ---------------------------------------------------------------------------
security.init_sentry(app)
security.init_cors(app)
security.init_security_headers(app)
security.init_rate_limiter(app)


# ---------------------------------------------------------------------------
# Auth middleware — auto-extract JWT on every /api/ request
# ---------------------------------------------------------------------------

@app.before_request
def _before_request_auth():
    """Auto-extract auth token for all /api/ routes.
    Sets g.user_id, g.user_email if token is valid.
    Does NOT block unauthenticated requests (optional auth).
    """
    g.user_id = None
    g.user_email = None
    g.access_token = None

    path = request.path
    # Skip auth extraction for non-API routes and auth endpoints
    if not path.startswith("/api/") and not path.startswith("/auth/me"):
        return

    token = auth._extract_token()
    if token:
        payload = auth.verify_token(token)
        if payload:
            g.user_id = payload["sub"]
            g.user_email = payload.get("email", "")
            g.user_role = payload.get("role", "authenticated")
            g.user_metadata = payload.get("user_metadata", {})
            g.access_token = token

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_CHEAP = "google/gemini-2.0-flash-001"
MODEL_GENERATION = "anthropic/claude-sonnet-4-5"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
BEEHIIV_PUB_ID = os.getenv("BEEHIIV_PUB_ID", "")

DEFAULT_RSS_FEEDS = [
    "https://huggingface.co/blog/feed.xml",
    "https://techcrunch.com/feed/",
    "https://www.therundown.ai/rss",
    "https://news.mit.edu/topic/artificial-intelligence2/feed",
    "https://openai.com/blog/rss.xml",
    "https://www.anthropic.com/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://venturebeat.com/ai/feed/",
]

FETCH_WINDOW_DAYS = 5


# ---------------------------------------------------------------------------
# User context helper
# ---------------------------------------------------------------------------

def _get_user_id() -> str:
    """Get current user ID from request context.
    Checks g.user_id (set by auth decorators) first, then falls back to env default.
    """
    uid = getattr(g, "user_id", None)
    if uid:
        return uid
    return os.getenv("DEFAULT_USER_ID", "00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# LLM / utility helpers
# ---------------------------------------------------------------------------

def _llm_call(messages: list, model: str = MODEL_CHEAP, temperature: float = 0.3) -> str:
    """Call OpenRouter chat completion and return assistant content."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5001",
        "X-Title": "Content Dashboard",
    }
    payload = {"model": model, "messages": messages, "temperature": temperature}
    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers, json=payload, timeout=120,
    )
    content_type = resp.headers.get("Content-Type", "")
    if "application/json" not in content_type and "text/json" not in content_type:
        _log_pipeline("error", f"LLM returned non-JSON ({resp.status_code}): {resp.text[:200]}")
        raise RuntimeError(f"OpenRouter returned non-JSON response (HTTP {resp.status_code})")
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        err_msg = data["error"].get("message", str(data["error"]))
        _log_pipeline("error", f"LLM API error: {err_msg}", {"model": model})
        raise RuntimeError(f"OpenRouter API error: {err_msg}")
    return data["choices"][0]["message"]["content"]


def _parse_published(entry) -> datetime | None:
    """Extract published datetime from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, attr, None)
        if tp:
            try:
                return datetime(*tp[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Feeds config
# ---------------------------------------------------------------------------

def _load_feeds_config() -> dict:
    user_id = _get_user_id()
    config = db.get_feeds_config(user_id)
    if not config or not config.get("categories"):
        return {"categories": {
            "Tool Pratici": [],
            "Casi Studio": [],
            "Automazioni": [],
            "News AI Italia": [],
        }}
    return config


def _save_feeds_config(config: dict):
    user_id = _get_user_id()
    db.save_feeds_config(user_id, config)


def _get_all_feed_urls() -> list[str]:
    config = _load_feeds_config()
    urls = []
    for cat, feeds in config.get("categories", {}).items():
        for feed in feeds:
            if feed.get("url"):
                urls.append(feed["url"])
    return urls if urls else DEFAULT_RSS_FEEDS


# ---------------------------------------------------------------------------
# Feedback system
# ---------------------------------------------------------------------------

def _get_feedback_context(format_type: str) -> str:
    user_id = _get_user_id()
    entries = db.get_feedback_by_format(user_id, format_type)
    if not entries:
        return ""
    recent = entries[-10:]
    lines = [f"- {e['feedback']}" for e in recent]
    return "\n\nFEEDBACK ACCUMULATO (impara da queste indicazioni per migliorare lo stile):\n" + "\n".join(lines)


def _add_feedback(format_type: str, feedback: str):
    user_id = _get_user_id()
    db.add_feedback(user_id, format_type, feedback)
    _log_pipeline("feedback", f"[{format_type}] {feedback}")


def _delete_feedback(format_type: str, feedback_id: str) -> bool:
    user_id = _get_user_id()
    ok = db.delete_feedback(user_id, feedback_id)
    if ok:
        _log_pipeline("info", f"Feedback deleted from {format_type}: {feedback_id}")
    return ok


def _enrich_prompt_with_feedback(format_type: str, feedback_ids: list[str]) -> str:
    FORMAT_MAP = {
        "linkedin": FORMAT_LINKEDIN,
        "instagram": FORMAT_INSTAGRAM,
        "newsletter": FORMAT_NEWSLETTER,
        "twitter": FORMAT_TWITTER,
        "video_script": FORMAT_VIDEO_SCRIPT,
        "system_prompt": SYSTEM_PROMPT,
    }
    current_prompt = FORMAT_MAP.get(format_type, "")
    if not current_prompt:
        return ""

    user_id = _get_user_id()
    selected = db.get_feedback_by_ids(user_id, feedback_ids)
    if not selected:
        return current_prompt

    feedback_text = "\n".join(f"- {e['feedback']}" for e in selected)

    enrichment_msg = f"""Sei un esperto di prompt engineering. Devi MIGLIORARE il seguente prompt incorporando i feedback ricevuti dall'utente.

PROMPT ATTUALE:
---
{current_prompt}
---

FEEDBACK DELL'UTENTE DA INCORPORARE:
{feedback_text}

ISTRUZIONI:
1. Mantieni la STESSA struttura e formato del prompt originale
2. Integra i feedback come regole/indicazioni aggiuntive nel prompt
3. Non rimuovere indicazioni esistenti a meno che un feedback non le contraddica esplicitamente
4. Il risultato deve essere un prompt migliore, non un commento sul prompt
5. Restituisci SOLO il prompt migliorato, nient'altro
6. Mantieni la stessa lingua (italiano)"""

    try:
        result = _llm_call(
            [{"role": "user", "content": enrichment_msg}],
            model=MODEL_GENERATION, temperature=0.3,
        )
        return result.strip()
    except Exception as e:
        _log_pipeline("error", f"Prompt enrichment LLM error: {e}")
        return current_prompt


# ---------------------------------------------------------------------------
# Selection preferences (auto-boost scoring)
# ---------------------------------------------------------------------------

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "this", "that", "are",
    "was", "be", "has", "have", "had", "not", "no", "can", "will", "do",
    "how", "what", "why", "who", "new", "just", "more", "up", "out", "so",
    "now", "than", "into", "over", "after", "about", "also", "been", "could",
    "all", "some", "other", "your", "their", "as", "if", "when", "where",
    "here", "there", "would", "should", "may", "might", "must", "very",
    "says", "said", "get", "gets", "got", "one", "two", "first",
}


def _extract_keywords(title: str) -> list[str]:
    words = re.findall(r"[a-zA-Z]{3,}", title.lower())
    return [w for w in words if w not in STOP_WORDS]


def _track_selection(articles: list[dict]):
    user_id = _get_user_id()
    prefs = db.get_selection_prefs(user_id)
    for art in articles:
        source = art.get("source", "")
        category = art.get("category", "")
        title = art.get("title", "")
        if source:
            prefs["source_counts"][source] = prefs["source_counts"].get(source, 0) + 1
        if category:
            prefs["category_counts"][category] = prefs["category_counts"].get(category, 0) + 1
        for kw in _extract_keywords(title):
            prefs["keyword_counts"][kw] = prefs["keyword_counts"].get(kw, 0) + 1
    prefs["total_selections"] = prefs.get("total_selections", 0) + len(articles)
    db.save_selection_prefs(user_id, prefs)
    _log_pipeline("info", f"Selection preferences updated: {len(articles)} articles tracked")


def _calc_preference_bonus(article: dict, prefs: dict) -> float:
    if prefs["total_selections"] < 1:
        return 0.0
    source_counts = prefs.get("source_counts", {})
    max_source = max(source_counts.values()) if source_counts else 1
    source_w = source_counts.get(article.get("source", ""), 0) / max_source if max_source else 0
    cat_counts = prefs.get("category_counts", {})
    max_cat = max(cat_counts.values()) if cat_counts else 1
    cat_w = cat_counts.get(article.get("category", ""), 0) / max_cat if max_cat else 0
    kw_counts = prefs.get("keyword_counts", {})
    title_kws = _extract_keywords(article.get("title", ""))
    if title_kws and kw_counts:
        matching = sum(1 for kw in title_kws if kw in kw_counts)
        kw_w = matching / len(title_kws)
    else:
        kw_w = 0
    bonus = source_w * 0.5 + cat_w * 0.8 + kw_w * 0.7
    return round(min(2.0, bonus), 2)


# ---------------------------------------------------------------------------
# Prompt versioning & pipeline logging
# ---------------------------------------------------------------------------

def _log_prompt_version(prompt_name: str, content: str, trigger: str = "init"):
    user_id = _get_user_id()
    prev = db.get_latest_prompt_version(user_id, prompt_name)
    if prev and prev["content"] == content:
        return
    version = db.get_prompt_version_count(user_id, prompt_name) + 1
    db.add_prompt_log(user_id, prompt_name, version, content, trigger)


def _log_pipeline(level: str, message: str, extra: dict | None = None, user_id: str | None = None):
    uid = user_id or _get_user_id()
    db.add_pipeline_log(uid, level, message, extra)


def _snapshot_all_prompts(trigger: str = "init"):
    prompts = {
        "system_prompt": SYSTEM_PROMPT,
        "format_linkedin": FORMAT_LINKEDIN,
        "format_instagram": FORMAT_INSTAGRAM,
        "format_newsletter": FORMAT_NEWSLETTER,
        "format_twitter": FORMAT_TWITTER,
        "format_video_script": FORMAT_VIDEO_SCRIPT,
    }
    for name, content in prompts.items():
        _log_prompt_version(name, content, trigger)


# ---------------------------------------------------------------------------
# ntfy push notifications
# ---------------------------------------------------------------------------

def _send_ntfy(title: str, message: str, url: str | None = None, tags: str = "loudspeaker"):
    if not NTFY_TOPIC:
        _log_pipeline("warning", "ntfy notification skipped — no topic configured")
        return False
    try:
        payload = {
            "topic": NTFY_TOPIC,
            "title": title,
            "message": message,
            "tags": [t.strip() for t in tags.split(",")],
        }
        if url:
            payload["click"] = url
        resp = requests.post("https://ntfy.sh/", json=payload, timeout=10)
        resp.raise_for_status()
        _log_pipeline("info", f"ntfy notification sent: {title}")
        return True
    except Exception as e:
        _log_pipeline("error", f"ntfy send error: {e}")
        return False


# ---------------------------------------------------------------------------
# Scheduling system
# ---------------------------------------------------------------------------

def _check_schedules():
    """Background task: check for due scheduled items and send notifications."""
    while True:
        try:
            pending = db.get_all_pending_schedules()
            now = datetime.now(timezone.utc)

            for item in pending:
                scheduled_at = item.get("scheduled_at", "")
                if not scheduled_at:
                    continue
                try:
                    sched_dt = datetime.fromisoformat(str(scheduled_at))
                    if sched_dt.tzinfo is None:
                        sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue

                if now >= sched_dt:
                    platform = item.get("platform", "content")
                    title_text = item.get("title", "Contenuto programmato")
                    emoji_map = {"linkedin": "\U0001f4bc", "instagram": "\U0001f4f8", "newsletter": "\U0001f4e7"}
                    emoji = emoji_map.get(platform, "\U0001f4e2")
                    _send_ntfy(
                        title=f"{emoji} Pubblica {platform.upper()}",
                        message=f"{title_text}\n\nÈ ora di pubblicare questo contenuto!",
                        tags=f"{platform},bell",
                    )
                    item_user_id = item.get("user_id", _get_user_id())
                    db.update_schedule(item_user_id, item["id"], {
                        "status": "notified",
                        "notified_at": now.isoformat(),
                    })
                    _log_pipeline("info", f"Schedule notification sent for {platform}: {title_text}",
                                  user_id=item_user_id)
        except Exception as e:
            try:
                _log_pipeline("error", f"Schedule checker error: {e}")
            except Exception:
                pass
        time.sleep(30)


# ---------------------------------------------------------------------------
# Weekly status tracking
# ---------------------------------------------------------------------------

def _get_week_key(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


def _update_weekly_status(platform: str, action: str = "generated"):
    user_id = _get_user_id()
    week = _get_week_key()
    db.increment_weekly_counter(user_id, week, platform, action)


def _get_current_week_status() -> dict:
    user_id = _get_user_id()
    week = _get_week_key()
    return db.get_weekly_status(user_id, week)


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — Auth API
# ---------------------------------------------------------------------------

@app.route("/auth/signup", methods=["POST"])
def auth_signup():
    body = request.json or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password", "")
    full_name = (body.get("full_name") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email e password sono obbligatori"}), 400
    if len(password) < 6:
        return jsonify({"error": "La password deve avere almeno 6 caratteri"}), 400

    try:
        result = auth.signup(email, password, full_name)
        # If Supabase has email confirmation disabled, we get tokens immediately
        if result.get("access_token"):
            return jsonify({
                "status": "ok",
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token", ""),
                "user": {
                    "id": result.get("user", {}).get("id"),
                    "email": result.get("user", {}).get("email"),
                    "full_name": full_name,
                },
            })
        # Email confirmation required
        return jsonify({
            "status": "confirm_email",
            "message": "Controlla la tua email per confermare la registrazione.",
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Errore durante la registrazione: {e}"}), 500


@app.route("/auth/login", methods=["POST"])
def auth_login():
    body = request.json or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email e password sono obbligatori"}), 400

    try:
        result = auth.login(email, password)
        _log_pipeline("info", f"User logged in: {email}")
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 401
    except Exception as e:
        return jsonify({"error": f"Errore di login: {e}"}), 500


@app.route("/auth/refresh", methods=["POST"])
def auth_refresh():
    body = request.json or {}
    refresh_token = body.get("refresh_token", "")
    if not refresh_token:
        return jsonify({"error": "refresh_token required"}), 400

    try:
        result = auth.refresh_session(refresh_token)
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 401


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        auth.logout_server(token)
    return jsonify({"status": "ok"})


@app.route("/auth/me")
@auth.require_auth
def auth_me():
    """Get current authenticated user profile."""
    user_id = g.user_id
    profile = db.get_profile(user_id)
    subscription = db.get_subscription(user_id)
    return jsonify({
        "user": {
            "id": user_id,
            "email": g.user_email,
            "full_name": (profile or {}).get("full_name", ""),
            "avatar_url": (profile or {}).get("avatar_url", ""),
            "plan": (profile or {}).get("plan", "free"),
        },
        "subscription": {
            "plan": (subscription or {}).get("plan", "free"),
            "status": (subscription or {}).get("status", "active"),
        },
    })


# ---------------------------------------------------------------------------
# Routes — Payments (Stripe)
# ---------------------------------------------------------------------------

@app.route("/api/plans")
def get_plans():
    """Return available subscription plans and current user plan."""
    user_id = _get_user_id()
    subscription = db.get_subscription(user_id)
    current_plan = (subscription or {}).get("plan", "free")

    plans_data = {}
    for key, plan in payments.PLANS.items():
        plans_data[key] = {
            **plan,
            "current": key == current_plan,
        }

    return jsonify({
        "plans": plans_data,
        "current_plan": current_plan,
        "subscription_status": (subscription or {}).get("status", "active"),
        "stripe_publishable_key": payments.STRIPE_PUBLISHABLE_KEY,
    })


@app.route("/api/checkout", methods=["POST"])
@auth.require_auth
def create_checkout():
    """Create a Stripe Checkout session for upgrading."""
    body = request.json or {}
    plan = body.get("plan", "")

    if plan not in ("pro", "business"):
        return jsonify({"error": "Piano non valido"}), 400

    # Check if already on this plan
    subscription = db.get_subscription(g.user_id)
    if subscription and subscription.get("plan") == plan and subscription.get("status") == "active":
        return jsonify({"error": "Sei già su questo piano"}), 400

    base_url = request.host_url.rstrip("/")

    try:
        result = payments.create_checkout_session(
            user_id=g.user_id,
            email=g.user_email,
            plan=plan,
            base_url=base_url,
        )
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log_pipeline("error", f"Checkout session error: {e}")
        return jsonify({"error": "Errore nella creazione della sessione di pagamento"}), 500


@app.route("/api/billing/portal", methods=["POST"])
@auth.require_auth
def billing_portal():
    """Create a Stripe Customer Portal session."""
    base_url = request.host_url.rstrip("/")
    try:
        result = payments.create_portal_session(
            user_id=g.user_id,
            email=g.user_email,
            base_url=base_url,
        )
        return jsonify(result)
    except Exception as e:
        _log_pipeline("error", f"Billing portal error: {e}")
        return jsonify({"error": "Errore nell'apertura del portale di fatturazione"}), 500


@app.route("/api/subscription")
@auth.require_auth
def get_subscription_status():
    """Get current user subscription details."""
    subscription = db.get_subscription(g.user_id)
    profile = db.get_profile(g.user_id)
    plan = (subscription or {}).get("plan", "free")

    # Check generation usage
    usage = payments.check_generation_limit(g.user_id, plan)

    return jsonify({
        "subscription": subscription or {"plan": "free", "status": "active"},
        "plan_details": payments.get_plan_limits(plan),
        "usage": usage,
    })


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    event = payments.verify_webhook(payload, sig_header)
    if event is None:
        return jsonify({"error": "Invalid signature"}), 400

    result = payments.handle_webhook_event(event)
    _log_pipeline("info", f"Stripe webhook: {event.get('type', 'unknown')} → {result.get('action', 'ignored')}")

    return jsonify(result)


# ---------------------------------------------------------------------------
# Routes — User API Keys (encrypted storage)
# ---------------------------------------------------------------------------

@app.route("/api/settings/keys", methods=["GET"])
@auth.require_auth
def get_user_keys():
    """Get user's API key configuration status (not the actual keys)."""
    profile = db.get_profile(g.user_id)
    if not profile:
        return jsonify({"keys": {}})

    return jsonify({
        "keys": {
            "openrouter": bool(profile.get("openrouter_api_key_enc")),
            "serper": bool(profile.get("serper_api_key_enc")),
            "fal": bool(profile.get("fal_key_enc")),
            "ntfy_topic": profile.get("ntfy_topic", ""),
            "beehiiv_pub_id": profile.get("beehiiv_pub_id", ""),
        }
    })


@app.route("/api/settings/keys", methods=["POST"])
@auth.require_auth
def save_user_keys():
    """Save user's API keys (encrypted)."""
    body = request.json or {}
    updates = {}

    for field, db_field in [
        ("openrouter_key", "openrouter_api_key_enc"),
        ("serper_key", "serper_api_key_enc"),
        ("fal_key", "fal_key_enc"),
    ]:
        val = body.get(field, "").strip()
        if val:
            encrypted = security.encrypt_api_key(val)
            if encrypted:
                updates[db_field] = encrypted
            else:
                updates[db_field] = val  # Store plain if encryption not configured
        elif val == "":
            # Explicit empty string = clear the key
            if field in body:
                updates[db_field] = None

    # Non-encrypted fields
    if "ntfy_topic" in body:
        updates["ntfy_topic"] = body["ntfy_topic"].strip()
    if "beehiiv_pub_id" in body:
        updates["beehiiv_pub_id"] = body["beehiiv_pub_id"].strip()

    if updates:
        db.update_profile(g.user_id, updates)

    return jsonify({"status": "ok"})


@app.route("/api/settings/profile", methods=["GET"])
@auth.require_auth
def get_user_profile():
    """Get user profile."""
    profile = db.get_profile(g.user_id)
    subscription = db.get_subscription(g.user_id)
    return jsonify({
        "profile": {
            "id": g.user_id,
            "email": g.user_email,
            "full_name": (profile or {}).get("full_name", ""),
            "avatar_url": (profile or {}).get("avatar_url", ""),
            "plan": (profile or {}).get("plan", "free"),
            "ntfy_topic": (profile or {}).get("ntfy_topic", ""),
            "beehiiv_pub_id": (profile or {}).get("beehiiv_pub_id", ""),
        },
        "subscription": subscription or {"plan": "free", "status": "active"},
    })


@app.route("/api/settings/profile", methods=["PUT"])
@auth.require_auth
def update_user_profile():
    """Update user profile fields."""
    body = request.json or {}
    updates = {}
    if "full_name" in body:
        updates["full_name"] = body["full_name"].strip()
    if "avatar_url" in body:
        updates["avatar_url"] = body["avatar_url"].strip()
    if updates:
        db.update_profile(g.user_id, updates)
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Routes — Feeds Config API
# ---------------------------------------------------------------------------

@app.route("/api/feeds/config", methods=["GET"])
def get_feeds_config():
    return jsonify(_load_feeds_config())


@app.route("/api/feeds/config", methods=["POST"])
def save_feeds_config():
    body = request.json
    if not body or "categories" not in body:
        return jsonify({"error": "Invalid config format"}), 400
    _save_feeds_config(body)
    _log_pipeline("info", "Feeds configuration updated")
    return jsonify({"status": "ok"})


@app.route("/api/feeds/config/add", methods=["POST"])
def add_feed():
    body = request.json
    category = body.get("category", "").strip()
    url = body.get("url", "").strip()
    name = body.get("name", "").strip()
    if not category or not url:
        return jsonify({"error": "category and url required"}), 400
    config = _load_feeds_config()
    if category not in config["categories"]:
        config["categories"][category] = []
    existing_urls = [f["url"] for f in config["categories"][category]]
    if url in existing_urls:
        return jsonify({"error": "Feed URL already exists in this category"}), 409
    config["categories"][category].append({"url": url, "name": name or url})
    _save_feeds_config(config)
    _log_pipeline("info", f"Feed added: {url} → {category}")
    return jsonify({"status": "ok", "config": config})


@app.route("/api/feeds/config/remove", methods=["POST"])
def remove_feed():
    body = request.json
    category = body.get("category", "").strip()
    url = body.get("url", "").strip()
    if not category or not url:
        return jsonify({"error": "category and url required"}), 400
    config = _load_feeds_config()
    if category in config["categories"]:
        config["categories"][category] = [
            f for f in config["categories"][category] if f.get("url") != url
        ]
    _save_feeds_config(config)
    _log_pipeline("info", f"Feed removed: {url} from {category}")
    return jsonify({"status": "ok", "config": config})


@app.route("/api/feeds/config/add-category", methods=["POST"])
def add_category():
    body = request.json
    category = body.get("category", "").strip()
    if not category:
        return jsonify({"error": "category name required"}), 400
    config = _load_feeds_config()
    if category not in config["categories"]:
        config["categories"][category] = []
    _save_feeds_config(config)
    return jsonify({"status": "ok", "config": config})


@app.route("/api/feeds/config/remove-category", methods=["POST"])
def remove_category():
    body = request.json
    category = body.get("category", "").strip()
    if not category:
        return jsonify({"error": "category name required"}), 400
    config = _load_feeds_config()
    config["categories"].pop(category, None)
    _save_feeds_config(config)
    _log_pipeline("info", f"Category removed: {category}")
    return jsonify({"status": "ok", "config": config})


# ---------------------------------------------------------------------------
# Routes — RSS Fetch API
# ---------------------------------------------------------------------------

_fetch_progress: list[str] = []
_fetch_running = False


@app.route("/api/feeds/fetch", methods=["POST"])
def fetch_feeds():
    global _fetch_running, _fetch_progress
    if _fetch_running:
        return jsonify({"error": "Fetch already in progress"}), 409
    _fetch_running = True
    _fetch_progress = []

    def run():
        global _fetch_running
        try:
            _do_fetch()
        finally:
            _fetch_running = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/feeds/progress")
def feed_progress():
    def generate():
        sent = 0
        while True:
            while sent < len(_fetch_progress):
                msg = _fetch_progress[sent]
                yield f"data: {json.dumps({'msg': msg})}\n\n"
                sent += 1
            if not _fetch_running and sent >= len(_fetch_progress):
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
            time.sleep(0.3)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")


def _do_fetch():
    """Core fetch + score logic."""
    user_id = _get_user_id()
    seen_urls = db.get_article_urls(user_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=FETCH_WINDOW_DAYS)
    new_articles = []

    config = _load_feeds_config()
    feed_items = []
    for cat, feeds in config.get("categories", {}).items():
        for feed in feeds:
            feed_items.append({"url": feed["url"], "name": feed.get("name", ""), "category": cat})

    if not feed_items:
        feed_items = [{"url": u, "name": u, "category": ""} for u in DEFAULT_RSS_FEEDS]

    for fi in feed_items:
        feed_url = fi["url"]
        feed_cat = fi.get("category", "")
        _fetch_progress.append(f"Fetching {feed_url} ...")
        try:
            feed = feedparser.parse(feed_url)
            status = getattr(feed, "status", None)
            if status and status >= 400:
                _fetch_progress.append(f"  \u26a0 HTTP {status} — skipping this feed")
                _log_pipeline("warning", f"RSS feed HTTP {status}", {"feed": feed_url})
                continue
            source = feed.feed.get("title", feed_url)
            count = 0
            for entry in feed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue
                pub = _parse_published(entry)
                if pub and pub < cutoff:
                    continue
                title = entry.get("title", "No title")
                description = entry.get("summary", entry.get("description", ""))
                description = re.sub(r"<[^>]+>", "", description)[:500]
                new_articles.append({
                    "url": url,
                    "title": title,
                    "description": description,
                    "source": source,
                    "feed_category": feed_cat,
                    "published": pub.isoformat() if pub else datetime.now(timezone.utc).isoformat(),
                })
                seen_urls.add(url)
                count += 1
            _fetch_progress.append(f"  \u2192 {count} new articles from {source}")
            if count > 0:
                _log_pipeline("info", f"Fetched {count} articles from {source}", {"feed": feed_url})
        except Exception as e:
            _fetch_progress.append(f"  \u26a0 Error fetching {feed_url}: {e}")
            _log_pipeline("error", f"RSS fetch error: {e}", {"feed": feed_url})

    _fetch_progress.append(f"\nTotal new articles to score: {len(new_articles)}")

    # Score in batches of 5
    scored = []
    for i in range(0, len(new_articles), 5):
        batch = new_articles[i:i + 5]
        _fetch_progress.append(f"Scoring articles {i + 1}-{i + len(batch)} ...")
        try:
            articles_text = ""
            for idx, art in enumerate(batch):
                articles_text += f"\n---\nARTICLE {idx + 1}:\nTitle: {art['title']}\nDescription: {art['description']}\n"

            prompt = f"""Analyze these articles about AI/tech. For EACH article return a JSON array element with:
- "index": article number (1-based)
- "category": one of ["Tool Pratici", "Casi Studio", "Automazioni", "News AI Italia"]
- "score": integer 1-10 (relevance + novelty + practical value for an AI automation consultant)
- "summary": one-line summary in Italian

Return ONLY a valid JSON array, no markdown, no explanation.
{articles_text}"""

            result = _llm_call([{"role": "user", "content": prompt}])
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1]
                result = result.rsplit("```", 1)[0]
            parsed = json.loads(result)

            for item in parsed:
                idx = item["index"] - 1
                if 0 <= idx < len(batch):
                    art = batch[idx]
                    art["category"] = item.get("category", art.get("feed_category", "News AI Italia"))
                    art["score"] = int(item.get("score", 5))
                    art["summary"] = item.get("summary", "")
                    art["scored_at"] = datetime.now(timezone.utc).isoformat()
                    scored.append(art)
        except Exception as e:
            _fetch_progress.append(f"  \u26a0 Scoring error: {e}")
            _log_pipeline("error", f"LLM scoring error: {e}", {"batch_start": i})
            for art in batch:
                art["category"] = art.get("feed_category", "News AI Italia")
                art["score"] = 5
                art["summary"] = art["title"]
                art["scored_at"] = datetime.now(timezone.utc).isoformat()
                scored.append(art)

    # Apply preference boost
    prefs = db.get_selection_prefs(user_id)
    if prefs["total_selections"] > 0:
        _fetch_progress.append(f"\nApplying preference boost (based on {prefs['total_selections']} past selections)...")
        boosted_count = 0
        for art in scored:
            bonus = _calc_preference_bonus(art, prefs)
            if bonus > 0:
                art["base_score"] = art["score"]
                art["boost"] = bonus
                art["score"] = min(10, round(art["score"] + bonus))
                boosted_count += 1
        _fetch_progress.append(f"  \u2192 {boosted_count} articles boosted")

    # Save new articles to database
    db.insert_articles(user_id, scored)
    _fetch_progress.append(f"\n\u2713 Done! {len(scored)} articles scored and saved.")
    _log_pipeline("info", f"Fetch complete: {len(scored)} articles scored and saved")

    if scored:
        _send_ntfy(
            title="\U0001f4f0 Feed aggiornato",
            message=f"{len(scored)} nuovi articoli analizzati e pronti per la selezione.",
            url="http://localhost:5001",
            tags="newspaper",
        )


@app.route("/api/articles")
def get_articles():
    user_id = _get_user_id()
    min_score = request.args.get("min_score", 0, type=int)
    articles = db.get_articles(user_id, min_score=min_score)
    return jsonify(articles)


# ---------------------------------------------------------------------------
# Content Generation Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Sei il ghostwriter di Juan, un consulente italiano di AI automation specializzato in retail ed eCommerce.
Il tuo compito è scrivere contenuti che posizionano Juan come un esperto pratico e onesto di AI applicata al business reale.

TONO DI VOCE:
- Diretto e pratico, mai accademico
- Onesto: se una cosa non funziona, lo dici
- Scorrevole e facile da leggere
- Non prolisso: ogni parola deve guadagnarsi il suo posto
- Coinvolgente: poni domande al lettore, poi dai le risposte più avanti nel testo
- Mai hype, mai buzzword vuote
- Scrivi come se stessi spiegando a un imprenditore italiano intelligente ma non tecnico

FONTE PRIMARIA: l'articolo selezionato
FONTE SECONDARIA: il punto di vista personale di Juan (integra sempre la sua opinione nel testo, in prima persona, come se fosse sua)
LINGUA: Italiano, con termini tecnici in inglese dove necessario (AI, workflow, ecc.)"""

FORMAT_LINKEDIN = """Formato LinkedIn — FOCUS: VALORE DI BUSINESS
- Lunghezza: 200-300 parole
- ANGOLO: Non tecnico. Parla di produttività, risparmio, economics, vantaggio competitivo.
  Traduci ogni novità tech in "cosa cambia per il mio business"
- Prima riga: hook forte che ferma lo scroll — affermazione controintuitiva O dato economico sorprendente
  O domanda provocatoria che tocca un nervo imprenditoriale
- Struttura:
  * Hook (1 riga)
  * Contesto: qual è il problema/opportunità di business (2-3 righe)
  * Insight pratico: cosa significa per chi gestisce un'azienda (3-4 righe)
  * Opinione personale di Juan, in prima persona (2-3 righe)
  * Domanda aperta che invita commenti da imprenditori/manager
- CTA finale: "Se vuoi approfondire, sono nella newsletter (link in bio)"
- Max 2-3 emoji, niente bullet points lunghi
- NON usare gergo tecnico senza spiegarlo in termini di business impact"""

FORMAT_INSTAGRAM = """Formato Instagram — CAROSELLO (slide separate)
- Struttura: restituisci il testo diviso in SLIDE, ognuna separata da ---SLIDE---
- SLIDE 1 (copertina): titolo forte da 5-8 parole, massimo impatto visivo, SOLO il titolo
- SLIDE 2-5 (contenuto): ogni slide ha UN singolo concetto chiave in 2-3 righe brevi.
  Vai dritto al punto. Ogni slide deve avere valore autonomo anche senza le altre.
  Usa frasi corte, spezza i concetti. Niente giri di parole.
- SLIDE FINALE: CTA + domanda che invita interazione ("Salva questo post se..." o "Qual è la tua esperienza con...")
- CAPTION (dopo l'ultima slide, separata da ---CAPTION---):
  * 1 frase riassuntiva + domanda al lettore
  * 5-8 hashtag rilevanti (#AIItalia #automazione #intelligenzaartificiale #ecommerce #retail + contestuali)
- Tono: diretto, visivo, zero filler. Ogni parola deve guadagnarsi il suo spazio nel carosello.
- Lunghezza totale: 4-6 slide + caption"""

FORMAT_NEWSLETTER = """Formato Newsletter settimanale (Beehiiv):
- Lunghezza: 600-900 parole
- Struttura:
  * Titolo oggetto email (max 50 caratteri, deve invogliare ad aprire)
  * Apertura: scenario concreto o domanda che aggancia (2-3 righe)
  * SEZIONE 1, 2, 3: un paragrafo per ogni topic della settimana (4-6 righe ciascuno),
    con l'opinione di Juan integrata naturalmente in prima persona
  * SEZIONE ESCLUSIVA: un insight, consiglio pratico o previsione che NON si trova
    nei topic trattati — qualcosa che solo Juan può dare ai suoi lettori
    (es. un workflow che ha testato, un tool nascosto, una riflessione controcorrente)
  * Chiusura: takeaway pratico in 1-2 righe + invito a rispondere alla mail
- Stile conversazionale, come una lettera a un amico imprenditore
- Niente formattazione pesante, max un grassetto per concetto chiave"""

FORMAT_TWITTER = """Formato Twitter/X — POST O THREAD
- Se il contenuto si presta: singolo tweet (max 280 caratteri), potente e shareable
- Se il tema è più complesso: thread da 3-5 tweet, ogni tweet è autonomo ma collegato
- Per thread: separa ogni tweet con ---TWEET---
- TWEET 1: hook forte, l'affermazione più controversa o il dato più sorprendente
- TWEET 2-4: sviluppo dell'argomentazione, un punto per tweet
- TWEET FINALE: takeaway pratico + CTA ("Seguimi per più insights su AI e business")
- Tono: diretto, assertivo, leggermente provocatorio
- Usa 1-2 hashtag MAX nel tweet finale
- Niente emoji eccessive, max 1 per tweet
- Scrivi come un founder che condivide una lezione appena imparata"""

FORMAT_VIDEO_SCRIPT = """Formato Short Video Script (Reels/TikTok/Shorts — 60-90 secondi):
- Struttura OBBLIGATORIA con sezioni separate da ---SECTION---:
  * HOOK (primi 3 secondi): frase d'apertura che ferma lo scroll. Inizia con una domanda
    provocatoria, un'affermazione scioccante, o "La maggior parte delle persone non sa che..."
  * PROBLEMA (10-15 sec): descrivi il pain point che il viewer riconosce immediatamente
  * SOLUZIONE (20-30 sec): la risposta pratica, spiega in modo semplice.
    Usa frasi brevi, ritmo veloce. "Ecco cosa devi fare:", "Step 1...", "Step 2..."
  * RISULTATO (10 sec): cosa cambia concretamente. Dai un numero o un esempio reale.
  * CTA (5 sec): "Salva questo video", "Seguimi per altri consigli", "Commenta se vuoi il tutorial completo"
- Scrivi ESATTAMENTE come si parla, non come si scrive
- Frasi da max 10-12 parole. Ritmo incalzante.
- Tra parentesi [TESTO A SCHERMO] indica i text overlay per i punti chiave
- Tra parentesi [B-ROLL] suggerisci riprese di supporto
- Lunghezza totale: 150-200 parole parlate
- Lingua: italiano parlato, informale ma competente"""


IG_VARIANT_ANGLES = [
    "",
    "\nANGOLO SPECIFICO: Focalizzati sull'aspetto PRATICO e operativo. Come si implementa concretamente? Che workflow o tool servono? Dai step actionable.",
    "\nANGOLO SPECIFICO: Focalizzati sull'aspetto STRATEGICO e di business impact. Perché un imprenditore dovrebbe interessarsi? Quali numeri contano? ROI, risparmio tempo, vantaggio competitivo.",
    "\nANGOLO SPECIFICO: Focalizzati sugli ERRORI COMUNI e le trappole. Cosa sbagliano tutti? Qual è il consiglio controintuitivo? Tono myth-busting, sfida le convinzioni del lettore.",
]


# ---------------------------------------------------------------------------
# Web Search (Serper API)
# ---------------------------------------------------------------------------

def _serper_search(query: str, num_results: int = 10) -> list[dict]:
    if not SERPER_API_KEY:
        raise ValueError("SERPER_API_KEY not configured in .env")
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
        json={"q": query, "num": num_results, "gl": "it", "hl": "it"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": item.get("link", "").split("/")[2] if "/" in item.get("link", "") else "",
            "position": item.get("position", 0),
        })
    return results


@app.route("/api/search", methods=["POST"])
def web_search():
    body = request.json
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query required"}), 400
    num = min(body.get("num_results", 10), 20)
    try:
        results = _serper_search(query, num)
        _log_pipeline("info", f"Web search: '{query}' → {len(results)} results")
        return jsonify({"results": results, "query": query})
    except Exception as e:
        _log_pipeline("error", f"Search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search/score", methods=["POST"])
def search_score():
    body = request.json
    results = body.get("results", [])
    if not results:
        return jsonify({"error": "No results to score"}), 400
    scored = []
    for item in results:
        article = {
            "title": item.get("title", ""),
            "summary": item.get("snippet", ""),
            "description": item.get("snippet", ""),
            "source": item.get("source", ""),
            "link": item.get("link", ""),
            "published": datetime.now(timezone.utc).isoformat(),
            "category": "web_search",
            "source_mode": "web_search",
        }
        try:
            prompt = f"""Sei un content strategist per un consulente AI italiano.
Valuta questo risultato web per potenziale contenuto:
Titolo: {article['title']}
Snippet: {article['summary']}
Fonte: {article['source']}

Rispondi SOLO con un JSON: {{"score": N, "reason": "motivo breve"}}
Score da 1 a 10 (10 = perfetto per content su AI/automazione business)."""
            result = _llm_call(
                [{"role": "user", "content": prompt}],
                model=MODEL_CHEAP, temperature=0.1,
            )
            data = json.loads(result.strip().strip("```json").strip("```"))
            article["score"] = data.get("score", 5)
            article["score_reason"] = data.get("reason", "")
        except Exception:
            article["score"] = 5
            article["score_reason"] = "Scoring failed"
        scored.append(article)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify({"articles": scored})


# ---------------------------------------------------------------------------
# Routes — Content Generation
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
def generate_content():
    body = request.json
    article = body.get("article", {})
    opinion = body.get("opinion", "")
    format_type = body.get("format")
    feedback = body.get("feedback", "")
    variant = body.get("variant", 0)

    FORMAT_MAP = {
        "linkedin": FORMAT_LINKEDIN,
        "instagram": FORMAT_INSTAGRAM,
        "twitter": FORMAT_TWITTER,
        "video_script": FORMAT_VIDEO_SCRIPT,
    }
    if format_type not in FORMAT_MAP:
        return jsonify({"error": f"format must be one of: {', '.join(FORMAT_MAP.keys())}"}), 400

    # --- Plan gating ---
    user_id = _get_user_id()
    subscription = db.get_subscription(user_id)
    user_plan = (subscription or {}).get("plan", "free")

    # Check platform access
    if not payments.check_platform_access(user_plan, format_type):
        return jsonify({
            "error": f"La piattaforma '{format_type}' non è disponibile nel piano {user_plan.upper()}. Effettua l'upgrade per accedervi.",
            "code": "PLAN_LIMIT",
            "upgrade_required": True,
        }), 403

    # Check generation limit
    usage = payments.check_generation_limit(user_id, user_plan)
    if not usage["allowed"]:
        return jsonify({
            "error": f"Hai raggiunto il limite di {usage['limit']} generazioni/mese per il piano {user_plan.upper()}. Effettua l'upgrade per continuare.",
            "code": "GENERATION_LIMIT",
            "upgrade_required": True,
            "used": usage["used"],
            "limit": usage["limit"],
        }), 403

    if feedback:
        _add_feedback(format_type, feedback)

    fmt = FORMAT_MAP[format_type]
    if format_type == "instagram" and 0 < variant < len(IG_VARIANT_ANGLES):
        fmt += IG_VARIANT_ANGLES[variant]

    regen_instruction = ""
    if feedback:
        regen_instruction = f"\n\nISTRUZIONE DI RISCRITTURA (priorità alta, segui questa indicazione):\n{feedback}"

    if opinion:
        opinion_section = f"\nOPINIONE DI JUAN:\n{opinion}"
    else:
        opinion_section = "\nNOTA: Questa è una prima bozza. Juan non ha ancora aggiunto la sua prospettiva personale. Genera il contenuto basandoti sull'articolo, mantenendo il tono di Juan. L'opinione verrà integrata nella prossima iterazione."

    source_mode = article.get("source_mode", "rss")
    if source_mode == "custom_text":
        custom_text = body.get("custom_text", "") or article.get("custom_text", "")
        user_msg = f"""TESTO PERSONALIZZATO (fonte diretta dell'utente):
{custom_text}
{opinion_section}

FORMATO RICHIESTO:
{fmt}{regen_instruction}

Scrivi il contenuto ora. Restituisci SOLO il testo del post/caption, senza commenti aggiuntivi."""
    else:
        user_msg = f"""ARTICOLO SELEZIONATO:
Titolo: {article.get('title', '')}
Fonte: {article.get('source', '')}
Riassunto: {article.get('summary', '')}
Descrizione: {article.get('description', '')}
{opinion_section}

FORMATO RICHIESTO:
{fmt}{regen_instruction}

Scrivi il contenuto ora. Restituisci SOLO il testo del post/caption, senza commenti aggiuntivi."""

    try:
        result = _llm_call(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=MODEL_GENERATION, temperature=0.7,
        )
        _log_pipeline("info", f"Generated {format_type} content", {"article": article.get("title", "")})
        _update_weekly_status(format_type, "generated")
        return jsonify({"content": result, "format": format_type})
    except Exception as e:
        _log_pipeline("error", f"LLM generation error ({format_type}): {e}")
        return jsonify({"error": f"LLM error: {e}"}), 500


@app.route("/api/generate-newsletter", methods=["POST"])
def generate_newsletter():
    body = request.json
    topics = body.get("topics", [])
    feedback = body.get("feedback", "")
    if not topics or len(topics) < 1:
        return jsonify({"error": "At least 1 topic required"}), 400
    if feedback:
        _add_feedback("newsletter", feedback)
    has_opinions = any(t.get("opinion", "").strip() for t in topics)
    topics_text = ""
    for i, t in enumerate(topics, 1):
        art = t.get("article", {})
        op = t.get("opinion", "")
        topics_text += f"""
--- TOPIC {i} ---
Titolo: {art.get('title', '')}
Fonte: {art.get('source', '')}
Riassunto: {art.get('summary', '')}
Descrizione: {art.get('description', '')}
"""
        if op:
            topics_text += f"Opinione di Juan: {op}\n"
    if not has_opinions:
        topics_text += "\nNOTA: Questa è una prima bozza. Juan non ha ancora aggiunto le sue prospettive personali.\n"
    regen_instruction = ""
    if feedback:
        regen_instruction = f"\n\nISTRUZIONE DI RISCRITTURA (priorità alta, segui questa indicazione):\n{feedback}"

    user_msg = f"""Questa settimana Juan ha selezionato questi topic per la sua newsletter:
{topics_text}

FORMATO RICHIESTO:
{FORMAT_NEWSLETTER}{regen_instruction}

IMPORTANTE: La sezione esclusiva deve essere un valore aggiunto reale.

Scrivi la newsletter ora. Restituisci SOLO il testo completo, senza commenti aggiuntivi."""

    try:
        result = _llm_call(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=MODEL_GENERATION, temperature=0.7,
        )
        _log_pipeline("info", "Generated newsletter")
        _update_weekly_status("newsletter", "generated")
        return jsonify({"content": result, "format": "newsletter"})
    except Exception as e:
        _log_pipeline("error", f"LLM newsletter error: {e}")
        return jsonify({"error": f"LLM error: {e}"}), 500


@app.route("/api/newsletter/html", methods=["POST"])
def newsletter_to_html():
    body = request.json
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    conversion_prompt = """Converti il seguente testo di newsletter in HTML email-ready con inline CSS.

REGOLE IMPORTANTI:
1. Usa SOLO inline CSS (no <style> tags, no classi CSS esterne). Ogni elemento ha il suo style="..."
2. Layout: max-width 600px, centrato, padding adeguato, sfondo bianco
3. Tipografia: font-family 'Helvetica Neue', Helvetica, Arial, sans-serif
4. Colori: testo principale #1a1a2e, titoli #16213e, link #6c5ce7, sfondo #f8f9fa per wrapper
5. Il titolo/oggetto email → <h1> grande e accattivante
6. Sezioni con heading <h2>, separatori sottili tra sezioni
7. Evidenzia i grassetti (**testo**) con <strong style="color:#6c5ce7;">
8. Aggiungi un header con il brand "Juan — AI Automation" e un footer con unsubscribe placeholder
9. Rendi la sezione esclusiva visivamente distinta (bordo laterale colorato o sfondo diverso)
10. Responsive: usa percentage widths dove possibile
11. Restituisci SOLO il codice HTML completo (da <!DOCTYPE html> a </html>), nient'altro.

TESTO NEWSLETTER:
"""

    try:
        result = _llm_call(
            [
                {"role": "system", "content": "Sei un esperto di email HTML design. Converti il testo in HTML email con inline CSS perfetto per Beehiiv."},
                {"role": "user", "content": conversion_prompt + text},
            ],
            model=MODEL_GENERATION, temperature=0.3,
        )
        html_result = result.strip()
        if html_result.startswith("```html"):
            html_result = html_result[7:]
        if html_result.startswith("```"):
            html_result = html_result[3:]
        if html_result.endswith("```"):
            html_result = html_result[:-3]
        html_result = html_result.strip()
        _log_pipeline("info", "Converted newsletter to HTML")
        return jsonify({"html": html_result})
    except Exception as e:
        _log_pipeline("error", f"Newsletter HTML conversion error: {e}")
        return jsonify({"error": f"Conversion error: {e}"}), 500


# ---------------------------------------------------------------------------
# Routes — Scheduling
# ---------------------------------------------------------------------------

@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    user_id = _get_user_id()
    schedule = db.get_schedules(user_id)
    return jsonify(schedule)


@app.route("/api/schedule", methods=["POST"])
def create_schedule():
    user_id = _get_user_id()
    body = request.json
    item = db.insert_schedule(user_id, body)
    _update_weekly_status(item.get("platform", ""), "scheduled")
    _log_pipeline("info", f"Content scheduled: {item.get('platform', '')} at {item.get('scheduled_at', '')}")
    return jsonify(item)


@app.route("/api/schedule/bulk", methods=["POST"])
def create_schedule_bulk():
    user_id = _get_user_id()
    body = request.json
    items_data = body.get("items", [])
    scheduled_at = body.get("scheduled_at", "")
    if not items_data or not scheduled_at:
        return jsonify({"error": "items and scheduled_at required"}), 400
    created = db.insert_schedules_bulk(user_id, items_data, scheduled_at)
    for item in created:
        _update_weekly_status(item.get("platform", ""), "scheduled")
    _log_pipeline("info", f"Bulk scheduled {len(created)} items at {scheduled_at}")
    return jsonify({"status": "ok", "count": len(created), "items": created})


@app.route("/api/schedule/<item_id>", methods=["DELETE"])
def delete_schedule(item_id):
    user_id = _get_user_id()
    db.delete_schedule(user_id, item_id)
    return jsonify({"status": "ok"})


@app.route("/api/schedule/<item_id>/publish", methods=["POST"])
def mark_published(item_id):
    user_id = _get_user_id()
    db.update_schedule(user_id, item_id, {
        "status": "published",
        "published_at": datetime.now(timezone.utc).isoformat(),
    })
    # Get item to know the platform
    item = db.get_schedule_item(user_id, item_id)
    if item:
        _update_weekly_status(item.get("platform", ""), "published")
    return jsonify({"status": "ok"})


@app.route("/api/schedule/<item_id>/content")
def get_schedule_content(item_id):
    user_id = _get_user_id()
    item = db.get_schedule_item(user_id, item_id)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    session_id = item.get("session_id", "")
    content_key = item.get("content_key", "")
    full_content = ""
    if session_id and content_key:
        session = db.get_session(user_id, session_id)
        if session:
            full_content = session.get("content", {}).get(content_key, "")
    if not full_content:
        full_content = item.get("content_preview", "")
    return jsonify({
        "content": full_content,
        "title": item.get("title", ""),
        "platform": item.get("platform", ""),
        "scheduled_at": item.get("scheduled_at", ""),
        "status": item.get("status", ""),
        "id": item_id,
    })


# ---------------------------------------------------------------------------
# Routes — Weekly Status
# ---------------------------------------------------------------------------

@app.route("/api/weekly-status")
def weekly_status():
    return jsonify(_get_current_week_status())


# ---------------------------------------------------------------------------
# Routes — Approve Content
# ---------------------------------------------------------------------------

@app.route("/api/approve", methods=["POST"])
def approve_content():
    body = request.json
    platform = body.get("platform", "")
    if platform:
        _update_weekly_status(platform, "approved")
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Routes — Sessions & Other APIs
# ---------------------------------------------------------------------------

@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    user_id = _get_user_id()
    sessions = db.get_sessions(user_id)
    return jsonify(sessions)


@app.route("/api/sessions", methods=["POST"])
def save_session():
    user_id = _get_user_id()
    body = request.json
    session = db.insert_session(user_id, body)
    return jsonify(session)


@app.route("/api/sessions/<session_id>", methods=["PUT"])
def update_session(session_id):
    user_id = _get_user_id()
    body = request.json
    updates = {}
    if "content" in body:
        updates["content"] = body["content"]
    if "carousel_images" in body:
        updates["carousel_images"] = body["carousel_images"]
    result = db.update_session(user_id, session_id, updates)
    if result is None:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(result)


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    user_id = _get_user_id()
    ok = db.delete_session(user_id, session_id)
    if not ok:
        return jsonify({"error": "Session not found"}), 404
    _log_pipeline("info", f"Deleted session {session_id}")
    return jsonify({"ok": True})


@app.route("/api/feedback")
def get_feedback():
    user_id = _get_user_id()
    return jsonify(db.get_all_feedback(user_id))


@app.route("/api/feedback", methods=["POST"])
def add_feedback_direct():
    body = request.json
    format_type = body.get("format_type") or body.get("format", "")
    feedback = body.get("feedback", "").strip()
    if not format_type or not feedback:
        return jsonify({"error": "format_type and feedback required"}), 400
    _add_feedback(format_type, feedback)
    return jsonify({"status": "ok"})


@app.route("/api/feedback/<format_type>/<feedback_id>", methods=["DELETE"])
def delete_feedback(format_type, feedback_id):
    ok = _delete_feedback(format_type, feedback_id)
    if not ok:
        return jsonify({"error": "Feedback not found"}), 404
    return jsonify({"status": "ok"})


@app.route("/api/prompts/enrich", methods=["POST"])
def enrich_prompt():
    global FORMAT_LINKEDIN, FORMAT_INSTAGRAM, FORMAT_NEWSLETTER, FORMAT_TWITTER, FORMAT_VIDEO_SCRIPT

    body = request.json
    format_type = body.get("format_type", "")
    feedback_ids = body.get("feedback_ids", [])

    VALID_FORMATS = {"linkedin", "instagram", "newsletter", "twitter", "video_script"}
    if format_type not in VALID_FORMATS:
        return jsonify({"error": f"Invalid format: {format_type}"}), 400
    if not feedback_ids:
        return jsonify({"error": "No feedback selected"}), 400

    PROMPT_MAP = {
        "linkedin": FORMAT_LINKEDIN,
        "instagram": FORMAT_INSTAGRAM,
        "newsletter": FORMAT_NEWSLETTER,
        "twitter": FORMAT_TWITTER,
        "video_script": FORMAT_VIDEO_SCRIPT,
    }
    old_prompt = PROMPT_MAP[format_type]
    new_prompt = _enrich_prompt_with_feedback(format_type, feedback_ids)

    if new_prompt == old_prompt:
        return jsonify({"error": "Enrichment produced no changes"}), 400

    if format_type == "linkedin":
        FORMAT_LINKEDIN = new_prompt
    elif format_type == "instagram":
        FORMAT_INSTAGRAM = new_prompt
    elif format_type == "newsletter":
        FORMAT_NEWSLETTER = new_prompt
    elif format_type == "twitter":
        FORMAT_TWITTER = new_prompt
    elif format_type == "video_script":
        FORMAT_VIDEO_SCRIPT = new_prompt

    prompt_name = f"format_{format_type}"
    _log_prompt_version(prompt_name, new_prompt, trigger="enrichment")

    user_id = _get_user_id()
    db.mark_feedback_enriched(user_id, feedback_ids)

    selected = db.get_feedback_by_ids(user_id, feedback_ids)
    selected_texts = [e["feedback"] for e in selected]
    _log_pipeline("info", f"Prompt enriched: {format_type} (used {len(feedback_ids)} feedback comments)",
                  {"feedback_used": selected_texts})

    return jsonify({
        "status": "ok",
        "format_type": format_type,
        "old_prompt": old_prompt,
        "new_prompt": new_prompt,
        "feedback_used": len(feedback_ids),
    })


@app.route("/api/track-selections", methods=["POST"])
def track_selections():
    body = request.json
    articles = body.get("articles", [])
    if articles:
        _track_selection(articles)
    return jsonify({"status": "ok", "tracked": len(articles)})


@app.route("/api/smart-brief")
def smart_brief():
    user_id = _get_user_id()
    prefs = db.get_selection_prefs(user_id)
    total = prefs.get("total_selections", 0)
    confidence = round(min(total / 100, 1.0), 2)

    if total < 3:
        return jsonify({
            "confidence": confidence,
            "total_selections": total,
            "suggestions": [],
            "message": "Seleziona almeno 3 articoli per attivare i suggerimenti intelligenti.",
        })

    top_sources = sorted(prefs.get("source_counts", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    top_cats = sorted(prefs.get("category_counts", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    top_kws = sorted(prefs.get("keyword_counts", {}).items(), key=lambda x: x[1], reverse=True)[:10]

    pref_summary = f"""Analisi preferenze utente (basata su {total} selezioni):
Fonti preferite: {', '.join(f'{s[0]} ({s[1]}x)' for s in top_sources)}
Categorie preferite: {', '.join(f'{c[0]} ({c[1]}x)' for c in top_cats)}
Keywords ricorrenti: {', '.join(f'{k[0]} ({k[1]}x)' for k in top_kws)}
Confidence score: {confidence:.0%}"""

    try:
        prompt = f"""Sei un content strategist per un consulente AI italiano.
{pref_summary}

Basandoti su queste preferenze, suggerisci 3-5 idee CONCRETE di contenuto.
Per ogni suggerimento includi:
- Titolo proposto (accattivante, stile LinkedIn)
- Piattaforma ideale (linkedin, instagram, twitter, newsletter, video_script)
- Angolo/hook (perché funzionerebbe)
- Livello di urgenza (alta/media/bassa)

Rispondi in JSON array: [{{"title": "...", "platform": "...", "hook": "...", "urgency": "..."}}]
Solo JSON, niente altro."""
        result = _llm_call(
            [{"role": "user", "content": prompt}],
            model=MODEL_CHEAP, temperature=0.7,
        )
        suggestions = json.loads(result.strip().strip("```json").strip("```"))
        if not isinstance(suggestions, list):
            suggestions = []
    except Exception as e:
        _log_pipeline("warning", f"Smart brief generation failed: {e}")
        suggestions = []

    return jsonify({
        "confidence": confidence,
        "total_selections": total,
        "suggestions": suggestions,
        "top_sources": top_sources[:3],
        "top_categories": top_cats[:3],
        "top_keywords": [k[0] for k in top_kws[:8]],
    })


@app.route("/api/render-carousel", methods=["POST"])
def render_carousel_images():
    from carousel_renderer import render_carousel_async
    body = request.json
    text = body.get("text", "")
    palette_idx = body.get("palette", 0)
    if not text.strip():
        return jsonify({"error": "No carousel text provided"}), 400
    try:
        result = render_carousel_async(text, palette_idx=palette_idx)
        _log_pipeline("info", f"Rendered carousel: {len(result['slides'])} slides")
        return jsonify(result)
    except Exception as e:
        _log_pipeline("error", f"Carousel render error: {e}")
        return jsonify({"error": f"Render error: {e}"}), 500


# ---------------------------------------------------------------------------
# Routes — Monitor
# ---------------------------------------------------------------------------

@app.route("/api/monitor/prompts")
def get_prompt_log():
    user_id = _get_user_id()
    return jsonify(db.get_prompt_logs(user_id))


@app.route("/api/monitor/pipeline")
def get_pipeline_log():
    user_id = _get_user_id()
    level = request.args.get("level")
    logs = db.get_pipeline_logs(user_id, level=level, limit=500)
    return jsonify(logs)


@app.route("/api/monitor/preferences")
def get_preferences():
    user_id = _get_user_id()
    prefs = db.get_selection_prefs(user_id)
    source_top = sorted(prefs.get("source_counts", {}).items(), key=lambda x: x[1], reverse=True)[:10]
    category_top = sorted(prefs.get("category_counts", {}).items(), key=lambda x: x[1], reverse=True)[:10]
    keyword_top = sorted(prefs.get("keyword_counts", {}).items(), key=lambda x: x[1], reverse=True)[:20]
    return jsonify({
        "total_selections": prefs.get("total_selections", 0),
        "updated_at": prefs.get("updated_at"),
        "top_sources": source_top,
        "top_categories": category_top,
        "top_keywords": keyword_top,
    })


@app.route("/api/monitor/health")
def get_health():
    user_id = _get_user_id()
    pipeline = db.get_pipeline_logs(user_id, limit=500)
    feedback = db.get_all_feedback(user_id)
    prompts = db.get_prompt_logs(user_id)
    articles = db.get_articles(user_id)
    sessions = db.get_sessions(user_id)

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_errors = [e for e in pipeline if e.get("level") == "error" and e.get("created_at", "") > cutoff_24h]
    recent_warnings = [e for e in pipeline if e.get("level") == "warning" and e.get("created_at", "") > cutoff_24h]

    feed_urls = _get_all_feed_urls()
    feed_health = {}
    for feed_url in feed_urls:
        feed_events = [e for e in pipeline if (e.get("extra") or {}).get("feed") == feed_url]
        if feed_events:
            last = feed_events[-1]
            feed_health[feed_url] = {"status": last["level"], "message": last["message"], "last_seen": last["created_at"]}
        else:
            feed_health[feed_url] = {"status": "unknown", "message": "Never fetched", "last_seen": None}

    fb_counts = {k: len(v) for k, v in feedback.items()}
    prompt_versions = {}
    for e in prompts:
        prompt_versions[e["prompt_name"]] = e["version"]

    return jsonify({
        "total_articles": len(articles),
        "total_sessions": len(sessions),
        "errors_24h": len(recent_errors),
        "warnings_24h": len(recent_warnings),
        "total_pipeline_events": len(pipeline),
        "feed_health": feed_health,
        "feedback_counts": fb_counts,
        "prompt_versions": prompt_versions,
    })


# ---------------------------------------------------------------------------
# Routes — ntfy test
# ---------------------------------------------------------------------------

@app.route("/api/ntfy/test", methods=["POST"])
def test_ntfy():
    success = _send_ntfy(
        title="\U0001f9ea Test Content Dashboard",
        message="Le notifiche funzionano! Riceverai un avviso quando sarà ora di pubblicare.",
        tags="white_check_mark",
    )
    if success:
        return jsonify({"status": "ok", "message": "Test notification sent"})
    return jsonify({"error": "Failed to send notification"}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Verify Supabase is configured
    if not db.is_configured():
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        print("Run: python setup_db.py   (after setting up .env)")
        exit(1)

    # Snapshot prompts on startup
    try:
        _snapshot_all_prompts("init")
    except Exception as e:
        print(f"Warning: Could not snapshot prompts: {e}")

    # Start schedule checker background thread
    schedule_thread = threading.Thread(target=_check_schedules, daemon=True)
    schedule_thread.start()
    try:
        _log_pipeline("info", "App started — schedule checker running")
    except Exception:
        pass

    print("\n  Content AI Generator running on http://localhost:5001\n")
    app.run(debug=True, port=5001, use_reloader=False)
