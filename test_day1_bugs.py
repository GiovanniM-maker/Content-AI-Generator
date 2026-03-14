#!/usr/bin/env python3
"""Day 1 bug reproduction & validation tests for C1, C2, C3.

Reproduction vectors:
  C1: POST /api/render-carousel with valid JSON → NameError on _get_plan()
  C2: POST /api/render-carousel with body 'null' → request.json returns None
  C3: POST /api/generate with body 'null' → request.json returns None
"""

import json
import unittest
from unittest.mock import patch

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
            patch.object(flask_app, '_is_admin', return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _post(self, url, data_str, content_type="application/json"):
        return self.client.post(url, data=data_str, content_type=content_type)


# ===================================================================
# C1: _get_plan() NameError
# ===================================================================
class TestC1(_AuthBase):

    @patch("db.get_subscription", return_value={"plan": "free"})
    def test_c1_nameerror_on_render_carousel(self, _mock_sub):
        """Valid JSON body → hits _get_plan() at line 3487 → NameError."""
        payload = json.dumps({"text": "Slide 1\n---SLIDE---\nSlide 2", "palette": 0})
        try:
            resp = self._post("/api/render-carousel", payload)
            status = resp.status_code
            data = resp.get_json() or {}
        except NameError as e:
            # NameError may propagate through WSGI in test mode
            print(f"\n[C1] REPRODUCED via exception: {e}")
            self.assertIn("_get_plan", str(e))
            return

        print(f"\n[C1] Status: {status}")
        print(f"[C1] Body: {json.dumps(data, ensure_ascii=False)[:300]}")

        if status == 500:
            # Check if it's from NameError
            print("[C1] RESULT: 500 — likely NameError (REPRODUCED)")
        elif status == 403:
            self.assertIn("PLAN_LIMIT", str(data))
            print("[C1] RESULT: PASS — plan gating works (403 for free user)")
        elif status == 200:
            print("[C1] RESULT: PASS — rendered OK")
        else:
            self.fail(f"Unexpected status {status}")


# ===================================================================
# C2: request.json → None on render-carousel
# ===================================================================
class TestC2(_AuthBase):

    def test_c2_json_null_body(self):
        """Body is literal JSON 'null' → request.json returns Python None → crash."""
        try:
            resp = self._post("/api/render-carousel", "null")
            status = resp.status_code
            data = resp.get_json() or {}
        except AttributeError as e:
            print(f"\n[C2] REPRODUCED via exception: {e}")
            self.assertIn("NoneType", str(e))
            return

        print(f"\n[C2] Status: {status}")
        print(f"[C2] Body: {json.dumps(data, ensure_ascii=False)[:300]}")

        if status == 500:
            print("[C2] RESULT: 500 — AttributeError (REPRODUCED)")
        elif status == 400:
            print("[C2] RESULT: PASS — 400 with proper error message")
        else:
            self.fail(f"Unexpected status {status}")

    def test_c2_json_array_body(self):
        """Body is JSON array → request.json returns list → .get() fails."""
        try:
            resp = self._post("/api/render-carousel", "[1,2,3]")
            status = resp.status_code
            data = resp.get_json() or {}
        except AttributeError as e:
            print(f"\n[C2-array] REPRODUCED via exception: {e}")
            return

        print(f"\n[C2-array] Status: {status}")
        print(f"[C2-array] Body: {json.dumps(data, ensure_ascii=False)[:300]}")

        if status == 500:
            print("[C2-array] RESULT: 500 — (REPRODUCED)")
        elif status == 400:
            print("[C2-array] RESULT: PASS — 400 with proper error")


# ===================================================================
# C3: request.json → None on /api/generate
# ===================================================================
class TestC3(_AuthBase):

    def test_c3_json_null_body(self):
        """Body is literal JSON 'null' → request.json returns None → crash."""
        try:
            resp = self._post("/api/generate", "null")
            status = resp.status_code
            data = resp.get_json() or {}
        except AttributeError as e:
            print(f"\n[C3] REPRODUCED via exception: {e}")
            self.assertIn("NoneType", str(e))
            return

        print(f"\n[C3] Status: {status}")
        print(f"[C3] Body: {json.dumps(data, ensure_ascii=False)[:300]}")

        if status == 500:
            print("[C3] RESULT: 500 — AttributeError (REPRODUCED)")
        elif status == 400:
            print("[C3] RESULT: PASS — 400 with proper error message")
        else:
            self.fail(f"Unexpected status {status}")

    def test_c3_json_array_body(self):
        """Body is JSON array → .get() fails."""
        try:
            resp = self._post("/api/generate", "[]")
            status = resp.status_code
            data = resp.get_json() or {}
        except AttributeError as e:
            print(f"\n[C3-array] REPRODUCED via exception: {e}")
            return

        print(f"\n[C3-array] Status: {status}")
        print(f"[C3-array] Body: {json.dumps(data, ensure_ascii=False)[:300]}")

        if status == 500:
            print("[C3-array] RESULT: 500 — (REPRODUCED)")
        elif status == 400:
            print("[C3-array] RESULT: PASS — 400 with proper error")


if __name__ == "__main__":
    print("=" * 60)
    print("DAY 1 — BUG REPRODUCTION BASELINE (PRE-FIX)")
    print("=" * 60)
    unittest.main(verbosity=2)
