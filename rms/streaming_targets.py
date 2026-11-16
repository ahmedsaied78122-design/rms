"""Store-only connection selection and app-managed transport scope identities."""

import uuid

import frappe
from frappe import _


def ensure_store_scope(doc):
    from arab_streaming.streaming.context import replay_source

    if replay_source() or frappe.conf.get("arab_streaming_site_role") != "Master":
        return
    previous = doc.get_doc_before_save()
    before = previous.get("streaming_branch") if previous else None
    if doc.get("streaming_branch") != before and doc.get("streaming_branch"):
        frappe.throw(_("Store connection settings are managed automatically."))
    if before and doc.get("streaming_branch") != before:
        frappe.throw(_("Store connection settings are managed automatically."))
    if not doc.name:
        return
    if not doc.get("streaming_branch"):
        name = "RMS-STORE-" + uuid.uuid4().hex[:20]
        frappe.get_doc(
            {"doctype": "Branch", "branch": name, "custom_streaming_enabled": 1}
        ).insert(ignore_permissions=True)
        doc.streaming_branch = name
    elif (
        frappe.db.get_value("Branch", doc.streaming_branch, "custom_streaming_enabled")
        != 1
    ):
        branch = frappe.get_doc("Branch", doc.streaming_branch)
        branch.custom_streaming_enabled = 1
        branch.save(ignore_permissions=True)


def install():
    """Preserve existing pair identities and provision only missing Store scopes."""
    if frappe.conf.get("arab_streaming_site_role") != "Master":
        return
    for name in frappe.get_all("Store", pluck="name"):
        doc = frappe.get_doc("Store", name)
        if not doc.streaming_branch or not frappe.db.get_value(
            "Branch", doc.streaming_branch, "custom_streaming_enabled"
        ):
            doc.save(ignore_permissions=True)


def _store_for_branch(branch):
    name = (
        frappe.db.get_value("Store", {"streaming_branch": branch}, "name")
        if branch
        else None
    )
    if not name:
        frappe.throw(
            _("Select an enabled Store for this connection."), frappe.PermissionError
        )
    doc = frappe.get_doc("Store", name)
    doc.check_permission("read")
    if not doc.enabled:
        frappe.throw(_("Choose an enabled Store."), frappe.PermissionError)
    return doc


def provide(operation, **values):
    if operation == "descriptor":
        return {"doctype": "Store", "label": "Store"}
    if operation == "choices":
        assigned = set(
            frappe.get_all(
                "Streaming Peer State",
                filters={"active_branch": ["is", "set"]},
                pluck="active_branch",
            )
        )
        rows = frappe.get_list(
            "Store",
            filters={"enabled": 1},
            fields=["name", "title", "streaming_branch"],
            order_by="title",
            limit_page_length=1000,
        )
        return {
            **provide("descriptor"),
            "targets": [
                {"name": row.name, "label": row.title or row.name}
                for row in rows
                if row.streaming_branch and row.streaming_branch not in assigned
            ],
        }
    if operation == "resolve":
        store = frappe.get_doc("Store", values["target"])
        store.check_permission("read")
        if (
            not store.enabled
            or not store.streaming_branch
            or frappe.db.exists(
                "Streaming Peer State", {"active_branch": store.streaming_branch}
            )
        ):
            frappe.throw(
                _("Choose an available Store that is not assigned to another Slave."),
                frappe.PermissionError,
            )
        return {"branch": store.streaming_branch}
    if operation == "validate":
        _store_for_branch(values["branch"])
        return True
    if operation == "describe":
        doc = values["document"]
        name = (
            frappe.db.get_value(
                "Store", {"streaming_branch": doc.get("restaurant_branch")}, "name"
            )
            if doc.get("restaurant_branch")
            else None
        )
        local = bool(name)
        if not name and doc.doctype == "Master Instance":
            facts = frappe.parse_json(doc.get("receiving_doctypes_data") or "{}")
            remote = facts.get("connection_target") or {}
            name = remote.get("name") if remote.get("doctype") == "Store" else None
        return {**provide("descriptor"), "name": name, "local": local}
    frappe.throw("Unsupported Store connection operation")


def store_connection(doc, method=None):
    role = frappe.conf.get("arab_streaming_site_role")
    type_name = "Slave Instance" if role == "Master" else "Master Instance"
    if role not in ("Master", "Slave") or not frappe.has_permission(type_name, "read"):
        return
    rows = (
        frappe.get_all(
            type_name,
            filters={"restaurant_branch": doc.get("streaming_branch")},
            fields=["name", "domain", "connection_status", "enabled"],
            order_by="modified desc",
        )
        if doc.get("streaming_branch")
        else []
    )
    peer = next(
        (r for r in rows if r.connection_status == "Connected"),
        rows[0] if rows else None,
    )
    doc.set_onload("rms_streaming_connection", {"doctype": type_name, "peer": peer})
