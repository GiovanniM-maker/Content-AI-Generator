#!/usr/bin/env python3
"""Day 3 bug reproduction & validation tests for R1, S2, Feature Disablement.

R1: _update_weekly_status failure destroys generated content (500 instead of 200)
S2: request.json None crash on 4 feed config endpoints
FD: Feature disablement — out-of-scope endpoints must return 403
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

_test_app = flask_app.app
_test_app.config["TESTING"] = True

_FAKE_JWT = {
    "sub": "test-user-123",
    "email": "user@test.com",
    "role": "authenticated",
    "user_metadata": {},
}


class _AuthBase(unittest.TestCase):
    def setUp(self):
        self.client = _test_app.test_client()
        self._patches = [
            patch.object(auth_mod, '_extract_token', return_value="fake-token"),
            patch.object(auth_mod, 'verify_token', return_value=_FAKE_JWT),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()


# ===================================================================
# R1: _update_weekly_status failure destroys generated content
# ===================================================================
class TestR1_WeeklyStatusDestroysContent(_AuthBase):
    """R1: app.py:2373 — _update_weekly_status() is called BEFORE building
    the response. If it raises, the outer except at line 2384 catches it
    and returns 500, losing the successfully generated LLM content.

    BEFORE fix: 500 error, content lost
    AFTER fix: 200 with content, weekly status failure logged
    """

    def test_r1_content_lost_on_weekly_status_failure(self):
        """Generate content → LLM succeeds → _update_weekly_status raises → ?"""
        with patch.object(flask_app, '_is_admin', return_value=True), \
             patch.object(flask_app, '_llm_call', return_value="Ecco il tuo post Instagram perfetto!"), \
             patch.object(flask_app, '_ensure_user_prompts'), \
             patch.object(flask_app, '_get_prompt', return_value="format prompt"), \
             patch.object(flask_app, '_update_weekly_status', side_effect=Exception("DB weekly_status table unreachable")), \
             patch.object(db, 'get_subscription', return_value={"plan": "pro"}), \
             patch("payments.check_platform_access", return_value=True), \
             patch("payments.check_generation_limit", return_value={"allowed": True, "used": 1, "limit": 50, "limit_type": "monthly"}), \
             patch.object(db, 'increment_generation_count', return_value={"generation_count": 2, "generation_count_monthly": 2, "month": "2026-03"}), \
             patch.object(db, 'create_notification'), \
             patch.object(flask_app, '_log_pipeline') as mock_log:

            resp = self.client.post("/api/generate",
                data=json.dumps({"article": {"title": "Test Article"}, "format": "instagram"}),
                content_type="application/json")

            data = resp.get_json()
            status = resp.status_code

            print(f"\n[R1] Status: {status}")
            print(f"[R1] Body: {json.dumps(data, indent=2, ensure_ascii=False) if data else 'None'}")

            # Check logs
            log_calls = [str(c) for c in mock_log.call_args_list]
            weekly_error_logged = any("weekly" in c.lower() for c in log_calls)
            print(f"[R1] Weekly status error logged: {weekly_error_logged}")
            print(f"[R1] Log calls: {log_calls}")

            if status == 500:
                print("[R1] RESULT: *** REPRODUCED — 500 returned, content destroyed ***")
                self.fail("R1 NOT FIXED: weekly status failure returns 500")
            elif status == 200:
                has_content = data and data.get("content")
                if has_content:
                    print(f"[R1] Content: '{data['content'][:60]}...'")
                    print("[R1] RESULT: PASS — 200 with content, weekly failure absorbed")
                else:
                    print("[R1] RESULT: PARTIAL — 200 but no content in response")
                    self.fail("R1: 200 returned but content missing")
            else:
                print(f"[R1] RESULT: UNEXPECTED status {status}")

    def test_r1_normal_flow_still_works(self):
        """Sanity: when weekly status succeeds, everything works normally."""
        with patch.object(flask_app, '_is_admin', return_value=True), \
             patch.object(flask_app, '_llm_call', return_value="Post generato con successo"), \
             patch.object(flask_app, '_ensure_user_prompts'), \
             patch.object(flask_app, '_get_prompt', return_value="format"), \
             patch.object(flask_app, '_update_weekly_status'), \
             patch.object(db, 'get_subscription', return_value={"plan": "pro"}), \
             patch("payments.check_platform_access", return_value=True), \
             patch("payments.check_generation_limit", return_value={"allowed": True, "used": 1, "limit": 50, "limit_type": "monthly"}), \
             patch.object(db, 'increment_generation_count', return_value={"generation_count": 1, "generation_count_monthly": 1, "month": "2026-03"}), \
             patch.object(db, 'create_notification'):

            resp = self.client.post("/api/generate",
                data=json.dumps({"article": {"title": "OK"}, "format": "instagram"}),
                content_type="application/json")

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["content"], "Post generato con successo")
            print(f"\n[R1-normal] Status: 200, content: '{data['content'][:40]}' — PASS")


# ===================================================================
# S2: request.json None crash on 4 feed config endpoints
# ===================================================================
class TestS2_FeedConfigNoneBody(_AuthBase):
    """S2: 4 feed config endpoints crash on None/non-dict request.json.
    Endpoints: /add, /remove, /add-category, /remove-category
    """

    FEED_ENDPOINTS = [
        ("/api/feeds/config/add", "add_feed"),
        ("/api/feeds/config/remove", "remove_feed"),
        ("/api/feeds/config/add-category", "add_category"),
        ("/api/feeds/config/remove-category", "remove_category"),
    ]

    def test_s2_json_null_all_endpoints(self):
        """Body is JSON 'null' → request.json returns None → crash on .get()."""
        for url, name in self.FEED_ENDPOINTS:
            with self.subTest(endpoint=name):
                try:
                    resp = self.client.post(url, data="null", content_type="application/json")
                    status = resp.status_code
                    data = resp.get_json()
                except AttributeError as e:
                    print(f"\n[S2-{name}] REPRODUCED via exception: {e}")
                    self.fail(f"S2 NOT FIXED on {name}: AttributeError")
                    continue

                print(f"\n[S2-{name}] null body → Status: {status}")
                if status == 500:
                    print(f"[S2-{name}] RESULT: *** REPRODUCED — 500 ***")
                    self.fail(f"S2 NOT FIXED on {name}")
                elif status == 400:
                    print(f"[S2-{name}] RESULT: PASS — 400")
                else:
                    print(f"[S2-{name}] RESULT: status {status}")

    def test_s2_json_array_all_endpoints(self):
        """Body is JSON array → list has no .get() → crash."""
        for url, name in self.FEED_ENDPOINTS:
            with self.subTest(endpoint=name):
                try:
                    resp = self.client.post(url, data="[1,2]", content_type="application/json")
                    status = resp.status_code
                except AttributeError as e:
                    print(f"\n[S2-{name}] array REPRODUCED: {e}")
                    self.fail(f"S2 array NOT FIXED on {name}")
                    continue

                print(f"\n[S2-{name}] array body → Status: {status}")
                if status == 500:
                    print(f"[S2-{name}] RESULT: *** REPRODUCED — 500 ***")
                    self.fail(f"S2 array NOT FIXED on {name}")
                elif status == 400:
                    print(f"[S2-{name}] RESULT: PASS — 400")

    def test_s2_text_plain_all_endpoints(self):
        """text/plain Content-Type → request.json is None or 415."""
        for url, name in self.FEED_ENDPOINTS:
            with self.subTest(endpoint=name):
                resp = self.client.post(url, data="hello", content_type="text/plain")
                status = resp.status_code
                print(f"\n[S2-{name}] text/plain → Status: {status}")
                # 400 or 415 are both acceptable, 500 is not
                self.assertIn(status, [400, 415],
                              f"Expected 400 or 415 on {name}, got {status}")
                print(f"[S2-{name}] RESULT: PASS — {status}")

    def test_s2_empty_post_all_endpoints(self):
        """Empty POST with no body at all."""
        for url, name in self.FEED_ENDPOINTS:
            with self.subTest(endpoint=name):
                resp = self.client.post(url)
                status = resp.status_code
                print(f"\n[S2-{name}] empty → Status: {status}")
                self.assertIn(status, [400, 415],
                              f"Expected 400 or 415 on {name}, got {status}")
                print(f"[S2-{name}] RESULT: PASS — {status}")


# ===================================================================
# FD: Feature Disablement — out-of-scope endpoints must return 403
# ===================================================================
class TestFD_FeatureDisablement(_AuthBase):
    """Verify all disabled endpoints return 403 with appropriate message."""

    DISABLED_ENDPOINTS = [
        ("POST", "/api/carousel/enrich-images"),
        ("POST", "/api/generate-newsletter"),
        ("POST", "/api/newsletter/enrich-images"),
        ("POST", "/api/newsletter/html"),
        ("POST", "/api/search"),
        ("POST", "/api/search/score"),
        ("GET",  "/api/schedule"),
        ("POST", "/api/schedule"),
        ("POST", "/api/schedule/bulk"),
        ("DELETE", "/api/schedule/test-id"),
        ("POST", "/api/schedule/test-id/publish"),
    ]

    def test_fd_all_disabled_return_403(self):
        """Every disabled endpoint must return 403 with feature_disabled code."""
        for method, url in self.DISABLED_ENDPOINTS:
            with self.subTest(endpoint=f"{method} {url}"):
                if method == "POST":
                    resp = self.client.post(url, data="{}", content_type="application/json")
                elif method == "GET":
                    resp = self.client.get(url)
                elif method == "DELETE":
                    resp = self.client.delete(url)
                else:
                    continue

                status = resp.status_code
                data = resp.get_json()

                print(f"\n[FD] {method} {url} → {status}")
                if data:
                    print(f"[FD] Body: {json.dumps(data, ensure_ascii=False)[:200]}")

                if status == 403:
                    print(f"[FD] RESULT: PASS — 403 returned")
                else:
                    print(f"[FD] RESULT: *** NOT DISABLED — status {status} ***")
                    self.fail(f"Feature not disabled: {method} {url} returned {status}")


if __name__ == "__main__":
    print("=" * 60)
    print("DAY 3 — BUG REPRODUCTION (PRE-FIX BASELINE)")
    print("=" * 60)
    unittest.main(verbosity=2)
