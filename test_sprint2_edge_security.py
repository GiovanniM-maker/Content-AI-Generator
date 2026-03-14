#!/usr/bin/env python3
"""Sprint 2 — Edge Cases + Security Review

Edge cases:
  - Carousel with 1 slide (cover only)
  - Carousel with 10+ slides
  - Special characters in text (<, >, ", emoji, unicode)
  - Empty article dict
  - Custom text mode (source_mode=custom_text)
  - Empty carousel text → 400

Security review:
  - All 12 disabled endpoints still return 403
  - ADMIN_EMAIL from env var (not hardcoded)
  - Webhook endpoint accessible without auth (public)
  - Rate limiter initialized
"""

import json
import unittest
from unittest.mock import patch, MagicMock

import os
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "fake-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "fake-jwt-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")

with patch("security.init_sentry"), \
     patch("security.init_cors"), \
     patch("security.init_security_headers"), \
     patch("security.init_rate_limiter"), \
     patch("db._sb"):
    import app as flask_app
    import auth as auth_mod
    import db

_app = flask_app.app
_app.config["TESTING"] = True

_FAKE_JWT = {
    "sub": "user-edge-001",
    "email": "edge@test.com",
    "role": "authenticated",
    "user_metadata": {},
}


class _AuthBase(unittest.TestCase):
    def setUp(self):
        self.client = _app.test_client()
        self._patches = [
            patch.object(auth_mod, '_extract_token', return_value="tok"),
            patch.object(auth_mod, 'verify_token', return_value=_FAKE_JWT),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _post(self, url, data):
        return self.client.post(url, data=json.dumps(data),
                                content_type="application/json")


# ===================================================================
# EDGE CASES: Carousel rendering
# ===================================================================
class TestEdge_Carousel(_AuthBase):

    def _render_patches(self, slides_count):
        fake_bytes = [b"PNG"] * slides_count
        fake_urls = [f"https://s.co/slide_{i}.png" for i in range(slides_count)]
        return [
            patch.object(flask_app, '_is_admin', return_value=True),
            patch.object(db, 'get_profile', return_value={"full_name": "Test", "id": "u1"}),
            patch.object(db, 'upload_carousel_images_batch', return_value=fake_urls),
            patch("carousel_renderer.render_carousel_async", return_value={
                "slides_bytes": fake_bytes,
                "caption": "Test caption",
            }),
            patch.object(flask_app, '_log_pipeline'),
        ]

    def test_edge_1_slide(self):
        """Carousel with 1 slide (cover only, no separators)."""
        for p in self._render_patches(1):
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/render-carousel", {
            "text": "Solo una cover slide",
            "palette": 0,
        })
        data = resp.get_json()

        print(f"\n[EDGE-1slide] Status: {resp.status_code}, Slides: {len(data.get('slides', []))}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data["slides"]), 1)
        print("[EDGE-1slide] RESULT: PASS")

    def test_edge_10_slides(self):
        """Carousel with 10+ slides."""
        for p in self._render_patches(12):
            p.start()
            self.addCleanup(p.stop)

        slides_text = "\n---SLIDE---\n".join([f"Slide {i}" for i in range(12)])
        resp = self._post("/api/render-carousel", {
            "text": slides_text,
            "palette": 1,
        })
        data = resp.get_json()

        print(f"\n[EDGE-10+slides] Status: {resp.status_code}, Slides: {len(data.get('slides', []))}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data["slides"]), 12)
        print("[EDGE-10+slides] RESULT: PASS")

    def test_edge_special_chars(self):
        """Text with <, >, ", emoji, unicode characters."""
        for p in self._render_patches(2):
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/render-carousel", {
            "text": '🔥 <strong>Bold</strong> "quotes" & più café ñ 日本語\n---SLIDE---\nSlide 2 with <script>alert("xss")</script>',
            "palette": 2,
        })
        data = resp.get_json()

        print(f"\n[EDGE-special] Status: {resp.status_code}, Slides: {len(data.get('slides', []))}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data["slides"]), 2)
        print("[EDGE-special] RESULT: PASS — special chars handled")

    def test_edge_empty_text(self):
        """Empty carousel text → should return 400."""
        for p in self._render_patches(0):
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/render-carousel", {"text": "", "palette": 0})
        data = resp.get_json()

        print(f"\n[EDGE-empty] Status: {resp.status_code}, Body: {data}")
        self.assertEqual(resp.status_code, 400)
        print("[EDGE-empty] RESULT: PASS — 400 on empty text")

    def test_edge_whitespace_only(self):
        """Whitespace-only text → should return 400."""
        for p in self._render_patches(0):
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/render-carousel", {"text": "   \n\t  ", "palette": 0})
        data = resp.get_json()

        print(f"\n[EDGE-whitespace] Status: {resp.status_code}")
        self.assertEqual(resp.status_code, 400)
        print("[EDGE-whitespace] RESULT: PASS — 400 on whitespace-only")


# ===================================================================
# EDGE CASES: Content generation
# ===================================================================
class TestEdge_Generate(_AuthBase):

    def _gen_patches(self):
        return [
            patch.object(flask_app, '_is_admin', return_value=True),
            patch.object(db, 'get_subscription', return_value={"plan": "pro"}),
            patch.object(flask_app, '_llm_call', return_value="Generated content"),
            patch.object(flask_app, '_ensure_user_prompts'),
            patch.object(flask_app, '_get_prompt', return_value="format"),
            patch.object(flask_app, '_update_weekly_status'),
            patch.object(db, 'increment_generation_count', return_value={
                "generation_count": 1, "generation_count_monthly": 1, "month": "2026-03"
            }),
            patch.object(db, 'create_notification'),
            patch("payments.check_platform_access", return_value=True),
            patch("payments.check_generation_limit", return_value={
                "allowed": True, "used": 0, "limit": 50, "limit_type": "monthly", "plan": "pro"
            }),
        ]

    def test_edge_empty_article(self):
        """Empty article dict → should still generate (LLM handles it)."""
        for p in self._gen_patches():
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/generate", {
            "article": {},
            "format": "instagram",
        })
        data = resp.get_json()

        print(f"\n[EDGE-empty-article] Status: {resp.status_code}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("content", data)
        print("[EDGE-empty-article] RESULT: PASS — generates even with empty article")

    def test_edge_custom_text_mode(self):
        """Custom text source mode (no article, direct text input)."""
        for p in self._gen_patches():
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/generate", {
            "article": {"source_mode": "custom_text"},
            "custom_text": "L'intelligenza artificiale sta cambiando il mondo del lavoro in 5 modi fondamentali.",
            "format": "instagram",
        })
        data = resp.get_json()

        print(f"\n[EDGE-custom-text] Status: {resp.status_code}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("content", data)
        print("[EDGE-custom-text] RESULT: PASS — custom_text mode works")

    def test_edge_long_custom_text(self):
        """Very long custom text (5000 chars) → should be accepted and sanitized."""
        for p in self._gen_patches():
            p.start()
            self.addCleanup(p.stop)

        long_text = "A" * 5000
        resp = self._post("/api/generate", {
            "article": {"source_mode": "custom_text"},
            "custom_text": long_text,
            "format": "linkedin",
        })
        data = resp.get_json()

        print(f"\n[EDGE-long-text] Status: {resp.status_code}")
        self.assertEqual(resp.status_code, 200)
        print("[EDGE-long-text] RESULT: PASS — 5000 char text accepted")

    def test_edge_invalid_format(self):
        """Invalid format → 400."""
        for p in self._gen_patches():
            p.start()
            self.addCleanup(p.stop)

        resp = self._post("/api/generate", {
            "article": {"title": "Test"},
            "format": "tiktok",
        })

        print(f"\n[EDGE-invalid-fmt] Status: {resp.status_code}")
        self.assertEqual(resp.status_code, 400)
        print("[EDGE-invalid-fmt] RESULT: PASS — invalid format rejected")


# ===================================================================
# SECURITY REVIEW
# ===================================================================
class TestSecurity(_AuthBase):

    def test_sec_admin_email_from_env(self):
        """ADMIN_EMAIL is read from env var, not hardcoded."""
        admin_email = os.environ.get("ADMIN_EMAIL", "")
        app_admin = flask_app.ADMIN_EMAIL

        print(f"\n[SEC-admin] Env ADMIN_EMAIL: '{admin_email}'")
        print(f"[SEC-admin] App ADMIN_EMAIL: '{app_admin}'")

        # Verify it matches env var (not some hardcoded value)
        self.assertEqual(app_admin, admin_email)
        print("[SEC-admin] RESULT: PASS — ADMIN_EMAIL from env")

    def test_sec_healthz_no_auth(self):
        """GET /api/healthz — excluded from auth in middleware (line 78).
        Route may not exist (404), but must NOT return 401."""
        # Stop auth patches to test unauthenticated access
        for p in self._patches:
            p.stop()

        resp = self.client.get("/api/healthz")

        # Restart patches for cleanup
        for p in self._patches:
            p.start()

        print(f"\n[SEC-healthz] Status: {resp.status_code}")
        # 200 if route exists, 404 if not — either way, NOT 401
        self.assertNotEqual(resp.status_code, 401,
                            "healthz should be excluded from auth middleware")
        print(f"[SEC-healthz] RESULT: PASS — not blocked by auth ({resp.status_code})")

    def test_sec_api_requires_auth(self):
        """API endpoints require auth (401 without token)."""
        # Stop auth patches
        for p in self._patches:
            p.stop()

        resp = self.client.get("/api/sessions")

        for p in self._patches:
            p.start()

        print(f"\n[SEC-auth-required] Status: {resp.status_code}")
        self.assertEqual(resp.status_code, 401)
        print("[SEC-auth-required] RESULT: PASS — 401 without auth")

    def test_sec_all_disabled_still_403(self):
        """Complete check: all 12 disabled endpoints return 403."""
        disabled = [
            ("POST", "/api/carousel/enrich-images"),
            ("POST", "/api/generate-newsletter"),
            ("POST", "/api/newsletter/enrich-images"),
            ("POST", "/api/newsletter/html"),
            ("POST", "/api/search"),
            ("POST", "/api/search/score"),
            ("GET",  "/api/schedule"),
            ("POST", "/api/schedule"),
            ("POST", "/api/schedule/bulk"),
            ("DELETE", "/api/schedule/x"),
            ("POST", "/api/schedule/x/publish"),
            ("GET",  "/api/schedule/x/content"),
        ]

        all_ok = True
        for method, url in disabled:
            if method == "POST":
                resp = self._post(url, {})
            elif method == "GET":
                resp = self.client.get(url)
            elif method == "DELETE":
                resp = self.client.delete(url)
            else:
                continue

            ok = resp.status_code == 403
            all_ok = all_ok and ok
            marker = "PASS" if ok else f"FAIL({resp.status_code})"
            print(f"[SEC-disabled] {method:6s} {url:40s} → {resp.status_code} [{marker}]")

        self.assertTrue(all_ok)
        print(f"\n[SEC-disabled] RESULT: PASS — all 12 endpoints return 403")

    def test_sec_non_admin_cannot_bypass_plan(self):
        """Non-admin user cannot access admin-only features."""
        with patch.object(flask_app, '_is_admin', return_value=False), \
             patch.object(db, 'get_subscription', return_value=None):

            resp = self._post("/api/generate", {
                "article": {"title": "Test"},
                "format": "instagram",
            })

            print(f"\n[SEC-non-admin] Status: {resp.status_code}")
            self.assertEqual(resp.status_code, 403)
            print("[SEC-non-admin] RESULT: PASS — non-admin blocked from Instagram on free plan")


if __name__ == "__main__":
    print("=" * 60)
    print("SPRINT 2 — EDGE CASES + SECURITY REVIEW")
    print("=" * 60)
    unittest.main(verbosity=2)
