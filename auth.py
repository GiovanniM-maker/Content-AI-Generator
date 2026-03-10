"""Authentication module — Supabase Auth integration.

Provides:
- JWT token verification via Supabase JWKS
- Login / signup / logout helpers
- Flask decorator for protecting API routes
- Session token management
"""

import functools
import os
import time

import requests
from flask import request, jsonify, g

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# JWT secret from Supabase (derived from service key for HS256 verification)
# Supabase uses HS256 with the JWT secret from Dashboard → Settings → API → JWT Secret
_JWT_SECRET: str | None = None
_JWT_ALGORITHM = "HS256"


def _get_jwt_secret() -> str:
    """Get JWT secret. Supabase JWT secret = your project JWT secret from dashboard."""
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
        if not _JWT_SECRET:
            # Fallback: try to decode from service key (the secret is the signing key)
            # For production, always set SUPABASE_JWT_SECRET explicitly
            _JWT_SECRET = os.getenv("SUPABASE_SERVICE_KEY", "")
    return _JWT_SECRET


# ---------------------------------------------------------------------------
# Token extraction & verification
# ---------------------------------------------------------------------------

def _extract_token() -> str | None:
    """Extract JWT token from Authorization header or cookie."""
    # Check Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    # Check cookie fallback
    token = request.cookies.get("sb-access-token")
    if token:
        return token

    return None


def verify_token(token: str) -> dict | None:
    """Verify a Supabase JWT token and return the payload.

    Returns the decoded payload dict with user info, or None if invalid.
    Uses Supabase's GoTrue API to verify (most reliable method).
    """
    if not token:
        return None

    try:
        # Use Supabase GoTrue API to verify token and get user
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            user_data = resp.json()
            return {
                "sub": user_data.get("id"),
                "email": user_data.get("email"),
                "role": user_data.get("role", "authenticated"),
                "user_metadata": user_data.get("user_metadata", {}),
            }
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Flask decorator
# ---------------------------------------------------------------------------

def require_auth(f):
    """Decorator: require valid Supabase JWT token.

    Sets g.user_id and g.user_email on success.
    Returns 401 JSON error on failure.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({"error": "Authentication required", "code": "NO_TOKEN"}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({"error": "Invalid or expired token", "code": "INVALID_TOKEN"}), 401

        g.user_id = payload["sub"]
        g.user_email = payload.get("email", "")
        g.user_role = payload.get("role", "authenticated")
        g.user_metadata = payload.get("user_metadata", {})
        g.access_token = token

        return f(*args, **kwargs)
    return decorated


def optional_auth(f):
    """Decorator: try to extract auth but don't require it.

    If a valid token is present, sets g.user_id etc.
    If not, g.user_id will be None (allows fallback to DEFAULT_USER_ID).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        if token:
            payload = verify_token(token)
            if payload:
                g.user_id = payload["sub"]
                g.user_email = payload.get("email", "")
                g.user_role = payload.get("role", "authenticated")
                g.user_metadata = payload.get("user_metadata", {})
                g.access_token = token
            else:
                g.user_id = None
                g.user_email = None
                g.access_token = None
        else:
            g.user_id = None
            g.user_email = None
            g.access_token = None
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Auth API helpers (called from app.py routes)
# ---------------------------------------------------------------------------

def signup(email: str, password: str, full_name: str = "") -> dict:
    """Create a new user via Supabase GoTrue signup.

    Returns dict with 'user' and 'session' keys on success.
    Raises RuntimeError on failure.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/signup",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={
            "email": email,
            "password": password,
            "data": {"full_name": full_name},
        },
        timeout=15,
    )

    data = resp.json()

    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or data.get("error_description") or str(data)
        # Map common Supabase error messages to Italian
        error_map = {
            "User already registered": "Questo indirizzo email è già registrato",
            "Password should be at least 6 characters": "La password deve avere almeno 6 caratteri",
            "Unable to validate email address": "Indirizzo email non valido",
            "Signup requires a valid password": "Inserisci una password valida",
        }
        for en_msg, it_msg in error_map.items():
            if en_msg.lower() in msg.lower():
                raise RuntimeError(it_msg)
        raise RuntimeError(msg)

    return data


def login(email: str, password: str) -> dict:
    """Authenticate user and return session tokens.

    Returns dict with access_token, refresh_token, user info.
    Raises RuntimeError on failure.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={
            "email": email,
            "password": password,
        },
        timeout=15,
    )

    data = resp.json()

    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or data.get("error_description") or str(data)
        error_map = {
            "Invalid login credentials": "Email o password non corretti",
            "Email not confirmed": "Conferma il tuo indirizzo email prima di accedere",
        }
        for en_msg, it_msg in error_map.items():
            if en_msg.lower() in msg.lower():
                raise RuntimeError(it_msg)
        raise RuntimeError(msg)

    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in", 3600),
        "token_type": data.get("token_type", "bearer"),
        "user": {
            "id": data.get("user", {}).get("id"),
            "email": data.get("user", {}).get("email"),
            "full_name": data.get("user", {}).get("user_metadata", {}).get("full_name", ""),
        },
    }


def refresh_session(refresh_token: str) -> dict:
    """Refresh an expired access token.

    Returns new access_token and refresh_token.
    Raises RuntimeError on failure.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={
            "refresh_token": refresh_token,
        },
        timeout=15,
    )

    data = resp.json()

    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or data.get("error_description") or str(data)
        raise RuntimeError(msg)

    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in", 3600),
    }


def logout_server(access_token: str) -> bool:
    """Invalidate a session on the server side."""
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/logout",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": SUPABASE_ANON_KEY,
            },
            timeout=10,
        )
        return resp.status_code < 400
    except Exception:
        return False


def get_user_from_token(access_token: str) -> dict | None:
    """Get full user profile from a valid access token."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": SUPABASE_ANON_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None
