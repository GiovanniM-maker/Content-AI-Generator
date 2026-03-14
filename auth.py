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
    """Extract JWT token from Authorization header, query param, or cookie.

    Priority order:
    1. Authorization: Bearer <token> header (standard API calls)
    2. ?token=<token> query parameter (for EventSource/SSE which can't set headers)
    3. sb-access-token cookie (legacy fallback)
    """
    # Check Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    # Check query parameter (needed for EventSource/SSE which cannot set headers)
    token = request.args.get("token")
    if token:
        return token

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
            "Email rate limit exceeded": "Troppi tentativi. Riprova tra qualche minuto",
        }
        for en_msg, it_msg in error_map.items():
            if en_msg.lower() in msg.lower():
                raise RuntimeError(it_msg)
        raise RuntimeError("Errore durante la registrazione. Riprova.")

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
            "Email rate limit exceeded": "Troppi tentativi. Riprova tra qualche minuto",
        }
        for en_msg, it_msg in error_map.items():
            if en_msg.lower() in msg.lower():
                raise RuntimeError(it_msg)
        raise RuntimeError("Errore di autenticazione. Riprova.")

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
        raise RuntimeError("Sessione scaduta")

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


# ---------------------------------------------------------------------------
# Password recovery
# ---------------------------------------------------------------------------

def send_password_reset(email: str) -> bool:
    """Send password reset email via Supabase GoTrue /recover endpoint.

    Returns True if the request was accepted (regardless of whether the email exists
    — prevents email enumeration).
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/recover",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"email": email},
        timeout=15,
    )
    # Supabase returns 200 even if email doesn't exist (anti-enumeration)
    return resp.status_code < 400


def update_user_password(access_token: str, new_password: str) -> bool:
    """Update user password using a valid access token (from reset link or logged-in user).

    Returns True on success, raises RuntimeError on failure.
    """
    resp = requests.put(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"password": new_password},
        timeout=15,
    )
    if resp.status_code >= 400:
        data = resp.json()
        msg = data.get("msg") or data.get("message") or "Errore aggiornamento password"
        error_map = {
            "Password should be at least 6 characters": "La password deve avere almeno 6 caratteri",
            "New password should be different from the old password": "La nuova password deve essere diversa dalla precedente",
        }
        for en, it in error_map.items():
            if en.lower() in msg.lower():
                raise RuntimeError(it)
        raise RuntimeError("Errore nell'aggiornamento della password.")
    return True


# ---------------------------------------------------------------------------
# Magic link (passwordless login)
# ---------------------------------------------------------------------------

def send_magic_link(email: str) -> bool:
    """Send a magic link for passwordless login.

    Returns True if accepted.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/magiclink",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"email": email},
        timeout=15,
    )
    return resp.status_code < 400


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------

def get_oauth_url(provider: str, redirect_to: str) -> str:
    """Build the Supabase OAuth authorization URL for a given provider.

    Returns the full URL the client should redirect/navigate to.
    """
    return (
        f"{SUPABASE_URL}/auth/v1/authorize"
        f"?provider={provider}"
        f"&redirect_to={redirect_to}"
    )


def exchange_code_for_session(code: str) -> dict:
    """Exchange an OAuth/magic-link auth code for a session.

    The code comes from the redirect URL after OAuth or email link callback.
    Returns dict with access_token, refresh_token, user.
    Raises RuntimeError on failure.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"auth_code": code},
        timeout=15,
    )
    data = resp.json()

    if resp.status_code >= 400:
        # Fallback: try the verify endpoint for OTP-style codes
        resp2 = requests.post(
            f"{SUPABASE_URL}/auth/v1/verify",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={"type": "magiclink", "token": code},
            timeout=15,
        )
        data = resp2.json()
        if resp2.status_code >= 400:
            raise RuntimeError("Codice non valido o scaduto.")

    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in", 3600),
        "user": {
            "id": data.get("user", {}).get("id"),
            "email": data.get("user", {}).get("email"),
            "full_name": data.get("user", {}).get("user_metadata", {}).get("full_name", ""),
        },
    }


# ---------------------------------------------------------------------------
# MFA / TOTP
# ---------------------------------------------------------------------------

SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


def mfa_enroll(access_token: str) -> dict:
    """Enroll a new TOTP factor for the authenticated user.

    Returns dict with: id, type, totp.qr_code, totp.secret, totp.uri
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/factors",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"factor_type": "totp", "friendly_name": "Content Dashboard"},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or "Errore nell'attivazione 2FA"
        raise RuntimeError(msg)
    return data


def mfa_challenge(access_token: str, factor_id: str) -> dict:
    """Create an MFA challenge for the given factor.

    Returns dict with: id (challenge_id)
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/factors/{factor_id}/challenge",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError("Errore nella creazione della sfida 2FA")
    return data


def mfa_verify(access_token: str, factor_id: str, challenge_id: str, code: str) -> dict:
    """Verify a TOTP code for an MFA challenge.

    Returns new session tokens on success.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/factors/{factor_id}/verify",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"challenge_id": challenge_id, "code": code},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code >= 400:
        msg = data.get("msg") or data.get("message") or "Codice non valido"
        raise RuntimeError(msg)
    return data


def mfa_unenroll(access_token: str, factor_id: str) -> bool:
    """Remove an MFA factor.

    Returns True on success.
    """
    resp = requests.delete(
        f"{SUPABASE_URL}/auth/v1/factors/{factor_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": SUPABASE_ANON_KEY,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise RuntimeError("Errore nella disattivazione 2FA")
    return True


def mfa_list_factors(access_token: str) -> list:
    """List the user's MFA factors."""
    user = get_user_from_token(access_token)
    if not user:
        return []
    factors = user.get("factors", [])
    return [f for f in factors if f.get("status") == "verified"]


# ---------------------------------------------------------------------------
# Duplicate signup detection
# ---------------------------------------------------------------------------

def check_user_exists(email: str) -> bool:
    """Check if a user with this email already exists using Supabase Admin API.

    Uses the service role key to query the admin endpoint.
    Returns True if user exists, False otherwise.
    """
    if not SUPABASE_SERVICE_KEY:
        return False  # Can't check without service key

    try:
        # Use Supabase admin API to list users filtered by email
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "apikey": SUPABASE_ANON_KEY,
            },
            params={"filter": email},  # Not always supported; we'll parse manually
            timeout=15,
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        users = data.get("users", [])
        for u in users:
            if u.get("email", "").lower() == email.lower():
                return True
        return False
    except Exception:
        return False
