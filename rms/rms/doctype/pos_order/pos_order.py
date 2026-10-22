import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime
from erpnext.stock.stock_ledger import is_negative_stock_allowed

from rms.recipe import get_recipe_components
from rms.snapshots import parse_json_rows, serialize_json_rows
from rms.taxes import apply_order_discount, apply_order_tax_template, prevent_pos_item_price_autoinsert
from rms.utils import get_business_date


def get_active_order_item_qty(qty, cancelled_qty=0):
	return max(flt(qty) - flt(cancelled_qty), 0)


def calculate_order_item_amount(qty, selling_price, modifiers, cancelled_qty=0):
	active_qty = get_active_order_item_qty(qty, cancelled_qty)
	return active_qty * flt(selling_price) + sum(
		active_qty * flt(modifier.qty) * flt(modifier.selling_price) for modifier in modifiers
	)


def validate_confirmed_item_cancellation(status, sent_to_kitchen, qty, cancelled_qty, cancellation_qty, reason, is_manager):
	if status not in ("Confirmed", "In Preparation", "Ready"):
		frappe.throw(_("Only confirmed, unpaid order items can be cancelled."))
	if not sent_to_kitchen:
		frappe.throw(_("This item has not been sent to preparation; remove it from the open order instead."))
	if not is_manager:
		frappe.throw(_("A POS Manager must approve cancellation of an item already sent to preparation."), frappe.PermissionError)
	reason = reason.strip() if isinstance(reason, str) else ""
	if not reason:
		frappe.throw(_("Enter a reason for cancelling this item."))
	if len(reason) > 250:
		frappe.throw(_("Cancellation reason cannot exceed 250 characters."))
	cancellation_qty = flt(cancellation_qty)
	remaining_qty = get_active_order_item_qty(qty, cancelled_qty)
	if cancellation_qty <= 0 or cancellation_qty > remaining_qty:
		frappe.throw(_("Cancellation quantity must be positive and no greater than the remaining quantity."))
	return cancellation_qty


def validate_modifier_group_selection(modifiers, single_selection_groups):
	"""Reject multiple selected modifier products from a single-choice group."""
	selected_single_groups = set()
	for modifier in modifiers:
		group = modifier.get("modifier_group")
		if group in single_selection_groups and group in selected_single_groups:
			frappe.throw(_("Choose only one option from Modifier Group {0}.").format(group))
		selected_single_groups.add(group)


def normalize_dining_context(require_table, dining_area=None, dining_table=None):
	"""Keep table assignments only on order types configured for table service."""
	return (dining_area, dining_table) if require_table else (None, None)


def ensure_order_items_append_only(previous_items, current_items):
	"""Return new rows while protecting every previously saved order line."""
	previous_items = list(previous_items or [])
	current_items = list(current_items or [])
	if len(current_items) <= len(previous_items) or current_items[:len(previous_items)] != previous_items:
		frappe.throw(_("Confirmed items cannot be edited or removed."))
	return current_items[len(previous_items):]


def normalize_guest_checks_for_lock(guest_checks):
	"""Keep confirmed guest identities and their item quantities stable."""
	checks = []
	for check in guest_checks or []:
		items = check.get("items_json") or "[]"
		items = frappe.parse_json(items) if isinstance(items, str) else items
		allocations = []
		for item in items or []:
			if isinstance(item, str):
				allocations.append((item, None))
			elif isinstance(item, dict):
				allocations.append((item.get("name"), flt(item.get("qty")) if item.get("qty") is not None else None))
		allocations.sort(key=lambda row: row[0] or "")
		checks.append((check.get("guest_name"), tuple(allocations)))
	return checks


def ensure_confirmed_guest_checks_unchanged(previous, current):
	"""Reject order item or split edits after guest checks have been confirmed."""
	if not previous or not previous.guest_checks:
		return
	if POSOrder.serialize_order_items(previous) != POSOrder.serialize_order_items(current):
		frappe.throw(_("Order items cannot be changed after guest checks are confirmed."))
	if normalize_guest_checks_for_lock(previous.guest_checks) != normalize_guest_checks_for_lock(current.guest_checks):
		frappe.throw(_("Guest checks are confirmed and cannot be changed."))


def ensure_guest_check_item_append_only(previous, current):
	"""Allow new order rows only when all are assigned to the first open check."""
	previous_items = POSOrder.serialize_order_items(previous)
	current_items = POSOrder.serialize_order_items(current)
	ensure_order_items_append_only(previous_items, current_items)
	old_checks = list(previous.guest_checks or [])
	new_checks = list(current.guest_checks or [])
	if len(old_checks) != len(new_checks) or [row.name for row in old_checks] != [row.name for row in new_checks]:
		frappe.throw(_("Guest checks cannot be added or removed while adding order items."))
	target = next((row for row in old_checks if row.status == "Open"), None)
	if not target or len(current_items) <= len(previous_items):
		frappe.throw(_("New items can only be added to an open guest check."))
	target_name = target.name
	old_by_name = {row.name: row for row in old_checks}
	new_by_name = {row.name: row for row in new_checks}
	old_item_names = {row.name for row in previous.items}
	new_item_names = [row.name for row in current.items if row.name not in old_item_names]
	for name, old in old_by_name.items():
		new = new_by_name[name]
		if old.guest_name != new.guest_name or old.status != new.status or old.pos_invoice != new.pos_invoice:
			frappe.throw(_("Guest check identity and payment status cannot change while adding items."))
		old_allocations = frappe.parse_json(old.items_json or "[]") if isinstance(old.items_json, str) else old.items_json
		new_allocations = frappe.parse_json(new.items_json or "[]") if isinstance(new.items_json, str) else new.items_json
		if name != target_name:
			if normalize_guest_checks_for_lock([old]) != normalize_guest_checks_for_lock([new]):
				frappe.throw(_("Only the first open guest check can receive new items."))
		elif old_allocations != new_allocations[:len(old_allocations)] or len(new_allocations) != len(old_allocations) + len(new_item_names):
			frappe.throw(_("New items must be assigned to the first open guest check."))
		else:
			new_allocations = new_allocations[len(old_allocations):]
			current_by_name = {row.name: get_active_order_item_qty(row.qty, row.cancelled_qty) for row in current.items}
			if {row.get("name") for row in new_allocations if isinstance(row, dict)} != set(new_item_names) or any(
				flt(allocation.get("qty")) != flt(current_by_name.get(allocation.get("name")))
				for allocation in new_allocations if isinstance(allocation, dict)
			):
				frappe.throw(_("New items must be assigned to the first open guest check."))


def option_tree_contains(parent_name, product_name, visited=None):
	if parent_name == product_name:
		return True
	visited = visited or set()
	if parent_name in visited:
		return False
	visited.add(parent_name)
	children = frappe.get_all("Selling Product Option", filters={"parent": parent_name, "parenttype": "Selling Product"}, pluck="option_product")
	return any(option_tree_contains(child, product_name, visited) for child in children)


def calculate_discount_amount(subtotal, tax_total, discount_type, discount_value, discount_scope, grand_total=None):
	base = flt(subtotal) if discount_scope == "Net Total" else flt(grand_total if grand_total is not None else flt(subtotal) + flt(tax_total))
	if discount_type == "Percentage":
		amount = base * flt(discount_value) / 100
	else:
		amount = flt(discount_value)
	return flt(min(max(amount, 0), max(base, 0)), 2)


class POSOrder(Document):
	def before_insert(self):
		self.status = "Open"
		self.business_date = (
			frappe.db.get_value("Cashier Session", self.cashier_session, "business_date")
			if self.cashier_session else None
		) or get_business_date(self.store)

	def validate(self):
		self.normalize_check_label()
		previous = self.get_doc_before_save()
		if previous:
			if self.flags.get("allow_guest_check_item_append"):
				ensure_guest_check_item_append_only(previous, self)
			elif self.flags.get("allow_guest_check_resplit"):
				if self.serialize_order_items(previous) != self.serialize_order_items(self):
					frappe.throw(_("Order items cannot be changed while splitting an open guest check."))
			else:
				ensure_confirmed_guest_checks_unchanged(previous, self)
		self.validate_transition()
		if previous and previous.status in ("Confirmed", "In Preparation", "Ready", "Paid", "Cancelled"):
			if self.flags.get("allow_item_cancellation") and previous.status in ("Confirmed", "In Preparation", "Ready"):
				self.recalculate_cancelled_item_amounts()
				if self.status == "Cancelled":
					self.validate_terminal_state()
				else:
					self.validate_payment_state()
				return
			if self.status == "Paid":
				self.validate_payment_state()
				self.validate_terminal_state()
				return
			if self.status == "Cancelled":
				self.validate_terminal_state()
				return
			if self.flags.get("allow_order_item_append") and previous.status in ("Confirmed", "In Preparation", "Ready"):
				self.validate_context()
				ensure_order_items_append_only(
					self.serialize_order_items(previous), self.serialize_order_items(self)
				)
				self.resolve_items(self.items[len(previous.items):])
				self.validate_payment_state()
				if self.flags.get("allow_guest_check_item_append"):
					target = next(row for row in self.guest_checks if row.status == "Open")
					previous_target = next(row for row in previous.guest_checks if row.name == target.name)
					target.grand_total = max(0, flt(previous_target.grand_total) + flt(self.grand_total) - flt(previous.grand_total))
				return
			if self.flags.get("allow_discount_update") and previous.status in ("Confirmed", "In Preparation", "Ready"):
				self.validate_discount(self.subtotal, self.tax_total, self.grand_total)
				self.discount_amount = calculate_discount_amount(
					self.subtotal, self.tax_total, self.discount_type or "Percentage", self.discount_value or 0,
					self.discount_scope or "Net Total", self.grand_total,
				)
				self.tax_total, self.grand_total = self.calculate_tax_preview(apply_discount=True)
				self.validate_payment_state()
				return
			return
		self.validate_context()
		if self.status == "Paid":
			self.validate_payment_state()
			self.validate_terminal_state()
			return
		if self.status == "Cancelled":
			self.validate_terminal_state()
			return
		self.resolve_items()
		self.validate_payment_state()

	def validate_transition(self):
		previous = self.get_doc_before_save()
		if not previous:
			if self.status != "Open":
				frappe.throw(_("A new POS Order must start Open."))
			return

		allowed = {
			"Open": {"Open", "Pending Confirmation", "Confirmed", "Cancelled"},
			"Pending Confirmation": {"Pending Confirmation", "Confirmed", "Cancelled"},
			"Confirmed": {"Confirmed", "In Preparation", "Ready", "Paid", "Cancelled"},
			"In Preparation": {"In Preparation", "Ready", "Paid", "Cancelled"},
			"Ready": {"Ready", "Paid", "Cancelled"},
			"Paid": {"Paid"},
			"Cancelled": {"Cancelled"},
		}
		if self.status not in allowed.get(previous.status, set()):
			frappe.throw(_("Invalid POS Order status change from {0} to {1}.").format(previous.status, self.status))
		if previous.status in ("Confirmed", "In Preparation", "Ready", "Paid", "Cancelled"):
			self.compare_locked_snapshot(previous)

	def compare_locked_snapshot(self, previous):
		locked_fields = (
			"store",
			"restaurant_brand",
			"order_type",
			"cashier_session",
			"business_date",
			"sales_taxes_and_charges_template",
			"customer",
			"external_reference",
			"dining_area",
			"dining_table",
			"check_label",
			"discount_type",
			"discount_scope",
			"discount_value",
			"discount_amount",
			"discount_reason",
		)
		for fieldname in locked_fields:
			if self.flags.get("allow_item_cancellation") and fieldname == "discount_amount":
				continue
			if self.flags.get("allow_discount_update") and fieldname in (
				"discount_type", "discount_scope", "discount_value", "discount_amount", "discount_reason"
			):
				continue
			if self.flags.get("allow_table_transfer") and fieldname in ("dining_area", "dining_table"):
				continue
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(_("Order context cannot change after confirmation."))
		current_items = self.serialize_order_items()
		previous_items = self.serialize_order_items(previous)
		if self.flags.get("allow_item_cancellation"):
			self.validate_item_cancellation_change(previous)
		elif self.flags.get("allow_order_item_append"):
			ensure_order_items_append_only(previous_items, current_items)
		elif current_items != previous_items:
			frappe.throw(_("Order items cannot be edited after they are confirmed."))

	def serialize_order_items(self, document=None):
		document = document or self
		fields = ("selling_product", "option_parent", "item", "qty", "cancelled_qty", "uom", "selling_price", "price_list", "amount", "warehouse", "preparation_area", "notes")
		serialized = []
		for row in document.items:
			serialized.append(
				{
					"values": {fieldname: row.get(fieldname) for fieldname in fields},
					"modifiers": sorted(
						(
							modifier.modifier_group,
							modifier.modifier_product,
							flt(modifier.qty),
							flt(modifier.selling_price),
						)
						for modifier in parse_json_rows(row.modifiers)
					),
					"recipe": sorted(
						(
							component.item,
							flt(component.qty),
							component.uom,
							component.warehouse,
						)
						for component in parse_json_rows(row.recipe_snapshot)
					),
				}
			)
		return serialized

	def validate_item_cancellation_change(self, previous):
		previous_rows = list(previous.items or [])
		current_rows = list(self.items or [])
		if len(previous_rows) != len(current_rows):
			frappe.throw(_("Confirmed order items cannot be added or removed during cancellation."))
		protected_fields = (
			"selling_product", "option_parent", "item", "qty", "uom", "selling_price", "price_list",
			"warehouse", "preparation_area", "notes", "modifiers", "recipe_snapshot", "sent_to_kitchen",
		)
		previous_by_name = {row.name: row for row in previous_rows}
		current_by_name = {row.name: row for row in current_rows}
		if set(previous_by_name) != set(current_by_name):
			frappe.throw(_("Confirmed order items cannot be replaced during cancellation."))
		for name, old_row in previous_by_name.items():
			new_row = current_by_name[name]
			if any(old_row.get(fieldname) != new_row.get(fieldname) for fieldname in protected_fields):
				frappe.throw(_("Cancellation cannot edit any confirmed item details."))
			old_cancelled = flt(old_row.cancelled_qty or 0)
			new_cancelled = flt(new_row.cancelled_qty or 0)
			if new_cancelled < old_cancelled or new_cancelled > flt(old_row.qty):
				frappe.throw(_("Cancelled quantity must increase without exceeding the ordered quantity."))

		old_events = [self.serialize_item_cancellation(row) for row in (previous.item_cancellations or [])]
		new_events = [self.serialize_item_cancellation(row) for row in (self.item_cancellations or [])]
		if new_events[:len(old_events)] != old_events or len(new_events) <= len(old_events):
			frappe.throw(_("Item cancellation history is append-only."))
		new_cancellations = list(self.item_cancellations or [])[len(old_events):]
		old_by_name = previous_by_name
		cancelled_deltas = {name: flt(current_by_name[name].cancelled_qty or 0) - flt(old_by_name[name].cancelled_qty or 0)
			for name in old_by_name}
		roles = set(frappe.get_roles(frappe.session.user))
		is_manager = bool(roles & {"POS Manager", "System Manager"})
		new_events_by_item = {}
		for event in new_cancellations:
			row = current_by_name.get(event.pos_order_item)
			if not row:
				frappe.throw(_("Cancellation history must reference an item on this order."))
			qty = validate_confirmed_item_cancellation(
				previous.status, row.sent_to_kitchen, row.qty, old_by_name[row.name].cancelled_qty or 0,
				event.qty, event.reason, is_manager,
			)
			new_events_by_item[row.name] = new_events_by_item.get(row.name, 0) + qty
			if event.cancelled_by != frappe.session.user or not event.cancelled_at:
				frappe.throw(_("Item cancellation history must record its actor and time."))
		for name, delta in cancelled_deltas.items():
			if abs(delta - new_events_by_item.get(name, 0)) > 0.0001:
				frappe.throw(_("Cancelled quantities must match the append-only cancellation history."))

	@staticmethod
	def serialize_item_cancellation(row):
		return (row.pos_order_item, flt(row.qty), (row.reason or "").strip(), row.cancelled_by, row.cancelled_at)

	def recalculate_cancelled_item_amounts(self):
		for row in self.items:
			row.amount = calculate_order_item_amount(row.qty, row.selling_price, parse_json_rows(row.modifiers), row.cancelled_qty)
		self.recalculate_order_totals()

	def recalculate_order_totals(self):
		self.subtotal = sum(flt(row.amount) for row in self.items)
		if not any(get_active_order_item_qty(row.qty, row.cancelled_qty) > 0 for row in self.items):
			self.discount_amount = 0
			self.tax_total = 0
			self.grand_total = 0
			return
		normal_tax_total, normal_grand_total = self.calculate_tax_preview()
		self.validate_discount(self.subtotal, normal_tax_total, normal_grand_total)
		self.discount_amount = calculate_discount_amount(
			self.subtotal, normal_tax_total, self.discount_type or "Percentage", self.discount_value or 0,
			self.discount_scope or "Net Total", normal_grand_total,
		)
		self.tax_total, self.grand_total = self.calculate_tax_preview(apply_discount=True)

	def validate_context(self):
		store = frappe.db.get_value(
			"Store", self.store, ["company", "enabled"], as_dict=True
		)
		if not store or not store.enabled:
			frappe.throw(_("Select an enabled Store."))
		if not frappe.db.get_value("Restaurant Brand", self.restaurant_brand, "enabled"):
			frappe.throw(_("Select an enabled Brand."))
		if not frappe.db.exists(
			"Store Brand Assignment",
			{
				"parent": self.store,
				"parenttype": "Store",
				"restaurant_brand": self.restaurant_brand,
			},
		):
			frappe.throw(_("The selected Brand is not assigned to this Store."))

		order_type = frappe.db.get_value(
			"Order Type",
			self.order_type,
			["enabled", "require_table", "require_external_reference"],
			as_dict=True,
		)
		if not order_type or not order_type.enabled:
			frappe.throw(_("Select an enabled Order Type."))
		tax_row = frappe.db.get_value(
			"Store Order Type Tax",
			{"parent": self.store, "parenttype": "Store", "order_type": self.order_type},
			"sales_taxes_and_charges_template",
		)
		if not tax_row:
			frappe.throw(_("Configure this Order Type and its Sales Taxes and Charges Template on the Store."))
		self.sales_taxes_and_charges_template = tax_row
		template_company = frappe.db.get_value(
			"Sales Taxes and Charges Template", tax_row, "company"
		)
		if template_company != store.company:
			frappe.throw(_("The Store tax template must belong to the Store Company."))

		session = frappe.db.get_value(
			"Cashier Session",
			self.cashier_session,
			["store", "user", "status", "business_date"],
			as_dict=True,
		)
		if not session or session.store != self.store or session.status != "Open":
			frappe.throw(_("Select an Open Cashier Session for the selected Store."))
		if self.business_date != session.business_date:
			frappe.throw(_("POS Order Business Date must match its Cashier Session."))

		if order_type.require_external_reference and not self.external_reference:
			frappe.throw(_("External Reference is required for this Order Type."))
		if order_type.require_table and not self.dining_table:
			frappe.throw(_("Select a Dining Table for this Order Type."))
		if not order_type.require_table:
			self.dining_area, self.dining_table = normalize_dining_context(False, self.dining_area, self.dining_table)
		if self.dining_table:
			table = frappe.db.get_value(
				"Dining Table", self.dining_table, ["store", "dining_area", "enabled"], as_dict=True
			)
			if not table or not table.enabled or table.store != self.store:
				frappe.throw(_("Dining Table must be enabled and belong to the selected Store."))
			if self.dining_area and table.dining_area != self.dining_area:
				frappe.throw(_("Dining Table must belong to the selected Dining Area."))
			self.dining_area = table.dining_area
			self.validate_table_check_occupancy()

	def validate_table_check_occupancy(self):
		open_orders = frappe.get_all(
			"POS Order",
			filters={
				"dining_table": self.dining_table,
				"name": ["!=", self.name or ""],
				"status": ["not in", ["Paid", "Cancelled"]],
			},
			fields=["name", "table_check_group", "check_label"],
		)
		for order in open_orders:
			if not self.table_check_group or order.table_check_group != self.table_check_group:
				frappe.throw(_("This Dining Table already has an open order. Use Split into checks to add another bill for the same table."))
			if self.check_label and order.check_label and self.check_label.strip().casefold() == order.check_label.strip().casefold():
				frappe.throw(_("Check label is already used by another open check at this table."))

	def normalize_check_label(self):
		if self.check_label is None:
			return
		if not isinstance(self.check_label, str):
			frappe.throw(_("Check label must be text."))
		self.check_label = self.check_label.strip() or None
		if self.check_label and len(self.check_label) > 60:
			frappe.throw(_("Check label cannot exceed 60 characters."))

	def resolve_items(self, rows=None):
		if self.status in ("Confirmed", "In Preparation", "Ready") and not self.items:
			frappe.throw(_("Add at least one product before confirming an order."))

		allowed_payment_methods = set(
			frappe.get_all(
				"POS Payment Method",
				filters={"parent": frappe.db.get_value("Cashier Session", self.cashier_session, "pos_profile"), "parenttype": "POS Profile"},
				pluck="mode_of_payment",
			)
		)
		rows = list(rows) if rows is not None else list(self.items)
		row_ids = {row.name for row in rows}
		subtotal = sum(flt(row.amount) for row in self.items if row.name not in row_ids)
		for row in rows:
			product = frappe.get_doc("Selling Product", row.selling_product)
			if not product.enabled or product.has_options:
				frappe.throw(_("Choose an enabled sellable product, not an Options parent."))
			if row.option_parent:
				parent = frappe.get_doc("Selling Product", row.option_parent)
				if not parent.has_options or not option_tree_contains(parent.name, row.selling_product):
					frappe.throw(_("Selected option product does not belong to the Option Parent."))
			if product.product_category not in self.get_brand_menu_categories():
				frappe.throw(_("Product {0} is not available on a Menu for this Brand.").format(product.title))
			if not row.qty or row.qty <= 0:
				frappe.throw(_("Product quantities must be greater than zero."))
			if frappe.db.get_value("UOM", row.uom, "must_be_whole_number") and row.qty % 1:
				frappe.throw(_("Unit {0} does not allow fractional quantities.").format(row.uom))

			blocked_store_rows = [item for item in product.store_availability if item.store == self.store]
			if product.store_availability and not blocked_store_rows:
				frappe.throw(_("Product {0} is not enabled for this Store.").format(product.title))
			if any(
				item.store == self.store and item.order_type == self.order_type
				for item in product.store_order_type_exclusions
			):
				frappe.throw(_("Product {0} is disabled for this Order Type.").format(product.title))

			price = product.resolve_price(self.store, self.order_type, self.restaurant_brand)
			row.item = product.item
			row.selling_price = price["selling_price"]
			row.price_list = price["price_list"]
			row.uom = product.uom
			defaults = product.get_effective_defaults(self.store)
			row.warehouse = defaults["warehouse"]
			if product.with_recipe and not row.warehouse:
				frappe.throw(_("Set a Warehouse default before selling a product with a Recipe."))
			if defaults["preparation_areas"]:
				row.preparation_area = row.preparation_area or defaults["preparation_areas"][0]
			self.build_recipe_snapshot(row, product, defaults["warehouse"])

			modifier_rows = []
			seen_modifiers = set()
			modifiers = parse_json_rows(row.modifiers)
			single_selection_groups = {
				group.modifier_group for group in product.modifier_groups
				if not frappe.db.get_value("Modifier Group", group.modifier_group, "allow_multiple_selections")
			}
			validate_modifier_group_selection(modifiers, single_selection_groups)
			for modifier_row in modifiers:
				key = (modifier_row.modifier_group, modifier_row.modifier_product)
				if key in seen_modifiers:
					frappe.throw(_("A modifier can only be selected once per Modifier Group."))
				seen_modifiers.add(key)
				if modifier_row.modifier_group not in {
					item.modifier_group for item in product.modifier_groups
				}:
					frappe.throw(_("Modifier Group is not configured for this product."))
				option = next(
					(
						item
						for item in product.modifier_options
						if item.modifier_group == modifier_row.modifier_group
						and item.modifier_product == modifier_row.modifier_product
					),
					None,
				)
				if not option:
					frappe.throw(_("The selected modifier is not configured for this product."))
				modifier_product = frappe.get_doc("Selling Product", modifier_row.modifier_product)
				if not modifier_product.enabled or not modifier_product.is_modifier:
					frappe.throw(_("Modifier must be an enabled product marked Is Modifier."))
				modifier_availability = [entry for entry in modifier_product.store_availability if entry.store == self.store]
				if modifier_product.store_availability and not modifier_availability:
					frappe.throw(_("Modifier {0} is not enabled for this Store.").format(modifier_product.title))
				if any(
					entry.store == self.store and entry.order_type == self.order_type
					for entry in modifier_product.store_order_type_exclusions
				):
					frappe.throw(_("Modifier {0} is disabled for this Order Type.").format(modifier_product.title))
				modifier_row.qty = modifier_row.qty or 1
				modifier_row.selling_price = option.selling_price or 0
				modifier_row.item = modifier_product.item
				modifier_defaults = modifier_product.get_effective_defaults(self.store)
				modifier_row.warehouse = modifier_defaults["warehouse"]
				if modifier_product.with_recipe:
					if not modifier_row.warehouse:
						frappe.throw(_("Set a Warehouse default before using recipe Modifier {0}.").format(modifier_product.title))
					self.append_modifier_recipe(row, modifier_product, modifier_row.qty, modifier_row.warehouse)
				elif modifier_product.maintain_stock and not modifier_row.warehouse:
					frappe.throw(_("Set a Warehouse default before using stock Modifier {0}.").format(modifier_product.title))
				modifier_rows.append(modifier_row)
			row.modifiers = serialize_json_rows(modifiers)

			row.amount = calculate_order_item_amount(row.qty, row.selling_price, modifier_rows)
			subtotal += row.amount

		for payment in self.payments:
			if payment.mode_of_payment not in allowed_payment_methods:
				frappe.throw(_("Payment Method {0} is not enabled on this POS Profile.").format(payment.mode_of_payment))

		self.subtotal = subtotal
		normal_tax_total, normal_grand_total = self.calculate_tax_preview()
		self.validate_discount(subtotal, normal_tax_total, normal_grand_total)
		self.discount_amount = calculate_discount_amount(
			subtotal, normal_tax_total, self.discount_type or "Percentage", self.discount_value or 0,
			self.discount_scope or "Net Total", normal_grand_total,
		)
		self.tax_total, self.grand_total = self.calculate_tax_preview(apply_discount=True)

	def validate_discount(self, subtotal, tax_total, grand_total):
		value = flt(self.discount_value or 0)
		if value < 0:
			frappe.throw(_("Discount value cannot be negative."))
		if value == 0:
			self.discount_amount = 0
			return
		if self.discount_type not in ("Percentage", "Amount"):
			frappe.throw(_("Choose Percentage or Amount for the discount."))
		if self.discount_scope not in ("Net Total", "Grand Total"):
			frappe.throw(_("Choose whether the discount applies to Net Total or Grand Total."))
		if not (self.discount_reason or "").strip():
			frappe.throw(_("Enter a reason for the discount."))
		if self.discount_type == "Percentage" and value > 100:
			frappe.throw(_("Discount percentage cannot exceed 100%."))
		base = flt(subtotal) if self.discount_scope == "Net Total" else flt(grand_total)
		effective_percent = value if self.discount_type == "Percentage" else (value / base * 100 if base else 0)
		actor = frappe.session.user
		roles = set(frappe.get_roles(actor))
		pos_user = frappe.db.get_value("POS User", {"user": actor, "enabled": 1},
			["can_apply_manual_discount", "max_manual_discount_percent"], as_dict=True)
		if pos_user and not pos_user.can_apply_manual_discount:
			frappe.throw(_("Your POS User permissions do not allow manual discounts."), frappe.PermissionError)
		if self.flags.get("discount_approval_authorized"):
			return
		if not pos_user and roles & {"System Manager", "POS Manager"}:
			return
		limit = flt(pos_user.max_manual_discount_percent if pos_user else 0)
		if effective_percent > limit:
			frappe.throw(_("This POS User is limited to a {0}% discount. Ask a POS Manager to apply a higher discount.").format(limit))

	def get_brand_menu_categories(self):
		categories = set()
		menus = frappe.get_all(
			"Brand Menu Assignment",
			filters={"parent": self.restaurant_brand, "parenttype": "Restaurant Brand"},
			pluck="store_menu",
		)
		for menu in menus:
			if not frappe.db.get_value("Store Menu", menu, "enabled"):
				continue
			root_categories = frappe.get_all(
				"Store Menu Category",
				filters={"parent": menu, "parenttype": "Store Menu"},
				pluck="product_category",
			)
			for root in root_categories:
				bounds = frappe.db.get_value("Product Category", root, ["lft", "rgt"], as_dict=True)
				if not bounds:
					continue
				for child in frappe.get_all(
					"Product Category",
					filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt], "enabled": 1},
					pluck="name",
				):
					categories.add(child)
		return categories

	def build_recipe_snapshot(self, order_row, product, warehouse):
		components = get_recipe_components(product, order_row.qty, warehouse, self.order_type)
		for component in components:
			component["source_selling_product"] = product.name
		order_row.recipe_snapshot = serialize_json_rows(components)

	def append_modifier_recipe(self, order_row, product, modifier_qty, warehouse):
		components = parse_json_rows(order_row.recipe_snapshot)
		modifier_components = get_recipe_components(product, flt(order_row.qty) * flt(modifier_qty), warehouse, self.order_type)
		for component in modifier_components:
			component["source_selling_product"] = product.name
		components.extend(modifier_components)
		order_row.recipe_snapshot = serialize_json_rows(components)

	def calculate_tax_preview(self, apply_discount=False, guest_check=None, discount_order=None, return_details=False):
		"""Use ERPNext's invoice calculator so preview and checkout share tax rules."""
		from frappe.utils import nowdate

		store_company = frappe.db.get_value("Store", self.store, "company")
		session = frappe.get_doc("Cashier Session", self.cashier_session)
		profile = frappe.get_doc("POS Profile", session.pos_profile)
		invoice = frappe.new_doc("POS Invoice")
		invoice.company = store_company
		invoice.customer = self.customer or profile.customer
		invoice.pos_profile = profile.name
		invoice.is_pos = 1
		invoice.posting_date = nowdate()
		invoice.selling_price_list = profile.selling_price_list
		invoice.taxes_and_charges = self.sales_taxes_and_charges_template
		line_rates = []
		allocations = None
		if guest_check:
			items = frappe.parse_json(guest_check.items_json or "[]") if isinstance(guest_check.items_json, str) else guest_check.items_json
			allocations = ({item["name"]: flt(item.get("qty"), 6) if item.get("qty") is not None else None
				for item in items or [] if isinstance(item, dict) and item.get("name")}
				| {item: None for item in items or [] if isinstance(item, str)})
		for row in self.items:
			active_qty = get_active_order_item_qty(row.qty, row.cancelled_qty)
			if allocations is not None:
				if row.name not in allocations:
					continue
				allocated_qty = allocations[row.name]
				if allocated_qty is not None:
					active_qty = min(active_qty, allocated_qty)
			if not active_qty:
				continue
			invoice_row = invoice.append("items", {
				"item_code": row.item,
				"qty": active_qty,
				"uom": row.uom,
				"stock_uom": frappe.db.get_value("Item", row.item, "stock_uom"),
				"rate": row.selling_price,
				"price_list_rate": row.selling_price,
				"warehouse": row.warehouse if frappe.db.get_value("Item", row.item, "is_stock_item") else None,
			})
			line_rates.append((invoice_row, flt(row.selling_price), invoice_row.warehouse))
			for modifier in parse_json_rows(row.modifiers):
				modifier_product = frappe.get_doc("Selling Product", modifier.modifier_product)
				modifier_invoice_row = invoice.append("items", {
					"item_code": modifier_product.item,
					"qty": active_qty * flt(modifier.qty),
					"uom": modifier_product.uom,
					"stock_uom": frappe.db.get_value("Item", modifier_product.item, "stock_uom"),
					"rate": modifier.selling_price,
					"price_list_rate": modifier.selling_price,
					"warehouse": modifier.warehouse if modifier_product.maintain_stock else None,
				})
				line_rates.append((modifier_invoice_row, flt(modifier.selling_price), modifier_invoice_row.warehouse))

		actor = frappe.session.user
		try:
			# Cashiers can calculate their authorized order without direct access to
			# ERPNext accounting masters used by POS Invoice.set_missing_values.
			frappe.set_user("Administrator")
			with prevent_pos_item_price_autoinsert(invoice):
				invoice.set_missing_values()
				apply_order_tax_template(invoice, self.sales_taxes_and_charges_template)
				if apply_discount:
					apply_order_discount(invoice, discount_order or self)
				for invoice_row, rate, warehouse in line_rates:
					invoice_row.rate = rate
					invoice_row.price_list_rate = rate
					if warehouse:
						invoice_row.warehouse = warehouse
				invoice.calculate_taxes_and_totals()
				if return_details:
					return {"subtotal": flt(invoice.total), "tax_total": flt(invoice.total_taxes_and_charges),
						"grand_total": flt(invoice.grand_total)}
				return flt(invoice.total_taxes_and_charges), flt(invoice.grand_total)
		finally:
			frappe.set_user(actor)

	def validate_payment_state(self):
		if self.status != "Paid":
			return
		if not self.payments:
			frappe.throw(_("Add at least one payment before marking the order Paid."))
		paid_total = sum(flt(row.amount) for row in self.payments)
		if abs(paid_total - flt(self.grand_total)) > 0.01:
			frappe.throw(_("Payment amounts must equal the order Grand Total."))

	def validate_terminal_state(self):
		previous = self.get_doc_before_save()
		if self.status == "Paid" and not self.pos_invoice:
			frappe.throw(_("A POS Invoice is required before marking an order Paid."))
		if self.status == "Paid" and any(parse_json_rows(row.recipe_snapshot) for row in self.items):
			stock_entry = frappe.db.get_value("Stock Entry", self.recipe_stock_entry, "docstatus") if self.recipe_stock_entry else 0
			if stock_entry != 1:
				frappe.throw(_("Submit the recipe Stock Entry before marking this order Paid."))
		if previous and previous.status == "Paid" and self.status == "Paid" and self.items != previous.items:
			frappe.throw(_("Paid order snapshots cannot be edited."))

	def confirm(self):
		if self.status not in ("Open", "Pending Confirmation", "Confirmed", "In Preparation", "Ready"):
			frappe.throw(_("Only an active unpaid order can be confirmed."))
		pending_rows = [row for row in self.items if not row.sent_to_kitchen]
		if not pending_rows:
			frappe.throw(_("There are no unconfirmed items to send to preparation."))
		self.validate_stock_available(pending_rows)
		if self.status in ("Open", "Pending Confirmation"):
			self.status = "Confirmed"
		for row in pending_rows:
			row.sent_to_kitchen = 1
		self.save(ignore_permissions=True)
		self.create_kitchen_tickets(pending_rows)
		return self

	def validate_stock_available(self, rows=None):
		requested = {}
		for row in rows or self.items:
			product = frappe.get_doc("Selling Product", row.selling_product)
			if product.with_recipe:
				for component in parse_json_rows(row.recipe_snapshot):
					requested[(component.item, component.warehouse)] = (
						requested.get((component.item, component.warehouse), 0) + flt(component.qty)
					)
			elif product.maintain_stock:
				if not row.warehouse:
					frappe.throw(_("Set a Warehouse default before selling stock products."))
				requested[(row.item, row.warehouse)] = requested.get((row.item, row.warehouse), 0) + flt(row.qty)
			for modifier in parse_json_rows(row.modifiers):
				modifier_product = frappe.get_doc("Selling Product", modifier.modifier_product)
				if modifier_product.maintain_stock and not modifier_product.with_recipe:
					if not modifier.warehouse:
						frappe.throw(_("Set a Warehouse default before selling stock Modifier {0}.").format(modifier_product.title))
					key = (modifier.item, modifier.warehouse)
					requested[key] = requested.get(key, 0) + flt(row.qty) * flt(modifier.qty)

		for (item_code, warehouse), required_qty in requested.items():
			if is_negative_stock_allowed(item_code=item_code):
				continue
			bin_row = frappe.db.get_value(
				"Bin", {"item_code": item_code, "warehouse": warehouse}, ["actual_qty", "reserved_qty"], as_dict=True
			)
			available_qty = (flt(bin_row.actual_qty) - flt(bin_row.reserved_qty)) if bin_row else 0
			if available_qty < required_qty:
				frappe.throw(
					_("Not enough stock for Item {0} in Warehouse {1}. Required {2}; available {3}.").format(
						item_code, warehouse, required_qty, available_qty
					)
				)

	def create_kitchen_tickets(self, rows=None):
		rows_by_area = {}
		for row in rows or self.items:
			product = frappe.get_doc("Selling Product", row.selling_product)
			areas = product.get_effective_defaults(self.store)["preparation_areas"]
			for area_name in areas:
				rows_by_area.setdefault(area_name, []).append(row)

		created = []
		for area_name, order_rows in rows_by_area.items():
			area = frappe.get_doc("Preparation Area", area_name)
			if not area.enabled or (not area.has_kds and not area.has_printer):
				continue
			ticket_name = frappe.db.get_value(
				"Kitchen Ticket", {"pos_order": self.name, "preparation_area": area_name}, "name"
			)
			is_new = not ticket_name
			ticket = (
				frappe.new_doc("Kitchen Ticket")
				if is_new
				else frappe.get_doc("Kitchen Ticket", ticket_name)
			)
			if is_new:
				ticket.pos_order = self.name
				ticket.store = self.store
				ticket.preparation_area = area_name
				ticket.status = "Pending"
				ticket.sent_at = now_datetime()

			known_rows = {item.pos_order_item for item in ticket.items}
			added_rows = False
			for order_row in order_rows:
				if order_row.name in known_rows:
					continue
				modifier_summary = "\n".join(
					_("{0} × {1}").format(modifier.modifier_product, modifier.qty)
					for modifier in parse_json_rows(order_row.modifiers)
				)
				ticket.append(
					"items",
					{
						"pos_order_item": order_row.name,
						"selling_product": order_row.selling_product,
						"qty": order_row.qty,
						"modifier_summary": modifier_summary,
						"notes": order_row.notes,
						"status": "Pending",
					},
				)
				added_rows = True

			if not is_new and not added_rows:
				continue
			if is_new:
				ticket.insert(ignore_permissions=True)
			else:
				ticket.save(ignore_permissions=True)
			created.append(ticket.name)

			if area.has_printer:
				idempotency_key = frappe.generate_hash(
					f"{ticket.name}|{','.join(item.pos_order_item for item in ticket.items)}", length=32
				)
				if not frappe.db.exists("Print Dispatch Job", {"idempotency_key": idempotency_key}):
					frappe.get_doc(
						{
							"doctype": "Print Dispatch Job",
							"store": self.store,
							"preparation_area": area_name,
							"print_device": area.print_device,
							"status": "Queued",
							"document_type": "Kitchen Ticket",
							"document_name": ticket.name,
							"attempt_count": 0,
							"idempotency_key": idempotency_key,
							"payload": frappe.as_json(ticket.as_dict()),
							"queued_at": now_datetime(),
						}
					).insert(ignore_permissions=True)
		return created

	def set_kitchen_status(self, status):
		if status not in ("In Preparation", "Ready"):
			frappe.throw(_("Unsupported POS Order kitchen status."))
		self.status = status
		self.save(ignore_permissions=True)
