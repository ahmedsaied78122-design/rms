import base64
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from rms.recipe import get_additional_recipe_order_types
from rms.rms.doctype.product_category.product_category import ProductCategory
from rms.rms.doctype.selling_product.selling_product import SellingProduct
from frappe.utils.nestedset import NestedSet


def encode_order_types(names):
	return ",".join(
		base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")
		for name in names
	)


class TestSellingProductRecipeValidation(FrappeTestCase):
	def make_product(self, base_items, additional_rows=()):
		product = frappe.get_doc({"doctype": "Selling Product", "with_recipe": 1})
		for item in base_items:
			product.append("recipe", {"item": item, "qty": 1})
		for item, order_types in additional_rows:
			product.append(
				"additional_recipe",
				{"item": item, "qty": 1, "order_types": encode_order_types(order_types)},
			)
		return product

	def test_duplicate_base_item_is_rejected(self):
		product = self.make_product(["INGREDIENT-A", "INGREDIENT-A"])
		with patch.object(product, "validate_stock_item", return_value=SimpleNamespace(stock_uom="Nos", valuation_rate=1)):
			with self.assertRaisesRegex(frappe.ValidationError, "Base Recipe Item can only appear once"):
				product.validate_recipe()

	def test_additional_item_cannot_repeat_for_same_order_type(self):
		product = self.make_product(
			["BASE-A"],
			[("EXTRA-A", ["Dine In", "Takeaway"]), ("EXTRA-A", ["Takeaway"])],
		)
		with patch.object(product, "validate_stock_item", return_value=SimpleNamespace(stock_uom="Nos", valuation_rate=1)):
			with patch("frappe.db.get_value", return_value=1):
				with self.assertRaisesRegex(frappe.ValidationError, "Additional Recipe Item can only appear once per Order Type"):
					product.validate_recipe()

	def test_same_additional_item_for_disjoint_order_types_is_allowed(self):
		product = self.make_product(
			["BASE-A"],
			[("EXTRA-A", ["Dine In"]), ("EXTRA-A", ["Takeaway"])],
		)
		with patch.object(product, "validate_stock_item", return_value=SimpleNamespace(stock_uom="Nos", valuation_rate=1)):
			with patch("frappe.db.get_value", return_value=1):
				product.validate_recipe()

	def test_multiselect_tokens_round_trip_unicode_and_comma_names(self):
		names = ["Dine In", "توصيل، سريع", "Counter, Retail"]
		self.assertEqual(get_additional_recipe_order_types(encode_order_types(names)), names)

	def test_invalid_multiselect_token_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "invalid selection"):
			get_additional_recipe_order_types("not-a-token!")

	def test_lowest_numeric_priority_wins_even_when_a_more_specific_rule_matches(self):
		product = frappe.get_doc({"doctype": "Selling Product", "item": "ITEM-1", "uom": "Nos"})
		product.append("selling_prices", {
			"store": "STORE-1", "order_type": "Dine In", "restaurant_brand": "BRAND-1",
			"selling_price": 70, "priority": 2,
		})
		product.append("selling_prices", {
			"order_type": "Dine In", "selling_price": 80, "priority": 1,
		})
		list_for = lambda conditions, currency: "GENERAL" if not conditions.get("store") else "SPECIFIC"
		price_by_list = {"GENERAL": 80, "SPECIFIC": 70}
		with patch.object(product, "get_price_currencies", return_value=["EGP"]), \
				patch.object(product, "get_price_list_name", side_effect=list_for), \
				patch("frappe.db.get_value", side_effect=lambda doctype, filters, field: price_by_list[filters["price_list"]]):
			price = SellingProduct.resolve_price(product, "STORE-1", "Dine In", "BRAND-1")
		self.assertEqual(price, {"selling_price": 80, "price_list": "GENERAL"})

	def test_product_category_tree_has_nested_set_storage(self):
		meta = frappe.get_meta("Product Category")
		self.assertTrue(issubclass(ProductCategory, NestedSet))
		self.assertIsNotNone(meta.get_field("lft"))
		self.assertIsNotNone(meta.get_field("rgt"))
		self.assertIsNotNone(meta.get_field("old_parent"))

	def test_options_parent_allows_database_zero_price(self):
		product = SimpleNamespace(
			has_options=1, maintain_stock=0, option_products=[SimpleNamespace(option_product="OPTION-1")],
			with_recipe=0, recipe=[], additional_recipe=[], selling_price=0.0, selling_prices=[],
		)
		with patch("frappe.db.get_value", return_value=frappe._dict(enabled=1, has_options=0)):
			SellingProduct.validate_options_and_prices(product)

	def test_options_parent_rejects_a_real_price(self):
		product = SimpleNamespace(
			has_options=1, maintain_stock=0, option_products=[SimpleNamespace(option_product="OPTION-1")],
			with_recipe=0, recipe=[], additional_recipe=[], selling_price=10.0, selling_prices=[],
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Set prices on the option products"):
			SellingProduct.validate_options_and_prices(product)


class TestSellingProductPriceSync(FrappeTestCase):
	def test_reapplying_price_updates_the_existing_item_price(self):
		item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		currency = frappe.db.get_default("currency")
		self.assertTrue(item_group)
		self.assertTrue(currency)

		suffix = frappe.generate_hash(length=8).upper()
		item = frappe.get_doc({
			"doctype": "Item", "item_code": f"RMS-PRICE-TEST-{suffix}",
			"item_name": f"RMS Price Sync Test {suffix}", "item_group": item_group,
			"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1, "is_purchase_item": 0,
		}).insert(ignore_permissions=True)
		price_list = frappe.get_doc({
			"doctype": "Price List", "price_list_name": f"RMS-PRICE-TEST-{suffix}",
			"currency": currency, "enabled": 1, "buying": 0, "selling": 1,
			"price_not_uom_dependent": 0,
		}).insert(ignore_permissions=True)
		product = frappe.get_doc({"doctype": "Selling Product", "item": item.name, "uom": "Nos"})

		product.upsert_item_price(price_list.name, 10)
		product.upsert_item_price(price_list.name, 12)
		prices = frappe.get_all(
			"Item Price", filters={"item_code": item.name, "price_list": price_list.name},
			fields=["price_list_rate"],
		)

		self.assertEqual(len(prices), 1)
		self.assertEqual(prices[0].price_list_rate, 12)
