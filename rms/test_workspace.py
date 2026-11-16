"""Workspace reachability and native role filtering are preserved."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import frappe
from frappe.desk.desktop import Workspace


DEFINITION = Path(__file__).parent / "rms/workspace/management/management.json"


class TestManagementWorkspace(unittest.TestCase):
	def setUp(self):
		self.definition = json.loads(DEFINITION.read_text())

	def test_all_rms_parent_forms_are_reachable_without_child_table_links(self):
		types = [json.loads(p.read_text()) for p in (Path(__file__).parent / 'rms/doctype').glob('*/*.json')]
		linked = {r['link_to'] for r in self.definition['links'] if r.get('link_type') == 'DocType'}
		parents = {d['name'] for d in types if not d.get('istable')}
		children = {d['name'] for d in types if d.get('istable')}
		self.assertTrue(parents <= linked, parents - linked)
		self.assertFalse(children & linked)

	def test_every_native_content_block_has_a_unique_existing_target(self):
		blocks = json.loads(self.definition['content'])
		self.assertEqual(len({b['id'] for b in blocks}), len(blocks))
		cards = [r['label'] for r in self.definition['links'] if r['type'] == 'Card Break']
		shortcuts = [r['label'] for r in self.definition['shortcuts']]
		self.assertEqual(len(cards), 9)
		for block in blocks:
			key = 'card_name' if block['type'] == 'card' else 'shortcut_name'
			self.assertIn(block['data'][key], cards if block['type'] == 'card' else shortcuts)
		self.assertEqual(len({(r.get('link_type'), r.get('link_to')) for r in self.definition['links'] if r['type'] == 'Link'}), sum(r['type']=='Link' for r in self.definition['links']))

	def test_workspace_references_installed_types_pages_and_reports(self):
		for row in self.definition['links'] + self.definition['shortcuts']:
			dt = row.get('link_type') or row['type']
			if dt not in ('DocType', 'Report', 'Page'): continue
			self.assertTrue(frappe.db.exists(dt, row['link_to']), (dt, row['link_to']))
			if dt == 'Report':
				self.assertEqual(row.get('report_ref_doctype'), frappe.db.get_value('Report', row['link_to'], 'ref_doctype'))

	def test_native_filter_omits_forbidden_links_and_empty_groups(self):
		workspace = Workspace.__new__(Workspace)
		workspace.doc = frappe.get_doc(self.definition)
		workspace.doc.hide_custom = 1
		workspace.can_read = ['POS Order', 'Cashier Session']
		workspace.restricted_doctypes = ['POS Order', 'Cashier Session']
		workspace.allowed_reports = {}
		workspace.allowed_pages = {'point-of-sale': {}}
		workspace.restricted_pages = ['point-of-sale']
		workspace._prepare_item = lambda item: item
		with patch('frappe.session', SimpleNamespace(user='fixture@example.invalid')):
			cards = workspace.get_links()
		self.assertEqual(len(cards), 1)
		self.assertEqual({r.link_to for r in cards[0]['links']}, {'POS Order', 'Cashier Session'})
		workspace.can_read = []
		with patch('frappe.session', SimpleNamespace(user='fixture@example.invalid')):
			self.assertEqual(workspace.get_links(), [])
