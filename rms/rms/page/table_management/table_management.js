frappe.pages["table-management"].on_page_load = (wrapper) => {
	set_table_navigation_state();
	new RMSTableManagement(wrapper);
};

function set_table_navigation_state() {
	const apply = () => {
		const route = (frappe.get_route?.() || []).map((part) => String(part).toLowerCase());
		const active = route.includes("table-management") || route.includes("point-of-sale");
		document.body.classList.toggle("rms-pos-active", active);
		document.querySelector(".body-sidebar-container")?.classList.toggle("rms-pos-sidebar-off", active);
	};
	apply();
	frappe.router?.on?.("change", () => requestAnimationFrame(apply));
}

class RMSTableManagement {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Tables"), single_column: true });
		this.page.main.addClass("rms-tables-page");
		this.state = { stores: [], store: null, currency: null, session: null, permissions: {}, areas: [], tables: [], area: "all", status: "all", search: "" };
		this.mount();
		this.bind();
		this.load();
	}

	call(method, args = {}) {
		return new Promise((resolve, reject) => frappe.call({ method: `rms.api.pos.${method}`, args,
			callback: (response) => resolve(response.message), error: (error) => reject(error) }));
	}

	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }
	currency(value) { return format_currency(value || 0, this.state.currency || undefined); }

	mount() {
		this.page.main.html(`
			<div class="rms-tables-shell">
				<header class="rms-tables-topbar">
					<a class="rms-tables-brand" href="/desk/rms/point-of-sale" data-action="back-pos"><span class="rms-pos-mark">R</span><span><b>RMS</b><small>${__("Restaurant service")}</small></span></a>
					<div class="rms-tables-heading"><h1>${__("Tables")}</h1><p>${__("See each dining area and manage its open checks.")}</p></div>
					<div class="rms-tables-top-actions"><label class="rms-tables-store"><span>${__("Store")}</span><select data-filter="store"></select></label><span class="rms-tables-session" data-role="session"></span><button class="btn btn-default" data-action="refresh">${__("Refresh")}</button><button class="btn btn-primary" data-action="back-pos">${__("Back to POS")}</button></div>
				</header>
				<section class="rms-tables-summary" aria-label="${__("Table summary")}">
					<div class="rms-table-summary-total"><span>${__("Total tables")}</span><strong data-count="all">0</strong></div>
					<div class="rms-table-summary-free"><span>${__("Available")}</span><strong data-count="available">0</strong></div>
					<div class="rms-table-summary-busy"><span>${__("Occupied")}</span><strong data-count="occupied">0</strong></div>
					<div class="rms-table-summary-orders"><span>${__("Open checks")}</span><strong data-count="orders">0</strong></div>
				</section>
				<section class="rms-tables-toolbar" aria-label="${__("Table filters")}">
					<div class="rms-tables-area-filter"><span>${__("Dining area / station")}</span><div class="rms-tables-area-strip" data-role="areas" role="group" aria-label="${__("Dining area / station")}"></div></div>
					<div class="rms-tables-status-filter" role="group" aria-label="${__("Table status")}">
						<button type="button" data-status="all" class="is-active">${__("All")}</button>
						<button type="button" data-status="available">${__("Available")}</button>
						<button type="button" data-status="occupied">${__("Occupied")}</button>
					</div>
					<label class="rms-tables-search"><span aria-hidden="true">⌕</span><input data-table-search type="search" placeholder="${__("Search tables or checks")}" autocomplete="off" aria-label="${__("Search tables or checks")}"></label>
				</section>
				<div class="rms-tables-content" data-role="content" aria-live="polite"></div>
			</div>`);
	}

	bind() {
		const root = this.page.main;
		root.on("change", '[data-filter="store"]', (event) => { this.state.store = event.currentTarget.value || null; this.state.area = "all"; this.load(); });
		root.on("click", "[data-area-filter]", (event) => { this.state.area = event.currentTarget.dataset.areaFilter; this.renderAreaOptions(); this.render(); });
		root.on("input", "[data-table-search]", (event) => { this.state.search = event.currentTarget.value.trim().toLocaleLowerCase(); this.render(); });
		root.on("click", "[data-status]", (event) => {
			this.state.status = event.currentTarget.dataset.status;
			root.find("[data-status]").removeClass("is-active").attr("aria-pressed", "false");
			$(event.currentTarget).addClass("is-active").attr("aria-pressed", "true");
			this.render();
		});
		root.on("click", '[data-action="back-pos"]', (event) => { event.preventDefault(); frappe.set_route("point-of-sale"); });
		root.on("click", '[data-action="refresh"]', () => this.load());
		root.on("click", "[data-new-order]", (event) => this.launchPOS({ store: this.state.store, dining_area: event.currentTarget.dataset.area, dining_table: event.currentTarget.dataset.newOrder }));
		root.on("click", "[data-open-order]", (event) => this.openOrder(event.currentTarget.dataset.openOrder));
		root.on("click", "[data-table-open]", (event) => {
			const table = this.state.tables.find((row) => row.name === event.currentTarget.dataset.tableOpen);
			if (table?.open_orders?.length) return this.openOrder(table.open_orders[0].order);
			if (table && !table.occupied) return this.launchPOS({ store: this.state.store, dining_area: table.dining_area, dining_table: table.name });
		});
		root.on("click", "[data-print-check]", (event) => this.printCheck(event.currentTarget.dataset.printCheck));
		root.on("click", "[data-pay-order]", (event) => this.launchPOS({ store: this.state.store, order_name: event.currentTarget.dataset.payOrder, action: "pay" }));
		root.on("click", "[data-toggle-more]", (event) => { const menu = event.currentTarget.parentElement.querySelector(".rms-table-more-actions"); menu.hidden = !menu.hidden; });
		root.on("click", "[data-view-order]", (event) => this.viewOrder(event.currentTarget.dataset.viewOrder));
		root.on("click", "[data-transfer-order]", (event) => this.transferOrder(event.currentTarget.dataset.transferOrder));
		root.on("click", "[data-split-order]", (event) => this.splitOrder(event.currentTarget.dataset.splitOrder));
		root.on("click", "[data-merge-order]", (event) => this.mergeOrder(event.currentTarget.dataset.mergeOrder));
		root.on("click", "[data-cancel-order]", (event) => this.cancelOrder(event.currentTarget.dataset.cancelOrder));
	}

	async load() {
		const content = this.page.main.find('[data-role="content"]');
		content.html(`<div class="rms-tables-loading"><span class="rms-tables-spinner"></span>${__("Loading tables…")}</div>`);
		try {
			const bootstrap = await this.call("get_bootstrap", {});
			this.state.stores = bootstrap.stores || [];
			this.state.session = bootstrap.session || null;
			this.state.permissions = bootstrap.permissions || {};
			this.state.store = this.state.session?.store || this.state.store || bootstrap.default_store || this.state.stores[0]?.name || null;
			if (!this.state.store) {
				content.html(`<div class="rms-tables-empty"><h2>${__("No assigned Store")}</h2><p>${__("Ask a manager to assign a Store to your POS User.")}</p></div>`);
				return;
			}
			if (!this.state.stores.some((row) => row.name === this.state.store)) this.state.store = this.state.stores[0]?.name || null;
			this.page.main.find('[data-filter="store"]').html(this.state.stores.map((row) => `<option value="${this.escape(row.name)}">${this.escape(row.title || row.name)}</option>`).join("")).val(this.state.store).prop("disabled", Boolean(this.state.session));
			const [storeBootstrap, areas, tables] = await Promise.all([
				this.call("get_bootstrap", { store: this.state.store }),
				this.call("get_dining_areas", { store: this.state.store }),
				this.call("get_tables", { store: this.state.store }),
			]);
			this.state.session = storeBootstrap.session || null;
			this.state.currency = storeBootstrap.currency || null;
			this.page.main.find('[data-filter="store"]').prop("disabled", Boolean(this.state.session));
			this.state.areas = areas || [];
			this.state.tables = tables || [];
			this.renderAreaOptions();
			this.page.main.find('[data-role="session"]').html(this.state.session
				? `<span class="rms-tables-live"></span>${this.escape(this.state.session.user_full_name || this.state.session.user)} · ${__("Session open")}`
				: `<span class="rms-tables-live is-closed"></span>${__("View mode · no cashier session")}`);
			this.render();
		} catch (error) {
			content.html(`<div class="rms-tables-error"><h2>${__("Could not load table status")}</h2><p>${this.escape(error?.message || error)}</p><button class="btn btn-default" data-action="refresh">${__("Try again")}</button></div>`);
		}
	}

	renderAreaOptions() {
		const options = [`<button type="button" data-area-filter="all" class="${this.state.area === "all" ? "is-active" : ""}" aria-pressed="${this.state.area === "all"}">${__("All areas")}</button>`, ...this.state.areas.map((area) => `<button type="button" data-area-filter="${this.escape(area.name)}" class="${this.state.area === area.name ? "is-active" : ""}" aria-pressed="${this.state.area === area.name}">${this.escape(area.title || area.name)}</button>`)];
		this.page.main.find('[data-role="areas"]').html(options.join(""));
	}

	getVisibleTables() {
		return this.state.tables.filter((table) => {
			if (this.state.area !== "all" && table.dining_area !== this.state.area) return false;
			if (this.state.status === "available" && table.occupied) return false;
			if (this.state.status === "occupied" && !table.occupied) return false;
			if (this.state.search) {
				const haystack = [table.title, table.name, table.dining_area_title,
					...(table.open_orders || []).flatMap((order) => [order.order, order.check_label, order.cashier, order.order_type])]
					.join(" ").toLocaleLowerCase();
				if (!haystack.includes(this.state.search)) return false;
			}
			return true;
		});
	}

	render() {
		const visible = this.getVisibleTables();
		const available = visible.filter((row) => !row.occupied).length;
		const occupied = visible.length - available;
		const openChecks = visible.reduce((count, row) => count + (row.open_orders || []).length, 0);
		this.page.main.find('[data-count="all"]').text(visible.length);
		this.page.main.find('[data-count="available"]').text(available);
		this.page.main.find('[data-count="occupied"]').text(occupied);
		this.page.main.find('[data-count="orders"]').text(openChecks);
		const grouped = this.state.area === "all";
		const areaGroups = grouped ? this.state.areas.map((area) => ({ ...area, tables: visible.filter((row) => row.dining_area === area.name) })).filter((area) => area.tables.length) : [{ name: this.state.area, title: this.state.areas.find((row) => row.name === this.state.area)?.title, tables: visible }];
		const html = areaGroups.map((area) => `<section class="rms-table-floor">
			<header class="rms-table-floor-head"><div><h2>${this.escape(area.title || area.name)}</h2><span>${area.tables.length} ${__("tables")}</span></div><span class="rms-table-floor-open">${area.tables.filter((row) => row.occupied).length} ${__("occupied")}</span></header>
			<div class="rms-table-floor-grid">${area.tables.map((table) => this.renderTable(table)).join("")}</div>
		</section>`).join("");
		this.page.main.find('[data-role="content"]').html(html || `<div class="rms-tables-empty"><span class="rms-tables-empty-icon">⌕</span><h2>${__("No tables match these filters")}</h2><p>${__("Change the area, status or search term to see more tables.")}</p></div>`);
	}

	renderTable(table) {
		const orders = table.open_orders || [];
		const occupied = Boolean(table.occupied);
		const ownSession = this.state.session?.status === "Open";
		const statusText = occupied ? __("Occupied") : __("Available");
		const ordersHTML = orders.map((order) => {
			const own = ownSession && order.cashier_session === this.state.session.name;
			const canEdit = own && this.state.permissions.can_checkout && ["Open", "Pending Confirmation"].includes(order.status);
			const confirmed = ["Confirmed", "In Preparation", "Ready"].includes(order.status);
			const canPrint = confirmed && this.state.permissions.can_reprint_receipts;
			const more = [
				own && this.state.permissions.can_transfer_tables ? `<button type="button" data-transfer-order="${this.escape(order.order)}">${__("Move table")}</button>` : "",
				own && this.state.permissions.can_split_orders && canEdit ? `<button type="button" data-split-order="${this.escape(order.order)}">${__("Split check")}</button>` : "",
				own && this.state.permissions.can_merge_orders && canEdit ? `<button type="button" data-merge-order="${this.escape(order.order)}">${__("Merge check")}</button>` : "",
				own && this.state.permissions.can_cancel_orders ? `<button type="button" class="is-danger" data-cancel-order="${this.escape(order.order)}">${__("Cancel order")}</button>` : "",
			].filter(Boolean).join("");
			const open = own ? `<button type="button" class="rms-table-check-open" data-open-order="${this.escape(order.order)}">${this.escape(order.check_label || order.order)}</button>` : `<strong>${this.escape(order.check_label || order.order)}</strong>`;
			const hint = confirmed ? "" : `<small class="rms-table-awaiting">${__("Confirm the order before printing or payment")}</small>`;
			const actions = `<button type="button" class="rms-table-action-print" data-print-check="${this.escape(order.order)}" ${canPrint ? "" : "disabled"} title="${canPrint ? __("Print check") : hint ? __("Confirm the order first") : __("Printing is not allowed")}">${__("Print")}</button><button type="button" class="rms-table-action-pay" data-pay-order="${this.escape(order.order)}" ${confirmed && own && this.state.permissions.can_checkout ? "" : "disabled"} title="${confirmed ? own ? __("Take payment") : __("Continue this order from its cashier session") : __("Confirm the order first")}">${__("Pay")}</button>${more ? `<button type="button" class="rms-table-action-more" data-toggle-more>${__("More")}</button><div class="rms-table-more-actions" hidden>${more}</div>` : ""}`;
			return `<article class="rms-table-check"><div class="rms-table-check-info">${open}<span>${this.escape(__(order.status))}${order.order_type ? ` · ${this.escape(__(order.order_type))}` : ""}</span><small>${this.escape(order.cashier || "")}</small></div><div class="rms-table-check-side"><b>${this.currency(order.grand_total)}</b><div class="rms-table-check-actions">${actions}</div></div>${hint}</article>`;
		}).join("");
		const first = orders[0];
		const owned = first && ownSession && first.cashier_session === this.state.session.name;
		const canOpenTable = occupied ? Boolean(owned) : Boolean(ownSession && this.state.permissions.can_checkout);
		const face = `<button type="button" class="rms-table-top" data-table-open="${this.escape(table.name)}" ${canOpenTable ? "" : "disabled"} aria-label="${this.escape(occupied ? `${__("Open check on")} ${table.title || table.name}` : `${__("Start an order at")} ${table.title || table.name}`)}"><span class="rms-table-top-name">${this.escape(table.title || table.name)}</span><span class="rms-table-top-meta">${occupied ? __("OPEN CHECK") : `${this.escape(table.capacity || 0)} ${__("seats")}`}</span></button>`;
		const orderArea = ordersHTML || (occupied ? `<p class="rms-table-hidden-order">${__("An active order is on this table.")}</p>` : `<p class="rms-table-empty-note">${__("Ready for the next guests")}</p>`);
		return `<article class="rms-table-card ${occupied ? "is-occupied" : "is-available"}">
			<header class="rms-table-card-head"><span class="rms-table-status">${statusText}</span></header>${face}
			<div class="rms-table-card-body">${orderArea}</div></article>`;
	}

	launchPOS(context) {
		if (!this.state.session || this.state.session.status !== "Open") return frappe.msgprint(__("Open your cashier session before creating a table order."));
		sessionStorage.setItem("rms-pos-launch-context", JSON.stringify(context));
		frappe.set_route("point-of-sale");
	}

	async openOrder(name) { this.launchPOS({ store: this.state.store, order_name: name }); }

	async printCheck(name) {
		const popup = window.open("", "_blank");
		if (!popup) return frappe.msgprint(__("Allow pop-ups to print the check."));
		try {
			const html = await this.call("get_open_order_check_print_html", { order_name: name });
			popup.document.open(); popup.document.write(html); popup.document.close();
		} catch (error) { popup.close(); this.showError(error); }
	}

	async viewOrder(name) {
		try {
			const order = await this.call("get_open_order_overview", { order_name: name });
			const items = (order.items || []).map((row) => `<li><span>${this.escape(row.title)} × ${this.escape(row.qty)}</span><b>${this.currency(row.amount)}</b></li>`).join("");
			const dialog = new frappe.ui.Dialog({ title: `${__("Table check")}: ${this.escape(order.check_label || order.name)}`, size: "large", fields: [
				{ fieldtype: "HTML", fieldname: "order", options: `<div class="rms-table-overview"><p>${this.escape(order.status)} · ${this.escape(order.cashier || "")}</p><ul>${items}</ul><strong>${__("Total")}: ${this.currency(order.grand_total)}</strong></div>` },
			], primary_action_label: __("Close"), primary_action: () => dialog.hide() });
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	async transferOrder(name) {
		try {
			const order = await this.call("get_open_order_overview", { order_name: name });
			const tables = (await this.call("get_tables", { store: order.store })).filter((row) => !row.occupied || row.name === order.dining_table).filter((row) => row.name !== order.dining_table);
			if (!tables.length) return frappe.msgprint(__("There are no available destination tables."));
			const dialog = new frappe.ui.Dialog({ title: __("Move order to another table"), fields: [
				{ fieldtype: "Select", fieldname: "table", label: __("Destination table"), options: tables.map((row) => `${row.name}\n`).join("").trim(), reqd: 1 },
			], primary_action_label: __("Move order"), primary_action: async (values) => {
				try { await this.call("transfer_order", { order_name: name, dining_table: values.table }); dialog.hide(); await this.load(); frappe.show_alert({ message: __("Order moved"), indicator: "green" }); }
				catch (error) { this.showError(error); }
			} });
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	async splitOrder(name) {
		try {
			const order = await this.call("get_order", { order_name: name });
			const fields = [
				{ fieldtype: "Data", fieldname: "source_check_label", label: __("Current guest / check"), default: order.check_label || __("Guest 1"), max_length: 60 },
				{ fieldtype: "Data", fieldname: "split_check_label", label: __("New guest / check"), default: __("Guest 2"), max_length: 60 },
				...order.items.map((row, index) => ({ fieldtype: "Float", fieldname: `qty_${index}`, label: `${row.title} · ${__("Available")}: ${row.qty}`, default: 0, min: 0, max: row.qty, step: row.must_be_whole_number ? 1 : 0.001 })),
			];
			const freeTables = (await this.call("get_tables", { store: order.store })).filter((row) => !row.occupied || row.name === order.dining_table);
			if (freeTables.length) fields.push({ fieldtype: "Select", fieldname: "table", label: __("Destination table"), options: freeTables.map((row) => row.name).join("\n"), default: order.dining_table, reqd: 1 });
			const dialog = new frappe.ui.Dialog({ title: __("Split table check"), fields,
				primary_action_label: __("Create split check"), primary_action: async (values) => {
					const quantities = Object.fromEntries(order.items.map((row, index) => [row.name, Number(values[`qty_${index}`] || 0)]).filter(([, qty]) => qty > 0));
					try { await this.call("split_order", { order_name: name, quantities: JSON.stringify(quantities), dining_table: values.table || order.dining_table, source_check_label: values.source_check_label, split_check_label: values.split_check_label }); dialog.hide(); await this.load(); frappe.show_alert({ message: __("New check created"), indicator: "green" }); }
					catch (error) { this.showError(error); }
				} });
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	async mergeOrder(name) {
		try {
			const order = await this.call("get_open_order_overview", { order_name: name });
			const rows = await this.call("get_store_open_orders", { store: order.store });
			const candidates = rows.filter((row) => row.name !== name && row.cashier_session === this.state.session?.name && row.status === "Open" && row.dining_table === order.dining_table && row.order_type === order.order_type);
			if (!candidates.length) return frappe.msgprint(__("No other open check on this table can be merged."));
			const dialog = new frappe.ui.Dialog({ title: __("Merge checks"), fields: [
				{ fieldtype: "Select", fieldname: "source", label: __("Merge this check into"), options: candidates.map((row) => row.name).join("\n"), reqd: 1 },
			], primary_action_label: __("Merge checks"), primary_action: async (values) => {
				try { await this.call("merge_orders", { target_order: name, source_order: values.source }); dialog.hide(); await this.load(); frappe.show_alert({ message: __("Checks merged"), indicator: "green" }); }
				catch (error) { this.showError(error); }
			} });
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	cancelOrder(name) {
		frappe.confirm(__("Cancel this open order?"), async () => {
			try { await this.call("cancel_order", { order_name: name }); await this.load(); frappe.show_alert({ message: __("Order cancelled"), indicator: "orange" }); }
			catch (error) { this.showError(error); }
		});
	}

	showError(error) {
		const raw = error?.message ?? error?.responseJSON?.message ?? error;
		const message = typeof raw === "string" ? raw : raw == null ? __("The operation could not be completed.") : JSON.stringify(raw);
		frappe.msgprint({ title: __("Table management"), message, indicator: "red" });
	}
}
