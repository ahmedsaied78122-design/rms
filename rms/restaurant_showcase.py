"""Explicit restaurant presentation setup. Never invoked by install or migration.

Run as Administrator with ``bench execute rms.restaurant_showcase.optimize_images``
then ``bench execute rms.restaurant_showcase.seed`` after installing the curated
menu photographs in ``public/images/menu``.
"""

from pathlib import Path

import frappe

from rms.demo import BRAND, MENU, PRESETS, MODIFIERS


ORIGINAL_ASSET_ROOT = "/assets/rms/images/menu"
ASSET_ROOT = f"{ORIGINAL_ASSET_ROOT}/cards-v1"
STORES = [f"بيت الشرق - {branch}" for branch in ("المعادي", "مدينة نصر", "التجمع الخامس")]

# Existing category identities remain stable, including those used by old orders.
CATEGORIES = [
	("المطبخ الشرقي", None, "oriental"),
	("المطبخ الإيطالي", None, "italian"),
	("المطبخ الإنترناشونال", None, "international"),
	("الوجبات السريعة", None, "burger"),
	("المقبلات", None, "mezze"),
	("المشروبات والحلويات", None, "drinks_desserts"),
	("الأطباق المصرية", "المطبخ الشرقي", "koshari"),
	("المشويات", "المطبخ الشرقي", "kebab"),
	("الطواجن والمحاشي", "المطبخ الشرقي", "mahshi"),
	("الأرز", "المطبخ الشرقي", "rice"),
	("الباستا", "المطبخ الإيطالي", "pasta_red"),
	("البيتزا الإيطالية", "المطبخ الإيطالي", "pizza"),
	("الريزوتو", "المطبخ الإيطالي", "risotto"),
	("المقبلات الإيطالية", "المطبخ الإيطالي", "garlicbread"),
	("الستيك والجريل", "المطبخ الإنترناشونال", "steak"),
	("أطباق الدجاج", "المطبخ الإنترناشونال", "chicken_mushroom"),
	("المأكولات البحرية", "المطبخ الإنترناشونال", "salmon"),
	("الشاورما والسندوتشات", "الوجبات السريعة", "shawarma"),
	("البيتزا والبرجر", "الوجبات السريعة", "burger"),
	("السلطات", "المقبلات", "salad"),
	("المقبلات الشرقية", "المقبلات", "mezze"),
	("الشوربة", "المقبلات", "lentil"),
	("الإفطار", "المقبلات", "foul"),
	("العصائر والمشروبات الباردة", "المشروبات والحلويات", "mango"),
	("المشروبات الساخنة", "المشروبات والحلويات", "cappuccino"),
	("الحلويات الشرقية", "المشروبات والحلويات", "kunafa"),
	("الحلويات العالمية", "المشروبات والحلويات", "tiramisu"),
]

# Real dish names, sample EGP prices, photograph and preparation station.
DISHES = [
	("ماتشا لاتيه مثلج", "المشروبات والحلويات", 95, "matcha", "البار والحلويات", "drink"),
	("مشكل شرقي", "المطبخ الشرقي", 340, "oriental", "المطبخ الساخن", "oriental"),
	("فيتوتشيني ألفريدو بالدجاج", "الباستا", 225, "pasta_white", "المطبخ الإيطالي", "pasta"),
	("سباجيتي نابوليتانا", "الباستا", 155, "pasta_red", "المطبخ الإيطالي", "pasta"),
	("سباجيتي سي فود", "الباستا", 285, "seafood", "المطبخ الإيطالي", "pasta"),
	("بيتزا مارجريتا", "البيتزا الإيطالية", 180, "pizza", "المطبخ الإيطالي", "pasta"),
	("بيتزا بيبروني", "البيتزا الإيطالية", 235, "pepperoni", "المطبخ الإيطالي", "pasta"),
	("بيتزا أربع أجبان", "البيتزا الإيطالية", 245, "fourcheese", "المطبخ الإيطالي", "pasta"),
	("ريزوتو بالمشروم", "الريزوتو", 210, "risotto", "المطبخ الإيطالي", None),
	("خبز بالثوم والأعشاب", "المقبلات الإيطالية", 65, "garlicbread", "المطبخ الإيطالي", None),
	("فيليه بصوص الفلفل", "الستيك والجريل", 425, "steak", "المطبخ الإنترناشونال", "grill"),
	("تشكن مشروم", "أطباق الدجاج", 245, "chicken_mushroom", "المطبخ الإنترناشونال", None),
	("تشيكن ستربس", "أطباق الدجاج", 195, "crispy", "المطبخ الإنترناشونال", "fries"),
	("سلمون مشوي بصوص الليمون", "المأكولات البحرية", 445, "salmon", "المطبخ الإنترناشونال", None),
	("سلطة سيزر بالدجاج", "السلطات", 175, "caesar", "المطبخ الإنترناشونال", None),
	("شوربة كريمة المشروم", "الشوربة", 85, "mushroom_soup", "المطبخ الإنترناشونال", None),
	("كابتشينو", "المشروبات الساخنة", 75, "cappuccino", "البار والحلويات", "coffee"),
	("آيس لاتيه", "العصائر والمشروبات الباردة", 85, "iced_latte", "البار والحلويات", "drink"),
	("تيراميسو", "الحلويات العالمية", 120, "tiramisu", "البار والحلويات", None),
	("تشيز كيك بالتوت", "الحلويات العالمية", 115, "cheesecake", "البار والحلويات", None),
	("مولتن شوكولاتة", "الحلويات العالمية", 125, "chocolate", "البار والحلويات", "dessert"),
]

EXISTING_PHOTOS = {
	"كشري مصري": "koshari", "كشري مخصوص": "koshari",
	"ملوخية بالأرز": "molokhia_rice", "ملوخية بالدجاج": "molokhia", "فتة باللحمة": "fatta",
	"كفتة مشوية": "kofta", "كباب مشوي": "kebab", "شيش طاووق": "tawook",
	"نصف فرخة مشوية": "chicken", "طاجن مسقعة": "moussaka", "محشي مشكل": "mahshi",
	"ورق عنب": "vineleaves", "أرز بالشعرية": "rice", "أرز بسمتي": "basmati",
	"فتة شاورما فراخ": "shawarma_fatta", "ساندوتش فلافل": "falafel_wrap", "برجر لحم شرقي": "burger",
	"سلطة خضراء": "salad", "فتوش": "fattoush", "سلطة طحينة": "tahini",
	"حمص بالطحينة": "hummus", "بابا غنوج": "baba", "بطاطس مقلية": "fries",
	"شوربة عدس": "lentil", "شوربة لسان عصفور": "orzo", "فول بالزيت الحار": "foul",
	"طبق فلافل": "falafel", "فول سادة": "foul", "عصير مانجو": "mango", "مياه معدنية": "water",
	"مشروب غازي": "soda", "شاي بالنعناع": "tea", "قهوة تركي": "coffee",
	"كنافة": "kunafa", "بقلاوة": "baklava", "أرز بلبن": "pudding",
	"شاورما فراخ": "shawarma", "مشكل مشويات": "mixed_grill", "بيتزا شرقية": "pizza_oriental",
	"ليمون نعناع": "lemonade", "PASTA": "pasta_red",
}


def image(key):
	return f"{ASSET_ROOT}/{key}.webp"


def photo_keys():
	return {row[2] for row in CATEGORIES} | {row[3] for row in DISHES} | set(EXISTING_PHOTOS.values()) | {"pasta_white"}


def optimize_images():
	"""Install lightweight menu photos while retaining the full-size originals.

	Run explicitly as Administrator. Only image links pointing to our curated
	assets are changed; uploaded photos and product settings are preserved.
	The versioned directory also avoids previously cached large responses.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw("Run restaurant photo optimization as Administrator.", frappe.PermissionError)
	from PIL import Image

	root = Path(frappe.get_app_path("rms", "public", "images", "menu"))
	keys = sorted(photo_keys())
	missing = [key for key in keys if not (root / f"{key}.webp").is_file()]
	if missing:
		raise ValueError(f"Curated menu photos missing: {', '.join(missing)}")
	destination = root / "cards-v1"
	destination.mkdir(exist_ok=True)
	original_bytes = card_bytes = 0
	for key in keys:
		source, target = root / f"{key}.webp", destination / f"{key}.webp"
		with Image.open(source) as original:
			card = original.convert("RGB")
			card.thumbnail((480, 480), Image.Resampling.LANCZOS)
			card.save(target, "WEBP", quality=76, method=6)
		original_bytes += source.stat().st_size
		card_bytes += target.stat().st_size

	replacements = {f"{ORIGINAL_ASSET_ROOT}/{key}.webp": image(key) for key in keys}
	updated = {}
	for doctype, field in (("Selling Product", "image"), ("Product Category", "image"),
		("Item", "image"), ("Restaurant Brand", "brand_image")):
		rows = frappe.get_all(doctype, filters={field: ["in", list(replacements)]}, fields=["name", field])
		for row in rows:
			frappe.db.set_value(doctype, row.name, field, replacements[row[field]])
		updated[doctype] = len(rows)
	frappe.db.commit()
	frappe.clear_cache()
	return {"photos": len(keys), "original_bytes": original_bytes, "card_bytes": card_bytes,
		"reduction_percent": round(100 * (1 - card_bytes / original_bytes), 1), "updated": updated}


def pasta_title(name):
	if name == "PASTA":
		return "باستا على ذوقك"
	labels = {"PENNE": "بيني", "SPAGHETTI": "سباجيتي", "FETTUCCINE": "فيتوتشيني",
		"Chicken": "بالدجاج", "Beef": "باللحم", "Shrimp": "بالجمبري", "Vegetarian": "بالخضار",
		"Red Sauce": "بصوص الطماطم", "White Sauce": "بصوص ألفريدو"}
	return " ".join(labels.get(part, part) for part in name.split(" / ")[1:])


def seed():
	if frappe.session.user != "Administrator":
		frappe.throw("Run restaurant presentation setup as Administrator.", frappe.PermissionError)
	missing = [key for key in sorted(photo_keys()) if not Path(frappe.get_app_path("rms", "public", "images", "menu", "cards-v1", f"{key}.webp")).is_file()]
	if missing:
		raise ValueError(f"Menu card photos missing; run rms.restaurant_showcase.optimize_images first: {', '.join(missing)}")
	if not all(frappe.db.exists("Store", store) for store in STORES):
		raise ValueError("The three restaurant branches must exist before extending the menu.")

	stations = {}
	created_stations = []
	for store in STORES:
		branch = store.removeprefix("بيت الشرق - ")
		for sequence, label in enumerate(("المطبخ الساخن", "الشواية", "البار والحلويات", "المطبخ الإيطالي", "المطبخ الإنترناشونال"), 1):
			name = f"{branch} - {label}"
			if not frappe.db.exists("Preparation Area", name):
				frappe.get_doc({"doctype": "Preparation Area", "title": name, "store": store,
					"has_kds": 1, "enabled": 1, "sequence_id": sequence}).insert()
				created_stations.append(name)
			stations[store, label] = name

	parents = {row[1] for row in CATEGORIES if row[1]}
	for index, (title, parent, photo) in enumerate(CATEGORIES, 1):
		doc = frappe.get_doc("Product Category", title) if frappe.db.exists("Product Category", title) else frappe.new_doc("Product Category")
		doc.update({"title": title, "parent_product_category": parent, "is_group": int(title in parents),
			"item_group": "Products", "enabled": 1, "sequence_id": index, "image": image(photo),
			"default_warehouse": ""})
		doc.save()
	menu = frappe.get_doc("Store Menu", MENU)
	listed = {row.product_category for row in menu.categories}
	for index, (title, parent, _) in enumerate(CATEGORIES, 1):
		if not parent and title not in listed:
			menu.append("categories", {"product_category": title, "sequence_id": index})
	menu.save()

	created = []
	for index, (title, category, price, photo, station, preset) in enumerate(DISHES, 1):
		if frappe.db.exists("Selling Product", title):
			continue  # Preserve later cashier/back-office edits on repeat execution.
		values = {"doctype": "Selling Product", "title": title, "product_category": category,
			"uom": "Nos", "selling_price": price, "image": image(photo), "enabled": 1,
			"default_store": "", "default_warehouse": "", "sequence_id": 100 + index,
			"store_availability": [{"store": store} for store in STORES],
			"print_routes": [{"store": store, "preparation_area": stations[store, station]} for store in STORES],
			"selling_prices": [{"store": STORES[2], "selling_price": round(price * 1.1), "priority": 10},
				{"order_type": "توصيل", "selling_price": round(price * 1.15), "priority": 5}]}
		if preset:
			values["modifier_groups"] = [{"modifier_group": group, "sequence_id": n} for n, group in enumerate(PRESETS[preset], 1)]
			values["modifier_options"] = [{"modifier_group": group, "modifier_product": name,
				"selling_price": amount, "sequence_id": n} for group in PRESETS[preset]
				for n, (name, amount, _) in enumerate(MODIFIERS[group], 1)]
		created.append(frappe.get_doc(values).insert().name)

	# Frappe synchronizes field:title with the document name on every save.
	# Rename through its link-aware API so option links and order references follow.
	pasta_names = {"PASTA": pasta_title("PASTA")}
	for shape in ("PENNE", "SPAGHETTI", "FETTUCCINE"):
		base = f"PASTA / {shape}"
		pasta_names[base] = pasta_title(base)
		for protein in ("Chicken", "Beef", "Shrimp", "Vegetarian"):
			parent = f"{base} / {protein}"
			pasta_names[parent] = pasta_title(parent)
			for sauce in ("Red Sauce", "White Sauce"):
				child = f"{parent} / {sauce}"
				pasta_names[child] = pasta_title(child)
	for old, new in pasta_names.items():
		if frappe.db.exists("Selling Product", old):
			if frappe.db.exists("Selling Product", new):
				raise ValueError(f"Cannot rename {old}: product {new} already exists.")
			frappe.rename_doc("Selling Product", old, new)
	legacy_pasta_names = {new: old for old, new in pasta_names.items()}
	updated = []
	for row in frappe.get_all("Selling Product", filters={"enabled": 1}, fields=["name", "product_category"]):
		legacy_name = legacy_pasta_names.get(row.name, row.name)
		key = EXISTING_PHOTOS.get(legacy_name)
		if not key:
			for prefix in ("شاورما فراخ", "بيتزا شرقية", "مشكل مشويات", "ليمون نعناع"):
				if row.name.startswith(prefix + " / "):
					key = EXISTING_PHOTOS[prefix]
		if legacy_name.startswith("PASTA / "):
			key = "pasta_white" if legacy_name.endswith("White Sauce") else "pasta_red"
		if not key:
			continue
		doc = frappe.get_doc("Selling Product", row.name)
		doc.image = image(key)
		if row.product_category == "الباستا":
			doc.set("print_routes", [{"store": store, "preparation_area": stations[store, "المطبخ الإيطالي"]} for store in STORES])
		doc.save()
		frappe.db.set_value("Item", doc.item, {"image": doc.image, "item_name": doc.title}, update_modified=False)
		updated.append(doc.name)
	frappe.db.set_value("Restaurant Brand", BRAND, "brand_image", image("oriental"))
	frappe.db.commit()
	frappe.clear_cache()
	return {"created_products": created, "updated_product_photos": len(updated),
		"menu_categories": len(CATEGORIES), "new_kitchen_stations": created_stations,
		"direct_parent_products": ["ماتشا لاتيه مثلج", "مشكل شرقي"]}


def configure_option_attributes():
	"""Map the showcase's real option levels to reusable ERPNext attributes."""
	if frappe.session.user != "Administrator":
		frappe.throw("Run restaurant attribute setup as Administrator.", frappe.PermissionError)
	mappings = {
		"باستا على ذوقك": ("نوع الباستا", ["بيني", "سباجيتي", "فيتوتشيني"]),
		"شاورما فراخ": ("الحجم", ["عادي", "كبير"]),
		"بيتزا شرقية": ("الحجم", ["صغير", "وسط", "كبير"]),
		"ليمون نعناع": ("الحجم", ["عادي", "كبير"]),
		"مشكل مشويات": ("الوزن", ["ربع كيلو", "نصف كيلو", "كيلو"]),
	}
	for shape in ("بيني", "سباجيتي", "فيتوتشيني"):
		mappings[shape] = ("الإضافة الرئيسية", ["دجاج", "لحم", "جمبري", "خضار"])
		for protein in ("بالدجاج", "باللحم", "بالجمبري", "بالخضار"):
			mappings[f"{shape} {protein}"] = ("نوع الصوص", ["طماطم", "ألفريدو"])
	attributes = {}
	for attribute, values in mappings.values():
		attributes.setdefault(attribute, [])
		for value in values:
			if value not in attributes[attribute]:
				attributes[attribute].append(value)
	for name, values in attributes.items():
		doc = frappe.get_doc("Item Attribute", name) if frappe.db.exists("Item Attribute", name) else frappe.get_doc({"doctype": "Item Attribute", "attribute_name": name})
		if doc.numeric_values or doc.disabled:
			raise ValueError(f"Choose an enabled non-numeric attribute for {name}.")
		existing = {row.attribute_value for row in doc.item_attribute_values}
		for n, value in enumerate(values, 1):
			if value not in existing:
				doc.append("item_attribute_values", {"attribute_value": value, "abbr": f"V{n}"})
		doc.save()
	configured = []
	for name, (attribute, values) in mappings.items():
		if not frappe.db.exists("Selling Product", name):
			continue
		doc = frappe.get_doc("Selling Product", name)
		if name == "باستا على ذوقك":
			option_values = {value: value for value in values}
		elif attribute in ("الحجم", "الوزن"):
			option_values = {f"{name} / {value}": value for value in values}
		elif attribute == "الإضافة الرئيسية":
			protein_names = {"دجاج": "بالدجاج", "لحم": "باللحم", "جمبري": "بالجمبري", "خضار": "بالخضار"}
			option_values = {f"{name} {protein_names[value]}": value for value in values}
		else:
			option_values = {f"{name} بصوص {('الطماطم' if value == 'طماطم' else value)}": value for value in values}
		if {row.option_product for row in doc.option_products} != set(option_values):
			raise ValueError(f"Review the option mapping for {name} before changing its attribute.")
		doc.option_attribute = attribute
		for row in doc.option_products:
			row.attribute_value = option_values[row.option_product]
		doc.save()
		configured.append(name)
	frappe.db.commit()
	frappe.clear_cache()
	return {"attributes": list(attributes), "configured_products": configured}
