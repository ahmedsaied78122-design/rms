"""First-run routing and authority tests; all writes and remote calls are mocked."""

import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

import frappe

from rms import onboarding as setup
from rms import setup_company


class TestOnboarding(unittest.TestCase):
	def setUp(self):
		self.addCleanup(patch.stopall)
		patch.object(frappe, "conf", frappe._dict()).start()
		patch.object(frappe, "session", frappe._dict(user="Administrator")).start()
		patch.object(frappe, "flags", frappe._dict()).start()
		patch.object(setup, "_configure").start()
		patch(
			"arab_streaming.streaming.context.replay",
			side_effect=lambda *a: nullcontext(),
		).start()
		self.db = patch.object(frappe, "db", Mock()).start()
		self.db.exists.return_value = False
		self.fresh = patch.object(
			frappe, "is_setup_complete", return_value=False
		).start()
		patch.object(
			frappe.utils, "get_url", return_value="https://slave.example.com"
		).start()

		def throw(message, exc=frappe.ValidationError, **kwargs):
			raise exc(message)

		patch.object(frappe, "throw", side_effect=throw).start()
		self.key, self.secret = "A" * 15, "B" * 15
		self.store = {
			"name": "S1",
			"title": "Store One",
			"streaming_branch": "B1",
			"company": "Company One",
		}
		self.companies = [
			{
				"name": "Company One",
				"company_name": "Company One",
				"abbr": "CO",
				"country": "Egypt",
				"default_currency": "EGP",
				"parent_company": None,
				"is_group": 0,
			}
		]

	def state(self):
		frappe.conf.rms_slave_setup = {
			"connection": "C1",
			"store": "S1",
			"branch": "B1",
			"company": "Company One",
			"master_url": "https://master.example.com",
			"companies": self.companies,
		}
		frappe.conf.arab_streaming_site_role = "Slave"

	def test_guest_cannot_start_or_read_setup(self):
		frappe.session.user = "Guest"
		for method, args in (
			(setup.test_master, ("x", "x", "x")),
			(setup.start_slave, ("x", "x", "x", "x", "x")),
			(setup.complete_master, ({},)),
			(setup.slave_status, ()),
			(setup.resume_slave, ()),
		):
			with (
				self.subTest(method=method.__name__),
				self.assertRaises(frappe.PermissionError),
			):
				method(*args)

	def test_master_retains_native_setup(self):
		args = {"rms_site_type": "Master", "company_name": "New Company"}
		with (
			patch(
				"frappe.desk.page.setup_wizard.setup_wizard.setup_complete",
				return_value={"status": "ok"},
			) as native,
			patch.object(setup, "_configure") as configure,
		):
			self.assertEqual(setup.complete_master(args), {"status": "ok"})
			native.assert_called_once_with(args)
			configure.assert_called_once_with(arab_streaming_site_role="Master")

	def test_native_company_creator_cannot_run_for_a_slave(self):
		for args in ({"rms_site_type": "Slave"}, {"rms_site_type": "invalid"}):
			with self.assertRaises(frappe.ValidationError):
				setup.complete_master(args)
		self.state()
		with self.assertRaises(frappe.ValidationError):
			setup.complete_master({"rms_site_type": "Master"})

	def test_completed_master_is_not_reconfigured(self):
		self.fresh.return_value = True
		with patch.object(setup, "_configure") as configure:
			self.assertEqual(setup.complete_master({}), {"status": "ok"})
			configure.assert_not_called()

	def test_connection_test_checks_protocol_and_returns_no_secret(self):
		from arab_streaming.protocol.version import PROTOCOL, VERSION

		with patch(
			"arab_streaming.streaming.client.remote_call",
			side_effect=[
				{"protocol": PROTOCOL, "version": VERSION, "role": "Master"},
				{
					"branches": ["B1"],
					"rms_stores": [self.store],
					"rms_companies": self.companies,
				},
			],
		) as remote:
			result = setup.test_master(
				"https://master.example.com", self.key, self.secret
			)
			self.assertEqual(result["stores"], [self.store])
			self.assertNotIn(self.secret, str(result))
			self.assertEqual(remote.call_count, 2)
			self.assertEqual(
				remote.call_args.args[0].get_password("secret"), self.secret
			)

	def test_invalid_credentials_and_self_url_never_reach_network(self):
		with patch("arab_streaming.streaming.client.remote_call") as remote:
			for url, key in (
				("https://slave.example.com", self.key),
				("http://master.example.com", self.key),
				("https://master.example.com", "invalid"),
			):
				with self.assertRaises(frappe.ValidationError):
					setup.test_master(url, key, self.secret)
			remote.assert_not_called()

	def test_cannot_select_an_unoffered_store(self):
		with (
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()),
			patch.object(
				setup,
				"_choices",
				return_value=(
					"https://master.example.com",
					[self.store],
					self.companies,
				),
			),
			patch.object(setup, "_configure") as configure,
		):
			with self.assertRaises(frappe.ValidationError):
				setup.start_slave(
					"https://master.example.com",
					self.key,
					self.secret,
					"S2",
					"https://slave.example.com",
				)
			configure.assert_not_called()

	def test_existing_company_is_not_replaced_by_slave_setup(self):
		self.db.exists.return_value = True
		with (
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()),
			patch.object(setup, "_choices") as choices,
		):
			with self.assertRaises(frappe.ValidationError):
				setup.start_slave(
					"x", self.key, self.secret, "S1", "https://slave.example.com"
				)
			choices.assert_not_called()

	def test_start_stores_encrypted_connection_and_non_secret_resume_identity(self):
		doc = Mock(name="connection")
		doc.name = "C1"
		doc.insert.return_value = doc
		with (
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()),
			patch.object(
				setup,
				"_choices",
				return_value=(
					"https://master.example.com",
					[self.store],
					self.companies,
				),
			),
			patch.object(setup, "_configure") as configure,
			patch.object(
				setup, "_integration_user", return_value="integration@rms.invalid"
			),
			patch("frappe.get_doc", return_value=doc) as get_doc,
			patch.object(setup, "_resume", return_value={"status": "In Progress"}),
		):
			setup.start_slave(
				"https://master.example.com",
				self.key,
				self.secret,
				"S1",
				"https://slave.example.com",
			)
			self.assertEqual(get_doc.call_args.args[0]["secret"], self.secret)
			self.assertNotIn(self.secret, str(configure.call_args_list))
			self.assertEqual(
				configure.call_args.kwargs[setup.STATE_KEY]["branch"], "B1"
			)
			self.db.commit.assert_called_once()

	def test_duplicate_start_does_not_replace_saved_connection(self):
		self.state()
		with (
			patch("frappe.utils.synchronization.filelock", return_value=nullcontext()),
			patch.object(setup, "_choices") as choices,
		):
			with self.assertRaises(frappe.ValidationError):
				setup.start_slave(
					"x", self.key, self.secret, "S1", "https://slave.example.com"
				)
			choices.assert_not_called()

	def test_initial_copy_excludes_financial_history_and_outbound_rules(self):
		rules = [
			frappe._dict(
				name=dt, doctype_name=dt, enabled=1, direction=direction, priority=i
			)
			for i, (dt, direction) in enumerate(
				(
					("Company", "Master to Slave"),
					("Store", "Master to Slave"),
					("Branch", "Master to Slave"),
					("POS Invoice", "Master to Slave"),
					("Customer", "Slave to Master"),
				)
			)
		]
		doc = Mock()
		doc.doctype = "Master Instance"
		doc.name = "C1"
		with (
			patch("arab_streaming.streaming.delivery.synchronize_policy"),
			patch(
				"arab_streaming.streaming.connections.peer_state",
				return_value=frappe._dict(policy_errors=None),
			),
			patch("arab_streaming.streaming.policy.stored_rules", return_value=rules),
			patch.object(setup, "_scaffold_companies"),
		):
			setup._prepare_copy(doc)
			rows = [c.args[1] for c in doc.append.call_args_list]
			self.assertEqual(
				{r["doctype_name"] for r in rows}, {"Company", "Store", "Branch"}
			)
			self.assertEqual(rows[0]["skip_if_exists"], 0)

	def test_failed_copy_is_continued_without_new_link_or_new_configuration(self):
		self.state()
		doc = frappe._dict(
			name="C1", syncing_status="Failed", connection_status="Connected"
		)
		with (
			patch("frappe.get_doc", return_value=doc),
			patch(
				"arab_streaming.streaming.initial_sync.start",
				return_value={"queued": True},
			) as start,
			patch.object(setup, "_prepare_copy") as prepare,
			patch.object(setup, "_configure"),
		):
			setup._resume()
			start.assert_called_once_with("C1", continuing=True, paired_peer=doc)
			prepare.assert_not_called()

	def test_in_progress_copy_is_not_queued_twice(self):
		self.state()
		with (
			patch(
				"frappe.get_doc",
				return_value=frappe._dict(syncing_status="In Progress"),
			),
			patch("arab_streaming.streaming.initial_sync.start") as start,
		):
			self.assertEqual(setup._resume(), {"status": "In Progress"})
			start.assert_not_called()

	def test_store_from_another_branch_does_not_complete_setup(self):
		self.state()
		with (
			patch(
				"frappe.get_doc",
				return_value=frappe._dict(
					enabled=1, streaming_branch="B2", company="Company One"
				),
			),
			self.assertRaises(frappe.ValidationError),
		):
			setup.finish_slave(frappe._dict(name="C1", restaurant_branch="B1"), None)
		self.db.set_single_value.assert_not_called()

	def test_skeleton_company_is_insufficient_to_complete_setup(self):
		self.state()
		with (
			patch(
				"frappe.get_doc",
				side_effect=[
					frappe._dict(
						enabled=1, streaming_branch="B1", company="Company One"
					),
					frappe._dict(name="Company One"),
				],
			),
			patch(
				"arab_streaming.streaming.connections.peer_state",
				return_value=frappe._dict(name="P1"),
			),
			self.assertRaises(frappe.ValidationError),
		):
			setup.finish_slave(
				frappe._dict(
					name="C1", doctype="Master Instance", restaurant_branch="B1"
				),
				None,
			)
		self.db.set_single_value.assert_not_called()

	def test_finish_uses_received_company_and_does_not_commit_early(self):
		self.state()
		self.db.exists.return_value = True
		with (
			patch(
				"frappe.get_doc",
				side_effect=[
					frappe._dict(
						enabled=1, streaming_branch="B1", company="Company One"
					),
					frappe._dict(
						name="Company One", country="Egypt", default_currency="EGP"
					),
				],
			),
			patch(
				"arab_streaming.streaming.connections.peer_state",
				return_value=frappe._dict(name="P1"),
			),
			patch("frappe.get_all", return_value=["frappe", "erpnext"]),
			patch("frappe.defaults.set_global_default") as defaults,
			patch("frappe.clear_cache"),
		):
			setup.finish_slave(
				frappe._dict(
					name="C1", doctype="Master Instance", restaurant_branch="B1"
				),
				None,
			)
			defaults.assert_any_call("company", "Company One")
			self.db.set_single_value.assert_any_call(
				"System Settings", "setup_complete", 1
			)
			self.db.commit.assert_not_called()

	def test_complete_status_requires_both_copy_and_setup_completion(self):
		self.state()
		doc = frappe._dict(
			syncing_status="Complete",
			progress=100,
			connection_status="Connected",
			exceptions=None,
		)
		with patch("frappe.get_doc", return_value=doc):
			self.assertFalse(setup.slave_status()["setup_complete"])
			self.fresh.return_value = True
			self.assertTrue(setup.slave_status()["setup_complete"])

	def test_store_link_deferral_is_only_for_authenticated_pending_setup(self):
		self.state()
		with patch.object(setup_company, "receiving_setup_company", return_value=False):
			self.assertEqual(
				setup.defer_initial_links(
					frappe._dict(name="C1"), {"doctype": "Store"}
				),
				[],
			)
		with patch.object(setup_company, "receiving_setup_company", return_value=True):
			self.assertEqual(
				setup.defer_initial_links(
					frappe._dict(name="OTHER"), {"doctype": "Store"}
				),
				[],
			)
			self.assertEqual(
				setup.defer_initial_links(
					frappe._dict(name="C1"), {"doctype": "Store"}
				),
				["default_preparation_area", "pos_profile"],
			)

	def test_install_defaults_preserves_existing_locale(self):
		self.db.get_single_value.return_value = "existing"
		setup.install_defaults()
		self.db.set_single_value.assert_not_called()
		self.db.get_single_value.return_value = None
		setup.install_defaults()
		self.db.set_single_value.assert_any_call("System Settings", "language", "en")
		self.db.set_single_value.assert_any_call("System Settings", "time_zone", "UTC")

	def test_migration_does_not_complete_a_failed_slave_with_company_scaffolds(self):
		self.state()
		self.db.get_value.return_value = "Failed"
		with patch("frappe.clear_cache"):
			setup.preserve_pending_slave_setup()
		self.db.set_value.assert_any_call(
			"Installed Application", {"app_name": "erpnext"}, "is_setup_complete", 0
		)
		self.db.set_single_value.assert_called_once_with(
			"System Settings", "setup_complete", 0
		)

	def test_migration_keeps_a_completed_slave_complete(self):
		self.state()
		self.db.get_value.return_value = "Complete"
		setup.preserve_pending_slave_setup()
		self.db.set_value.assert_not_called()
		self.db.set_single_value.assert_not_called()

	def test_setup_receiver_authority_requires_replay_and_the_paired_identity(self):
		self.state()
		with patch("arab_streaming.streaming.context.replay_source", return_value=None):
			self.assertFalse(setup_company.receiving_setup_company())
		with patch(
			"arab_streaming.streaming.context.replay_source", return_value="pairing"
		):
			self.db.exists.return_value = False
			self.assertFalse(setup_company.receiving_setup_company())
			self.db.exists.return_value = True
			self.assertTrue(setup_company.receiving_setup_company())
			self.fresh.return_value = True
			self.assertFalse(setup_company.receiving_setup_company())

	def test_company_generation_is_suppressed_only_inside_trusted_setup(self):
		company = object.__new__(setup_company.RMSSetupCompany)
		with (
			patch.object(setup_company.Company, "on_update") as native,
			patch.object(setup_company.NestedSet, "on_update") as tree,
			patch.object(setup_company, "receiving_setup_company", return_value=False),
		):
			company.on_update()
			native.assert_called_once()
			with setup_company.scaffolding():
				company.on_update()
			tree.assert_called_once_with(company)
			native.assert_called_once()

	def test_account_root_keeps_other_mandatory_fields_and_requires_trusted_setup(self):
		doc = object.__new__(setup_company.RMSSetupAccount)
		doc.is_group = 1
		doc.parent_account = None
		doc.root_type = "Asset"
		doc.is_new = Mock(return_value=True)
		missing = [("parent_account", "parent"), ("company", "company")]
		with (
			patch.object(
				setup_company.Account,
				"_get_missing_mandatory_fields",
				return_value=missing,
			),
			patch.object(setup_company, "receiving_setup_company", return_value=True),
		):
			self.assertEqual(
				doc._get_missing_mandatory_fields(), [("company", "company")]
			)
			doc.is_group = 0
			self.assertEqual(doc._get_missing_mandatory_fields(), missing)
			doc.is_group = 1
			doc.is_new.return_value = False
			self.assertEqual(doc._get_missing_mandatory_fields(), missing)
		with (
			patch.object(
				setup_company.Account,
				"_get_missing_mandatory_fields",
				return_value=missing,
			),
			patch.object(setup_company, "receiving_setup_company", return_value=False),
		):
			doc.is_new.return_value = True
			self.assertEqual(doc._get_missing_mandatory_fields(), missing)


def run_tests():
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(TestOnboarding)
	)
	if not result.wasSuccessful():
		raise AssertionError("RMS onboarding tests failed")
	return {"tests": result.testsRun, "passed": True}
