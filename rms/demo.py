"""Explicitly invoked restaurant demo setup; never run during install or migration.

bench --site rms.arab-erp.com execute rms.demo.seed --kwargs \
  '{"image_manifest": "/tmp/rms-demo-assets/manifest.json"}'
"""

import json
from pathlib import Path

import frappe
from frappe.utils.file_manager import save_file


BRAND = "بيت الشرق"
MENU = "منيو بيت الشرق"
BRANCHES = [("المعادي", "MAADI"), ("مدينة نصر", "NASR"), ("التجمع الخامس", "TAGAMOA")]
CATEGORY_GROUPS = {
	"المطبخ الشرقي": ["الأطباق المصرية", "المشويات", "الطواجن والمحاشي", "الأرز"],
	"الوجبات السريعة": ["الشاورما والسندوتشات", "الباستا", "البيتزا والبرجر"],
	"المقبلات": ["السلطات", "المقبلات الشرقية", "الشوربة", "الإفطار"],
	"المشروبات والحلويات": ["العصائر والمشروبات الباردة", "المشروبات الساخنة", "الحلويات الشرقية"],
}
# title, category, demo price in EGP, photograph, optional modifier preset
DISHES = [
	("كشري مصري", "الأطباق المصرية", 65, "koshari", None),
	("كشري مخصوص", "الأطباق المصرية", 90, "koshari", "oriental"),
	("ملوخية بالأرز", "الأطباق المصرية", 110, "molokhia", None),
	("ملوخية بالدجاج", "الأطباق المصرية", 185, "molokhia", "oriental"),
	("فتة باللحمة", "الأطباق المصرية", 230, "rice", None),
	("كفتة مشوية", "المشويات", 210, "kofta", "grill"),
	("كباب مشوي", "المشويات", 285, "kebab", "grill"),
	("شيش طاووق", "المشويات", 195, "chicken", "grill"),
	("نصف فرخة مشوية", "المشويات", 190, "chicken", None),
	("طاجن مسقعة", "الطواجن والمحاشي", 95, "moussaka", None),
	("محشي مشكل", "الطواجن والمحاشي", 125, "mahshi", "oriental"),
	("ورق عنب", "الطواجن والمحاشي", 95, "mahshi", None),
	("أرز بالشعرية", "الأرز", 45, "rice", None),
	("أرز بسمتي", "الأرز", 55, "rice", None),
	("فتة شاورما فراخ", "الشاورما والسندوتشات", 160, "shawarma", "sandwich"),
	("ساندوتش فلافل", "الشاورما والسندوتشات", 35, "falafel", None),
	("برجر لحم شرقي", "البيتزا والبرجر", 155, "burger", "sandwich"),
	("سلطة خضراء", "السلطات", 40, "salad", None),
	("فتوش", "السلطات", 65, "salad", "salad"),
	("سلطة طحينة", "السلطات", 30, "hummus", None),
	("حمص بالطحينة", "المقبلات الشرقية", 55, "hummus", None),
	("بابا غنوج", "المقبلات الشرقية", 50, "baba", None),
	("بطاطس مقلية", "المقبلات الشرقية", 55, "fries", "fries"),
	("شوربة عدس", "الشوربة", 55, "soup", None),
	("شوربة لسان عصفور", "الشوربة", 45, "soup", None),
	("فول بالزيت الحار", "الإفطار", 45, "foul", "oriental"),
	("طبق فلافل", "الإفطار", 40, "falafel", None),
	("فول سادة", "الإفطار", 35, "foul", None),
	("عصير مانجو", "العصائر والمشروبات الباردة", 65, "mango", None),
	("مياه معدنية", "العصائر والمشروبات الباردة", 20, "water", None),
	("مشروب غازي", "العصائر والمشروبات الباردة", 30, "soda", None),
	("شاي بالنعناع", "المشروبات الساخنة", 30, "tea", None),
	("قهوة تركي", "المشروبات الساخنة", 45, "coffee", "coffee"),
	("كنافة", "الحلويات الشرقية", 75, "kunafa", "dessert"),
	("بقلاوة", "الحلويات الشرقية", 80, "baklava", None),
	("أرز بلبن", "الحلويات الشرقية", 45, "pudding", "dessert"),
]
MODIFIERS = {
	"إضافات الجبن": [("بارميزان إضافي", 25, "cheese"), ("موزاريلا إضافية", 30, "cheese")],
	"إضافات الخضار": [("مشروم", 20, "mushroom"), ("زيتون", 15, "salad"), ("فلفل مشوي", 10, "salad")],
	"درجة الشطة": [("بدون شطة", 0, "hummus"), ("شطة خفيفة", 0, "hummus"), ("شطة حارة", 5, "hummus")],
	"الصوصات الإضافية": [("ثومية", 10, "hummus"), ("طحينة إضافية", 10, "hummus"), ("صوص حار", 10, "hummus")],
	"الإضافات الجانبية": [("خبز بلدي إضافي", 5, "falafel"), ("أرز إضافي", 25, "rice"), ("بطاطس جانبية", 30, "fries")],
	"إضافات الحلويات": [("آيس كريم", 25, "pudding"), ("مكسرات", 20, "baklava")],
	"السكر": [("بدون سكر", 0, "coffee"), ("سكر خفيف", 0, "coffee"), ("سكر عادي", 0, "coffee")],
	"إضافات المشروبات": [("نعناع إضافي", 5, "lemonade"), ("ثلج إضافي", 0, "water")],
}
PRESETS = {
	"pasta": ["إضافات الجبن", "إضافات الخضار", "درجة الشطة"],
	"oriental": ["الصوصات الإضافية", "الإضافات الجانبية", "درجة الشطة"],
	"grill": ["الإضافات الجانبية", "الصوصات الإضافية"],
	"sandwich": ["إضافات الجبن", "الصوصات الإضافية", "درجة الشطة"],
	"salad": ["إضافات الخضار"], "fries": ["إضافات الجبن", "الصوصات الإضافية"],
	"coffee": ["السكر"], "dessert": ["إضافات الحلويات"], "drink": ["السكر", "إضافات المشروبات"],
}


def ensure(doctype, name, values):
	"""Keep existing records intact so rerunning setup cannot overwrite test edits."""
	if frappe.db.exists(doctype, name):
		return frappe.get_doc(doctype, name)
	if doctype in ("Selling Product", "Product Category"):
		# A global ERPNext Warehouse default must not override Store fallbacks.
		values = {"default_warehouse": "", **values}
	return frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def seed(image_manifest, company="TEST", user="Administrator"):
	if frappe.session.user != "Administrator":
		frappe.throw("Run restaurant demo setup as Administrator.", frappe.PermissionError)
	manifest = json.loads(Path(image_manifest).read_text())
	needed = {r[3] for r in DISHES} | {r[2] for rows in MODIFIERS.values() for r in rows} | {"pasta", "white_pasta", "pizza", "lemonade"}
	for key in needed:
		if key not in manifest or not Path(manifest[key]["path"]).is_file():
			raise ValueError(f"Missing demo photograph: {key}")
	company_doc = frappe.get_doc("Company", company)
	if company_doc.default_currency != "EGP":
		raise ValueError("This demo is priced in EGP; choose an EGP demo company.")
	if not frappe.db.exists("User", {"name": user, "enabled": 1}):
		raise ValueError("Choose an existing enabled demo user.")
	images = {}
	for key in sorted(needed):
		path = Path(manifest[key]["path"])
		filename = f"bayt-al-sharq-{key}{path.suffix}"
		existing = frappe.db.get_value("File", {"file_name": filename, "is_private": 0}, "file_url")
		images[key] = existing or save_file(filename, path.read_bytes(), None, None, is_private=0).file_url
	# Retain attribution and licence details with the demo photos.
	credits = [{k: v for k, v in data.items() if k != "path"} for data in manifest.values()]
	if not frappe.db.exists("File", {"file_name": "bayt-al-sharq-image-credits.json"}):
		save_file("bayt-al-sharq-image-credits.json", json.dumps(credits, ensure_ascii=False, indent=2).encode(), None, None, is_private=0)

	def account(label, parent, account_type):
		name = f"{label} - {company_doc.abbr}"
		return ensure("Account", name, {"account_name": label, "parent_account": parent,
			"company": company, "account_type": account_type, "is_group": 0}).name

	cash = account("خزينة بيت الشرق", f"Cash In Hand - {company_doc.abbr}", "Cash")
	bank = account("تسويات البطاقات", f"Bank Accounts - {company_doc.abbr}", "Bank")
	vat = account("ضريبة القيمة المضافة", f"Duties and Taxes - {company_doc.abbr}", "Tax")
	for name, kind, ledger in [("نقدي", "Cash", cash), ("بطاقة بنكية", "Bank", bank), ("محفظة إلكترونية", "Bank", bank)]:
		ensure("Mode of Payment", name, {"mode_of_payment": name, "type": kind,
			"accounts": [{"company": company, "default_account": ledger}]})
	taxes = ensure("Sales Taxes and Charges Template", f"ضريبة القيمة المضافة 14% - {company_doc.abbr}", {
		"title": "ضريبة القيمة المضافة 14%", "company": company, "is_default": 0,
		"taxes": [{"charge_type": "On Net Total", "account_head": vat, "rate": 14,
			"description": "ضريبة القيمة المضافة 14%", "cost_center": company_doc.cost_center}]}).name
	customer = ensure("Customer", "عميل نقدي - بيت الشرق", {"customer_name": "عميل نقدي - بيت الشرق",
		"customer_type": "Individual", "customer_group": "Individual", "territory": "Egypt"}).name
	for name in ["أحمد محمد", "سارة علي", "شركة النور"]:
		ensure("Customer", name, {"customer_name": name, "customer_type": "Individual", "customer_group": "Individual", "territory": "Egypt"})
	price_list = ensure("Price List", "قائمة أسعار بيت الشرق", {"price_list_name": "قائمة أسعار بيت الشرق", "currency": "EGP", "selling": 1, "enabled": 1}).name
	brand = ensure("Restaurant Brand", BRAND, {"title": BRAND, "brand_code": "SHARQ", "brand_image": images["kofta"]})
	types = []
	for i, (name, table, reference) in enumerate([("صالة", 1, 0), ("تيك أواي", 0, 0), ("توصيل", 0, 1)], 1):
		types.append(ensure("Order Type", name, {"title": name, "sequence_id": i, "require_table": table,
			"require_external_reference": reference, "delivery_included": reference,
			"accounts": [{"company": company, "income_account": company_doc.default_income_account,
				"cost_of_goods_sold_account": company_doc.default_expense_account}]}).name)
	stores, kitchens = [], {}
	for i, (arabic, code) in enumerate(BRANCHES):
		name = f"بيت الشرق - {arabic}"
		warehouse = ensure("Warehouse", f"مخزن بيت الشرق {arabic} - {company_doc.abbr}", {
			"warehouse_name": f"مخزن بيت الشرق {arabic}", "company": company,
			"parent_warehouse": f"All Warehouses - {company_doc.abbr}", "is_group": 0}).name
		cost_center = ensure("Cost Center", f"بيت الشرق {arabic} - {company_doc.abbr}", {
			"cost_center_name": f"بيت الشرق {arabic}", "company": company,
			"parent_cost_center": frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name"), "is_group": 0}).name
		profile = ensure("POS Profile", f"بيت الشرق - كاشير {arabic}", {"name": f"بيت الشرق - كاشير {arabic}", "company": company,
			"warehouse": warehouse, "currency": "EGP", "customer": customer, "selling_price_list": price_list,
			"income_account": company_doc.default_income_account, "expense_account": company_doc.default_expense_account,
			"cost_center": cost_center, "write_off_account": f"Round Off - {company_doc.abbr}",
			"write_off_cost_center": cost_center, "write_off_limit": 1, "account_for_change_amount": cash,
			"update_stock": 0, "ignore_pricing_rule": 1, "taxes_and_charges": taxes,
			"payments": [{"mode_of_payment": mode, "default": int(j == 0)} for j, mode in enumerate(["نقدي", "بطاقة بنكية", "محفظة إلكترونية"])]}).name
		store = ensure("Store", name, {"title": name, "store_code": code, "company": company,
			"default_warehouse": warehouse, "pos_profile": profile, "city": "القاهرة", "state": "القاهرة",
			"description": "مطعم بيت الشرق", "operating_day_end": "04:00:00",
			"brands": [{"restaurant_brand": brand.name, "is_default": 1, "sequence_id": 1}],
			"working_hours": [{"weekday": day, "from_time": "00:00:00", "to_time": "23:59:59", "enabled": 1}
				for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]],
			"order_type_taxes": [{"order_type": t, "sales_taxes_and_charges_template": taxes} for t in types]})
		stores.append(store.name)
		kitchens[store.name] = {}
		for j, area in enumerate(["المطبخ الساخن", "الشواية", "البار والحلويات"], 1):
			area_name = f"{arabic} - {area}"
			kitchens[store.name][area] = ensure("Preparation Area", area_name, {"title": area_name, "store": store.name,
				"has_kds": 1, "has_printer": 0, "sequence_id": j}).name
		if not store.default_preparation_area:
			store.default_preparation_area = kitchens[store.name]["المطبخ الساخن"]
			store.save(ignore_permissions=True)
		for j, area in enumerate(["الصالة", "التراس"], 1):
			area_name = f"{arabic} - {area}"
			ensure("Dining Area", area_name, {"title": area_name, "store": store.name, "restaurant_brand": brand.name, "sequence_id": j})
			for n in range(1, 5):
				table_name = f"{arabic} - {'صالة ' if j == 1 else 'تراس '}{n:02d}"
				ensure("Dining Table", table_name, {"title": table_name, "store": store.name,
					"dining_area": area_name, "capacity": [2, 4, 4, 6][n - 1], "sequence_id": n})
	pos_user = frappe.get_doc("POS User", user) if frappe.db.exists("POS User", user) else frappe.new_doc("POS User")
	pos_user.user = user
	for store in stores:
		if store not in {r.store for r in pos_user.stores}:
			pos_user.append("stores", {"store": store, "default_store": int(not pos_user.stores)})
	pos_user.max_manual_discount_percent = max(pos_user.max_manual_discount_percent or 0, 20)
	pos_user.can_payout = 1
	pos_user.save(ignore_permissions=True)
	category_names = []
	category_map = {}
	for i, (group, children) in enumerate(CATEGORY_GROUPS.items(), 1):
		parent = ensure("Product Category", group, {"title": group, "is_group": 1, "sequence_id": i}).name
		category_names.append(parent)
		for j, child in enumerate(children, 1):
			category_map[child] = ensure("Product Category", child, {"title": child,
				"parent_product_category": parent, "item_group": "Products", "sequence_id": j}).name
	modifier_category = ensure("Product Category", "إضافات داخلية", {"title": "إضافات داخلية", "item_group": "Products"}).name
	menu = ensure("Store Menu", MENU, {"title": MENU, "restaurant_brand": brand.name,
		"categories": [{"product_category": name, "sequence_id": i} for i, name in enumerate(category_names, 1)]})
	if menu.name not in {r.store_menu for r in brand.menus}:
		brand.append("menus", {"store_menu": menu.name, "sequence_id": 1})
		brand.save(ignore_permissions=True)
	for i, (group, choices) in enumerate(MODIFIERS.items(), 1):
		ensure("Modifier Group", group, {"title": group, "sequence_id": i,
			"allow_multiple_selections": int(group not in ["درجة الشطة", "السكر"]),
			"allow_collapse": 1, "collapsed_by_default": int(group == "إضافات الخضار")})
		for title, price, photo in choices:
			ensure("Selling Product", title, {"title": title, "product_category": modifier_category,
				"uom": "Nos", "is_modifier": 1, "can_be_sold_separately": 0, "selling_price": price, "image": images[photo]})
	products = []

	def product(title, category, price, photo, preset=None, options=None):
		name = title
		values = {"title": name, "product_category": category_map[category], "uom": "Nos", "image": images[photo],
			"selling_price": price if not options else 0, "has_options": int(bool(options)),
			"sequence_id": len(products) + 1, "store_availability": [{"store": s} for s in stores]}
		if options:
			values["option_products"] = [{"option_product": p, "sequence_id": i} for i, p in enumerate(options, 1)]
		if preset:
			values["modifier_groups"] = [{"modifier_group": g, "sequence_id": i} for i, g in enumerate(PRESETS[preset], 1)]
			values["modifier_options"] = [{"modifier_group": g, "modifier_product": title,
				"selling_price": amount, "sequence_id": i} for g in PRESETS[preset] for i, (title, amount, _) in enumerate(MODIFIERS[g], 1)]
		area = "الشواية" if category == "المشويات" else "البار والحلويات" if category in CATEGORY_GROUPS["المشروبات والحلويات"] else "المطبخ الساخن"
		values["print_routes"] = [{"store": s, "preparation_area": kitchens[s][area]} for s in stores]
		if not options:
			values["selling_prices"] = [{"store": stores[2], "selling_price": round(price * 1.1), "priority": 10},
				{"order_type": types[2], "selling_price": round(price * 1.15), "priority": 5}]
		doc = ensure("Selling Product", name, values)
		products.append(doc.name)
		return doc.name

	for row in DISHES:
		product(*row)
	shapes = []
	for shape in ["PENNE", "SPAGHETTI", "FETTUCCINE"]:
		proteins = []
		for protein, base_price in [("Chicken", 165), ("Beef", 195), ("Shrimp", 225), ("Vegetarian", 135)]:
			sauces = [product(f"PASTA / {shape} / {protein} / {sauce}", "الباستا", base_price + extra, photo, "pasta")
				for sauce, extra, photo in [("Red Sauce", 0, "pasta"), ("White Sauce", 15, "white_pasta")]]
			proteins.append(product(f"PASTA / {shape} / {protein}", "الباستا", 0, "pasta", options=sauces))
		shapes.append(product(f"PASTA / {shape}", "الباستا", 0, "pasta", options=proteins))
	product("PASTA", "الباستا", 0, "pasta", options=shapes)
	for title, category, photo, preset, choices in [
		("شاورما فراخ", "الشاورما والسندوتشات", "shawarma", "sandwich", [("عادي", 100), ("كبير", 140)]),
		("مشكل مشويات", "المشويات", "kebab", None, [("ربع كيلو", 230), ("نصف كيلو", 440), ("كيلو", 850)]),
		("بيتزا شرقية", "البيتزا والبرجر", "pizza", "pasta", [("صغير", 120), ("وسط", 165), ("كبير", 210)]),
		("ليمون نعناع", "العصائر والمشروبات الباردة", "lemonade", "drink", [("عادي", 50), ("كبير", 70)]),
	]:
		children = [product(f"{title} / {size}", category, price, photo, preset) for size, price in choices]
		product(title, category, 0, photo, options=children)
	for title, ledger in [("مصروفات تشغيل", "Miscellaneous Expenses"), ("توصيل", "Freight and Forwarding Charges")]:
		ensure("Expense Category", title, {"title": title, "company": company,
			"expense_account": f"{ledger} - {company_doc.abbr}", "cost_center": company_doc.cost_center})
	for reason in ["طلب العميل", "صنف غير مطابق", "خطأ في إدخال الطلب"]:
		if not frappe.db.exists("POS Action Reason", {"reason": reason}):
			frappe.get_doc({"doctype": "POS Action Reason", "reason": reason, "applies_to": "Both", "description": "سبب إلغاء أو مرتجع"}).insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache()
	return {"brand": brand.name, "stores": stores, "products": len(products), "photos": len(images), "menu": menu.name}
