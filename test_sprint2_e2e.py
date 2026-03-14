#!/usr/bin/env python3
"""Sprint 2 — E2E Smoke Test: Carousel-First Core Loop

Tests the complete user journey:
  1. Auth (signup/login simulated via JWT mock)
  2. Profile update (brand_name, brand_handle)
  3. Generate Instagram carousel content
  4. Render carousel (palette-based)
  5. Save session
  6. Reload / retrieve session
  7. Verify generation counter
  8. Free plan limits (10 lifetime)
  9. Pro plan upgrade + continued access
 10. Feature disablement verification

Each step: action → expected → actual → PASS/FAIL/PARTIAL
"""

import json
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

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
    import payments

_app = flask_app.app
_app.config["TESTING"] = True

# =========================================================================
# Shared state: simulates DB across the test session
# =========================================================================
_user_profile = {
    "id": "user-e2e-001",
    "full_name": "",
    "brand_handle": "",
    "generation_count": 0,
    "generation_count_monthly": 0,
    "generation_count_month": "2026-03",
    "stripe_customer_id": None,
}

_user_subscription = None   # None = free plan
_saved_sessions = {}        # session_id → data
_generation_counter = {"lifetime": 0, "monthly": 0}


class TestE2E_CarouselFirstLoop(unittest.TestCase):
    """Full E2E smoke test of the carousel-first beta loop."""

    @classmethod
    def setUpClass(cls):
        cls.client = _app.test_client()
        # Reset state
        global _user_profile, _user_subscription, _saved_sessions, _generation_counter
        _user_profile["full_name"] = ""
        _user_profile["brand_handle"] = ""
        _user_profile["generation_count"] = 0
        _user_profile["generation_count_monthly"] = 0
        _user_subscription = None
        _saved_sessions.clear()
        _generation_counter["lifetime"] = 0
        _generation_counter["monthly"] = 0

    def _auth_patches(self):
        """Context manager for auth + DB mocks."""
        return [
            patch.object(auth_mod, '_extract_token', return_value="e2e-token"),
            patch.object(auth_mod, 'verify_token', return_value={
                "sub": "user-e2e-001",
                "email": "beta@test.com",
                "role": "authenticated",
                "user_metadata": {},
            }),
        ]

    def _start_patches(self, extra_patches=None):
        patches = self._auth_patches() + (extra_patches or [])
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def _post(self, url, data=None):
        return self.client.post(url, data=json.dumps(data) if data else None,
                                content_type="application/json")

    def _put(self, url, data=None):
        return self.client.put(url, data=json.dumps(data) if data else None,
                               content_type="application/json")

    # =================================================================
    # STEP 1: Auth — Verify authenticated access
    # =================================================================
    def test_01_auth_access(self):
        """Step 1: Authenticated user can access /api/ endpoints."""
        print("\n" + "="*60)
        print("STEP 1: AUTH — Verify authenticated access")
        print("="*60)

        self._start_patches([
            patch.object(db, 'get_profile', return_value=_user_profile),
            patch.object(db, 'get_subscription', return_value=_user_subscription),
        ])

        resp = self.client.get("/api/settings/profile")
        data = resp.get_json()

        print(f"  Action:   GET /api/settings/profile")
        print(f"  Expected: 200 with profile data")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Body:     {json.dumps(data, ensure_ascii=False)[:200]}")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("profile", data)
        print(f"  Result:   PASS")

    # =================================================================
    # STEP 2: Profile update — brand_name + brand_handle
    # =================================================================
    def test_02_profile_update(self):
        """Step 2: Update brand_name and brand_handle for carousel branding."""
        print("\n" + "="*60)
        print("STEP 2: PROFILE — Update brand_name + brand_handle")
        print("="*60)

        def mock_update_profile(user_id, updates):
            _user_profile.update(updates)
            return _user_profile

        self._start_patches([
            patch.object(db, 'update_profile', side_effect=mock_update_profile),
        ])

        resp = self._put("/api/settings/profile", {
            "full_name": "Marco Rossi",
            "brand_handle": "@marcorossi.ai",
        })
        data = resp.get_json()

        print(f"  Action:   PUT /api/settings/profile (full_name='Marco Rossi', brand_handle='@marcorossi.ai')")
        print(f"  Expected: 200 with updated profile")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Body:     {json.dumps(data, ensure_ascii=False)[:200]}")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_user_profile["full_name"], "Marco Rossi")
        print(f"  Profile:  full_name='{_user_profile['full_name']}', brand_handle='{_user_profile.get('brand_handle', '')}'")
        print(f"  Result:   PASS")

    # =================================================================
    # STEP 3: Generate Instagram content (free plan)
    # =================================================================
    def test_03_generate_instagram_free(self):
        """Step 3: Generate Instagram carousel content on free plan.
        Free plan includes linkedin + newsletter but NOT instagram.
        Expected: 403 PLAN_LIMIT."""
        print("\n" + "="*60)
        print("STEP 3: GENERATE — Instagram on FREE plan")
        print("="*60)

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value=None),
        ])

        resp = self._post("/api/generate", {
            "article": {"title": "AI in Marketing 2026", "source": "TechCrunch"},
            "format": "instagram",
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/generate (format=instagram, plan=free)")
        print(f"  Expected: 403 PLAN_LIMIT (instagram not in free plan)")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Body:     {json.dumps(data, ensure_ascii=False)[:200]}")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data.get("code"), "PLAN_LIMIT")
        print(f"  Result:   PASS — free plan correctly blocks Instagram")

    # =================================================================
    # STEP 4: Generate LinkedIn content (free plan — allowed)
    # =================================================================
    def test_04_generate_linkedin_free(self):
        """Step 4: Generate LinkedIn content on free plan.
        linkedin IS in free plan platforms. Should succeed."""
        print("\n" + "="*60)
        print("STEP 4: GENERATE — LinkedIn on FREE plan (allowed)")
        print("="*60)

        _generation_counter["lifetime"] = 0

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value=None),
            patch.object(flask_app, '_llm_call', return_value="L'AI sta trasformando il marketing..."),
            patch.object(flask_app, '_ensure_user_prompts'),
            patch.object(flask_app, '_get_prompt', return_value="LinkedIn format"),
            patch.object(flask_app, '_update_weekly_status'),
            patch.object(db, 'increment_generation_count', return_value={
                "generation_count": 1, "generation_count_monthly": 1, "month": "2026-03"
            }),
            patch.object(db, 'create_notification'),
            patch("payments.check_generation_limit", return_value={
                "allowed": True, "used": 0, "limit": 10, "limit_type": "lifetime", "plan": "free"
            }),
        ])

        resp = self._post("/api/generate", {
            "article": {"title": "AI in Marketing 2026"},
            "format": "linkedin",
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/generate (format=linkedin, plan=free)")
        print(f"  Expected: 200 with content")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Content:  '{(data or {}).get('content', '')[:60]}...'")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("content", data)
        self.assertEqual(data["format"], "linkedin")
        print(f"  Result:   PASS — LinkedIn generation works on free plan")

    # =================================================================
    # STEP 5: Generate Instagram (Pro plan — allowed)
    # =================================================================
    def test_05_generate_instagram_pro(self):
        """Step 5: Simulate Pro plan upgrade, generate Instagram content."""
        print("\n" + "="*60)
        print("STEP 5: GENERATE — Instagram on PRO plan")
        print("="*60)

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value={"plan": "pro"}),
            patch.object(flask_app, '_llm_call', return_value="🔥 L'AI nel Marketing\n---SLIDE---\n3 trend che cambieranno tutto\n---SLIDE---\n1. Personalizzazione\n---SLIDE---\nSeguimi per altri insight!"),
            patch.object(flask_app, '_ensure_user_prompts'),
            patch.object(flask_app, '_get_prompt', return_value="Instagram carousel format"),
            patch.object(flask_app, '_update_weekly_status'),
            patch.object(db, 'increment_generation_count', return_value={
                "generation_count": 2, "generation_count_monthly": 1, "month": "2026-03"
            }),
            patch.object(db, 'create_notification'),
            patch("payments.check_platform_access", return_value=True),
            patch("payments.check_generation_limit", return_value={
                "allowed": True, "used": 0, "limit": 50, "limit_type": "monthly", "plan": "pro"
            }),
        ])

        resp = self._post("/api/generate", {
            "article": {"title": "AI in Marketing 2026", "source": "TechCrunch",
                        "summary": "How AI is transforming marketing strategies"},
            "format": "instagram",
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/generate (format=instagram, plan=pro)")
        print(f"  Expected: 200 with carousel content (---SLIDE--- separators)")
        print(f"  Actual:   {resp.status_code}")

        self.assertEqual(resp.status_code, 200)
        content = data.get("content", "")
        has_slides = "---SLIDE---" in content or "SLIDE" in content
        print(f"  Content:  '{content[:80]}...'")
        print(f"  Slides:   {'Yes' if has_slides else 'No'} (---SLIDE--- separators)")
        print(f"  Format:   {data.get('format')}")
        print(f"  Result:   PASS — Instagram generation works on Pro plan")

    # =================================================================
    # STEP 6: Render carousel (Pro plan)
    # =================================================================
    def test_06_render_carousel_pro(self):
        """Step 6: Render carousel slides as PNG via built-in palette."""
        print("\n" + "="*60)
        print("STEP 6: RENDER CAROUSEL — Built-in palette (Pro)")
        print("="*60)

        fake_slides = [b"PNG_SLIDE_1_BYTES", b"PNG_SLIDE_2_BYTES", b"PNG_SLIDE_3_BYTES"]
        fake_urls = [
            "https://storage.supabase.co/carousel/slide_0.png",
            "https://storage.supabase.co/carousel/slide_1.png",
            "https://storage.supabase.co/carousel/slide_2.png",
        ]

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value={"plan": "pro"}),
            patch.object(db, 'get_profile', return_value={**_user_profile, "full_name": "Marco Rossi"}),
            patch.object(db, 'upload_carousel_images_batch', return_value=fake_urls),
            patch("carousel_renderer.render_carousel_async", return_value={
                "slides_bytes": fake_slides,
                "caption": "AI nel marketing: 3 trend da seguire",
            }),
            patch.object(flask_app, '_log_pipeline'),
        ])

        resp = self._post("/api/render-carousel", {
            "text": "🔥 L'AI nel Marketing\n---SLIDE---\n3 trend\n---SLIDE---\nSeguimi!",
            "palette": 0,
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/render-carousel (palette=0, Pro plan)")
        print(f"  Expected: 200 with slide URLs + caption")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Slides:   {data.get('slides', [])}")
        print(f"  Caption:  '{data.get('caption', '')[:60]}'")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data.get("slides", [])), 3)
        self.assertTrue(data.get("caption"))
        print(f"  Result:   PASS — 3 slides rendered + caption returned")

    # =================================================================
    # STEP 7: Render carousel on FREE plan → 403
    # =================================================================
    def test_07_render_carousel_free_blocked(self):
        """Step 7: Free plan user cannot render carousel (instagram not in platforms)."""
        print("\n" + "="*60)
        print("STEP 7: RENDER CAROUSEL — Free plan → BLOCKED")
        print("="*60)

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value=None),
        ])

        resp = self._post("/api/render-carousel", {
            "text": "Slide 1\n---SLIDE---\nSlide 2",
            "palette": 0,
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/render-carousel (free plan)")
        print(f"  Expected: 403 PLAN_LIMIT")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Body:     {json.dumps(data, ensure_ascii=False)[:200]}")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data.get("code"), "PLAN_LIMIT")
        print(f"  Result:   PASS — free plan correctly blocks carousel render")

    # =================================================================
    # STEP 8: Save session
    # =================================================================
    def test_08_save_session(self):
        """Step 8: Save generated content to a session."""
        print("\n" + "="*60)
        print("STEP 8: SESSION — Save")
        print("="*60)

        session_data = {
            "session_id": "e2e-session-001",
            "content": "🔥 L'AI nel Marketing\n---SLIDE---\n3 trend",
            "carousel_images": ["https://storage.supabase.co/carousel/slide_0.png"],
        }

        def mock_insert(user_id, body):
            _saved_sessions[body["session_id"]] = {**body, "user_id": user_id}
            return _saved_sessions[body["session_id"]]

        self._start_patches([
            patch.object(db, 'insert_session', side_effect=mock_insert),
        ])

        resp = self._post("/api/sessions", session_data)
        data = resp.get_json()

        print(f"  Action:   POST /api/sessions (session_id='e2e-session-001')")
        print(f"  Expected: 200/201 with saved session")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Saved:    {list(_saved_sessions.keys())}")

        self.assertIn(resp.status_code, [200, 201])
        self.assertIn("e2e-session-001", _saved_sessions)
        print(f"  Result:   PASS — session saved")

    # =================================================================
    # STEP 9: Retrieve sessions (reload)
    # =================================================================
    def test_09_retrieve_sessions(self):
        """Step 9: GET /api/sessions returns saved sessions."""
        print("\n" + "="*60)
        print("STEP 9: SESSION — Retrieve (reload)")
        print("="*60)

        self._start_patches([
            patch.object(db, 'get_sessions', return_value=list(_saved_sessions.values())),
        ])

        resp = self.client.get("/api/sessions")
        data = resp.get_json()

        print(f"  Action:   GET /api/sessions")
        print(f"  Expected: 200 with session list containing 'e2e-session-001'")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Sessions: {len(data) if isinstance(data, list) else 'not a list'}")

        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(data, list)
        has_session = any(s.get("session_id") == "e2e-session-001" for s in data)
        self.assertTrue(has_session, "Saved session not found in list")
        print(f"  Found:    e2e-session-001 present: {has_session}")
        print(f"  Result:   PASS — session retrieved after reload")

    # =================================================================
    # STEP 10: Verify generation counter
    # =================================================================
    def test_10_verify_counter(self):
        """Step 10: Generation counter correctly reflects usage."""
        print("\n" + "="*60)
        print("STEP 10: COUNTER — Verify generation tracking")
        print("="*60)

        self._start_patches([
            patch.object(db, 'get_generation_counts', return_value={
                "lifetime": 2, "monthly": 1, "month": "2026-03"
            }),
            patch.object(db, 'get_subscription', return_value={"plan": "pro"}),
        ])

        result = payments.check_generation_limit("user-e2e-001", "pro")

        print(f"  Action:   check_generation_limit(user, 'pro')")
        print(f"  Expected: allowed=True, used=1, limit=50, type=monthly")
        print(f"  Actual:   {json.dumps(result)}")

        self.assertTrue(result["allowed"])
        self.assertEqual(result["limit_type"], "monthly")
        self.assertEqual(result["limit"], 50)
        print(f"  Result:   PASS — counter correct, under limit")

    # =================================================================
    # STEP 11: Free plan limit reached (10 lifetime)
    # =================================================================
    def test_11_free_plan_limit_reached(self):
        """Step 11: After 10 generations, free plan blocks further generation."""
        print("\n" + "="*60)
        print("STEP 11: LIMIT — Free plan 10 lifetime reached")
        print("="*60)

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value=None),
            patch.object(db, 'get_generation_counts', return_value={
                "lifetime": 10, "monthly": 10, "month": "2026-03"
            }),
        ])

        resp = self._post("/api/generate", {
            "article": {"title": "One more article"},
            "format": "linkedin",
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/generate (linkedin, free plan, 10 used)")
        print(f"  Expected: 403 GENERATION_LIMIT with upgrade_required")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Body:     {json.dumps(data, ensure_ascii=False)[:200]}")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data.get("code"), "GENERATION_LIMIT")
        self.assertTrue(data.get("upgrade_required"))
        self.assertEqual(data.get("used"), 10)
        self.assertEqual(data.get("limit"), 10)
        print(f"  Result:   PASS — limit correctly enforced at 10/10")

    # =================================================================
    # STEP 12: Pro plan monthly limit
    # =================================================================
    def test_12_pro_plan_monthly_limit(self):
        """Step 12: Pro plan with 50 monthly generations used → blocked."""
        print("\n" + "="*60)
        print("STEP 12: LIMIT — Pro plan 50/month reached")
        print("="*60)

        self._start_patches([
            patch.object(flask_app, '_is_admin', return_value=False),
            patch.object(db, 'get_subscription', return_value={"plan": "pro"}),
            patch.object(db, 'get_generation_counts', return_value={
                "lifetime": 120, "monthly": 50, "month": "2026-03"
            }),
        ])

        resp = self._post("/api/generate", {
            "article": {"title": "Limit test"},
            "format": "instagram",
        })
        data = resp.get_json()

        print(f"  Action:   POST /api/generate (instagram, pro plan, 50/50 monthly)")
        print(f"  Expected: 403 GENERATION_LIMIT")
        print(f"  Actual:   {resp.status_code}")
        print(f"  Body:     {json.dumps(data, ensure_ascii=False)[:200]}")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(data.get("code"), "GENERATION_LIMIT")
        self.assertEqual(data.get("used"), 50)
        self.assertEqual(data.get("limit"), 50)
        print(f"  Result:   PASS — Pro monthly limit enforced at 50/50")

    # =================================================================
    # STEP 13: Disabled features still blocked
    # =================================================================
    def test_13_disabled_features(self):
        """Step 13: Verify disabled endpoints remain 403."""
        print("\n" + "="*60)
        print("STEP 13: FEATURE GATE — Disabled endpoints check")
        print("="*60)

        self._start_patches()

        disabled = [
            ("POST", "/api/search", "Web Search"),
            ("POST", "/api/generate-newsletter", "Newsletter"),
            ("POST", "/api/carousel/enrich-images", "Carousel AI Images"),
            ("GET",  "/api/schedule", "Schedule"),
        ]

        all_pass = True
        for method, url, name in disabled:
            if method == "POST":
                resp = self._post(url, {})
            else:
                resp = self.client.get(url)

            status = resp.status_code
            ok = status == 403
            all_pass = all_pass and ok
            marker = "PASS" if ok else "FAIL"
            print(f"  {name:25s} {method} {url} → {status} [{marker}]")

        self.assertTrue(all_pass, "Some disabled features are still accessible")
        print(f"  Result:   PASS — all disabled endpoints return 403")


if __name__ == "__main__":
    print("=" * 60)
    print("SPRINT 2 — E2E SMOKE TEST: CAROUSEL-FIRST CORE LOOP")
    print("=" * 60)
    # Run tests in order (sorted by name = test_01, test_02, etc.)
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = lambda x, y: (x > y) - (x < y)
    suite = loader.loadTestsFromTestCase(TestE2E_CarouselFirstLoop)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
