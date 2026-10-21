frappe.pages["kitchen-display"].on_page_load = (wrapper) => {
	new RMSKitchenDisplay(wrapper);
};

class RMSKitchenDisplay {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Kitchen Display"), single_column: true });
		this.page.main.addClass("rms-kds-page");
		this.state = { stores: [], store: null, areas: [], area: null, tickets: [], permissions: {}, loading: false };
		this.mount();
		this.bind();
		this.loadStores();
		this.startRefresh();
	}

	call(method, args = {}) {
		return new Promise((resolve, reject) => frappe.call({ method: `rms.api.pos.${method}`, args,
			callback: (response) => resolve(response.message), error: (error) => reject(error) }));
	}

	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }

	mount() {
		this.page.main.html(`<section class="rms-kds-shell"><header class="rms-kds-header"><div class="rms-kds-brand"><span class="rms-kds-mark">R</span><div><b>${__("Kitchen Display")}</b><small>${__("Live preparation queue")}</small></div></div><div class="rms-kds-picks"><label>${__("Store")}<select data-kds-select="store"></select></label><label>${__("Preparation Area")}<select data-kds-select="area"></select></label></div><div class="rms-kds-live"><i></i>${__("LIVE")}</div></header><main class="rms-kds-main"><div class="rms-kds-summary"><div><span>${__("Tickets awaiting action")}</span><b data-kds-count>0</b></div><button class="btn btn-default" data-kds-refresh>${__("Refresh")}</button></div><div class="rms-kds-tickets" data-kds-tickets></div></main></section>`);
	}

	bind() {
		const root = this.page.main.get(0);
		root.addEventListener("change", (event) => {
			const select = event.target.closest("[data-kds-select]");
			if (!select) return;
			if (select.dataset.kdsSelect === "store") { this.state.store = select.value || null; this.state.area = null; this.loadBoard(); }
			else { this.state.area = select.value || null; this.loadBoard(); }
		});
		root.addEventListener("click", (event) => {
			if (event.target.closest("[data-kds-refresh]")) return this.loadBoard();
			const action = event.target.closest("[data-kds-ticket-action]");
			if (action) this.updateTicket(action.dataset.name, action.dataset.kdsTicketAction);
		});
	}

	async loadStores() {
		try {
			this.state.stores = await this.call("get_kitchen_stores");
			this.state.store = this.state.stores[0]?.name || null;
			this.renderFilters();
			await this.loadBoard();
		} catch (error) { this.showError(error); }
	}

	async loadBoard() {
		if (!this.state.store || this.state.loading) return;
		this.state.loading = true;
		try {
			const result = await this.call("get_kitchen_board", { store: this.state.store, preparation_area: this.state.area });
			this.state.areas = result.areas || [];
			this.state.permissions = result.permissions || {};
			if (this.state.area && !this.state.areas.some((area) => area.name === this.state.area)) this.state.area = null;
			this.state.tickets = result.tickets || [];
			this.renderFilters(); this.renderTickets();
		} catch (error) { this.showError(error); }
		finally { this.state.loading = false; }
	}

	startRefresh() {
		this.refreshTimer = setInterval(() => this.loadBoard(), 15000);
		this.page.wrapper?.on?.("hide", () => clearInterval(this.refreshTimer));
	}

	async updateTicket(name, status) {
		try { await this.call("set_kitchen_ticket_status", { ticket_name: name, status }); await this.loadBoard(); }
		catch (error) { this.showError(error); }
	}

	renderFilters() {
		const storeSelect = this.page.main.find('[data-kds-select="store"]');
		storeSelect.html(this.options(this.state.stores, this.state.store, __("Select Store")));
		const areaSelect = this.page.main.find('[data-kds-select="area"]');
		areaSelect.html(this.options(this.state.areas, this.state.area, __("All preparation areas"))).prop("disabled", !this.state.store || !this.state.areas.length);
	}

	options(rows, selected, empty) {
		return `<option value="">${this.escape(empty)}</option>${rows.map((row) => `<option value="${this.escape(row.name)}" ${row.name === selected ? "selected" : ""}>${this.escape(row.title || row.name)}</option>`).join("")}`;
	}

	renderTickets() {
		this.page.main.find("[data-kds-count]").text(this.state.tickets.length);
		const html = this.state.tickets.length ? this.state.tickets.map((ticket) => {
			const cancelled = ticket.status === "Cancelled";
			const next = cancelled || ["Pending", "Started"].includes(ticket.status) && !this.state.permissions.can_prepare_orders || ticket.status === "Ready" && !this.state.permissions.can_pick_orders ? null : { Pending: ["Started", __("Start Preparing")], Started: ["Ready", __("Mark Ready")], Ready: ["Picked", __("Mark Picked Up")] }[ticket.status];
			const lines = ticket.lines.map((line) => `<article class="rms-kds-line"><div class="rms-kds-line-title"><b>${this.escape(line.remaining_qty)} × ${this.escape(line.title || line.selling_product)}</b><span class="rms-kds-line-status">${this.escape(line.status)}</span></div>${Number(line.cancelled_qty) > 0 ? `<p class="rms-kds-cancellation">${__("Cancel")}: ${this.escape(line.cancelled_qty)}</p>` : ""}${line.modifier_summary ? `<p>${this.escape(line.modifier_summary).replaceAll("\n", " · ")}</p>` : ""}${line.notes ? `<p class="rms-kds-note">${this.escape(line.notes)}</p>` : ""}</article>`).join("");
			const action = cancelled && this.state.permissions.can_acknowledge_cancellations ? `<button class="btn btn-default" data-kds-ticket-action="Acknowledge Cancellation" data-name="${this.escape(ticket.name)}">${__("Acknowledge cancellation")}</button>` : next ? `<button class="btn btn-primary" data-kds-ticket-action="${next[0]}" data-name="${this.escape(ticket.name)}">${next[1]}</button>` : "";
			return `<section class="rms-kds-ticket rms-kds-${this.escape(ticket.status.toLowerCase().replaceAll(" ", "-"))}"><header><span class="rms-kds-ticket-tag">${this.escape(ticket.is_item_cancellation_notice ? __("Item cancellation") : ticket.name)}</span><span class="rms-kds-status">${this.escape(ticket.status)}</span></header><div class="rms-kds-ticket-context"><b>${this.escape(ticket.order_type)}</b><span>${this.escape(ticket.dining_table || __("Counter"))}</span><small>${this.escape(ticket.preparation_area)}</small></div>${ticket.cancellation_reason ? `<p class="rms-kds-cancellation">${this.escape(ticket.cancellation_reason)}</p>` : ""}<div class="rms-kds-lines">${lines}</div><footer><time>${this.escape(ticket.sent_at ? frappe.datetime.prettyDate(ticket.sent_at) : "")}</time>${action}</footer></section>`;
		}).join("") : `<div class="rms-kds-empty"><div>✓</div><h2>${__("All caught up")}</h2><p>${__("New kitchen tickets for this Store will appear here.")}</p></div>`;
		this.page.main.find("[data-kds-tickets]").html(html);
	}

	showError(error) { frappe.msgprint({ title: __("Kitchen Display"), message: error?.message || error, indicator: "red" }); }
}
