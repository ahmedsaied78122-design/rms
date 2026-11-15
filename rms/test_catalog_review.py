import unittest
from unittest.mock import patch
import frappe
from rms.rms.doctype.selling_product.selling_product import SellingProduct


class TestCatalogReview(unittest.TestCase):
	def test_existing_product_can_change_menu_category_without_moving_accounting_group(self):
		product = frappe.get_doc(
			dict(doctype="Selling Product", name="P", item="I", product_category="NEW-CATEGORY")
		)
		with (
			patch(
				"frappe.db.get_value",
				return_value=frappe._dict(enabled=1, is_group=0, item_group="DIFFERENT-GROUP"),
			),
			patch("frappe.db.set_value") as write,
		):
			product.validate_category()
		write.assert_not_called()
		self.assertEqual(product.item, "I")

	def test_disabled_or_unmapped_category_remains_rejected(self):
		product = frappe.get_doc(dict(doctype="Selling Product", product_category="C"))
		for enabled, item_group in [(0, "G"), (1, None)]:
			with patch(
				"frappe.db.get_value", return_value=frappe._dict(enabled=enabled, item_group=item_group)
			):
				with self.assertRaises(frappe.ValidationError):
					product.validate_category()

	def test_product_minimum_requires_enough_distinct_modifier_options(self):
		product = frappe.get_doc(
			dict(
				doctype="Selling Product",
				modifier_groups=[dict(modifier_group="SAUCES", min_selections=2, max_selections=3)],
				modifier_options=[dict(modifier_group="SAUCES", modifier_product="M1")],
			)
		)

		def value(dt, *a, **k):
			return frappe._dict(enabled=1, is_modifier=1, item="I") if dt == "Selling Product" else 1

		with patch("frappe.db.get_value", side_effect=value):
			with self.assertRaisesRegex(frappe.ValidationError, "available choices"):
				product.validate_modifiers()

	def test_duplicate_modifier_rows_do_not_count_as_two_choices(self):
		product = frappe.get_doc(
			dict(
				doctype="Selling Product",
				modifier_groups=[dict(modifier_group="G", min_selections=0, max_selections=2)],
				modifier_options=[
					dict(modifier_group="G", modifier_product="M"),
					dict(modifier_group="G", modifier_product="M"),
				],
			)
		)
		with patch(
			"frappe.db.get_value",
			side_effect=lambda dt, *a, **k: (
				frappe._dict(enabled=1, is_modifier=1, item="I") if dt == "Selling Product" else 1
			),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "only appear once"):
				product.validate_modifiers()

	def test_shared_category_warehouse_does_not_cross_company_boundaries(self):
		product = frappe.get_doc(dict(doctype="Selling Product", product_category="C", print_routes=[]))
		store = frappe._dict(company="COMPANY-A", default_warehouse="STORE-WAREHOUSE")
		category = frappe._dict(default_warehouse="CATEGORY-WAREHOUSE")
		for company, group, disabled, expected in [
			("COMPANY-B", 0, 0, "STORE-WAREHOUSE"),
			("COMPANY-A", 1, 0, "STORE-WAREHOUSE"),
			("COMPANY-A", 0, 1, "STORE-WAREHOUSE"),
			("COMPANY-A", 0, 0, "CATEGORY-WAREHOUSE"),
		]:
			with (
				patch("frappe.get_doc", side_effect=[store, category]),
				patch(
					"frappe.db.get_value",
					return_value=frappe._dict(company=company, is_group=group, disabled=disabled),
				),
			):
				self.assertEqual(product.get_effective_defaults("STORE")["warehouse"], expected)

	def test_order_controller_enforces_the_limits_of_each_product(self):
		from rms.rms.doctype.pos_order.pos_order import POSOrder
		from rms.snapshots import serialize_json_rows

		shared = frappe._dict(enabled=1, allow_multiple_selections=0, min_selections=1, max_selections=1)

		def product(name, minimum, maximum):
			return frappe._dict(
				name=name,
				title=name,
				enabled=1,
				product_category="C",
				has_options=0,
				item="I-" + name,
				uom="Nos",
				with_recipe=0,
				maintain_stock=0,
				store_availability=[],
				store_order_type_exclusions=[],
				modifier_groups=[
					frappe._dict(modifier_group="G", min_selections=minimum, max_selections=maximum)
				],
				modifier_options=[
					frappe._dict(modifier_group="G", modifier_product="M" + str(i), selling_price=i)
					for i in range(1, 5)
				],
				resolve_price=lambda *a, **k: {"selling_price": 100, "price_list": "PL"},
				get_effective_defaults=lambda *a: {"warehouse": None, "preparation_areas": []},
			)

		products = {"A": product("A", 1, 2), "B": product("B", 0, 3)}
		for i in range(1, 5):
			products["M" + str(i)] = frappe._dict(
				title="Modifier",
				enabled=1,
				is_modifier=1,
				item="M-I",
				store_availability=[],
				store_order_type_exclusions=[],
				with_recipe=0,
				maintain_stock=0,
				get_effective_defaults=lambda *a: {"warehouse": None, "preparation_areas": []},
			)
		for name, count, valid in [
			("A", 0, False),
			("A", 2, True),
			("A", 3, False),
			("B", 0, True),
			("B", 3, True),
			("B", 4, False),
			("B", -1, False),
			("B", -2, False),
		]:
			with self.subTest(product=name, choices=count):
				order = frappe.get_doc(
					dict(
						doctype="POS Order",
						store="S",
						restaurant_brand="BR",
						order_type="OT",
						cashier_session="CS",
						items=[
							dict(
								name="ROW",
								selling_product=name,
								qty=1,
								uom="Nos",
								modifiers=serialize_json_rows(
									[
										dict(modifier_group="G", modifier_product="M" + str(i), qty=1)
										for i in range(1, abs(count) + 1)
									]
								),
							)
						],
					)
				)
				if count == -1:
					order.items[0].modifiers = serialize_json_rows(
						[dict(modifier_group="G", modifier_product="M1", qty=-1)]
					)
				shared.enabled = 0 if count == -2 else 1
				with (
					patch("frappe.get_doc", side_effect=lambda dt, n: products[n]),
					patch("frappe.get_all", return_value=[]),
					patch(
						"frappe.db.get_value",
						side_effect=lambda dt, *a, **k: (
							shared if dt == "Modifier Group" else "PROFILE" if dt == "Cashier Session" else 0
						),
					),
					patch.object(order, "get_brand_menu_categories", return_value=["C"]),
					patch.object(order, "get_doc_before_save", return_value=None),
					patch.object(order, "build_recipe_snapshot"),
					patch.object(order, "calculate_tax_preview", return_value=(0, 100)),
					patch.object(order, "validate_discount"),
				):
					if valid:
						order.resolve_items()
					else:
						with self.assertRaises(frappe.ValidationError):
							order.resolve_items()
