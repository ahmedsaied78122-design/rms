import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from rms import streaming_policy as profile
from rms import streaming_replica as replica
from arab_streaming.streaming import copying, naming, policy, stock
from arab_streaming.streaming.adapters import is_business_doctype, transferable_fields
from arab_streaming.streaming.context import _replay


class TestRMSStreamingIsolation(unittest.TestCase):
	def setUp(self):
		self.role = frappe.conf.get("arab_streaming_site_role")
		self.enabled = frappe.conf.get("arab_streaming_enabled")

	def tearDown(self):
		frappe.conf.arab_streaming_site_role = self.role
		frappe.conf.arab_streaming_enabled = self.enabled

	def doc(self, **kwargs):
		return frappe._dict(
			doctype="Stock Entry", name="BR-A-WR-1", company="Company", **kwargs
		)

	def test_registered_resolver_gets_authenticated_peer_context(self):
		config = frappe._dict(scope="Branch", branch_field="app:rms_store")
		peer = frappe._dict(restaurant_branch="A")
		with patch.object(profile, "resolve_branch", return_value={"A"}) as resolver:
			self.assertTrue(
				policy.matches_scope(self.doc(), config, "A", peer=peer, incoming=True)
			)
			self.assertFalse(
				policy.matches_scope(self.doc(), config, "B", peer=peer, incoming=True)
			)
		resolver.assert_called_with(self.doc(), config, peer=peer, incoming=True)

	def test_source_only_new_transaction_uses_slave_pairing(self):
		frappe.conf.arab_streaming_site_role = "Slave"

		def all_rows(dt, **kwargs):
			return (
				["A"]
				if dt == "Master Instance"
				else ["Company"]
				if dt == "Store"
				else []
			)

		with (
			patch.object(profile, "_assignment", return_value=set()),
			patch("frappe.get_all", side_effect=all_rows),
		):
			self.assertEqual(profile.resolve_branch(self.doc(), {}), {"A"})

	def test_incoming_new_transaction_is_bound_to_authenticated_branch(self):
		frappe.conf.arab_streaming_site_role = "Master"
		with (
			patch.object(profile, "_assignment", return_value=set()),
			patch("frappe.db.exists", return_value=False),
			patch(
				"frappe.get_all",
				side_effect=lambda dt, **kw: ["Company"] if dt == "Store" else [],
			),
		):
			self.assertEqual(
				profile.resolve_branch(
					self.doc(), {}, frappe._dict(restaurant_branch="A"), True
				),
				{"A"},
			)

	def test_incoming_company_cannot_escape_store(self):
		frappe.conf.arab_streaming_site_role = "Master"
		with (
			patch.object(profile, "_assignment", return_value=set()),
			patch("frappe.db.exists", return_value=False),
			patch(
				"frappe.get_all",
				side_effect=lambda dt, **kw: ["Other"] if dt == "Store" else [],
			),
		):
			with self.assertRaises(frappe.PermissionError):
				profile.resolve_branch(
					self.doc(), {}, frappe._dict(restaurant_branch="A"), True
				)

	def test_persisted_transaction_is_not_adopted_from_peer_claim(self):
		frappe.conf.arab_streaming_site_role = "Master"
		with (
			patch.object(profile, "_assignment", return_value=set()),
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_all", return_value=[]),
		):
			self.assertEqual(
				profile.resolve_branch(
					self.doc(), {}, frappe._dict(restaurant_branch="A"), True
				),
				set(),
			)

	def test_existing_branch_assignment_is_authoritative(self):
		with patch.object(profile, "_assignment", return_value={"B"}):
			self.assertEqual(
				profile.resolve_branch(
					self.doc(), {}, frappe._dict(restaurant_branch="A"), True
				),
				{"B"},
			)

	def test_explicit_pos_profile_cannot_send_another_branch_transaction(self):
		frappe.conf.arab_streaming_site_role = "Master"
		with (
			patch.object(profile, "_assignment", return_value=set()),
			patch.object(profile, "_store_branches", return_value={"B"}),
			patch("frappe.db.exists", return_value=False),
			patch("frappe.get_all", return_value=[]),
		):
			with self.assertRaises(frappe.PermissionError):
				profile.resolve_branch(
					self.doc(), {}, frappe._dict(restaurant_branch="A"), True
				)

	def test_local_queues_and_approval_secrets_are_not_business_roots(self):
		for dt in profile.LOCAL_TYPES:
			self.assertFalse(is_business_doctype(dt))
		self.assertNotIn(
			"approval_challenge",
			{f.fieldname for f in transferable_fields(frappe.get_meta("POS Return"))},
		)

	def test_unregistered_and_non_branch_paths_fail(self):
		for path in (
			"app:unregistered",
			"store.title",
			"store.__class__.__dict__.x",
			"store;drop",
		):
			with self.subTest(path=path), self.assertRaises(frappe.ValidationError):
				policy.validate_branch_path("POS Order", path)

	def test_app_resolver_is_not_used_as_sql_column_in_initial_copy(self):
		config = frappe._dict(
			doctype_name="Stock Entry", scope="Branch", branch_field="app:rms_store"
		)
		with patch("arab_streaming.streaming.exports.selection", return_value=[]):
			filters, direct = copying.selection(
				config, frappe._dict(restaurant_branch="A")
			)
		self.assertEqual(filters, [])
		self.assertFalse(direct)

	def test_receive_only_rules_do_not_partition_central_writes(self):
		frappe.conf.arab_streaming_site_role = "Master"
		frappe.conf.arab_streaming_enabled = 1
		doc = SimpleNamespace(
			doctype="Stock Entry",
			meta=frappe._dict(is_submittable=1),
			naming_series="MAT-",
		)
		doc.meta.has_field = lambda field: True
		with (
			patch.object(
				naming,
				"stored_rules",
				return_value=[
					frappe._dict(
						enabled=1,
						doctype_name="Stock Entry",
						direction="Slave to Master",
					)
				],
			),
			patch.object(naming, "check_source") as check,
		):
			naming.before_naming(doc)
		check.assert_not_called()
		self.assertEqual(doc.naming_series, "MAT-")

	def test_non_submittable_operational_ids_are_partitioned_by_branch_and_writer(self):
		frappe.conf.arab_streaming_site_role = "Slave"
		frappe.conf.arab_streaming_enabled = 1
		doc = frappe.new_doc("Kitchen Ticket")
		with (
			patch.object(
				naming,
				"stored_rules",
				return_value=[
					frappe._dict(
						enabled=1,
						doctype_name="Kitchen Ticket",
						direction="Slave to Master",
						scope="Branch",
					)
				],
			),
			patch.object(naming, "check_source"),
			patch.object(naming, "document_branches", return_value={"A"}),
			patch(
				"frappe.db.get_value",
				return_value="12345678-1234-1234-1234-123456789012",
			),
		):
			naming.before_naming(doc)
		self.assertTrue(doc.naming_series.startswith("BR-"))
		self.assertIn("-WR-123456-", doc.naming_series)

	def test_branch_assignment_requires_server_owned_replay(self):
		with self.assertRaises(frappe.PermissionError):
			profile.remember_branch(
				{}, {}, self.doc(), {"branch_field": "app:rms_store"}
			)

	def test_stock_aggregation_checks_every_voucher_before_ledger_query(self):
		peer = frappe._dict(restaurant_branch="A")
		config = frappe._dict(scope="Branch", branch_field="app:rms_store")
		doc = Mock()
		with (
			patch.object(stock, "discover_branch_field", return_value=None),
			patch.object(policy, "config_for", return_value=config),
			patch.object(policy, "matches_scope", return_value=False),
			patch("frappe.get_doc", return_value=doc),
			patch("frappe.db.sql") as query,
		):
			with self.assertRaises(frappe.PermissionError):
				stock.movements(
					peer, ["Stock Entry"], {"Stock Entry": ["other-branch"]}
				)
			query.assert_not_called()


class TestRMSStreamingSnapshots(unittest.TestCase):
	def setUp(self):
		self.role = frappe.conf.get("arab_streaming_site_role")
		frappe.conf.arab_streaming_site_role = "Master"

	def tearDown(self):
		frappe.conf.arab_streaming_site_role = self.role

	def test_posted_replica_flags_do_not_grant_authority(self):
		doc = frappe._dict(
			doctype="POS Order",
			flags={"streaming_target_docstatus": 1, "from_pos_api": True},
		)
		self.assertFalse(replica.upstream(doc))
		with self.assertRaises(frappe.ValidationError):
			replica.validate(doc)

	def test_only_master_replay_uses_snapshot_path(self):
		doc = frappe._dict(doctype="POS Order")
		token = _replay.set("trusted-server-test")
		try:
			self.assertTrue(replica.upstream(doc))
			frappe.conf.arab_streaming_site_role = "Slave"
			self.assertFalse(replica.upstream(doc))
		finally:
			_replay.reset(token)

	def test_original_status_and_dates_are_not_reset_by_before_insert(self):
		for dt in ("POS Order", "Cashier Session", "POS Return", "Kitchen Ticket"):
			with self.subTest(doctype=dt):
				doc = frappe.get_doc(
					dict(
						doctype=dt,
						status="Approved" if dt == "POS Return" else "Closed",
						business_date="2026-10-01",
						opened_at="2026-10-01 08:00:00",
					)
				)
				before = (doc.status, doc.get("business_date"), doc.get("opened_at"))
				token = _replay.set("trusted-server-test")
				try:
					doc.before_insert()
				finally:
					_replay.reset(token)
				self.assertEqual(
					(doc.status, doc.get("business_date"), doc.get("opened_at")), before
				)

	def test_waste_replay_never_creates_another_stock_movement(self):
		doc = frappe.new_doc("Waste Entry")
		with (
			patch(
				"rms.rms.doctype.waste_entry.waste_entry.upstream", return_value=True
			),
			patch(
				"rms.rms.doctype.waste_entry.waste_entry.validate_replica"
			) as validator,
			patch(
				"rms.rms.doctype.waste_entry.waste_entry.create_material_issue"
			) as create,
			patch("rms.rms.doctype.waste_entry.waste_entry.cancel_waste") as cancel,
		):
			doc.on_submit()
			doc.on_cancel()
		create.assert_not_called()
		validator.assert_called_once_with(doc)
		cancel.assert_called_once_with(doc)

	def test_waste_cancel_reverses_existing_movement_once_with_native_cancel(self):
		doc = frappe._dict(doctype="Waste Entry", docstatus=2, stock_entry="STE", store="S")
		stock = Mock(docstatus=1)
		def cancelled():
			stock.docstatus = 2
		stock.cancel.side_effect = cancelled
		with (
			patch.object(replica, "upstream", return_value=True),
			patch.object(replica, "linked", side_effect=lambda dt, name: stock if dt == "Stock Entry" else "store"),
			patch.object(replica, "validate_waste") as before,
			patch.object(replica, "validate") as after,
			patch("arab_streaming.streaming.companions.cancel", side_effect=lambda target: target.cancel()) as native,
		):
			replica.cancel_waste(doc)
			replica.cancel_waste(doc)
			before.assert_called_once_with(doc, "store", stock_status=1)
			self.assertEqual(after.call_count, 2)
			native.assert_called_once_with(stock)
		stock.cancel.assert_called_once_with()

	def test_waste_cancel_rejects_wrong_components_before_reversal(self):
		doc = frappe._dict(doctype="Waste Entry", docstatus=2, stock_entry="STE", store="S")
		stock = Mock(docstatus=1)
		with (
			patch.object(replica, "upstream", return_value=True),
			patch.object(replica, "linked", return_value=stock),
			patch.object(replica, "validate_waste", side_effect=frappe.ValidationError("mismatch")),
		):
			with self.assertRaises(frappe.ValidationError):
				replica.cancel_waste(doc)
		stock.cancel.assert_not_called()

	def test_posted_flags_cannot_authorize_waste_child_cancellation(self):
		doc = frappe._dict(doctype="Waste Entry", docstatus=2, flags={"streaming_target_docstatus":2})
		with self.assertRaises(frappe.ValidationError):
			replica.cancel_waste(doc)

	def test_waste_snapshot_must_match_existing_native_stock_movement(self):
		doc = SimpleNamespace(
			quantity=1,
			items=[
				frappe._dict(item="X", warehouse="WH", qty=2, basic_rate=10, amount=20)
			],
			flags=frappe._dict(streaming_target_docstatus=1),
			docstatus=0,
			stock_entry="STE",
			status="Submitted",
		)
		movement = SimpleNamespace(
			company="C",
			docstatus=1,
			purpose="Material Issue",
			items=[frappe._dict(item_code="X", s_warehouse="WH", transfer_qty=3)],
		)
		with patch.object(
			replica,
			"linked",
			side_effect=lambda dt, name: (
				frappe._dict(company="C") if dt == "Warehouse" else movement
			),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Waste quantities"):
				replica.validate_waste(doc, frappe._dict(company="C"))
			movement.items[0].transfer_qty = 2
			replica.validate_waste(doc, frappe._dict(company="C"))

	def test_order_snapshot_is_not_repriced(self):
		doc = frappe.get_doc(
			dict(
				doctype="POS Order",
				store="S",
				status="Confirmed",
				business_date="2026-10-01",
				items=[
					dict(
						selling_product="P",
						item="X",
						qty=1,
						cancelled_qty=0,
						selling_price=42,
						amount=42,
					)
				],
				subtotal=42,
				tax_total=0,
				discount_amount=0,
				grand_total=42,
			)
		)
		with patch.object(
			replica, "linked", return_value=frappe._dict(item="X", selling_price=999)
		):
			replica.validate_order(doc, frappe._dict(company="C"))
		self.assertEqual(doc.items[0].selling_price, 42)

	def test_negative_nan_or_infinite_quantities_fail(self):
		for qty in (-1, 0, float("nan"), float("inf")):
			with self.subTest(qty=qty), self.assertRaises(frappe.ValidationError):
				replica.number(qty, positive=True)


class TestRMSNativeClosingReplay(unittest.TestCase):
	def test_receiving_completed_closing_does_not_start_consolidation(self):
		from rms.streaming_closing import RMSPOSClosingEntry

		doc = RMSPOSClosingEntry({"doctype": "POS Closing Entry"})
		with (
			patch("rms.streaming_closing.upstream_closing", return_value=True),
			patch.object(doc, "validate_replica") as validate,
			patch(
				"erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.consolidate_pos_invoices"
			) as consolidate,
			patch(
				"erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.unconsolidate_pos_invoices"
			) as undo,
		):
			doc.on_submit()
			doc.on_cancel()
			doc.before_update_after_submit()
		consolidate.assert_not_called()
		undo.assert_not_called()
		self.assertEqual(validate.call_count, 3)

	def test_invoice_payable_uses_original_rounding_during_replay(self):
		from rms.streaming_closing import preserve_invoice_rounding

		for grand, payable, expected in (
			(100.25, 101, "Round Up"),
			(100.25, 100.25, "No Rounding"),
			(-100.25, -101, "Round Up"),
		):
			doc = frappe._dict(
				grand_total=grand,
				rounded_total=payable,
				flags=frappe._dict(streaming_target_docstatus=1),
			)
			with (
				patch(
					"arab_streaming.streaming.context.replay_source",
					return_value="trusted",
				),
				patch.dict(frappe.conf, arab_streaming_site_role="Master"),
			):
				preserve_invoice_rounding(doc)
			self.assertEqual(doc.flags.rms_pos_rounding_method, expected)

	def test_invoice_flags_alone_cannot_override_rounding(self):
		from rms.streaming_closing import preserve_invoice_rounding

		doc = frappe._dict(
			grand_total=100.25,
			rounded_total=101,
			flags=frappe._dict(streaming_target_docstatus=1),
		)
		preserve_invoice_rounding(doc)
		self.assertFalse(doc.flags.rms_pos_rounding_method)


class TestRMSStoreBranchMapping(unittest.TestCase):
	def test_branch_cannot_be_assigned_to_two_stores(self):
		doc = frappe.get_doc(dict(doctype="Store", name="S", streaming_branch="A"))
		with patch("frappe.db.exists", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				doc.validate_streaming_branch()

	def test_paired_store_cannot_change_its_branch(self):
		doc = frappe.get_doc(dict(doctype="Store", name="S", streaming_branch="B"))
		with (
			patch.object(
				doc,
				"get_doc_before_save",
				return_value=frappe._dict(streaming_branch="A"),
			),
			patch(
				"frappe.db.exists",
				side_effect=lambda dt, filters: dt == "Master Instance",
			),
		):
			with self.assertRaises(frappe.ValidationError):
				doc.validate_streaming_branch()

	def test_optional_mapping_can_be_filled_before_pairing(self):
		doc = frappe.get_doc(dict(doctype="Store", name="S", streaming_branch="A"))
		with (
			patch.object(
				doc,
				"get_doc_before_save",
				return_value=frappe._dict(streaming_branch=None),
			),
			patch("frappe.db.exists", return_value=False),
		):
			doc.validate_streaming_branch()


class TestRMSPolicyPublication(unittest.TestCase):
	def test_publication_preserves_app_resolver_and_retires_old_rules_first(self):
		from arab_streaming.api.policies import install
		from arab_streaming.protocol.codec import digest

		state = SimpleNamespace(
			name="state",
			doctype="Streaming Peer State",
			execution_user="integration@example.test",
		)
		doc = Mock()
		row = dict(
			next(
				row
				for row in profile.defaults()
				if row["doctype_name"] == "Stock Entry"
			),
			name="new-rule",
		)
		row["branch_field"] = "app:rms_store"
		data = dict(branch="A", rules=[row], policy_hash=digest([row]))
		actions = []
		doc.insert.side_effect = lambda **kw: self.assertIn("old-rule", actions)
		with (
			patch(
				"frappe.get_doc",
				side_effect=lambda *args, **kw: (
					state if args[0] == "Streaming Peer State" else doc
				),
			),
			patch("frappe.get_all", return_value=["old-rule"]),
			patch("frappe.db.exists", return_value=True),
			patch("frappe.db.sql"),
			patch(
				"frappe.db.set_value",
				side_effect=lambda dt, name, *args: actions.append(name),
			),
			patch(
				"arab_streaming.streaming.adapters.is_business_doctype",
				return_value=True,
			),
			patch("arab_streaming.streaming.permissions.provision"),
			patch("arab_streaming.streaming.policy.ensure_branch_field") as add_field,
		):
			result = install(frappe._dict(restaurant_branch="A"), state, data)
		self.assertEqual(result["rules"], 1)
		add_field.assert_not_called()
		doc.set.assert_any_call("branch_field", "app:rms_store")

	def test_stock_movements_use_verified_voucher_scope_without_new_ledger_fields(self):
		config = frappe._dict(scope="Branch", branch_field="app:rms_store")
		with (
			patch.object(stock, "discover_branch_field", return_value=None),
			patch.object(policy, "config_for", return_value=config),
			patch.object(policy, "matches_scope", return_value=True),
			patch("frappe.get_doc", return_value=Mock()),
			patch(
				"frappe.db.sql",
				return_value=[
					frappe._dict(item_code="X", warehouse="WH", quantity=2, value=20)
				],
			) as sql,
		):
			result = stock.movements(
				frappe._dict(restaurant_branch="A"),
				["Stock Entry"],
				{"Stock Entry": ["STE-A"]},
			)
		self.assertEqual(result, [dict(item="X", warehouse="WH", quantity=2, value=20)])
		self.assertEqual(sql.call_args.args[1], ("Stock Entry", ("STE-A",)))


class TestRMSIncomingOwnership(unittest.TestCase):
	def test_amend_does_not_bypass_disabled_creation_and_amend_permissions(self):
		from arab_streaming.streaming.ownership import validate_action

		doc = frappe.new_doc("Stock Entry")
		doc.amended_from = "CANCELLED-SOURCE"
		row = next(
			row for row in profile.defaults() if row["doctype_name"] == "Stock Entry"
		)
		peer = frappe._dict(
			restaurant_branch="A",
			connection_status="Connected",
			receiving_doctypes_data="{}",
			incoming_rules=[row],
			syncing_doctypes=[],
		)
		with (
			patch.dict(
				frappe.conf, arab_streaming_enabled=1, arab_streaming_site_role="Master"
			),
			patch(
				"arab_streaming.streaming.ownership.policy_snapshot",
				return_value=([peer], 1),
			),
			patch.object(policy, "matches_scope", return_value=True),
		):
			with self.assertRaises(frappe.ValidationError):
				validate_action(doc, "before_validate")
