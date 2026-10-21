import hashlib
import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from rms.recipe import get_additional_recipe_order_types


class SellingProduct(Document):
	def before_insert(self):
		self.create_erpnext_item()

	def validate(self):
		self.validate_category()
		self.validate_item_ownership()
		self.validate_default_warehouse()
		self.validate_options_and_prices()
		self.validate_recipe()
		self.validate_store_rows()
		self.validate_modifiers()

	def on_update(self):
		if self.item and frappe.db.exists("Item", self.item):
			frappe.db.set_value(
				"Item", self.item, "disabled", 0 if self.enabled else 1, update_modified=False
			)
			self.sync_erpnext_prices()

	def get_effective_defaults(self, store):
		"""Resolve Store-specific product settings using Product → Category → Store fallback."""
		store_doc = frappe.get_doc("Store", store)
		category = frappe.get_doc("Product Category", self.product_category)

		warehouse = None
		if self.default_store == store:
			warehouse = self.default_warehouse
		if not warehouse:
			warehouse = category.default_warehouse
		if not warehouse:
			warehouse = store_doc.default_warehouse

		preparation_areas = [
			row.preparation_area for row in self.print_routes if row.store == store
		]
		if not preparation_areas and category.default_preparation_area:
			category_store = frappe.db.get_value(
				"Preparation Area", category.default_preparation_area, "store"
			)
			if category_store == store:
				preparation_areas = [category.default_preparation_area]
		if not preparation_areas and store_doc.default_preparation_area:
			preparation_areas = [store_doc.default_preparation_area]

		return {"warehouse": warehouse, "preparation_areas": preparation_areas}

	def create_erpnext_item(self):
		if self.item:
			frappe.throw(_("The ERPNext Item is created automatically and cannot be selected manually."))

		if not self.product_category or not self.uom:
			frappe.throw(_("Select a Product Category and Unit of Measure before saving."))

		category = frappe.get_doc("Product Category", self.product_category)
		if not category.enabled or category.is_group or not category.item_group:
			frappe.throw(_("Select an enabled leaf Product Category with an Item Group."))

		item_code = make_autoname("RMS-ITEM-.YYYY.-.#####")
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": self.title,
				"item_group": category.item_group,
				"stock_uom": self.uom,
				"is_stock_item": 1 if self.maintain_stock else 0,
				"is_sales_item": 1,
				"is_purchase_item": 0,
				"disabled": 0 if self.enabled else 1,
				"image": self.image,
			}
		).insert()
		self.item = item.name

	def validate_category(self):
		if not self.product_category:
			return
		category = frappe.db.get_value(
			"Product Category", self.product_category, ["enabled", "is_group", "item_group"], as_dict=True
		)
		if not category or not category.enabled or category.is_group or not category.item_group:
			frappe.throw(_("Select an enabled leaf Product Category with an Item Group."))
		if self.item and frappe.db.exists("Item", self.item):
			item_group = frappe.db.get_value("Item", self.item, "item_group")
			if item_group != category.item_group:
				frappe.throw(
					_("The Product Category Item Group cannot change after the linked Item is created.")
				)

	def validate_item_ownership(self):
		if self.item and frappe.db.exists(
			"Selling Product", {"item": self.item, "name": ["!=", self.name or ""]}
		):
			frappe.throw(_("Each Selling Product must own a unique ERPNext Item."))
		if self.item and frappe.db.exists("Item", self.item):
			item = frappe.db.get_value("Item", self.item, ["stock_uom", "is_stock_item"], as_dict=True)
			if item.stock_uom != self.uom or bool(item.is_stock_item) != bool(self.maintain_stock):
				frappe.throw(_("Unit of Measure and Maintain Stock must match the linked ERPNext Item."))

	def validate_default_warehouse(self):
		if bool(self.default_store) != bool(self.default_warehouse):
			frappe.throw(_("Choose both Store and Warehouse, or leave both empty to use fallback defaults."))
		if self.default_store and not frappe.db.get_value("Store", self.default_store, "enabled"):
			frappe.throw(_("The selected Store is disabled."))
		if self.default_store and self.default_warehouse:
			store_company = frappe.db.get_value("Store", self.default_store, "company")
			warehouse = frappe.db.get_value(
				"Warehouse", self.default_warehouse, ["company", "is_group", "disabled"], as_dict=True
			)
			if not warehouse or warehouse.company != store_company or warehouse.is_group or warehouse.disabled:
				frappe.throw(_("Default Warehouse must be an enabled leaf Warehouse belonging to the selected Store's Company."))

	def sync_erpnext_prices(self):
		"""Compile product rates into standard ERPNext Price Lists and Item Prices."""
		desired = {}
		can_sell = self.enabled and not self.has_options and (
			not self.is_modifier or self.can_be_sold_separately
		)
		if can_sell and self.selling_price is not None:
			for currency in self.get_price_currencies():
				price_list = self.get_price_list_name({}, currency)
				desired[price_list] = self.selling_price

		if can_sell:
			for row in self.selling_prices:
				for currency in self.get_price_currencies(row.store):
					conditions = {
						"store": row.store or "",
						"order_type": row.order_type or "",
						"restaurant_brand": row.restaurant_brand or "",
					}
					price_list = self.get_price_list_name(conditions, currency)
					desired[price_list] = row.selling_price

		for price_list_name, rate in desired.items():
			price_list = self.ensure_selling_price_list(price_list_name, self.get_price_list_currency(price_list_name))
			self.upsert_item_price(price_list, rate)

		stale_prices = frappe.get_all(
			"Item Price",
			filters={"item_code": self.item, "price_list": ["like", "RMS-SALES-%"]},
			fields=["name", "price_list"],
		)
		for item_price in stale_prices:
			if item_price.price_list not in desired:
				frappe.delete_doc("Item Price", item_price.name, ignore_permissions=True, force=True)

	def get_price_currencies(self, store=None):
		if store:
			stores = [store]
		else:
			stores = frappe.get_all("Store", filters={"enabled": 1}, pluck="name")

		currencies = set()
		for store_name in stores:
			company = frappe.db.get_value("Store", store_name, "company")
			currency = frappe.db.get_value("Company", company, "default_currency") if company else None
			if currency:
				currencies.add(currency)

		if not currencies:
			currency = frappe.db.get_default("currency")
			if currency:
				currencies.add(currency)
		if not currencies:
			frappe.throw(_("Set a default currency before adding Selling Product prices."))
		return sorted(currencies)

	def get_price_list_name(self, conditions, currency):
		key = json.dumps([conditions, currency], sort_keys=True, separators=(",", ":"))
		digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:14].upper()
		labels = []
		if conditions.get("store"):
			labels.append(frappe.db.get_value("Store", conditions["store"], "store_code") or conditions["store"])
		else:
			labels.append("ANY-STORE")
		if conditions.get("order_type"):
			labels.append(conditions["order_type"])
		else:
			labels.append("ANY-TYPE")
		if conditions.get("restaurant_brand"):
			labels.append(
				frappe.db.get_value("Restaurant Brand", conditions["restaurant_brand"], "brand_code")
				or conditions["restaurant_brand"]
			)
		else:
			labels.append("ANY-BRAND")
		slug = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").upper()[:18] for label in labels)
		return f"RMS-SALES-{currency}-{slug}-{digest}"

	def get_price_list_currency(self, price_list_name):
		for currency in self.get_price_currencies():
			if self.get_price_list_name({}, currency) == price_list_name:
				return currency
		for row in self.selling_prices:
			for currency in self.get_price_currencies(row.store):
				conditions = {
					"store": row.store or "",
					"order_type": row.order_type or "",
					"restaurant_brand": row.restaurant_brand or "",
				}
				if self.get_price_list_name(conditions, currency) == price_list_name:
					return currency
		frappe.throw(_("Unable to resolve currency for generated Price List {0}.").format(price_list_name))

	def ensure_selling_price_list(self, name, currency):
		if frappe.db.exists("Price List", name):
			price_list = frappe.get_doc("Price List", name)
			if not price_list.enabled or not price_list.selling or price_list.currency != currency:
				price_list.enabled = 1
				price_list.buying = 0
				price_list.selling = 1
				price_list.currency = currency
				price_list.save(ignore_permissions=True)
			return name

		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": name,
				"currency": currency,
				"enabled": 1,
				"buying": 0,
				"selling": 1,
				"price_not_uom_dependent": 0,
			}
		).insert(ignore_permissions=True)
		return name

	def upsert_item_price(self, price_list, rate):
		filters = {
			"item_code": self.item,
			"price_list": price_list,
			"uom": self.uom,
			"customer": ["is", "not set"],
			"supplier": ["is", "not set"],
			"batch_no": ["is", "not set"],
		}
		item_price_name = frappe.db.get_value("Item Price", filters, "name")
		if item_price_name:
			item_price = frappe.get_doc("Item Price", item_price_name)
			if item_price.price_list_rate == rate and item_price.selling and not item_price.buying:
				return
			item_price.price_list_rate = rate
			item_price.selling = 1
			item_price.buying = 0
			item_price.save(ignore_permissions=True)
			return

		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": self.item,
				"price_list": price_list,
				"uom": self.uom,
				"price_list_rate": rate,
				"selling": 1,
				"buying": 0,
			}
		).insert(ignore_permissions=True)

	def resolve_price(self, store, order_type, restaurant_brand, strict=True):
		"""Return the applicable price list; the lowest numeric Priority wins."""
		matches = []
		for row in self.selling_prices:
			if row.store and row.store != store:
				continue
			if row.order_type and row.order_type != order_type:
				continue
			if row.restaurant_brand and row.restaurant_brand != restaurant_brand:
				continue
			specificity = sum(bool(value) for value in (row.store, row.order_type, row.restaurant_brand))
			matches.append((row.priority, -specificity, row.name or "", row))

		if matches:
			row = min(matches)[-1]
			currency = self.get_price_currencies(store)[0]
			conditions = {
				"store": row.store or "",
				"order_type": row.order_type or "",
				"restaurant_brand": row.restaurant_brand or "",
			}
			price_list = self.get_price_list_name(conditions, currency)
			rate = frappe.db.get_value(
				"Item Price",
				{"item_code": self.item, "price_list": price_list, "uom": self.uom},
				"price_list_rate",
			)
			return {"selling_price": rate if rate is not None else row.selling_price, "price_list": price_list}

		currency = self.get_price_currencies(store)[0]
		if self.selling_price is None:
			if strict:
				frappe.throw(_("No Selling Price matches this Store, Order Type, and Brand."))
			return None
		price_list = self.get_price_list_name({}, currency)
		rate = frappe.db.get_value(
			"Item Price",
			{"item_code": self.item, "price_list": price_list, "uom": self.uom},
			"price_list_rate",
		)
		return {"selling_price": rate if rate is not None else self.selling_price, "price_list": price_list}

	def validate_options_and_prices(self):
		if self.has_options:
			if self.maintain_stock:
				frappe.throw(_("An Options parent cannot also be maintained as a stock product."))
			if not self.option_products:
				frappe.throw(_("Add at least one option product."))
			if self.with_recipe or self.recipe or self.additional_recipe:
				frappe.throw(_("An options parent cannot have a recipe."))
			if self.selling_price not in (None, 0) or self.selling_prices:
				frappe.throw(_("Set prices on the option products, not on the options parent."))
			for row in self.option_products:
				option = frappe.db.get_value(
					"Selling Product", row.option_product, ["enabled", "has_options"], as_dict=True
				)
				if not option or not option.enabled:
					frappe.throw(_("Each option must be an enabled Selling Product."))
				if row.option_product == self.name or self.option_graph_reaches(row.option_product, self.name):
					frappe.throw(_("Selling Product options cannot contain a cycle."))
		else:
			if self.with_recipe and self.selling_price is not None and self.selling_price < 0:
				frappe.throw(_("Selling Price cannot be negative."))

		seen_rules = set()
		for row in self.selling_prices:
			if not row.store and not row.order_type and not row.restaurant_brand:
				frappe.throw(_("Each conditional price needs at least one condition."))
			key = (row.store or "", row.order_type or "", row.restaurant_brand or "")
			if key in seen_rules:
				frappe.throw(_("A conditional price condition set can only appear once."))
			seen_rules.add(key)
			if row.priority is None or row.priority < 0:
				frappe.throw(_("Priority must be zero or a positive number; lower numbers take precedence."))
			if row.store and not frappe.db.get_value("Store", row.store, "enabled"):
				frappe.throw(_("Price rules cannot target a disabled Store."))
			if row.order_type and not frappe.db.get_value("Order Type", row.order_type, "enabled"):
				frappe.throw(_("Price rules cannot target a disabled Order Type."))
			if row.restaurant_brand and not frappe.db.get_value("Restaurant Brand", row.restaurant_brand, "enabled"):
				frappe.throw(_("Price rules cannot target a disabled Brand."))
			if row.store and row.restaurant_brand and not frappe.db.exists(
				"Store Brand Assignment",
				{
					"parent": row.store,
					"parenttype": "Store",
					"restaurant_brand": row.restaurant_brand,
				},
			):
				frappe.throw(_("Price rule Brand must be assigned to its Store."))

	def option_graph_reaches(self, product_name, target_name, visited=None):
		visited = visited or set()
		if product_name == target_name:
			return True
		if product_name in visited:
			return False
		visited.add(product_name)
		for child in frappe.get_all("Selling Product Option", filters={"parent": product_name, "parenttype": "Selling Product"}, pluck="option_product"):
			if self.option_graph_reaches(child, target_name, visited):
				return True
		return False

	def validate_recipe(self):
		if self.with_recipe and self.maintain_stock:
			frappe.throw(_("Choose either a stock Item or a Recipe; a product cannot be both."))
		if not self.with_recipe:
			if self.recipe or self.additional_recipe:
				frappe.throw(_("Recipe rows require With Recipe to be enabled."))
			return

		if self.has_options:
			frappe.throw(_("An options parent cannot have a recipe."))
		if not self.recipe:
			frappe.throw(_("With Recipe requires at least one Base Recipe row."))

		base_items = set()
		for row in self.recipe:
			if row.item in base_items:
				frappe.throw(_("A Base Recipe Item can only appear once."))
			base_items.add(row.item)
			item = self.validate_stock_item(row.item)
			row.uom = item.stock_uom
			row.cost = item.valuation_rate or 0
			if not row.qty or row.qty <= 0:
				frappe.throw(_("Recipe quantities must be greater than zero."))
			if row.sub_recipe:
				bom = frappe.db.exists(
					"BOM",
					{"item": row.item, "is_active": 1, "docstatus": 1},
				)
				if not bom:
					frappe.throw(_("Sub Recipe requires an active, submitted BOM for Item {0}.").format(row.item))
			elif row.multi_level:
				frappe.throw(_("Multi-Level can only be selected when Sub Recipe is enabled."))

		additional_item_types = set()
		for row in self.additional_recipe:
			item = self.validate_stock_item(row.item)
			row.uom = item.stock_uom
			row.cost = item.valuation_rate or 0
			if not row.qty or row.qty <= 0:
				frappe.throw(_("Additional Recipe quantities must be greater than zero."))
			if not row.order_types:
				frappe.throw(_("Choose at least one Order Type for each Additional Recipe row."))
			order_types = get_additional_recipe_order_types(row.order_types)
			if not order_types:
				frappe.throw(_("Choose at least one Order Type for each Additional Recipe row."))
			for order_type in order_types:
				if not frappe.db.get_value("Order Type", order_type, "enabled"):
					frappe.throw(_("Order Type {0} is disabled.").format(frappe.bold(order_type)))
				key = (row.item, order_type)
				if key in additional_item_types:
					frappe.throw(_("An Additional Recipe Item can only appear once per Order Type."))
				additional_item_types.add(key)

	def validate_stock_item(self, item_code):
		item = (
			frappe.db.get_value(
				"Item", item_code, ["is_stock_item", "disabled", "stock_uom", "valuation_rate"], as_dict=True
			)
			if item_code
			else None
		)
		if not item or not item.is_stock_item or item.disabled:
			frappe.throw(_("Recipe components must be ERPNext Items with Maintain Stock enabled."))
		return item

	def validate_store_rows(self):
		availability_stores = [row.store for row in self.store_availability if row.store]
		if len(availability_stores) != len(set(availability_stores)):
			frappe.throw(_("Store Availability can only have one row per Store."))
		for store in availability_stores:
			if not frappe.db.get_value("Store", store, "enabled"):
				frappe.throw(_("Store Availability must reference an enabled Store."))

		exclusions = [(row.store, row.order_type) for row in self.store_order_type_exclusions]
		if len(exclusions) != len(set(exclusions)):
			frappe.throw(_("A Store and Order Type exclusion can only appear once."))
		for store, order_type in exclusions:
			if not frappe.db.get_value("Store", store, "enabled"):
				frappe.throw(_("Order Type exclusions must reference an enabled Store."))
			if not frappe.db.get_value("Order Type", order_type, "enabled"):
				frappe.throw(_("Order Type exclusions must reference an enabled Order Type."))

		for row in self.print_routes:
			area = frappe.db.get_value(
				"Preparation Area", row.preparation_area, ["store", "enabled", "has_kds", "has_printer"], as_dict=True
			)
			if not area or area.store != row.store or not area.enabled:
				frappe.throw(_("Preparation Area must belong to the Store selected on its print route."))
			if not area.has_kds and not area.has_printer:
				frappe.throw(_("Preparation Area must have KDS or Printer output enabled before it can be routed."))

		pairs = [(row.store, row.preparation_area) for row in self.print_routes]
		if len(pairs) != len(set(pairs)):
			frappe.throw(_("A Store and Preparation Area print route can only appear once."))

	def validate_modifiers(self):
		groups = [row.modifier_group for row in self.modifier_groups if row.modifier_group]
		if len(groups) != len(set(groups)):
			frappe.throw(_("A Modifier Group can only be added once."))
		for group in groups:
			if not frappe.db.get_value("Modifier Group", group, "enabled"):
				frappe.throw(_("Modifier Group {0} is disabled.").format(frappe.bold(group)))

		configured = set(groups)
		for row in self.modifier_options:
			if row.modifier_group not in configured:
				frappe.throw(_("Every Modifier Option must belong to a Modifier Group enabled on this product."))
			modifier = frappe.db.get_value(
				"Selling Product", row.modifier_product, ["enabled", "is_modifier", "item"], as_dict=True
			)
			if not modifier or not modifier.enabled or not modifier.is_modifier:
				frappe.throw(_("Modifier Options must reference enabled products marked Is Modifier."))
			row.cost = frappe.db.get_value("Item", modifier.item, "valuation_rate") or 0
