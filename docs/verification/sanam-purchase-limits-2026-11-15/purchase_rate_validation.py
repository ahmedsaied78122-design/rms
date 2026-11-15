# Rates are in company currency, after discounts and before tax, per stock UOM.
# Run after ERPNext calculates rates, on both save and submit.
item_codes = list(set(row.item_code for row in doc.get("items", []) if row.item_code))
item_limits = {}
if item_codes:
    for item in frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "item_name", "stock_uom", "is_purchase_item", "custom_minimum_purchase_rate", "custom_maximum_purchase_rate"],
    ):
        item_limits[item.name] = item
errors = []
for row in doc.get("items", []):
    item = item_limits.get(row.item_code)
    if item and item.is_purchase_item:
        minimum = frappe.utils.flt(item.custom_minimum_purchase_rate)
        maximum = frappe.utils.flt(item.custom_maximum_purchase_rate)
        if minimum > 0 or maximum > 0:
            factor = frappe.utils.flt(row.get("conversion_factor"))
            if factor <= 0:
                frappe.throw("تعذر التحقق من حدود سعر الشراء للصنف %s: معامل تحويل وحدة القياس يجب أن يكون أكبر من صفر." % frappe.utils.escape_html(row.item_code))
            if row.get("base_net_rate") is None:
                frappe.throw("تعذر التحقق من حدود سعر الشراء: لم يتم حساب صافي السعر بعملة الشركة للصنف %s." % frappe.utils.escape_html(row.item_code))
            rate = frappe.utils.flt(frappe.utils.flt(row.base_net_rate) / factor, 6)
            if (minimum > 0 and rate < minimum) or (maximum > 0 and rate > maximum):
                errors.append("السطر %s — الصنف %s: صافي سعر الشراء %s لكل %s بعملة الشركة خارج النطاق المسموح. يرجى مراجعة السعر. السعر بعد الخصم وقبل الضريبة." % (
                    row.idx,
                    frappe.utils.escape_html(row.item_code),
                    rate,
                    frappe.utils.escape_html(item.stock_uom),
                ))
if errors:
    frappe.throw("<br>".join(errors), title="سعر الشراء خارج الحدود المسموحة")
