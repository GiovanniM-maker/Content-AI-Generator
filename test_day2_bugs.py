#!/usr/bin/env python3
"""Day 2 bug reproduction & validation tests for B1, B2, B3.

B1: increment_generation_count fallback hard-resets monthly counter to 1
B2: increment_weekly_counter fallback uses non-atomic read-modify-write
B3: increment_generation_count failure silently swallowed in app.py

These tests mock Supabase to simulate RPC failure and verify fallback behavior.
"""

import json
import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call

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
    import db
    import app as flask_app
    import auth as auth_mod


# ===================================================================
# B1: increment_generation_count fallback resets monthly to 1
# ===================================================================
class TestB1_MonthlyCounterReset(unittest.TestCase):
    """B1: When RPC fails, fallback at db.py:987 sets generation_count_monthly=1
    instead of incrementing. A user with 30 monthly generations drops to 1."""

    def _make_mock_sb(self, profile_data):
        """Create a mock Supabase client that:
        - Raises on rpc() (simulates RPC failure)
        - Returns profile_data on table('profiles').select()
        - Captures the update() call for inspection
        """
        mock_sb = MagicMock()

        # RPC fails
        mock_sb.rpc.side_effect = Exception("RPC not available")

        # table().select().eq().execute() returns profile
        select_result = MagicMock()
        select_result.data = [profile_data] if profile_data else []
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = select_result

        # table().update().eq().execute() — capture what gets written
        self.captured_update = {}
        def capture_update(data):
            self.captured_update = data
            update_chain = MagicMock()
            update_chain.eq.return_value.execute.return_value = MagicMock(data=[])
            return update_chain
        mock_sb.table.return_value.update.side_effect = capture_update

        return mock_sb

    def test_b1_monthly_destroyed(self):
        """Scenario: User has 30 monthly generations. RPC fails.
        BEFORE fix: fallback sets generation_count_monthly=1 (loses 29 gens).
        AFTER fix: fallback sets generation_count_monthly=31 (correct increment).
        """
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        profile = {
            "id": "user-123",
            "generation_count": 45,           # lifetime
            "generation_count_monthly": 30,    # monthly — THIS IS THE KEY VALUE
            "generation_count_month": current_month,
        }

        mock_sb = self._make_mock_sb(profile)

        with patch.object(db, '_sb', return_value=mock_sb):
            result = db.increment_generation_count("user-123")

        print(f"\n[B1] Captured update payload: {json.dumps(self.captured_update, indent=2, default=str)}")
        print(f"[B1] Returned result: {json.dumps(result, indent=2, default=str)}")

        monthly_written = self.captured_update.get("generation_count_monthly")
        lifetime_written = self.captured_update.get("generation_count")

        print(f"[B1] Monthly written to DB: {monthly_written} (was 30, expected 31)")
        print(f"[B1] Lifetime written to DB: {lifetime_written} (was 45, expected 46)")

        # BEFORE fix: monthly_written == 1  (BUG: hard reset)
        # AFTER fix:  monthly_written == 31 (correct increment)
        if monthly_written == 1:
            print("[B1] RESULT: *** REPRODUCED — monthly counter reset to 1 ***")
            self.fail("B1 NOT FIXED: monthly counter reset from 30 to 1")
        elif monthly_written == 31:
            print("[B1] RESULT: PASS — monthly counter correctly incremented to 31")
        else:
            print(f"[B1] RESULT: UNEXPECTED value {monthly_written}")
            self.fail(f"Unexpected monthly value: {monthly_written}")

        # Also verify lifetime
        self.assertEqual(lifetime_written, 46, f"Lifetime should be 46, got {lifetime_written}")

    def test_b1_month_boundary_reset(self):
        """Edge case: stored month is old — should legitimately reset to 1."""
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        profile = {
            "id": "user-123",
            "generation_count": 45,
            "generation_count_monthly": 30,
            "generation_count_month": "2025-01",  # OLD month — reset is legitimate
        }

        mock_sb = self._make_mock_sb(profile)

        with patch.object(db, '_sb', return_value=mock_sb):
            result = db.increment_generation_count("user-123")

        monthly_written = self.captured_update.get("generation_count_monthly")
        print(f"\n[B1-boundary] Monthly written: {monthly_written} (old month → expect 1)")

        # When stored month != current month, resetting to 1 IS correct
        if monthly_written == 1:
            print("[B1-boundary] RESULT: PASS — legitimate month boundary reset to 1")
        else:
            print(f"[B1-boundary] RESULT: value {monthly_written}")


# ===================================================================
# B2: increment_weekly_counter fallback race condition
# ===================================================================
class TestB2_WeeklyCounterRace(unittest.TestCase):
    """B2: Fallback read-modify-write at db.py:921-929 is non-atomic.
    Two concurrent requests read same value, both write value+1, one increment lost.

    We simulate this deterministically by showing that the UPDATE payload
    uses a hardcoded value (not SQL col+1), making it vulnerable to races.
    """

    def _make_mock_sb_simple(self, existing_row):
        """Mock for basic insert test (no optimistic lock simulation)."""
        mock_sb = MagicMock()
        mock_sb.rpc.side_effect = Exception("RPC not available")

        select_result = MagicMock()
        select_result.data = [existing_row] if existing_row else []
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = select_result

        self.captured_updates = []
        def capture_update(data):
            self.captured_updates.append(data)
            chain = MagicMock()
            chain.eq.return_value.execute.return_value = MagicMock(data=[data])
            chain.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[data])
            return chain
        mock_sb.table.return_value.update.side_effect = capture_update

        self.captured_inserts = []
        def capture_insert(data):
            self.captured_inserts.append(data)
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[data])
            return chain
        mock_sb.table.return_value.insert.side_effect = capture_insert

        return mock_sb

    def test_b2_optimistic_lock_present(self):
        """Verify the fallback UPDATE now includes an .eq(action, old_val) condition.

        BEFORE fix: update({generated: 6}).eq("id", row_id) — no lock
        AFTER fix:  update({generated: 6}).eq("id", row_id).eq("generated", 5) — optimistic lock

        We verify this by checking the mock call chain.
        """
        existing = {"id": "row-1", "user_id": "u1", "week_key": "2026-W11",
                     "platform": "instagram", "generated": 5, "published": 0}

        mock_sb = MagicMock()
        mock_sb.rpc.side_effect = Exception("RPC not available")

        # SELECT returns existing row
        select_result = MagicMock()
        select_result.data = [existing]
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = select_result

        # Track the full chain: update().eq().eq().execute()
        update_calls = []
        def capture_update(data):
            update_calls.append({"update_data": data})
            eq1_mock = MagicMock()
            eq_calls = []
            def capture_eq1(field, val):
                eq_calls.append((field, val))
                eq2_mock = MagicMock()
                def capture_eq2(field2, val2):
                    eq_calls.append((field2, val2))
                    exec_mock = MagicMock()
                    # Optimistic lock succeeds — return data
                    exec_mock.execute.return_value = MagicMock(data=[data])
                    return exec_mock
                eq2_mock.eq.side_effect = capture_eq2
                eq2_mock.execute.return_value = MagicMock(data=[data])
                return eq2_mock
            eq1_mock.eq.side_effect = capture_eq1
            update_calls[-1]["eq_calls"] = eq_calls
            return eq1_mock
        mock_sb.table.return_value.update.side_effect = capture_update

        with patch.object(db, '_sb', return_value=mock_sb):
            db.increment_weekly_counter("u1", "2026-W11", "instagram", "generated")

        print(f"\n[B2] Update calls: {update_calls}")
        if update_calls:
            data_written = update_calls[0]["update_data"]
            eq_chain = update_calls[0]["eq_calls"]
            print(f"[B2] Data: {data_written}")
            print(f"[B2] EQ chain: {eq_chain}")

            # Check if optimistic lock condition is present
            has_id_eq = any(f == "id" for f, v in eq_chain)
            has_action_eq = any(f == "generated" and v == 5 for f, v in eq_chain)

            if has_action_eq:
                print("[B2] RESULT: PASS — optimistic lock present: .eq('generated', 5)")
            elif has_id_eq and not has_action_eq:
                print("[B2] RESULT: *** NO LOCK — only .eq('id', ...) without .eq('generated', old_val) ***")
                self.fail("B2 NOT FIXED: no optimistic lock on update")
            else:
                print(f"[B2] RESULT: UNEXPECTED eq chain")

    def test_b2_retry_on_conflict(self):
        """When optimistic lock fails (data=[]), verify retry logic kicks in."""
        existing = {"id": "row-1", "user_id": "u1", "week_key": "2026-W11",
                     "platform": "instagram", "generated": 5, "published": 0}
        refreshed = {"id": "row-1", "user_id": "u1", "week_key": "2026-W11",
                      "platform": "instagram", "generated": 7, "published": 0}

        mock_sb = MagicMock()
        mock_sb.rpc.side_effect = Exception("RPC not available")

        # Track select calls — first returns existing, second returns refreshed
        select_call_count = [0]
        def mock_select(*args):
            chain = MagicMock()
            def mock_eq_chain(*a, **kw):
                result_mock = MagicMock()
                if select_call_count[0] == 0:
                    # First select: 3 .eq() calls (user, week, platform)
                    result_mock.data = [existing]
                    eq3 = MagicMock()
                    eq3.execute.return_value = result_mock
                    eq2 = MagicMock()
                    eq2.eq.return_value = eq3
                    eq1 = MagicMock()
                    eq1.eq.return_value = eq2
                    select_call_count[0] = 1
                    return eq1
                else:
                    # Second select (retry): 1 .eq() call (id only)
                    result_mock.data = [refreshed]
                    eq1 = MagicMock()
                    eq1.execute.return_value = result_mock
                    select_call_count[0] += 1
                    return eq1
                return result_mock
            chain.eq.side_effect = mock_eq_chain
            return chain
        mock_sb.table.return_value.select.side_effect = mock_select

        update_payloads = []
        def mock_update(data):
            update_payloads.append(data)
            eq_mock = MagicMock()
            if len(update_payloads) == 1:
                # First update: optimistic lock FAILS (data=[])
                eq_mock.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                eq_mock.eq.return_value.execute.return_value = MagicMock(data=[])
            else:
                # Retry update: succeeds
                eq_mock.eq.return_value.execute.return_value = MagicMock(data=[data])
            return eq_mock
        mock_sb.table.return_value.update.side_effect = mock_update

        with patch.object(db, '_sb', return_value=mock_sb):
            db.increment_weekly_counter("u1", "2026-W11", "instagram", "generated")

        print(f"\n[B2-retry] Update payloads: {update_payloads}")
        if len(update_payloads) >= 2:
            first = update_payloads[0].get("generated")
            retry = update_payloads[1].get("generated")
            print(f"[B2-retry] 1st attempt wrote: {first} (should fail optimistic lock)")
            print(f"[B2-retry] Retry wrote: {retry} (based on refreshed value 7 → should be 8)")
            if retry == 8:
                print("[B2-retry] RESULT: PASS — retry used refreshed value (7+1=8)")
            else:
                print(f"[B2-retry] RESULT: PARTIAL — retry value {retry}")
        elif len(update_payloads) == 1:
            print("[B2-retry] RESULT: FAIL — no retry after optimistic lock failure")
            self.fail("B2: no retry on optimistic lock failure")

    def test_b2_new_row_insert(self):
        """When no row exists, insert should create with action=1."""
        mock_sb = self._make_mock_sb_simple(None)

        with patch.object(db, '_sb', return_value=mock_sb):
            db.increment_weekly_counter("u1", "2026-W11", "instagram", "generated")

        if self.captured_inserts:
            print(f"\n[B2-insert] Inserted: {self.captured_inserts[0]}")
            self.assertEqual(self.captured_inserts[0].get("generated"), 1)
            print("[B2-insert] RESULT: PASS — new row with generated=1")
        else:
            print("[B2-insert] RESULT: FAIL — no insert captured")


# ===================================================================
# B3: increment_generation_count exception silently swallowed
# ===================================================================
class TestB3_SilentSwallow(unittest.TestCase):
    """B3: app.py:2375-2378 swallows generation counter failures silently.
    No logging, no tracking — user gets free generation."""

    def test_b3_no_logging(self):
        """When db.increment_generation_count raises, nothing is logged."""
        _test_app = flask_app.app
        _test_app.config["TESTING"] = True

        with patch.object(auth_mod, '_extract_token', return_value="tok"), \
             patch.object(auth_mod, 'verify_token', return_value={
                 "sub": "u1", "email": "e@t.com", "role": "authenticated", "user_metadata": {}
             }), \
             patch.object(flask_app, '_is_admin', return_value=True), \
             patch.object(flask_app, '_llm_call', return_value="Generated content here"), \
             patch.object(flask_app, '_ensure_user_prompts'), \
             patch.object(flask_app, '_get_prompt', return_value="format prompt"), \
             patch.object(flask_app, '_update_weekly_status'), \
             patch.object(db, 'get_subscription', return_value={"plan": "pro"}), \
             patch("payments.check_platform_access", return_value=True), \
             patch("payments.check_generation_limit", return_value={"allowed": True, "used": 1, "limit": 50, "limit_type": "monthly"}), \
             patch.object(db, 'increment_generation_count', side_effect=Exception("DB connection lost")) as mock_inc, \
             patch.object(db, 'create_notification'), \
             patch.object(flask_app, '_log_pipeline') as mock_log:

            client = _test_app.test_client()
            resp = client.post("/api/generate",
                data=json.dumps({"article": {"title": "Test"}, "format": "instagram"}),
                content_type="application/json")

            data = resp.get_json()
            print(f"\n[B3] Status: {resp.status_code}")
            print(f"[B3] Content returned: {bool(data and data.get('content'))}")

            # Check if the error was logged
            log_calls = [str(c) for c in mock_log.call_args_list]
            logged_increment_error = any("increment" in c.lower() or "generation count" in c.lower()
                                         for c in log_calls)

            print(f"[B3] Log calls: {log_calls}")
            print(f"[B3] Increment error logged: {logged_increment_error}")

            if not logged_increment_error:
                print("[B3] RESULT: *** REPRODUCED — exception silently swallowed, no log ***")
            else:
                print("[B3] RESULT: PASS — error is logged")

            # Content should still be returned (200) regardless
            self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}")


if __name__ == "__main__":
    print("=" * 60)
    print("DAY 2 — BUG REPRODUCTION (PRE-FIX BASELINE)")
    print("=" * 60)
    unittest.main(verbosity=2)
