#!/usr/bin/env python3
"""Content Creation Dashboard — Flask backend (Supabase edition)."""

import base64
import ipaddress
import json
import os
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Response, stream_with_context, g, make_response

import db
import auth
import payments
import security

load_dotenv()

app = Flask(__name__)
_flask_secret = os.getenv("FLASK_SECRET_KEY")
if not _flask_secret and os.getenv("FLASK_ENV") == "production":
    raise ValueError("FLASK_SECRET_KEY must be set in production environment")
app.secret_key = _flask_secret or os.urandom(32).hex()

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
    BLOCKS unauthenticated requests to /api/ endpoints (security).
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

    # Enforce auth on all /api/ routes (except healthz)
    if path.startswith("/api/") and path != "/api/healthz":
        if not g.user_id:
            return jsonify({"error": "Authentication required"}), 401

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_CHEAP = "google/gemini-2.0-flash-001"           # Cheapest: scoring, parsing, quick tasks ($0.10/M in, $0.40/M out)
MODEL_SMART = "google/gemini-3.1-pro-preview"          # Smart+affordable: generation, content ($2/M in, $12/M out)
MODEL_FAST  = "google/gemini-2.5-flash"                # Fast+cheap: template chat, iterative HTML ($0.15/M in, $0.60/M out)
MODEL_PREMIUM = "anthropic/claude-sonnet-4-5"          # Premium fallback only ($3/M in, $15/M out)
MODEL_IMAGE = "black-forest-labs/flux.2-pro"           # Image generation: text→image (~$0.03/image, high quality)

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# Admin email — full access, bypasses all plan limits
ADMIN_EMAIL = "giovanni.mavilla.grz@gmail.com"


def _is_admin() -> bool:
    """Check if current user is the admin."""
    return getattr(g, "user_email", "") == ADMIN_EMAIL
BEEHIIV_PUB_ID = os.getenv("BEEHIIV_PUB_ID", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://content-ai-generator-1.onrender.com")

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

# ---------------------------------------------------------------------------
# Feed Catalog — curated RSS feeds users can browse and import
# ---------------------------------------------------------------------------

FEED_CATALOG = {
    "AI Research": [
        {"url": "https://openai.com/blog/rss.xml", "name": "OpenAI Blog"},
        {"url": "https://www.anthropic.com/rss.xml", "name": "Anthropic Blog"},
        {"url": "https://blog.google/technology/ai/rss/", "name": "Google AI Blog"},
        {"url": "https://deepmind.google/blog/rss.xml", "name": "Google DeepMind"},
        {"url": "https://ai.meta.com/blog/rss/", "name": "Meta AI Blog"},
        {"url": "https://huggingface.co/blog/feed.xml", "name": "Hugging Face Blog"},
        {"url": "https://news.mit.edu/topic/artificial-intelligence2/feed", "name": "MIT AI News"},
        {"url": "https://hai.stanford.edu/news/rss.xml", "name": "Stanford HAI"},
        {"url": "https://arxiv.org/rss/cs.AI", "name": "arXiv CS.AI"},
        {"url": "https://arxiv.org/rss/cs.CL", "name": "arXiv NLP (cs.CL)"},
        {"url": "https://machinelearningmastery.com/feed/", "name": "Machine Learning Mastery"},
        {"url": "https://distill.pub/rss.xml", "name": "Distill.pub"},
        {"url": "https://bair.berkeley.edu/blog/feed.xml", "name": "Berkeley AI Research"},
        {"url": "https://www.microsoft.com/en-us/research/feed/", "name": "Microsoft Research"},
        {"url": "https://research.nvidia.com/rss.xml", "name": "NVIDIA Research"},
    ],
    "AI News & Media": [
        {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "name": "TechCrunch AI"},
        {"url": "https://venturebeat.com/ai/feed/", "name": "VentureBeat AI"},
        {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "name": "The Verge AI"},
        {"url": "https://www.wired.com/feed/tag/ai/latest/rss", "name": "WIRED AI"},
        {"url": "https://www.therundown.ai/rss", "name": "The Rundown AI"},
        {"url": "https://tldr.tech/ai/rss", "name": "TLDR AI"},
        {"url": "https://jack-clark.net/feed/", "name": "Import AI (Jack Clark)"},
        {"url": "https://www.deeplearning.ai/the-batch/feed/", "name": "The Batch (Andrew Ng)"},
        {"url": "https://arstechnica.com/tag/artificial-intelligence/feed/", "name": "Ars Technica AI"},
        {"url": "https://www.technologyreview.com/feed/", "name": "MIT Technology Review"},
        {"url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "name": "IEEE Spectrum AI"},
        {"url": "https://www.marktechpost.com/feed/", "name": "MarkTechPost"},
        {"url": "https://syncedreview.com/feed/", "name": "Synced Review"},
    ],
    "AI Tools & Automazioni": [
        {"url": "https://blog.langchain.dev/rss/", "name": "LangChain Blog"},
        {"url": "https://zapier.com/blog/feed/", "name": "Zapier Blog"},
        {"url": "https://www.make.com/en/blog/rss.xml", "name": "Make (Integromat) Blog"},
        {"url": "https://n8n.io/blog/rss.xml", "name": "n8n Blog"},
        {"url": "https://www.notion.so/blog/rss.xml", "name": "Notion Blog"},
        {"url": "https://www.pinecone.io/blog/rss.xml", "name": "Pinecone Blog"},
        {"url": "https://unwindai.substack.com/feed", "name": "Unwind AI"},
        {"url": "https://bensbites.beehiiv.com/feed", "name": "Ben's Bites"},
        {"url": "https://www.superhuman.ai/feed", "name": "Superhuman AI"},
        {"url": "https://lmsys.org/blog/feed.xml", "name": "LMSYS (Chatbot Arena)"},
    ],
    "Marketing Digitale": [
        {"url": "https://blog.hubspot.com/marketing/rss.xml", "name": "HubSpot Marketing"},
        {"url": "https://contentmarketinginstitute.com/feed/", "name": "Content Marketing Institute"},
        {"url": "https://www.searchenginejournal.com/feed/", "name": "Search Engine Journal"},
        {"url": "https://moz.com/blog/feed", "name": "Moz Blog"},
        {"url": "https://neilpatel.com/blog/feed/", "name": "Neil Patel"},
        {"url": "https://www.socialmediaexaminer.com/feed/", "name": "Social Media Examiner"},
        {"url": "https://copyblogger.com/feed/", "name": "Copyblogger"},
        {"url": "https://www.convinceandconvert.com/feed/", "name": "Convince & Convert"},
        {"url": "https://sproutsocial.com/insights/feed/", "name": "Sprout Social Insights"},
        {"url": "https://buffer.com/resources/feed/", "name": "Buffer Blog"},
        {"url": "https://blog.hootsuite.com/feed/", "name": "Hootsuite Blog"},
    ],
    "Business & Startup": [
        {"url": "https://hbr.org/feed", "name": "Harvard Business Review"},
        {"url": "https://www.inc.com/rss", "name": "Inc. Magazine"},
        {"url": "https://www.entrepreneur.com/latest.rss", "name": "Entrepreneur"},
        {"url": "https://review.firstround.com/feed.xml", "name": "First Round Review"},
        {"url": "https://a16z.com/feed/", "name": "Andreessen Horowitz (a16z)"},
        {"url": "https://news.ycombinator.com/rss", "name": "Hacker News"},
        {"url": "https://www.fastcompany.com/technology/rss", "name": "Fast Company Tech"},
        {"url": "https://seths.blog/feed/", "name": "Seth Godin Blog"},
        {"url": "https://www.groovehq.com/blog/feed", "name": "Groove Blog"},
        {"url": "https://bothsidesofthetable.com/feed", "name": "Both Sides of the Table"},
    ],
    "E-commerce": [
        {"url": "https://www.shopify.com/blog/feed", "name": "Shopify Blog"},
        {"url": "https://www.practicalecommerce.com/feed", "name": "Practical Ecommerce"},
        {"url": "https://www.bigcommerce.com/blog/feed/", "name": "BigCommerce Blog"},
        {"url": "https://www.oberlo.com/blog/feed", "name": "Oberlo Blog"},
        {"url": "https://ecommercenews.eu/feed/", "name": "Ecommerce News EU"},
        {"url": "https://www.digitalcommerce360.com/feed/", "name": "Digital Commerce 360"},
    ],
    "Finanza & Fintech": [
        {"url": "https://www.finextra.com/rss/headlines.aspx", "name": "Finextra"},
        {"url": "https://thefintechtimes.com/feed/", "name": "The Fintech Times"},
        {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "name": "CoinDesk"},
        {"url": "https://cointelegraph.com/rss", "name": "CoinTelegraph"},
        {"url": "https://www.pymnts.com/feed/", "name": "PYMNTS"},
        {"url": "https://techcrunch.com/category/fintech/feed/", "name": "TechCrunch Fintech"},
    ],
    "SaaS & Prodotto": [
        {"url": "https://www.saastr.com/feed/", "name": "SaaStr"},
        {"url": "https://www.producthunt.com/feed", "name": "Product Hunt"},
        {"url": "https://www.lennysnewsletter.com/feed", "name": "Lenny's Newsletter"},
        {"url": "https://www.intercom.com/blog/feed/", "name": "Intercom Blog"},
        {"url": "https://openviewpartners.com/blog/feed/", "name": "OpenView Blog"},
        {"url": "https://www.heavybit.com/library/feed", "name": "Heavybit Blog"},
        {"url": "https://tomtunguz.com/feed/", "name": "Tom Tunguz Blog"},
        {"url": "https://www.custify.com/blog/feed/", "name": "Custify Blog"},
    ],
    "Tech Italia": [
        {"url": "https://www.wired.it/feed/rss", "name": "Wired Italia"},
        {"url": "https://startupitalia.eu/feed", "name": "StartupItalia"},
        {"url": "https://www.italian.tech/rss", "name": "Italian Tech (Repubblica)"},
        {"url": "https://www.agendadigitale.eu/feed/", "name": "Agenda Digitale"},
        {"url": "https://www.ai4business.it/feed/", "name": "AI4Business"},
        {"url": "https://www.hwupgrade.it/rss/news.xml", "name": "HWUpgrade"},
        {"url": "https://www.punto-informatico.it/feed/", "name": "Punto Informatico"},
        {"url": "https://www.tomshw.it/feed", "name": "Tom's Hardware Italia"},
    ],
    "Tech Generale": [
        {"url": "https://techcrunch.com/feed/", "name": "TechCrunch"},
        {"url": "https://arstechnica.com/feed/", "name": "Ars Technica"},
        {"url": "https://thenextweb.com/feed/", "name": "The Next Web"},
        {"url": "https://www.theverge.com/rss/index.xml", "name": "The Verge"},
        {"url": "https://www.wired.com/feed/rss", "name": "WIRED"},
        {"url": "https://feeds.feedburner.com/TechCrunch/", "name": "TechCrunch (Feedburner)"},
        {"url": "https://www.zdnet.com/news/rss.xml", "name": "ZDNet"},
        {"url": "https://www.cnet.com/rss/news/", "name": "CNET News"},
    ],
}

FETCH_WINDOW_DAYS = 5


# ---------------------------------------------------------------------------
# User context helper
# ---------------------------------------------------------------------------

def _get_user_id() -> str:
    """Get current user ID from request context.
    Raises 401 if not authenticated.
    """
    uid = getattr(g, "user_id", None)
    if not uid:
        from flask import abort
        abort(401, description="Authentication required")
    return uid


# ---------------------------------------------------------------------------
# LLM / utility helpers
# ---------------------------------------------------------------------------

def _sanitize_user_input(text: str, max_length: int = 5000) -> str:
    """Sanitize user-provided text before injecting into LLM prompts.

    Prevents prompt injection by:
    - Truncating to max_length
    - Stripping control characters
    - Escaping patterns that look like role/instruction markers
    """
    if not text:
        return ""
    # Truncate
    text = text[:max_length]
    # Strip null bytes and other control chars (keep newlines/tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Neutralize patterns that look like LLM role markers or system instructions
    # These could trick the model into switching roles
    text = re.sub(r'(?i)(^|\n)\s*(system|assistant|user)\s*:', r'\1\2 -', text)
    text = re.sub(r'(?i)(^|\n)\s*<\s*/?\s*(system|instruction|prompt|override|admin|ignore)', r'\1[filtered]', text)
    # Neutralize "ignore previous instructions" type patterns
    text = re.sub(r'(?i)ignor[ae]\s+(tutt[eio]|l[ea]|previous|all|ogni)\s+(istruzion[ei]|instruc|prompt|regol[ea])', '[filtered]', text)
    return text.strip()


# ---------------------------------------------------------------------------
# SSRF protection for user-supplied URLs
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = frozenset({
    "localhost", "0.0.0.0", "127.0.0.1", "::1",
    "metadata.google.internal",             # GCP metadata
    "169.254.169.254",                      # AWS/Azure metadata
    "metadata.internal",
})

def _validate_feed_url(url: str) -> tuple[bool, str]:
    """Validate a user-supplied URL to prevent SSRF attacks.

    Returns (is_valid, error_message).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL non valido"

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        return False, "Solo URL http:// o https:// sono consentiti"

    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        return False, "URL non valido (hostname mancante)"

    # Blocked hostnames
    if hostname in _BLOCKED_HOSTS:
        return False, "URL non consentito (indirizzo riservato)"

    # Block private/internal IPs
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "URL non consentito (indirizzo di rete privato)"
    except ValueError:
        # It's a hostname, not an IP — resolve and check
        try:
            resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _type, _proto, _canonname, sockaddr in resolved:
                addr = sockaddr[0]
                ip = ipaddress.ip_address(addr)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False, "URL non consentito (risolve a indirizzo privato)"
        except socket.gaierror:
            return False, "URL non raggiungibile (hostname non trovato)"

    return True, ""


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
        headers=headers, json=payload, timeout=240,
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


def _generate_image(prompt: str, aspect_ratio: str = "1:1",
                    model: str = MODEL_IMAGE) -> str | None:
    """Generate an image via OpenRouter image generation API.

    Returns base64 data URL (data:image/png;base64,...) or None on failure.
    Uses the same OpenRouter API with modalities=["image"].
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5001",
        "X-Title": "Content Dashboard",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image"],
    }
    # Add aspect ratio config if not default
    if aspect_ratio and aspect_ratio != "1:1":
        payload["image_config"] = {"aspect_ratio": aspect_ratio}

    try:
        resp = requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers=headers, json=payload, timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            _log_pipeline("error", f"Image gen error: {data['error']}")
            return None
        # Extract base64 image from response
        msg = data.get("choices", [{}])[0].get("message", {})
        images = msg.get("images", [])
        if images:
            return images[0].get("image_url", {}).get("url")
        _log_pipeline("warn", "Image gen returned no images in response")
        return None
    except Exception as e:
        _log_pipeline("error", f"Image generation failed: {e}")
        return None


def _generate_and_upload_image(prompt: str, user_id: str, template_id: str,
                               aspect_ratio: str = "1:1",
                               filename: str = None) -> str | None:
    """Generate an image and upload it to Supabase Storage.

    Returns the public URL of the uploaded image, or None on failure.
    """
    base64_url = _generate_image(prompt, aspect_ratio=aspect_ratio)
    if not base64_url:
        return None

    try:
        # Parse base64 data URL → raw bytes
        # Format: data:image/png;base64,iVBORw0KGgo...
        header, b64data = base64_url.split(",", 1)
        img_bytes = base64.b64decode(b64data)
        content_type = "image/png"
        if "image/jpeg" in header:
            content_type = "image/jpeg"
        elif "image/webp" in header:
            content_type = "image/webp"

        ext = content_type.split("/")[1]
        if not filename:
            filename = f"ai_gen_{uuid.uuid4().hex[:8]}.{ext}"

        public_url = db.upload_template_asset(
            user_id, template_id, filename, img_bytes, content_type
        )
        _log_pipeline("info", f"AI image generated and uploaded: {filename}")
        return public_url
    except Exception as e:
        _log_pipeline("error", f"Failed to upload generated image: {e}")
        return None


def _llm_call_validated(messages: list, model: str = MODEL_SMART,
                        temperature: float = 0.5, expect_json: bool = False,
                        expect_html: bool = False, fallback_model: str = None) -> str:
    """Two-model pipeline: generate with primary model, validate, retry with fallback if needed.

    Validator logic (deterministic, no AI cost):
    - expect_json: Verifies output is valid JSON, attempts to fix common issues
    - expect_html: Verifies output contains proper HTML structure
    - If validation fails, retries once with the same model (stricter prompt)
    - If retry fails and fallback_model given, tries with fallback
    """
    raw = _llm_call(messages, model=model, temperature=temperature)

    # --- Deterministic validator (no AI, just code) ---
    if expect_json:
        cleaned = _strip_fences(raw)
        try:
            json.loads(cleaned)
            return cleaned  # valid JSON
        except json.JSONDecodeError:
            # Try to extract JSON from text
            first = cleaned.find("{")
            last = cleaned.rfind("}")
            if first != -1 and last > first:
                try:
                    json.loads(cleaned[first:last + 1])
                    return cleaned[first:last + 1]
                except json.JSONDecodeError:
                    pass
            # Try array
            first = cleaned.find("[")
            last = cleaned.rfind("]")
            if first != -1 and last > first:
                try:
                    json.loads(cleaned[first:last + 1])
                    return cleaned[first:last + 1]
                except json.JSONDecodeError:
                    pass
            _log_pipeline("warn", f"JSON validation failed, retrying", {"model": model})
            # Retry with explicit instruction
            retry_msgs = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "ERRORE: la tua risposta non è JSON valido. Rispondi con SOLO JSON valido, senza testo prima o dopo. Niente ```json```, niente commenti."}
            ]
            retry_model = fallback_model or model
            raw2 = _llm_call(retry_msgs, model=retry_model, temperature=max(0.1, temperature - 0.2))
            cleaned2 = _strip_fences(raw2)
            try:
                json.loads(cleaned2)
                return cleaned2
            except json.JSONDecodeError:
                first2 = cleaned2.find("{")
                last2 = cleaned2.rfind("}")
                if first2 != -1 and last2 > first2:
                    try:
                        json.loads(cleaned2[first2:last2 + 1])
                        return cleaned2[first2:last2 + 1]
                    except json.JSONDecodeError:
                        pass
                _log_pipeline("error", "JSON validation failed after retry")
                return raw  # Return original, let caller handle

    if expect_html:
        cleaned = _strip_fences(raw)
        extracted = _extract_html(cleaned)
        if extracted:
            return extracted
        _log_pipeline("warn", f"HTML validation failed, retrying", {"model": model})
        retry_msgs = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "ERRORE: la tua risposta non contiene HTML valido. Restituisci SOLO il codice HTML completo, da <!DOCTYPE html> a </html>. Niente commenti, niente ```."}
        ]
        retry_model = fallback_model or model
        raw2 = _llm_call(retry_msgs, model=retry_model, temperature=max(0.1, temperature - 0.2))
        cleaned2 = _strip_fences(raw2)
        extracted2 = _extract_html(cleaned2)
        return extracted2 or cleaned2

    return raw


def _extract_html(text: str) -> str | None:
    """Extract ONLY the HTML portion from text, removing surrounding prose.

    Handles:
    - Full documents: <!DOCTYPE html>...</html>
    - Partial fragments: <div>...</div>, <table>...</table>, etc.
    - Surrounding text like 'Ecco il template:' or 'Fammi sapere!'
    Returns None if no HTML found.
    """
    lower = text.lower()
    # Strategy 1: Full HTML document (<!DOCTYPE...> to </html>)
    doctype_pos = lower.find("<!doctype")
    html_end = lower.rfind("</html>")
    if doctype_pos != -1 and html_end != -1 and html_end > doctype_pos:
        return text[doctype_pos:html_end + 7].strip()
    # Strategy 2: <html> to </html>
    html_start = lower.find("<html")
    if html_start != -1 and html_end != -1 and html_end > html_start:
        return text[html_start:html_end + 7].strip()
    # Strategy 3: First opening tag to last closing tag (for fragments)
    first_tag = re.search(r'<(div|table|section|header|body|main|article)\b', lower)
    if first_tag:
        tag_name = first_tag.group(1)
        last_close = lower.rfind(f"</{tag_name}>")
        if last_close > first_tag.start():
            return text[first_tag.start():last_close + len(f"</{tag_name}>")].strip()
    # Strategy 4: Any substantial HTML content (contains tags)
    if re.search(r'<\w+[^>]*>', text) and ("<div" in lower or "<table" in lower or "<p" in lower):
        return text.strip()
    return None


def _strip_fences(s: str) -> str:
    """Remove markdown code fences from LLM output."""
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```html"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


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
        # Auto-popola con TUTTO il catalogo per nuovi utenti
        auto_config: dict = {"categories": {}}
        for cat_name, feeds in FEED_CATALOG.items():
            auto_config["categories"][cat_name] = [
                {"url": f["url"], "name": f["name"]} for f in feeds
            ]
        db.save_feeds_config(user_id, auto_config)
        _log_pipeline("info", f"Auto-populated feeds config with {sum(len(v) for v in auto_config['categories'].values())} feeds from catalog")
        return auto_config
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


def _enrich_prompt_with_feedback(prompt_name: str, feedback_ids: list[str]) -> str:
    current_prompt = _get_prompt(prompt_name)
    if not current_prompt:
        return ""

    user_id = _get_user_id()
    selected = db.get_feedback_by_ids(user_id, feedback_ids)
    if not selected:
        return current_prompt

    feedback_text = "\n".join(f"- {_sanitize_user_input(e['feedback'], max_length=1000)}" for e in selected)

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
            model=MODEL_SMART, temperature=0.3,
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
    uid = user_id
    if not uid:
        uid = getattr(g, "user_id", None)
    if not uid:
        # No authenticated user (e.g. Stripe webhook, background task)
        # Log to app logger but skip DB write (requires user_id FK)
        app.logger.info(f"[pipeline/{level}] {message}")
        return
    db.add_pipeline_log(uid, level, message, extra)


def _snapshot_all_prompts(trigger: str = "init"):
    for name, content in BASE_PROMPTS.items():
        _log_prompt_version(name, content, trigger)


# ---------------------------------------------------------------------------
# ntfy push notifications
# ---------------------------------------------------------------------------

def _send_ntfy(title: str, message: str, url: str | None = None, tags: str = "loudspeaker", topic: str = ""):
    ntfy_topic = topic or NTFY_TOPIC
    if not ntfy_topic:
        return False
    try:
        payload = {
            "topic": ntfy_topic,
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
                    item_user_id = item.get("user_id")
                    if not item_user_id:
                        continue  # skip items without user_id
                    platform = item.get("platform", "content")
                    title_text = item.get("title", "Contenuto programmato")
                    emoji_map = {"linkedin": "\U0001f4bc", "instagram": "\U0001f4f8", "newsletter": "\U0001f4e7"}
                    emoji = emoji_map.get(platform, "\U0001f4e2")
                    # Get user-specific ntfy topic
                    user_topic = ""
                    try:
                        profile = db.get_profile(item_user_id)
                        user_topic = (profile or {}).get("ntfy_topic", "")
                    except Exception:
                        pass
                    _send_ntfy(
                        title=f"{emoji} Pubblica {platform.upper()}",
                        message=f"{title_text}\n\nÈ ora di pubblicare questo contenuto!",
                        tags=f"{platform},bell",
                        url=f"{APP_BASE_URL}/app",
                        topic=user_topic,
                    )
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


def _retention_cleanup():
    """Background task: delete expired sessions + their carousel images from Storage.

    Runs every 6 hours. Per-plan retention:
      free  = 24 hours
      pro   = 30 days
      business = 90 days
    """
    # Wait 60s after startup before first run
    time.sleep(60)
    while True:
        total_deleted = 0
        try:
            users = db.get_all_users_with_sessions()
            for user_row in users:
                uid = user_row["user_id"]
                try:
                    sub = db.get_subscription(uid)
                    plan = (sub or {}).get("plan", "free")
                    expired = db.get_expired_sessions(plan, uid)
                    if not expired:
                        continue

                    session_ids = []
                    for sess in expired:
                        sid = sess["id"]
                        session_ids.append(sid)
                        # Delete carousel images from Storage
                        carousel = sess.get("carousel_images") or {}
                        if carousel:
                            # Count how many images to try deleting
                            max_slides = max(len(v) if isinstance(v, list) else 0 for v in carousel.values()) if carousel else 0
                            if max_slides:
                                db.delete_carousel_images(uid, sid, num_slides=max_slides)

                    deleted = db.delete_sessions_batch(session_ids)
                    total_deleted += deleted
                except Exception:
                    pass  # Skip this user, continue with next

            if total_deleted:
                try:
                    _log_pipeline("info", f"Retention cleanup: deleted {total_deleted} expired sessions")
                except Exception:
                    pass
        except Exception as e:
            try:
                _log_pipeline("error", f"Retention cleanup error: {e}")
            except Exception:
                pass

        # Run every 6 hours
        time.sleep(6 * 3600)


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
def landing():
    """Public landing page — always visible, no auth required."""
    return render_template("landing.html")


@app.route("/app")
def app_dashboard():
    """SPA dashboard — serves the main application (auth handled client-side)."""
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


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
    if len(password) < 8:
        return jsonify({"error": "La password deve avere almeno 8 caratteri"}), 400

    # Password strength validation
    import re
    if not re.search(r"[A-Z]", password):
        return jsonify({"error": "La password deve contenere almeno una lettera maiuscola"}), 400
    if not re.search(r"[a-z]", password):
        return jsonify({"error": "La password deve contenere almeno una lettera minuscola"}), 400
    if not re.search(r"\d", password):
        return jsonify({"error": "La password deve contenere almeno un numero"}), 400

    # Check for duplicate email before calling Supabase signup
    if auth.check_user_exists(email):
        return jsonify({"error": "Questo indirizzo email è già registrato. Prova ad accedere."}), 409

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
        app.logger.error(f"Signup error: {e}")
        return jsonify({"error": "Errore durante la registrazione. Riprova tra poco."}), 500


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
        app.logger.error(f"Login error: {e}")
        return jsonify({"error": "Errore di login. Riprova tra poco."}), 500


@app.route("/auth/refresh", methods=["POST"])
def auth_refresh():
    body = request.json or {}
    refresh_token = body.get("refresh_token", "")
    if not refresh_token:
        return jsonify({"error": "refresh_token required"}), 400

    try:
        result = auth.refresh_session(refresh_token)
        return jsonify(result)
    except RuntimeError:
        return jsonify({"error": "Sessione scaduta. Effettua nuovamente il login."}), 401
    except Exception as e:
        app.logger.error(f"Token refresh error: {e}")
        return jsonify({"error": "Errore nel refresh della sessione."}), 500


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
# Routes — Password Recovery
# ---------------------------------------------------------------------------

@app.route("/auth/forgot-password", methods=["POST"])
def auth_forgot_password():
    """Send a password reset email."""
    body = request.json or {}
    email = (body.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Inserisci la tua email"}), 400

    auth.send_password_reset(email)
    # Always return success to prevent email enumeration
    return jsonify({
        "status": "ok",
        "message": "Se l'email esiste nel nostro sistema, riceverai un link per reimpostare la password.",
    })


@app.route("/auth/update-password", methods=["POST"])
@auth.require_auth
def auth_update_password():
    """Update user password (requires valid access token — from reset link or logged in)."""
    body = request.json or {}
    new_password = body.get("new_password", "")

    if len(new_password) < 8:
        return jsonify({"error": "La password deve avere almeno 8 caratteri"}), 400

    import re
    if not re.search(r"[A-Z]", new_password):
        return jsonify({"error": "La password deve contenere almeno una lettera maiuscola"}), 400
    if not re.search(r"[a-z]", new_password):
        return jsonify({"error": "La password deve contenere almeno una lettera minuscola"}), 400
    if not re.search(r"\d", new_password):
        return jsonify({"error": "La password deve contenere almeno un numero"}), 400

    try:
        auth.update_user_password(g.access_token, new_password)
        return jsonify({"status": "ok", "message": "Password aggiornata con successo."})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Password update error: {e}")
        return jsonify({"error": "Errore nell'aggiornamento della password."}), 500


# ---------------------------------------------------------------------------
# Routes — Magic Link
# ---------------------------------------------------------------------------

@app.route("/auth/magic-link", methods=["POST"])
def auth_magic_link():
    """Send a magic link for passwordless login."""
    body = request.json or {}
    email = (body.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Inserisci la tua email"}), 400

    auth.send_magic_link(email)
    return jsonify({
        "status": "ok",
        "message": "Ti abbiamo inviato un link di accesso via email.",
    })


# ---------------------------------------------------------------------------
# Routes — OAuth
# ---------------------------------------------------------------------------

@app.route("/auth/oauth/<provider>")
def auth_oauth_redirect(provider):
    """Redirect user to OAuth provider (Google, GitHub, etc.)."""
    allowed_providers = ["google", "github", "apple"]
    if provider not in allowed_providers:
        return jsonify({"error": f"Provider '{provider}' non supportato"}), 400

    # Build callback URL dynamically
    redirect_to = request.host_url.rstrip("/") + "/auth/callback"
    oauth_url = auth.get_oauth_url(provider, redirect_to)
    return jsonify({"url": oauth_url})


@app.route("/auth/callback")
def auth_callback():
    """Handle OAuth / magic link / email confirmation callback.

    After Supabase redirects back, the URL contains a hash fragment with
    access_token and refresh_token. Since hash fragments are not sent to the
    server, we serve a minimal HTML page that extracts them client-side
    and stores them in localStorage.
    """
    # Check for error in query params
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    if error:
        return f"""<!DOCTYPE html><html><body><script>
            window.opener ? window.opener.postMessage({{type:'auth_error',error:'{error_desc}'}}, '*') : null;
            localStorage.setItem('cd_auth_error', '{error_desc}');
            window.location.href = '/';
        </script></body></html>"""

    # Serve a page that extracts tokens from hash fragment
    return """<!DOCTYPE html>
<html><head><title>Autenticazione...</title>
<style>
body { display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:system-ui;background:#f5f5f5;margin:0; }
.card { background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.1);text-align:center; }
.spinner { width:32px;height:32px;border:3px solid #e0e0e0;border-top-color:#7c3aed;border-radius:50%;animation:spin .7s linear infinite;margin:0 auto 16px; }
@keyframes spin { to { transform:rotate(360deg) } }
</style></head>
<body><div class="card"><div class="spinner"></div><p>Autenticazione in corso...</p></div>
<script>
(function() {
    // Extract tokens from URL hash fragment
    const hash = window.location.hash.substring(1);
    const params = new URLSearchParams(hash);
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');
    const type = params.get('type'); // e.g. 'recovery' for password reset

    if (type === 'recovery' && accessToken) {
        // Password reset flow — store token and redirect to reset page
        localStorage.setItem('cd_password_reset', JSON.stringify({
            access_token: accessToken,
            refresh_token: refreshToken || '',
        }));
        localStorage.removeItem('cd_auth_error');
        window.location.href = '/';
        return;
    }

    if (accessToken) {
        // Normal OAuth / magic link login — use oauth-specific keys
        // so handleAuthCallback() picks them up
        localStorage.setItem('cd_oauth_access_token', accessToken);
        localStorage.setItem('cd_oauth_refresh_token', refreshToken || '');
        localStorage.removeItem('cd_auth_error');
        window.location.href = '/';
    } else {
        // Check query params for code-based flow
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        if (code) {
            fetch('/auth/exchange-code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code}),
            })
            .then(r => r.json())
            .then(data => {
                if (data.access_token) {
                    localStorage.setItem('cd_oauth_access_token', data.access_token);
                    localStorage.setItem('cd_oauth_refresh_token', data.refresh_token || '');
                    window.location.href = '/';
                } else {
                    localStorage.setItem('cd_auth_error', data.error || 'Errore di autenticazione');
                    window.location.href = '/';
                }
            })
            .catch(() => {
                localStorage.setItem('cd_auth_error', 'Errore di connessione');
                window.location.href = '/';
            });
        } else {
            localStorage.setItem('cd_auth_error', 'Nessun token ricevuto');
            window.location.href = '/';
        }
    }
})();
</script></body></html>"""


@app.route("/auth/exchange-code", methods=["POST"])
def auth_exchange_code():
    """Exchange OAuth/magic-link code for session tokens."""
    body = request.json or {}
    code = body.get("code", "")
    if not code:
        return jsonify({"error": "Codice mancante"}), 400

    try:
        result = auth.exchange_code_for_session(code)
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Code exchange error: {e}")
        return jsonify({"error": "Errore nello scambio del codice."}), 500


# ---------------------------------------------------------------------------
# Routes — MFA / 2FA
# ---------------------------------------------------------------------------

@app.route("/auth/mfa/enroll", methods=["POST"])
@auth.require_auth
def auth_mfa_enroll():
    """Start MFA enrollment — generates TOTP QR code."""
    try:
        result = auth.mfa_enroll(g.access_token)
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/auth/mfa/verify", methods=["POST"])
@auth.require_auth
def auth_mfa_verify():
    """Verify a TOTP code (used during enrollment confirmation and login)."""
    body = request.json or {}
    factor_id = body.get("factor_id", "")
    code = body.get("code", "")

    if not factor_id or not code:
        return jsonify({"error": "factor_id e code sono obbligatori"}), 400

    try:
        # Create challenge and verify in one step
        challenge = auth.mfa_challenge(g.access_token, factor_id)
        result = auth.mfa_verify(g.access_token, factor_id, challenge["id"], code)
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/auth/mfa/unenroll", methods=["POST"])
@auth.require_auth
def auth_mfa_unenroll():
    """Remove a TOTP factor (disable 2FA)."""
    body = request.json or {}
    factor_id = body.get("factor_id", "")
    if not factor_id:
        return jsonify({"error": "factor_id obbligatorio"}), 400

    try:
        auth.mfa_unenroll(g.access_token, factor_id)
        return jsonify({"status": "ok", "message": "Autenticazione a due fattori disattivata."})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/auth/mfa/factors")
@auth.require_auth
def auth_mfa_factors():
    """List user's active MFA factors."""
    factors = auth.mfa_list_factors(g.access_token)
    return jsonify({"factors": factors})


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

    plan_details = payments.get_plan_limits(plan)
    # Admin override: all platforms, unlimited generations
    if _is_admin():
        plan_details = dict(plan_details)  # copy
        plan_details["platforms"] = ["linkedin", "instagram", "twitter", "newsletter", "video_script"]
        usage = {"allowed": True, "used": usage.get("used", 0), "limit": -1,
                 "limit_type": "unlimited", "plan": plan}

    return jsonify({
        "subscription": subscription or {"plan": "free", "status": "active"},
        "plan_details": plan_details,
        "usage": usage,
        "is_admin": _is_admin(),
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

    # Extract user_id from webhook metadata for logging (may be absent)
    webhook_user_id = None
    try:
        obj = event.get("data", {}).get("object", {})
        webhook_user_id = (
            (obj.get("metadata") or {}).get("user_id")
            or (obj.get("client_reference_id"))
        )
    except Exception:
        pass
    _log_pipeline("info", f"Stripe webhook: {event.get('type', 'unknown')} → {result.get('action', 'ignored')}", user_id=webhook_user_id)

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
                return jsonify({"error": "Encryption not configured. Cannot save API keys securely."}), 500
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
    # SSRF protection: validate URL before accepting
    url_valid, url_error = _validate_feed_url(url)
    if not url_valid:
        return jsonify({"error": url_error}), 400
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
# Routes — Feed Catalog (curated browsable feed lists)
# ---------------------------------------------------------------------------

@app.route("/api/feeds/catalog")
def get_feed_catalog():
    """Return the curated feed catalog for users to browse."""
    # Also include info about which feeds user already has
    user_config = _load_feeds_config()
    existing_urls = set()
    for feeds in user_config.get("categories", {}).values():
        for f in feeds:
            existing_urls.add(f.get("url", ""))

    catalog_with_status = {}
    for cat, feeds in FEED_CATALOG.items():
        catalog_with_status[cat] = [
            {**f, "active": f["url"] in existing_urls}
            for f in feeds
        ]
    return jsonify({"catalog": catalog_with_status})


@app.route("/api/feeds/catalog/import", methods=["POST"])
def import_catalog_feeds():
    """Import selected catalog categories into user's feed config."""
    body = request.json or {}
    categories_to_import = body.get("categories", [])
    if not categories_to_import:
        return jsonify({"error": "Seleziona almeno una categoria"}), 400

    config = _load_feeds_config()
    existing_urls = set()
    for feeds in config.get("categories", {}).values():
        for f in feeds:
            existing_urls.add(f.get("url", ""))

    added_count = 0
    for cat_name in categories_to_import:
        if cat_name not in FEED_CATALOG:
            continue
        # Ensure category exists in user config
        if cat_name not in config["categories"]:
            config["categories"][cat_name] = []
        # Add feeds that aren't already present (by URL)
        for feed in FEED_CATALOG[cat_name]:
            if feed["url"] not in existing_urls:
                config["categories"][cat_name].append({"url": feed["url"], "name": feed["name"]})
                existing_urls.add(feed["url"])
                added_count += 1

    _save_feeds_config(config)
    _log_pipeline("info", f"Catalog import: {added_count} feed aggiunti da {len(categories_to_import)} categorie")
    return jsonify({"status": "ok", "config": config, "added": added_count})


# ---------------------------------------------------------------------------
# Routes — RSS Fetch API
# ---------------------------------------------------------------------------

_fetch_state: dict[str, dict] = {}  # user_id -> {"progress": [], "running": bool, "ts": float}
_fetch_lock = threading.Lock()       # Prevents TOCTOU race on _fetch_state

# Cleanup stale entries older than 10 minutes (prevents memory leak)
_FETCH_STATE_TTL = 600


def _cleanup_stale_fetch_states():
    """Remove completed fetch states older than TTL."""
    now = time.time()
    stale_keys = [
        uid for uid, s in _fetch_state.items()
        if not s.get("running") and (now - s.get("ts", 0)) > _FETCH_STATE_TTL
    ]
    for uid in stale_keys:
        _fetch_state.pop(uid, None)


@app.route("/api/feeds/fetch", methods=["POST"])
def fetch_feeds():
    user_id = _get_user_id()

    with _fetch_lock:
        _cleanup_stale_fetch_states()
        state = _fetch_state.get(user_id)
        if state and state.get("running"):
            return jsonify({"error": "Fetch already in progress"}), 409
        state = {"progress": [], "running": True, "ts": time.time()}
        _fetch_state[user_id] = state

    # Load config inside try — if it fails, release the state lock
    try:
        feeds_config = _load_feeds_config()
    except Exception as e:
        _log_pipeline("error", f"Failed to load feeds config: {e}")
        with _fetch_lock:
            state["running"] = False
            state["ts"] = time.time()
        return jsonify({"error": f"Errore nel caricamento configurazione feed: {e}"}), 500

    def run():
        try:
            _do_fetch(user_id, state, feeds_config)
        except Exception as e:
            state["progress"].append(f"❌ Errore critico: {e}")
            _log_pipeline("error", f"Feed fetch critical error: {e}", user_id=user_id)
        finally:
            with _fetch_lock:
                state["running"] = False
                state["ts"] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/feeds/progress")
def feed_progress():
    user_id = _get_user_id()
    state = _fetch_state.get(user_id, {"progress": [], "running": False})

    def generate():
        sent = 0
        last_ping = time.time()
        max_duration = 300  # 5 min safety limit
        start = time.time()
        while True:
            progress = state["progress"]
            while sent < len(progress):
                msg = progress[sent]
                yield f"data: {json.dumps({'msg': msg})}\n\n"
                sent += 1
                last_ping = time.time()
            if not state["running"] and sent >= len(progress):
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
            # Send keep-alive comment every 15s to prevent proxy timeout
            if time.time() - last_ping > 15:
                yield ": keepalive\n\n"
                last_ping = time.time()
            # Safety timeout
            if time.time() - start > max_duration:
                yield f"data: {json.dumps({'done': True, 'msg': 'Timeout raggiunto'})}\n\n"
                break
            time.sleep(0.3)
        # Cleanup: free progress memory after stream completes
        with _fetch_lock:
            if user_id in _fetch_state and not _fetch_state[user_id].get("running"):
                _fetch_state.pop(user_id, None)

    resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"  # Disable Nginx/proxy buffering
    return resp


def _do_fetch(user_id: str, state: dict, feeds_config: dict):
    """Core fetch + score logic (runs in background thread)."""
    progress = state["progress"]
    seen_urls = db.get_article_urls(user_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=FETCH_WINDOW_DAYS)
    new_articles = []

    config = feeds_config
    feed_items = []
    for cat, feeds in config.get("categories", {}).items():
        for feed in feeds:
            feed_items.append({"url": feed["url"], "name": feed.get("name", ""), "category": cat})

    if not feed_items:
        feed_items = [{"url": u, "name": u, "category": ""} for u in DEFAULT_RSS_FEEDS]

    for fi in feed_items:
        feed_url = fi["url"]
        feed_cat = fi.get("category", "")
        progress.append(f"Fetching {feed_url} ...")
        try:
            feed = feedparser.parse(feed_url)
            status = getattr(feed, "status", None)
            if status and status >= 400:
                progress.append(f"  \u26a0 HTTP {status} — skipping this feed")
                _log_pipeline("warning", f"RSS feed HTTP {status}", {"feed": feed_url}, user_id=user_id)
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
            progress.append(f"  \u2192 {count} new articles from {source}")
            if count > 0:
                _log_pipeline("info", f"Fetched {count} articles from {source}", {"feed": feed_url}, user_id=user_id)
        except Exception as e:
            progress.append(f"  \u26a0 Error fetching {feed_url}: {e}")
            _log_pipeline("error", f"RSS fetch error: {e}", {"feed": feed_url}, user_id=user_id)

    progress.append(f"\nTotal new articles to score: {len(new_articles)}")

    # Score in batches of 5
    scored = []
    for i in range(0, len(new_articles), 5):
        batch = new_articles[i:i + 5]
        progress.append(f"Scoring articles {i + 1}-{i + len(batch)} ...")
        try:
            articles_text = ""
            for idx, art in enumerate(batch):
                safe_title = _sanitize_user_input(art.get("title", ""), max_length=500)
                safe_desc = _sanitize_user_input(art.get("description", ""), max_length=1000)
                articles_text += f"\n---\nARTICLE {idx + 1}:\nTitle: {safe_title}\nDescription: {safe_desc}\n"

            prompt = f"""Analyze these articles about AI/tech. For EACH article return a JSON array element with:
- "index": article number (1-based)
- "category": one of ["Tool Pratici", "Casi Studio", "Automazioni", "News AI Italia"]
- "score": integer 1-10 (relevance + novelty + practical value for an AI automation consultant)
- "summary": one-line summary in Italian

Return ONLY a valid JSON array, no markdown, no explanation.
{articles_text}"""

            result = _llm_call([{"role": "user", "content": prompt}])
            result = result.strip()
            # Strip markdown code fences if present
            if result.startswith("```"):
                result = result.split("\n", 1)[1]
                result = result.rsplit("```", 1)[0]
            # Try direct parse first; if it fails, extract JSON array via regex
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\[.*\]', result, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                else:
                    raise ValueError(f"No JSON array found in LLM response: {result[:200]}")

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
            progress.append(f"  \u26a0 Scoring error: {e}")
            _log_pipeline("error", f"LLM scoring error: {e}", {"batch_start": i}, user_id=user_id)
            for art in batch:
                art["category"] = art.get("feed_category", "News AI Italia")
                art["score"] = 5
                art["summary"] = art["title"]
                art["scored_at"] = datetime.now(timezone.utc).isoformat()
                scored.append(art)

    # Apply preference boost
    prefs = db.get_selection_prefs(user_id)
    if prefs["total_selections"] > 0:
        progress.append(f"\nApplying preference boost (based on {prefs['total_selections']} past selections)...")
        boosted_count = 0
        for art in scored:
            bonus = _calc_preference_bonus(art, prefs)
            if bonus > 0:
                art["base_score"] = art["score"]
                art["boost"] = bonus
                art["score"] = min(10, round(art["score"] + bonus))
                boosted_count += 1
        progress.append(f"  \u2192 {boosted_count} articles boosted")

    # Save new articles to database
    db.insert_articles(user_id, scored)
    progress.append(f"\n\u2713 Done! {len(scored)} articles scored and saved.")
    _log_pipeline("info", f"Fetch complete: {len(scored)} articles scored and saved", user_id=user_id)

    if scored:
        # Use per-user ntfy topic (not global)
        user_ntfy_topic = ""
        try:
            user_profile = db.get_profile(user_id)
            user_ntfy_topic = (user_profile or {}).get("ntfy_topic", "")
        except Exception:
            pass
        _send_ntfy(
            title="\U0001f4f0 Feed aggiornato",
            message=f"{len(scored)} nuovi articoli analizzati e pronti per la selezione.",
            url=f"{APP_BASE_URL}/app",
            tags="newspaper",
            topic=user_ntfy_topic,
        )


@app.route("/api/articles")
def get_articles():
    user_id = _get_user_id()
    min_score = request.args.get("min_score", 0, type=int)
    articles = db.get_articles(user_id, min_score=min_score)
    return jsonify(articles)


@app.route("/api/articles/status")
def get_articles_status():
    """Check freshness of articles — stale if last fetch >24h ago."""
    user_id = _get_user_id()
    articles = db.get_articles(user_id)
    if not articles:
        return jsonify({"last_fetch": None, "stale": True, "count": 0})
    scored_dates = [a.get("scored_at", "") for a in articles if a.get("scored_at")]
    if not scored_dates:
        return jsonify({"last_fetch": None, "stale": True, "count": len(articles)})
    last_fetch = max(scored_dates)
    try:
        last_dt = datetime.fromisoformat(last_fetch.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        stale = age_hours > 24
    except Exception:
        stale = True
    return jsonify({"last_fetch": last_fetch, "stale": stale, "count": len(articles)})


# Per-platform session limits (max contents per generation session)
PLATFORM_SESSION_LIMITS = {
    "linkedin": 3,
    "instagram": 3,
    "twitter": 3,
    "newsletter": 1,
    "video_script": 3,
}


@app.route("/api/platform-limits")
def get_platform_limits():
    """Return per-platform session limits for frontend quantity selectors."""
    return jsonify(PLATFORM_SESSION_LIMITS)


# ---------------------------------------------------------------------------
# Content Generation Prompts
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = """Sei il ghostwriter personale dell'utente, un professionista che vuole posizionarsi come esperto nel suo settore.
Il tuo compito è scrivere contenuti che posizionano l'utente come un esperto pratico e onesto nel suo ambito professionale.

TONO DI VOCE:
- Diretto e pratico, mai accademico
- Onesto: se una cosa non funziona, lo dici
- Scorrevole e facile da leggere
- Non prolisso: ogni parola deve guadagnarsi il suo posto
- Coinvolgente: poni domande al lettore, poi dai le risposte più avanti nel testo
- Mai hype, mai buzzword vuote
- Scrivi come se stessi spiegando a un professionista intelligente ma non specializzato

FONTE PRIMARIA: l'articolo selezionato
FONTE SECONDARIA: il punto di vista personale dell'utente (integra sempre la sua opinione nel testo, in prima persona, come se fosse sua)
LINGUA: Italiano, con termini tecnici in inglese dove necessario (AI, workflow, ecc.)"""

BASE_FORMAT_LINKEDIN = """Formato LinkedIn — FOCUS: VALORE DI BUSINESS
- Lunghezza: 200-300 parole
- ANGOLO: Non tecnico. Parla di produttività, risparmio, economics, vantaggio competitivo.
  Traduci ogni novità tech in "cosa cambia per il mio business"
- Prima riga: hook forte che ferma lo scroll — affermazione controintuitiva O dato economico sorprendente
  O domanda provocatoria che tocca un nervo imprenditoriale
- Struttura:
  * Hook (1 riga)
  * Contesto: qual è il problema/opportunità di business (2-3 righe)
  * Insight pratico: cosa significa per chi gestisce un'azienda (3-4 righe)
  * Opinione personale dell'utente, in prima persona (2-3 righe)
  * Domanda aperta che invita commenti da imprenditori/manager
- CTA finale: "Se vuoi approfondire, sono nella newsletter (link in bio)"
- Max 2-3 emoji, niente bullet points lunghi
- NON usare gergo tecnico senza spiegarlo in termini di business impact"""

BASE_FORMAT_INSTAGRAM = """Formato Instagram — CAROSELLO (slide separate)
- Struttura: restituisci il testo diviso in SLIDE, ognuna separata da ---SLIDE---
- SLIDE 1 (copertina): titolo forte da 5-8 parole, massimo impatto visivo, SOLO il titolo
- SLIDE 2-5 (contenuto): ogni slide ha UN singolo concetto chiave in 2-3 righe brevi.
  Vai dritto al punto. Ogni slide deve avere valore autonomo anche senza le altre.
  Usa frasi corte, spezza i concetti. Niente giri di parole.
- SLIDE FINALE: CTA + domanda che invita interazione ("Salva questo post se..." o "Qual è la tua esperienza con...")
- CAPTION (dopo l'ultima slide, separata da ---CAPTION---):
  * 1 frase riassuntiva + domanda al lettore
  * 5-8 hashtag rilevanti e contestuali
- Tono: diretto, visivo, zero filler. Ogni parola deve guadagnarsi il suo spazio nel carosello.
- Lunghezza totale: 4-6 slide + caption"""

BASE_FORMAT_NEWSLETTER = """Formato Newsletter settimanale (Beehiiv):
- Lunghezza: 600-900 parole
- Struttura:
  * Titolo oggetto email (max 50 caratteri, deve invogliare ad aprire)
  * Apertura: scenario concreto o domanda che aggancia (2-3 righe)
  * SEZIONE 1, 2, 3: un paragrafo per ogni topic della settimana (4-6 righe ciascuno),
    con l'opinione dell'utente integrata naturalmente in prima persona
  * SEZIONE ESCLUSIVA: un insight, consiglio pratico o previsione che NON si trova
    nei topic trattati — qualcosa che solo l'autore può dare ai suoi lettori
    (es. un workflow che ha testato, un tool nascosto, una riflessione controcorrente)
  * Chiusura: takeaway pratico in 1-2 righe + invito a rispondere alla mail
- Stile conversazionale, come una lettera a un amico imprenditore
- Niente formattazione pesante, max un grassetto per concetto chiave

FORMATTAZIONE MARKDOWN OBBLIGATORIA:
Il testo DEVE usare markdown standard. Questo è FONDAMENTALE per il rendering nel template:
- # Titolo newsletter (una sola riga con #)
- ## Titolo sezione (per ogni sezione/topic)
- **testo grassetto** per concetti chiave (max 1-2 per paragrafo)
- *testo corsivo* per enfasi leggera
- > citazione (per quote rilevanti o dati importanti)
- - punto elenco (per liste)
- --- (tre trattini su riga singola) come separatore tra sezioni
- [testo link](url) per i link

NON usare HTML. Solo markdown puro. La prima riga DEVE essere il titolo con # singolo."""

BASE_FORMAT_TWITTER = """Formato Twitter/X — POST O THREAD
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

BASE_FORMAT_VIDEO_SCRIPT = """Formato Short Video Script (Reels/TikTok/Shorts — 60-90 secondi):
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

# Base prompts dict for initialization
BASE_PROMPTS = {
    "system_prompt": BASE_SYSTEM_PROMPT,
    "format_linkedin": BASE_FORMAT_LINKEDIN,
    "format_instagram": BASE_FORMAT_INSTAGRAM,
    "format_newsletter": BASE_FORMAT_NEWSLETTER,
    "format_twitter": BASE_FORMAT_TWITTER,
    "format_video_script": BASE_FORMAT_VIDEO_SCRIPT,
}


def _get_prompt(prompt_name: str) -> str:
    """Get user-specific prompt, falling back to base if not found."""
    try:
        user_id = _get_user_id()
        row = db.get_user_prompt(user_id, prompt_name)
        if row:
            return row["content"]
    except Exception:
        pass
    return BASE_PROMPTS.get(prompt_name, "")


def _ensure_user_prompts():
    """Ensure the current user has prompts initialized, and log initial versions."""
    try:
        user_id = _get_user_id()
        existing = db.get_all_user_prompts(user_id)
        if not existing:
            db.init_user_prompts(user_id, BASE_PROMPTS)
            # Log initial versions so they appear in the monitor "Storico Prompt"
            _snapshot_all_prompts("init")
    except Exception as e:
        import sys
        print(f"[WARN] _ensure_user_prompts failed: {e}", file=sys.stderr)


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
        return jsonify({"error": "Errore nella ricerca. Riprova tra poco."}), 500


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
            # Sanitize web search results (could contain adversarial content)
            safe_title = _sanitize_user_input(article['title'], max_length=500)
            safe_snippet = _sanitize_user_input(article['summary'], max_length=1000)
            safe_source = _sanitize_user_input(article['source'], max_length=200)
            prompt = f"""Sei un content strategist per un consulente AI italiano.
Valuta questo risultato web per potenziale contenuto:
Titolo: {safe_title}
Snippet: {safe_snippet}
Fonte: {safe_source}

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

    VALID_FORMATS = {"linkedin", "instagram", "twitter", "video_script"}
    if format_type not in VALID_FORMATS:
        return jsonify({"error": f"format must be one of: {', '.join(VALID_FORMATS)}"}), 400

    # --- Plan gating ---
    user_id = _get_user_id()
    subscription = db.get_subscription(user_id)
    user_plan = (subscription or {}).get("plan", "free")

    # Check platform access (admin bypasses all limits)
    if not _is_admin() and not payments.check_platform_access(user_plan, format_type):
        return jsonify({
            "error": f"La piattaforma '{format_type}' non è disponibile nel piano {user_plan.upper()}. Effettua l'upgrade per accedervi.",
            "code": "PLAN_LIMIT",
            "upgrade_required": True,
        }), 403

    # Check generation limit (admin bypasses)
    usage = payments.check_generation_limit(user_id, user_plan)
    if not _is_admin() and not usage["allowed"]:
        if usage["limit_type"] == "lifetime":
            limit_msg = f"Hai raggiunto il limite di {usage['limit']} generazioni totali per il piano {user_plan.upper()}. Effettua l'upgrade per continuare."
        else:
            limit_msg = f"Hai raggiunto il limite di {usage['limit']} generazioni/mese per il piano {user_plan.upper()}. Effettua l'upgrade per continuare."
        return jsonify({
            "error": limit_msg,
            "code": "GENERATION_LIMIT",
            "upgrade_required": True,
            "used": usage["used"],
            "limit": usage["limit"],
        }), 403

    # Sanitize user inputs before LLM injection
    opinion = _sanitize_user_input(opinion, max_length=2000)
    feedback = _sanitize_user_input(feedback, max_length=1000)

    if feedback:
        _add_feedback(format_type, feedback)

    _ensure_user_prompts()
    fmt = _get_prompt(f"format_{format_type}")
    if format_type == "instagram" and 0 < variant < len(IG_VARIANT_ANGLES):
        fmt += IG_VARIANT_ANGLES[variant]

    regen_instruction = ""
    if feedback:
        regen_instruction = f"\n\nISTRUZIONE DI RISCRITTURA (priorità alta, segui questa indicazione):\n{feedback}"

    if opinion:
        opinion_section = f"\nOPINIONE DELL'UTENTE:\n{opinion}"
    else:
        opinion_section = "\nNOTA: Questa è una prima bozza. L'utente non ha ancora aggiunto la sua prospettiva personale. Genera il contenuto basandoti sull'articolo, mantenendo il tono dell'utente. L'opinione verrà integrata nella prossima iterazione."

    # --- Template style constraints (inject into prompt if template selected) ---
    template_id = body.get("template_id", "")
    style_constraints = ""
    if format_type == "instagram" and template_id:
        try:
            tpl = db.get_user_template_by_id(user_id, template_id)
            if tpl and tpl.get("style_rules"):
                rules = tpl["style_rules"]
                typo = rules.get("typography", {})
                ct = typo.get("cover_title", {})
                ch = typo.get("content_header", {})
                cb = typo.get("content_body", {})
                li = typo.get("list_items", {})
                cta = typo.get("cta_text", {})
                cr = rules.get("content_rules", {})
                emph = cb.get("emphasis_tag", "strong")
                body_total = cb.get("max_chars_per_line", 55) * cb.get("max_lines", 8)
                style_constraints = f"""

VINCOLI TEMPLATE (il testo verrà renderizzato in un template con queste regole — RISPETTALE):
- Titolo cover: max {ct.get('max_chars', 80)} caratteri
- Header slide: max {ch.get('max_chars', 60)} caratteri
- Body slide: max ~{body_total} caratteri totali ({cb.get('max_lines', 8)} righe x ~{cb.get('max_chars_per_line', 55)} car/riga)
- Liste: max {li.get('max_items', 6)} punti, max {li.get('max_chars_per_item', 50)} car/punto
- CTA: max {cta.get('max_chars', 150)} caratteri
- Slide totali consigliate: {cr.get('recommended_slides', '4-7')}
- Usa <{emph}> per enfasi (il template lo renderizza con stile accento)
- NON superare MAI i limiti di caratteri — il testo viene troncato se troppo lungo!"""
        except Exception as e:
            _log_pipeline("warn", f"Failed to load style constraints for template {template_id}: {e}")

    source_mode = article.get("source_mode", "rss")
    if source_mode == "custom_text":
        custom_text = _sanitize_user_input(body.get("custom_text", "") or article.get("custom_text", ""), max_length=5000)
        user_msg = f"""TESTO PERSONALIZZATO (fonte diretta dell'utente):
{custom_text}
{opinion_section}

FORMATO RICHIESTO:
{fmt}{regen_instruction}{style_constraints}

Scrivi il contenuto ora. Restituisci SOLO il testo del post/caption, senza commenti aggiuntivi."""
    else:
        # Sanitize article fields (user-controlled data from client)
        art_title = _sanitize_user_input(article.get('title', ''), max_length=500)
        art_source = _sanitize_user_input(article.get('source', ''), max_length=200)
        art_summary = _sanitize_user_input(article.get('summary', ''), max_length=2000)
        art_desc = _sanitize_user_input(article.get('description', ''), max_length=2000)
        user_msg = f"""ARTICOLO SELEZIONATO:
Titolo: {art_title}
Fonte: {art_source}
Riassunto: {art_summary}
Descrizione: {art_desc}
{opinion_section}

FORMATO RICHIESTO:
{fmt}{regen_instruction}{style_constraints}

Scrivi il contenuto ora. Restituisci SOLO il testo del post/caption, senza commenti aggiuntivi."""

    try:
        result = _llm_call(
            [
                {"role": "system", "content": _get_prompt("system_prompt")},
                {"role": "user", "content": user_msg},
            ],
            model=MODEL_SMART, temperature=0.7,
        )
        _log_pipeline("info", f"Generated {format_type} content", {"article": article.get("title", "")})
        _update_weekly_status(format_type, "generated")
        # Increment generation counter (for plan limits)
        try:
            db.increment_generation_count(user_id)
        except Exception:
            pass
        try:
            db.create_notification(user_id, "generation", f"Contenuto {format_type} generato", article.get("title", "")[:120])
        except Exception:
            pass
        return jsonify({"content": result, "format": format_type})
    except Exception as e:
        _log_pipeline("error", f"LLM generation error ({format_type}): {e}")
        return jsonify({"error": "Errore nella generazione del contenuto. Riprova tra poco."}), 500


# ---------------------------------------------------------------------------
# Newsletter assembler — deterministic markdown → styled HTML
# ---------------------------------------------------------------------------

def _nl_escape(text: str) -> str:
    """Escape HTML entities in text (but preserve already-valid HTML tags from assembler)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def assemble_newsletter_html(markdown_text: str, layout_html: str, components: dict) -> str:
    """Convert markdown text into fully styled HTML using the template's layout and component styles.

    Architecture:
    - layout_html: the template shell with {{CONTENT}}, {{NEWSLETTER_TITLE}}, {{FOOTER}} placeholders
    - components: a dict mapping element types to inline CSS style strings
      e.g. {"h1": "font-size:28px;color:#111;", "p": "font-size:16px;color:#4b5563;", ...}
    - markdown_text: the raw newsletter text with markdown formatting

    The assembler parses the markdown deterministically (no LLM) and wraps each element
    in the appropriate HTML tag with the component's inline style.
    """
    import re as _re

    # Default component styles (fallback if component key missing)
    defaults = {
        "h1": "font-size:28px;font-weight:700;color:#111827;margin:0 0 16px 0;line-height:1.3;",
        "h2": "font-size:22px;font-weight:600;color:#1f2937;margin:24px 0 12px 0;line-height:1.3;",
        "h3": "font-size:18px;font-weight:600;color:#374151;margin:20px 0 8px 0;line-height:1.4;",
        "p": "font-size:16px;color:#4b5563;margin:0 0 16px 0;line-height:1.7;",
        "strong": "font-weight:700;color:#1f2937;",
        "em": "font-style:italic;",
        "a": "color:#6c5ce7;text-decoration:underline;",
        "blockquote": "border-left:4px solid #6c5ce7;padding:12px 20px;margin:16px 0;background:#f8f7ff;font-style:italic;color:#4b5563;",
        "ul": "margin:0 0 16px 0;padding-left:24px;",
        "ol": "margin:0 0 16px 0;padding-left:24px;",
        "li": "font-size:16px;color:#4b5563;margin:0 0 8px 0;line-height:1.6;",
        "hr": "border:none;border-top:1px solid #e5e7eb;margin:24px 0;",
        "callout": "background:#f0f9ff;border-left:4px solid #3b82f6;padding:16px 20px;margin:16px 0;border-radius:0 8px 8px 0;",
        "callout_title": "font-size:16px;font-weight:700;color:#1d4ed8;margin:0 0 8px 0;",
        "callout_body": "font-size:15px;color:#374151;margin:0;line-height:1.6;",
        "img": "max-width:100%;height:auto;border-radius:8px;margin:16px 0;display:block;",
    }

    def _style(tag: str) -> str:
        """Get the inline style for a tag, preferring components over defaults."""
        return components.get(tag, defaults.get(tag, ""))

    def _inline_format(text: str) -> str:
        """Process inline markdown: **bold**, *italic*, [links](url), `code`."""
        # Bold: **text** or __text__
        text = _re.sub(
            r'\*\*(.+?)\*\*',
            lambda m: f'<strong style="{_style("strong")}">{m.group(1)}</strong>',
            text
        )
        text = _re.sub(
            r'__(.+?)__',
            lambda m: f'<strong style="{_style("strong")}">{m.group(1)}</strong>',
            text
        )
        # Italic: *text* or _text_ (but not inside already-processed strong tags)
        text = _re.sub(
            r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)',
            lambda m: f'<em style="{_style("em")}">{m.group(1)}</em>',
            text
        )
        # Links: [text](url)
        text = _re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: f'<a href="{m.group(2)}" style="{_style("a")}">{m.group(1)}</a>',
            text
        )
        # Inline code: `code`
        text = _re.sub(
            r'`([^`]+)`',
            r'<code style="background:#f3f4f6;padding:2px 6px;border-radius:3px;font-size:14px;">\1</code>',
            text
        )
        return text

    # Split into lines and parse block-level elements
    lines = markdown_text.strip().split("\n")
    html_blocks = []
    i = 0
    title_text = ""

    while i < len(lines):
        line = lines[i].rstrip()

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # --- Horizontal rule ---
        if _re.match(r'^-{3,}$|^\*{3,}$|^_{3,}$', line.strip()):
            html_blocks.append(f'<hr style="{_style("hr")}">')
            i += 1
            continue

        # --- Headings ---
        heading_match = _re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = _inline_format(heading_match.group(2).strip())
            tag = f"h{level}"
            # Capture first h1 as the newsletter title
            if level == 1 and not title_text:
                title_text = heading_match.group(2).strip()
            html_blocks.append(f'<{tag} style="{_style(tag)}">{text}</{tag}>')
            i += 1
            continue

        # --- Blockquote ---
        if line.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(_re.sub(r'^>\s?', '', lines[i].strip()))
                i += 1
            quote_text = _inline_format(" ".join(quote_lines))
            html_blocks.append(f'<blockquote style="{_style("blockquote")}"><p style="margin:0;{_style("p")}">{quote_text}</p></blockquote>')
            continue

        # --- Callout block (:::callout or > 💡 or > ⚡ pattern) ---
        callout_match = _re.match(r'^>\s*[💡⚡🔥✨🎯📌]\s*\*\*(.+?)\*\*\s*(.*)', line)
        if callout_match:
            c_title = callout_match.group(1)
            c_body_parts = [callout_match.group(2)] if callout_match.group(2) else []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                c_body_parts.append(_re.sub(r'^>\s?', '', lines[i].strip()))
                i += 1
            c_body = _inline_format(" ".join(c_body_parts))
            html_blocks.append(
                f'<div style="{_style("callout")}">'
                f'<p style="{_style("callout_title")}">{c_title}</p>'
                f'<p style="{_style("callout_body")}">{c_body}</p>'
                f'</div>'
            )
            continue

        # --- Unordered list ---
        if _re.match(r'^[\-\*]\s+', line):
            items = []
            while i < len(lines) and _re.match(r'^[\-\*]\s+', lines[i].strip()):
                item_text = _re.sub(r'^[\-\*]\s+', '', lines[i].strip())
                items.append(f'<li style="{_style("li")}">{_inline_format(item_text)}</li>')
                i += 1
            html_blocks.append(f'<ul style="{_style("ul")}">{"".join(items)}</ul>')
            continue

        # --- Ordered list ---
        if _re.match(r'^\d+\.\s+', line):
            items = []
            while i < len(lines) and _re.match(r'^\d+\.\s+', lines[i].strip()):
                item_text = _re.sub(r'^\d+\.\s+', '', lines[i].strip())
                items.append(f'<li style="{_style("li")}">{_inline_format(item_text)}</li>')
                i += 1
            html_blocks.append(f'<ol style="{_style("ol")}">{"".join(items)}</ol>')
            continue

        # --- Image ---
        img_match = _re.match(r'^!\[([^\]]*)\]\(([^)]+)\)', line)
        if img_match:
            alt = img_match.group(1)
            src = img_match.group(2)
            html_blocks.append(f'<img src="{src}" alt="{alt}" style="{_style("img")}">')
            i += 1
            continue

        # --- Regular paragraph (collect consecutive non-empty, non-special lines) ---
        para_lines = []
        while i < len(lines):
            l = lines[i].rstrip()
            if not l.strip():
                i += 1
                break
            if _re.match(r'^#{1,3}\s|^-{3,}$|^\*{3,}$|^_{3,}$|^[\-\*]\s|^\d+\.\s|^>|^!\[', l):
                break
            para_lines.append(l.strip())
            i += 1
        if para_lines:
            para_text = _inline_format(" ".join(para_lines))
            html_blocks.append(f'<p style="{_style("p")}">{para_text}</p>')
        continue

    # Assemble the content HTML
    content_html = "\n".join(html_blocks)

    # Check if layout uses new {{CONTENT}} placeholder or old {{SECTION_*}} placeholders
    if "{{CONTENT}}" in layout_html:
        # New component-based layout: single content placeholder
        result = layout_html
        result = result.replace("{{NEWSLETTER_TITLE}}", _inline_format(title_text) if title_text else "Newsletter")
        result = result.replace("{{CONTENT}}", content_html)
        result = result.replace("{{FOOTER}}", '<p style="font-size:13px;color:#9ca3af;text-align:center;">Se non vuoi pi&ugrave; ricevere questa newsletter, <a href="{{unsubscribe_url}}" style="color:#6b7280;">clicca qui</a>.</p>')
        return result
    else:
        # Backwards compatibility: old placeholder system — inject full content into SECTION_1
        result = layout_html
        result = result.replace("{{NEWSLETTER_TITLE}}", _inline_format(title_text) if title_text else "Newsletter")
        result = result.replace("{{SECTION_1}}", content_html)
        result = result.replace("{{SECTION_2}}", "")
        result = result.replace("{{EXCLUSIVE_SECTION}}", "")
        result = result.replace("{{FOOTER}}", '<p style="font-size:13px;color:#9ca3af;text-align:center;">Se non vuoi pi&ugrave; ricevere questa newsletter, <a href="{{unsubscribe_url}}" style="color:#6b7280;">clicca qui</a>.</p>')
        return result


@app.route("/api/generate-newsletter", methods=["POST"])
def generate_newsletter():
    body = request.json
    topics = body.get("topics", [])
    feedback = _sanitize_user_input(body.get("feedback", ""), max_length=1000)
    if not topics or len(topics) < 1:
        return jsonify({"error": "At least 1 topic required"}), 400

    # --- Plan gating (newsletter) ---
    user_id = _get_user_id()
    subscription = db.get_subscription(user_id)
    user_plan = (subscription or {}).get("plan", "free")

    if not _is_admin() and not payments.check_platform_access(user_plan, "newsletter"):
        return jsonify({
            "error": "La newsletter non è disponibile nel tuo piano. Effettua l'upgrade.",
            "code": "PLAN_LIMIT",
            "upgrade_required": True,
        }), 403

    usage = payments.check_generation_limit(user_id, user_plan)
    if not _is_admin() and not usage["allowed"]:
        if usage["limit_type"] == "lifetime":
            limit_msg = f"Hai raggiunto il limite di {usage['limit']} generazioni totali per il piano {user_plan.upper()}. Effettua l'upgrade per continuare."
        else:
            limit_msg = f"Hai raggiunto il limite di {usage['limit']} generazioni/mese per il piano {user_plan.upper()}. Effettua l'upgrade per continuare."
        return jsonify({
            "error": limit_msg,
            "code": "GENERATION_LIMIT",
            "upgrade_required": True,
            "used": usage["used"],
            "limit": usage["limit"],
        }), 403

    if feedback:
        _add_feedback("newsletter", feedback)
    _ensure_user_prompts()
    has_opinions = any(t.get("opinion", "").strip() for t in topics)
    topics_text = ""
    for i, t in enumerate(topics, 1):
        art = t.get("article", {})
        op = _sanitize_user_input(t.get("opinion", ""), max_length=2000)
        # Sanitize article fields from client
        art_title = _sanitize_user_input(art.get('title', ''), max_length=500)
        art_source = _sanitize_user_input(art.get('source', ''), max_length=200)
        art_summary = _sanitize_user_input(art.get('summary', ''), max_length=2000)
        art_desc = _sanitize_user_input(art.get('description', ''), max_length=2000)
        topics_text += f"""
--- TOPIC {i} ---
Titolo: {art_title}
Fonte: {art_source}
Riassunto: {art_summary}
Descrizione: {art_desc}
"""
        if op:
            topics_text += f"Opinione dell'utente: {op}\n"
    if not has_opinions:
        topics_text += "\nNOTA: Questa è una prima bozza. L'utente non ha ancora aggiunto le sue prospettive personali.\n"
    regen_instruction = ""
    if feedback:
        regen_instruction = f"\n\nISTRUZIONE DI RISCRITTURA (priorità alta, segui questa indicazione):\n{feedback}"

    # --- Template style constraints for newsletter ---
    template_id = body.get("template_id", "")
    nl_style_constraints = ""
    if template_id:
        try:
            tpl = db.get_user_template_by_id(user_id, template_id)
            if tpl and tpl.get("style_rules"):
                rules = tpl["style_rules"]
                typo = rules.get("typography", {})
                h1 = typo.get("h1", {})
                h2 = typo.get("h2", {})
                p = typo.get("p", {})
                cr = rules.get("content_rules", {})
                nl_style_constraints = f"""

VINCOLI TEMPLATE NEWSLETTER (il testo verrà renderizzato nel template scelto — RISPETTA questi limiti):
- Titoli H1 (# ): max {h1.get('max_chars', 80)} caratteri
- Sottotitoli H2 (## ): max {h2.get('max_chars', 60)} caratteri
- Paragrafi: max ~{p.get('max_chars_per_paragraph', 400)} caratteri ciascuno
- Il template supporta: callout={'sì' if cr.get('supports_callouts') else 'no'}, blockquote={'sì' if cr.get('supports_blockquotes') else 'no'}, immagini={'sì' if cr.get('supports_images') else 'no'}
- Sezioni tipiche: {cr.get('max_sections', 5)}
- Usa markdown standard: # ## ### **bold** *italic* > blockquote - liste"""
        except Exception as e:
            _log_pipeline("warn", f"Failed to load NL style constraints for template {template_id}: {e}")

    nl_format = _get_prompt("format_newsletter")
    user_msg = f"""Questa settimana l'utente ha selezionato questi topic per la sua newsletter:
{topics_text}

FORMATO RICHIESTO:
{nl_format}{regen_instruction}{nl_style_constraints}

IMPORTANTE: La sezione esclusiva deve essere un valore aggiunto reale.

Scrivi la newsletter ora. Restituisci SOLO il testo completo, senza commenti aggiuntivi."""

    try:
        result = _llm_call(
            [
                {"role": "system", "content": _get_prompt("system_prompt")},
                {"role": "user", "content": user_msg},
            ],
            model=MODEL_SMART, temperature=0.7,
        )
        _log_pipeline("info", "Generated newsletter")
        _update_weekly_status("newsletter", "generated")
        # Increment generation counter (for plan limits)
        try:
            db.increment_generation_count(user_id)
        except Exception:
            pass
        try:
            db.create_notification(user_id, "generation", "Newsletter generata", f"{len(topics)} topic inclusi")
        except Exception:
            pass
        return jsonify({"content": result, "format": "newsletter"})
    except Exception as e:
        _log_pipeline("error", f"LLM newsletter error: {e}")
        return jsonify({"error": "Errore nella generazione della newsletter. Riprova tra poco."}), 500


@app.route("/api/newsletter/enrich-images", methods=["POST"])
def newsletter_enrich_images():
    """AI Node: Analyze newsletter markdown text and generate images where appropriate.

    This is an intelligent intermediary node that:
    1. Reads the generated newsletter markdown text
    2. Decides which sections benefit from images (max 3)
    3. Generates image prompts optimized for the content
    4. Generates images via FLUX.2 Pro
    5. Returns the enriched markdown with ![description](url) tags inserted

    Body: { "text": "markdown newsletter text", "template_id": "optional" }
    Returns: { "text": "enriched markdown with images", "images_generated": 2 }
    """
    user_id = _get_user_id()
    body = request.json or {}
    text = body.get("text", "").strip()
    template_id = body.get("template_id", "")
    if not text:
        return jsonify({"error": "Nessun testo fornito"}), 400

    try:
        # Step 1: AI decides where images should go and what they should depict
        analysis_prompt = f"""Analizza questo testo di newsletter e decidi dove inserire immagini AI-generate per migliorare l'impatto visivo.

TESTO NEWSLETTER:
{text}

REGOLE:
- Massimo 3 immagini totali (meno è meglio se il testo è breve)
- Scegli i punti dove un'immagine aggiunge valore (dopo il titolo, tra sezioni importanti, per illustrare un concetto)
- Per ogni immagine, fornisci:
  1. "after_line": il numero di riga (0-indexed) DOPO cui inserire l'immagine
  2. "prompt": descrizione dettagliata dell'immagine da generare (in inglese, per il modello)
  3. "alt": breve descrizione in italiano per l'alt text
- NON inserire immagini in punti dove spezzerebbero il flusso (es. dentro una lista, in mezzo a un paragrafo)
- Le immagini devono essere professionali, pertinenti al contenuto, senza testo

Rispondi SOLO con un JSON array:
[
  {{"after_line": 3, "prompt": "professional modern office workspace with laptop and analytics dashboard, clean minimal style", "alt": "Workspace moderno con analytics"}},
  ...
]

Se il testo non beneficia di immagini, ritorna un array vuoto: []"""

        raw = _llm_call(
            [{"role": "user", "content": analysis_prompt}],
            model=MODEL_CHEAP, temperature=0.3,
        )

        # Parse the AI's image placement decisions
        cleaned = _strip_fences(raw).strip()
        try:
            image_plan = json.loads(cleaned)
        except json.JSONDecodeError:
            first = cleaned.find("[")
            last = cleaned.rfind("]")
            if first != -1 and last > first:
                image_plan = json.loads(cleaned[first:last + 1])
            else:
                image_plan = []

        if not image_plan or not isinstance(image_plan, list):
            return jsonify({"text": text, "images_generated": 0})

        # Limit to 3 images max
        image_plan = image_plan[:3]

        # Step 2: Generate all images
        lines = text.split("\n")
        generated_images = []

        for plan in image_plan:
            prompt = plan.get("prompt", "")
            alt = plan.get("alt", "Immagine")
            after_line = plan.get("after_line", 0)

            if not prompt:
                continue

            # Use a generic template_id for non-template newsletters
            storage_tpl_id = template_id if template_id else f"nl_{uuid.uuid4().hex[:8]}"

            url = _generate_and_upload_image(
                prompt=f"Professional, high-quality image: {prompt}. Clean modern style, no text or watermarks.",
                user_id=user_id,
                template_id=storage_tpl_id,
                aspect_ratio="16:9",  # Landscape for newsletter
            )

            if url:
                generated_images.append({
                    "after_line": min(after_line, len(lines) - 1),
                    "markdown": f"\n![{alt}]({url})\n",
                })

        # Step 3: Insert images into the text (from bottom to top to preserve line numbers)
        if generated_images:
            generated_images.sort(key=lambda x: x["after_line"], reverse=True)
            for img in generated_images:
                insert_pos = img["after_line"] + 1
                lines.insert(insert_pos, img["markdown"])

        enriched_text = "\n".join(lines)
        _log_pipeline("info", f"Newsletter enriched with {len(generated_images)} AI images")

        return jsonify({
            "text": enriched_text,
            "images_generated": len(generated_images),
        })

    except Exception as e:
        _log_pipeline("error", f"Newsletter image enrichment error: {e}")
        # Non-fatal: return original text without images
        return jsonify({"text": text, "images_generated": 0})


@app.route("/api/carousel/enrich-images", methods=["POST"])
def carousel_enrich_images():
    """AI Node: Analyze carousel text and generate style-matching AI images.

    Two-phase pipeline:
    1. Decision phase (MODEL_CHEAP): analyzes slides, picks which ones (max 2) get images
    2. Generation phase (MODEL_IMAGE / FLUX.2 Pro): generates images matching template style

    Body: { "text": "---SLIDE--- separated carousel text", "template_id": "uuid" }
    Returns: { "images": {"0": "url", "2": "url"}, "count": 2 }
    """
    user_id = _get_user_id()
    body = request.json or {}
    text = body.get("text", "").strip()
    template_id = body.get("template_id", "")
    if not text:
        return jsonify({"error": "Nessun testo fornito"}), 400

    try:
        # Parse slides from text
        import re as _re
        parts = _re.split(r"---CAPTION---", text, flags=_re.IGNORECASE)
        slide_text = parts[0]
        raw_slides = [s.strip() for s in _re.split(r"---SLIDE---", slide_text, flags=_re.IGNORECASE) if s.strip()]
        if not raw_slides:
            return jsonify({"images": {}, "count": 0})

        # Load template style rules for image style guidance
        image_style_desc = "Professional, clean, modern style"
        image_style_avoid = ""
        if template_id:
            tpl = db.get_user_template_by_id(user_id, template_id)
            if tpl and tpl.get("style_rules"):
                rules = tpl["style_rules"]
                img_style = rules.get("image_style", {})
                if img_style.get("description"):
                    image_style_desc = img_style["description"]
                avoid_list = img_style.get("avoid", [])
                if avoid_list:
                    image_style_avoid = f" Avoid: {', '.join(avoid_list)}."

        # Build slide summary for the AI
        slide_summaries = []
        for i, s in enumerate(raw_slides):
            # Identify slide type from content structure
            lines = s.strip().split("\n")
            has_list = any(ln.strip().startswith(("- ", "• ", "✅", "📌", "🔹", "1.", "2.", "3.")) for ln in lines)
            is_short = len(s) < 100
            slide_type = "cover" if i == 0 else ("list" if has_list else ("cta" if i == len(raw_slides) - 1 and is_short else "content"))
            preview = s[:200].replace("\n", " | ")
            slide_summaries.append(f"Slide {i} [{slide_type}]: {preview}")

        slides_text = "\n".join(slide_summaries)

        # Phase 1: AI decides which slides get images (MODEL_CHEAP, ~$0.001)
        decision_prompt = f"""Analizza queste slide di un carousel Instagram e decidi quali beneficerebbero di un'immagine di sfondo.

SLIDE:
{slides_text}

REGOLE:
- Massimo 2 immagini totali
- La cover (slide 0) spesso beneficia di un'immagine
- Slide con contenuto descrittivo/narrativo: sì
- Slide con liste di punti: raramente (l'immagine distrae)
- Slide CTA (call to action, ultima): quasi mai
- Se il carousel ha poche slide (≤3), massimo 1 immagine

Per ogni immagine, fornisci:
1. "slide_index": indice della slide (0-based)
2. "prompt": descrizione dettagliata dell'immagine da generare (in inglese, per FLUX.2 Pro)

L'immagine verrà usata come sfondo semi-trasparente dietro il testo, quindi:
- Deve funzionare come sfondo (non troppo dettagliata, no testo)
- Deve evocare il tema della slide
- Stile desiderato: {image_style_desc}

Rispondi SOLO con un JSON array:
[{{"slide_index": 0, "prompt": "abstract dark gradient with purple light rays, minimal tech aesthetic"}}]

Se nessuna slide beneficia di immagini, ritorna: []"""

        raw = _llm_call(
            [{"role": "user", "content": decision_prompt}],
            model=MODEL_CHEAP, temperature=0.3,
        )

        # Parse the AI's decision
        cleaned = _strip_fences(raw).strip()
        try:
            image_plan = json.loads(cleaned)
        except json.JSONDecodeError:
            first = cleaned.find("[")
            last = cleaned.rfind("]")
            if first != -1 and last > first:
                image_plan = json.loads(cleaned[first:last + 1])
            else:
                image_plan = []

        if not image_plan or not isinstance(image_plan, list):
            return jsonify({"images": {}, "count": 0})

        # Limit to 2 images max
        image_plan = image_plan[:2]

        # Phase 2: Generate images (MODEL_IMAGE / FLUX.2 Pro, ~$0.03/img)
        images_map = {}
        storage_tpl_id = template_id if template_id else f"ig_{uuid.uuid4().hex[:8]}"

        for plan in image_plan:
            slide_idx = plan.get("slide_index", 0)
            prompt = plan.get("prompt", "")
            if not prompt or slide_idx < 0 or slide_idx >= len(raw_slides):
                continue

            # Prefix with template style + suffix for background use
            full_prompt = (
                f"{image_style_desc}, {prompt}. "
                f"High quality, suitable as background image behind text.{image_style_avoid} "
                f"No text, no watermarks, no logos."
            )

            url = _generate_and_upload_image(
                prompt=full_prompt,
                user_id=user_id,
                template_id=storage_tpl_id,
                aspect_ratio="1:1",
            )

            if url:
                images_map[str(slide_idx)] = url

        _log_pipeline("info", f"Carousel enriched with {len(images_map)} AI images for {len(raw_slides)} slides")
        return jsonify({
            "images": images_map,
            "count": len(images_map),
        })

    except Exception as e:
        _log_pipeline("error", f"Carousel image enrichment error: {e}")
        return jsonify({"images": {}, "count": 0})


@app.route("/api/newsletter/html", methods=["POST"])
def newsletter_to_html():
    body = request.json
    text = _sanitize_user_input((body.get("text") or ""), max_length=20000)
    template_id = body.get("template_id")
    if not text:
        return jsonify({"error": "No text provided"}), 400

    # If a custom template is provided, inject text into its layout
    if template_id:
        try:
            user_id = _get_user_id()
            tpl = db.get_user_template_by_id(user_id, template_id)
            if not tpl:
                return jsonify({"error": "Template non trovato"}), 404
            html_template = tpl["html_content"]
            components = tpl.get("components", {}) or {}

            # ── New path: component-based assembler (deterministic, no LLM) ──
            if components and "{{CONTENT}}" in html_template:
                html_result = assemble_newsletter_html(text, html_template, components)
                _log_pipeline("info", f"Newsletter HTML assembled from template {template_id} (component-based)")
                return jsonify({"html": html_result})

            # ── Legacy path: LLM parses text into sections for old placeholder templates ──
            inject_prompt = f"""Analizza il seguente testo di newsletter e restituisci un JSON con queste chiavi:
- "title": il titolo della newsletter
- "section_1": prima sezione in HTML (con <h2>, <p>, <strong> etc.)
- "section_2": seconda sezione in HTML
- "exclusive_section": sezione esclusiva/premium in HTML
- "footer": footer text

Se una sezione non è presente, usa una stringa vuota.
Restituisci SOLO il JSON valido, nient'altro.

TESTO:
{text}"""

            sections_raw = _llm_call(
                [{"role": "user", "content": inject_prompt}],
                model=MODEL_CHEAP, temperature=0.2,
            )
            cleaned = sections_raw.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            sections = json.loads(cleaned.strip())

            # Inject sections into template placeholders
            html_result = html_template
            html_result = html_result.replace("{{NEWSLETTER_TITLE}}", sections.get("title", ""))
            html_result = html_result.replace("{{SECTION_1}}", sections.get("section_1", ""))
            html_result = html_result.replace("{{SECTION_2}}", sections.get("section_2", ""))
            html_result = html_result.replace("{{EXCLUSIVE_SECTION}}", sections.get("exclusive_section", ""))
            html_result = html_result.replace("{{FOOTER}}", sections.get("footer", ""))

            _log_pipeline("info", f"Newsletter HTML from template {template_id} (legacy placeholders)")
            return jsonify({"html": html_result})
        except json.JSONDecodeError:
            _log_pipeline("error", "Failed to parse newsletter sections JSON")
            return jsonify({"error": "Errore nel parsing delle sezioni. Riprova."}), 500
        except Exception as e:
            _log_pipeline("error", f"Newsletter template error: {e}")
            return jsonify({"error": "Errore nella generazione HTML con template. Riprova."}), 500

    # Default flow: LLM converts text to HTML from scratch
    conversion_prompt = """Converti il seguente testo di newsletter in HTML email-ready con inline CSS.

REGOLE IMPORTANTI:
1. Usa SOLO inline CSS (no <style> tags, no classi CSS esterne). Ogni elemento ha il suo style="..."
2. Layout: max-width 600px, centrato, padding adeguato, sfondo bianco
3. Tipografia: font-family 'Helvetica Neue', Helvetica, Arial, sans-serif
4. Colori: testo principale #1a1a2e, titoli #16213e, link #6c5ce7, sfondo #f8f9fa per wrapper
5. Il titolo/oggetto email → <h1> grande e accattivante
6. Sezioni con heading <h2>, separatori sottili tra sezioni
7. Evidenzia i grassetti (**testo**) con <strong style="color:#6c5ce7;">
8. Aggiungi un header con il brand dell'utente e un footer con unsubscribe placeholder
9. Rendi la sezione esclusiva visivamente distinta (bordo laterale colorato o sfondo diverso)
10. Responsive: usa percentage widths dove possibile
11. Restituisci SOLO il codice HTML completo (da <!DOCTYPE html> a </html>), nient'altro.

TESTO NEWSLETTER:
"""

    try:
        html_result = _llm_call_validated(
            [
                {"role": "system", "content": "Sei un esperto di email HTML design. Converti il testo in HTML email con inline CSS perfetto per Beehiiv."},
                {"role": "user", "content": conversion_prompt + text},
            ],
            model=MODEL_SMART, temperature=0.3,
            expect_html=True,
        )
        _log_pipeline("info", "Converted newsletter to HTML")
        return jsonify({"html": html_result})
    except Exception as e:
        _log_pipeline("error", f"Newsletter HTML conversion error: {e}")
        return jsonify({"error": "Errore nella conversione HTML. Riprova tra poco."}), 500


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


@app.route("/api/notify-completion", methods=["POST"])
def notify_completion():
    """Send email notification when generation is complete."""
    user_id = _get_user_id()
    user_email = getattr(g, "user_email", "")
    if not user_email:
        return jsonify({"error": "No email found"}), 400

    resend_key = os.getenv("RESEND_API_KEY", "")
    if not resend_key:
        # Fallback: just create in-app notification
        db.create_notification(
            user_id, "generation_complete",
            "Generazione completata!",
            "I tuoi contenuti sono pronti. Vai alla sezione Crea per vederli."
        )
        return jsonify({"ok": True, "method": "in_app"})

    body = request.json or {}
    platforms = body.get("platforms", [])
    platform_names = {
        "linkedin": "LinkedIn", "instagram": "Instagram",
        "twitter": "Twitter/X", "newsletter": "Newsletter",
        "video_script": "Video Script"
    }
    import re as _re
    platform_list = ", ".join(
        platform_names.get(p, p)
        for p in set(_re.sub(r"_\d+$", "", p) for p in platforms)
    )

    try:
        import resend
        resend.api_key = resend_key
        resend.Emails.send({
            "from": os.getenv("RESEND_FROM", "Content AI <noreply@resend.dev>"),
            "to": [user_email],
            "subject": "✅ I tuoi contenuti AI sono pronti!",
            "html": f"""
            <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:32px;">
              <h2 style="color:#111;">Generazione completata!</h2>
              <p>I contenuti per <strong>{platform_list or 'le piattaforme selezionate'}</strong> sono stati generati con successo.</p>
              <p><a href="{os.getenv('APP_URL', 'https://content-ai-generator.onrender.com')}/app"
                     style="display:inline-block;background:#111;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">
                Vai ai tuoi contenuti →
              </a></p>
              <p style="color:#888;font-size:12px;margin-top:24px;">Content AI Generator</p>
            </div>
            """,
        })
        return jsonify({"ok": True, "method": "email"})
    except Exception as e:
        _log_pipeline("error", f"Email send failed: {e}")
        # Fallback: in-app notification
        db.create_notification(
            user_id, "generation_complete",
            "Generazione completata!",
            "I tuoi contenuti sono pronti."
        )
        return jsonify({"ok": True, "method": "in_app", "email_error": str(e)})


@app.route("/api/feedback")
def get_feedback():
    user_id = _get_user_id()
    return jsonify(db.get_all_feedback(user_id))


VALID_FORMAT_TYPES = {"linkedin", "instagram", "newsletter", "twitter", "video_script"}

@app.route("/api/feedback", methods=["POST"])
def add_feedback_direct():
    body = request.json
    format_type = body.get("format_type") or body.get("format", "")
    feedback = body.get("feedback", "").strip()
    if not format_type or not feedback:
        return jsonify({"error": "format_type and feedback required"}), 400
    if format_type not in VALID_FORMAT_TYPES:
        return jsonify({"error": "Formato non valido"}), 400
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
    body = request.json
    format_type = body.get("format_type", "")
    feedback_ids = body.get("feedback_ids", [])

    VALID_FORMATS = {"linkedin", "instagram", "newsletter", "twitter", "video_script"}
    if format_type not in VALID_FORMATS:
        return jsonify({"error": f"Invalid format: {format_type}"}), 400
    if not feedback_ids:
        return jsonify({"error": "No feedback selected"}), 400

    prompt_name = f"format_{format_type}"
    _ensure_user_prompts()
    old_prompt = _get_prompt(prompt_name)
    new_prompt = _enrich_prompt_with_feedback(prompt_name, feedback_ids)

    if new_prompt == old_prompt:
        return jsonify({"error": "Enrichment produced no changes"}), 400

    # Save enriched prompt to user's DB record
    user_id = _get_user_id()
    db.upsert_user_prompt(user_id, prompt_name, new_prompt, is_base=False)
    _log_prompt_version(prompt_name, new_prompt, trigger="enrichment")

    db.mark_feedback_enriched(user_id, feedback_ids)

    selected = db.get_feedback_by_ids(user_id, feedback_ids)
    selected_texts = [e["feedback"] for e in selected]
    _log_pipeline("info", f"Prompt enriched: {format_type} (used {len(feedback_ids)} feedback comments)",
                  {"feedback_used": selected_texts})
    try:
        db.create_notification(user_id, "enrichment", f"Prompt {format_type} migliorato",
                               f"Integrati {len(feedback_ids)} feedback")
    except Exception:
        pass

    return jsonify({
        "status": "ok",
        "format_type": format_type,
        "old_prompt": old_prompt,
        "new_prompt": new_prompt,
        "feedback_used": len(feedback_ids),
    })


# ---------------------------------------------------------------------------
# Routes — Notifications
# ---------------------------------------------------------------------------

@app.route("/api/notifications")
def get_notifications():
    user_id = _get_user_id()
    notifs = db.get_notifications(user_id)
    unread = db.get_unread_count(user_id)
    return jsonify({"notifications": notifs, "unread_count": unread})


@app.route("/api/notifications/read", methods=["POST"])
def mark_notification_read():
    user_id = _get_user_id()
    nid = request.json.get("notification_id", "")
    if not nid:
        return jsonify({"error": "notification_id required"}), 400
    db.mark_notification_read(user_id, nid)
    return jsonify({"status": "ok"})


@app.route("/api/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    user_id = _get_user_id()
    count = db.mark_all_notifications_read(user_id)
    return jsonify({"status": "ok", "marked": count})


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
    body = request.json
    text = body.get("text", "")
    palette_idx = body.get("palette", 0)
    template_id = body.get("template_id")
    session_id = body.get("session_id")  # for Storage path
    if not text.strip():
        return jsonify({"error": "No carousel text provided"}), 400

    user_id = _get_user_id()

    # Check platform access — Instagram carousel requires Pro+
    if not _is_admin():
        user_plan = _get_plan()
        plan_details = payments.PLANS.get(user_plan, payments.PLANS["free"])
        if "instagram" not in plan_details.get("platforms", []):
            return jsonify({
                "error": "Il rendering carousel richiede il piano Pro o superiore.",
                "code": "PLAN_LIMIT",
                "upgrade_required": True,
            }), 403

    # Optional: slide images from AI enrichment
    slide_images = body.get("slide_images")  # dict: {"0": "url", "2": "url"}

    try:
        if template_id:
            # Use custom user template for rendering
            tpl = db.get_user_template_by_id(user_id, template_id)
            if not tpl:
                return jsonify({"error": "Template non trovato"}), 404
            from carousel_renderer import render_carousel_from_template_async
            result = render_carousel_from_template_async(
                text,
                template_html=tpl["html_content"],
                aspect_ratio=tpl.get("aspect_ratio", "1:1"),
                style_rules=tpl.get("style_rules"),
                slide_images=slide_images,
            )
        else:
            # Default rendering (original palette-based)
            # Get user brand info for slide branding
            brand_name = body.get("brand_name", "")
            brand_handle = body.get("brand_handle", "")
            if not brand_name:
                try:
                    profile = db.get_profile(user_id)
                    if profile:
                        brand_name = profile.get("full_name") or ""
                except Exception:
                    pass
            from carousel_renderer import render_carousel_async
            result = render_carousel_async(
                text, palette_idx=palette_idx,
                brand_name=brand_name, brand_handle=brand_handle,
            )

        slides_bytes = result.get("slides_bytes", [])
        caption = result.get("caption", "")

        if not slides_bytes:
            return jsonify({"slides": [], "caption": caption, "error": result.get("error", "No slides")})

        # Upload PNG bytes to Supabase Storage
        # Use session_id if provided, otherwise generate a temporary one
        storage_session_id = session_id or f"tmp_{uuid.uuid4().hex[:12]}"
        slide_urls = db.upload_carousel_images_batch(user_id, storage_session_id, slides_bytes)

        _log_pipeline("info", f"Rendered carousel: {len(slide_urls)} slides → Supabase Storage")
        return jsonify({"slides": slide_urls, "caption": caption})
    except Exception as e:
        _log_pipeline("error", f"Carousel render error: {e}")
        return jsonify({"error": "Errore nel rendering del carosello. Riprova tra poco."}), 500


# ---------------------------------------------------------------------------
# Routes — Monitor
# ---------------------------------------------------------------------------

@app.route("/api/monitor/prompts")
def get_prompt_log():
    user_id = _get_user_id()
    logs = db.get_prompt_logs(user_id)
    if logs:
        return jsonify(logs)
    # Fallback: synthesize logs from current user_prompts (first-time view)
    _ensure_user_prompts()
    user_prompts = db.get_all_user_prompts(user_id)
    synthetic = []
    for name, content in user_prompts.items():
        synthetic.append({
            "prompt_name": name,
            "version": 1,
            "content": content,
            "trigger": "init",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return jsonify(synthetic)


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


@app.route("/api/retention-info")
def retention_info():
    """Return retention policy info for the current user's plan."""
    plan = _get_user_plan()
    days = db.RETENTION_DAYS.get(plan, 1)
    labels = {"free": "24 ore", "pro": "30 giorni", "business": "90 giorni"}
    return jsonify({
        "plan": plan,
        "retention_days": days,
        "retention_label": labels.get(plan, f"{days} giorni"),
    })


@app.route("/healthz")
def healthz():
    """Lightweight health check for Render / load balancers."""
    return jsonify({"status": "ok"}), 200


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
# Routes — User Templates (Personalizzazione)
# ---------------------------------------------------------------------------

# Plan limits: how many templates each plan allows
TEMPLATE_LIMITS = {"free": 1, "pro": 5, "business": 15}

# In-memory preview cache for user templates (cleared on restart / HTML change)
# Key: "{template_id}_{md5_12chars}"  Value: {"type":"gallery","slides":{...}}
_preview_cache: dict = {}


def _get_user_plan() -> str:
    """Return the user's current plan ('free', 'pro', 'business')."""
    user_id = _get_user_id()
    sub = db.get_subscription(user_id)
    return (sub or {}).get("plan", "free")


def _extract_style_rules(template_html: str, template_type: str,
                          aspect_ratio: str = "1:1",
                          components: dict = None) -> dict:
    """Analyze template HTML and extract structured style rules via AI.

    Returns a JSON dict with:
      - visual_style (mood, color_palette, aesthetic)
      - typography (per-zone: max_chars, font sizes, weights)
      - layout (viewport, padding, safe zones)
      - image_style (description for AI image generation matching)
      - content_rules (recommended slide count, format guidance)

    Uses MODEL_FAST (Gemini 2.5 Flash) — cost: ~$0.002 per extraction.
    """
    if not template_html or not template_html.strip():
        return {}

    # Build context about the template
    if template_type == "instagram":
        # Determine viewport from aspect_ratio
        ar_map = {"1:1": (1080, 1080), "4:3": (1080, 810), "3:4": (1080, 1440)}
        vw, vh = ar_map.get(aspect_ratio, (1080, 1080))

        system_msg = f"""Sei un analista di template HTML per carousel Instagram.
Analizza il template e estrai regole di stile strutturate come JSON.

Il template ha viewport {vw}x{vh}px (aspect ratio {aspect_ratio}).
Il template contiene 4 tipi di slide: cover, content, list, cta.

ANALIZZA:
1. Stile visivo: colori usati (hex), mood, estetica generale
2. Tipografia: per ogni zona di testo (cover_title, content_header, content_body, list_items, cta_text):
   - font-weight usato
   - font-size range (max e min in px)
   - max caratteri stimati per riga (basato su font-size e larghezza contenuto)
   - max righe visibili nell'area disponibile
   - tag enfasi usato (strong, em, span con classe, etc.)
3. Layout: padding, margini, larghezza/altezza area sicura per contenuto
4. Stile immagini: che tipo di immagini AI si abbinerebbero a questo stile
5. Regole contenuto: quante slide consigliate, formato cover/content/list/cta

RITORNA SOLO un JSON valido con questa struttura esatta:
{{
  "visual_style": {{
    "mood": "descrizione breve del mood visivo",
    "color_palette": ["#hex1", "#hex2", ...],
    "aesthetic": "descrizione estetica"
  }},
  "typography": {{
    "cover_title": {{
      "font_weight": 900, "max_font_size_px": 80, "min_font_size_px": 46,
      "max_chars": 80, "max_lines": 3, "line_height": 1.12
    }},
    "content_header": {{
      "font_weight": 800, "max_font_size_px": 46, "max_chars": 60, "max_lines": 2
    }},
    "content_body": {{
      "font_weight": 400, "max_font_size_px": 36, "min_font_size_px": 24,
      "max_chars_per_line": 55, "max_lines": 8, "line_height": 1.55,
      "emphasis_tag": "strong"
    }},
    "list_items": {{ "max_items": 6, "max_chars_per_item": 50 }},
    "cta_text": {{ "max_chars": 150 }}
  }},
  "layout": {{
    "viewport_width": {vw}, "viewport_height": {vh},
    "padding_px": 90, "safe_content_width": 900
  }},
  "image_style": {{
    "description": "english description of matching AI image style",
    "keywords": ["keyword1", "keyword2"],
    "preferred_aspect_ratio": "{aspect_ratio}",
    "avoid": ["thing to avoid 1", "thing to avoid 2"]
  }},
  "content_rules": {{
    "recommended_slides": "4-7",
    "cover_format": "description",
    "content_format": "description",
    "list_format": "description",
    "cta_format": "description"
  }}
}}"""
    else:
        # Newsletter template
        components_info = ""
        if components:
            components_info = f"\n\nCOMPONENTI CSS DEL TEMPLATE:\n{json.dumps(components, indent=2)}"

        system_msg = f"""Sei un analista di template HTML per newsletter email.
Analizza il template e estrai regole di stile strutturate come JSON.

Il template ha larghezza massima tipica di 600px per email.{components_info}

ANALIZZA:
1. Stile visivo: colori principali, mood, estetica
2. Tipografia: per ogni tipo di elemento (h1, h2, p, li, strong):
   - font-size usato
   - max caratteri consigliati
3. Layout: larghezza max, sezioni tipiche, struttura header/footer
4. Stile immagini: che tipo di immagini AI si abbinerebbero
5. Regole contenuto: formati supportati (callout, blockquote, immagini), max sezioni

RITORNA SOLO un JSON valido con questa struttura esatta:
{{
  "visual_style": {{
    "mood": "descrizione breve",
    "color_palette": ["#hex1", "#hex2", ...],
    "aesthetic": "descrizione estetica"
  }},
  "typography": {{
    "h1": {{ "max_chars": 80, "font_size": "28px" }},
    "h2": {{ "max_chars": 60, "font_size": "22px" }},
    "p": {{ "max_chars_per_paragraph": 400, "font_size": "16px" }},
    "li": {{ "max_chars": 120 }}
  }},
  "layout": {{
    "max_width": 600, "has_header": true, "has_footer": true,
    "sections_typical": 3
  }},
  "image_style": {{
    "description": "english description of matching AI image style",
    "keywords": ["keyword1", "keyword2"],
    "preferred_aspect_ratio": "16:9",
    "avoid": ["thing to avoid"]
  }},
  "content_rules": {{
    "supports_callouts": true,
    "supports_blockquotes": true,
    "supports_images": true,
    "max_sections": 5,
    "format": "markdown"
  }}
}}"""

    user_msg = f"TEMPLATE HTML:\n```html\n{template_html[:8000]}\n```"

    try:
        raw = _llm_call(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            model=MODEL_FAST,
            temperature=0.2,
        )

        # Parse the JSON response
        cleaned = _strip_fences(raw)
        # Try direct parse
        try:
            rules = json.loads(cleaned)
        except json.JSONDecodeError:
            # Find JSON object between first { and last }
            first = cleaned.find("{")
            last = cleaned.rfind("}")
            if first != -1 and last > first:
                rules = json.loads(cleaned[first:last + 1])
            else:
                _log_pipeline("warn", "Style rules extraction: failed to parse JSON")
                return {}

        # Add metadata
        from datetime import datetime as dt, timezone as tz
        rules["extracted_at"] = dt.now(tz.utc).isoformat()
        rules["extraction_model"] = MODEL_FAST

        _log_pipeline("info", f"Style rules extracted for {template_type} template")
        return rules

    except Exception as e:
        _log_pipeline("warn", f"Style rules extraction failed: {e}")
        return {}


@app.route("/api/templates", methods=["GET"])
def list_templates():
    """List user templates + preset templates. Includes plan limit info."""
    user_id = _get_user_id()
    ttype = request.args.get("type")  # 'instagram' or 'newsletter' or None
    user_tpls = db.get_user_templates(user_id, template_type=ttype)
    presets = db.get_preset_templates(template_type=ttype)
    plan = _get_user_plan()
    limit = TEMPLATE_LIMITS.get(plan, 1)
    if _is_admin():
        limit = 999
    count = db.count_user_templates(user_id)
    return jsonify({
        "templates": user_tpls,
        "presets": presets,
        "plan": plan,
        "limit": limit,
        "count": count,
    })


@app.route("/api/templates/<template_id>", methods=["GET"])
def get_template(template_id):
    """Get a single user template with HTML and chat history."""
    user_id = _get_user_id()
    tpl = db.get_user_template_by_id(user_id, template_id)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404
    return jsonify(tpl)


@app.route("/api/templates", methods=["POST"])
def create_template():
    """Create a new user template. Checks plan limits."""
    user_id = _get_user_id()
    body = request.json or {}
    template_type = body.get("template_type", "")
    name = body.get("name", "Senza nome")
    aspect_ratio = body.get("aspect_ratio", "1:1")
    html_content = body.get("html_content", "")

    if template_type not in ("instagram", "newsletter"):
        return jsonify({"error": "template_type deve essere 'instagram' o 'newsletter'"}), 400
    if aspect_ratio not in ("1:1", "4:3", "3:4"):
        return jsonify({"error": "aspect_ratio deve essere '1:1', '4:3' o '3:4'"}), 400

    # Check plan limit
    plan = _get_user_plan()
    limit = TEMPLATE_LIMITS.get(plan, 1)
    if _is_admin():
        limit = 999
    count = db.count_user_templates(user_id)
    if count >= limit:
        return jsonify({"error": f"Hai raggiunto il limite di {limit} template per il piano {plan}. Passa a un piano superiore per crearne di più."}), 403

    tpl = db.create_user_template(
        user_id=user_id,
        template_type=template_type,
        name=name,
        html_content=html_content,
        aspect_ratio=aspect_ratio,
        chat_history=[],
    )
    _log_pipeline("info", f"Template created: {name} ({template_type})")
    return jsonify(tpl), 201


@app.route("/api/templates/<template_id>", methods=["DELETE"])
def delete_template(template_id):
    """Delete a user template (with ownership check)."""
    user_id = _get_user_id()
    ok = db.delete_user_template(template_id, user_id)
    if not ok:
        return jsonify({"error": "Template non trovato o non autorizzato"}), 404
    _log_pipeline("info", f"Template deleted: {template_id}")
    return jsonify({"status": "ok"})


@app.route("/api/templates/<template_id>/chat", methods=["POST"])
def template_chat(template_id):
    """Chat with the AI to iteratively build/modify a template's HTML."""
    user_id = _get_user_id()
    tpl = db.get_user_template_by_id(user_id, template_id)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404

    body = request.json or {}
    user_message = _sanitize_user_input(body.get("message", ""), max_length=3000)
    # Support both single image_url (legacy) and multiple image_urls
    image_urls = body.get("image_urls", [])
    if not image_urls:
        legacy_url = body.get("image_url", "")
        if legacy_url:
            image_urls = [legacy_url]
    # Limit to 5 images max
    image_urls = [u for u in image_urls if isinstance(u, str) and u.strip()][:5]
    if not user_message.strip() and not image_urls:
        return jsonify({"error": "Messaggio vuoto"}), 400

    template_type = tpl["template_type"]
    current_html = tpl.get("html_content", "")
    chat_history = tpl.get("chat_history", []) or []
    aspect_ratio = tpl.get("aspect_ratio", "1:1")
    current_components = tpl.get("components", {}) or {}

    # Build system prompt based on template type
    if template_type == "instagram":
        dimensions = {"1:1": "1080x1080", "4:3": "1080x810", "3:4": "1080x1440"}.get(aspect_ratio, "1080x1080")
        w, h = dimensions.split("x")
        system_prompt = f"""Sei un designer HTML/CSS esperto specializzato in slide Instagram. Crei template HTML che verranno renderizzati in immagini PNG da Playwright (browser headless).

═══ VIEWPORT E DIMENSIONI ═══
- Dimensione esatta: {w}px × {h}px (aspect ratio {aspect_ratio})
- Il tuo HTML verrà visualizzato in un browser a queste dimensioni esatte
- Usa SOLO unità px per sizing — NO vh, vw, %, em, rem
- Tutto il testo e gli elementi devono stare dentro {w}×{h}px senza scrolling

═══ STRUTTURA HTML OBBLIGATORIA ═══
Ogni slide DEVE seguire questa struttura:
```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=NomeFontScelto:wght@400;600;700;800;900&display=swap');
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ width: {w}px; height: {h}px; overflow: hidden; font-family: 'NomeFontScelto', sans-serif; }}
    /* ... il tuo CSS ... */
  </style>
</head>
<body>
  <!-- contenuto slide -->
</body>
</html>
```

═══ I 4 TIPI DI SLIDE ═══
1. **cover** — Prima slide, titolo grande.
   Placeholder: {{{{COVER_TITLE}}}}, {{{{COVER_SUBTITLE}}}}
2. **content** — Slide con testo (header + paragrafo).
   Placeholder: {{{{CONTENT_HEADER}}}}, {{{{CONTENT_BODY}}}}
3. **list** — Slide con elenco.
   Placeholder: {{{{LIST_HEADER}}}}, {{{{LIST_ITEMS}}}} (sarà HTML: <li>punto 1</li><li>punto 2</li>)
4. **cta** — Ultima slide, call-to-action.
   Placeholder: {{{{CTA_TEXT}}}}, {{{{CTA_BUTTON}}}}

Placeholder comuni: {{{{SLIDE_NUM}}}}, {{{{TOTAL_SLIDES}}}}, {{{{BRAND_NAME}}}}, {{{{BRAND_HANDLE}}}}
Usa SOLO questi placeholder — non inventarne di nuovi.

═══ FONT ═══
- Carica i font con @import di Google Fonts dentro il <style>
- Specifica i pesi che usi (400, 600, 700, 800, 900)
- Applica il font su body e su tutti gli elementi

═══ ICONE E SVG ═══
Se devi inserire icone (cuore, segnalibro, freccia, stella, ecc.), usa SVG inline:
- OBBLIGATORIO: aggiungi SEMPRE xmlns="http://www.w3.org/2000/svg" nel tag <svg>
- Esempio cuore: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="white"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
- Esempio segnalibro: <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="white"><path d="M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z"/></svg>
- NON usare emoji come icone — non renderizzano bene in Playwright
- NON usare icon font (FontAwesome, Material Icons) — non sono disponibili

═══ IMMAGINI E LOGO ═══
L'utente può allegare fino a 5 immagini per messaggio, oppure può chiedere di GENERARE immagini con AI:
- Le immagini (allegate o generate) vengono caricate su Supabase Storage — URL nel formato: https://fepljzntmbtcucbymtgq.supabase.co/storage/v1/object/public/template-assets/...
- GUARDA il messaggio utente: se c'è scritto "[Immagine allegata: URL]" o "[Immagine AI generata: URL — Descrizione: ...]", quell'URL è l'immagine
- Per inserire un'immagine: <img src="QUELL_URL_ESATTO" style="width: 100%; height: auto; ..."> — usa l'URL ESATTO, non modificarlo
- Se l'utente allega più immagini, potrebbe volerle usare per cose diverse (logo, sfondo, icone) — chiedi o deduci dal contesto
- Se l'utente dice "metti il logo", cerca nei messaggi precedenti l'URL dell'immagine allegata e usalo
- Quando inserisci immagini, cura la UX: dimensioni proporzionate, border-radius, ombra, margini appropriati

═══ CONSIGLI DI DESIGN ═══
- Font grandi: titoli almeno 60-90px, body almeno 32-40px per {w}x{h}
- Padding generoso: almeno 60-80px ai lati
- Colori: sfondo pieno + testo contrastante (NO trasparenze complicate)
- Decorazioni: cerchi, linee, forme geometriche via CSS (border-radius, gradients)
- Tutto il testo DEVE essere visibile — se è bianco lo sfondo DEVE essere scuro e viceversa

═══ FORMATO RISPOSTA (OBBLIGATORIO — SOLO JSON) ═══
{{{{
  "reply": "Breve messaggio in italiano (max 2-3 frasi)",
  "html": {{{{
    "cover": "<!DOCTYPE html><html>...</html>",
    "content": "<!DOCTYPE html><html>...</html>",
    "list": "<!DOCTYPE html><html>...</html>",
    "cta": "<!DOCTYPE html><html>...</html>"
  }}}}
}}}}

REGOLE FINALI:
1. SEMPRE ritorna JSON con "reply" + "html" (oggetto con 4 chiavi)
2. Ogni modifica → rigenera TUTTI e 4 i tipi con il JSON completo
3. Rispondi in italiano — il reply deve essere BREVE
4. NON dire "ho fatto" se non hai effettivamente cambiato l'HTML — l'utente vede la preview
5. Se qualcosa non è chiaro, chiedi — ma metti comunque il campo "html" con lo stato attuale"""
    else:  # newsletter
        components_json = json.dumps(current_components, indent=2) if current_components else "{}"

        system_prompt = """Sei un designer HTML esperto di email marketing. Crei template newsletter con un sistema a 2 livelli: LAYOUT + COMPONENTI.

═══ COME FUNZIONA ═══
Il template ha 2 parti separate:
1. **html** = il LAYOUT della newsletter (struttura, header, footer, wrapper) con il placeholder {{CONTENT}} dove verrà iniettato il testo.
2. **components** = una mappa di stili inline CSS per ogni tipo di elemento testuale (h1, h2, p, strong, ecc.)

Quando l'utente genera una newsletter, il testo markdown viene convertito in HTML usando i tuoi stili componenti e iniettato nel layout al posto di {{CONTENT}}.

═══ LAYOUT HTML ═══
- Max-width: 600px, centrato
- SOLO inline CSS su ogni elemento (compatibilità email: Gmail, Outlook, Apple Mail)
- Font base: 'Helvetica Neue', Helvetica, Arial, sans-serif (sovrascrivibile)
- Il layout DEVE contenere il placeholder {{CONTENT}} — è dove finisce il testo assemblato
- Placeholder opzionali: {{NEWSLETTER_TITLE}}, {{FOOTER}}
- Il layout definisce: wrapper/sfondo, header con logo, container centrale, footer
- NO <style> tags, NO classi CSS — TUTTO inline

═══ COMPONENTI (mappa stili) ═══
Ogni chiave è un tipo di elemento HTML. Il valore è una stringa di CSS inline.
Chiavi supportate:
- "h1" — titolo principale newsletter (font-size, color, font-weight, margin...)
- "h2" — sottotitoli sezioni
- "h3" — sotto-sottotitoli
- "p" — paragrafi normali
- "strong" — testo in grassetto (solo font-weight e color)
- "em" — testo in corsivo
- "a" — link (color, text-decoration)
- "blockquote" — citazioni (border-left, padding, background...)
- "ul" / "ol" — liste
- "li" — elementi lista
- "hr" — separatore orizzontale
- "callout" — box evidenziato (background, border-left, padding...)
- "callout_title" — titolo del callout
- "callout_body" — corpo del callout
- "img" — immagini inline

═══ IMMAGINI E LOGO ═══
- L'utente può allegare fino a 5 immagini per messaggio, oppure chiedere di GENERARE immagini con AI
- Se l'utente allega/genera immagini, il messaggio conterrà "[Immagine allegata: URL]" o "[Immagine AI generata: URL — Descrizione: ...]"
- Usa quegli URL ESATTI nei tag <img src="URL"> — non modificarli
- Per logo nel layout: <img src="URL" style="height:40px;width:auto;">
- Se più immagini, deduci dal contesto quale usare per cosa (logo, banner, sfondo, ecc.)
- Quando inserisci immagini nel layout, cura la UX email: max-width:100%, alt text, margini, border-radius se appropriato

═══ FORMATO RISPOSTA (SOLO JSON, OBBLIGATORIO) ═══
{
  "reply": "Breve messaggio in italiano (max 2-3 frasi)",
  "html": "<!DOCTYPE html><html>...LAYOUT COMPLETO con {{CONTENT}}...</html>",
  "components": {
    "h1": "font-size:28px;font-weight:700;color:#111827;margin:0 0 16px 0;line-height:1.3;",
    "h2": "font-size:22px;font-weight:600;color:#1f2937;margin:24px 0 12px 0;",
    "p": "font-size:16px;color:#4b5563;margin:0 0 16px 0;line-height:1.7;",
    "strong": "font-weight:700;color:#1f2937;",
    "em": "font-style:italic;",
    "a": "color:#6c5ce7;text-decoration:underline;",
    "blockquote": "border-left:4px solid #6c5ce7;padding:12px 20px;margin:16px 0;background:#f8f7ff;",
    "ul": "margin:0 0 16px 0;padding-left:24px;",
    "li": "font-size:16px;color:#4b5563;margin:0 0 8px 0;line-height:1.6;",
    "hr": "border:none;border-top:1px solid #e5e7eb;margin:24px 0;",
    "callout": "background:#f0f9ff;border-left:4px solid #3b82f6;padding:16px 20px;margin:16px 0;",
    "callout_title": "font-size:16px;font-weight:700;color:#1d4ed8;margin:0 0 8px 0;",
    "callout_body": "font-size:15px;color:#374151;margin:0;line-height:1.6;",
    "img": "max-width:100%;height:auto;border-radius:8px;margin:16px 0;"
  }
}

REGOLE:
1. SEMPRE ritorna JSON con "reply" + "html" + "components" (tutte e 3 le chiavi)
2. L'HTML è il LAYOUT (con {{CONTENT}}), NON il contenuto finale — metti testo d'esempio dove serve per la preview
3. I components sono gli stili inline per ogni tipo di elemento — cambiali quando l'utente chiede modifiche di stile
4. Ogni modifica dell'utente → rigenera HTML e components COMPLETI
5. Quando l'utente dice "colore più caldo", "font più grande", "stile più moderno" → modifica i components
6. Quando l'utente dice "aggiungi logo", "cambia header", "metti sfondo diverso" → modifica l'HTML layout
7. SOLO inline CSS nel layout — niente <style> tags
8. Rispondi in italiano, reply BREVE (max 2-3 frasi)
9. NON dire "ho fatto" se non hai effettivamente cambiato HTML o components"""

    # Build conversation messages (keep last 14 messages = ~7 exchanges)
    messages = [{"role": "system", "content": system_prompt}]

    # Add current HTML context if exists
    if current_html.strip():
        if template_type == "instagram":
            try:
                slides = json.loads(current_html)
                ctx = "JSON ATTUALE DEL TEMPLATE (4 tipi di slide):\n```json\n" + json.dumps(slides, indent=2) + "\n```"
            except (json.JSONDecodeError, TypeError):
                ctx = f"HTML ATTUALE DEL TEMPLATE:\n```html\n{current_html}\n```"
        else:
            # Newsletter: include both layout HTML and components
            ctx = f"LAYOUT HTML ATTUALE:\n```html\n{current_html}\n```"
            if current_components:
                ctx += f"\n\nCOMPONENTI ATTUALI:\n```json\n{components_json}\n```"
        messages.append({"role": "system", "content": ctx})

    # Extract image URLs from full chat history for context persistence
    image_urls_in_history = []
    for msg in chat_history:
        if msg["role"] == "user" and "[Immagine allegata:" in msg.get("content", ""):
            urls = re.findall(r'\[Immagine allegata:\s*(https?://[^\]]+)\]', msg["content"])
            image_urls_in_history.extend(urls)
    if image_urls_in_history:
        img_ctx = "IMMAGINI CARICATE DALL'UTENTE (usa questi URL esatti per <img src=\"...\">):\n"
        for i, url in enumerate(image_urls_in_history, 1):
            img_ctx += f"  {i}. {url}\n"
        messages.append({"role": "system", "content": img_ctx})

    # Add recent chat history (last 14 messages ≈ 7 exchanges)
    recent_history = chat_history[-14:] if len(chat_history) > 14 else chat_history
    for msg in recent_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add the new user message (multimodal if images attached)
    if image_urls:
        user_content = []
        if user_message.strip():
            user_content.append({"type": "text", "text": user_message})
        # Add text notes with all URLs so the model can reference them in HTML
        urls_text = "\n".join(f"  {i+1}. {url}" for i, url in enumerate(image_urls))
        user_content.append({"type": "text", "text": f"[Immagini caricate ({len(image_urls)}):\n{urls_text}\n] — usa questi URL esatti per <img src>"})
        # Add each image as a visual attachment for the multimodal model
        for url in image_urls:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_message})

    try:
        raw_response = _llm_call_validated(
            messages, model=MODEL_FAST, temperature=0.4,
            expect_json=True,
        )

        # Parse JSON response from LLM
        reply_text = ""
        new_html = current_html
        new_components = current_components if template_type == "newsletter" else None
        html_changed = False
        components_changed = False

        def _try_parse_response(text):
            """Try multiple strategies to extract JSON from the LLM response."""
            cleaned = _strip_fences(text)
            # Strategy 1: Direct JSON parse
            try:
                parsed = json.loads(cleaned)
                return parsed
            except json.JSONDecodeError:
                pass
            # Strategy 2: Find JSON object in text (between first { and last })
            first_brace = cleaned.find("{")
            last_brace = cleaned.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                try:
                    parsed = json.loads(cleaned[first_brace:last_brace + 1])
                    return parsed
                except json.JSONDecodeError:
                    pass
            return None

        parsed = _try_parse_response(raw_response)

        if parsed and "html" in parsed:
            reply_text = parsed.get("reply", "Template aggiornato!")
            raw_html = parsed["html"]
            if isinstance(raw_html, dict):
                new_html = json.dumps(raw_html)
            else:
                new_html = raw_html
            html_changed = True
            # Extract components for newsletter templates
            if template_type == "newsletter" and "components" in parsed and isinstance(parsed["components"], dict):
                new_components = parsed["components"]
                components_changed = True
        elif parsed and "reply" in parsed:
            # Got JSON but no html field — model responded conversationally
            reply_text = parsed["reply"]
            _log_pipeline("warn", "Template chat: model returned JSON without 'html' field")
        else:
            # No valid JSON — try to find raw HTML
            cleaned = _strip_fences(raw_response)
            html_match = re.search(r'(<!DOCTYPE html>.*?</html>)', cleaned, re.DOTALL | re.IGNORECASE)
            if html_match:
                new_html = html_match.group(1)
                reply_text = cleaned[:cleaned.find("<!DOCTYPE")].strip() or "Ecco il template aggiornato."
                html_changed = True
            else:
                reply_text = cleaned + "\n\n⚠️ Non sono riuscito ad aggiornare il template. Riprova con istruzioni più specifiche."
                _log_pipeline("warn", f"Template chat: failed to parse JSON response")

        # Update chat history (store text only — images referenced by URL in message)
        history_user_content = user_message
        if image_urls:
            img_tags = "\n".join(f"[Immagine allegata: {url}]" for url in image_urls)
            history_user_content = f"{user_message}\n{img_tags}" if user_message.strip() else img_tags
        chat_history.append({"role": "user", "content": history_user_content})
        chat_history.append({"role": "assistant", "content": reply_text})

        # Save updated template (only update html/components if actually changed)
        db.update_user_template(
            template_id=template_id,
            user_id=user_id,
            html_content=new_html if html_changed else None,
            chat_history=chat_history,
            name=None,
            components=new_components if components_changed else None,
        )

        # Invalidate in-memory preview cache if HTML changed
        if html_changed:
            stale_keys = [k for k in _preview_cache if k.startswith(template_id)]
            for k in stale_keys:
                del _preview_cache[k]

        # Extract style rules when HTML changes (async-safe, non-blocking on error)
        extracted_rules = None
        if html_changed and new_html.strip():
            try:
                extracted_rules = _extract_style_rules(
                    template_html=new_html,
                    template_type=template_type,
                    aspect_ratio=aspect_ratio,
                    components=new_components if template_type == "newsletter" else None,
                )
                if extracted_rules:
                    db.update_user_template(
                        template_id=template_id,
                        user_id=user_id,
                        style_rules=extracted_rules,
                    )
            except Exception as e:
                _log_pipeline("warn", f"Style rules extraction skipped: {e}")

        _log_pipeline("info", f"Template chat: updated {template_id} (html_changed={html_changed})")
        return jsonify({
            "reply": reply_text,
            "html_content": new_html if html_changed else None,
            "style_rules": extracted_rules,
        })

    except Exception as e:
        _log_pipeline("error", f"Template chat error: {e}")
        return jsonify({"error": "Errore nella generazione. Riprova tra poco."}), 500


@app.route("/api/templates/<template_id>/preview", methods=["POST"])
def template_preview(template_id):
    """Generate a preview of the user template.
    IG: renders all 4 slide types via Playwright → base64 PNG gallery.
    Uses in-memory cache keyed on content hash to avoid repeated renders.
    NL: returns HTML string for iframe display.
    """
    user_id = _get_user_id()
    tpl = db.get_user_template_by_id(user_id, template_id)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404

    template_type = tpl["template_type"]
    html_content = tpl.get("html_content", "")

    if not html_content.strip():
        return jsonify({"error": "Template vuoto — inizia a chattare per crearlo"}), 400

    if template_type == "newsletter":
        components = tpl.get("components", {}) or {}
        if components and "{{CONTENT}}" in html_content:
            # New component-based template: assemble with sample content for preview
            sample_md = """# La Tua Newsletter Settimanale

Bentornato alla tua newsletter! Ecco le novità più interessanti della settimana.

## Prima Sezione

Questo è un **paragrafo di esempio** con del testo formattato. Contiene [un link](https://example.com) per mostrare lo stile dei collegamenti.

> Questa è una citazione di esempio per mostrare lo stile dei blockquote nel tuo template.

## Seconda Sezione

- Primo punto elenco di esempio
- Secondo punto con **testo in grassetto**
- Terzo punto con *testo in corsivo*

---

## Sezione Esclusiva

Contenuto premium per i tuoi lettori più fedeli. Un insight pratico che fa la differenza."""
            assembled = assemble_newsletter_html(sample_md, html_content, components)
            return jsonify({"type": "html", "html": assembled})
        else:
            # Legacy template or no components: return raw HTML
            return jsonify({"type": "html", "html": html_content})

    # For Instagram — render all 4 slide types as mini-gallery
    aspect_ratio = tpl.get("aspect_ratio", "1:1")

    # ── Fast path: in-memory cache (keyed on content hash) ──
    import hashlib
    content_hash = hashlib.md5(html_content.encode()).hexdigest()[:12]
    cache_key = f"{template_id}_{content_hash}"
    cached = _preview_cache.get(cache_key)
    if cached:
        return jsonify(cached)

    # ── Slow path: render via Playwright ──
    try:
        import base64
        from carousel_renderer import render_template_preview

        result = render_template_preview(
            template_html=html_content,
            aspect_ratio=aspect_ratio,
            brand_name=request.json.get("brand_name", "Il Tuo Brand") if request.json else "Il Tuo Brand",
            brand_handle=request.json.get("brand_handle", "@tuobrand") if request.json else "@tuobrand",
        )

        gallery = {}
        for slide_type, png_bytes in result.items():
            gallery[slide_type] = f"data:image/png;base64,{base64.b64encode(png_bytes).decode('utf-8')}"

        response_data = {"type": "gallery", "slides": gallery}

        # Store in memory cache
        _preview_cache[cache_key] = response_data

        return jsonify(response_data)
    except Exception as e:
        _log_pipeline("error", f"Template preview render error: {e}")
        return jsonify({"error": "Errore nel rendering della preview. Riprova."}), 500


@app.route("/api/templates/preset/<preset_id>/preview", methods=["GET"])
def preset_template_preview(preset_id):
    """Generate preview gallery for a preset template.
    Returns cached Supabase Storage URLs when available (instant).
    Falls back to Playwright render → upload → cache on first call.
    """
    preset = db.get_preset_template_by_id(preset_id)
    if not preset:
        return jsonify({"error": "Preset non trovato"}), 404

    html_content = preset.get("html_content", "")
    if not html_content.strip():
        return jsonify({"error": "Preset vuoto"}), 400

    template_type = preset.get("template_type", "instagram")
    if template_type == "newsletter":
        return jsonify({"type": "html", "html": html_content})

    # ── Fast path: return cached URLs from thumbnail_url ──
    thumbnail_url = preset.get("thumbnail_url", "")
    if thumbnail_url:
        try:
            cached = json.loads(thumbnail_url)
            if isinstance(cached, dict) and cached:
                return jsonify({"type": "gallery", "slides": cached})
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Slow path: render via Playwright, upload to Storage, cache in DB ──
    try:
        from carousel_renderer import render_template_preview

        result = render_template_preview(
            template_html=html_content,
            aspect_ratio=preset.get("aspect_ratio", "1:1"),
        )

        # Upload PNGs to Supabase Storage and collect public URLs
        gallery = {}
        for slide_type, png_bytes in result.items():
            url = db.upload_template_preview_image(preset_id, slide_type, png_bytes)
            gallery[slide_type] = url

        # Persist URLs in preset_templates.thumbnail_url for future instant loads
        try:
            db.update_preset_thumbnail_url(preset_id, json.dumps(gallery))
        except Exception:
            pass  # Non-critical: preview still works, just won't be cached

        return jsonify({"type": "gallery", "slides": gallery})
    except Exception as e:
        _log_pipeline("error", f"Preset preview render error: {e}")
        return jsonify({"error": "Errore nel rendering della preview."}), 500


@app.route("/api/templates/<template_id>/upload", methods=["POST"])
def template_upload_asset(template_id):
    """Upload an image/logo for use in a template. Returns the public URL."""
    user_id = _get_user_id()
    tpl = db.get_user_template_by_id(user_id, template_id)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Nessun file inviato"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Filename mancante"}), 400

    # Validate file type
    allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
    import os as _os
    ext = _os.path.splitext(f.filename)[1].lower()
    if ext not in allowed_ext:
        return jsonify({"error": f"Tipo file non supportato. Usa: {', '.join(allowed_ext)}"}), 400

    # Max 2MB
    file_bytes = f.read()
    if len(file_bytes) > 2 * 1024 * 1024:
        return jsonify({"error": "File troppo grande. Massimo 2MB."}), 400

    content_types = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    }

    try:
        import uuid as _uuid
        safe_name = f"{_uuid.uuid4().hex[:8]}{ext}"
        url = db.upload_template_asset(
            user_id=user_id,
            template_id=template_id,
            filename=safe_name,
            file_bytes=file_bytes,
            content_type=content_types.get(ext, "image/png"),
        )
        _log_pipeline("info", f"Template asset uploaded: {safe_name} for {template_id}")
        return jsonify({"url": url, "filename": safe_name})
    except Exception as e:
        _log_pipeline("error", f"Template asset upload error: {e}")
        return jsonify({"error": "Errore nell'upload. Riprova."}), 500


@app.route("/api/templates/<template_id>/generate-image", methods=["POST"])
def template_generate_image(template_id):
    """Generate an AI image from a text prompt and upload it to Storage.

    Body: { "prompt": "description of the image", "aspect_ratio": "16:9" }
    Returns: { "url": "https://...", "description": "..." }
    """
    user_id = _get_user_id()
    tpl = db.get_user_template_by_id(user_id, template_id)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404

    body = request.json or {}
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt immagine mancante"}), 400

    # Use the template's aspect ratio by default for IG, 16:9 for NL
    tpl_type = tpl.get("template_type", "instagram")
    default_ratio = tpl.get("aspect_ratio", "1:1") if tpl_type == "instagram" else "16:9"
    aspect_ratio = body.get("aspect_ratio", default_ratio)

    # Enhance the prompt for better results
    enhanced_prompt = f"Professional, high-quality image: {prompt}. Clean, modern style suitable for {'social media carousel' if tpl_type == 'instagram' else 'email newsletter'}. No text or watermarks."

    try:
        url = _generate_and_upload_image(
            prompt=enhanced_prompt,
            user_id=user_id,
            template_id=template_id,
            aspect_ratio=aspect_ratio,
        )
        if not url:
            return jsonify({"error": "Generazione immagine fallita. Riprova."}), 500

        _log_pipeline("info", f"AI image generated for template {template_id}: {prompt[:50]}")
        return jsonify({"url": url, "description": prompt})
    except Exception as e:
        _log_pipeline("error", f"Image generation endpoint error: {e}")
        return jsonify({"error": "Errore nella generazione immagine."}), 500


@app.route("/api/templates/clone/<preset_id>", methods=["POST"])
def clone_preset(preset_id):
    """Clone a preset template as a new user template."""
    user_id = _get_user_id()

    # Check plan limit
    plan = _get_user_plan()
    limit = TEMPLATE_LIMITS.get(plan, 1)
    if _is_admin():
        limit = 999
    count = db.count_user_templates(user_id)
    if count >= limit:
        return jsonify({"error": f"Hai raggiunto il limite di {limit} template per il piano {plan}."}), 403

    preset = db.get_preset_template_by_id(preset_id)
    if not preset:
        return jsonify({"error": "Preset template non trovato"}), 404

    body = request.json or {}
    custom_name = body.get("name", f"{preset['name']} (personalizzato)")

    # Copy style_rules from preset if available, otherwise extract
    preset_rules = preset.get("style_rules") or {}

    tpl = db.create_user_template(
        user_id=user_id,
        template_type=preset["template_type"],
        name=custom_name,
        html_content=preset["html_content"],
        aspect_ratio=preset.get("aspect_ratio", "1:1"),
        chat_history=[],
        components=preset.get("components", {}),
        style_rules=preset_rules,
    )

    # If preset had no style_rules, extract them now
    if not preset_rules and tpl.get("id") and preset["html_content"].strip():
        try:
            extracted = _extract_style_rules(
                template_html=preset["html_content"],
                template_type=preset["template_type"],
                aspect_ratio=preset.get("aspect_ratio", "1:1"),
                components=preset.get("components"),
            )
            if extracted:
                db.update_user_template(tpl["id"], user_id, style_rules=extracted)
                tpl["style_rules"] = extracted
        except Exception:
            pass

    _log_pipeline("info", f"Cloned preset '{preset['name']}' as '{custom_name}'")
    return jsonify(tpl), 201


@app.route("/api/templates/<template_id>/rename", methods=["POST"])
def rename_template(template_id):
    """Rename a user template."""
    user_id = _get_user_id()
    body = request.json or {}
    new_name = body.get("name", "").strip()
    if not new_name:
        return jsonify({"error": "Nome non valido"}), 400
    tpl = db.update_user_template(template_id, user_id, name=new_name)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404
    return jsonify(tpl)


@app.route("/api/templates/<template_id>/extract-rules", methods=["POST"])
def extract_template_rules(template_id):
    """Re-extract style rules from a template's current HTML.

    Useful after manual edits or to refresh outdated rules.
    """
    user_id = _get_user_id()
    tpl = db.get_user_template_by_id(user_id, template_id)
    if not tpl:
        return jsonify({"error": "Template non trovato"}), 404

    html_content = tpl.get("html_content", "")
    if not html_content.strip():
        return jsonify({"error": "Template vuoto — nessun HTML da analizzare"}), 400

    try:
        rules = _extract_style_rules(
            template_html=html_content,
            template_type=tpl["template_type"],
            aspect_ratio=tpl.get("aspect_ratio", "1:1"),
            components=tpl.get("components"),
        )
        if rules:
            db.update_user_template(template_id, user_id, style_rules=rules)
            return jsonify({"style_rules": rules})
        else:
            return jsonify({"error": "Estrazione regole fallita. Riprova."}), 500
    except Exception as e:
        _log_pipeline("error", f"Style rules extraction endpoint error: {e}")
        return jsonify({"error": "Errore nell'estrazione delle regole di stile."}), 500


# ---------------------------------------------------------------------------
# Routes — ntfy test
# ---------------------------------------------------------------------------

@app.route("/api/ntfy/test", methods=["POST"])
def test_ntfy():
    # Use per-user ntfy topic
    user_id = _get_user_id()
    profile = db.get_profile(user_id)
    user_ntfy_topic = (profile or {}).get("ntfy_topic", "")
    success = _send_ntfy(
        title="\U0001f9ea Test Content Dashboard",
        message="Le notifiche funzionano! Riceverai un avviso quando sarà ora di pubblicare.",
        tags="white_check_mark",
        topic=user_ntfy_topic,
    )
    if success:
        return jsonify({"status": "ok", "message": "Test notification sent"})
    return jsonify({"error": "Failed to send notification"}), 500


# ---------------------------------------------------------------------------
# Background threads — start at module level so Gunicorn workers also run them
# ---------------------------------------------------------------------------

_bg_started = False

def _start_background_threads():
    global _bg_started
    if _bg_started or not db.is_configured():
        return
    _bg_started = True

    threading.Thread(target=_check_schedules, daemon=True).start()
    threading.Thread(target=_retention_cleanup, daemon=True).start()

    try:
        _log_pipeline("info", "Background threads started — schedule checker + retention cleanup")
    except Exception:
        pass


# Start background threads when module is loaded (works for both Gunicorn and local dev)
_start_background_threads()


# ---------------------------------------------------------------------------
# Main (local dev only)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not db.is_configured():
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        print("Run: python setup_db.py   (after setting up .env)")
        exit(1)

    print("\n  Content AI Generator running on http://localhost:5001\n")
    app.run(debug=True, port=5001, host='0.0.0.0', use_reloader=False)
