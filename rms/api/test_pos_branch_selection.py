import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import frappe

from rms.api import pos


class TestPOSBranchSelection(unittest.TestCase):
    @contextmanager
    def register(self, role="Master", active=None, assigned=None):
        stores = [
            frappe._dict(
                name=f"STORE-{i}",
                title=f"Store {i}",
                store_code=str(i),
                streaming_branch=f"B{i}",
            )
            for i in (1, 2, 3)
        ]

        def value(dt, name, fields, *args, **kwargs):
            if dt == "Store":
                return (
                    next(row for row in stores if row.name == name)
                    if isinstance(fields, list)
                    else "COMPANY"
                )
            if dt == "Company":
                return "EGP"
            return None

        def guard(name):
            allowed = name != "STORE-1" if role == "Master" else name == "STORE-1"
            if not allowed:
                frappe.throw("Store belongs to another writer", frappe.PermissionError)
            return next(row for row in stores if row.name == name)

        with ExitStack() as stack:
            for target, kwargs in {
                "rms.api.pos.require_pos_role": {},
                "rms.api.pos.get_pos_capabilities": {"return_value": {}},
                "rms.api.pos.get_active_pos_user": {"return_value": None},
                "rms.api.pos._user_has_store_access": {
                    "side_effect": lambda user, store: (
                        assigned is None or store in assigned
                    )
                },
                "rms.api.pos.assert_store_access": {"side_effect": guard},
                "rms.api.pos.get_brands": {"return_value": []},
                "rms.api.pos.get_order_types": {"return_value": []},
                "rms.api.pos.get_user_session": {
                    "side_effect": lambda store=None: (
                        active
                        if active and (not store or store == active.store)
                        else None
                    )
                },
                "rms.api.pos.serialize_session": {
                    "side_effect": lambda s: {"name": s.name, "store": s.store}
                },
                "frappe.get_all": {"return_value": stores},
                "frappe.db.get_value": {"side_effect": value},
                "frappe.db.exists": {
                    "side_effect": lambda dt, f: f.get("restaurant_branch") == "B1"
                },
            }.items():
                stack.enter_context(patch(target, **kwargs))
            stack.enter_context(
                patch.object(
                    frappe, "conf", frappe._dict(arab_streaming_site_role=role)
                )
            )
            before = frappe.local.message_log
            frappe.local.message_log = []
            try:
                yield
            finally:
                frappe.local.message_log = before

    def test_master_ignores_slave_session_and_returns_local_store_choices_without_messages(
        self,
    ):
        with self.register(active=frappe._dict(name="REMOTE", store="STORE-1")):
            data = pos.get_bootstrap()
            self.assertEqual([r.name for r in data["stores"]], ["STORE-2", "STORE-3"])
            self.assertEqual(data["store"].name, "STORE-2")
            self.assertIsNone(data["session"])
            self.assertEqual(frappe.local.message_log, [])

    def test_slave_excludes_other_stores_without_message_dialogs(self):
        with self.register(
            role="Slave", active=frappe._dict(name="OLD", store="STORE-2")
        ):
            data = pos.get_bootstrap()
            self.assertEqual([r.name for r in data["stores"]], ["STORE-1"])
            self.assertEqual(data["store"].name, "STORE-1")
            self.assertEqual(frappe.local.message_log, [])

    def test_stale_browser_choice_can_fall_back_without_returning_its_session(self):
        with self.register(active=frappe._dict(name="REMOTE", store="STORE-1")):
            data = pos.get_bootstrap("STORE-1", allow_store_fallback=1)
            self.assertTrue(data["store_selection_reset"])
            self.assertEqual(data["store"].name, "STORE-2")
            self.assertIsNone(data["session"])
            self.assertEqual(frappe.local.message_log, [])

    def test_explicit_disallowed_bootstrap_without_navigation_fallback_still_fails(
        self,
    ):
        with self.register(), self.assertRaises(frappe.PermissionError):
            pos.get_bootstrap("STORE-1")

    def test_user_store_assignments_still_restrict_local_branch_choices(self):
        with self.register(assigned={"STORE-3"}):
            self.assertEqual(pos.get_bootstrap()["store"].name, "STORE-3")

    def test_no_allowed_store_returns_no_session_or_foreign_context(self):
        with self.register(
            active=frappe._dict(name="REMOTE", store="STORE-1"), assigned=set()
        ):
            data = pos.get_bootstrap("STORE-1", allow_store_fallback=1)
            self.assertEqual(data["stores"], [])
            self.assertIsNone(data["store"])
            self.assertIsNone(data["session"])
            self.assertEqual(frappe.local.message_log, [])

    def test_valid_local_session_is_restored(self):
        with self.register(active=frappe._dict(name="LOCAL", store="STORE-3")):
            data = pos.get_bootstrap()
            self.assertEqual(data["store"].name, "STORE-3")
            self.assertEqual(data["session"]["name"], "LOCAL")

    def test_local_session_query_skips_remote_sessions_and_checks_all_candidates(self):
        rows = [
            frappe._dict(name="REMOTE", store="SLAVE"),
            frappe._dict(name="LOCAL", store="LOCAL"),
        ]
        with (
            patch("frappe.get_all", return_value=rows),
            patch(
                "rms.streaming_policy.is_store_operated_locally",
                side_effect=lambda name: name == "LOCAL",
            ),
            patch("frappe.get_doc", return_value="local-session") as get_doc,
        ):
            self.assertEqual(pos.get_user_session(), "local-session")
            get_doc.assert_called_once_with("Cashier Session", "LOCAL")
