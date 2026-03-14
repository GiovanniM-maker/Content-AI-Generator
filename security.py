"""Security module — CORS, rate limiting, headers, encryption, email.

Provides:
- Flask-CORS configuration
- Flask-Limiter (Upstash Redis backend)
- Secure response headers
- AES-256 encryption for API keys (Fernet)
- Sentry integration
- Resend transactional email helper
"""

import base64
import os
from datetime import datetime, timezone

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from flask import Flask, request, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# Sentry error tracking
# ---------------------------------------------------------------------------

def init_sentry(app: Flask):
    """Initialize Sentry for error tracking."""
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        return

    def _before_send(event, hint):
        """Filter out noisy transient errors (Redis connection, etc.)."""
        exc = hint.get("exc_info")
        if exc:
            exc_type, exc_value = exc[0], exc[1]
            msg = str(exc_value).lower()
            # Ignore Redis/Upstash transient connection errors
            if "redis" in msg or "upstash" in msg:
                if "connection" in msg or "timeout" in msg or "reading from" in msg:
                    return None
        return event

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,  # 10% of requests
        environment=os.getenv("FLASK_ENV", "production"),
        send_default_pii=False,  # Don't send user emails/IPs to Sentry
        before_send=_before_send,
    )


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def init_cors(app: Flask):
    """Configure CORS — allow same-origin + configurable origins."""
    allowed_origins = os.getenv("CORS_ORIGINS", "").split(",")
    allowed_origins = [o.strip() for o in allowed_origins if o.strip()]

    if not allowed_origins:
        # Default: restrict to app's own origin
        base_url = os.getenv("APP_BASE_URL", "http://localhost:5001")
        allowed_origins = [base_url]

    CORS(app, resources={
        r"/api/*": {"origins": allowed_origins, "supports_credentials": True},
        r"/auth/*": {"origins": allowed_origins, "supports_credentials": True},
    })


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_limiter: Limiter | None = None


def init_rate_limiter(app: Flask) -> Limiter:
    """Initialize Flask-Limiter with Upstash Redis backend (fallback: memory)."""
    global _limiter

    redis_url = os.getenv("UPSTASH_REDIS_URL", "")
    storage_uri = "memory://"

    if redis_url:
        # Upstash provides HTTPS REST URLs; Flask-Limiter needs redis(s):// protocol.
        # Try to build a valid redis URI from the Upstash URL + token.
        redis_token = os.getenv("UPSTASH_REDIS_TOKEN", "")
        if redis_url.startswith("https://"):
            # Convert https://xxx.upstash.io → rediss://:token@xxx.upstash.io:6379
            host = redis_url.replace("https://", "").rstrip("/")
            if redis_token:
                storage_uri = f"rediss://:{redis_token}@{host}:6379"
            else:
                storage_uri = "memory://"
        elif redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
            storage_uri = redis_url
        # else: keep memory://

    # Ensure Upstash URLs use TLS (rediss://)
    if "upstash.io" in storage_uri and storage_uri.startswith("redis://"):
        storage_uri = storage_uri.replace("redis://", "rediss://", 1)

    # Swallow backend errors so requests aren't killed when Redis is down
    app.config["RATELIMIT_SWALLOW_ERRORS"] = True
    # Short connection timeout so we don't block requests when Redis is unreachable
    app.config["RATELIMIT_STORAGE_OPTIONS"] = {
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "retry_on_timeout": False,
    }

    try:
        _limiter = Limiter(
            app=app,
            key_func=_get_rate_limit_key,
            default_limits=["200 per minute"],
            storage_uri=storage_uri,
            strategy="fixed-window",
        )
        app.logger.info(f"Rate limiter initialized (storage: {storage_uri[:30]}...)")
    except Exception as e:
        app.logger.warning(f"Redis rate-limit storage failed ({e}), falling back to memory://")
        _limiter = Limiter(
            app=app,
            key_func=_get_rate_limit_key,
            default_limits=["200 per minute"],
            storage_uri="memory://",
            strategy="fixed-window",
        )

    # Apply specific limits to sensitive endpoints
    # auth_signup: 3 per day per IP to slow down multi-account abuse
    for endpoint, limit_str in {
        "auth_login": "5 per minute",
        "auth_signup": "3 per day",
        "auth_refresh": "10 per minute",
        "auth_forgot_password": "3 per minute",
        "auth_magic_link": "3 per minute",
        "auth_update_password": "5 per minute",
        "auth_mfa_enroll": "5 per minute",
        "auth_mfa_verify": "10 per minute",
        "auth_mfa_unenroll": "3 per minute",
        "generate_content": "5 per minute",
        "generate_newsletter": "5 per minute",
        "create_checkout": "3 per minute",
    }.items():
        fn = app.view_functions.get(endpoint)
        if fn:
            _limiter.limit(limit_str)(fn)

    return _limiter


def _get_rate_limit_key():
    """Rate limit key: use user_id if authenticated, else IP."""
    uid = getattr(g, "user_id", None)
    if uid:
        return f"user:{uid}"
    return get_remote_address()


def get_limiter() -> Limiter | None:
    return _limiter


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

def init_security_headers(app: Flask):
    """Add security headers to all responses.

    Includes:
    - HSTS (force HTTPS)
    - CSP (Content Security Policy)
    - X-Frame-Options, X-Content-Type-Options
    - Referrer-Policy, Permissions-Policy
    - Cache-Control for API routes
    """
    is_production = os.getenv("FLASK_ENV") == "production"

    @app.after_request
    def _add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        # HSTS — tell browsers to always use HTTPS (production only)
        if is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Content Security Policy — restrict what can load
        csp_parts = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://js.stripe.com https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net",
            "img-src 'self' data: blob: https:",
            "connect-src 'self' https://*.supabase.co https://api.stripe.com https://*.sentry.io https://*.posthog.com",
            "frame-src https://js.stripe.com https://hooks.stripe.com",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)

        # Cache-control for API responses
        if request.path.startswith("/api/") or request.path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response


# ---------------------------------------------------------------------------
# API key encryption (AES-256 via Fernet)
# ---------------------------------------------------------------------------

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    """Get Fernet instance for encryption/decryption."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.getenv("ENCRYPTION_KEY", "")
    if not key:
        return None

    try:
        # Ensure key is valid base64 (Fernet requires 32 bytes, base64-encoded)
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception:
        return None


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key.

    Returns a base64-encoded 32-byte key string.
    Use this to generate ENCRYPTION_KEY for .env.
    """
    return Fernet.generate_key().decode()


def encrypt_api_key(plaintext: str) -> str | None:
    """Encrypt an API key for storage.

    Returns the encrypted string, or None if encryption is not configured.
    """
    f = _get_fernet()
    if not f or not plaintext:
        return None
    try:
        return f.encrypt(plaintext.encode()).decode()
    except Exception:
        return None


def decrypt_api_key(ciphertext: str) -> str | None:
    """Decrypt a stored API key.

    Returns the plaintext string, or None if decryption fails.
    """
    f = _get_fernet()
    if not f or not ciphertext:
        return None
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Resend email
# ---------------------------------------------------------------------------

def send_email(to: str, subject: str, html: str) -> bool:
    """Send a transactional email via Resend.

    Returns True on success, False on failure.
    """
    api_key = os.getenv("RESEND_API_KEY", "")
    from_email = os.getenv("RESEND_FROM_EMAIL", "noreply@contentdashboard.app")

    if not api_key:
        return False

    try:
        import resend
        resend.api_key = api_key
        resend.Emails.send({
            "from": from_email,
            "to": [to],
            "subject": subject,
            "html": html,
        })
        return True
    except Exception:
        return False


def send_welcome_email(email: str, name: str) -> bool:
    """Send welcome email to new user."""
    app_url = os.getenv("APP_URL", "https://content-ai-generator-1.onrender.com")
    return send_email(
        to=email,
        subject="Benvenuto su Content AI Generator! 🚀",
        html=f"""
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:32px;background:#000;color:#fff;border-radius:16px;border:1px solid rgba(255,255,255,0.1);">
            <h1 style="color:#7c3aed;font-size:24px;margin-bottom:8px;">Benvenuto, {name or 'Utente'}!</h1>
            <p style="color:#8b8aa0;font-size:15px;margin-bottom:20px;">Il tuo account Content AI Generator è pronto.</p>

            <p style="font-size:14px;line-height:1.6;">Con il piano <strong>Free</strong> hai a disposizione:</p>
            <ul style="font-size:14px;line-height:1.8;padding-left:20px;color:#ccc;">
                <li><strong>10 generazioni</strong> totali (lifetime)</li>
                <li>Post <strong>LinkedIn</strong> + <strong>Newsletter</strong></li>
                <li>Fino a <strong>5 feed RSS</strong></li>
                <li>Storico delle ultime 10 sessioni</li>
            </ul>

            <div style="background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.3);border-radius:12px;padding:16px 20px;margin:20px 0;">
                <p style="margin:0;font-size:14px;"><strong style="color:#a78bfa;">Come iniziare:</strong></p>
                <ol style="font-size:13px;line-height:1.8;padding-left:20px;color:#ccc;margin:8px 0 0;">
                    <li>Aggiungi i tuoi feed RSS o cerca un articolo sul web</li>
                    <li>Seleziona il topic e le piattaforme</li>
                    <li>Genera i contenuti con un click</li>
                </ol>
            </div>

            <p style="font-size:13px;color:#8b8aa0;margin-bottom:16px;">
                Vuoi di più? Con il piano <strong style="color:#a78bfa;">Pro</strong> a €29/mese ottieni
                50 generazioni/mese su tutte le 5 piattaforme, caroselli, scheduling e molto altro.
            </p>

            <a href="{app_url}" style="display:inline-block;padding:14px 28px;background:#7c3aed;color:#fff;text-decoration:none;border-radius:10px;font-weight:700;font-size:15px;">
                Vai alla Dashboard →
            </a>

            <p style="color:#44435a;font-size:11px;margin-top:28px;border-top:1px solid rgba(255,255,255,0.08);padding-top:16px;">
                Content AI Generator — AI Content Pipeline<br>
                Contatto: giovanni.mavilla.grz@gmail.com
            </p>
        </div>
        """,
    )


def send_limit_reached_email(email: str, name: str, plan: str) -> bool:
    """Send notification when user reaches their generation limit."""
    app_url = os.getenv("APP_URL", "https://content-ai-generator-1.onrender.com")

    if plan == "free":
        limit_msg = "hai raggiunto le <strong>10 generazioni gratuite</strong> incluse nel piano Free"
        upgrade_msg = """
            <p style="font-size:14px;line-height:1.6;">Con il piano <strong style="color:#a78bfa;">Pro</strong> a €29/mese ottieni:</p>
            <ul style="font-size:13px;line-height:1.8;padding-left:20px;color:#ccc;">
                <li><strong>50 generazioni</strong> al mese</li>
                <li>Tutte le <strong>5 piattaforme</strong> (LinkedIn, Instagram, Twitter, Newsletter, Video)</li>
                <li>Caroselli, scheduling, feedback AI e molto altro</li>
            </ul>
        """
    else:
        limit_msg = "hai raggiunto il <strong>limite mensile di generazioni</strong> del tuo piano"
        upgrade_msg = """
            <p style="font-size:14px;line-height:1.6;">Passa al piano <strong style="color:#a78bfa;">Business</strong>
            a €79/mese per <strong>generazioni illimitate</strong> e supporto prioritario.</p>
        """

    return send_email(
        to=email,
        subject="Hai raggiunto il limite di generazioni 📊",
        html=f"""
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:32px;background:#000;color:#fff;border-radius:16px;border:1px solid rgba(255,255,255,0.1);">
            <h1 style="color:#f59e0b;font-size:22px;margin-bottom:8px;">Limite raggiunto</h1>
            <p style="color:#ccc;font-size:15px;margin-bottom:20px;">Ciao {name or 'Utente'}, {limit_msg}.</p>

            <div style="background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.3);border-radius:12px;padding:16px 20px;margin:20px 0;">
                {upgrade_msg}
            </div>

            <a href="{app_url}" style="display:inline-block;padding:14px 28px;background:#7c3aed;color:#fff;text-decoration:none;border-radius:10px;font-weight:700;font-size:15px;">
                Vedi i piani →
            </a>

            <p style="color:#44435a;font-size:11px;margin-top:28px;border-top:1px solid rgba(255,255,255,0.08);padding-top:16px;">
                Content AI Generator — AI Content Pipeline<br>
                Contatto: giovanni.mavilla.grz@gmail.com
            </p>
        </div>
        """,
    )


def send_subscription_email(email: str, name: str, plan: str) -> bool:
    """Send subscription confirmation email."""
    plan_name = {"pro": "Pro", "business": "Business"}.get(plan, plan)
    return send_email(
        to=email,
        subject=f"Piano {plan_name} attivato! ✨",
        html=f"""
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
            <h1 style="color:#7c3aed;">Piano {plan_name} attivato!</h1>
            <p>Ciao {name or 'Utente'},</p>
            <p>Il tuo piano <strong>{plan_name}</strong> è ora attivo.
            Hai accesso a tutte le funzionalità incluse nel tuo piano.</p>
            <p>Buona creazione di contenuti!</p>
            <p style="color:#999;font-size:12px;margin-top:24px;">
                Content Dashboard — AI Content Pipeline
            </p>
        </div>
        """,
    )
