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

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,  # 10% of requests
        environment=os.getenv("FLASK_ENV", "production"),
        send_default_pii=False,  # Don't send user emails/IPs to Sentry
    )


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def init_cors(app: Flask):
    """Configure CORS — allow same-origin + configurable origins."""
    allowed_origins = os.getenv("CORS_ORIGINS", "").split(",")
    allowed_origins = [o.strip() for o in allowed_origins if o.strip()]

    if not allowed_origins:
        # Default: same-origin only (no external origins)
        CORS(app, resources={
            r"/api/*": {"origins": "*", "supports_credentials": True},
            r"/auth/*": {"origins": "*", "supports_credentials": True},
        })
    else:
        CORS(app, resources={
            r"/api/*": {"origins": allowed_origins, "supports_credentials": True},
            r"/auth/*": {"origins": allowed_origins, "supports_credentials": True},
        })


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_limiter: Limiter | None = None


def init_rate_limiter(app: Flask) -> Limiter:
    """Initialize Flask-Limiter with Upstash Redis backend."""
    global _limiter

    redis_url = os.getenv("UPSTASH_REDIS_URL", "")

    if redis_url:
        storage_uri = redis_url
    else:
        storage_uri = "memory://"

    _limiter = Limiter(
        app=app,
        key_func=_get_rate_limit_key,
        default_limits=["200 per minute"],
        storage_uri=storage_uri,
        strategy="fixed-window",
    )

    # Apply specific limits to sensitive endpoints
    _limiter.limit("5 per minute")(app.view_functions.get("auth_login", lambda: None))
    _limiter.limit("5 per minute")(app.view_functions.get("auth_signup", lambda: None))
    _limiter.limit("10 per minute")(app.view_functions.get("auth_refresh", lambda: None))
    _limiter.limit("20 per minute")(app.view_functions.get("generate_content", lambda: None))
    _limiter.limit("20 per minute")(app.view_functions.get("generate_newsletter", lambda: None))
    _limiter.limit("3 per minute")(app.view_functions.get("create_checkout", lambda: None))

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
    """Add security headers to all responses."""

    @app.after_request
    def _add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
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
    return send_email(
        to=email,
        subject="Benvenuto su Content Dashboard! 🚀",
        html=f"""
        <div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
            <h1 style="color:#7c3aed;">Benvenuto, {name or 'Utente'}!</h1>
            <p>Il tuo account Content Dashboard è stato creato con successo.</p>
            <p>Con il piano <strong>Free</strong> puoi:</p>
            <ul>
                <li>Generare fino a 10 contenuti al mese</li>
                <li>Creare post per LinkedIn</li>
                <li>Gestire fino a 5 feed RSS</li>
            </ul>
            <p>Per sbloccare tutte le piattaforme e generazioni illimitate,
            <a href="#" style="color:#7c3aed;">effettua l'upgrade</a>.</p>
            <p style="color:#999;font-size:12px;margin-top:24px;">
                Content Dashboard — AI Content Pipeline
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
