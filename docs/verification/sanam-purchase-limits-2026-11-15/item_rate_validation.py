minimum = frappe.utils.flt(doc.get("custom_minimum_purchase_rate"))
maximum = frappe.utils.flt(doc.get("custom_maximum_purchase_rate"))
if minimum < 0 or maximum < 0:
    frappe.throw("الحد الأدنى والحد الأقصى لسعر الشراء لا يمكن أن يكونا أقل من صفر. اترك الحد فارغًا أو صفرًا ليكون مفتوحًا.")
if minimum > 0 and maximum > 0 and minimum > maximum:
    frappe.throw("الحد الأدنى لسعر الشراء لا يمكن أن يكون أكبر من الحد الأقصى.")
