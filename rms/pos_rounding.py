from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


POS_ROUNDING_METHODS = ("Round Up", "Nearest", "Round Down", "No Rounding")
DEFAULT_POS_ROUNDING_METHOD = "Nearest"


def normalize_pos_rounding_method(method):
	return method if method in POS_ROUNDING_METHODS else DEFAULT_POS_ROUNDING_METHOD


def round_pos_payable(amount, method=DEFAULT_POS_ROUNDING_METHOD):
	"""Round an EGP POS payable to a whole pound using the Restaurant Brand rule."""
	amount = Decimal(str(amount or 0))
	method = normalize_pos_rounding_method(method)
	if method == "No Rounding":
		return amount
	negative = amount < 0
	amount = abs(amount)
	strategy = {
		"Round Up": ROUND_CEILING,
		"Nearest": ROUND_HALF_UP,
		"Round Down": ROUND_FLOOR,
	}[method]
	rounded = amount.quantize(Decimal("1"), rounding=strategy)
	return -rounded if negative else rounded


def _currency_precision(doc, fieldname):
	try:
		precision = doc.precision(fieldname)
		if precision is not None:
			return max(0, int(precision))
	except (AttributeError, TypeError, ValueError):
		pass
	return 2


def _at_precision(value, precision):
	quantum = Decimal("1").scaleb(-precision)
	return Decimal(str(value or 0)).quantize(quantum, rounding=ROUND_HALF_UP)


def apply_pos_brand_rounding(doc, method=None):
	"""Apply brand rounding to the standard POS Invoice payable fields."""
	if method is None:
		method = getattr(getattr(doc, "flags", None), "rms_pos_rounding_method", None)
	if not method:
		return False

	method = normalize_pos_rounding_method(method)
	rounded_total = round_pos_payable(doc.grand_total, method)
	rounded_precision = _currency_precision(doc, "rounded_total")
	adjustment_precision = _currency_precision(doc, "rounding_adjustment")
	base_precision = _currency_precision(doc, "base_rounded_total")
	base_adjustment_precision = _currency_precision(doc, "base_rounding_adjustment")
	if method == "No Rounding":
		doc.disable_rounded_total = 1
		doc.rounded_total = float(_at_precision(doc.grand_total, rounded_precision))
		doc.rounding_adjustment = 0
		doc.base_rounded_total = float(_at_precision(doc.base_grand_total, base_precision))
		doc.base_rounding_adjustment = 0
		return True

	doc.disable_rounded_total = 0
	doc.rounded_total = float(_at_precision(rounded_total, rounded_precision))
	doc.rounding_adjustment = float(_at_precision(
		Decimal(str(doc.rounded_total)) - Decimal(str(doc.grand_total or 0)), adjustment_precision))

	conversion_rate = Decimal(str(getattr(doc, "conversion_rate", 1) or 1))
	base_rounded_total = _at_precision(Decimal(str(doc.rounded_total)) * conversion_rate, base_precision)
	doc.base_rounded_total = float(base_rounded_total)
	doc.base_rounding_adjustment = float(_at_precision(
		base_rounded_total - Decimal(str(doc.base_grand_total or 0)), base_adjustment_precision))
	return True


class POSInvoiceRoundingMixin:
	"""Keep brand rounding in place whenever ERPNext recalculates POS totals."""

	def calculate_taxes_and_totals(self):
		method = getattr(getattr(self, "flags", None), "rms_pos_rounding_method", None)
		if method:
			self.disable_rounded_total = int(normalize_pos_rounding_method(method) == "No Rounding")
		super().calculate_taxes_and_totals()
		if method:
			apply_pos_brand_rounding(self, method)
