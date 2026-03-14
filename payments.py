"""Payments module — Stripe integration for subscriptions.

Provides:
- Stripe Checkout session creation
- Webhook event handling (subscription lifecycle)
- Customer portal for self-service billing
- Plan limits and feature gating
"""

import os
import time

import stripe
from flask import request, jsonify, g


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

stripe.api_key = STRIPE_SECRET_KEY

# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------

# Maps plan name → limits & features
# Free plan uses a LIFETIME cap (not monthly).  Pro/Business are monthly.
PLANS = {
    "free": {
        "name": "Free",
        "price_monthly": 0,
        "generations_per_month": 0,      # not used — see generations_lifetime
        "generations_lifetime": 10,      # 10 total generations ever
        "platforms": ["linkedin", "newsletter"],
        "features": [
            "10 generazioni totali",
            "LinkedIn + Newsletter",
            "RSS feed (max 5)",
            "Storico sessioni (ultime 10)",
        ],
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 29,
        "generations_per_month": 50,
        "generations_lifetime": -1,      # no lifetime cap
        "platforms": ["linkedin", "instagram", "twitter", "newsletter", "video_script"],
        "features": [
            "50 generazioni/mese",
            "Tutte le 5 piattaforme",
            "RSS illimitati + Web Search",
            "Feedback & prompt enrichment",
            "Carousel generator",
            "Scheduling & notifiche push",
            "Storico sessioni illimitato",
            "Smart Brief AI",
        ],
    },
    "business": {
        "name": "Business",
        "price_monthly": 79,
        "generations_per_month": -1,     # unlimited
        "generations_lifetime": -1,      # no lifetime cap
        "platforms": ["linkedin", "instagram", "twitter", "newsletter", "video_script"],
        "features": [
            "Generazioni illimitate",
            "Tutte le 5 piattaforme",
            "API keys personalizzate",
            "Pipeline monitoring avanzato",
            "Supporto prioritario",
            "Tutto ciò che è incluso in Pro",
        ],
    },
}

# Stripe Price IDs — set these after creating products in Stripe Dashboard
# Format: price_xxx for monthly recurring prices
STRIPE_PRICE_IDS = {
    "pro": os.getenv("STRIPE_PRICE_PRO", ""),
    "business": os.getenv("STRIPE_PRICE_BUSINESS", ""),
}


# ---------------------------------------------------------------------------
# Plan limits & gating
# ---------------------------------------------------------------------------

def get_plan_limits(plan: str) -> dict:
    """Return limits for a given plan."""
    return PLANS.get(plan, PLANS["free"])


def check_generation_limit(user_id: str, plan: str) -> dict:
    """Check if user can generate content based on their plan limits.

    Uses actual generation counts (tracked per API call), NOT session counts.

    Free plan  → lifetime cap (10 generations total, ever).
    Pro plan   → monthly cap (50 per calendar month).
    Business   → unlimited.

    Returns {"allowed": bool, "used": int, "limit": int,
             "limit_type": "lifetime"|"monthly"|"unlimited", "plan": str}
    """
    import db

    limits = get_plan_limits(plan)
    max_monthly = limits.get("generations_per_month", 0)
    max_lifetime = limits.get("generations_lifetime", -1)

    # ── Unlimited (Business) ─────────────────────────────
    if max_monthly == -1:
        return {"allowed": True, "used": 0, "limit": -1,
                "limit_type": "unlimited", "plan": plan}

    counts = db.get_generation_counts(user_id)

    # ── Lifetime cap (Free) ──────────────────────────────
    if max_lifetime > 0:
        return {
            "allowed": counts["lifetime"] < max_lifetime,
            "used": counts["lifetime"],
            "limit": max_lifetime,
            "limit_type": "lifetime",
            "plan": plan,
        }

    # ── Monthly cap (Pro) ────────────────────────────────
    return {
        "allowed": counts["monthly"] < max_monthly,
        "used": counts["monthly"],
        "limit": max_monthly,
        "limit_type": "monthly",
        "plan": plan,
    }


def check_platform_access(plan: str, platform: str) -> bool:
    """Check if a platform is available in the user's plan."""
    limits = get_plan_limits(plan)
    return platform in limits.get("platforms", [])


# ---------------------------------------------------------------------------
# Stripe customer management
# ---------------------------------------------------------------------------

def get_or_create_customer(user_id: str, email: str) -> str:
    """Get existing Stripe customer or create a new one.

    Returns the Stripe customer ID.
    """
    import db
    profile = db.get_profile(user_id)
    if profile and profile.get("stripe_customer_id"):
        return profile["stripe_customer_id"]

    # Create new Stripe customer
    customer = stripe.Customer.create(
        email=email,
        metadata={"user_id": user_id},
    )

    # Save customer ID to profile
    db.update_profile(user_id, {"stripe_customer_id": customer.id})

    return customer.id


# ---------------------------------------------------------------------------
# Checkout session
# ---------------------------------------------------------------------------

def create_checkout_session(user_id: str, email: str, plan: str, base_url: str) -> dict:
    """Create a Stripe Checkout session for a subscription.

    Returns {"url": "https://checkout.stripe.com/...", "session_id": "cs_..."}
    Raises RuntimeError on failure.
    """
    if plan not in STRIPE_PRICE_IDS or not STRIPE_PRICE_IDS[plan]:
        raise RuntimeError(f"Piano '{plan}' non configurato in Stripe. Contatta il supporto.")

    price_id = STRIPE_PRICE_IDS[plan]
    customer_id = get_or_create_customer(user_id, email)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}?payment=cancelled",
        metadata={"user_id": user_id, "plan": plan},
        subscription_data={
            "metadata": {"user_id": user_id, "plan": plan},
        },
        allow_promotion_codes=True,
    )

    return {"url": session.url, "session_id": session.id}


# ---------------------------------------------------------------------------
# Customer portal
# ---------------------------------------------------------------------------

def create_portal_session(user_id: str, email: str, base_url: str) -> dict:
    """Create a Stripe Customer Portal session for self-service billing.

    Returns {"url": "https://billing.stripe.com/..."}
    """
    customer_id = get_or_create_customer(user_id, email)

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=base_url,
    )

    return {"url": session.url}


# ---------------------------------------------------------------------------
# Webhook processing
# ---------------------------------------------------------------------------

def verify_webhook(payload: bytes, sig_header: str) -> dict | None:
    """Verify Stripe webhook signature and return the event.

    Returns None if verification fails.
    """
    if not STRIPE_WEBHOOK_SECRET:
        # No webhook secret configured
        if os.getenv("FLASK_ENV") == "production":
            return None  # NEVER accept unverified webhooks in production
        # Dev-only fallback (skip verification)
        try:
            return stripe.Event.construct_from(
                stripe.util.json.loads(payload), stripe.api_key
            )
        except Exception:
            return None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        return event
    except stripe.error.SignatureVerificationError:
        return None
    except Exception:
        return None


def handle_webhook_event(event: dict) -> dict:
    """Process a verified Stripe webhook event.

    Returns {"status": "ok", "action": "..."} or {"status": "ignored"}.
    """
    import db

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    # --- Checkout completed (new subscription) ---
    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(data)

    # --- Subscription updated ---
    if event_type == "customer.subscription.updated":
        return _handle_subscription_updated(data)

    # --- Subscription deleted (canceled) ---
    if event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(data)

    # --- Invoice payment succeeded (renewal) ---
    if event_type == "invoice.payment_succeeded":
        return _handle_invoice_paid(data)

    # --- Invoice payment failed ---
    if event_type == "invoice.payment_failed":
        return _handle_invoice_failed(data)

    return {"status": "ignored", "event_type": event_type}


def _find_user_by_customer(customer_id: str) -> str | None:
    """Find user_id by Stripe customer ID."""
    import db
    # Search profiles for the customer
    try:
        result = db._sb().table("profiles").select("id").eq(
            "stripe_customer_id", customer_id
        ).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception:
        pass
    return None


def _handle_checkout_completed(session: dict) -> dict:
    """Handle checkout.session.completed — activate subscription."""
    import db

    user_id = session.get("metadata", {}).get("user_id")
    plan = session.get("metadata", {}).get("plan", "pro")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not user_id:
        user_id = _find_user_by_customer(customer_id)
    if not user_id:
        return {"status": "error", "reason": "user_id not found"}

    # Fetch subscription details from Stripe
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        period_start = sub.current_period_start
        period_end = sub.current_period_end
        price_id = sub["items"]["data"][0]["price"]["id"] if sub.get("items") else ""
    except Exception:
        period_start = None
        period_end = None
        price_id = ""

    # Update subscription in DB
    from datetime import datetime, timezone
    sub_data = {
        "stripe_subscription_id": subscription_id,
        "stripe_price_id": price_id,
        "plan": plan,
        "status": "active",
        "cancel_at_period_end": False,
    }
    if period_start:
        sub_data["current_period_start"] = datetime.fromtimestamp(
            period_start, tz=timezone.utc
        ).isoformat()
    if period_end:
        sub_data["current_period_end"] = datetime.fromtimestamp(
            period_end, tz=timezone.utc
        ).isoformat()

    db.upsert_subscription(user_id, sub_data)

    # Update profile plan
    db.update_profile(user_id, {"plan": plan, "stripe_customer_id": customer_id})

    try:
        db.add_pipeline_log(user_id, "info", f"Subscription activated: {plan}")
    except Exception:
        pass

    return {"status": "ok", "action": "subscription_activated", "plan": plan}


def _handle_subscription_updated(subscription: dict) -> dict:
    """Handle customer.subscription.updated — plan change, renewal, etc."""
    import db
    from datetime import datetime, timezone

    subscription_id = subscription.get("id")
    customer_id = subscription.get("customer")
    status = subscription.get("status", "active")
    cancel_at_end = subscription.get("cancel_at_period_end", False)

    user_id = subscription.get("metadata", {}).get("user_id")
    plan = subscription.get("metadata", {}).get("plan", "pro")

    if not user_id:
        user_id = _find_user_by_customer(customer_id)
    if not user_id:
        return {"status": "error", "reason": "user_id not found"}

    period_start = subscription.get("current_period_start")
    period_end = subscription.get("current_period_end")

    sub_data = {
        "stripe_subscription_id": subscription_id,
        "plan": plan,
        "status": status,
        "cancel_at_period_end": cancel_at_end,
    }
    if period_start:
        sub_data["current_period_start"] = datetime.fromtimestamp(
            period_start, tz=timezone.utc
        ).isoformat()
    if period_end:
        sub_data["current_period_end"] = datetime.fromtimestamp(
            period_end, tz=timezone.utc
        ).isoformat()

    # Detect plan from price ID
    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id", "")
        sub_data["stripe_price_id"] = price_id
        # Reverse-lookup plan from price ID
        for p, pid in STRIPE_PRICE_IDS.items():
            if pid == price_id:
                plan = p
                sub_data["plan"] = plan
                break

    db.upsert_subscription(user_id, sub_data)
    db.update_profile(user_id, {"plan": plan})

    return {"status": "ok", "action": "subscription_updated", "plan": plan, "stripe_status": status}


def _handle_subscription_deleted(subscription: dict) -> dict:
    """Handle customer.subscription.deleted — revert to free."""
    import db

    customer_id = subscription.get("customer")
    user_id = subscription.get("metadata", {}).get("user_id")

    if not user_id:
        user_id = _find_user_by_customer(customer_id)
    if not user_id:
        return {"status": "error", "reason": "user_id not found"}

    db.upsert_subscription(user_id, {
        "plan": "free",
        "status": "canceled",
        "stripe_subscription_id": subscription.get("id"),
        "cancel_at_period_end": False,
    })
    db.update_profile(user_id, {"plan": "free"})

    try:
        db.add_pipeline_log(user_id, "info", "Subscription canceled — reverted to free plan")
    except Exception:
        pass

    return {"status": "ok", "action": "subscription_canceled"}


def _handle_invoice_paid(invoice: dict) -> dict:
    """Handle invoice.payment_succeeded — renewal confirmation."""
    import db
    from datetime import datetime, timezone

    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")

    user_id = _find_user_by_customer(customer_id)
    if not user_id:
        return {"status": "ignored", "reason": "user not found for renewal"}

    # Update period dates if subscription info available
    if subscription_id:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            sub_data = {
                "status": "active",
                "current_period_start": datetime.fromtimestamp(
                    sub.current_period_start, tz=timezone.utc
                ).isoformat(),
                "current_period_end": datetime.fromtimestamp(
                    sub.current_period_end, tz=timezone.utc
                ).isoformat(),
            }
            db.upsert_subscription(user_id, sub_data)
        except Exception:
            pass

    return {"status": "ok", "action": "invoice_paid"}


def _handle_invoice_failed(invoice: dict) -> dict:
    """Handle invoice.payment_failed — mark as past_due."""
    import db

    customer_id = invoice.get("customer")
    user_id = _find_user_by_customer(customer_id)
    if not user_id:
        return {"status": "ignored", "reason": "user not found"}

    db.upsert_subscription(user_id, {"status": "past_due"})

    try:
        db.add_pipeline_log(user_id, "warning", "Payment failed — subscription is past due")
    except Exception:
        pass

    return {"status": "ok", "action": "payment_failed_marked"}
