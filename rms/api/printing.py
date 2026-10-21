import json
import socket
import struct
import subprocess
from urllib.parse import urlsplit, urlunsplit
import urllib.request

import frappe
from frappe import _
from frappe.utils import now_datetime


PRINT_JOB_FIELDS = [
	"name", "store", "preparation_area", "print_device", "status", "document_type",
	"document_name", "attempt_count", "last_error", "queued_at", "printed_at",
]
PRINT_JOB_STATUSES = {"Queued", "Printing", "Printed", "Failed", "Cancelled"}


def _require_print_manager():
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Guest" or not roles & {"POS Manager", "System Manager"}:
		frappe.throw(_("Only POS Managers can manage print jobs."), frappe.PermissionError)
	return user, roles


def _user_has_store_access(user, store):
	from rms.api.pos import _user_has_store_access as has_store_access
	return has_store_access(user, store)


def get_print_dispatch_job_permission_query(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return ""
	if "POS Manager" not in roles:
		return "1 = 0"
	pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1}, "name")
	user_sql = frappe.db.escape(user)
	if pos_user:
		return (
			"`tabPrint Dispatch Job`.store in (select pus.store from `tabPOS User Store` pus "
			"inner join `tabPOS User` pu on pu.name = pus.parent "
			f"where pus.parenttype = 'POS User' and pu.user = {user_sql} and pu.enabled = 1)"
		)
	return (
		"(`tabPrint Dispatch Job`.store in (select sua.parent from `tabStore User Assignment` sua "
		f"where sua.user = {user_sql} and sua.enabled = 1) "
		"or not exists (select 1 from `tabStore User Assignment` sua2 "
		"where sua2.parent = `tabPrint Dispatch Job`.store and sua2.enabled = 1))"
	)


def has_print_dispatch_job_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return True
	return bool(
		"POS Manager" in roles
		and permission_type == "read"
		and _user_has_store_access(user, doc.store)
	)


@frappe.whitelist()
def get_print_dispatch_jobs(store=None, status=None):
	user, roles = _require_print_manager()
	if store and user != "Administrator" and "System Manager" not in roles and not _user_has_store_access(user, store):
		frappe.throw(_("You do not have access to this Store."), frappe.PermissionError)
	if status and status not in PRINT_JOB_STATUSES:
		frappe.throw(_("Invalid print job status."))
	filters = {}
	if store:
		filters["store"] = store
	if status:
		filters["status"] = status
	return frappe.get_list(
		"Print Dispatch Job", filters=filters, fields=PRINT_JOB_FIELDS,
		order_by="modified desc", limit_page_length=100,
	)


@frappe.whitelist()
def retry_print_job(print_job_name):
	user, roles = _require_print_manager()
	job = frappe.get_doc("Print Dispatch Job", print_job_name)
	if user != "Administrator" and "System Manager" not in roles and not _user_has_store_access(user, job.store):
		frappe.throw(_("You do not have access to this Store."), frappe.PermissionError)
	job.retry()
	return {"name": job.name, "status": job.status, "attempt_count": job.attempt_count}


def process_print_job(print_job_name):
	job = frappe.get_doc("Print Dispatch Job", print_job_name)
	if job.status != "Queued":
		return

	device = frappe.get_doc("Print Device", job.print_device)
	job.status = "Printing"
	job.attempt_count = (job.attempt_count or 0) + 1
	job.save(ignore_permissions=True)

	try:
		payload = render_ticket(job)
		dispatch(device, payload)
		job.status = "Printed"
		job.printed_at = now_datetime()
		job.last_error = None
	except Exception as error:
		job.status = "Failed"
		job.last_error = str(error)[:2000]
	job.save(ignore_permissions=True)


def render_ticket(job):
	if job.document_type != "Kitchen Ticket":
		try:
			data = json.loads(job.payload or "{}")
			return f"RMS PRINT JOB\n{data}\n".encode("utf-8")
		except Exception:
			return (job.payload or "").encode("utf-8")
	if (job.payload or "").startswith("CANCEL "):
		ticket = frappe.get_doc("Kitchen Ticket", job.document_name)
		order = frappe.get_doc("POS Order", ticket.pos_order)
		store = frappe.db.get_value("Store", job.store, "title") or job.store
		area = frappe.db.get_value("Preparation Area", job.preparation_area, "title") or job.preparation_area
		order_context = f"{order.order_type} · {order.dining_table}" if order.dining_table else order.order_type
		return "\n".join(["\x1b@", "\x1ba\x01", store, area, f"Order {order.name}", order_context,
			"*** ITEM CANCELLATION ***",
			job.payload, "\x1ba\x00", "\n\n\x1dV\x00"]).encode("utf-8")

	ticket = frappe.get_doc("Kitchen Ticket", job.document_name)
	order = frappe.get_doc("POS Order", ticket.pos_order)
	store = frappe.db.get_value("Store", ticket.store, "title") or ticket.store
	area = frappe.db.get_value("Preparation Area", ticket.preparation_area, "title") or ticket.preparation_area
	lines = ["\x1b@", "\x1ba\x01", store, area, f"Ticket {ticket.name}", f"Order {order.name}", "\x1ba\x00", "-" * 32]
	if ticket.status == "Cancelled":
		lines.insert(4, "*** CANCELLED ***")
	for row in ticket.items:
		name = frappe.db.get_value("Selling Product", row.selling_product, "title") or row.selling_product
		lines.append(f"{row.qty:g} x {name}")
		if row.modifier_summary:
			lines.extend(f"  + {value}" for value in row.modifier_summary.splitlines())
		if row.notes:
			lines.append(f"  {row.notes}")
	lines.extend(["-" * 32, "\n\n\x1dV\x00"])
	return "\n".join(lines).encode("utf-8")


def dispatch(device, payload):
	if device.print_method == "Network Socket":
		with socket.create_connection((device.host, int(device.port)), timeout=10) as connection:
			connection.sendall(payload)
		return

	if device.print_method == "IPP":
		print_ipp(device.ipp_url, payload)
		return

	if device.print_method == "System Queue":
		process = subprocess.run(
			["lp", "-d", device.queue_name],
			input=payload,
			capture_output=True,
			timeout=30,
			check=False,
		)
		if process.returncode:
			raise RuntimeError(process.stderr.decode("utf-8", errors="replace") or "System print queue failed.")
		return

	raise ValueError(f"Unsupported Print Method: {device.print_method}")


def print_ipp(url, payload):
	parts = urlsplit(url)
	transport_scheme = {"ipp": "http", "ipps": "https", "http": "http", "https": "https"}.get(parts.scheme.lower())
	if not transport_scheme or not parts.netloc or not parts.path:
		raise ValueError("IPP URL must use ipp://, ipps://, http:// or https:// and include a printer path.")
	transport_url = urlunsplit((transport_scheme, parts.netloc, parts.path, parts.query, ""))
	request_id = 1
	attributes = bytearray(b"\x01\x01\x00\x02" + struct.pack(">I", request_id) + b"\x01")
	attributes += ipp_attribute(0x47, "attributes-charset", "utf-8")
	attributes += ipp_attribute(0x48, "attributes-natural-language", "en")
	attributes += ipp_attribute(0x45, "printer-uri", url)
	attributes += ipp_attribute(0x42, "requesting-user-name", "RMS")
	attributes += ipp_attribute(0x49, "document-format", "application/octet-stream")
	attributes += b"\x03" + payload

	request = urllib.request.Request(
		transport_url,
		data=bytes(attributes),
		headers={"Content-Type": "application/ipp", "Accept": "application/ipp"},
		method="POST",
	)
	with urllib.request.urlopen(request, timeout=20) as response:
		result = response.read()
	if len(result) < 4:
		raise RuntimeError("IPP printer returned an incomplete response.")
	status_code = struct.unpack(">H", result[2:4])[0]
	if status_code >= 0x0400:
		raise RuntimeError(f"IPP printer rejected the job with status 0x{status_code:04x}.")


def ipp_attribute(tag, name, value):
	name_bytes = name.encode("utf-8")
	value_bytes = value.encode("utf-8")
	return (
		bytes([tag])
		+ struct.pack(">H", len(name_bytes))
		+ name_bytes
		+ struct.pack(">H", len(value_bytes))
		+ value_bytes
	)
