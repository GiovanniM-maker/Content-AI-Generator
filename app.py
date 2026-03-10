#!/usr/bin/env python3
"""Content Creation Dashboard — Flask backend."""

import json
import os
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Response, stream_with_context

load_dotenv()

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
ARTICLES_FILE = DATA_DIR / "articles.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
FEEDBACK_FILE = DATA_DIR / "feedback.json"
PROMPT_LOG_FILE = DATA_DIR / "prompt_log.json"
PIPELINE_LOG_FILE = DATA_DIR / "pipeline_log.json"
SELECTION_PREFS_FILE = DATA_DIR / "selection_prefs.json"
FEEDS_CONFIG_FILE = DATA_DIR / "feeds_config.json"
SCHEDULE_FILE = DATA_DIR / "schedule.json"
WEEKLY_STATUS_FILE = DATA_DIR / "weekly_status.json"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_CHEAP = "google/gemini-2.0-flash-001"  # cheap model for scoring
MODEL_GENERATION = "anthropic/claude-sonnet-4-5"  # quality model for content

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
BEEHIIV_PUB_ID = os.getenv("BEEHIIV_PUB_ID", "")

# Fallback feeds if no config file
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

FETCH_WINDOW_DAYS = 5  # how many days back to look for articles

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _load_json_obj(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    return {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _llm_call(messages: list, model: str = MODEL_CHEAP, temperature: float = 0.3) -> str:
    """Call OpenRouter chat completion and return assistant content."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5001",
        "X-Title": "Content Dashboard",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
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
# Feeds config (categorized RSS feeds)
# ---------------------------------------------------------------------------

def _load_feeds_config() -> dict:
    """Load categorized RSS feed configuration."""
    config = _load_json_obj(FEEDS_CONFIG_FILE)
    if not config or "categories" not in config:
        return {"categories": {
            "Tool Pratici": [],
            "Casi Studio": [],
            "Automazioni": [],
            "News AI Italia": [],
        }}
    return config


def _save_feeds_config(config: dict):
    _save_json(FEEDS_CONFIG_FILE, config)


def _get_all_feed_urls() -> list[str]:
    """Get flat list of all feed URLs from config, or fallback to defaults."""
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

def _load_feedback() -> dict:
    """Load feedback memory. Structure: {format: [feedback_entries]}.
    Migrates legacy entries (missing 'id') by adding UUIDs."""
    try:
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            migrated = False
            for fmt, entries in data.items():
                for entry in entries:
                    if isinstance(entry, dict) and "id" not in entry:
                        entry["id"] = str(uuid.uuid4())
                        migrated = True
            if migrated:
                _save_feedback(data)
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    return {}


def _save_feedback(data: dict):
    FEEDBACK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_feedback_context(format_type: str) -> str:
    """Build a prompt section from accumulated feedback for a format."""
    fb = _load_feedback()
    entries = fb.get(format_type, [])
    if not entries:
        return ""
    recent = entries[-10:]
    lines = []
    for e in recent:
        lines.append(f"- {e['feedback']}")
    return "\n\nFEEDBACK ACCUMULATO (impara da queste indicazioni per migliorare lo stile):\n" + "\n".join(lines)


def _add_feedback(format_type: str, feedback: str):
    """Append a feedback entry for a format. Does NOT auto-modify prompts."""
    fb = _load_feedback()
    if format_type not in fb:
        fb[format_type] = []
    fb[format_type].append({
        "id": str(uuid.uuid4()),
        "feedback": feedback,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_feedback(fb)
    _log_pipeline("feedback", f"[{format_type}] {feedback}")


def _delete_feedback(format_type: str, feedback_id: str) -> bool:
    """Delete a specific feedback entry by ID."""
    fb = _load_feedback()
    entries = fb.get(format_type, [])
    new_entries = [e for e in entries if e.get("id") != feedback_id]
    if len(new_entries) == len(entries):
        return False
    fb[format_type] = new_entries
    _save_feedback(fb)
    _log_pipeline("info", f"Feedback deleted from {format_type}: {feedback_id}")
    return True


def _enrich_prompt_with_feedback(format_type: str, feedback_ids: list[str]) -> str:
    """Use LLM to rewrite a prompt incorporating selected feedback comments."""
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

    # Get selected feedback entries
    fb = _load_feedback()
    entries = fb.get(format_type, [])
    selected = [e for e in entries if e.get("id") in feedback_ids]
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
            model=MODEL_GENERATION,
            temperature=0.3,
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


def _load_prefs() -> dict:
    try:
        data = json.loads(SELECTION_PREFS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    return {
        "source_counts": {},
        "category_counts": {},
        "keyword_counts": {},
        "total_selections": 0,
        "updated_at": None,
    }


def _save_prefs(data: dict):
    SELECTION_PREFS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _extract_keywords(title: str) -> list[str]:
    import re
    words = re.findall(r"[a-zA-Z]{3,}", title.lower())
    return [w for w in words if w not in STOP_WORDS]


def _track_selection(articles: list[dict]):
    prefs = _load_prefs()
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
    prefs["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_prefs(prefs)
    _log_pipeline("info", f"Selection preferences updated: {len(articles)} articles tracked")


def _calc_preference_bonus(article: dict) -> float:
    prefs = _load_prefs()
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

def _load_prompt_log() -> list:
    try:
        return json.loads(PROMPT_LOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_prompt_log(data: list):
    PROMPT_LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_prompt_version(prompt_name: str, content: str, trigger: str = "init"):
    log = _load_prompt_log()
    prev = None
    for entry in reversed(log):
        if entry["prompt_name"] == prompt_name:
            prev = entry
            break
    if prev and prev["content"] == content:
        return
    version = sum(1 for e in log if e["prompt_name"] == prompt_name) + 1
    log.append({
        "prompt_name": prompt_name,
        "version": version,
        "content": content,
        "trigger": trigger,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_prompt_log(log)


def _load_pipeline_log() -> list:
    try:
        return json.loads(PIPELINE_LOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_pipeline_log(data: list):
    PIPELINE_LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_pipeline(level: str, message: str, extra: dict | None = None):
    log = _load_pipeline_log()
    entry = {
        "level": level,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        entry["extra"] = extra
    log.append(entry)
    if len(log) > 500:
        log = log[-500:]
    _save_pipeline_log(log)


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
    """Send a push notification via ntfy.sh using JSON API (handles emoji/UTF-8)."""
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
        resp = requests.post(
            "https://ntfy.sh/",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        _log_pipeline("info", f"ntfy notification sent: {title}")
        return True
    except Exception as e:
        _log_pipeline("error", f"ntfy send error: {e}")
        return False


# ---------------------------------------------------------------------------
# Scheduling system
# ---------------------------------------------------------------------------

def _load_schedule() -> list:
    return _load_json(SCHEDULE_FILE)


def _save_schedule(data: list):
    _save_json(SCHEDULE_FILE, data)


def _check_schedules():
    """Background task: check for due scheduled items and send notifications."""
    while True:
        try:
            schedule = _load_schedule()
            now = datetime.now(timezone.utc)
            changed = False

            for item in schedule:
                if item.get("status") != "pending":
                    continue
                scheduled_at = item.get("scheduled_at", "")
                if not scheduled_at:
                    continue
                try:
                    sched_dt = datetime.fromisoformat(scheduled_at)
                    if sched_dt.tzinfo is None:
                        sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue

                if now >= sched_dt:
                    # Time to publish — send notification
                    platform = item.get("platform", "content")
                    title_text = item.get("title", "Contenuto programmato")
                    emoji_map = {
                        "linkedin": "💼",
                        "instagram": "📸",
                        "newsletter": "📧",
                    }
                    emoji = emoji_map.get(platform, "📢")
                    _send_ntfy(
                        title=f"{emoji} Pubblica {platform.upper()}",
                        message=f"{title_text}\n\nÈ ora di pubblicare questo contenuto!",
                        tags=f"{platform},bell",
                    )
                    item["status"] = "notified"
                    item["notified_at"] = now.isoformat()
                    changed = True
                    _log_pipeline("info", f"Schedule notification sent for {platform}: {title_text}")

            if changed:
                _save_schedule(schedule)
        except Exception as e:
            _log_pipeline("error", f"Schedule checker error: {e}")

        time.sleep(30)  # check every 30 seconds


# ---------------------------------------------------------------------------
# Weekly status tracking
# ---------------------------------------------------------------------------

def _get_week_key(dt: datetime | None = None) -> str:
    """Get ISO week key like '2026-W10'."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


def _load_weekly_status() -> dict:
    return _load_json_obj(WEEKLY_STATUS_FILE)


def _save_weekly_status(data: dict):
    _save_json(WEEKLY_STATUS_FILE, data)


def _update_weekly_status(platform: str, action: str = "generated"):
    """Track content generation/approval/scheduling per platform per week."""
    status = _load_weekly_status()
    week = _get_week_key()
    if "weeks" not in status:
        status["weeks"] = {}
    if week not in status["weeks"]:
        status["weeks"][week] = {}
    wk = status["weeks"][week]
    if platform not in wk:
        wk[platform] = {"generated": 0, "approved": 0, "scheduled": 0, "published": 0}
    if action in wk[platform]:
        wk[platform][action] += 1
    _save_weekly_status(status)


def _get_current_week_status() -> dict:
    """Get status summary for the current week."""
    status = _load_weekly_status()
    week = _get_week_key()
    wk = status.get("weeks", {}).get(week, {})
    return {
        "week": week,
        "platforms": wk,
    }


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — Feeds Config API
# ---------------------------------------------------------------------------

@app.route("/api/feeds/config", methods=["GET"])
def get_feeds_config():
    """Return current RSS feeds configuration."""
    return jsonify(_load_feeds_config())


@app.route("/api/feeds/config", methods=["POST"])
def save_feeds_config():
    """Save entire feeds configuration."""
    body = request.json
    if not body or "categories" not in body:
        return jsonify({"error": "Invalid config format"}), 400
    _save_feeds_config(body)
    _log_pipeline("info", "Feeds configuration updated")
    return jsonify({"status": "ok"})


@app.route("/api/feeds/config/add", methods=["POST"])
def add_feed():
    """Add a single feed to a category."""
    body = request.json
    category = body.get("category", "").strip()
    url = body.get("url", "").strip()
    name = body.get("name", "").strip()

    if not category or not url:
        return jsonify({"error": "category and url required"}), 400

    config = _load_feeds_config()
    if category not in config["categories"]:
        config["categories"][category] = []

    # Check duplicate
    existing_urls = [f["url"] for f in config["categories"][category]]
    if url in existing_urls:
        return jsonify({"error": "Feed URL already exists in this category"}), 409

    config["categories"][category].append({
        "url": url,
        "name": name or url,
    })
    _save_feeds_config(config)
    _log_pipeline("info", f"Feed added: {url} → {category}")
    return jsonify({"status": "ok", "config": config})


@app.route("/api/feeds/config/remove", methods=["POST"])
def remove_feed():
    """Remove a single feed from a category."""
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
    """Add a new empty category."""
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
    """Remove an entire category and its feeds."""
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
    """Fetch RSS feeds and score articles via LLM. Returns immediately, progress via SSE."""
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
    """SSE stream of fetch progress messages."""
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
    """Core fetch + score logic. Uses feeds from config."""
    import re

    existing = _load_json(ARTICLES_FILE)
    seen_urls = {a["url"] for a in existing}
    cutoff = datetime.now(timezone.utc) - timedelta(days=FETCH_WINDOW_DAYS)
    new_articles = []

    # Get feed URLs from config (with category info)
    config = _load_feeds_config()
    feed_items = []
    for cat, feeds in config.get("categories", {}).items():
        for feed in feeds:
            feed_items.append({"url": feed["url"], "name": feed.get("name", ""), "category": cat})

    # Fallback to defaults
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
                _fetch_progress.append(f"  ⚠ HTTP {status} — skipping this feed")
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
            _fetch_progress.append(f"  → {count} new articles from {source}")
            if count > 0:
                _log_pipeline("info", f"Fetched {count} articles from {source}", {"feed": feed_url})
        except Exception as e:
            _fetch_progress.append(f"  ⚠ Error fetching {feed_url}: {e}")
            _log_pipeline("error", f"RSS fetch error: {e}", {"feed": feed_url})

    _fetch_progress.append(f"\nTotal new articles to score: {len(new_articles)}")

    # Score in batches of 5
    scored = []
    for i in range(0, len(new_articles), 5):
        batch = new_articles[i:i+5]
        _fetch_progress.append(f"Scoring articles {i+1}-{i+len(batch)} ...")
        try:
            articles_text = ""
            for idx, art in enumerate(batch):
                articles_text += f"\n---\nARTICLE {idx+1}:\nTitle: {art['title']}\nDescription: {art['description']}\n"

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
            _fetch_progress.append(f"  ⚠ Scoring error: {e}")
            _log_pipeline("error", f"LLM scoring error: {e}", {"batch_start": i})
            for art in batch:
                art["category"] = art.get("feed_category", "News AI Italia")
                art["score"] = 5
                art["summary"] = art["title"]
                art["scored_at"] = datetime.now(timezone.utc).isoformat()
                scored.append(art)

    # Apply preference boost
    prefs = _load_prefs()
    if prefs["total_selections"] > 0:
        _fetch_progress.append(f"\nApplying preference boost (based on {prefs['total_selections']} past selections)...")
        boosted_count = 0
        for art in scored:
            bonus = _calc_preference_bonus(art)
            if bonus > 0:
                art["base_score"] = art["score"]
                art["boost"] = bonus
                art["score"] = min(10, round(art["score"] + bonus))
                boosted_count += 1
        _fetch_progress.append(f"  → {boosted_count} articles boosted")

    # Merge and save
    all_articles = existing + scored
    _save_json(ARTICLES_FILE, all_articles)
    _fetch_progress.append(f"\n✓ Done! {len(scored)} articles scored and saved.")
    _log_pipeline("info", f"Fetch complete: {len(scored)} articles scored and saved")

    # Send ntfy notification
    if scored:
        _send_ntfy(
            title="📰 Feed aggiornato",
            message=f"{len(scored)} nuovi articoli analizzati e pronti per la selezione.",
            url="http://localhost:5001",
            tags="newspaper",
        )


@app.route("/api/articles")
def get_articles():
    """Return scored articles, optionally filtered by min_score."""
    articles = _load_json(ARTICLES_FILE)
    min_score = request.args.get("min_score", 0, type=int)
    if min_score:
        articles = [a for a in articles if a.get("score", 0) >= min_score]
    articles.sort(key=lambda a: a.get("score", 0), reverse=True)
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
    "",  # default
    "\nANGOLO SPECIFICO: Focalizzati sull'aspetto PRATICO e operativo. Come si implementa concretamente? Che workflow o tool servono? Dai step actionable.",
    "\nANGOLO SPECIFICO: Focalizzati sull'aspetto STRATEGICO e di business impact. Perché un imprenditore dovrebbe interessarsi? Quali numeri contano? ROI, risparmio tempo, vantaggio competitivo.",
    "\nANGOLO SPECIFICO: Focalizzati sugli ERRORI COMUNI e le trappole. Cosa sbagliano tutti? Qual è il consiglio controintuitivo? Tono myth-busting, sfida le convinzioni del lettore.",
]


# ---------------------------------------------------------------------------
# Web Search (Serper API)
# ---------------------------------------------------------------------------

def _serper_search(query: str, num_results: int = 10) -> list[dict]:
    """Search the web using Serper.dev API. Returns list of result dicts."""
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
    """Search the web using Serper API."""
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
    """Score web search results using AI (like RSS article scoring)."""
    body = request.json
    results = body.get("results", [])
    if not results:
        return jsonify({"error": "No results to score"}), 400

    scored = []
    for item in results:
        # Create a pseudo-article dict compatible with the article scoring
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
        # Quick LLM scoring
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
                model=MODEL_CHEAP,
                temperature=0.1,
            )
            data = json.loads(result.strip().strip("```json").strip("```"))
            article["score"] = data.get("score", 5)
            article["score_reason"] = data.get("reason", "")
        except Exception:
            article["score"] = 5
            article["score_reason"] = "Scoring failed"
        scored.append(article)

    # Sort by score descending
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify({"articles": scored})


# ---------------------------------------------------------------------------
# Routes — Content Generation
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
def generate_content():
    """Generate content for a single article (LinkedIn or IG)."""
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

    if feedback:
        _add_feedback(format_type, feedback)

    fmt = FORMAT_MAP[format_type]
    if format_type == "instagram" and 0 < variant < len(IG_VARIANT_ANGLES):
        fmt += IG_VARIANT_ANGLES[variant]

    regen_instruction = ""
    if feedback:
        regen_instruction = f"\n\nISTRUZIONE DI RISCRITTURA (priorità alta, segui questa indicazione):\n{feedback}"

    opinion_section = ""
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
            model=MODEL_GENERATION,
            temperature=0.7,
        )
        _log_pipeline("info", f"Generated {format_type} content", {"article": article.get("title", "")})
        # Track weekly status
        _update_weekly_status(format_type, "generated")
        return jsonify({"content": result, "format": format_type})
    except Exception as e:
        _log_pipeline("error", f"LLM generation error ({format_type}): {e}")
        return jsonify({"error": f"LLM error: {e}"}), 500


@app.route("/api/generate-newsletter", methods=["POST"])
def generate_newsletter():
    """Generate aggregated weekly newsletter from multiple articles + opinions."""
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
            model=MODEL_GENERATION,
            temperature=0.7,
        )
        _log_pipeline("info", "Generated newsletter")
        _update_weekly_status("newsletter", "generated")
        return jsonify({"content": result, "format": "newsletter"})
    except Exception as e:
        _log_pipeline("error", f"LLM newsletter error: {e}")
        return jsonify({"error": f"LLM error: {e}"}), 500


@app.route("/api/newsletter/html", methods=["POST"])
def newsletter_to_html():
    """Convert newsletter plain text to styled HTML for Beehiiv email."""
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
            model=MODEL_GENERATION,
            temperature=0.3,
        )
        # Clean up — remove markdown code fences if present
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
    """Return all scheduled items."""
    schedule = _load_schedule()
    schedule.sort(key=lambda s: s.get("scheduled_at", ""))
    return jsonify(schedule)


@app.route("/api/schedule", methods=["POST"])
def create_schedule():
    """Schedule a content piece for publishing."""
    body = request.json
    item = {
        "id": str(uuid.uuid4()),
        "platform": body.get("platform", ""),
        "title": body.get("title", ""),
        "content_preview": body.get("content_preview", "")[:200],
        "content_key": body.get("content_key", ""),
        "session_id": body.get("session_id", ""),
        "scheduled_at": body.get("scheduled_at", ""),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notified_at": None,
    }

    schedule = _load_schedule()
    schedule.append(item)
    _save_schedule(schedule)

    # Track in weekly status
    _update_weekly_status(item["platform"], "scheduled")

    _log_pipeline("info", f"Content scheduled: {item['platform']} at {item['scheduled_at']}")
    return jsonify(item)


@app.route("/api/schedule/bulk", methods=["POST"])
def create_schedule_bulk():
    """Schedule multiple content pieces at once."""
    body = request.json
    items_data = body.get("items", [])
    scheduled_at = body.get("scheduled_at", "")

    if not items_data or not scheduled_at:
        return jsonify({"error": "items and scheduled_at required"}), 400

    schedule = _load_schedule()
    created = []

    for item_data in items_data:
        item = {
            "id": str(uuid.uuid4()),
            "platform": item_data.get("platform", ""),
            "title": item_data.get("title", ""),
            "content_preview": item_data.get("content_preview", "")[:200],
            "content_key": item_data.get("content_key", ""),
            "session_id": item_data.get("session_id", ""),
            "scheduled_at": scheduled_at,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "notified_at": None,
        }
        schedule.append(item)
        created.append(item)
        _update_weekly_status(item["platform"], "scheduled")

    _save_schedule(schedule)
    _log_pipeline("info", f"Bulk scheduled {len(created)} items at {scheduled_at}")
    return jsonify({"status": "ok", "count": len(created), "items": created})


@app.route("/api/schedule/<item_id>", methods=["DELETE"])
def delete_schedule(item_id):
    """Remove a scheduled item."""
    schedule = _load_schedule()
    schedule = [s for s in schedule if s.get("id") != item_id]
    _save_schedule(schedule)
    return jsonify({"status": "ok"})


@app.route("/api/schedule/<item_id>/publish", methods=["POST"])
def mark_published(item_id):
    """Mark a scheduled item as published."""
    schedule = _load_schedule()
    for item in schedule:
        if item.get("id") == item_id:
            item["status"] = "published"
            item["published_at"] = datetime.now(timezone.utc).isoformat()
            platform = item.get("platform", "")
            _update_weekly_status(platform, "published")
            break
    _save_schedule(schedule)
    return jsonify({"status": "ok"})


@app.route("/api/schedule/<item_id>/content")
def get_schedule_content(item_id):
    """Return full content for a scheduled item by looking up its session."""
    schedule = _load_schedule()
    item = next((s for s in schedule if s.get("id") == item_id), None)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    session_id = item.get("session_id", "")
    content_key = item.get("content_key", "")
    full_content = ""
    if session_id and content_key:
        sessions = _load_json(SESSIONS_FILE)
        session = next((s for s in sessions if s.get("id") == session_id), None)
        if session:
            full_content = session.get("content", {}).get(content_key, "")
    # Fallback to content_preview if session lookup fails
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
    """Return weekly content status summary."""
    return jsonify(_get_current_week_status())


# ---------------------------------------------------------------------------
# Routes — Approve Content
# ---------------------------------------------------------------------------

@app.route("/api/approve", methods=["POST"])
def approve_content():
    """Track content approval in weekly status."""
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
    sessions = _load_json(SESSIONS_FILE)
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return jsonify(sessions)


@app.route("/api/sessions", methods=["POST"])
def save_session():
    body = request.json
    sessions = _load_json(SESSIONS_FILE)
    session = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "article": body.get("article", {}),
        "topics": body.get("topics", []),
        "opinion": body.get("opinion", ""),
        "content": body.get("content", {}),
        "carousel_images": body.get("carousel_images", {}),
        "platforms": body.get("platforms", []),
    }
    sessions.append(session)
    _save_json(SESSIONS_FILE, sessions)
    return jsonify(session)


@app.route("/api/sessions/<session_id>", methods=["PUT"])
def update_session(session_id):
    body = request.json
    sessions = _load_json(SESSIONS_FILE)
    for s in sessions:
        if s["id"] == session_id:
            s["content"] = body.get("content", s.get("content", {}))
            if "carousel_images" in body:
                s["carousel_images"] = body["carousel_images"]
            _save_json(SESSIONS_FILE, sessions)
            return jsonify(s)
    return jsonify({"error": "Session not found"}), 404


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    sessions = _load_json(SESSIONS_FILE)
    before = len(sessions)
    sessions = [s for s in sessions if s.get("id") != session_id]
    if len(sessions) == before:
        return jsonify({"error": "Session not found"}), 404
    _save_json(SESSIONS_FILE, sessions)
    _log_pipeline("info", f"Deleted session {session_id}")
    return jsonify({"ok": True})


@app.route("/api/feedback")
def get_feedback():
    return jsonify(_load_feedback())


@app.route("/api/feedback", methods=["POST"])
def add_feedback_direct():
    """Add a feedback comment directly (not via regeneration)."""
    body = request.json
    format_type = body.get("format_type") or body.get("format", "")
    feedback = body.get("feedback", "").strip()
    if not format_type or not feedback:
        return jsonify({"error": "format_type and feedback required"}), 400
    _add_feedback(format_type, feedback)
    return jsonify({"status": "ok"})


@app.route("/api/feedback/<format_type>/<feedback_id>", methods=["DELETE"])
def delete_feedback(format_type, feedback_id):
    """Delete a specific feedback comment."""
    ok = _delete_feedback(format_type, feedback_id)
    if not ok:
        return jsonify({"error": "Feedback not found"}), 404
    return jsonify({"status": "ok"})


@app.route("/api/prompts/enrich", methods=["POST"])
def enrich_prompt():
    """Use LLM to rewrite a prompt incorporating selected feedback."""
    global FORMAT_LINKEDIN, FORMAT_INSTAGRAM, FORMAT_NEWSLETTER, FORMAT_TWITTER, FORMAT_VIDEO_SCRIPT

    body = request.json
    format_type = body.get("format_type", "")
    feedback_ids = body.get("feedback_ids", [])

    VALID_FORMATS = {"linkedin", "instagram", "newsletter", "twitter", "video_script"}
    if format_type not in VALID_FORMATS:
        return jsonify({"error": f"Invalid format: {format_type}"}), 400
    if not feedback_ids:
        return jsonify({"error": "No feedback selected"}), 400

    # Get current prompt BEFORE enrichment
    PROMPT_MAP = {
        "linkedin": FORMAT_LINKEDIN,
        "instagram": FORMAT_INSTAGRAM,
        "newsletter": FORMAT_NEWSLETTER,
        "twitter": FORMAT_TWITTER,
        "video_script": FORMAT_VIDEO_SCRIPT,
    }
    old_prompt = PROMPT_MAP[format_type]

    # Enrich using LLM
    new_prompt = _enrich_prompt_with_feedback(format_type, feedback_ids)

    if new_prompt == old_prompt:
        return jsonify({"error": "Enrichment produced no changes"}), 400

    # Update the global FORMAT variable
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

    # Log the new prompt version
    prompt_name = f"format_{format_type}"
    _log_prompt_version(prompt_name, new_prompt, trigger="enrichment")

    # Mark selected feedback entries as "used for enrichment"
    fb = _load_feedback()
    entries = fb.get(format_type, [])
    selected_texts = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for e in entries:
        if e.get("id") in feedback_ids:
            selected_texts.append(e["feedback"])
            e["enriched_at"] = now_iso
    _save_feedback(fb)

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
    """Generate AI-powered content suggestions based on user preferences."""
    prefs = _load_prefs()
    total = prefs.get("total_selections", 0)
    confidence = round(min(total / 100, 1.0), 2)

    if total < 3:
        return jsonify({
            "confidence": confidence,
            "total_selections": total,
            "suggestions": [],
            "message": "Seleziona almeno 3 articoli per attivare i suggerimenti intelligenti.",
        })

    # Build a preference summary
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
            model=MODEL_CHEAP,
            temperature=0.7,
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
    return jsonify(_load_prompt_log())


@app.route("/api/monitor/pipeline")
def get_pipeline_log():
    log = _load_pipeline_log()
    level = request.args.get("level")
    if level:
        log = [e for e in log if e["level"] == level]
    log.reverse()
    return jsonify(log)


@app.route("/api/monitor/preferences")
def get_preferences():
    prefs = _load_prefs()
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
    pipeline = _load_pipeline_log()
    feedback = _load_feedback()
    prompts = _load_prompt_log()
    articles = _load_json(ARTICLES_FILE)
    sessions = _load_json(SESSIONS_FILE)

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_errors = [e for e in pipeline if e["level"] == "error" and e["created_at"] > cutoff_24h]
    recent_warnings = [e for e in pipeline if e["level"] == "warning" and e["created_at"] > cutoff_24h]

    feed_urls = _get_all_feed_urls()
    feed_health = {}
    for feed_url in feed_urls:
        feed_events = [e for e in pipeline if e.get("extra", {}).get("feed") == feed_url]
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
    """Send a test ntfy notification."""
    success = _send_ntfy(
        title="🧪 Test Content Dashboard",
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
    DATA_DIR.mkdir(exist_ok=True)
    for f in (ARTICLES_FILE, SESSIONS_FILE, SCHEDULE_FILE):
        if not f.exists():
            _save_json(f, [])
    if not FEEDBACK_FILE.exists():
        _save_feedback({})
    if not PROMPT_LOG_FILE.exists():
        _save_prompt_log([])
    if not PIPELINE_LOG_FILE.exists():
        _save_pipeline_log([])
    if not SELECTION_PREFS_FILE.exists():
        _save_prefs(_load_prefs())
    if not WEEKLY_STATUS_FILE.exists():
        _save_weekly_status({"weeks": {}})

    # Snapshot prompts on startup
    _snapshot_all_prompts("init")

    # Start schedule checker background thread
    schedule_thread = threading.Thread(target=_check_schedules, daemon=True)
    schedule_thread.start()
    _log_pipeline("info", "Schedule checker started")

    # Open browser after short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:5001")

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(debug=True, port=5001, use_reloader=False)
