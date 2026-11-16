frappe.pages["point-of-sale"].on_page_load = (wrapper) => {
	set_pos_navigation_state(true);
	new RMSPointOfSale(wrapper);
};

function set_pos_navigation_state(is_pos) {
	const apply = (active) => {
		document.body.classList.toggle("rms-pos-active", active);
		// Frappe keeps the workspace rail in the Desk layout while a custom Page is open.
		// The register is full-screen, so it should not reserve or overlay that rail.
		document.querySelector(".body-sidebar-container")?.classList.toggle("rms-pos-sidebar-off", active);
	};
	apply(is_pos);
	if (!window.rmsPosKeyboardBoundary) {
		window.rmsPosKeyboardBoundary = true;
		document.addEventListener("keydown", (event) => {
			if (!document.body.classList.contains("rms-pos-active") || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") return;
			event.preventDefault();
			event.stopImmediatePropagation();
			document.querySelector(".rms-pos-page [data-search]:not(:disabled), .rms-tables-page [data-table-search]")?.focus();
		}, true);
	}
	if (!window.rmsPosRouteListener && frappe.router?.on) {
		window.rmsPosRouteListener = true;
		frappe.router.on("change", () => {
			requestAnimationFrame(() => {
				const route = (frappe.get_route?.() || []).map((part) => String(part).toLowerCase());
				apply(route.includes("point-of-sale") || route.includes("table-management"));
				if (route.includes("point-of-sale")) window.rmsPointOfSale?.consumeLaunchContext();
			});
		});
	}
}

class RMSPointOfSale {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Point of Sale"), single_column: true });
		this.page.main.addClass("rms-pos-page");
		this.state = { stores: [], store: null, brands: [], order_types: [], session: null, currency: null, permissions: {},
			brand: null, order_type: null, categories: [], category: null, catalog_mode: "categories", products: [], cart: [], order_name: null,
			customer: null, dining_area: null, dining_table: null, tables: [], search: "", busy: false,
			bootstrap_loading: true, catalog_loading: false,
			discount_type: "Percentage", discount_scope: "Net Total", discount_value: 0, discount_reason: "" };
		this.catalogRequestId = 0;
		this.saveQueue = Promise.resolve();
		const orderRoute = this.readOrderRoute();
		this.pendingLaunchContext = orderRoute ? null : this.readLaunchContext();
		this.pendingResumeContext = orderRoute || this.pendingLaunchContext ? null : this.readResumeContext();
		this.mount();
		this.page.main.toggleClass("rms-pos-restoring", Boolean(orderRoute || this.pendingResumeContext || this.pendingLaunchContext?.order_name));
		this.page.main.append(`<div class="rms-pos-restore-status" role="status"><span class="rms-pos-loading-spinner" aria-hidden="true"></span><span>${__("Restoring your order…")}</span></div>`);
		this.bind();
		this.startOrderSync();
		window.rmsPointOfSale = this;
		if (orderRoute) this.openOrderRoute(orderRoute);
		else this.loadBootstrap(this.pendingLaunchContext?.store || this.pendingResumeContext?.store || null);
	}

	readOrderRoute() {
		try {
			const url = new URL(window.location.href);
			if (!/\/point-of-sale\/?$/.test(url.pathname)) return null;
			const name = url.searchParams.get("order") || frappe.route_options?.order;
			if (typeof name !== "string" || !name.trim()) return null;
			const screen = url.searchParams.get("screen") || frappe.route_options?.screen;
			return { order_name: name, screen: screen === "payment" ? "payment" : "sale" };
		} catch (_) { return null; }
	}

	syncOrderRoute() {
		if (this.openingOrderRoute) return;
		try {
			const url = new URL(window.location.href);
			if (!/\/point-of-sale\/?$/.test(url.pathname)) return;
			if (this.state.order_name && !["Paid", "Cancelled"].includes(this.state.order_status)) {
				url.searchParams.set("order", this.state.order_name);
				if (this.currentOrderScreen === "payment") url.searchParams.set("screen", "payment");
				else url.searchParams.delete("screen");
			} else {
				url.searchParams.delete("order");
				url.searchParams.delete("screen");
			}
			// Replace the address without reloading Desk or adding a history entry per save.
			if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url.href);
			// Frappe can deliver a clicked Desk link's query through route_options.
			if (frappe.route_options) {
				delete frappe.route_options.order;
				delete frappe.route_options.screen;
			}
		} catch (_) { /* Storage/history restrictions must not interrupt the sale. */ }
	}

	async openOrderRoute(route) {
		if (this.openingOrderRoute) return;
		this.openingOrderRoute = true;
		this.state.bootstrap_loading = true;
		this.page.main.toggleClass?.("rms-pos-restoring", true);
		let restored = false;
		try {
			await this.flushDraftSave();
			// Resolve the branch through the existing permission-checked order API.
			const order = await this.call("get_order", { order_name: route.order_name });
			this.pendingLaunchContext = null;
			try { sessionStorage.removeItem("rms-pos-launch-context"); } catch (_) {}
			this.pendingResumeOrder = order;
			this.pendingResumeContext = { ...route, store: order.store, from_url: true };
			restored = await this.loadBootstrap(order.store);
		} catch (error) {
			this.clearUnavailableStoreContext();
			restored = await this.loadBootstrap();
			this.showError(error);
		} finally {
			this.openingOrderRoute = false;
		}
		if (restored && (this.state.order_name === route.order_name || !this.state.order_name)) this.syncOrderRoute();
	}

	resumeStorageKey() { return `rms-pos-current-order:${frappe.session?.user || ""}`; }

	readResumeContext() {
		try {
			const saved = JSON.parse(sessionStorage.getItem(this.resumeStorageKey()) || "null");
			return saved && [saved.store, saved.order_name, saved.session].every(value => typeof value === "string" && value)
				? saved : null;
		} catch (_) { return null; }
	}

	rememberCurrentScreen(screen = this.currentOrderScreen || "sale") {
		this.currentOrderScreen = screen;
		this.syncOrderRoute();
		try {
			if (!this.state.order_name || !this.state.session?.name) {
				sessionStorage.removeItem(this.resumeStorageKey());
				return;
			}
			sessionStorage.setItem(this.resumeStorageKey(), JSON.stringify({ store: this.state.store,
				order_name: this.state.order_name, session: this.state.session.name, screen }));
		} catch (_) { /* The register still works when browser storage is unavailable. */ }
	}

	async restoreCurrentOrder() {
		const saved = this.pendingResumeContext;
		if (!saved) return;
		this.pendingResumeContext = null;
		if (saved.store !== this.state.store || (!saved.from_url && saved.session !== this.state.session?.name)) {
			this.rememberCurrentScreen("sale");
			return;
		}
		const order = this.pendingResumeOrder || await this.call("get_order", { order_name: saved.order_name });
		this.pendingResumeOrder = null;
		if (order.store !== this.state.store || order.docstatus === 2 || ["Paid", "Cancelled"].includes(order.status)) {
			if (saved.from_url) this.resetSale();
			frappe.show_alert({ message: __("The previous order has already been closed. A new sale is ready."), indicator: "orange" });
			this.rememberCurrentScreen("sale");
			return;
		}
		await this.loadOrder(order, { deferMenu: true });
		if (saved.screen === "payment" && ["Confirmed", "In Preparation", "Ready"].includes(order.status)
			&& this.state.permissions.can_checkout && !this.state.cross_session_edit) this.showPaymentScreen();
	}

	readLaunchContext() {
		try {
			const raw = sessionStorage.getItem("rms-pos-launch-context");
			return raw ? JSON.parse(raw) : null;
		} catch (_) { return null; }
	}

	call(method, args = {}, options = {}) {
		return new Promise((resolve, reject) => frappe.call({ method: `rms.api.pos.${method}`, args, silent: Boolean(options.silent),
			callback: (r) => resolve(r.message), error: (e) => { if (options.silent) e.rmsSilent = true; reject(e); } }));
	}

	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }
	currency(value) { return format_currency(value || 0, this.state.currency || undefined); }
	orderNumber(name) {
		const value = String(name || "");
		const match = value.match(/(?:^|-)(\d+)$/);
		return match ? String(Number(match[1])) : value;
	}

	getPosRoundingMethod(brandName = this.state.brand) {
		const brand = (this.state.brands || []).find((row) => row.name === brandName);
		return ["No Rounding", "Round Up", "Nearest", "Round Down"].includes(brand?.pos_rounding_method)
			? brand.pos_rounding_method : "Nearest";
	}

	roundPosPayable(amount, method = this.getPosRoundingMethod()) {
		const value = Number(amount) || 0;
		const epsilon = 1e-9;
		if (method === "No Rounding") return value;
		const magnitude = Math.abs(value);
		const rounded = method === "Round Up" ? Math.ceil(magnitude - epsilon)
			: method === "Round Down" ? Math.floor(magnitude + epsilon) : Math.floor(magnitude + 0.5 + epsilon);
		return value < 0 ? -rounded : rounded;
	}

	getSuggestedPaymentAmounts(total) {
		const due = Math.max(0, Number(total) || 0);
		if (!due) return [];
		const roundUp = (denomination) => Math.ceil((due - 1e-9) / denomination) * denomination;
		const values = [due, roundUp(5), roundUp(10), roundUp(50), roundUp(100), roundUp(200)];
		return [...new Set(values.map((value) => Math.round(value * 100) / 100))];
	}

	renderSuggestedPaymentAmounts(total) {
		return this.getSuggestedPaymentAmounts(total).map((amount) => `<button type="button" data-action="payment-quick" data-amount="${amount}">${amount === Number(total) ? __("Exact") : this.currency(amount)}</button>`).join("");
	}

	updateSuggestedPaymentAmounts() {
		const container = this.page.main[0].querySelector("[data-suggested-payment-amounts]");
		if (container) container.innerHTML = this.renderSuggestedPaymentAmounts(this.paymentTotal);
	}

	handlePaymentKey(key) {
		const input = this.paymentInput?.isConnected ? this.paymentInput : this.page.main[0].querySelector("[data-payment-amount], [data-guest-amount]");
		if (!input || input.disabled || input.readOnly) return;
		if (key === "C") { input.value = ""; this.paymentKeypadInput = input; }
		else {
			let value = this.paymentKeypadInput === input ? String(input.value || "") : "";
			if (key === "." && value.includes(".")) return;
			if (key === "." && !value) value = "0";
			input.value = value + key;
			this.paymentKeypadInput = input;
		}
		input.dispatchEvent(new Event("input", { bubbles: true }));
	}

	userMenuIdentity() {
		const name = String(frappe.boot?.user?.full_name || frappe.session?.user_fullname || frappe.session?.user || __("User"));
		return { name: this.escape(name), initial: this.escape(name.trim().charAt(0).toLocaleUpperCase()) };
	}

	userMenuIcon(name) {
		const paths = {
			expenses: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6"/>',
			returns: '<path d="m9 5-5 5 5 5M4 10h10a6 6 0 0 1 0 12"/>',
			history: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
			approvals: '<path d="m8 12 3 3 6-7M12 2 4 5v7c0 5 8 10 8 10s8-5 8-10V5z"/>',
			account: '<circle cx="12" cy="8" r="4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/>',
			language: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a20 20 0 0 1 0 18 20 20 0 0 1 0-18"/>',
			apps: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
			logout: '<path d="M9 4H4v16h5M14 8l4 4-4 4M8 12h13"/>',
			settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor" stroke="none"/><circle cx="15" cy="17" r="3" fill="currentColor" stroke="none"/>',
		};
		return `<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ""}</svg>`;
	}

	mount() {
		const identity = this.userMenuIdentity();
		this.page.main.html(`
			<section class="rms-pos-shell" aria-label="${__("Point of Sale")}">
				<header class="rms-pos-topbar">
					<div class="rms-pos-brand"><span class="rms-pos-mark" aria-hidden="true">R</span><div><strong>RMS</strong><small>${__("Restaurant & Retail")}</small></div></div>
					<div class="rms-pos-header-tools">
						<div class="rms-pos-order-picker" data-order-type-picker>
							<select data-select="order_type" hidden tabindex="-1" aria-hidden="true" disabled></select>
							<button type="button" class="rms-pos-order-type-toggle" data-order-type-toggle aria-haspopup="listbox" aria-controls="rms-pos-order-types" aria-expanded="false" disabled><span><small>${__("Order Type")}</small><strong data-role="order-type-label"></strong></span><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>
							<div class="rms-pos-order-type-list" id="rms-pos-order-types" data-order-type-list role="listbox" aria-label="${__("Order Type")}" hidden></div>
						</div>
						<div class="rms-pos-view-switch" role="tablist" aria-label="${__("Menu view")}"><button type="button" role="tab" data-catalog-mode="categories">${__("Categories")}</button><button type="button" role="tab" data-catalog-mode="products" aria-selected="true">${__("Products")}</button></div>
						<div class="rms-pos-toolbar"><label class="rms-pos-search"><span aria-hidden="true">⌕</span><input data-search type="search" placeholder="${__("Search products or scan a barcode")}" disabled autocomplete="off" aria-label="${__("Search products or scan a barcode")}"></label><button type="button" class="rms-pos-scan" data-action="scan" disabled aria-label="${__("Focus barcode search")}">▦</button></div>
						<span class="rms-pos-catalog-count sr-only" data-role="catalog-count"></span>
					</div>
					<div class="rms-pos-header-actions">
						<button class="rms-pos-quiet-action" data-action="open-orders" data-capability="can_view_open_orders">${__("Open Orders")}</button>
						<button class="rms-pos-quiet-action" data-action="table-map" data-capability="can_view_tables">${__("Tables")}</button>
						<button class="rms-pos-quiet-action" data-action="kitchen-display" data-capability="can_access_kitchen">${__("Kitchen")}</button>
						<button class="rms-pos-session-action" data-action="session">${__("Open Session")}</button>
						<div class="rms-pos-more-actions" data-more-actions>
							<button type="button" class="rms-pos-quiet-action rms-pos-more-toggle" data-more-toggle aria-haspopup="menu" aria-expanded="false" aria-controls="rms-pos-actions-menu" aria-label="${__("User Menu")}: ${identity.name}"><span class="rms-pos-user-avatar" aria-hidden="true">${identity.initial}</span><span class="rms-pos-user-name">${identity.name}</span><span class="rms-pos-more-caret" aria-hidden="true">▾</span></button>
							<div class="rms-pos-actions-menu" id="rms-pos-actions-menu" data-actions-menu role="menu" aria-label="${__("User Menu")}" dir="${frappe.utils.is_rtl() ? "rtl" : "ltr"}" hidden>
								<div class="rms-pos-user-identity" role="presentation"><span class="rms-pos-user-avatar" aria-hidden="true">${identity.initial}</span><div><strong>${identity.name}</strong><small>${__("Signed in")}</small></div></div>
								<div class="rms-pos-session-status" data-role="context"><span class="rms-pos-live"></span><span>${__("Cashier session closed")}</span></div>
								<span class="rms-pos-actions-caption" role="presentation">${__("Cashier actions")}</span>
								<button type="button" role="menuitem" tabindex="-1" data-action="expenses">${this.userMenuIcon("expenses")}${__("Expenses")}</button>
								<button type="button" role="menuitem" tabindex="-1" data-action="returns">${this.userMenuIcon("returns")}${__("Returns")}</button>
								<button type="button" role="menuitem" tabindex="-1" data-action="sales-history" data-capability="can_view_sales_history">${this.userMenuIcon("history")}${__("Sales History")}</button>
								<button type="button" role="menuitem" tabindex="-1" data-action="operation-approvals" data-capability="can_approve_discount">${this.userMenuIcon("approvals")}${__("Approvals")}</button>
								<span class="rms-pos-actions-caption rms-pos-actions-divider" role="presentation">${__("Account")}</span>
								<button type="button" role="menuitem" tabindex="-1" data-action="my-account">${this.userMenuIcon("account")}<span class="rms-pos-setup-entry-copy"><strong>${__("My Account")}</strong><small data-role="setup-summary"></small></span><span aria-hidden="true">›</span></button>
								<div class="rms-pos-language-row"><span>${this.userMenuIcon("language")}${__("Language")}</span><div class="rms-pos-language-choices" role="group" aria-label="${__("Language")}"><button type="button" role="menuitemradio" tabindex="-1" data-language="ar" lang="ar" aria-checked="false">العربية</button><button type="button" role="menuitemradio" tabindex="-1" data-language="en" lang="en" aria-checked="false">English</button></div></div>
								<button type="button" role="menuitem" tabindex="-1" data-action="switch-apps">${this.userMenuIcon("apps")}${__("Back to Apps")}</button>
								<button type="button" role="menuitem" tabindex="-1" class="rms-pos-actions-signout" data-action="logout">${this.userMenuIcon("logout")}${__("Sign Out")}</button>
							</div>
							<div class="rms-pos-setup-panel" id="rms-pos-setup-panel" data-pos-setup role="dialog" aria-label="${__("My Account")}" hidden>
								<div class="rms-pos-setup-heading"><button type="button" class="rms-pos-setup-back" data-setup-back aria-label="${__("User Menu")}"><span aria-hidden="true">‹</span></button><strong>${__("My Account")}</strong><button type="button" data-setup-close aria-label="${__("Close")}">×</button></div>
								<div class="rms-pos-account-identity"><span class="rms-pos-user-avatar" aria-hidden="true">${identity.initial}</span><div><strong>${identity.name}</strong><small>${this.escape(frappe.session?.user || "")}</small></div></div>
								<div class="rms-pos-session-status" data-role="context"></div>
								<p class="rms-pos-account-caption">${__("Store and brand")}</p>
								<div class="rms-pos-context-fields">
									<label>${__("Store")}<select data-select="store"></select></label>
									<label>${__("Brand")}<select data-select="brand" disabled></select></label>
								</div>
								<p data-role="setup-hint"></p>
							</div>
						</div>
					</div>
				</header>
				<div class="rms-pos-layout">
					<main class="rms-pos-catalog">
						<div class="rms-pos-heading sr-only"><h1>${__("Menu")}</h1><p data-role="catalog-hint">${__("Select a Store, Brand and Order Type to browse the menu.")}</p></div>
						<nav class="rms-pos-categories" data-role="categories" aria-label="${__("Product categories")}"></nav>

						<div class="rms-pos-category-browser" data-category-browser>
							<div class="rms-pos-category-context" data-role="category-context" hidden></div>
							<div class="rms-pos-catalog-results">
								<button type="button" class="rms-pos-category-backdrop" data-category-nav-close tabindex="-1" aria-label="${__("Close subcategories")}" hidden></button>
								<nav class="rms-pos-category-rail" id="rms-pos-subcategories" data-role="subcategories" aria-label="${__("Subcategories")}" hidden></nav>
								<div class="rms-pos-product-grid" data-role="products" aria-live="polite"></div>
							</div>
						</div>
					</main>
					<aside class="rms-pos-cart" aria-label="${__("Current order")}">
						<div class="rms-pos-cart-head"><div><span class="rms-pos-eyebrow">${__("CURRENT ORDER")}</span><h2 data-role="cart-title">${__("New sale")}</h2></div><div class="rms-pos-cart-head-tools"><button class="rms-pos-new-sale" data-action="new-sale" hidden>${__("New sale")}</button><span class="rms-pos-ticket" data-role="ticket">${__("Draft")}</span></div></div>
						<div class="rms-pos-order-meta"><label>${__("Customer")}<button class="rms-pos-meta-button" data-action="customer">${__("Walk-in Customer")}</button></label><div class="rms-pos-table-fields" data-role="dining-wrap" hidden><label>${__("Dining Area")}<select data-select="dining_area" disabled><option value="">${__("Not applicable")}</option></select></label><label>${__("Table")}<select data-select="dining_table" disabled><option value="">${__("Not applicable")}</option></select></label></div><label data-role="reference-wrap" hidden>${__("External Reference")}<input data-input="external_reference" /></label></div>
						<div class="rms-pos-order-comment"><button type="button" data-action="order-notes">${__("Order comment")}</button><p data-role="order-notes" hidden></p></div>
						<div class="rms-pos-cart-tabs" data-role="cart-tabs" role="tablist" aria-label="${__("Order items")}"></div>
						<div class="rms-pos-cart-actions" data-role="cart-actions" hidden></div>
						<div class="rms-pos-cart-lines" data-role="cart" aria-live="polite"></div>
						<div class="rms-pos-summary"><div><span>${__("Subtotal")}</span><b data-role="subtotal">—</b></div><div><span>${__("Discount")}</span><b data-role="discount">—</b></div><button type="button" class="rms-pos-discount" data-action="discount" disabled>${__("Apply discount")}</button><div><span>${__("Taxes")}</span><b data-role="taxes">—</b></div><div data-role="rounding-row" hidden><span>${__("Rounding adjustment")}</span><b data-role="rounding-adjustment">—</b></div><div class="rms-pos-total"><span>${__("Total")}</span><strong data-role="total">—</strong></div><button class="rms-pos-checkout" data-action="checkout" disabled>${__("Continue to payment")}</button></div>
					</aside>
				</div>
			</section>
			<section class="rms-pos-workspace-screen" data-screen="open-orders" hidden></section>
			<section class="rms-pos-workspace-screen" data-screen="tables" hidden></section>
			<section class="rms-pos-workspace-screen" data-screen="payment" hidden></section>`);
	}

	setActionsMenuOpen(open, focus = null) {
		const root = this.page.main[0];
		const menu = root?.querySelector("[data-actions-menu]");
		const toggle = root?.querySelector("[data-more-toggle]");
		if (!menu || !toggle) return;
		if (open) this.closeMyAccount();
		menu.hidden = !open;
		toggle.setAttribute("aria-expanded", String(open));
		if (open) {
			menu.style.right = "0px";
			const rect = menu.getBoundingClientRect();
			menu.style.maxHeight = `${Math.max(0, window.innerHeight - rect.top - 12)}px`;
			if (rect.left < 12) menu.style.right = `${rect.left - 12}px`;
			else if (rect.right > window.innerWidth - 12) menu.style.right = `${rect.right - window.innerWidth + 12}px`;
			if (focus) {
				const items = this.actionsMenuItems();
				(focus === "last" ? items.at(-1) : items[0])?.focus();
			}
		} else if (focus) toggle.focus();
	}

	actionsMenuItems() {
		const menu = this.page.main[0]?.querySelector("[data-actions-menu]");
		return [...(menu?.querySelectorAll('[role="menuitem"], [role="menuitemradio"]') || [])].filter(item => !item.hidden && !item.disabled);
	}

	handleActionsMenuKey(event) {
		if (!event.target.closest("[data-more-actions]")) return false;
		const menu = this.page.main[0]?.querySelector("[data-actions-menu]");
		if (!menu) return false;
		if (event.key === "Escape") {
			if (menu.hidden) return false;
			event.preventDefault(); event.stopPropagation(); this.setActionsMenuOpen(false, true); return true;
		}
		if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return false;
		if (menu.hidden && !event.target.closest("[data-more-toggle]")) return false;
		event.preventDefault();
		this.setActionsMenuOpen(true);
		const items = this.actionsMenuItems();
		if (!items.length) return true;
		const current = items.indexOf(event.target);
		const index = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
			: current < 0 ? (event.key === "ArrowUp" ? items.length - 1 : 0)
			: (current + (event.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
		items[index].focus();
		return true;
	}

	renderHeaderActions() {
		const root = this.page.main;
		root.find('[data-action="expenses"], [data-action="returns"]').prop("disabled", !this.state.session);
		root.find('[data-action="sales-history"], [data-action="operation-approvals"]').prop("disabled", !this.state.store);
		root.find("[data-capability]").each((_, element) => { element.hidden = !this.state.permissions[element.dataset.capability]; });
	}

	bind() {
		const root = this.page.main.get(0);
		this.actionsMenuOutsideClick = event => {
			if (!event.target.closest("[data-more-actions]")) this.setActionsMenuOpen(false);
			if (!event.target.closest("[data-more-actions]")) this.closeMyAccount();
			if (!event.target.closest("[data-order-type-picker]")) this.setOrderTypePickerOpen(false);
			if (this.categoryNavOpen && !event.target.closest('[data-role="subcategories"], [data-category-nav-toggle], [data-category], [data-category-back]')) this.setCategoryNavigationOpen(false);
		};
		document.addEventListener("click", this.actionsMenuOutsideClick);
		document.addEventListener("focusin", this.actionsMenuOutsideClick);
		root.addEventListener("change", async (event) => {
			if (!await this.ensureCurrentOrderActive()) return;
			if (event.target.matches("[data-table-area-filter], [data-table-status-filter]")) return this.renderTableMap();
			if (event.target.matches("[data-split-check-toggle]")) return this.handleSplitCheckToggle(event.target);
			if (event.target.matches("[data-guest-name]")) { this.syncPaymentGuestFields(); if ((this.paymentResplitGuestIndex === null || this.paymentResplitGuestIndex === undefined) && !this.paymentGuests?.some((guest) => guest.paid)) this.guestCheckState = null; this.renderPaymentItemAssignments(); return; }
			if (event.target.matches("[data-guest-method]")) return;
			const quantity = event.target.closest("[data-quantity]");
			if (quantity) return this.updateQuantity(quantity);
			const select = event.target.closest("[data-select]");
			if (!select) return;
			const key = select.dataset.select;
			if (key === "store" && this.state.session) {
				select.value = this.state.store || "";
				return;
			}
			if (["brand", "order_type"].includes(key) && (this.state.cart.length || this.state.order_name)) {
				select.value = this.state[key] || "";
				return frappe.msgprint(__("Finish or start a new sale before changing the Brand or Order Type."));
			}
			this.state[key] = select.value || null;
			if (["store", "brand", "order_type"].includes(key)) this.renderSaleSetup();
			if (key === "store") this.onStoreChanged();
			if (key === "brand") this.onBrandChanged();
			if (key === "order_type") this.onOrderTypeChanged();
			if (key === "dining_area") this.onDiningAreaChanged();
			if (key === "dining_table") this.saveDraft();
		});
		root.addEventListener("input", async (event) => {
			if (!await this.ensureCurrentOrderActive()) return;
			if (event.target.matches("[data-guest-share]")) {
				event.target.value = Math.max(0, Math.min(Number(this.paymentTotal || 0), Number(event.target.value || 0))).toFixed(2);
				event.target.dataset.manualShare = "1";
				return this.updateGuestSplitAmounts();
			}
			if (event.target.matches("[data-search]")) {
				this.state.search = event.target.value;
				clearTimeout(this.searchTimer);
				this.searchTimer = setTimeout(() => this.loadCatalog(), 220);
			}
			if (event.target.matches('[data-input="external_reference"]')) this.state.external_reference = event.target.value;
			if (event.target.matches("[data-open-order-search]")) this.renderOpenOrders(event.target.value);
			if (event.target.matches("[data-table-search], [data-table-area-filter], [data-table-status-filter]")) this.renderTableMap();
			if (event.target.matches("[data-payment-amount], [data-guest-amount]")) this.updatePaymentTotal();
			if (event.target.matches("[data-guest-amount]")) event.target.dataset.manual = "1";
			if (event.target.matches("[data-guest-name]")) { const row = event.target.closest(".rms-guest-check"); if (row && this.paymentGuests[Number(row.dataset.guestIndex)]) this.paymentGuests[Number(row.dataset.guestIndex)].name = event.target.value; const heading = row?.querySelector(".rms-guest-check-heading strong"); if (heading) heading.textContent = event.target.value || __("Guest {0}", [Number(row.dataset.guestIndex) + 1]); }
			if (event.target.matches("[data-pay-discount-value], [data-pay-discount-reason]")) {
				this.clearDiscountApprovalPrompt();
				if (event.target.matches('[data-pay-discount-value="percentage"]')) {
					const percentLabel = root.querySelector("[data-discount-percent-label]");
					if (percentLabel) percentLabel.textContent = `${event.target.value}%`;
				}
				this.updateDiscountApplyState();
				this.queuePaymentDiscountPreview(false);
			}
			if (event.target.matches("[data-discount-approval-code]")) this.updateDiscountApplyState();
		});
		root.addEventListener("focusin", (event) => { if (event.target.matches("[data-payment-amount], [data-guest-amount], [data-guest-share]")) { this.paymentInput = event.target; this.paymentKeypadInput = null; } });
		root.addEventListener("keydown", (event) => {
			if (this.handleOrderTypePickerKey(event)) return;
			if (event.key === "Escape" && root.querySelector("[data-pos-setup]")?.hidden === false) {
				event.preventDefault(); event.stopPropagation(); this.closeMyAccount(true); return;
			}
			if (this.handleActionsMenuKey(event)) return;
			if (this.handleCategoryNavigationKey(event)) return;
			if (event.target.matches('[data-action="cart-tab"]') && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
				event.preventDefault();
				const tab = event.key === "Home" ? "pending" : event.key === "End" ? "confirmed" : event.target.dataset.tab === "pending" ? "confirmed" : "pending";
				return this.onAction("cart-tab", { tab });
			}
			if (event.key === "Escape" && root.querySelector("[data-payment-items-backdrop]")) { event.preventDefault(); return this.closePaymentItemsDialog(); }
			if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
				event.preventDefault();
				const search = root.querySelector("[data-search]");
				if (search && !search.disabled) search.focus();
				return;
			}
			if (!event.target.matches("[data-search]")) return;
			if (event.key === "Enter") { event.preventDefault(); this.searchAndAddBarcode(); }
		});
		root.addEventListener("click", (event) => { if (event.target.matches("[data-split-dialog-backdrop]")) this.closePaymentSplitDialog(); });
		root.addEventListener("click", (event) => { if (event.target.matches("[data-payment-items-backdrop]")) this.closePaymentItemsDialog(); });
		root.addEventListener("click", async (event) => {
			const language = event.target.closest("[data-language]");
			if (language) { if (!language.disabled) return this.changeLanguage(language.dataset.language); return; }
			if (event.target.closest("[data-order-type-toggle]")) { this.setOrderTypePickerOpen(!this.orderTypePickerOpen); return; }
			const typeOption = event.target.closest("[data-order-type-option]");
			if (typeOption) {
				const select = root.querySelector('[data-select="order_type"]');
				if (!select || select.disabled || !this.state.order_types.some(row => row.name === typeOption.dataset.orderTypeOption)) return;
				this.setOrderTypePickerOpen(false, true);
				select.value = typeOption.dataset.orderTypeOption;
				select.dispatchEvent(new Event("change", { bubbles: true }));
				return;
			}
			if (event.target.closest("[data-setup-close]")) { this.closeMyAccount(true); return; }
			if (event.target.closest("[data-setup-back]")) { this.closeMyAccount(); this.setActionsMenuOpen(true); root.querySelector('[data-action="my-account"]')?.focus(); return; }
			const moreToggle = event.target.closest("[data-more-toggle]");
			if (moreToggle) {
				const menu = root.querySelector("[data-actions-menu]");
				if (root.querySelector("[data-pos-setup]")?.hidden === false) { this.closeMyAccount(true); return; }
				this.setActionsMenuOpen(menu.hidden, menu.hidden ? "first" : null);
				return;
			}
			const navToggle = event.target.closest("[data-category-nav-toggle]");
			if (navToggle) { this.setCategoryNavigationOpen(!this.categoryNavOpen, true); return; }
			if (event.target.closest("[data-category-nav-close]")) { this.setCategoryNavigationOpen(false, true); return; }
			const modeButton = event.target.closest("[data-catalog-mode]");
			if (modeButton) { this.state.catalog_mode = modeButton.dataset.catalogMode; return this.selectCategory(this.state.category, modeButton); }
			const categoryBack = event.target.closest("[data-category-back]");
			if (categoryBack) return this.selectCategory(categoryBack.dataset.categoryBack, categoryBack);
			const button = event.target.closest("[data-action]");
			if (button) {
				if (button.disabled || button.hidden) return;
				if (button.closest("[data-actions-menu]")) this.setActionsMenuOpen(false, true);
				return this.onAction(button.dataset.action, button.dataset);
			}
			const product = event.target.closest("[data-product]");
			if (product) this.addProduct(product.dataset.product);
			const category = event.target.closest("[data-category]");
			if (category) return this.selectCategory(category.dataset.category, category);
		});
		this.render();
	}

	defaultOrderType() {
		const types = this.state.order_types || [];
		const normalize = value => String(value || "").toLowerCase().replace(/[أإآ]/g, "ا").replace(/[\s_-]/g, "");
		return types.find(row => [row.name, row.title].some(value => ["takeaway", "takeout", "تيكاواي", "تيكاوي"].includes(normalize(value))))?.name || types[0]?.name || null;
	}

	async loadBootstrap(store = null) {
		this.state.bootstrap_loading = true;
		this.state.restoring_order = Boolean(this.pendingResumeContext || this.pendingLaunchContext?.order_name || this.openingOrderRoute);
		try {
			const data = await this.call("get_bootstrap", { store, allow_store_fallback: 1 });
			if (data.store_selection_reset) this.clearUnavailableStoreContext();
			store = data.store?.name || (data.store_selection_reset ? null : store);
			let catalogPromise;
			this.state.stores = data.stores || [];
			this.state.permissions = data.permissions || {};
			if (!store && data.session?.store) {
				this.state.session = data.session;
				this.state.store = data.session.store;
				this.render();
				return await this.loadBootstrap(data.session.store);
			}
			if (!store && data.default_store) {
				this.state.store = data.default_store;
				this.render();
				return await this.loadBootstrap(data.default_store);
			}
			if (store) {
				Object.assign(this.state, { store: data.store?.name, brands: data.brands || [], order_types: data.order_types || [],
					session: data.session, currency: data.currency });
				if (!this.state.brand || !this.state.brands.some((row) => row.name === this.state.brand)) this.state.brand = this.state.brands.find((row) => row.is_default)?.name || this.state.brands[0]?.name || null;
				if (!this.state.order_type || !this.state.order_types.some((row) => row.name === this.state.order_type)) this.state.order_type = this.defaultOrderType();
				if (this.state.session?.payments) this.state.payment_methods = this.state.session.payments.map((row) => row.mode_of_payment);
				if (this.pendingResumeContext && !this.pendingResumeOrder &&
					(this.pendingResumeContext.from_url || this.pendingResumeContext.session === this.state.session?.name)) {
					this.pendingResumeOrder = await this.call("get_order", {order_name:this.pendingResumeContext.order_name});
				}
				if (this.pendingResumeOrder) {
					this.state.brand = this.pendingResumeOrder.restaurant_brand || this.state.brand;
					this.state.order_type = this.pendingResumeOrder.order_type || this.state.order_type;
					this.state.dining_area = this.pendingResumeOrder.dining_area || null;
				}
				if (!this.pendingResumeContext && !this.pendingLaunchContext?.order_name && this.state.brand && this.state.order_type) {
					catalogPromise = this.loadCatalog();
				}
				await this.loadContextDetails();
			} else {
				Object.assign(this.state, { store: null, session: null, brands: [], order_types: [],
					brand: null, order_type: null, categories: [], products: [] });
			}
			const restoring = Boolean(this.pendingResumeContext || this.pendingLaunchContext?.order_name);
			if (restoring) {
				await this.restoreCurrentOrder();
				await this.applyLaunchContext();
				this.state.bootstrap_loading = false;
				this.render();
				// The saved order and payment screen do not depend on the menu.
				if (this.state.store && this.state.brand && this.state.order_type) this.loadCatalog();
			} else {
				this.render();
				if (catalogPromise) await catalogPromise;
				else if (this.state.store && this.state.brand && this.state.order_type) await this.loadCatalog();
				await this.applyLaunchContext();
				this.state.bootstrap_loading = false;
				this.render();
			}
			return true;
		} catch (error) {
			this.state.bootstrap_loading = false;
			this.state.catalog_loading = false;
			this.render();
			this.showError(error);
			return false;
		}
	}

	clearUnavailableStoreContext() {
		this.pendingResumeContext = this.pendingResumeOrder = this.pendingLaunchContext = null;
		Object.assign(this.state, { order_name: null, order_status: null, cart: [], session: null,
			customer: null, dining_area: null, dining_table: null, category: null, products: [], categories: [] });
		try { sessionStorage.removeItem("rms-pos-launch-context"); } catch (_) {}
		this.rememberCurrentScreen("sale");
	}

	async applyLaunchContext() {
		const context = this.pendingLaunchContext;
		if (!context || context.store !== this.state.store || !this.state.session || this.state.session.status !== "Open") return;
		this.pendingLaunchContext = null;
		sessionStorage.removeItem("rms-pos-launch-context");
		if (context.order_name) {
			const order = await this.call("get_order", { order_name: context.order_name });
			await this.loadOrder(order);
			if (context.action === "pay") await this.checkout();
			return;
		}
		this.state.dining_area = context.dining_area || null;
		this.state.dining_table = context.dining_table || null;
		if (context.dining_table) {
			this.state.order_type = this.state.order_types.find(row => row.require_table)?.name || this.state.order_type;
			this.page.main.find('[data-select="order_type"]').val(this.state.order_type);
			this.updateOrderTypeFields();
			await this.loadCatalog();
		}
		this.renderFields();
	}

	async consumeLaunchContext() {
		if (this.state.bootstrap_loading || this.openingOrderRoute) return;
		const route = this.readOrderRoute();
		if (route && (route.order_name !== this.state.order_name || route.screen !== (this.currentOrderScreen || "sale"))) {
			return this.openOrderRoute(route);
		}
		if (!this.pendingLaunchContext) this.pendingLaunchContext = this.readLaunchContext();
		await this.applyLaunchContext();
	}

	async loadContextDetails() {
		if (!this.state.store) return;
		const [context, areas, categories] = await Promise.all([
			this.call("get_pos_context", { store: this.state.store }),
			this.call("get_dining_areas", { store: this.state.store }),
			this.call("get_categories", { brand: this.state.brand, store: this.state.store })
		]);
		this.state.currency = context.currency;
		this.state.manual_discount_scope = context.manual_discount_scope || "Net Total";
		this.state.default_customer = context.customer;
		this.state.payment_config = context.payments || [];
		this.state.areas = areas || [];
		this.state.categories = categories || [];
		this.state.customer = this.state.customer || context.customer || null;
		if (this.state.order_types.find(row => row.name === this.state.order_type)?.require_table) await this.loadTables();
		else this.state.tables = [];
	}

	async onStoreChanged() {
		this.state.session = null; this.state.order_name = null; this.state.cart = []; this.state.brand = null; this.state.order_type = null;
		this.state.category = null; this.state.customer = null; this.state.dining_table = null; this.state.dining_area = null;
		this.rememberCurrentScreen("sale");
		this.state.products = []; this.state.categories = []; this.catalogRequestId++;
		if (this.state.store) await this.loadBootstrap(this.state.store); else this.render();
	}

	async onBrandChanged() {
		this.state.category = null; this.state.cart = []; this.state.order_name = null;
		this.currentOrderScreen = "sale"; this.watchCurrentOrder();
		if (this.state.brand) this.state.categories = await this.call("get_categories", { brand: this.state.brand, store: this.state.store });
		this.renderCategories(); this.loadCatalog(); this.saveDraft();
	}

	async onOrderTypeChanged() {
		this.state.cart = []; this.state.order_name = null;
		this.currentOrderScreen = "sale"; this.watchCurrentOrder();
		const selectedType = this.state.order_types.find((row) => row.name === this.state.order_type);
		if (!selectedType?.require_table) { this.state.dining_area = null; this.state.dining_table = null; }
		this.updateOrderTypeFields(); await this.loadTables(); this.loadCatalog(); this.saveDraft();
	}

	async loadTables() {
		this.state.tables = this.state.store ? await this.call("get_tables", { store: this.state.store, dining_area: this.state.dining_area }) : [];
		this.renderFields();
	}

	async onDiningAreaChanged() { this.state.dining_table = null; await this.loadTables(); this.saveDraft(); }

	catalogScopeKey() {
		return JSON.stringify([this.state.store, this.state.brand, this.state.order_type]);
	}

	async loadMenuSnapshot() {
		const key = this.catalogScopeKey();
		if (this.menuSnapshot?.key !== key) this.menuSnapshot = { key, products: null, refreshAt: 0, promise: null };
		const snapshot = this.menuSnapshot;
		// Every category uses the same complete, scoped menu. A refresh never blanks it.
		this.state.products = snapshot.products || [];
		this.state.catalog_loading = !snapshot.products;
		this.renderProducts();
		if (snapshot.products && Date.now() < snapshot.refreshAt) return snapshot.products;
		if (!snapshot.promise) {
			snapshot.promise = this.call("get_catalog", {
				store: this.state.store, brand: this.state.brand, order_type: this.state.order_type,
				category: null, search: "", include_descendants: 1, full_menu: 1,
			}, { silent: Boolean(snapshot.products) }).then(products => {
				snapshot.products = products || [];
				snapshot.refreshAt = Date.now() + 30000;
				return snapshot.products;
			}).catch(error => {
				snapshot.refreshAt = Date.now() + 5000;
				const denied = ["PermissionError", "AuthenticationError"].includes(error?.exc_type || error?.responseJSON?.exc_type);
				if (denied) snapshot.products = null;
				if ((!snapshot.products || denied) && this.menuSnapshot === snapshot && this.catalogScopeKey() === key && !this.state.search) this.showError(error);
				return snapshot.products || [];
			}).finally(() => { snapshot.promise = null; });
		}
		const products = await snapshot.promise;
		if (this.menuSnapshot === snapshot && this.catalogScopeKey() === key && !this.state.search) {
			this.state.products = products;
			this.state.catalog_loading = false;
			this.renderProducts();
		}
		return products;
	}

	async loadCatalog() {
		if (!this.state.store || !this.state.brand || !this.state.order_type) {
			this.catalogRequestId++;
			this.menuSnapshot = null;
			this.state.products = [];
			this.state.catalog_loading = false;
			this.renderProducts();
			return [];
		}
		const requestId = ++this.catalogRequestId;
		if (!this.state.search) return this.loadMenuSnapshot();
		this.state.catalog_loading = true;
		this.renderProducts();
		try {
			const products = await this.call("get_catalog", { store: this.state.store, brand: this.state.brand,
				order_type: this.state.order_type, category: this.state.category, search: this.state.search, include_descendants: this.state.search ? 1 : 0, limit: 200 });
			if (requestId !== this.catalogRequestId) return this.state.products;
			this.state.products = products || [];
			this.state.catalog_loading = false;
			this.renderProducts();
			return this.state.products;
		} catch (error) {
			if (requestId === this.catalogRequestId) {
				this.state.catalog_loading = false;
				this.renderProducts();
				this.showError(error);
			}
			return [];
		}
	}

	async searchAndAddBarcode() {
		const value = this.state.search.trim();
		if (!value || !this.state.session) return;
		clearTimeout(this.searchTimer);
		const rows = await this.loadCatalog();
		const normalized = value.toLocaleLowerCase();
		const barcodeMatches = rows.filter((row) => row.barcode_match);
		const exact = rows.filter((row) => [row.name, row.title].some((label) => String(label || "").trim().toLocaleLowerCase() === normalized));
		const match = barcodeMatches.length === 1 ? barcodeMatches[0] : barcodeMatches.length > 1 ? null
			: exact.length === 1 ? exact[0] : exact.length === 0 && rows.length === 1 ? rows[0] : null;
		if (match) return this.addProduct(match.name);
		if (rows.length > 1) frappe.show_alert({ message: __("More than one product matches. Select the right item from the results."), indicator: "orange" });
	}

	async addProduct(productName, optionParent = null, configured = null, entry = {}) {
		if (!this.state.session) return frappe.msgprint(__("Open a cashier session first."));
		if (!await this.ensureCurrentOrderActive()) return;
		if (["Paid", "Cancelled"].includes(this.state.order_status)) return frappe.msgprint(__("Start a new sale before adding products."));
		if (this.state.order_types.find((row) => row.name === this.state.order_type)?.require_table && !this.state.dining_table) return frappe.msgprint(__("Choose a dining table before adding items to a Dine In order."));
		try {
			const config = configured || await this.call("get_product_configuration", { product: productName,
				store: this.state.store, brand: this.state.brand, order_type: this.state.order_type });
			if (config.has_options) return this.showProductOptions(config, optionParent || config.name, entry);
			if (config.price == null) return frappe.msgprint(__("Set a Selling Price for this product before adding it to an order."));
			if (config.modifier_groups.length) return this.showModifiers(config, optionParent, entry);
			await this.pushCart(productName, optionParent, [], config, entry);
		} catch (error) { this.showError(error); }
	}

	quantityKeypadHtml() {
		const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "C"];
		return `<div class="rms-pos-dialog-quantity" data-quantity-control><span class="rms-pos-quantity-label">${__("Quantity")}</span><div class="rms-pos-quantity-stepper"><button type="button" data-quantity-adjust="-1" aria-label="${__("Decrease quantity")}">−</button><button type="button" data-quantity-toggle aria-haspopup="dialog" aria-expanded="false" title="${__("Enter quantity")}"><span data-quantity-display>1</span><span class="rms-pos-keypad-icon" aria-hidden="true">▦</span></button><button type="button" data-quantity-adjust="1" aria-label="${__("Increase quantity")}">+</button></div><div class="rms-pos-quantity-popover" data-quantity-popover role="dialog" aria-label="${__("Enter quantity")}" hidden><div class="rms-pos-quantity-popover-head"><span>${__("Quantity")}</span><button type="button" data-quantity-close aria-label="${__("Close")}">×</button></div><output data-quantity-display aria-live="polite">1</output><div class="rms-pos-quantity-keys">${keys.map(key => `<button type="button" data-quantity-key="${key}"${key === "C" ? ` aria-label="${__("Clear quantity")}"` : ""}>${key}</button>`).join("")}</div></div></div>`;
	}

	bindQuantityKeypad(dialog, onChange) {
		dialog.$wrapper.find(".modal-footer").prepend(this.quantityKeypadHtml());
		let input = String(dialog.get_value("quantity") || 1);
		let replaceOnNext = true;
		const update = () => {
			dialog.$wrapper.find("[data-quantity-display]").text(input || "0");
			dialog.$wrapper.find('[data-quantity-adjust="-1"]').prop("disabled", Number(input || 0) <= 0);
			onChange();
		};
		let expanded = false;
		const setExpanded = (open, restoreFocus = false) => {
			expanded = open;
			dialog.$wrapper.find("[data-quantity-popover]").prop("hidden", !open);
			dialog.$wrapper.find("[data-quantity-toggle]").attr("aria-expanded", String(open));
			if (open) {
				replaceOnNext = true;
				dialog.$wrapper.find('[data-quantity-key="1"]').trigger("focus");
			} else if (restoreFocus) dialog.$wrapper.find("[data-quantity-toggle]").trigger("focus");
		};
		dialog.$wrapper.on("click.rmsPosQuantity", "[data-quantity-toggle]", () => setExpanded(!expanded));
		dialog.$wrapper.on("click.rmsPosQuantity", "[data-quantity-close]", () => setExpanded(false, true));
		dialog.$wrapper.on("click.rmsPosQuantity focusin.rmsPosQuantity", ".modal-content", event => {
			if (!event.target.closest("[data-quantity-control]")) setExpanded(false);
		});
		dialog.$wrapper.on("keydown.rmsPosQuantity", "[data-quantity-control]", event => {
			if (event.key === "Escape" && expanded) {
				event.preventDefault(); event.stopPropagation(); setExpanded(false, true);
			}
		});
		// Keep rapid taps ordered while Frappe updates the hidden quantity field.
		let pending = Promise.resolve();
		dialog.$wrapper.on("click.rmsPosQuantity", "[data-quantity-key]", event => {
			const key = event.currentTarget.dataset.quantityKey;
			pending = pending.then(async () => {
				if (key === "C") input = "";
				else if (key === ".") {
					if (replaceOnNext) input = "";
					if (input.includes(".")) return;
					input = `${input || "0"}.`;
				} else {
					const next = replaceOnNext || input === "0" ? key : input + key;
					if (next.length > 12 || (next.split(".")[1] || "").length > 3) return;
					input = next;
				}
				replaceOnNext = false;
				await dialog.set_value("quantity", Number(input || 0));
				update();
			});
			return pending;
		});
		dialog.$wrapper.on("click.rmsPosQuantity", "[data-quantity-adjust]", event => {
			const delta = Number(event.currentTarget.dataset.quantityAdjust);
			pending = pending.then(async () => {
				input = String(Math.max(0, Math.round((Number(input || 0) + delta) * 1000) / 1000));
				replaceOnNext = true;
				await dialog.set_value("quantity", Number(input));
				update();
			});
			return pending;
		});
		dialog.$wrapper.on("hidden.bs.modal.rmsPosQuantity", () => dialog.$wrapper.off(".rmsPosQuantity"));
		update();
	}

	validConfigurationQuantity(config, quantity) {
		const qty = Number(quantity);
		return Number.isFinite(qty) && qty > 0 && (!config?.must_be_whole_number || Number.isInteger(qty));
	}

	modifierSelectionError(config, chosen) {
		for (const group of config.modifier_groups || []) {
			const count = new Set(chosen.filter(row => row.modifier_group === group.name && group.options.some(option => option.name === row.modifier_product)).map(row => row.modifier_product)).size;
			if (count < Number(group.min_selections || 0)) return __("Choose at least {0} option(s) from Modifier Group {1}.", [group.min_selections, this.escape(group.title)]);
			if (Number(group.max_selections || 0) > 0 && count > Number(group.max_selections)) return __("Choose at most {0} option(s) from Modifier Group {1}.", [group.max_selections, this.escape(group.title)]);
		}
		return "";
	}

	syncModifierLimits(dialog, config, chosen) {
		const root = dialog.$wrapper?.[0];
		if (!root) return;
		for (const group of config?.modifier_groups || []) {
			const maximum = Number(group.max_selections || 0);
			const count = new Set(chosen.filter(row => row.modifier_group === group.name).map(row => row.modifier_product)).size;
			for (const input of root.querySelectorAll('input[type="checkbox"][data-group]')) {
				if (input.dataset.group !== group.name) continue;
				input.disabled = maximum > 0 && count >= maximum && !input.checked;
			}
		}
	}

	modifierGroupHtml(group, choices) {
		const minimum = Number(group.min_selections || 0);
		const maximum = Number(group.max_selections || 0);
		const range = maximum ? (minimum === maximum ? `${minimum}` : minimum ? `${minimum}–${maximum}` : __("Up to {0}", [maximum])) : `${minimum}+`;
		const required = minimum || maximum ? `<span class="rms-pos-modifier-required">${minimum ? __("Required") + " · " : ""}<bdi>${this.escape(range)}</bdi></span>` : "";
		const clear = minimum === 0 ? `<button type="button" class="rms-pos-clear-modifiers" data-clear-modifiers="${this.escape(group.name)}">${__("Clear")}</button>` : "";
		const heading = `${this.escape(group.title)}${required}${clear}`;
		if (group.allow_collapse === false || group.allow_collapse === 0) return `<section class="rms-pos-modifier-group"><h4>${heading}</h4><div>${choices}</div></section>`;
		const open = minimum > 0 || (group.collapsed_by_default != null && !group.collapsed_by_default);
		return `<details class="rms-pos-modifier-group"${open ? " open" : ""}><summary>${heading}</summary><div>${choices}</div></details>`;
	}

	showProductOptions(config, rootOptionParent = config.name, entry = {}) {
		const selectable = (row) => row.has_options || row.price != null;
		const configs = [config];
		const selections = [];
		const modifierSelections = new Set();
		const chosenModifiers = () => [...modifierSelections].map(key => {
			const [modifier_group, modifier_product] = JSON.parse(key);
			return { modifier_group, modifier_product, qty: 1 };
		});
		let selectedConfig = null;
		let loadingDepth = null;
		const updatePrimaryAction = () => {
			this.syncModifierLimits(dialog, selectedConfig, chosenModifiers());
			const ready = selectedConfig && !selectedConfig.has_options && selectedConfig.price != null && loadingDepth === null
				&& this.validConfigurationQuantity(selectedConfig, dialog.get_value("quantity")) && !this.modifierSelectionError(selectedConfig, chosenModifiers());
			dialog.$wrapper.find(".modal-footer .btn-primary").prop("disabled", !ready);
			dialog.$wrapper.find('[data-quantity-key="."]').prop("disabled", Boolean(selectedConfig?.must_be_whole_number));
		};
		const renderFlow = () => {
			const levels = configs.map((parentConfig, depth) => {
				const optionRows = (parentConfig.options || []).map((row) => `<label class="rms-pos-option-row ${row.has_options ? "is-parent" : ""} ${selectable(row) ? "" : "is-disabled"}"><input type="radio" name="rms-product-option-${depth}" data-option-depth="${depth}" value="${this.escape(row.name)}" ${selections[depth] === row.name ? "checked" : ""} ${selectable(row) && loadingDepth === null ? "" : "disabled"}><span>${this.escape(row.attribute_value || row.title)}</span>${row.has_options ? "" : `<b>${row.price == null ? __("Price not set") : this.currency(row.price)}</b>`}</label>`).join("");
				return `<section class="rms-pos-option-level"><h4>${this.escape(parentConfig.option_attribute || parentConfig.title)}</h4><div class="rms-pos-choice-list">${optionRows || `<p class="text-muted">${__("No available options")}</p>`}</div></section>`;
			}).join("");
			let modifiers = "";
			if (selectedConfig && !selectedConfig.has_options && selectedConfig.modifier_groups.length) {
				modifiers = selectedConfig.modifier_groups.map((group, depth) => {
					const type = group.allow_multiple_selections ? "checkbox" : "radio";
					const choices = group.options.map((option) => {
						const key = JSON.stringify([group.name, option.name]);
						return `<label class="rms-pos-modifier"><input type="${type}" name="rms-modifier-${depth}-${this.escape(group.name)}" data-modifier="${this.escape(option.name)}" data-group="${this.escape(group.name)}" data-modifier-key="${this.escape(key)}" data-price="${Number(option.selling_price) || 0}" ${modifierSelections.has(key) ? "checked" : ""}><span>${this.escape(option.title)}</span><b>${this.currency(option.selling_price)}</b></label>`;
					}).join("");
					return this.modifierGroupHtml(group, choices);
				}).join("");
			}
			const loading = loadingDepth !== null ? `<p class="rms-pos-option-loading" role="status">${__("Loading the next choice…")}</p>` : "";
			dialog.$wrapper.find("[data-option-flow]").html(`${levels}${loading}<div class="rms-pos-modifier-sections">${modifiers}</div>`);
			updatePrimaryAction();
		};
		const dialog = new frappe.ui.Dialog({ title: config.title, size: "large", fields: [
			{ fieldtype: "HTML", fieldname: "options_html", options: `<div data-option-flow></div>` },
			{ fieldtype: "Float", fieldname: "quantity", label: __("Quantity"), default: entry.qty || 1, hidden: 1, precision: 3, change: () => updatePrimaryAction() },
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Comment for this item"), default: entry.notes || "" },
		], primary_action_label: __("Add to order"), primary_action: async (values) => {
			if (!selectedConfig || selectedConfig.has_options || loadingDepth !== null) return frappe.msgprint(__("Choose each required option first."));
			const qty = Number(values.quantity);
			if (!Number.isFinite(qty) || qty <= 0) return frappe.msgprint(__("Enter a quantity greater than zero."));
			if (selectedConfig.must_be_whole_number && !Number.isInteger(qty)) return frappe.msgprint(__("This option must be ordered in whole quantities."));
			const chosen = chosenModifiers();
			const selectionError = this.modifierSelectionError(selectedConfig, chosen);
			if (selectionError) return frappe.msgprint(selectionError);
			dialog.hide();
			await this.pushCart(selectedConfig.name, rootOptionParent, chosen, selectedConfig, { qty, notes: values.notes || "" });
		} });
		dialog.$wrapper.addClass("rms-pos-option-dialog rms-pos-compact-options");
		dialog.$wrapper.on("change.rmsPosOptions", "[data-option-depth]", async (event) => {
			const depth = Number(event.currentTarget.dataset.optionDepth);
			const optionName = event.currentTarget.value;
			const option = configs[depth]?.options?.find((row) => row.name === optionName);
			if (!option || !selectable(option) || loadingDepth !== null) return;
			selections.splice(depth);
			selections[depth] = optionName;
			configs.splice(depth + 1);
			modifierSelections.clear();
			selectedConfig = null;
			loadingDepth = depth;
			renderFlow();
			try {
				const optionConfig = await this.call("get_product_configuration", { product: option.name, store: this.state.store, brand: this.state.brand, order_type: this.state.order_type });
				if (selections[depth] !== optionName) return;
				if (optionConfig.has_options) configs[depth + 1] = optionConfig;
				else selectedConfig = optionConfig;
			} catch (error) { this.showError(error); }
			finally { loadingDepth = null; renderFlow(); }
		});
		dialog.$wrapper.on("change.rmsPosOptions", "[data-modifier-key]", (event) => {
			const key = event.currentTarget.dataset.modifierKey;
			if (event.currentTarget.checked) {
				if (event.currentTarget.type === "radio") {
					const groupName = event.currentTarget.dataset.group;
					for (const selected of modifierSelections) if (JSON.parse(selected)[0] === groupName) modifierSelections.delete(selected);
				}
				modifierSelections.add(key);
			}
			else modifierSelections.delete(key);
			updatePrimaryAction();
		});
		dialog.$wrapper.on("click.rmsPosOptions", "[data-clear-modifiers]", (event) => {
			event.preventDefault(); event.stopPropagation();
			for (const key of modifierSelections) if (JSON.parse(key)[0] === event.currentTarget.dataset.clearModifiers) modifierSelections.delete(key);
			renderFlow();
		});
		dialog.$wrapper.on("hidden.bs.modal.rmsPosOptions", () => dialog.$wrapper.off(".rmsPosOptions"));
		dialog.show();
		this.bindQuantityKeypad(dialog, updatePrimaryAction);
		renderFlow();
	}

	showModifiers(config, optionParent, entry = {}) {
		const html = config.modifier_groups.map((group) => {
			const type = group.allow_multiple_selections ? "checkbox" : "radio";
			const choices = group.options.map((option) => `<label class="rms-pos-modifier"><input type="${type}" name="rms-modifier-${this.escape(group.name)}" data-modifier="${this.escape(option.name)}" data-group="${this.escape(group.name)}" data-price="${Number(option.selling_price) || 0}"><span>${this.escape(option.title)}</span><b>${this.currency(option.selling_price)}</b></label>`).join("");
			return this.modifierGroupHtml(group, choices);
		}).join("");
		const chosenModifiers = () => [...dialog.$wrapper.find("[data-modifier]:checked")].map(input => ({ modifier_group: input.dataset.group, modifier_product: input.dataset.modifier, qty: 1 }));
		const dialog = new frappe.ui.Dialog({ title: config.title, size: "large", fields: [
			{ fieldtype: "HTML", fieldname: "modifier_html", options: `<div class="rms-pos-modifiers rms-pos-modifier-sections">${html}</div>` },
			{ fieldtype: "Float", fieldname: "quantity", label: __("Quantity"), default: entry.qty || 1, hidden: 1, precision: 3, change: () => update() },
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Comment for this item"), default: entry.notes || "" },
		],
			primary_action_label: __("Add to order"), primary_action: async () => {
				const chosen = chosenModifiers();
				const selectionError = this.modifierSelectionError(config, chosen);
				if (selectionError) return frappe.msgprint(selectionError);
				const qty = Number(dialog.get_value("quantity"));
				if (!Number.isFinite(qty) || qty <= 0) return frappe.msgprint(__("Enter a quantity greater than zero."));
				if (config.must_be_whole_number && !Number.isInteger(qty)) return frappe.msgprint(__("This option must be ordered in whole quantities."));
				const notes = dialog.get_value("notes") || "";
				dialog.hide(); await this.pushCart(config.name, optionParent, chosen, config, { qty, notes });
			} });
		dialog.$wrapper.addClass("rms-pos-option-dialog rms-pos-compact-options");
		dialog.show();
		const update = () => {
			this.syncModifierLimits(dialog, config, chosenModifiers());
			dialog.$wrapper.find(".modal-footer .btn-primary").prop("disabled", !this.validConfigurationQuantity(config, dialog.get_value("quantity")) || Boolean(this.modifierSelectionError(config, chosenModifiers())));
			dialog.$wrapper.find('[data-quantity-key="."]').prop("disabled", Boolean(config.must_be_whole_number));
		};
		this.bindQuantityKeypad(dialog, update);
		dialog.$wrapper.on("change.rmsPosModifiers", "[data-modifier]", update);
		dialog.$wrapper.on("click.rmsPosModifiers", "[data-clear-modifiers]", (event) => {
			event.preventDefault(); event.stopPropagation();
			dialog.$wrapper.find("[data-modifier]").each((_, input) => {
				if (input.dataset.group === event.currentTarget.dataset.clearModifiers) input.checked = false;
			});
			update();
		});
		dialog.$wrapper.on("hidden.bs.modal.rmsPosModifiers", () => dialog.$wrapper.off(".rmsPosModifiers"));
		update();
	}

	cartItemMergeKey(row) {
		const modifiers = (row.modifiers || []).map(modifier => JSON.stringify([
			modifier.modifier_group || "", modifier.modifier_product, Number(modifier.qty) || 1,
		])).sort();
		const modifierPrice = (row.modifier_labels || []).reduce((sum, modifier) => sum + (Number(modifier.price) || 0), 0);
		return JSON.stringify([row.selling_product, row.option_parent || "", row.uom || "",
			Number(row.price) || 0, Number(modifierPrice.toFixed(6)), row.notes || "", modifiers]);
	}

	async pushCart(product, optionParent, modifiers, config, entry = {}) {
		if (!await this.ensureCurrentOrderActive()) return;
		const info = this.state.products.find((row) => row.name === product);
		const basePrice = Number(config.price ?? info?.price) || 0;
		const added = { local_id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, saved_to_order: false, selling_product: product, option_parent: optionParent, title: info?.title || config.title,
			qty: Number(entry.qty) || 1, notes: entry.notes || "", sent_to_kitchen: false, uom: config.uom || info?.uom, must_be_whole_number: Boolean(config.must_be_whole_number ?? info?.must_be_whole_number), price: basePrice, modifiers, modifier_labels: modifiers.map((row) => ({ ...row, title: config.modifier_groups.flatMap((group) => group.options).find((option) => option.name === row.modifier_product)?.title,
			price: Number(config.modifier_groups.flatMap((group) => group.options).find((option) => option.name === row.modifier_product)?.selling_price) || 0 })) };
		const appendOnly = this.state.cross_session_edit || Boolean(this.guestCheckState?.guest_checks?.length);
		const key = this.cartItemMergeKey(added);
		const matching = this.state.cart.filter(row => !row.read_only && !row.sent_to_kitchen && !Number(row.cancelled_qty || 0)
			&& !(appendOnly && (row.saved_to_order || this.savingOrder)) && this.cartItemMergeKey(row) === key);
		if (matching.length) {
			const target = matching[0];
			target.qty = Number((matching.reduce((sum, row) => sum + Number(row.qty), Number(added.qty))).toFixed(6));
			const duplicates = new Set(matching.slice(1));
			this.state.cart = this.state.cart.filter(row => !duplicates.has(row));
		} else this.state.cart.push(added);
		this.cartTab = "pending";
		this.state.order_status = this.state.order_status || "Open"; this.renderCart();
		this.page?.main?.find?.('[data-role="cart"]')?.[0]?.scrollTo?.({ top: 0, behavior: "auto" });
		this.saveDraft();
	}

	orderPayload() {
		return { name: this.state.order_name, expected_modified: this.orderModified || null, store: this.state.store, restaurant_brand: this.state.brand,
			order_type: this.state.order_type, customer: this.state.customer, external_reference: this.state.external_reference,
			order_notes: this.state.order_notes || "",
			dining_area: this.state.dining_area, dining_table: this.state.dining_table,
			discount_type: this.state.discount_type, discount_scope: this.state.discount_scope,
			discount_value: this.state.discount_value, discount_reason: this.state.discount_reason,
			append_only: Boolean(this.state.cross_session_edit),
			edit_pending_items: !this.state.cross_session_edit && !this.guestCheckState?.guest_checks?.length
				&& ["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status),
			items: this.state.cart.filter((row) => {
				if (this.state.cross_session_edit) return !row.saved_to_order;
				if (!["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status)) return true;
				return !row.sent_to_kitchen && (!this.guestCheckState?.guest_checks?.length || !row.saved_to_order);
			}).map((row) => ({ client_key: row.local_id, order_item_name: row.order_item_name, selling_product: row.selling_product, option_parent: row.option_parent,
				qty: row.qty, notes: row.notes || "", modifiers: row.modifiers })) };
	}

	async persistDraft() {
		if (["Paid", "Cancelled"].includes(this.state.order_status) || !this.state.session || !this.state.cart.length || !this.state.store || !this.state.brand || !this.state.order_type) return null;
		const revision = this.saleRevision || 0;
		const save = async () => {
			if (revision !== (this.saleRevision || 0) || ["Paid", "Cancelled"].includes(this.state.order_status)) return null;
			if (!await this.ensureCurrentOrderActive()) return null;
			const orderName = this.state.order_name;
			let result;
			this.savingOrder = true;
			try {
				result = await this.call("save_order", { order_data: JSON.stringify(this.orderPayload()) }, { silent: true });
			} catch (error) {
				// Another screen may have cancelled or paid the order since it was loaded.
				if (orderName && this.state.order_name === orderName) {
					try {
						const order = await this.call("get_order_state", { order_name: orderName });
						if (order.is_closed || ["Paid", "Cancelled"].includes(order.status)) {
							this.recoverClosedOrder(order);
							return null;
						}
					} catch (_) { /* Preserve the original save error. */ }
				}
				throw error;
			} finally { this.savingOrder = false; }
			if (revision !== (this.saleRevision || 0)) return null;
			if (result.conflict) { await this.syncCurrentOrder(null, true); return null; }
			this.state.order_name = result.name; this.state.totals = result;
			this.orderModified = result.modified || this.orderModified;
			this.watchCurrentOrder();
			if (result.status) this.state.order_status = result.status;
			if (result.guest_checks?.length) this.guestCheckState = { order_name: result.name, guest_checks: result.guest_checks };
			for (const appended of result.appended_items || []) {
				const line = this.state.cart.find((row) => row.local_id === appended.client_key);
				if (line) { line.saved_to_order = true; line.order_item_name = appended.name; }
			}
			this.renderCart();
			if (this.orderSyncStarted) this.scheduleOrderSync(true);
			return result;
		};
		const queued = this.saveQueue.catch(() => {}).then(save);
		this.saveQueue = queued;
		return queued;
	}

	resetSale() {
		this.cartTab = null; this.cartPendingCount = 0;
		clearTimeout(this.saveTimer); this.saveTimer = null;
		this.saleRevision = (this.saleRevision || 0) + 1;
		this.state.order_name = null; this.state.order_status = null; this.state.cart = []; this.state.totals = null;
		this.currentOrderScreen = "sale";
		this.orderModified = null; this.syncedOrderItems = new Map(); this.syncedOrderMeta = null;
		this.watchCurrentOrder();
		this.state.cross_session_edit = false;
		this.state.customer = this.state.default_customer || null; this.state.external_reference = null;
		this.state.order_notes = "";
		this.state.discount_type = "Percentage"; this.state.discount_scope = "Net Total";
		this.state.discount_value = 0; this.state.discount_reason = "";
		this.state.dining_table = null; this.activeGuestPayment = null; this.guestCheckState = null;
		const defaultType = this.defaultOrderType();
		if (defaultType && defaultType !== this.state.order_type) {
			this.state.order_type = defaultType; this.state.dining_area = null;
			this.page.main.find('[data-select="order_type"]').val(defaultType);
			this.updateOrderTypeFields();
			this.loadCatalog();
		}
		this.page.main.find("[data-screen]").prop("hidden", true);
		this.page.main.find(".rms-pos-shell").prop("hidden", false);
		this.renderCart(); this.renderFields();
	}

	startOrderSync() {
		if (window.rmsPointOfSale && window.rmsPointOfSale !== this) window.rmsPointOfSale.stopOrderSync?.();
		this.orderSyncStarted = true;
		this.orderSyncHandler = event => {
			if (event.doctype === "POS Order" && event.name === this.state.order_name && event.modified !== this.orderModified) this.scheduleOrderSync();
		};
		frappe.realtime?.on("doc_update", this.orderSyncHandler);
		this.permissionSyncHandler = () => {
			this.menuSnapshot = null;
			this.refreshPosPermissions();
			this.loadCatalog();
		};
		frappe.realtime?.on("rms_pos_permissions_changed", this.permissionSyncHandler);
		const refresh = () => {
			if (document.visibilityState !== "hidden" && document.body.classList.contains("rms-pos-active")) this.refreshPosPermissions();
			if (document.visibilityState !== "hidden" && document.body.classList.contains("rms-pos-active")
				&& this.menuSnapshot?.products && !this.menuSnapshot.promise && Date.now() >= this.menuSnapshot.refreshAt && !this.state.search) this.loadCatalog();
			if (this.state.order_name && document.visibilityState !== "hidden" && document.body.classList.contains("rms-pos-active")) this.syncCurrentOrder();
		};
		this.orderSyncRefresh = refresh;
		this.orderSyncReconnect = () => {
			if (this.state.order_name && frappe.realtime?.socket) frappe.realtime.emit("doc_subscribe", "POS Order", this.state.order_name);
			this.menuSnapshot = null;
			this.loadCatalog();
			refresh();
		};
		frappe.realtime?.on("connect", this.orderSyncReconnect);
		this.orderSyncInterval = window.setInterval(refresh, 3000);
		window.addEventListener("focus", refresh);
		window.addEventListener("online", refresh);
	}

	stopOrderSync() {
		document.removeEventListener?.("click", this.actionsMenuOutsideClick);
		document.removeEventListener?.("focusin", this.actionsMenuOutsideClick);
		window.clearInterval(this.orderSyncInterval); clearTimeout(this.orderSyncTimer);
		frappe.realtime?.off("doc_update", this.orderSyncHandler);
		frappe.realtime?.off("connect", this.orderSyncReconnect);
		frappe.realtime?.off("rms_pos_permissions_changed", this.permissionSyncHandler);
		window.removeEventListener("focus", this.orderSyncRefresh);
		window.removeEventListener("online", this.orderSyncRefresh);
		if (this.realtimeOrderName && frappe.realtime?.socket) frappe.realtime.doc_unsubscribe?.("POS Order", this.realtimeOrderName);
		this.orderSyncStarted = false;
	}

	async refreshPosPermissions() {
		if (this.permissionRefreshPromise) return this.permissionRefreshPromise;
		this.permissionRefreshPromise = this.call("get_pos_permissions", {}, {silent:true}).then(permissions => {
			if (JSON.stringify(permissions) !== JSON.stringify(this.state.permissions)) {
				this.state.permissions = permissions;
				this.menuSnapshot = null;
				this.renderHeaderActions(); this.renderFields(); this.renderCart();
			}
		}).catch(() => {}).finally(() => { this.permissionRefreshPromise = null; });
		return this.permissionRefreshPromise;
	}

	watchCurrentOrder() {
		const name = this.state.order_name;
		this.rememberCurrentScreen();
		if (this.realtimeOrderName === name) return;
		if (this.realtimeOrderName && frappe.realtime?.socket) frappe.realtime.doc_unsubscribe?.("POS Order", this.realtimeOrderName);
		this.realtimeOrderName = name;
		if (name && frappe.realtime?.socket) frappe.realtime.doc_subscribe?.("POS Order", name);
	}

	scheduleOrderSync(force = false) {
		this.orderSyncForced = this.orderSyncForced || force;
		clearTimeout(this.orderSyncTimer);
		this.orderSyncTimer = setTimeout(() => {
			const forced = this.orderSyncForced; this.orderSyncForced = false;
			this.syncCurrentOrder(null, forced);
		}, 150);
	}

	orderMetadata(order) {
		return { brand: order.restaurant_brand, order_type: order.order_type, customer: order.customer || null,
			order_notes: order.order_notes || "",
			dining_area: order.dining_area || null, dining_table: order.dining_table || null, external_reference: order.external_reference || null,
			discount_type: order.discount_type || "Percentage", discount_scope: order.discount_scope || "Net Total",
			discount_value: Number(order.discount_value) || 0, discount_reason: order.discount_reason || "" };
	}

	orderRowSignature(row) {
		return JSON.stringify([Number(row.qty), row.notes || "", row.modifiers || []]);
	}

	rememberOrderSnapshot(order) {
		this.orderModified = order.modified;
		this.syncedOrderItems = new Map(this.mapOrderItems(order).map(row => [row.order_item_name, this.orderRowSignature(row)]));
		this.syncedOrderMeta = this.orderMetadata(order);
		this.watchCurrentOrder();
	}

	applyOrderSnapshot(order) {
		const original = this.state.cart;
		const local = new Map(original.filter(row => row.saved_to_order).map(row => [row.order_item_name, row]));
		const baseline = this.syncedOrderItems || new Map();
		let pending = false, conflict = false;
		const remote = this.mapOrderItems(order);
		const remoteNames = new Set(remote.map(row => row.order_item_name));
		for (const [name, row] of local) {
			if (baseline.has(name) && !remoteNames.has(name) && this.orderRowSignature(row) !== baseline.get(name)) conflict = true;
		}
		const saved = remote.filter(row => {
			const previous = baseline.get(row.order_item_name);
			if (previous && !local.has(row.order_item_name) && this.orderRowSignature(row) === previous && !row.sent_to_kitchen && !this.state.cross_session_edit) {
				pending = true; return false; // Keep a local removal that has not been saved yet.
			}
			return true;
		}).map(row => {
			const own = local.get(row.order_item_name), previous = baseline.get(row.order_item_name);
			if (own && previous && this.orderRowSignature(own) !== previous) {
				if (this.orderRowSignature(row) === previous && !row.sent_to_kitchen && !row.read_only) {
					pending = true;
					return { ...row, qty: own.qty, notes: own.notes, modifiers: own.modifiers, modifier_labels: own.modifier_labels, local_id: own.local_id };
				}
				if (this.orderRowSignature(own) !== this.orderRowSignature(row)) conflict = true;
			}
			return { ...row, local_id: own?.local_id };
		});
		const serverMeta = this.orderMetadata(order);
		for (const [field, value] of Object.entries(serverMeta)) {
			const previous = this.syncedOrderMeta?.[field];
			if (previous !== undefined && this.state[field] !== previous && value === previous) pending = true;
			else {
				if (previous !== undefined && this.state[field] !== previous && this.state[field] !== value) conflict = true;
				this.state[field] = value;
			}
		}
		this.state.order_status = order.status;
		const additions = original.filter(row => !row.saved_to_order && !row.sent_to_kitchen);
		this.state.cart = [...saved, ...additions];
		this.state.totals = order;
		this.rememberOrderSnapshot(order);
		this.renderCart(); this.renderFields();
		if (conflict) frappe.show_alert({ message: __("This order was edited on another screen. The latest saved changes are shown; review the order."), indicator: "orange" });
		if (pending || additions.length) this.saveDraft();
	}

	async syncCurrentOrder(knownState = null, force = false) {
		if (!this.state.order_name) return;
		if (this.savingOrder) { this.scheduleOrderSync(force); return; }
		if (this.orderSyncPromise) return this.orderSyncPromise;
		const name = this.state.order_name, revision = this.saleRevision || 0;
		const current = () => this.state.order_name === name && (this.saleRevision || 0) === revision;
		this.orderSyncPromise = (async () => {
			const state = knownState || await this.call("get_order_state", { order_name: name });
			if (!current()) return;
			if (state.is_closed || ["Paid", "Cancelled"].includes(state.status)) { this.recoverClosedOrder(state); return; }
			if (!force && state.modified && state.modified === this.orderModified) return;
			const order = await this.call("get_order", { order_name: name });
			if (!current() || this.savingOrder) { if (current()) this.scheduleOrderSync(true); return; }
			if (["Paid", "Cancelled"].includes(order.status)) { this.recoverClosedOrder(order); return; }
			let checks = null;
			try { checks = await this.call("get_guest_checks", { order_name: name }); } catch (_) { /* Refresh again on the next update. */ }
			if (!current() || this.savingOrder) { if (current()) this.scheduleOrderSync(true); return; }
			const changed = this.orderModified && order.modified !== this.orderModified;
			this.applyOrderSnapshot(order);
			this.guestCheckState = checks?.guest_checks?.length ? { order_name: name, guest_checks: checks.guest_checks } : null;
			const payment = this.page.main[0]?.querySelector('[data-screen="payment"]');
			if (changed && payment && !payment.hidden) {
				this.activeGuestPayment = null;
				payment.hidden = true; this.page.main.find(".rms-pos-shell").prop("hidden", false);
				frappe.show_alert({ message: __("The order changed on another screen. Review the updated total before paying."), indicator: "orange" });
			}
		})().catch(error => { console.warn("RMS order synchronization will retry", error); }).finally(() => { this.orderSyncPromise = null; });
		return this.orderSyncPromise;
	}

	async ensureCurrentOrderActive() {
		if (this.orderSyncPromise) {
			const name = this.state.order_name, revision = this.saleRevision || 0, modified = this.orderModified;
			await this.orderSyncPromise;
			if (name !== this.state.order_name || revision !== (this.saleRevision || 0) || modified !== this.orderModified) return false;
		}
		const name = this.state.order_name;
		if (!name) return true;
		const revision = this.saleRevision || 0;
		try {
			if (!this.orderStateRequest || this.orderStateRequest.name !== name || this.orderStateRequest.revision !== revision) {
				const request = { name, revision, promise: this.call("get_order_state", { order_name: name }) };
				this.orderStateRequest = request;
			}
			const request = this.orderStateRequest;
			let order;
			try { order = await request.promise; }
			finally { if (this.orderStateRequest === request) this.orderStateRequest = null; }
			if (name !== this.state.order_name || revision !== (this.saleRevision || 0)) return false;
			if (order.is_closed || ["Paid", "Cancelled"].includes(order.status)) {
				this.recoverClosedOrder(order);
				return false;
			}
			if (order.modified && this.orderModified && order.modified !== this.orderModified) {
				await this.syncCurrentOrder(order);
				return false;
			}
			return true;
		} catch (error) { this.showError(error); return false; }
	}

	recoverClosedOrder(order) {
		const additions = this.state.cart.filter(row => !row.saved_to_order && !row.sent_to_kitchen);
		this.resetSale();
		const revision = this.saleRevision;
		frappe.show_alert({ message: order.status === "Cancelled"
			? __("The previous order was cancelled. A new sale is ready.")
			: __("The previous order was paid. A new sale is ready."), indicator: "orange" });
		if (additions.length) {
			frappe.confirm(__("Move your unsaved new items to the new sale?"), () => {
				if (this.saleRevision !== revision) return;
				this.state.cart.push(...additions.map(row => ({ ...row, saved_to_order: false,
					sent_to_kitchen: false, read_only: false, order_item_name: null })));
				this.renderCart(); this.saveDraft();
			});
		}
	}

	async saveDraft() {
		if (["Paid", "Cancelled"].includes(this.state.order_status) || !this.state.session || !this.state.cart.length || !this.state.store || !this.state.brand || !this.state.order_type) return;
		clearTimeout(this.saveTimer);
		this.saveTimer = setTimeout(async () => {
			this.saveTimer = null;
			try { await this.persistDraft(); } catch (error) { this.showError(error); }
		}, 250);
	}

	async flushDraftSave() {
		const hasScheduledSave = Boolean(this.saveTimer);
		clearTimeout(this.saveTimer);
		this.saveTimer = null;
		if (hasScheduledSave) await this.persistDraft();
		else await this.saveQueue;
	}

	async editDiscount() {
		if (!this.state.cart.length) return frappe.msgprint(__("Add products before applying a discount."));
		const dialog = new frappe.ui.Dialog({ title: __("Manual Discount"), fields: [
			{ fieldtype: "Select", fieldname: "discount_type", label: __("Discount Type"), options: "Percentage\nAmount", default: this.state.discount_type, reqd: 1 },
			{ fieldtype: "Select", fieldname: "discount_scope", label: __("Apply On"), options: "Net Total\nGrand Total", default: this.state.discount_scope, reqd: 1 },
			{ fieldtype: "Float", fieldname: "discount_value", label: __("Discount Value"), default: this.state.discount_value || 0, reqd: 1 },
			{ fieldtype: "Small Text", fieldname: "discount_reason", label: __("Reason"), default: this.state.discount_reason, description: __("A reason is saved with the order and invoice."), reqd: true }
		], primary_action_label: __("Apply Discount"), primary_action: async (values) => {
			if (!await this.ensureCurrentOrderActive()) { dialog.hide(); return; }
			this.state.discount_type = values.discount_type; this.state.discount_scope = values.discount_scope;
			this.state.discount_value = Number(values.discount_value) || 0; this.state.discount_reason = values.discount_reason;
			dialog.hide(); this.renderCart();
			try { await this.persistDraft(); } catch (error) { this.showError(error); }
		}, secondary_action_label: __("Clear Discount"), secondary_action: () => {
			this.state.discount_type = "Percentage"; this.state.discount_scope = "Net Total"; this.state.discount_value = 0; this.state.discount_reason = "";
			dialog.hide(); this.renderCart(); this.saveDraft();
		} });
		dialog.show();
	}
	async onAccountAction(action) {
		if (action === "my-account") return this.showMyAccount();
		try {
			await this.flushDraftSave();
			if (action === "logout") return frappe.app.logout();
		} catch (error) { this.showError(error); }
	}

	renderLanguageChoices() {
		const current = frappe.boot?.lang === "ar" ? "ar" : "en";
		for (const button of this.page.main[0]?.querySelectorAll?.("[data-language]") || []) {
			const active = button.dataset.language === current;
			button.setAttribute("aria-checked", String(active));
			button.classList.toggle("is-active", active);
			button.disabled = Boolean(this.languageChangePending);
		}
	}

	async changeLanguage(language) {
		if (!["ar", "en"].includes(language) || language === frappe.boot?.lang || this.languageChangePending) return;
		this.languageChangePending = true;
		this.renderLanguageChoices();
		try {
			await this.flushDraftSave();
			await frappe.db.set_value("User", frappe.session.user, "language", language);
			window.location.reload();
		} catch (error) { this.showError(error); }
		finally { this.languageChangePending = false; this.renderLanguageChoices(); }
	}

	async onAction(action, data) {
		if (["my-account", "logout"].includes(action)) return this.onAccountAction(action);
		if (action === "cart-tab" && ["pending", "confirmed"].includes(data.tab)) {
			this.cartTab = data.tab; this.renderCart();
			this.page.main.find(`[data-action="cart-tab"][data-tab="${data.tab}"]`).trigger?.("focus");
			return;
		}
		if (!["new-sale", "switch-apps"].includes(action) && !await this.ensureCurrentOrderActive()) return;
		if (action === "screen-back") { this.page.main.find("[data-screen]").prop("hidden", true); this.page.main.find(".rms-pos-shell").prop("hidden", false); return; }
		if (action === "refresh-open-orders") return this.showOpenOrders();
		if (action === "refresh-tables") return this.showTableMap();
		if (action === "open-pos-order") {
			try { const order = await this.call("get_order", { order_name: data.order }); await this.loadOrder(order); this.page.main.find("[data-screen]").prop("hidden", true); this.page.main.find(".rms-pos-shell").prop("hidden", false); }
			catch (error) { this.showError(error); }
			return;
		}
		if (action === "view-open-order") {
			try { return await this.showOpenOrderOverview(data.order); } catch (error) { return this.showError(error); }
		}
		if (action === "cancel-pos-order") {
			try {
				if (this.state.order_name === data.order) {
					clearTimeout(this.saveTimer); this.saveTimer = null;
					await this.saveQueue.catch(() => {});
				}
				await this.call("cancel_order", { order_name: data.order });
				if (this.state.order_name === data.order) {
					this.resetSale();
					frappe.show_alert({ message: __("Order cancelled. A new sale is ready."), indicator: "orange" });
					return;
				}
				frappe.show_alert({ message: __("Order cancelled"), indicator: "orange" });
				return this.showOpenOrders();
			}
			catch (error) { return this.showError(error); }
		}
		if (action === "cancel-confirmed-item") return this.cancelConfirmedItem(Number(data.index));
		if (action === "cancel-confirmed-items") return this.cancelConfirmedItems();
		if (action === "transfer-open-order") return this.transferOpenOrder(data.order);
		if (action === "split-open-order") return this.splitOpenOrder(data.order);
		if (action === "table-choice") {
			if (!this.state.session || !this.state.permissions.can_checkout) return frappe.msgprint(__("Open a cashier session before starting an order at a table."));
			this.state.order_type = this.state.order_types.find((row) => row.require_table)?.name || this.state.order_type;
			this.state.dining_area = data.area || null; this.state.dining_table = data.table || null;
			this.page.main.find('[data-screen="tables"]').prop("hidden", true); this.page.main.find(".rms-pos-shell").prop("hidden", false);
			this.renderFields(); return;
		}
		if (action === "table-order") {
			try { const order = await this.call("get_order", { order_name: data.order }); await this.loadOrder(order); this.page.main.find('[data-screen="tables"]').prop("hidden", true); this.page.main.find(".rms-pos-shell").prop("hidden", false); }
			catch (error) { this.showError(error); }
			return;
		}
		if (action === "table-view-order") {
			try { return await this.showOpenOrderOverview(data.order); } catch (error) { return this.showError(error); }
		}
		if (action === "payment-back") { this.rememberCurrentScreen("sale"); this.paymentApprovalOnly = false; if (this.activeGuestPayment) { this.activeGuestPayment = null; return this.showPaymentScreen(); } this.page.main.find('[data-screen="payment"]').prop("hidden", true); this.page.main.find(".rms-pos-shell").prop("hidden", false); return; }
		if (action === "payment-open-items") return this.openPaymentItemsDialog();
		if (action === "payment-close-items") return this.closePaymentItemsDialog();
		if (action === "payment-open-split") return this.openPaymentSplitDialog();
		if (action === "payment-cancel-split") return this.closePaymentSplitDialog();
		if (action === "payment-confirm-split") return this.confirmPaymentSplit();
		if (action === "payment-pay") return this.submitPayment(false);
		if (action === "payment-pay-print") return this.submitPayment(true);
		if (action === "payment-key") return this.handlePaymentKey(data.key);
		if (action === "payment-discount-type") { this.setPaymentDiscountType(data.type); this.queuePaymentDiscountPreview(false); return; }
		if (action === "payment-discount-clear") return this.clearPaymentDiscountValue();
		if (action === "payment-clear-discount") return this.clearAppliedPaymentDiscount();
		if (action === "payment-open-discount") return this.openPaymentDiscountDialog();
		if (action === "payment-discount-close") return this.closePaymentDiscountDialog();
		if (action === "payment-discount-approver") return this.selectDiscountApprover(data.approver || "");
		if (action === "payment-discount-back-to-managers") { this.paymentDiscountApprovalApprover = null; return this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers || []); }
		if (action === "payment-discount-request-code") return this.requestDiscountApprovalCode(true);
		if (action === "payment-discount-auth-method") return this.setDiscountApprovalMethod(data.method);
		if (action === "payment-print-only") return this.printOpenOrderCheck();
		if (action === "payment-guest-add") return this.changePaymentGuestCount(1);
		if (action === "payment-guest-remove") return this.changePaymentGuestCount(-1);
		if (action === "payment-split-mode") return this.setPaymentSplitMode(data.mode);
		if (action === "split-item-adjust") return this.adjustPaymentItemAllocation(data.groupKey, Number(data.guestIndex), Number(data.delta));
		if (action === "guest-check-take-payment") return this.openGuestPayment(Number(data.guestIndex));
		if (action === "guest-check-resplit-current") return this.openCurrentGuestCheckResplit();
		if (action === "payment-apply-discount") return this.applyPaymentDiscount();
		if (action === "payment-quick") {
			return this.applySuggestedPaymentAmount(data.amount);
		}
		if (action === "switch-apps") return window.location.assign("/apps");
		if (action === "kitchen-display") return frappe.set_route("kitchen-display");
		if (action === "new-sale") {
			clearTimeout(this.saveTimer); this.saveTimer = null;
			await this.saveQueue.catch(() => {});
			this.resetSale(); return;
		}
		if (action === "session") return this.state.session ? this.closeSession() : this.openSession();
		if (action === "expenses") return this.openExpenses();
		if (action === "checkout") return this.checkout();
		if (action === "sales-history") return this.showSalesHistory();
		if (action === "customer") return this.chooseCustomer();
		if (action === "open-orders") return this.showOpenOrders();
		if (action === "table-map") return this.showTableMap();
		if (action === "returns") return this.startReturnFlow();
		if (action === "operation-approvals") return this.showOperationApprovals();
		if (action === "discount") return this.editDiscount();
		if (action === "notes") return this.editItemNotes(data.index);
		if (action === "order-notes") return this.editOrderNotes();
		if (action === "quantity") { const line = this.state.cart[Number(data.index)]; if (!line || line.read_only || line.sent_to_kitchen) return; const step = line.must_be_whole_number ? 1 : 0.1; line.qty = Math.max(0, Math.round((line.qty + Number(data.delta) * step) * 1000) / 1000); if (!line.qty) this.state.cart.splice(Number(data.index), 1); this.renderCart(); return this.saveDraft(); }
		if (action === "remove") { const line = this.state.cart[Number(data.index)]; if (!line || line.read_only || line.sent_to_kitchen) return; this.state.cart.splice(Number(data.index), 1); this.renderCart(); return this.saveDraft(); }
		if (action === "scan") return this.page.main.find("[data-search]").trigger("focus");
	}

	updateQuantity(input) {
		const index = Number(input.dataset.quantity);
		const line = this.state.cart[index];
		if (!line || line.read_only || line.sent_to_kitchen) return;
		const value = Number(input.value);
		if (!Number.isFinite(value) || value <= 0) this.state.cart.splice(index, 1);
		else line.qty = line.must_be_whole_number ? Math.max(1, Math.round(value)) : Math.round(value * 1000) / 1000;
		this.renderCart();
		this.saveDraft();
	}

	async openSession() {
		if (!this.state.store) return frappe.msgprint(__("Choose a Store first."));
		try {
			const context = await this.call("get_pos_context", { store: this.state.store });
			const fields = context.payments.map((row, index) => ({ fieldtype: "Currency", fieldname: `amount_${index}`,
				label: __("Opening amount") + ` · ${row.mode_of_payment}`, default: 0 }));
			const dialog = new frappe.ui.Dialog({ title: __("Open Cashier Session"), fields,
				primary_action_label: __("Open Session"), primary_action: async (values) => {
					const amounts = Object.fromEntries(context.payments.map((row, index) => [row.mode_of_payment, values[`amount_${index}`] || 0]));
					try {
						const result = await this.call("open_session", { store: this.state.store, opening_amounts: JSON.stringify(amounts) });
						dialog.hide(); await this.loadBootstrap(this.state.store);
						if (result?.resumed) frappe.show_alert({ message: __("Your existing cashier session was restored."), indicator: "green" });
					}
					catch (error) { this.showError(error); }
				} });
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	loadExpenseCategoryStyles() {
		const styleId = "rms-expense-category-styles";
		const styleHref = `${window.location.origin}/assets/rms/css/expense_category_picker.css?v=expense-picker-4`;
		let link = document.getElementById(styleId);
		if (link?.href === styleHref && link.sheet) return Promise.resolve();
		if (link) {
			link.remove();
			link = null;
		}
		return new Promise((resolve) => {
			const finish = () => resolve();
			if (!link) {
				link = document.createElement("link");
				link.id = styleId;
				link.rel = "stylesheet";
				link.href = styleHref;
				link.onload = finish;
				link.onerror = finish;
				document.head.appendChild(link);
				return;
			}
			link.addEventListener("load", finish, { once: true });
			link.addEventListener("error", finish, { once: true });
		});
	}

	renderStaticPicker(key, label, options, selectedValue) {
		const selected = options.find((row) => row.value === selectedValue) || options[0];
		return `<div class="rms-expense-category-picker rms-pos-static-picker" data-pos-picker="${key}"><label class="rms-pos-picker-label">${this.escape(label)}</label><button type="button" class="form-control" data-pos-picker-trigger="${key}" aria-haspopup="listbox" aria-expanded="false"><span data-pos-picker-value>${this.escape(selected?.label || __("Choose {0}", [label]))}</span><span class="rms-pos-picker-caret" aria-hidden="true">▾</span></button><div class="rms-expense-category-list" data-pos-picker-list="${key}" role="listbox" hidden>${options.map((row) => `<button type="button" class="rms-expense-category-option" role="option" tabindex="-1" data-pos-picker-option="${key}" data-pos-picker-option-value="${this.escape(row.value)}" aria-selected="${row.value === selected?.value}">${this.escape(row.label)}</button>`).join("")}</div></div>`;
	}

	bindStaticPicker(dialog, key, fieldname) {
		const wrapper = dialog.$wrapper;
		const triggerSelector = `[data-pos-picker-trigger="${key}"]`;
		const listSelector = `[data-pos-picker-list="${key}"]`;
		const optionSelector = `[data-pos-picker-option="${key}"]`;
		const close = (focusTrigger = false) => {
			const list = wrapper.find(listSelector)[0];
			if (list) list.hidden = true;
			wrapper.find(triggerSelector).attr("aria-expanded", "false");
			if (focusTrigger) wrapper.find(triggerSelector).trigger("focus");
		};
		wrapper.on("click", triggerSelector, (event) => {
			const trigger = event.currentTarget;
			const list = wrapper.find(listSelector)[0];
			const open = list.hidden;
			list.hidden = !open;
			trigger.setAttribute("aria-expanded", String(open));
			if (open) wrapper.find(`${optionSelector}:not([hidden])`).first().trigger("focus");
		});
		wrapper.on("click", optionSelector, (event) => {
			const option = event.currentTarget;
			const value = option.dataset.posPickerOptionValue;
			dialog.set_value(fieldname, value);
			wrapper.find(optionSelector).attr("aria-selected", "false").removeClass("is-selected");
			$(option).attr("aria-selected", "true").addClass("is-selected");
			wrapper.find(`[data-pos-picker="${key}"] [data-pos-picker-value]`).text(option.textContent);
			close(true);
		});
		wrapper.on("click", (event) => {
			if (!event.target.closest(`[data-pos-picker="${key}"]`)) close();
		});
		wrapper.on("keydown", triggerSelector, (event) => {
			if (["Enter", " ", "ArrowDown"].includes(event.key)) {
				event.preventDefault();
				const list = wrapper.find(listSelector)[0];
				list.hidden = false;
				event.currentTarget.setAttribute("aria-expanded", "true");
				wrapper.find(`${optionSelector}:not([hidden])`).first().trigger("focus");
			} else if (event.key === "Escape") close();
		});
		wrapper.on("keydown", optionSelector, (event) => {
			const options = [...wrapper.find(`${optionSelector}:not([hidden])`)];
			const index = options.indexOf(event.currentTarget);
			if (event.key === "ArrowDown" || event.key === "ArrowUp") {
				event.preventDefault();
				options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length]?.focus();
			} else if (event.key === "Enter" || event.key === " ") {
				event.preventDefault();
				event.currentTarget.click();
			} else if (event.key === "Escape") close(true);
		});
	}

	async openExpenses() {
		if (!this.state.session || this.state.session.status !== "Open") return frappe.msgprint(__("Open a cashier session before recording an expense."));
		try {
			await this.loadExpenseCategoryStyles();
			const context = await this.call("get_expense_context");
			const methods = [...new Set((this.state.session.payments || []).map((row) => row.mode_of_payment).filter(Boolean))];
			const categories = context.categories || [];
			const paymentMethodPicker = this.renderStaticPicker("expense-payment-method", __("Mode of Payment"),
				methods.map((method) => ({ value: method, label: method })), methods[0] || "");
			const categoryPicker = categories.length
				? `<div class="rms-expense-category-picker">
					<input class="form-control" type="search" role="combobox" aria-autocomplete="list" aria-expanded="false" data-expense-category-search placeholder="${this.escape(__("Choose or search expense category"))}" autocomplete="off">
					<div class="rms-expense-category-list" data-expense-category-list role="listbox" hidden>${categories.map((row) => {
						const title = row.title || row.name;
						return `<div class="rms-expense-category-option" role="option" tabindex="-1" data-expense-category="${this.escape(row.name)}" data-expense-search="${this.escape(`${title} ${row.name}`)}" aria-selected="false">${this.escape(title)}</div>`;
					}).join("")}</div>
					<p class="rms-expense-category-empty" data-expense-category-empty hidden>${this.escape(__("No matching expense categories."))}</p>
				</div>`
				: `<p class="rms-expense-category-empty">${this.escape(__("No enabled expense categories are configured for this Store."))}</p>`;
			const fields = [
				{ fieldtype: "HTML", fieldname: "expense_category_picker", label: __("Expense Category"), options: categoryPicker },
				{ fieldtype: "Data", fieldname: "expense_category", hidden: 1, reqd: 1 },
				{ fieldtype: "Currency", fieldname: "amount", label: __("Amount"), options: context.currency, reqd: 1 },
				{ fieldtype: "HTML", fieldname: "payment_method_picker", options: paymentMethodPicker },
				{ fieldtype: "Data", fieldname: "mode_of_payment", default: methods[0] || "", hidden: 1, reqd: 1 },
				{ fieldtype: "Small Text", fieldname: "remarks", label: __("Notes") },
				{ fieldtype: "Attach", fieldname: "attachment", label: __("Receipt Attachment") }
			];
			const dialog = new frappe.ui.Dialog({ title: __("Shift Expenses"), fields,
				primary_action_label: __("Record Expense"), primary_action: async (values) => {
					try {
						if (!values.expense_category) return frappe.msgprint(__("Choose an Expense Category."));
						if (!values.mode_of_payment) return frappe.msgprint(__("Choose a payment method."));
						const result = await this.call("create_shift_expense", {
							expense_category: values.expense_category, amount: values.amount,
							mode_of_payment: values.mode_of_payment, remarks: values.remarks, attachment: values.attachment
						});
						dialog.hide();
						if (result.requires_approval) frappe.msgprint(__("Expense is waiting for manager approval. Reopen Expenses, choose Authorize Pending Expense and send a code to the selected manager.") + ` · ${this.escape(result.name)}`);
						else frappe.show_alert({ message: __("Expense posted") + ` · ${result.name}`, indicator: "green" });
						await this.loadBootstrap(this.state.store);
					} catch (error) { this.showError(error); }
				}
			});
			dialog.$wrapper.addClass("rms-shift-expense-dialog");
			this.bindStaticPicker(dialog, "expense-payment-method", "mode_of_payment");
			dialog.$wrapper.on("input", "[data-expense-category-search]", (event) => {
				const input = event.currentTarget;
				const query = input.value.trim().toLocaleLowerCase();
				dialog.set_value("expense_category", "");
				input.setAttribute("aria-expanded", "true");
				const options = dialog.$wrapper.find("[data-expense-category]");
				let visible = 0;
				options.each((_, option) => {
					option.hidden = !option.dataset.expenseSearch.toLocaleLowerCase().includes(query);
					if (!option.hidden) visible++;
				});
				dialog.$wrapper.find("[data-expense-category-list]").prop("hidden", false);
				dialog.$wrapper.find("[data-expense-category-empty]").prop("hidden", visible > 0);
			});
			dialog.$wrapper.find("[data-expense-category-search]").on("focus", (event) => {
				const input = event.currentTarget;
				if (dialog.get_value("expense_category")) {
					input.value = "";
					dialog.set_value("expense_category", "");
					dialog.$wrapper.find("[data-expense-category]").attr("aria-selected", "false").removeClass("is-selected");
				}
				input.setAttribute("aria-expanded", "true");
				dialog.$wrapper.find("[data-expense-category]").prop("hidden", false);
				dialog.$wrapper.find("[data-expense-category-list]").prop("hidden", false);
				dialog.$wrapper.find("[data-expense-category-empty]").prop("hidden", true);
			});
			dialog.$wrapper.find("[data-expense-category-search]").on("blur", (event) => {
				const input = event.currentTarget;
				window.setTimeout(() => {
					const list = dialog.$wrapper.find("[data-expense-category-list]")[0];
					if (list && !list.contains(document.activeElement)) {
						list.hidden = true;
						input.setAttribute("aria-expanded", "false");
					}
				}, 0);
			});
			dialog.$wrapper.on("mousedown", "[data-expense-category]", (event) => event.preventDefault());
			dialog.$wrapper.on("click", "[data-expense-category]", (event) => {
				const option = event.currentTarget;
				const input = dialog.$wrapper.find("[data-expense-category-search]")[0];
				dialog.set_value("expense_category", option.dataset.expenseCategory);
				dialog.$wrapper.find("[data-expense-category]").attr("aria-selected", "false").removeClass("is-selected");
				$(option).attr("aria-selected", "true").addClass("is-selected");
				input.value = option.textContent;
				input.setAttribute("aria-expanded", "false");
				dialog.$wrapper.find("[data-expense-category-list]").prop("hidden", true);
				dialog.$wrapper.find("[data-expense-category-empty]").prop("hidden", true);
			});
			dialog.$wrapper.find("[data-expense-category-search]").on("keydown", (event) => {
				const options = [...dialog.$wrapper.find("[data-expense-category]:not([hidden])")];
				if (event.key === "Escape") {
					dialog.$wrapper.find("[data-expense-category-list]").prop("hidden", true);
					event.currentTarget.setAttribute("aria-expanded", "false");
				} else if (event.key === "ArrowDown" && options.length) {
					event.preventDefault();
					options[0].focus();
				} else if (event.key === "Enter" && options.length === 1) {
					event.preventDefault();
					options[0].click();
				}
			});
			dialog.$wrapper.on("keydown", "[data-expense-category]", (event) => {
				const options = [...dialog.$wrapper.find("[data-expense-category]:not([hidden])")];
				const index = options.indexOf(event.currentTarget);
				if (event.key === "ArrowDown" || event.key === "ArrowUp") {
					event.preventDefault();
					options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length]?.focus();
				} else if (event.key === "Enter") {
					event.preventDefault();
					event.currentTarget.click();
				} else if (event.key === "Escape") {
					const input = dialog.$wrapper.find("[data-expense-category-search]")[0];
					dialog.$wrapper.find("[data-expense-category-list]").prop("hidden", true);
					input.setAttribute("aria-expanded", "false");
					input.focus();
				}
			});
			dialog.$wrapper.on("shown.bs.modal", () => document.body.classList.add("rms-expense-dialog-open"));
			dialog.$wrapper.on("hidden.bs.modal", () => document.body.classList.remove("rms-expense-dialog-open"));
			if (context.pending_expenses?.length) {
				dialog.set_secondary_action_label(__("Authorize Pending Expense"));
				dialog.set_secondary_action(() => { dialog.hide(); this.authorizePendingExpense(context.pending_expenses, context.approvers || []); });
			}
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	async authorizePendingExpense(pendingExpenses, approvers = []) {
		const options = pendingExpenses.map((row) => row.name);
		const dialog = new frappe.ui.Dialog({ title: __("Authorize Pending Expense"),
			fields: [
				{ fieldtype: "Link", fieldname: "expense_name", label: __("Pending Expense"), options: "Shift Expense", reqd: 1,
					get_query: () => ({ filters: { name: ["in", options], status: "Pending Approval" } }) },
				{ fieldtype:"Select", fieldname:"approver", label:__("Manager"), options:[{value:"",label:__("Choose a manager")},...approvers.map(row=>({value:row.user,label:row.full_name}))] },
				{ fieldtype:"HTML", fieldname:"request_code", options:`<button type="button" class="btn btn-default" data-expense-request-code hidden>${__("Retry sending code")}</button><p data-expense-code-status role="status"></p>` },
				{ fieldtype: "Data", fieldname: "approval_code", label: __("Manager Approval Code"), description: __("The selected manager receives the code in their notification bell."), reqd: 1 }
			],
			primary_action_label: __("Authorize Expense"), primary_action: async (values) => {
				try {
					const result = await this.call("redeem_shift_expense_approval_code", { expense_name: values.expense_name, code: values.approval_code });
					dialog.hide();
					frappe.show_alert({ message: __("Expense approved and posted") + ` · ${result.name}`, indicator: "green" });
					await this.loadBootstrap(this.state.store);
				} catch (error) { this.showError(error); }
			}
		});
		const sendCode = (resend = false) => {
			const expense=dialog.get_value("expense_name"), approver=dialog.get_value("approver");
			if (!expense || !approver) return;
			return this.deliverApprovalCode("request_shift_expense_approval_code",{expense_name:expense,approver},
				dialog.$wrapper.find("[data-expense-code-status]")[0],dialog.$wrapper.find("[data-expense-request-code]")[0],resend===true);
		};
		for (const name of ["expense_name","approver"]) {
			if (dialog.fields_dict?.[name]) dialog.fields_dict[name].df.onchange=()=>sendCode();
		}
		dialog.$wrapper.on("change", '[data-fieldname="expense_name"] input, [data-fieldname="approver"] select',()=>sendCode());
		dialog.$wrapper.on("click","[data-expense-request-code]",()=>sendCode(true));
		dialog.show();
	}

	async closeSession() {
		try {
			const hasOpenOrders = await this.call("has_open_orders", { session_name: this.state.session.name });
			if (hasOpenOrders) return frappe.msgprint(__("Finish or cancel all open orders before closing the session."));
			if (this.state.session.status === "Closing" && this.state.session.pos_closing_entry) {
				const payments = this.state.session.payments || [];
				if (payments.some((row) => row.actual_amount == null)) {
					return frappe.msgprint(__("Enter an actual amount for every payment method to resume session closing."));
				}
				const storedAmounts = Object.fromEntries(payments.map((row) => [row.mode_of_payment, row.actual_amount]));
				const result = await this.call("close_session", { session_name: this.state.session.name, actual_amounts: JSON.stringify(storedAmounts) });
				if (result.status === "Closing") frappe.msgprint(result.message || __("Invoice consolidation is still processing."));
				else frappe.show_alert({ message: __("Cashier session closed"), indicator: "green" });
				await this.loadBootstrap(this.state.store);
				return;
			}
			const fields = (this.state.session.payments || []).map((row, index) => ({ fieldtype: "Currency", fieldname: `actual_${index}`,
				label: __("Actual amount") + ` · ${row.mode_of_payment}`, default: row.actual_amount ?? undefined, reqd: 1 }));
			const dialog = new frappe.ui.Dialog({ title: __("Close Cashier Session"), fields,
				primary_action_label: __("Close Session"), primary_action: async (values) => {
					const amounts = Object.fromEntries((this.state.session.payments || []).map((row, index) => [row.mode_of_payment, values[`actual_${index}`] || 0]));
					try { const result = await this.call("close_session", { session_name: this.state.session.name, actual_amounts: JSON.stringify(amounts) }); dialog.hide();
						if (result.status === "Closing") frappe.msgprint(result.message || __("The session close is waiting for ERPNext invoice consolidation."));
						else frappe.show_alert({ message: __("Cashier session closed"), indicator: "green" });
						await this.loadBootstrap(this.state.store); }
					catch (error) { this.showError(error); }
				} });
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	async checkout() {
		if (!await this.ensureCurrentOrderActive()) return;
		if (!this.state.cart.length) return;
		if (this.state.cross_session_edit && ["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status)
			&& !this.state.cart.some((row) => !row.sent_to_kitchen)) {
			if (!this.state.permissions.can_approve_discount) return frappe.msgprint(__("Only the cashier who opened this order can take its payment."));
			this.paymentApprovalOnly = true;
			return this.showPaymentScreen();
		}
		this.paymentApprovalOnly = false;
		if (this.state.order_types.find((row) => row.name === this.state.order_type)?.require_table && !this.state.dining_table) return frappe.msgprint(__("Select a table for this Order Type."));
		if (this.state.order_types.find((row) => row.name === this.state.order_type)?.require_external_reference && !this.state.external_reference) return frappe.msgprint(__("Enter the required external reference."));
		clearTimeout(this.saveTimer);
		try {
			const revision = this.saleRevision || 0;
			const confirmed = ["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status);
			const hasUnconfirmedItems = this.state.cart.some((row) => !row.sent_to_kitchen);
			const saved = confirmed && !hasUnconfirmedItems ? null : await this.persistDraft();
			if (revision !== (this.saleRevision || 0)) return;
			if (!saved && (!confirmed || hasUnconfirmedItems)) return;
			if (!confirmed || hasUnconfirmedItems) {
				const result = await this.call("confirm_order", { order_name: this.state.order_name });
				this.state.order_status = result.status || "Confirmed";
				const refreshed = await this.call("get_order", { order_name: this.state.order_name });
				await this.loadOrder(refreshed);
				return;
			}
			if (!["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status)) return frappe.msgprint(__("Confirm the order before taking payment."));
			return this.showPaymentScreen();
		} catch (error) { this.showError(error); }
	}

	customerSearchDefaults(search = "") {
		const value = search.trim();
		const digits = value.replace(/[٠-٩۰-۹]/g, char => String(char.charCodeAt(0) - (char <= "٩" ? 1632 : 1776)));
		return /^[+()\d\s.-]+$/.test(digits) && /\d/.test(digits)
			? { mobile_no: digits, customer_name: "" } : { customer_name: value, mobile_no: "" };
	}

	async chooseCustomer() {
		let requestId = 0, searchTimer;
		const dialog = new frappe.ui.Dialog({ title: __("Choose Customer"), size: "small", fields: [
			{ fieldtype: "HTML", fieldname: "customer_picker", options: `
				<div class="rms-customer-picker">
					<div class="rms-customer-search-row"><input type="text" class="form-control" data-customer-search autocomplete="off" aria-label="${__("Customer")}"><button type="button" class="rms-customer-icon" data-clear-customer aria-label="${__("Clear")}">×</button></div>
					<div class="rms-customer-results" role="listbox" aria-label="${__("Customers")}"></div>
					<button type="button" class="rms-customer-add" data-new-customer data-new-customer-main><span class="rms-customer-plus">+</span>${__("New Customer")}</button>
					<button type="button" class="rms-customer-add" data-edit-customer hidden>${__("Edit Customer")}</button>
				</div>` },
		], primary_action_label: __("Apply"), primary_action: async () => {
			if (!await this.ensureCurrentOrderActive()) { dialog.hide(); return; }
			this.state.customer = dialog.selectedCustomer || null;
			dialog.hide(); this.renderCart(); this.saveDraft();
		}, secondary_action_label: __("Walk-in"), secondary_action: async () => {
			if (!await this.ensureCurrentOrderActive()) { dialog.hide(); return; }
			this.state.customer = null; dialog.hide(); this.renderCart(); this.saveDraft();
		} });
		dialog.$wrapper.addClass("rms-pos-customer-dialog rms-pos-customer-chooser");
		const root = dialog.fields_dict.customer_picker.$wrapper;
		const input = root.find("[data-customer-search]"), results = root.find(".rms-customer-results");
		dialog.selectedCustomer = this.state.customer;
		root.find("[data-edit-customer]").prop("hidden", !dialog.selectedCustomer);
		dialog.selectCustomer = customer => {
			dialog.selectedCustomer = customer.name;
			root.find("[data-edit-customer]").prop("hidden", false);
			root.find("[data-new-customer-main]").show();
			input.val(customer.customer_name || customer.name);
			++requestId;
			clearTimeout(searchTimer);
			results.html(`<div class="rms-customer-selected"><strong>${this.escape(customer.customer_name || customer.name)}</strong><span>${this.escape(customer.mobile_no || customer.name)}</span></div>`);
			dialog.enable_primary_action();
		};
		const search = async () => {
			const current = ++requestId, value = input.val().trim();
			results.html(`<div class="rms-customer-empty">${__("Loading...")}</div>`);
			try {
				const customers = await this.call("get_customers", { search: value, limit: 30 });
				if (current !== requestId || !dialog.is_visible) return;
				root.find("[data-new-customer-main]").toggle(Boolean(customers.length) || !value);
				results.html(customers.length ? customers.map((customer, index) => `<button type="button" role="option" aria-selected="${customer.name === dialog.selectedCustomer}" class="rms-customer-result" data-customer-index="${index}"><strong>${this.escape(customer.customer_name)}</strong><span>${this.escape(customer.mobile_no || customer.name)}</span></button>`).join("")
					: `<div class="rms-customer-empty">${__("No customers found")}</div><button type="button" class="rms-customer-add is-inline" data-new-customer><span class="rms-customer-plus">+</span>${__("New Customer")} <strong>${this.escape(value)}</strong></button>`);
				results.find("[data-customer-index]").on("click", event => dialog.selectCustomer(customers[Number(event.currentTarget.dataset.customerIndex)]));
			} catch (error) { if (current === requestId) { results.empty(); this.showError(error); } }
		};
		input.on("input", () => {
			dialog.selectedCustomer = null; dialog.disable_primary_action();
			root.find("[data-edit-customer]").prop("hidden", true);
			++requestId; clearTimeout(searchTimer); searchTimer = setTimeout(search, 180);
		});
		input.on("keydown", event => {
			if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); results.find("[data-customer-index], [data-new-customer]").first().trigger("click"); }
		});
		root.on("click", "[data-new-customer]", () => this.createCustomer(dialog, input.val()));
		root.find("[data-edit-customer]").on("click", () => this.editCustomer(dialog, dialog.selectedCustomer));
		root.find("[data-clear-customer]").on("click", () => { input.val("").trigger("input").trigger("focus"); });
		dialog.onhide = () => { ++requestId; clearTimeout(searchTimer); };
		dialog.show();
		input.val(this.state.customer || "");
		await search();
		input.trigger("focus");
	}

	async editCustomer(chooser, customer) {
		if (!customer || !this.state.store) return;
		try {
			const details = await this.call("get_customer_details", { customer, store: this.state.store });
			return this.createCustomer(chooser, "", details);
		} catch (error) { this.showError(error); }
	}

	createCustomer(chooser, search = "", details = null) {
		if (!this.state.store) return frappe.msgprint(__("Select a Store first."));
		const defaults = details || this.customerSearchDefaults(search);
		const phones = (details?.phone_rows || (details?.phones || [defaults.mobile_no || ""]).map(phone => ({ phone, is_default: phone === defaults.mobile_no }))).map(row => ({ ...row }));
		const addresses = (details?.addresses || []).map(row => ({ ...row }));
		if (!phones.length) phones.push({ phone: "", is_default: true });
		if (!phones.some(row => row.is_default)) phones[0].is_default = true;
		if (addresses.length && !addresses.some(row => row.is_default)) addresses[0].is_default = true;
		const dialog = new frappe.ui.Dialog({ title: details ? __("Edit Customer") : __("New Customer"), size: "small", fields: [
			{ fieldtype: "Data", fieldname: "customer_name", label: __("Customer Name"), reqd: 1, default: defaults.customer_name },
			{ fieldtype: "HTML", fieldname: "customer_extras", options: `
				<label class="control-label">${__("Phone Numbers")} <span class="text-danger">*</span></label>
				<div class="rms-customer-phones"></div>
				<div class="rms-customer-tools"><button type="button" class="rms-customer-add" data-add-phone><span class="rms-customer-plus">+</span>${__("Phone Number")}</button><button type="button" class="rms-customer-add" data-add-address><span class="rms-customer-plus">+</span>${__("Address")}</button></div>
				<div class="rms-customer-addresses"></div>` },
		], primary_action_label: __("Save"), primary_action: async values => {
			dialog.disable_primary_action();
			try {
				const customer = await this.call("save_customer_details", {
					...(details ? { customer: details.name } : {}), customer_name: values.customer_name,
					phones, addresses, store: this.state.store });
				chooser.selectCustomer(customer); dialog.hide();
			} catch (error) { this.showError(error); }
			finally { dialog.enable_primary_action(); }
		} });
		dialog.$wrapper.addClass("rms-pos-customer-dialog");
		const extras = dialog.fields_dict.customer_extras.$wrapper;
		const renderPhones = () => {
			extras.find(".rms-customer-phones").html(phones.map((row, index) => `<div class="rms-customer-phone-row">
				<input type="tel" inputmode="tel" class="form-control" value="${this.escape(row.phone || "")}" data-phone-index="${index}" aria-label="${__("Phone Number")} ${index + 1}">
				<label class="rms-customer-default"><input type="radio" name="rms-customer-default-phone" data-default-phone="${index}" ${row.is_default ? "checked" : ""}>${__("Default")}</label>
				${!row.name && phones.length > 1 ? `<button type="button" class="rms-customer-icon" data-remove-phone="${index}" aria-label="${__("Remove")}">×</button>` : ""}</div>`).join(""));
			extras.find("[data-phone-index]").on("input", event => { phones[Number(event.currentTarget.dataset.phoneIndex)].phone = event.currentTarget.value; });
			extras.find("[data-default-phone]").on("change", event => { phones.forEach((row, index) => { row.is_default = index === Number(event.currentTarget.dataset.defaultPhone); }); renderPhones(); });
			extras.find("[data-remove-phone]").on("click", event => {
				phones.splice(Number(event.currentTarget.dataset.removePhone), 1);
				if (!phones.some(row => row.is_default)) phones[0].is_default = true;
				renderPhones();
			});
		};
		const renderAddresses = () => {
			extras.find(".rms-customer-addresses").html(addresses.map((address, index) => `<div class="rms-customer-address-card">
				<div><strong>${this.escape(address.address_line1)}</strong><span>${this.escape([address.address_line2, address.city, address.state, address.country].filter(Boolean).join(" · "))}</span>
				<label class="rms-customer-default"><input type="radio" name="rms-customer-default-address" data-default-address="${index}" ${address.is_default ? "checked" : ""}>${__("Default")}</label></div>
				<div class="rms-customer-address-actions"><button type="button" class="rms-customer-add" data-edit-address="${index}">${__("Edit")}</button>${address.name ? "" : `<button type="button" class="rms-customer-icon" data-remove-address="${index}" aria-label="${__("Remove")}">×</button>`}</div></div>`).join(""));
			extras.find("[data-edit-address]").on("click", event => editAddress(Number(event.currentTarget.dataset.editAddress)));
			extras.find("[data-default-address]").on("change", event => { addresses.forEach((row, index) => { row.is_default = index === Number(event.currentTarget.dataset.defaultAddress); }); renderAddresses(); });
			extras.find("[data-remove-address]").on("click", event => {
				addresses.splice(Number(event.currentTarget.dataset.removeAddress), 1);
				if (addresses.length && !addresses.some(row => row.is_default)) addresses[0].is_default = true;
				renderAddresses();
			});
		};
		const editAddress = (index = null) => {
			const address = index === null ? {} : addresses[index];
			const addressDialog = new frappe.ui.Dialog({ title: index === null ? __("New Address") : __("Edit Address"), size: "small", fields: [
				{ fieldtype: "Data", fieldname: "address_line1", label: __("Street Address"), reqd: 1, default: address.address_line1 },
				{ fieldtype: "Data", fieldname: "address_line2", label: __("Building / Floor / Apartment"), default: address.address_line2 },
				{ fieldtype: "Data", fieldname: "city", label: __("City"), reqd: 1, default: address.city },
				{ fieldtype: "Data", fieldname: "state", label: __("Area"), default: address.state },
			], primary_action_label: index === null ? __("Add") : __("Apply"), primary_action: values => {
				const updated = { ...address, ...Object.fromEntries(["address_line1", "address_line2", "city", "state"].map(field => [field, values[field] || ""])) };
				if (index === null) addresses.push({ ...updated, is_default: !addresses.length });
				else addresses[index] = updated;
				renderAddresses(); addressDialog.hide();
			} });
			addressDialog.show();
		};
		renderPhones(); renderAddresses();
		extras.find("[data-add-phone]").on("click", () => {
			if (phones.length >= (details ? 50 : 10)) return;
			phones.push({ phone: "", is_default: false }); renderPhones();
			extras.find(`[data-phone-index="${phones.length - 1}"]`).trigger("focus");
		});
		extras.find("[data-add-address]").on("click", () => editAddress());
		chooser.hide();
		dialog.onhide = () => chooser.show();
		dialog.show();
		return dialog;
	}

	editOrderNotes() {
		if (["Paid", "Cancelled"].includes(this.state.order_status)) return;
		const revision = this.saleRevision || 0;
		const dialog = new frappe.ui.Dialog({ title: __("Order comment"), fields: [
			{fieldname: "notes", fieldtype: "Small Text", label: __("Comment"), default: this.state.order_notes || "", description: __("Saved with the whole order.")},
		], primary_action_label: __("Save comment"), primary_action: async () => {
			if (dialog.saving || revision !== (this.saleRevision || 0) || !await this.ensureCurrentOrderActive()) return;
			if (dialog.saving || revision !== (this.saleRevision || 0)) return;
			const notes = (dialog.get_value("notes") || "").trim();
			if (notes.length > 2000) return frappe.msgprint(__("Enter an order comment of up to 2000 characters."));
			dialog.saving = true; dialog.disable_primary_action();
			try {
				await this.flushDraftSave();
				if (revision !== (this.saleRevision || 0)) { dialog.hide(); return; }
				if (this.state.order_name) {
					const result = await this.call("update_order_notes", {order_name: this.state.order_name, notes, expected_modified: this.orderModified});
					if (this.orderSyncPromise) await this.orderSyncPromise;
					if (revision !== (this.saleRevision || 0) || result.name !== this.state.order_name) { dialog.hide(); return; }
					this.orderModified = result.modified;
					if (this.syncedOrderMeta) this.syncedOrderMeta.order_notes = result.order_notes;
					this.state.order_notes = result.order_notes;
				} else this.state.order_notes = notes;
				this.renderCart(); dialog.hide();
				if (!this.state.order_name) this.saveDraft();
			} catch (error) { this.showError(error); }
			finally { dialog.saving = false; dialog.enable_primary_action(); }
		} });
		dialog.show();
	}

	editItemNotes(index) {
		const row = this.state.cart[Number(index)];
		if (!row || row.read_only || row.sent_to_kitchen || ["Paid", "Cancelled"].includes(this.state.order_status)) return;
		const dialog = new frappe.ui.Dialog({ title: __("Comment for {0}", [row.title]), fields: [
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Comment"), default: row.notes || "", description: __("This comment is saved with the item and shown to preparation staff.") },
		], primary_action_label: __("Save comment"), primary_action: async (values) => {
			if (!await this.ensureCurrentOrderActive()) { dialog.hide(); return; }
			const notes = dialog.get_value("notes") || "";
			row.notes = notes;
			try {
				await this.flushDraftSave();
				if (!this.state.cart.includes(row)) { dialog.hide(); return; }
				if (!row.saved_to_order || !row.order_item_name) await this.persistDraft();
				if (!this.state.cart.includes(row)) { dialog.hide(); return; }
				if (!row.order_item_name) {
					const order = await this.call("get_order", { order_name: this.state.order_name });
					const knownItems = new Set(this.state.cart.filter((item) => item !== row).map((item) => item.order_item_name).filter(Boolean));
					const matchingItem = [...(order.items || [])].reverse().find((item) => item.selling_product === row.selling_product && !knownItems.has(item.name));
					if (matchingItem) { row.saved_to_order = true; row.order_item_name = matchingItem.name; }
				}
				if (!row.saved_to_order || !row.order_item_name) throw new Error(__("The item comment could not be saved. Please try again."));
				const result = await this.call("update_order_item_notes", { order_name: this.state.order_name, item_name: row.order_item_name, notes });
				if (!this.state.cart.includes(row)) { dialog.hide(); return; }
				this.orderModified = result.modified || this.orderModified;
				this.syncedOrderItems?.set(row.order_item_name, this.orderRowSignature(row));
			} catch (error) { return this.showError(error); }
			dialog.hide(); this.renderCart();
		} });
		dialog.show();
	}

	async showOpenOrders() {
		if (!this.state.store) return frappe.msgprint(__("Select a Store to view open orders."));
		let orders;
		try { orders = await this.call("get_store_open_orders", { store: this.state.store }); } catch (error) { return this.showError(error); }
		this.openOrders = orders || [];
		this.renderOpenOrders();
		this.page.main.find(".rms-pos-shell").prop("hidden", true);
		this.page.main.find('[data-screen="open-orders"]').prop("hidden", false);
	}

	renderOpenOrders(query = "") {
		const orders = (this.openOrders || []).filter((row) => `${row.name} ${row.check_label || ""} ${row.order_type || ""} ${row.dining_table || ""} ${row.cashier || ""}`.toLowerCase().includes(query.toLowerCase()));
		const cards = orders.map((row) => {
			const own = this.state.session?.status === "Open" && row.cashier_session === this.state.session.name && this.state.permissions.can_checkout;
			const canEdit = this.state.session?.status === "Open" && this.state.permissions.can_checkout
				&& (own || this.state.permissions.can_edit_open_orders);
			const pendingCount = Number(row.pending_item_count || 0);
			const sentCount = Number(row.sent_item_count || 0);
			const pending = pendingCount > 0 || ["Open", "Pending Confirmation"].includes(row.status);
			const preparationStatus = pendingCount || sentCount
				? `${sentCount ? `<em class="is-confirmed">${this.escape(__("Sent to preparation"))} · ${sentCount}</em>` : ""}${pendingCount ? `<em class="is-pending">${this.escape(__("Needs confirmation"))} · ${pendingCount}</em>` : ""}`
				: `<em class="${pending ? "is-pending" : "is-confirmed"}">${pending ? __("Needs confirmation") : __("Sent to preparation")}</em>`;
			const canSplit = ["Open", "Pending Confirmation"].includes(row.status);
			const moveAction = own && row.dining_table && this.state.permissions.can_transfer_tables ? `<button class="rms-screen-secondary" data-action="transfer-open-order" data-order="${this.escape(row.name)}">${__("Transfer")}</button>` : "";
			const splitAction = own && canSplit && this.state.permissions.can_split_orders ? `<button class="rms-screen-secondary" data-action="split-open-order" data-order="${this.escape(row.name)}">${__("Split items")}</button>` : "";
			const openAction = canEdit ? `<button class="rms-screen-primary" data-action="open-pos-order" data-order="${this.escape(row.name)}">${own ? __("Open order") : __("Open to add items")}</button>` : `<button class="rms-screen-secondary" data-action="view-open-order" data-order="${this.escape(row.name)}">${__("View details")}</button>`;
			return `<article class="rms-open-order-card"><div class="rms-open-order-info"><b>${this.escape(row.check_label || this.orderNumber(row.name))}</b><span>${this.escape(row.order_type || "")} · ${row.dining_table ? this.escape(row.dining_table) : __("No table")}</span><small>${this.escape(this.orderNumber(row.name))} · ${this.escape(row.cashier || "")}</small><div class="rms-open-order-prep">${preparationStatus}</div></div><strong class="rms-open-order-total">${this.currency(this.roundPosPayable(row.grand_total, this.getPosRoundingMethod(row.restaurant_brand)))}</strong><div class="rms-open-order-actions">${openAction}${splitAction}${moveAction}${own && this.state.permissions.can_cancel_orders ? `<button class="rms-screen-danger" data-action="cancel-pos-order" data-order="${this.escape(row.name)}">${__("Cancel")}</button>` : ""}</div></article>`;
		}).join("");
		this.page.main.find('[data-screen="open-orders"]').html(`<header class="rms-workspace-head"><button class="rms-screen-back" data-action="screen-back">‹ ${__("Back to register")}</button><div><span class="rms-pos-eyebrow">${__("ACTIVE CHECKS")}</span><h1>${__("Open Orders")}</h1><p>${__("Open any active dine-in or takeaway order to add items and confirm them for preparation.")}</p></div><span class="rms-open-count">${orders.length} ${__("orders")}</span></header><div class="rms-open-orders-toolbar"><input type="search" data-open-order-search placeholder="${__("Search check, table, order type or cashier")}"><button class="rms-screen-secondary" data-action="refresh-open-orders">${__("Refresh")}</button></div><div class="rms-open-orders-list">${cards || `<div class="rms-screen-empty">${__("No matching open orders.")}</div>`}</div>`);
	}

	async transferOpenOrder(orderName) {
		try {
			const order = await this.call("get_order", { order_name: orderName });
			const tables = (await this.call("get_tables", { store: order.store })).filter((row) => !row.occupied || row.name === order.dining_table);
			const choices = tables.filter((row) => row.name !== order.dining_table);
			if (!choices.length) return frappe.msgprint(__("No available destination tables."));
			let selectedTable = null;
			const tableCards = choices.map((row) => `<button type="button" class="rms-table-destination" data-transfer-table="${this.escape(row.name)}"><b>${this.escape(row.title || row.name)}</b><span>${this.escape(row.dining_area_title || row.dining_area || "")}${row.capacity ? ` · ${this.escape(row.capacity)} ${__("seats")}` : ""}</span></button>`).join("");
			const dialog = new frappe.ui.Dialog({ title: __("Transfer order to another table"), size: "large", fields: [
				{ fieldtype: "HTML", fieldname: "transfer_hint", options: `<div class="rms-transfer-intro"><p>${__("Move this check to an available table.")}</p><strong>${this.escape(order.check_label || this.orderNumber(order.name))}</strong><span>${this.escape(order.dining_table || "")}</span></div><div class="rms-table-destinations">${tableCards}</div>` },
			], primary_action_label: __("Transfer order"), primary_action: async () => {
				if (!selectedTable) return frappe.msgprint(__("Choose an available table first."));
				try { await this.call("transfer_order", { order_name: orderName, dining_table: selectedTable }); dialog.hide(); await this.showOpenOrders(); }
				catch (error) { this.showError(error); }
			} });
			dialog.$wrapper.addClass("rms-pos-workflow-dialog"); dialog.show();
			dialog.$wrapper.on("click", "[data-transfer-table]", (event) => {
				selectedTable = event.currentTarget.dataset.transferTable;
				dialog.$wrapper.find("[data-transfer-table]").removeClass("is-selected").attr("aria-pressed", "false");
				$(event.currentTarget).addClass("is-selected").attr("aria-pressed", "true");
			});
		} catch (error) { this.showError(error); }
	}
	async splitOpenOrder(orderName) {
		try {
			const order = await this.call("get_order", { order_name: orderName });
			const requiresTable = Boolean(this.state.order_types.find((row) => row.name === order.order_type)?.require_table);
			let selectedTable = order.dining_table || null;
			let tableMarkup = "";
			if (requiresTable) {
				const tables = (await this.call("get_tables", { store: order.store })).filter((row) => !row.occupied || row.name === order.dining_table);
				if (!tables.length) return frappe.msgprint(__("No available table can hold the split check."));
				if (!tables.some((row) => row.name === selectedTable)) selectedTable = null;
				tableMarkup = `<section class="rms-split-table-section"><h3>${__("Table for the second check")}</h3><div class="rms-table-destinations">${tables.map((row) => `<button type="button" class="rms-table-destination ${row.name === selectedTable ? "is-selected" : ""}" aria-pressed="${row.name === selectedTable}" data-split-table="${this.escape(row.name)}"><b>${this.escape(row.title || row.name)}</b><span>${this.escape(row.dining_area_title || row.dining_area || "")}${row.name === order.dining_table ? ` · ${__("Same table")}` : ""}</span></button>`).join("")}</div></section>`;
			}
			const itemRows = order.items.map((row, index) => `<article class="rms-split-item"><div><b>${this.escape(row.title || row.selling_product)}</b><span>${__("Available")} ${this.escape(row.qty)} ${this.escape(row.uom || "")}${row.notes ? ` · ${this.escape(row.notes)}` : ""}</span></div><label>${__("Move to second check")}<input type="number" data-split-qty="${index}" min="0" max="${this.escape(row.qty)}" step="${row.must_be_whole_number ? "1" : "0.001"}" value="0"></label></article>`).join("");
			const dialog = new frappe.ui.Dialog({ title: __("Split order between guests"), size: "large", fields: [
				{ fieldtype: "HTML", fieldname: "split_order_form", options: `<div class="rms-split-order-form"><div class="rms-split-check-labels"><label>${__("First guest / check")}<input type="text" data-split-source-label maxlength="60" value="${this.escape(order.check_label || __("Guest 1"))}"></label><label>${__("Second guest / check")}<input type="text" data-split-new-label maxlength="60" value="${this.escape(__("Guest 2"))}"></label></div>${tableMarkup}<section class="rms-split-items-section"><h3>${__("Choose items for the second check")}</h3><div class="rms-split-items">${itemRows}</div></section></div>` },
			], primary_action_label: __("Create second check"), primary_action: async () => {
				const quantities = Object.fromEntries([...dialog.$wrapper[0].querySelectorAll("[data-split-qty]")].map((input) => [order.items[Number(input.dataset.splitQty)].name, Number(input.value || 0)]).filter(([, qty]) => qty > 0));
				if (!Object.keys(quantities).length) return frappe.msgprint(__("Choose at least one item for the second check."));
				if (requiresTable && !selectedTable) return frappe.msgprint(__("Choose a table for the second check."));
				const sourceLabel = dialog.$wrapper[0].querySelector("[data-split-source-label]").value.trim();
				const splitLabel = dialog.$wrapper[0].querySelector("[data-split-new-label]").value.trim();
				try { await this.call("split_order", { order_name: orderName, quantities: JSON.stringify(quantities), dining_table: selectedTable, source_check_label: sourceLabel, split_check_label: splitLabel }); dialog.hide(); await this.showOpenOrders(); }
				catch (error) { this.showError(error); }
			} });
			dialog.$wrapper.addClass("rms-pos-workflow-dialog"); dialog.show();
			dialog.$wrapper.on("click", "[data-split-table]", (event) => {
				selectedTable = event.currentTarget.dataset.splitTable;
				dialog.$wrapper.find("[data-split-table]").removeClass("is-selected").attr("aria-pressed", "false");
				$(event.currentTarget).addClass("is-selected").attr("aria-pressed", "true");
			});
		} catch (error) { this.showError(error); }
	}
	showPaymentScreen() {
		const methods = this.state.payment_config || [];
		if (!methods.length && !this.paymentApprovalOnly) return frappe.msgprint(__("Configure payment methods on the POS Profile before taking payment."));
		const guestPayment = this.activeGuestPayment;
		const rawTotal = guestPayment ? Number(guestPayment.source_total ?? guestPayment.grand_total ?? 0) : Number(this.state.totals?.grand_total || 0);
		const total = this.roundPosPayable(rawTotal);
		const activeGuestCheck = guestPayment ? this.guestCheckState?.guest_checks?.find((row) => row.name === guestPayment.guest_check_name) : null;
		this.paymentSourceTotal = rawTotal;
		this.paymentTotal = total;
		this.paymentDiscount = guestPayment
			? { type: activeGuestCheck?.discount_type || "Percentage", value: Number(activeGuestCheck?.discount_value || 0), reason: activeGuestCheck?.discount_reason || "" }
			: { type: this.state.discount_type || "Percentage", value: Number(this.state.discount_value || 0), reason: this.state.discount_reason || "" };
		this.paymentDiscountApprovalCode = null;
		this.paymentDiscountApprovalApprover = null;
		this.paymentDiscountApprovers = [];
		const approvalOnly = Boolean(this.paymentApprovalOnly);
		const canEditDiscount = this.state.permissions.can_apply_manual_discount || approvalOnly;
		const firstGuestAmount = Math.floor(total * 50) / 100;
		const activeOrderItemCount = (this.state.cart || []).filter((row) => row.order_item_name && Number(row.qty || 0) > Number(row.cancelled_qty || 0)).length;
		const paymentItems = (this.state.cart || []).map((row) => ({ row, quantity: Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0)) })).filter(({ row, quantity }) => row.order_item_name && quantity > 0);
		const paymentItemQuantity = paymentItems.reduce((sum, item) => sum + item.quantity, 0);
		const paymentItemsButton = !approvalOnly && !guestPayment && this.guestCheckState?.order_name !== this.state.order_name && paymentItems.length
			? `<button type="button" class="rms-screen-secondary" data-action="payment-open-items" aria-haspopup="dialog" aria-controls="rms-payment-items-dialog">${__("View items ({0})", [paymentItemQuantity])}</button>`
			: "";
		const methodFields = methods.map((row, index) => `<label class="rms-payment-method"><span>${this.escape(row.mode_of_payment)}${row.default ? ` <small>${__("Default")}</small>` : ""}</span><input type="number" min="0" step="0.01" data-payment-amount data-method="${this.escape(row.mode_of_payment)}" value="${index === 0 ? total.toFixed(2) : "0.00"}" aria-label="${__("Amount for")} ${this.escape(row.mode_of_payment)}"></label>`).join("");
		this.paymentGuestMethods = methods;
		this.paymentSplitMode = this.guestCheckState?.order_name === this.state.order_name ? "items" : "amount";
		this.guestSplitFinalized = guestPayment ? true : this.guestCheckState?.order_name === this.state.order_name;
		this.paymentGuests = this.guestCheckState?.order_name === this.state.order_name
			? this.guestCheckState.guest_checks.map((row) => {
				const due = row.status === "Paid" && row.payable_total !== undefined
					? Number(row.payable_total || 0) : this.roundPosPayable(row.grand_total || 0);
				return { check_name: row.name, name: row.guest_name, method: methods[0]?.mode_of_payment, amount: due, due, paid: row.status === "Paid" };
			})
			: methods.length ? [1, 2].map((number) => ({ name: __("Guest {0}", [number]), method: methods[0].mode_of_payment, amount: number === 1 ? firstGuestAmount : total - firstGuestAmount })) : [];
		if (this.guestCheckState?.order_name === this.state.order_name) {
			this.paymentItemAssignments = {};
			this.guestCheckState.guest_checks.forEach((check, index) => (check.items || []).forEach((item) => { const allocation = this.paymentItemAssignments[item.name] ||= Array(this.guestCheckState.guest_checks.length).fill(0); allocation[index] = Number(item.qty || 0); }));
		}
		const guests = this.renderPaymentGuests();
		const discountTools = canEditDiscount ? `<div class="rms-payment-discount-launch"><span>${guestPayment ? this.escape(__("Discount for {0}", [guestPayment.guest_name])) : __("Discount")}: <b data-discount-preview>${this.currency(guestPayment ? activeGuestCheck?.discount_amount || 0 : this.state.totals?.discount_amount || 0)}</b></span><div class="rms-payment-tools-actions"><button type="button" class="rms-screen-secondary" data-action="payment-open-discount" aria-label="${this.escape(guestPayment ? __("Add discount for {0}", [guestPayment.guest_name]) : __("Add discount"))}">${__("Add discount")}</button></div></div>` : "";
		const quick = this.renderSuggestedPaymentAmounts(total);
		const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "C"].map((key) => `<button type="button" data-action="payment-key" data-key="${key}">${key}</button>`).join("");
		const guestResplitButton = activeGuestCheck?.status === "Open" && (activeGuestCheck.items || []).filter((item) => Number(item.qty || 0) > 0).length >= 2
			? `<button type="button" class="rms-screen-secondary" data-action="guest-check-resplit-current">${__("Split items")}</button>` : "";
		const splitMarkup = guestPayment
			? `<section class="rms-guest-payment-overview"><div class="rms-guest-payment-overview-head"><h3>${__("Order split")}</h3>${guestResplitButton}</div><div data-guest-payment-progress-container>${this.renderGuestPaymentProgress(Number(this.state.totals?.grand_total || 0))}</div><div data-split-checks-anchor><input type="checkbox" data-split-check-toggle hidden><div class="rms-guest-checks" data-guest-checks><div class="rms-split-toolbar" hidden><div><span>${__("Split by")}</span><div class="rms-split-mode-switch"><button type="button" data-action="payment-split-mode" data-mode="items">${__("By items")}</button><button type="button" data-action="payment-split-mode" data-mode="amount">${__("Equally")}</button></div></div></div><p data-split-description hidden></p><div data-payment-guests>${guests}</div><div class="rms-item-assignments" data-item-assignments hidden></div><p class="rms-split-balance" data-split-balance data-valid="false" aria-live="polite"></p></div></div></section>`
			: `${this.guestSplitFinalized ? "" : `<div class="rms-split-check-launch"><button type="button" class="rms-screen-secondary" data-action="payment-open-split">${__("Split check")}</button></div>`}<div data-guest-payment-progress-container>${this.renderGuestPaymentProgress(total)}</div><input type="checkbox" data-split-check-toggle hidden><div data-split-checks-anchor><div class="rms-guest-checks" data-guest-checks hidden><div class="rms-split-toolbar"><div><span>${__("Split by")}</span><div class="rms-split-mode-switch" role="group" aria-label="${__("Split by")}"><button type="button" data-action="payment-split-mode" data-mode="items" aria-pressed="${this.paymentSplitMode === "items"}" ${activeOrderItemCount < 2 ? "disabled" : ""}>${__("By items")}</button><button type="button" data-action="payment-split-mode" data-mode="amount" aria-pressed="${this.paymentSplitMode === "amount"}">${__("Equally")}</button></div></div><div class="rms-split-actions"><button type="button" data-action="payment-guest-add">+ ${__("Add person")}</button><button type="button" data-action="payment-guest-remove">− ${__("Remove person")}</button></div></div><p class="rms-split-description" data-split-description>${__("Set each person's share of the bill.")}</p><div data-payment-guests>${guests}</div><div class="rms-item-assignments" data-item-assignments hidden></div><p class="rms-split-balance" data-split-balance data-valid="false" aria-live="polite"></p></div></div>`;
		this.page.main.find('[data-screen="payment"]').html(`<header class="rms-workspace-head"><button class="rms-screen-back" data-action="payment-back">‹ ${__("Back to order")}</button><div><span class="rms-pos-eyebrow">${approvalOnly ? __("DISCOUNT APPROVAL") : __("CHECKOUT")}</span><h1>${approvalOnly ? __("Approve cashier discount") : __("Take Payment")}</h1><p>${this.escape(this.orderNumber(this.state.order_name))} · ${this.escape(guestPayment?.guest_name || this.state.order_type || "")}</p></div><strong class="rms-payment-total">${this.currency(total)}</strong></header><div class="rms-payment-layout"><section class="rms-payment-panel">${approvalOnly ? "" : `<div class="rms-payment-panel-head"><h2>${__("Payment methods")}</h2>${paymentItemsButton}</div><p>${__("Allocate the total across payment methods or guests.")}</p>`}${discountTools}${approvalOnly ? "" : `<div class="rms-payment-method-list">${methodFields}</div>${splitMarkup}<div class="rms-payment-shortcuts"><span>${__("Suggested payment amounts")}</span><div data-suggested-payment-amounts>${quick}</div></div><div class="rms-payment-sum">${__("Remaining")}: <b data-payment-remaining>${this.currency(total)}</b></div><div class="rms-payment-change" data-payment-change hidden>${__("Change")}: <b data-change-amount>${this.currency(0)}</b></div><div class="rms-payment-actions"><button class="rms-screen-secondary" data-action="payment-print-only">${__("Print only")}</button><button class="rms-screen-secondary" data-action="payment-pay-print">${__("Pay and print")}</button><button class="rms-screen-primary" data-action="payment-pay">${__("Pay only")}</button></div>`}</section>${approvalOnly ? "" : `<section class="rms-payment-panel rms-payment-keypad"><h2>${__("Keypad")}</h2><p>${__("Select an amount field, then enter the amount.")}</p><div>${keys}</div></section>`}</div><div data-discount-dialog-root></div><div data-split-dialog-root></div>`);
		this.page.main.find('[data-screen="payment"]').append('<div data-payment-items-dialog-root></div>');
		if (this.guestCheckState?.order_name !== this.state.order_name) this.paymentItemAssignments = {};
		this.renderPaymentItemAssignments();
		this.page.main.find(".rms-pos-shell").prop("hidden", true);
		this.page.main.find('[data-screen="payment"]').prop("hidden", false);
		this.rememberCurrentScreen("payment");
		this.updatePaymentTotal();
		this.updateGuestSplitAmounts();
		if (!guestPayment && this.guestCheckState?.order_name === this.state.order_name) {
			this.page.main[0].querySelector("[data-split-check-toggle]").checked = true;
			this.toggleSplitCheck(true);
		}
		this.toggleDiscountValueInput(this.paymentDiscount.type);
	}

	updatePaymentTotal() {
		const total = Number(this.paymentTotal ?? this.state.totals?.grand_total ?? 0);
		const split = this.page.main[0].querySelector("[data-split-check-toggle]")?.checked;
		const selector = split ? "[data-guest-amount]" : "[data-payment-amount]";
		const inputs = [...this.page.main[0].querySelectorAll(selector)];
		const paid = inputs.reduce((sum, input) => sum + (Number(input.value) || 0), 0);
		const remaining = total - paid;
		this.page.main.find("[data-payment-remaining]").text(this.currency(Math.max(0, remaining)));
		const change = Math.max(0, paid - total);
		this.page.main.find("[data-payment-change]").prop("hidden", change < 0.005);
		this.page.main.find("[data-change-amount]").text(this.currency(change));
	}

	applySuggestedPaymentAmount(amount) {
		const inputs = [...this.page.main[0].querySelectorAll("[data-payment-amount]")];
		const cashMethod = this.state.payment_config?.find((method) => method.type === "Cash")?.mode_of_payment;
		const input = inputs.includes(this.paymentInput) ? this.paymentInput : inputs.find((row) => row.dataset.method === cashMethod) || inputs[0];
		if (!input) return;
		input.value = Math.max(0, Number(amount) || 0).toFixed(2);
		this.paymentInput = input;
		input.dispatchEvent(new Event("input", { bubbles: true }));
	}

	openGuestPayment(index) {
		const guest = this.paymentGuests?.[index];
		const check = this.guestCheckState?.order_name === this.state.order_name
			? this.guestCheckState.guest_checks.find((row) => row.guest_name === guest?.name) : null;
		if (!guest || !check || guest.paid || check.status === "Paid") return;
		const total = check.status === "Paid" ? Number(check.payable_total || check.grand_total || 0)
			: this.roundPosPayable(check.grand_total || guest.due || 0);
		this.activeGuestPayment = { guest_check_name: check.name, guest_name: guest.name,
			grand_total: total, source_total: Number(check.grand_total || guest.due || 0), index };
		this.showPaymentScreen();
	}

	renderGuestPaymentProgress(total) {
		if (!this.guestSplitFinalized || this.paymentSplitMode !== "items" || this.guestCheckState?.order_name !== this.state.order_name) return "";
		const checks = this.guestCheckState.guest_checks || [];
		const checkPayable = (check) => check.status === "Paid" && check.payable_total !== undefined
			? Number(check.payable_total || 0) : this.roundPosPayable(check.grand_total || 0);
		const paid = checks.reduce((sum, check) => sum + (check.status === "Paid" ? checkPayable(check) : 0), 0);
		const payableTotal = checks.reduce((sum, check) => sum + checkPayable(check), 0);
		const percent = payableTotal > 0 ? Math.max(0, Math.min(100, Math.round(paid / payableTotal * 100))) : 100;
		return `<section class="rms-guest-payment-progress" aria-label="${__("Order payment progress")}"><div><span>${__("Paid amount")}</span><strong>${this.currency(paid)} <small>/ ${this.currency(payableTotal)}</small></strong></div><div class="rms-guest-payment-progress-track" role="progressbar" aria-label="${__("Paid")}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span style="width:${percent}%"></span></div><small>${percent}% ${__("paid")}</small></section>`;
	}

	renderPaymentGuests(setupOnly = false) {
		const methods = this.paymentGuestMethods || [];
		const mode = this.paymentSplitMode || "amount";
		const finalized = Boolean(this.guestSplitFinalized);
		const groups = this.getPaymentItemGroups();
		const entries = (this.paymentGuests || []).map((guest, index) => ({ guest, index }));
		const visibleEntries = this.activeGuestPayment && !this.paymentSplitSetupOpen
			? entries.filter(({ guest }) => guest.check_name === this.activeGuestPayment.guest_check_name)
			: entries;
		return visibleEntries.map(({ guest, index }) => {
			const guestName = this.escape(guest.name || __("Guest {0}", [index + 1]));
			const currentPayment = guest.check_name && guest.check_name === this.activeGuestPayment?.guest_check_name;
			const status = guest.paid ? `<span class="rms-guest-check-status is-paid">${__("Paid")}</span>` : currentPayment ? `<span class="rms-guest-check-status is-current">${__("Selected")}</span>` : `<span class="rms-guest-check-status">${__("Open")}</span>`;
			const resplitItemNames = new Set(this.paymentResplitItemNames || []);
			const scopedGroups = resplitItemNames.size ? groups.filter((group) => group.rows.some((row) => resplitItemNames.has(row.order_item_name))) : groups;
			const visibleGroups = finalized && mode === "items" ? scopedGroups.filter((group) => group.rows.some((row) => Number(this.paymentItemAssignments?.[row.order_item_name]?.[index] || 0) > 0)) : scopedGroups;
			const itemList = mode === "items" ? `<div class="rms-guest-item-list" aria-label="${__("Items for")} ${guestName}">${visibleGroups.map((group) => {
				const assigned = group.rows.filter((row) => Number(this.paymentItemAssignments?.[row.order_item_name]?.[index] || 0) > 0);
				const quantity = group.rows.reduce((sum, row) => sum + Number(this.paymentItemAssignments?.[row.order_item_name]?.[index] || 0), 0);
				const total = group.rows.reduce((sum, row) => { const active = Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0)); return sum + (active ? this.paymentItemRowAmount(row) * Number(this.paymentItemAssignments?.[row.order_item_name]?.[index] || 0) / active : 0); }, 0);
				const canTake = group.rows.some((row) => (this.paymentItemAssignments?.[row.order_item_name] || []).some((qty, guestIndex) => guestIndex !== index && Number(qty) >= (row.must_be_whole_number === false ? 0.001 : 1)));
				const canGive = group.rows.some((row) => Number(this.paymentItemAssignments?.[row.order_item_name]?.[index] || 0) >= (row.must_be_whole_number === false ? 0.001 : 1));
				return `<div class="rms-guest-item"><div class="rms-guest-item-copy"><strong>${this.escape(group.title)}</strong><small>${this.currency(total)}</small></div><div class="rms-guest-item-quantity" aria-label="${quantity} ${__("assigned")}"><button type="button" data-action="split-item-adjust" data-group-key="${this.escape(group.key)}" data-guest-index="${index}" data-delta="-1" aria-label="${__("Move one unit away from")} ${guestName}" ${!canGive || guest.paid || finalized ? "disabled" : ""}>−</button><b>${quantity}</b><button type="button" data-action="split-item-adjust" data-group-key="${this.escape(group.key)}" data-guest-index="${index}" data-delta="1" aria-label="${__("Move one unit to")} ${guestName}" ${!canTake || guest.paid || finalized ? "disabled" : ""}>+</button></div></div>`;
			}).join("")}</div>` : "";
			const shareField = `<label>${mode === "items" ? __("Check total") : __("Share due")}<input type="number" data-guest-share data-manual-share="${guest.dueManual ? "1" : ""}" min="0" step="0.01" value="${Number(guest.due || guest.amount || 0).toFixed(2)}" ${mode === "items" || guest.paid || finalized || setupOnly ? "readonly" : ""}></label>`;
			const lockedCheck = mode === "items" && finalized && !setupOnly;
			const paymentFields = setupOnly || lockedCheck ? "" : `<label>${__("Payment method")}<select data-guest-method ${guest.paid ? "disabled" : ""}>${methods.map((row) => `<option value="${this.escape(row.mode_of_payment)}" ${row.mode_of_payment === guest.method ? "selected" : ""}>${this.escape(row.mode_of_payment)}</option>`).join("")}</select></label><label>${__("Paid Amount")}<input type="number" data-guest-amount data-manual="${guest.manual ? "1" : ""}" min="0" step="0.01" value="${Number(guest.amount || 0).toFixed(2)}" ${guest.paid ? "disabled" : ""}></label>`;
			const checkActions = lockedCheck && !guest.paid && !currentPayment ? `<div class="rms-guest-check-actions"><button type="button" data-action="guest-check-take-payment" data-guest-index="${index}">${__("Take Payment")}</button></div>` : "";
			return `<article class="rms-guest-check ${mode === "items" ? "is-item-check" : ""} ${currentPayment ? "is-current-payment" : ""}" data-guest-index="${index}"><header><div class="rms-guest-check-heading"><span class="rms-guest-check-number">${index + 1}</span><strong>${guestName}</strong>${status}</div></header><label class="rms-guest-name">${__("Guest name")}<input type="text" data-guest-name value="${guestName}" aria-label="${__("Guest {0}", [index + 1])}" ${guest.paid || finalized ? "disabled" : ""}></label>${itemList}<div class="rms-guest-check-fields">${shareField}${paymentFields}</div>${checkActions}</article>`;
		}).join("");
	}

	openGuestCheckResplit(index) {
		const check = this.guestCheckState?.guest_checks?.[index];
		if (!check || check.status !== "Open") return;
		const itemNames = (check.items || []).filter((item) => Number(item.qty || 0) > 0).map((item) => item.name);
		if (itemNames.length < 2) return frappe.msgprint(__("By items requires at least two active order items."));
		const root = this.page.main[0];
		const checks = root.querySelector("[data-guest-checks]");
		const dialogRoot = root.querySelector("[data-split-dialog-root]");
		if (!checks || !dialogRoot) return;
		this.paymentSplitDraftBackup = {
			mode: this.paymentSplitMode || "items", finalized: Boolean(this.guestSplitFinalized), total: this.paymentTotal,
			sourceTotal: this.paymentSourceTotal,
			resplitGuestIndex: this.paymentResplitGuestIndex, resplitItemNames: this.paymentResplitItemNames,
			guests: (this.paymentGuests || []).map((guest) => ({ ...guest })),
			assignments: Object.fromEntries(Object.entries(this.paymentItemAssignments || {}).map(([name, values]) => [name, Array.isArray(values) ? [...values] : values])),
			payments: [...root.querySelectorAll("[data-payment-amount]")].map((input) => input.value),
		};
		this.paymentResplitGuestIndex = index;
		this.paymentResplitItemNames = itemNames;
		this.paymentSourceTotal = Number(check.grand_total || 0);
		this.paymentTotal = this.roundPosPayable(this.paymentSourceTotal);
		this.paymentSplitMode = "items";
		this.paymentSplitSetupOpen = true;
		this.guestSplitFinalized = false;
		this.paymentGuests = [
			{ name: check.guest_name, method: this.paymentGuestMethods?.[0]?.mode_of_payment, amount: Number(check.grand_total || 0), due: Number(check.grand_total || 0) },
			{ name: __("Guest {0}", [this.guestCheckState.guest_checks.length + 1]), method: this.paymentGuestMethods?.[0]?.mode_of_payment, amount: 0, due: 0 },
		];
		this.paymentItemAssignments = Object.fromEntries((this.state.cart || []).filter((row) => row.order_item_name).map((row) => {
			const assigned = (check.items || []).find((item) => item.name === row.order_item_name);
			return [row.order_item_name, [Number(assigned?.qty || 0), 0]];
		}));
		const guestList = checks.querySelector("[data-payment-guests]");
		if (guestList) guestList.innerHTML = this.renderPaymentGuests(true);
		dialogRoot.innerHTML = this.renderPaymentSplitDialog();
		dialogRoot.querySelector("[data-split-modal-host]").append(checks);
		checks.hidden = false;
		root.querySelector(".rms-split-toolbar > div:first-child").hidden = true;
		root.querySelectorAll('[data-action="payment-split-mode"]').forEach((button) => button.hidden = true);
		root.querySelector("[data-split-description]").textContent = __("Assign this open check's items to guests.");
		root.querySelector("[data-split-check-toggle]").checked = true;
		this.renderPaymentItemAssignments();
		this.updateGuestSplitAmounts();
		dialogRoot.querySelector("[data-split-dialog]")?.focus();
	}

	openCurrentGuestCheckResplit() {
		if (!this.activeGuestPayment) return;
		this.openGuestCheckResplit(Number(this.activeGuestPayment.index));
	}

	renderPaymentSplitDialog() {
		return `<div class="rms-split-dialog-backdrop" data-split-dialog-backdrop><section class="rms-split-dialog" data-split-dialog role="dialog" aria-modal="true" aria-labelledby="rms-split-dialog-title" tabindex="-1"><header><div><span class="rms-pos-eyebrow">${__("CHECKOUT")}</span><h2 id="rms-split-dialog-title">${__("Split check")}</h2><p>${this.paymentResplitGuestIndex !== null && this.paymentResplitGuestIndex !== undefined ? __("Assign this open check's items to guests.") : __("Choose equal shares or assign items to each guest.")}</p></div><button type="button" data-action="payment-cancel-split" aria-label="${__("Close")}">×</button></header><div class="rms-split-dialog-body"><div data-split-modal-host></div></div><footer><button type="button" class="rms-screen-secondary" data-action="payment-cancel-split">${__("Cancel")}</button><button type="button" class="rms-screen-primary" data-action="payment-confirm-split" disabled>${__("Confirm split")}</button></footer></section></div>`;
	}

	openPaymentSplitDialog() {
		if (this.guestSplitFinalized) return frappe.msgprint(__("Guest checks are confirmed and cannot be changed."));
		const root = this.page.main[0];
		const split = root.querySelector("[data-split-check-toggle]");
		const checks = root.querySelector("[data-guest-checks]");
		const dialogRoot = root.querySelector("[data-split-dialog-root]");
		if (!split || !checks || !dialogRoot) return;
		this.paymentSplitDraftBackup = {
			mode: this.paymentSplitMode || "amount",
			finalized: Boolean(this.guestSplitFinalized),
			total: this.paymentTotal,
			resplitGuestIndex: this.paymentResplitGuestIndex,
			resplitItemNames: this.paymentResplitItemNames,
			guests: (this.paymentGuests || []).map((guest) => ({ ...guest })),
			assignments: Object.fromEntries(Object.entries(this.paymentItemAssignments || {}).map(([name, values]) => [name, Array.isArray(values) ? [...values] : values])),
			payments: [...root.querySelectorAll("[data-payment-amount]")].map((input) => input.value),
		};
		const activeOrderItemCount = (this.state.cart || []).filter((row) => row.order_item_name && Number(row.qty || 0) > Number(row.cancelled_qty || 0)).length;
		this.paymentSplitMode = activeOrderItemCount >= 2 ? "items" : "amount";
		this.paymentResplitGuestIndex = null;
		this.paymentResplitItemNames = null;
		root.querySelector(".rms-split-toolbar > div:first-child").hidden = false;
		root.querySelectorAll('[data-action="payment-split-mode"]').forEach((button) => button.hidden = false);
		this.paymentSplitSetupOpen = true;
		split.checked = true;
		this.toggleSplitCheck(true);
		dialogRoot.innerHTML = this.renderPaymentSplitDialog();
		dialogRoot.querySelector("[data-split-modal-host]").append(checks);
		checks.hidden = false;
		this.renderPaymentItemAssignments();
		this.updateGuestSplitAmounts();
		dialogRoot.querySelector("[data-split-dialog]")?.focus();
	}

	closePaymentSplitDialog() {
		const root = this.page.main[0];
		const dialogRoot = root.querySelector("[data-split-dialog-root]");
		const checks = root.querySelector("[data-guest-checks]");
		const anchor = root.querySelector("[data-split-checks-anchor]");
		if (!dialogRoot?.childElementCount || !checks || !anchor) return;
		anchor.append(checks);
		dialogRoot.innerHTML = "";
		this.paymentSplitSetupOpen = false;
		const backup = this.paymentSplitDraftBackup;
		this.guestSplitFinalized = Boolean(backup?.finalized);
		root.querySelector("[data-split-check-toggle]").checked = false;
		if (backup) {
			this.paymentSplitMode = backup.mode;
			this.paymentTotal = backup.total;
			this.paymentSourceTotal = backup.sourceTotal;
			this.paymentResplitGuestIndex = backup.resplitGuestIndex ?? null;
			this.paymentResplitItemNames = backup.resplitItemNames ?? null;
			this.paymentGuests = backup.guests;
			this.paymentItemAssignments = backup.assignments;
		}
		root.querySelectorAll('[data-action="payment-split-mode"]').forEach((button) => button.hidden = backup?.resplitGuestIndex !== null && backup?.resplitGuestIndex !== undefined);
		root.querySelector(".rms-split-toolbar > div:first-child").hidden = backup?.resplitGuestIndex !== null && backup?.resplitGuestIndex !== undefined;
		this.toggleSplitCheck(false);
		if (backup) [...root.querySelectorAll("[data-payment-amount]")].forEach((input, index) => { if (backup.payments[index] !== undefined) input.value = backup.payments[index]; });
		this.paymentSplitDraftBackup = null;
		checks.hidden = true;
		this.renderPaymentItemAssignments();
		this.updatePaymentTotal();
		if (backup?.resplitGuestIndex !== null && backup?.resplitGuestIndex !== undefined && this.activeGuestPayment) return this.showPaymentScreen();
	}

	async confirmPaymentSplit() {
		if (this.paymentSubmitting || !this.paymentSplitSetupOpen) return;
		this.updateGuestSplitAmounts();
		const root = this.page.main[0];
		if (root.querySelector("[data-split-balance]")?.dataset.valid !== "true") return frappe.msgprint(root.querySelector("[data-split-balance]")?.textContent || __("Complete the split before confirming."));
		if (this.paymentResplitGuestIndex !== null && this.paymentResplitGuestIndex !== undefined) {
			const target = this.guestCheckState?.guest_checks?.[this.paymentResplitGuestIndex];
			if (!target || target.status !== "Open") return frappe.msgprint(__("Only an open guest check can be split again."));
			const guest_checks = [...root.querySelectorAll(".rms-guest-check")].map((card, index) => ({
				guest_name: (card.querySelector("[data-guest-name]").value || __("Guest {0}", [index + 1])).trim(),
				items: Object.entries(this.paymentItemAssignments || {}).flatMap(([name, quantities]) => Number(quantities?.[index] || 0) > 0 ? [{ name, qty: Number(quantities[index]) }] : []),
			}));
			this.paymentSubmitting = true;
			try {
				const result = await this.call("resplit_open_guest_check", { order_name: this.state.order_name, guest_check_name: target.name, guest_checks: JSON.stringify(guest_checks) });
				this.guestCheckState = { order_name: this.state.order_name, guest_checks: result.guest_checks };
				if (this.activeGuestPayment) {
					const activeIndex = result.guest_checks.findIndex((row) => row.name === this.activeGuestPayment.guest_check_name);
					const activeCheck = result.guest_checks[activeIndex];
					if (activeCheck) this.activeGuestPayment = { ...this.activeGuestPayment, guest_name: activeCheck.guest_name, grand_total: Number(activeCheck.grand_total || 0), index: activeIndex };
				}
				this.paymentSplitMode = "items";
				this.paymentResplitGuestIndex = null;
				this.paymentResplitItemNames = null;
				this.paymentSplitSetupOpen = false;
				this.paymentSplitDraftBackup = null;
				return this.showPaymentScreen();
			} catch (error) { return this.showError(error); }
			finally { this.paymentSubmitting = false; }
		}
		if (this.paymentSplitMode === "items") {
			this.paymentSubmitting = true;
			try { await this.ensureGuestChecks(); }
			catch (error) { this.showError(error); return; }
			finally { this.paymentSubmitting = false; }
		}
		this.guestSplitFinalized = true;
		this.paymentSplitSetupOpen = false;
		this.paymentSplitDraftBackup = null;
		const checks = root.querySelector("[data-guest-checks]");
		const anchor = root.querySelector("[data-split-checks-anchor]");
		anchor.append(checks);
		root.querySelector("[data-split-dialog-root]").innerHTML = "";
		checks.hidden = false;
		root.querySelector(".rms-split-toolbar").hidden = true;
		root.querySelector("[data-split-description]").hidden = true;
		this.renderPaymentItemAssignments();
		this.updateGuestSplitAmounts();
		this.updatePaymentTotal();
		const progress = root.querySelector("[data-guest-payment-progress-container]");
		if (progress) progress.innerHTML = this.renderGuestPaymentProgress(this.paymentTotal);
	}

	getPaymentItemGroups() {
		const groups = new Map();
		for (const row of (this.state.cart || []).filter((item) => item.order_item_name && Math.max(0, Number(item.qty || 0) - Number(item.cancelled_qty || 0)) > 0)) {
			const modifiers = (row.modifier_labels || []).map((item) => [item.title || item.modifier_product, Number(item.price || 0)]).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
			const key = JSON.stringify([row.selling_product || row.title, row.option_parent || "", row.uom || "", Number(row.price || 0), row.notes || "", modifiers]);
			if (!groups.has(key)) groups.set(key, { key, title: row.title, rows: [] });
			groups.get(key).rows.push(row);
		}
		return [...groups.values()];
	}

	paymentItemRowAmount(row) {
		const quantity = Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0));
		return quantity * (Number(row.price || 0) + (row.modifier_labels || []).reduce((sum, modifier) => sum + Number(modifier.price || 0), 0));
	}

	syncPaymentGuestFields() {
		const cards = this.page.main[0]?.querySelectorAll(".rms-guest-check") || [];
		cards.forEach((card, position) => {
			const index = Number(card.dataset.guestIndex ?? position);
			const guest = this.paymentGuests?.[index];
			if (!guest) return;
			guest.name = card.querySelector("[data-guest-name]")?.value || guest.name;
			guest.method = card.querySelector("[data-guest-method]")?.value || guest.method;
			guest.amount = Number(card.querySelector("[data-guest-amount]")?.value || 0);
			guest.due = Number(card.querySelector("[data-guest-share]")?.value || 0);
			guest.manual = Boolean(card.querySelector("[data-guest-amount]")?.dataset.manual);
		});
	}

	changePaymentGuestCount(delta) {
		this.syncPaymentGuestFields();
		const count = this.paymentGuests?.length || 0;
		if (this.guestSplitFinalized) return frappe.msgprint(__("Guest checks are confirmed and cannot be changed."));
		if (this.paymentGuests?.some((guest) => guest.paid)) return frappe.msgprint(__("Guest checks cannot be changed after one has been paid."));
		if (delta > 0 && (this.paymentResplitGuestIndex !== null && this.paymentResplitGuestIndex !== undefined ? (this.guestCheckState?.guest_checks?.length || 0) + count - 1 >= 10 : count >= 10)) return frappe.msgprint(__("A check can be split between up to ten people."));
		if (delta < 0 && count <= 2) return;
		if (delta > 0) {
			const newNumber = this.paymentResplitGuestIndex !== null && this.paymentResplitGuestIndex !== undefined ? (this.guestCheckState?.guest_checks?.length || 0) + count - 1 : count + 1;
			this.paymentGuests.push({ name: __("Guest {0}", [newNumber]), method: this.paymentGuestMethods?.[0]?.mode_of_payment, amount: 0, due: 0, manual: false, dueManual: false });
			for (const allocation of Object.values(this.paymentItemAssignments || {})) if (Array.isArray(allocation)) allocation.push(0);
		} else {
			const removedIndex = count - 1;
			for (const allocation of Object.values(this.paymentItemAssignments || {})) if (Array.isArray(allocation)) {
				allocation[0] = Number(allocation[0] || 0) + Number(allocation[removedIndex] || 0);
				allocation.pop();
			}
			this.paymentGuests.pop();
		}
		if (this.paymentResplitGuestIndex === null || this.paymentResplitGuestIndex === undefined) this.guestCheckState = null;
		this.page.main[0].querySelector("[data-payment-guests]").innerHTML = this.renderPaymentGuests(Boolean(this.paymentSplitSetupOpen));
		this.renderPaymentItemAssignments();
		this.updateGuestSplitAmounts();
	}
	async setPaymentSplitMode(mode) {
		if (!["amount", "items"].includes(mode)) return;
		if (this.guestSplitFinalized) return frappe.msgprint(__("Guest checks are confirmed and cannot be changed."));
		if (this.paymentGuests?.some((guest) => guest.paid)) return frappe.msgprint(__("Guest checks cannot be changed after one has been paid."));
		if (mode === "amount" && this.guestCheckState?.order_name === this.state.order_name) {
			try { await this.call("clear_guest_check_allocations", { order_name: this.state.order_name }); this.guestCheckState = null; }
			catch (error) { return this.showError(error); }
		}
		if (mode === "items" && (this.state.cart || []).filter((row) => row.order_item_name && Number(row.qty || 0) > Number(row.cancelled_qty || 0)).length < 2) return frappe.msgprint(__("By items requires at least two active order items."));
		this.paymentSplitMode = mode;
		this.page.main[0].querySelectorAll('[data-action="payment-split-mode"]').forEach((button) => {
			button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
		});
		const description = this.page.main[0].querySelector("[data-split-description]");
		if (description) description.textContent = mode === "items"
			? __("All item quantities start with Guest 1. Use + or − to move one unit to another guest.")
			: __("The order total is divided equally between the guests.");
		this.renderPaymentItemAssignments();
		this.updateGuestSplitAmounts();
	}

	renderPaymentItemAssignments() {
		const root = this.page.main[0];
		const target = root?.querySelector("[data-payment-guests]");
		if (!target) return;
		this.syncPaymentGuestFields();
		root.querySelectorAll('[data-action="payment-split-mode"]').forEach((button) => {
			button.setAttribute("aria-pressed", String(button.dataset.mode === this.paymentSplitMode));
		});
		const items = (this.state.cart || []).filter((row) => row.order_item_name && Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0)) > 0);
		this.paymentItemAssignments ||= {};
		for (const group of this.getPaymentItemGroups()) {
			for (const row of group.rows) {
				const active = Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0));
				let allocation = this.paymentItemAssignments[row.order_item_name];
				if (!Array.isArray(allocation)) { allocation = Array((this.paymentGuests || []).length).fill(0); allocation[0] = active; this.paymentItemAssignments[row.order_item_name] = allocation; }
				while (allocation.length < (this.paymentGuests || []).length) allocation.push(0);
			}
		}
		target.innerHTML = this.renderPaymentGuests(Boolean(this.paymentSplitSetupOpen || this.activeGuestPayment));
		const itemMode = this.paymentSplitMode === "items";
		const itemSplitActive = itemMode && Boolean(root.querySelector("[data-split-check-toggle]")?.checked);
		const guestTender = root.querySelector("[data-guest-amount]:not([disabled])");
		const methodTender = root.querySelector("[data-payment-amount]:not([disabled])");
		if (itemSplitActive) {
			if (!this.paymentInput?.isConnected || this.paymentInput.matches?.("[data-payment-amount]")) this.paymentInput = guestTender;
		} else if (!this.paymentInput?.isConnected || this.paymentInput.matches?.("[data-guest-amount]")) {
			this.paymentInput = methodTender || guestTender;
		}
		if (!this.paymentInput?.isConnected) this.paymentInput = guestTender || methodTender;
		this.paymentKeypadInput = null;
		root.querySelector(".rms-payment-layout")?.classList.toggle("is-item-split", itemSplitActive);
		root.querySelector(".rms-payment-layout")?.classList.toggle("is-guest-check-overview", Boolean(this.guestSplitFinalized && itemMode && !this.activeGuestPayment));
		root.querySelector(".rms-guest-checks")?.classList.toggle("is-item-split", itemMode);
		root.querySelector(".rms-payment-method-list")?.classList.toggle("is-item-split-hidden", itemSplitActive);
		root.querySelector(".rms-split-toolbar")?.toggleAttribute("hidden", Boolean(this.guestSplitFinalized && !this.paymentSplitSetupOpen));
		root.querySelector("[data-split-description]")?.toggleAttribute("hidden", Boolean(this.guestSplitFinalized));
		root.querySelectorAll('[data-action="payment-pay"], [data-action="payment-pay-print"], [data-action="payment-print-only"]').forEach((button) => { button.hidden = itemSplitActive; });
		root.querySelectorAll(".rms-payment-shortcuts, .rms-payment-sum, .rms-payment-change").forEach((node) => { node.hidden = itemSplitActive; });
		if (this.paymentGuests?.some((guest) => guest.paid)) {
			root.querySelectorAll("[data-item-guest], [data-guest-name], [data-action='payment-guest-add'], [data-action='payment-guest-remove'], [data-action='payment-split-mode']").forEach((input) => { input.disabled = true; });
		}
	}

	adjustPaymentItemAllocation(groupKey, guestIndex, delta) {
		if (this.guestSplitFinalized) return frappe.msgprint(__("Guest checks are confirmed and cannot be changed."));
		if (this.paymentGuests?.some((guest) => guest.paid)) return frappe.msgprint(__("Guest checks cannot be changed after one has been paid."));
		this.syncPaymentGuestFields();
		const group = this.getPaymentItemGroups().find((row) => row.key === groupKey);
		if (!group || !this.paymentGuests?.[guestIndex]) return;
		const stepFor = (row) => row.must_be_whole_number === false ? 0.001 : 1;
		const quantityFor = (row, index) => Number(this.paymentItemAssignments[row.order_item_name]?.[index] || 0);
		const totals = this.paymentGuests.map((_, index) => group.rows.reduce((sum, row) => sum + quantityFor(row, index), 0));
		if (delta > 0) {
			const donor = totals.map((quantity, index) => ({ index, quantity })).filter((row) => row.index !== guestIndex && row.quantity > 0).sort((a, b) => b.quantity - a.quantity)[0];
			if (!donor) return;
			const row = group.rows.find((item) => quantityFor(item, donor.index) >= stepFor(item));
			if (!row) return;
			const allocation = this.paymentItemAssignments[row.order_item_name];
			const moved = Math.min(1, quantityFor(row, donor.index));
			allocation[donor.index] = Number((allocation[donor.index] - moved).toFixed(3));
			allocation[guestIndex] = Number((quantityFor(row, guestIndex) + moved).toFixed(3));
		} else {
			const row = group.rows.find((item) => quantityFor(item, guestIndex) >= stepFor(item));
			if (!row) return;
			const recipient = totals.map((quantity, index) => ({ index, quantity })).filter((item) => item.index !== guestIndex).sort((a, b) => a.quantity - b.quantity)[0];
			if (!recipient) return;
			const allocation = this.paymentItemAssignments[row.order_item_name];
			const moved = Math.min(1, quantityFor(row, guestIndex));
			allocation[guestIndex] = Number((allocation[guestIndex] - moved).toFixed(3));
			allocation[recipient.index] = Number((quantityFor(row, recipient.index) + moved).toFixed(3));
		}
		if (this.paymentResplitGuestIndex === null || this.paymentResplitGuestIndex === undefined) this.guestCheckState = null;
		this.renderPaymentItemAssignments(); this.updateGuestSplitAmounts();
	}
	updateGuestSplitAmounts() {
		if (!this.page.main[0]?.querySelector("[data-split-check-toggle]")?.checked) return;
		const mode = this.paymentSplitMode || "amount";
		const total = Number((mode === "items" ? this.paymentSourceTotal : this.paymentTotal) || 0);
		const sections = [...this.page.main[0].querySelectorAll(".rms-guest-check")];
		const dues = sections.map(() => 0);
		let valid = true;
		let message = "";
		if (mode === "amount") {
			const shares = sections.map((section) => section.querySelector("[data-guest-share]"));
			const manualIndexes = shares.map((input, index) => input.dataset.manualShare === "1" ? index : -1).filter((index) => index >= 0);
			const autoIndexes = shares.map((input, index) => input.dataset.manualShare !== "1" ? index : -1).filter((index) => index >= 0);
			const manualTotal = manualIndexes.reduce((sum, index) => sum + Math.max(0, Number(shares[index].value || 0)), 0);
			const remainder = Math.max(0, total - manualTotal);
			if (autoIndexes.length) {
				const base = Math.floor(remainder * 100 / autoIndexes.length) / 100;
				autoIndexes.forEach((index, position) => { shares[index].value = (position === autoIndexes.length - 1 ? remainder - base * (autoIndexes.length - 1) : base).toFixed(2); });
			}
			shares.forEach((input, index) => { dues[index] = Math.max(0, Number(input.value || 0)); });
			const allocated = dues.reduce((sum, amount) => sum + amount, 0);
			valid = Math.abs(allocated - total) <= 0.01 && (total <= 0.005 || dues.every((amount) => amount > 0.005));
			message = valid ? __("Shares match the order total.") : Math.abs(allocated - total) > 0.01
				? __("Shares must add up to the order total.") : __("Give every person a share of the order.");
		} else {
			const scopedNames = new Set(this.paymentResplitItemNames || []);
			const lines = (this.state.cart || []).filter((row) => row.order_item_name && Number(row.qty || 0) > Number(row.cancelled_qty || 0) && (!scopedNames.size || scopedNames.has(row.order_item_name)));
			if (lines.length < 2) { valid = false; message = __("By items requires at least two active order items."); }
			const scopedQuantities = new Map((this.guestCheckState?.guest_checks?.[this.paymentResplitGuestIndex]?.items || []).map((item) => [item.name, Number(item.qty || 0)]));
			const amountFor = (row) => {
				const fullQty = Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0));
				const qty = scopedNames.size ? Number(scopedQuantities.get(row.order_item_name) || 0) : fullQty;
				return fullQty ? this.paymentItemRowAmount(row) * qty / fullQty : 0;
			};
			const subtotal = lines.reduce((sum, row) => sum + amountFor(row), 0);
			for (const row of lines) {
				const active = scopedNames.size ? Number(scopedQuantities.get(row.order_item_name) || 0) : Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0));
				const allocation = this.paymentItemAssignments?.[row.order_item_name] || [];
				const allocatedQty = allocation.reduce((sum, quantity) => sum + Number(quantity || 0), 0);
				if (Math.abs(allocatedQty - active) > 0.001 || allocation.some((quantity) => Number(quantity) < -0.001)) valid = false;
			if (subtotal > 0 && active > 0) allocation.forEach((quantity, index) => { if (index < dues.length && Number(quantity) > 0) dues[index] += total * amountFor(row) * Number(quantity) / active / subtotal; });
			}
			const assigned = sections.map((_, index) => lines.some((row) => Number(this.paymentItemAssignments?.[row.order_item_name]?.[index] || 0) > 0) ? index : -1).filter((index) => index >= 0);
			if (valid && assigned.length) {
				let allocated = 0;
				for (const index of assigned.slice(0, -1)) { dues[index] = Math.round(dues[index] * 100) / 100; allocated += dues[index]; }
				const last = assigned[assigned.length - 1]; dues[last] = Math.round((total - allocated) * 100) / 100;
			}
			if (assigned.length !== sections.length) valid = false;
			message = valid ? __("Every item quantity is assigned once. Guests can pay separately.") : __("Assign every item quantity and give each guest an item.");
		}
		sections.forEach((section, index) => {
			let due = Math.round((dues[index] || 0) * 100) / 100;
			if (mode === "items") {
				const savedCheck = this.guestCheckState?.order_name === this.state.order_name
					? this.guestCheckState.guest_checks?.[index] : null;
				const rawCheckTotal = this.guestSplitFinalized && savedCheck ? Number(savedCheck.grand_total || 0) : due;
				due = savedCheck?.status === "Paid" && savedCheck.payable_total !== undefined
					? Number(savedCheck.payable_total || 0) : this.roundPosPayable(rawCheckTotal);
			}
			if (this.paymentGuests?.[index]) this.paymentGuests[index].due = due;
			const share = section.querySelector("[data-guest-share]");
			share.value = due.toFixed(2);
			const tender = section.querySelector("[data-guest-amount]");
			if (tender && !tender.dataset.manual) tender.value = due.toFixed(2);
		});
		const balance = this.page.main[0].querySelector("[data-split-balance]");
		if (balance) { balance.dataset.valid = String(valid); balance.textContent = message; balance.classList.toggle("is-invalid", !valid); }
		const confirmButton = this.page.main[0].querySelector('[data-action="payment-confirm-split"]');
		if (confirmButton) confirmButton.disabled = !valid;
		this.updatePaymentTotal();
	}

	openPaymentDiscountDialog() {
		const root = this.page.main[0].querySelector("[data-discount-dialog-root]");
		if (!root) return;
		root.innerHTML = this.renderPaymentDiscountDialog();
		root.querySelector("[data-discount-dialog]")?.focus();
	}

	renderPaymentItemsDialog() {
		const groups = new Map();
		for (const row of (this.state.cart || [])) {
			const quantity = Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0));
			if (!row.order_item_name || quantity <= 0) continue;
			const modifiers = (row.modifier_labels || []).map((modifier) => ({
				title: modifier.title,
				price: Number(modifier.price || 0),
			}));
			const unitPrice = Number(row.price || 0) + modifiers.reduce((sum, modifier) => sum + modifier.price, 0);
			const modifierKey = modifiers.map((modifier) => [modifier.title, modifier.price]).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
			const key = JSON.stringify([
				row.item_code || "", row.selling_product || "", row.title || row.item_name || row.order_item_name,
				row.option_parent || "", row.uom || "", Number(row.price || 0), row.notes || "",
				row.item_tax_template || "", row.tax_category || "", row.warehouse || "", modifierKey,
			]);
			const group = groups.get(key);
			if (group) {
				group.quantity += quantity;
				group.lineTotal += unitPrice * quantity;
			} else {
				groups.set(key, { row, quantity, modifiers, unitPrice, lineTotal: unitPrice * quantity });
			}
		}
		const items = [...groups.values()];
		const itemCount = items.reduce((sum, item) => sum + item.quantity, 0);
		const rows = items.map(({ row, quantity, modifiers, unitPrice, lineTotal }) => {
			const modifierMarkup = modifiers.length
				? `<ul class="rms-payment-items-modifiers">${modifiers.map((modifier) => `<li>${this.escape(modifier.title)}${modifier.price ? ` · ${this.currency(modifier.price)}` : ""}</li>`).join("")}</ul>`
				: "";
			const noteMarkup = row.notes ? `<p class="rms-payment-items-note">${this.escape(row.notes)}</p>` : "";
			return `<article class="rms-payment-items-row"><div class="rms-payment-items-description"><div class="rms-payment-items-title-line"><h3>${this.escape(row.title || row.item_name || row.order_item_name)}</h3><span>${quantity}${row.uom ? ` ${this.escape(row.uom)}` : ""} × ${this.currency(unitPrice)}</span></div>${modifierMarkup}${noteMarkup}</div><strong>${this.currency(lineTotal)}</strong></article>`;
		}).join("");
		const totals = this.state.totals || {};
		return `<div class="rms-payment-items-backdrop" data-payment-items-backdrop><section id="rms-payment-items-dialog" class="rms-payment-items-dialog" role="dialog" aria-modal="true" aria-labelledby="rms-payment-items-title" tabindex="-1"><header class="rms-payment-items-header"><div><span class="rms-pos-eyebrow">${__("ORDER DETAILS")}</span><h2 id="rms-payment-items-title">${__("Order items")}</h2><p>${__("{0} items", [itemCount])}</p></div><button type="button" class="rms-screen-secondary" data-action="payment-close-items" aria-label="${__("Close")}">×</button></header><div class="rms-payment-items-dialog-body">${rows || `<p class="rms-payment-items-empty">${__("No order items to display.")}</p>`}</div><footer class="rms-payment-items-footer"><div><span>${__("Subtotal")}</span><b>${this.currency(totals.subtotal || 0)}</b></div>${Number(totals.discount_amount || 0) ? `<div><span>${__("Discount")}</span><b>− ${this.currency(totals.discount_amount)}</b></div>` : ""}<div><span>${__("Taxes")}</span><b>${this.currency(totals.tax_total || 0)}</b></div><div class="rms-payment-items-grand-total"><span>${__("Total")}</span><b>${this.currency(totals.grand_total ?? totals.total ?? 0)}</b></div></footer></section></div>`;
	}

	openPaymentItemsDialog() {
		const root = this.page.main[0].querySelector("[data-payment-items-dialog-root]");
		if (!root) return;
		root.innerHTML = this.renderPaymentItemsDialog();
		root.querySelector('[data-action="payment-close-items"]')?.focus();
	}

	closePaymentItemsDialog() {
		const root = this.page?.main?.[0]?.querySelector("[data-payment-items-dialog-root]");
		if (root) root.innerHTML = "";
		this.page?.main?.[0]?.querySelector('[data-action="payment-open-items"]')?.focus();
	}

	closePaymentDiscountDialog(preserveApproval = false) {
		const root = this.page?.main?.[0]?.querySelector("[data-discount-dialog-root]");
		if (root) root.innerHTML = "";
		if (!preserveApproval && !this.paymentDiscountApprovalCode) this.clearDiscountApprovalPrompt();
	}

	renderPaymentDiscountDialog() {
		const type = this.paymentDiscount.type;
		const value = Number(this.paymentDiscount.value || 0);
		const max = Number(this.activeGuestPayment?.grand_total || this.state.totals?.grand_total || 0);
		const activeGuestCheck = this.activeGuestPayment
			? this.guestCheckState?.guest_checks?.find((row) => row.name === this.activeGuestPayment.guest_check_name)
			: null;
		const currentDiscount = this.activeGuestPayment ? activeGuestCheck?.discount_amount || 0 : this.state.totals?.discount_amount || 0;
		const title = this.activeGuestPayment ? __("Discount for {0}", [this.activeGuestPayment.guest_name]) : __("Add Discount");
		const percentageTicks = [0, 10, 20, 30, 50, 80, 100].map((tick) => `<span style="left:${tick}%">${tick}%</span>`).join("");
		return `<div class="rms-discount-backdrop" data-action="payment-discount-backdrop"><section class="rms-discount-dialog" data-discount-dialog role="dialog" aria-modal="true" aria-labelledby="rms-discount-title" tabindex="-1"><header><h2 id="rms-discount-title">${title}</h2><button type="button" data-action="payment-discount-close" aria-label="${__("Close")}">×</button></header><div class="rms-discount-dialog-body"><div data-discount-edit-fields><div class="rms-discount-type-wrap"><span>${__("Discount type")}</span><input type="hidden" data-pay-discount-type value="${this.escape(type)}"><div class="rms-discount-type-switch" role="group" aria-label="${__("Discount type")}"><button type="button" data-action="payment-discount-type" data-type="Amount" aria-pressed="${type === "Amount"}">${__("Amount")}</button><button type="button" data-action="payment-discount-type" data-type="Percentage" aria-pressed="${type === "Percentage"}">${__("Percentage")}</button></div></div><div class="rms-discount-percentage" data-discount-range-wrap ${type === "Percentage" ? "" : "hidden"}><div class="rms-discount-value-heading"><span>${type === "Percentage" ? __("Discount %") : __("Discount amount")}</span><strong><b data-discount-percent-label>${type === "Percentage" ? value : 0}%</b></strong></div><input type="range" data-pay-discount-value="percentage" min="0" max="100" step="5" value="${type === "Percentage" ? value : 0}" aria-label="${__("Discount percentage")}"><div class="rms-discount-ticks" aria-hidden="true">${percentageTicks}</div></div><label class="rms-discount-amount-wrap" data-discount-amount-wrap ${type === "Amount" ? "" : "hidden"}>${__("Discount amount")}<span class="rms-discount-value-field"><input type="number" data-pay-discount-value="amount" min="0" max="${max}" step="0.01" value="${type === "Amount" ? value : 0}" aria-label="${__("Discount amount")}"><button type="button" data-action="payment-discount-clear" aria-label="${__("Clear discount amount")}">×</button></span></label><label class="rms-discount-reason">${__("Reason")}<input type="text" data-pay-discount-reason value="${this.escape(this.paymentDiscount.reason)}" placeholder="${__("Reason for discount")}"></label><div class="rms-discount-dialog-summary">${__("Discount")}: <b data-discount-preview>${this.currency(currentDiscount)}</b></div></div><div class="rms-discount-approval-feedback" data-discount-approval-feedback aria-live="polite"></div></div><footer><button type="button" class="rms-screen-secondary" data-action="payment-clear-discount" data-applied-discount="${currentDiscount}">${__("Clear")}</button><button type="button" class="rms-screen-secondary" data-action="payment-discount-close">${__("Cancel")}</button><button type="button" class="rms-screen-primary rms-discount-apply" data-action="payment-apply-discount" ${this.paymentDiscount.reason.trim() ? "" : "disabled"}>${__("Apply")}</button></footer></section></div>`;
	}

	async printOpenOrderCheck() {
		if (this.paymentSubmitting) return;
		const printWindow = window.open("about:blank", "_blank");
		if (!printWindow) return frappe.msgprint(__("Your browser blocked the print window. Allow pop-ups for this POS, then try again."));
		this.paymentSubmitting = true;
		const button = this.page.main.find('[data-action="payment-print-only"]');
		button.prop("disabled", true);
		try {
			const html = this.activeGuestPayment ? await this.call("get_guest_check_print_html", { order_name: this.state.order_name, guest_check_name: this.activeGuestPayment.guest_check_name }) : await this.call("get_open_order_check_print_html", { order_name: this.state.order_name });
			printWindow.document.open(); printWindow.document.write(html); printWindow.document.close();
			setTimeout(() => printWindow.print(), 400);
		} catch (error) {
			if (!printWindow.closed) printWindow.close();
			this.showError(error);
		} finally {
			this.paymentSubmitting = false;
			button.prop("disabled", false);
		}
	}

	toggleDiscountValueInput(type) {
		this.page.main.find("[data-discount-range-wrap]").prop("hidden", type !== "Percentage");
		this.page.main.find("[data-discount-amount-wrap]").prop("hidden", type !== "Amount");
		this.page.main[0].querySelectorAll('[data-action="payment-discount-type"]').forEach((button) => {
			button.setAttribute("aria-pressed", String(button.dataset.type === type));
		});
		if (this.paymentDiscountDraft) this.paymentDiscountDraft.type = type;
	}

	updateDiscountApplyState() {
		const button = this.page?.main?.[0]?.querySelector("[data-action='payment-apply-discount']");
		const type = this.page?.main?.[0]?.querySelector("[data-pay-discount-type]")?.value || "Percentage";
		const value = Number(this.page?.main?.[0]?.querySelector(`[data-pay-discount-value="${type === "Amount" ? "amount" : "percentage"}"]`)?.value || 0);
		const clearButton = this.page?.main?.[0]?.querySelector("[data-action='payment-clear-discount']");
		if (clearButton) clearButton.disabled = !(Number(clearButton.dataset.appliedDiscount || 0) > 0 || value > 0);
		if (!button || button.hidden) return;
		const codeInput = this.page.main[0].querySelector("[data-discount-approval-code]");
		button.disabled = codeInput ? !codeInput.value.trim()
			: value > 0 && !this.page.main[0].querySelector("[data-pay-discount-reason]")?.value.trim();
	}

	setPaymentDiscountType(type) {
		if (!["Percentage", "Amount"].includes(type)) return;
		this.paymentDiscount.type = type;
		this.page.main.find("[data-pay-discount-type]").val(type);
		this.clearDiscountApprovalPrompt();
		this.toggleDiscountValueInput(type);
	}

	clearDiscountApprovalPrompt() {
		this.paymentDiscountApprovalCode = null;
		this.paymentDiscountApprovalApprover = null;
		this.paymentDiscountApprovers = [];
		const feedback = this.page?.main?.[0]?.querySelector("[data-discount-approval-feedback]");
		if (feedback) { feedback.textContent = ""; feedback.innerHTML = ""; }
		const editFields = this.page?.main?.[0]?.querySelector("[data-discount-edit-fields]");
		if (editFields) editFields.hidden = false;
		const title = this.page?.main?.[0]?.querySelector("#rms-discount-title");
		if (title) title.textContent = __("Add Discount");
		const apply = this.page?.main?.[0]?.querySelector("[data-action='payment-apply-discount']");
		if (apply) { apply.textContent = __("Apply"); apply.hidden = false; }
		const clear = this.page?.main?.[0]?.querySelector("[data-action='payment-clear-discount']");
		if (clear) clear.hidden = false;
		this.updateDiscountApplyState();
	}

	selectDiscountApprover(approver) {
		this.paymentDiscountApprovalApprover = approver || null;
		this.paymentDiscountAuthMethod = "OTP";
		this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers || [], approver || "", "", "", "OTP");
		this.updateDiscountApplyState();
		this.page.main[0].querySelector("[data-discount-approval-code]")?.focus();
		if (approver) return this.requestDiscountApprovalCode();
	}

	async deliverApprovalCode(method, args, status, button, resend = false) {
		this.approvalDeliveries ||= new Map();
		const key = JSON.stringify([method,args]);
		let entry = this.approvalDeliveries.get(key);
		const render = () => {
			if (!entry?.sent || status?.isConnected === false) return;
			const wait = Math.max(0,Math.ceil((entry.resendAt-Date.now())/1000));
			const expired = Date.now() >= entry.expiresAt;
			const message = expired ? __("انتهت صلاحية الكود. يمكنك إعادة الإرسال.") : __("تم إرسال الكود للموافق.");
			if (status && status.textContent !== message) status.textContent = message;
			if (button) {
				button.hidden = false; button.disabled = wait > 0;
				button.textContent = wait ? __("إعادة الإرسال بعد {0} ثانية",[wait]) : __("إعادة إرسال الكود");
				clearTimeout(button.rmsResendTimer);
				if ((wait || !expired) && typeof setTimeout === "function") {
					button.rmsResendTimer = setTimeout(render,1000);
					button.rmsResendTimer?.unref?.();
				}
			}
		};
		if (entry?.sent && (!resend || Date.now() < entry.resendAt)) { render(); return; }
		if (!entry) { entry={}; this.approvalDeliveries.set(key,entry); }
		if (status) status.textContent = __("جارٍ إرسال الكود…");
		if (button) {button.disabled = true;clearTimeout(button.rmsResendTimer);}
		try {
			if (!entry.inflight) entry.inflight=this.call(method,{...args,...(resend ? {resend:1} : {})}).then(result=>{
				entry.sent=true;
				entry.expiresAt=Date.now()+Number(result.expires_in_seconds ?? (method==="request_shift_expense_approval_code" ? 180:300))*1000;
				entry.resendAt=Date.now()+Number(result.resend_after_seconds ?? 60)*1000;
				return result;
			}).finally(()=>{entry.inflight=null;});
			await entry.inflight;render();
		} catch(error) {
			if (status?.isConnected !== false && status) status.textContent=__("تعذر إرسال الكود. حاول مرة أخرى.");
			if (button) {clearTimeout(button.rmsResendTimer);button.hidden=false;button.disabled=false;button.textContent=__("إعادة المحاولة");}
			this.showError(error);
		}
	}

	async requestDiscountApprovalCode(resend = false) {
		if (!this.paymentDiscountApprovalApprover) return;
		const root=this.page.main[0], discount=this.paymentDiscountDraft || this.paymentDiscount;
		return this.deliverApprovalCode("request_pos_discount_approval_code",{
			order_name:this.state.order_name, approver:this.paymentDiscountApprovalApprover,
			discount_type:discount.type, discount_value:discount.value, discount_reason:discount.reason,
			guest_check_name:this.activeGuestPayment?.guest_check_name || null, expected_modified:this.orderModified || null,
		},root.querySelector('[data-discount-code-status]'),root.querySelector('[data-action="payment-discount-request-code"]'),resend===true);
	}

	setDiscountApprovalMethod(method) {
		if (!["OTP", "Password"].includes(method) || !this.paymentDiscountApprovalApprover) return;
		this.paymentDiscountAuthMethod = method;
		this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers || [], this.paymentDiscountApprovalApprover,
			"", "", method);
		this.page.main[0].querySelector("[data-discount-approval-code]")?.focus();
		if (method === "OTP") return this.requestDiscountApprovalCode();
	}

	clearPaymentDiscountValue() {
		const type = this.page.main.find("[data-pay-discount-type]").val() || "Percentage";
		const input = this.page.main[0].querySelector(`[data-pay-discount-value="${type === "Amount" ? "amount" : "percentage"}"]`);
		if (!input) return;
		input.value = "0";
		input.dispatchEvent(new Event("input", { bubbles: true }));
	}

	async clearAppliedPaymentDiscount() {
		const type = this.page.main.find("[data-pay-discount-type]").val() || "Percentage";
		const input = this.page.main[0].querySelector(`[data-pay-discount-value="${type === "Amount" ? "amount" : "percentage"}"]`);
		const reason = this.page.main[0].querySelector("[data-pay-discount-reason]");
		if (input) input.value = "0";
		if (reason) reason.value = "";
		this.paymentDiscountPreview = null;
		this.clearDiscountApprovalPrompt();
		await this.applyPaymentDiscount();
	}

	renderDiscountApprovalPrompt(approvers, selectedApprover = "", errorMessage = "", approvalCode = "", approvalMethod = this.paymentDiscountAuthMethod || "OTP") {
		const feedback = this.page.main[0].querySelector("[data-discount-approval-feedback]");
		if (!feedback) return;
		if (!approvers.length) {
			const title = this.page.main[0].querySelector("#rms-discount-title");
			if (title) title.textContent = __("Select Authorizer");
			const editFields = this.page.main[0].querySelector("[data-discount-edit-fields]");
			if (editFields) editFields.hidden = true;
			const applyButton = this.page.main[0].querySelector("[data-action='payment-apply-discount']");
			if (applyButton) applyButton.hidden = true;
			const clearButton = this.page.main[0].querySelector("[data-action='payment-clear-discount']");
			if (clearButton) clearButton.hidden = true;
			feedback.textContent = errorMessage || __("No POS Manager with access to this Store is available to approve the discount.");
			return;
		}
		const editFields = this.page.main[0].querySelector("[data-discount-edit-fields]");
		if (editFields) editFields.hidden = true;
		if (selectedApprover) {
			this.paymentDiscountAuthMethod = approvalMethod === "Password" ? "Password" : "OTP";
			const passwordMode = this.paymentDiscountAuthMethod === "Password";
			const title = this.page.main[0].querySelector("#rms-discount-title");
			if (title) title.textContent = __("Manager approval");
			const selected = approvers.find((row) => row.user === selectedApprover);
			feedback.innerHTML = `
				<div class="rms-discount-approval-flow">
					<div class="rms-discount-stepper"><span>1</span><i>›</i><b>2</b></div>
					<h3>${this.escape(__("Verify manager approval"))}</h3>
					<p class="rms-discount-selected-manager">${this.escape(selected?.full_name || selectedApprover)}</p>
					<div class="rms-discount-auth-switch" role="group" aria-label="${this.escape(__("Verification method"))}">
						<button type="button" data-action="payment-discount-auth-method" data-method="OTP" aria-pressed="${!passwordMode}">${this.escape(__("One-time code"))}</button>
						<button type="button" data-action="payment-discount-auth-method" data-method="Password" aria-pressed="${passwordMode}">${this.escape(__("Fixed password"))}</button>
					</div>
					<label class="rms-discount-approval-step">${this.escape(passwordMode ? __("Manager fixed password") : __("Manager approval code"))}
						<input type="password" class="${passwordMode ? "rms-manager-password" : "rms-manager-otp"}" data-discount-approval-code inputmode="${passwordMode ? "text" : "numeric"}" autocomplete="${passwordMode ? "off" : "one-time-code"}" ${passwordMode ? "" : 'maxlength="6"'} value="${this.escape(approvalCode)}" placeholder="${this.escape(passwordMode ? __("Enter manager fixed password") : __("Enter one-time code"))}">
					</label>
					${passwordMode ? `<p class="rms-discount-manager-note">${this.escape(__("Use the fixed approval password configured on this manager's POS User profile."))}</p>` : `<button type="button" class="btn btn-default" data-action="payment-discount-request-code" hidden>${this.escape(__("Retry sending code"))}</button><p class="rms-discount-manager-note" data-discount-code-status role="status"></p>`}
					<button type="button" class="rms-discount-back" data-action="payment-discount-back-to-managers">${this.escape(__("Choose another manager"))}</button>
					${errorMessage ? `<p class="rms-discount-error">${this.escape(errorMessage)}</p>` : ""}
				</div>`;
			const applyButton = this.page.main[0].querySelector("[data-action='payment-apply-discount']");
			if (applyButton) { applyButton.textContent = __("Verify and Apply"); applyButton.hidden = false; this.updateDiscountApplyState(); }
			const clearButton = this.page.main[0].querySelector("[data-action='payment-clear-discount']");
			if (clearButton) clearButton.hidden = true;
			return;
		}
		const options = approvers.map((row) => `<button type="button" class="rms-discount-approver" data-action="payment-discount-approver" data-approver="${this.escape(row.user)}">${this.escape(row.full_name)}<small>${this.escape(row.user)}</small></button>`).join("");
		const title = this.page.main[0].querySelector("#rms-discount-title");
		if (title) title.textContent = __("Select Authorizer");
		feedback.innerHTML = `<div class="rms-discount-approval-flow"><div class="rms-discount-stepper"><b>1</b><i>›</i><span>2</span></div><h3>${this.escape(__("Select Authorizer"))}</h3><p>${this.escape(__("Select a manager to approve this discount."))}</p><div class="rms-discount-approver-list">${options}</div>${errorMessage ? `<p class="rms-discount-error">${this.escape(errorMessage)}</p>` : ""}</div>`;
		const applyButton = this.page.main[0].querySelector("[data-action='payment-apply-discount']");
		if (applyButton) { applyButton.textContent = __("Apply"); applyButton.hidden = true; }
		const clearButton = this.page.main[0].querySelector("[data-action='payment-clear-discount']");
		if (clearButton) clearButton.hidden = true;
	}

	queuePaymentDiscountPreview(showApprovalPrompt = false) {
		if (!this.page.main[0].querySelector('[data-screen="payment"]:not([hidden])')) return;
		clearTimeout(this.discountPreviewTimer);
		const requestId = this.discountPreviewRequestId = (this.discountPreviewRequestId || 0) + 1;
		this.discountPreviewTimer = setTimeout(() => this.refreshPaymentDiscountPreview(requestId, "", showApprovalPrompt), 250);
	}

	async refreshPaymentDiscountPreview(requestId = this.discountPreviewRequestId, approvalCode = "", showApprovalPrompt = true) {
		if (requestId !== this.discountPreviewRequestId) return;
		const type = this.page.main.find("[data-pay-discount-type]").val() || "Percentage";
		const input = this.page.main.find(`[data-pay-discount-value="${type === "Amount" ? "amount" : "percentage"}"]`);
		const value = Number(input.val() || 0);
		const reason = this.page.main.find("[data-pay-discount-reason]").val() || "";
		this.paymentDiscountDraft = { type, value, reason };
		const invoiceTotal = Number(this.activeGuestPayment?.grand_total || this.state.totals?.grand_total || 0);
		const feedback = this.page.main[0].querySelector("[data-discount-approval-feedback]");
		if (value < 0 || (type === "Percentage" && value > 100) || (type === "Amount" && value > invoiceTotal)) {
			feedback.textContent = type === "Amount" && value > invoiceTotal
				? __("Discount amount cannot exceed the invoice total.")
				: __("Enter a valid discount value.");
			const previewTarget = this.page.main[0].querySelector("[data-discount-dialog] [data-discount-preview]");
			if (previewTarget) previewTarget.textContent = "—";
			this.paymentDiscountPreview = null;
			return;
		}
		const approvalApprover = this.paymentDiscountApprovalApprover || "";
		if (type === "Percentage") this.page.main.find("[data-discount-percent-label]").text(`${value}%`);
		try {
			const preview = await this.call("preview_order_discount", { order_name: this.state.order_name, discount_type: type, discount_value: value, discount_reason: reason, approval_code: approvalCode || null, approval_approver: approvalApprover || null, approval_method: this.paymentDiscountAuthMethod || "OTP", guest_check_name: this.activeGuestPayment?.guest_check_name || null });
			if (requestId !== this.discountPreviewRequestId) return;
			const previewTarget = this.page.main[0].querySelector("[data-discount-dialog] [data-discount-preview]");
			if (previewTarget) previewTarget.textContent = this.currency(preview.discount_amount);
			this.paymentDiscountPreview = preview;
			if (preview.requires_manager_approval && !preview.approved_by) {
				this.paymentDiscountApprovers = preview.approvers || [];
				this.paymentDiscountApprovalApprover = approvalApprover || null;
				if (showApprovalPrompt) {
					this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers, approvalApprover);
					this.paymentDiscountPreview = null;
				}
				return;
			}
			if (preview.approved_by) {
				this.paymentDiscountApprovalCode = preview.approval_token || approvalCode;
				this.paymentDiscountApprovalApprover = preview.approved_by;
				if (this.paymentDiscountAuthMethod === "Password") {
					const passwordInput = this.page.main[0].querySelector("[data-discount-approval-code]");
					if (passwordInput) passwordInput.value = "";
				}
				feedback.textContent = __("Approved by {0}. The code will be consumed when payment is recorded.", [preview.approved_by]);
			} else {
				this.paymentDiscountApprovalCode = null;
				feedback.textContent = "";
				feedback.innerHTML = "";
				this.paymentDiscountApprovers = [];
				this.paymentDiscountApprovalApprover = null;
			}
		} catch (error) {
			if (requestId !== this.discountPreviewRequestId) return;
			const message = String(error?.responseJSON?._server_messages || error?.responseJSON?.message || error?.message || "");
			const feedback = this.page.main[0].querySelector("[data-discount-approval-feedback]");
			const cleanMessage = message.replace(/[\\[\\]\\\"]+/g, " ").trim() || __("The discount could not be applied. Check the discount details and try again.");
			if (this.paymentDiscountApprovers?.length && approvalApprover) {
				this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers, approvalApprover, cleanMessage, approvalCode);
			} else feedback.textContent = cleanMessage;
			this.paymentDiscountPreview = null;
		}
	}

	async applyPaymentDiscount() {
		clearTimeout(this.discountPreviewTimer);
		const requestId = this.discountPreviewRequestId = (this.discountPreviewRequestId || 0) + 1;
		const approvalCode = this.page.main[0].querySelector("[data-discount-approval-code]")?.value.trim() || "";
		const reason = this.page.main[0].querySelector("[data-pay-discount-reason]")?.value.trim() || "";
		const type = this.page.main.find("[data-pay-discount-type]").val() || "Percentage";
		const value = Number(this.page.main[0].querySelector(`[data-pay-discount-value="${type === "Amount" ? "amount" : "percentage"}"]`)?.value || 0);
		if (value > 0 && !reason) {
			const feedback = this.page.main[0].querySelector("[data-discount-approval-feedback]");
			if (feedback) feedback.textContent = __("Enter a reason for the discount.");
			return;
		}
		this.paymentDiscountPreview = null;
		await this.refreshPaymentDiscountPreview(requestId, approvalCode, true);
		if (!this.paymentDiscountPreview || requestId !== this.discountPreviewRequestId) return;
		this.paymentDiscount = this.paymentDiscountDraft || this.paymentDiscount;
		this.paymentSourceTotal = Number(this.paymentDiscountPreview.grand_total || 0);
		this.paymentTotal = this.roundPosPayable(this.paymentSourceTotal);
		this.updateSuggestedPaymentAmounts();
		if (this.activeGuestPayment) {
			this.activeGuestPayment.grand_total = this.paymentTotal;
			this.activeGuestPayment.source_total = this.paymentSourceTotal;
			const activeCheck = this.guestCheckState?.guest_checks?.find((row) => row.name === this.activeGuestPayment.guest_check_name);
			if (activeCheck) Object.assign(activeCheck, {
				discount_type: this.paymentDiscount.type,
				discount_value: this.paymentDiscount.value,
				discount_reason: this.paymentDiscount.reason,
				discount_amount: Number(this.paymentDiscountPreview.discount_amount || 0),
				grand_total: this.paymentSourceTotal,
			});
		}
		const appliedDiscountLabel = this.page.main[0].querySelector(".rms-payment-discount-launch [data-discount-preview]");
		if (appliedDiscountLabel) appliedDiscountLabel.textContent = this.currency(this.paymentDiscountPreview.discount_amount);
		this.page.main.find(".rms-payment-total").text(this.currency(this.paymentTotal));
		const split = this.page.main[0].querySelector("[data-split-check-toggle]")?.checked;
		if (split) {
			this.page.main[0].querySelectorAll("[data-guest-amount]").forEach((input) => { input.dataset.manual = ""; });
			this.updateGuestSplitAmounts();
		} else {
			const amounts = [...this.page.main[0].querySelectorAll("[data-payment-amount]")];
			if (amounts.length && amounts.slice(1).every((row) => Number(row.value || 0) === 0)) amounts[0].value = this.paymentTotal.toFixed(2);
			this.updatePaymentTotal();
		}
		this.closePaymentDiscountDialog(true);
	}

	async handleSplitCheckToggle(input) {
		const enabled = input.checked;
		if (!enabled && this.guestCheckState?.order_name === this.state.order_name) {
			if (this.paymentGuests?.some((guest) => guest.paid)) { input.checked = true; return frappe.msgprint(__("Guest checks cannot be changed after one has been paid.")); }
			try { await this.call("clear_guest_check_allocations", { order_name: this.state.order_name }); this.guestCheckState = null; }
			catch (error) { input.checked = true; return this.showError(error); }
		}
		this.toggleSplitCheck(enabled);
	}

	toggleSplitCheck(enabled) {
		this.page.main.find(".rms-payment-method-list, .rms-payment-shortcuts").prop("hidden", enabled);
		this.page.main.find("[data-guest-checks]").prop("hidden", !enabled);
		const total = Number(this.paymentTotal ?? this.state.totals?.grand_total ?? 0);
		if (enabled) {
			this.renderPaymentItemAssignments();
			this.updateGuestSplitAmounts();
		} else {
			const methods = this.page.main[0].querySelectorAll("[data-payment-amount]");
			if (methods.length) { methods[0].value = total.toFixed(2); methods.forEach((input, index) => { if (index) input.value = "0.00"; }); }
		}
		this.paymentInput = this.page.main[0].querySelector(enabled ? "[data-guest-amount]" : "[data-payment-amount]");
		this.updatePaymentTotal();
	}

	async submitPayment(print = false) {
		if (this.paymentSubmitting) return;
		this.paymentSubmitting = true;
		const orderActive = await this.ensureCurrentOrderActive();
		this.paymentSubmitting = false;
		if (!orderActive) return;
		const activeGuestPayment = this.activeGuestPayment;
		const isSplit = !activeGuestPayment && Boolean(this.page.main[0].querySelector("[data-split-check-toggle]")?.checked);
		if (isSplit && !this.guestSplitFinalized) return frappe.msgprint(__("Confirm the split before taking payment."));
		const splitMode = this.paymentSplitMode || "amount";
		if (isSplit && this.page.main[0].querySelector("[data-split-balance]")?.dataset.valid !== "true") {
			return frappe.msgprint(this.page.main[0].querySelector("[data-split-balance]")?.textContent || __("Complete the split before payment."));
		}
		const guestRows = isSplit ? [...this.page.main[0].querySelectorAll(".rms-guest-check")].map((section, index) => ({
			guest: section.querySelector("[data-guest-name]").value.trim(),
			mode_of_payment: section.querySelector("[data-guest-method]").value,
			amount: Number(section.querySelector("[data-guest-amount]").value || 0),
			due_amount: Number(section.querySelector("[data-guest-share]")?.value || 0),
			items: [],
			split_mode: splitMode,
		})) : [];
		const payments = isSplit ? guestRows.map(({ mode_of_payment, amount }) => ({ mode_of_payment, amount })) : [...this.page.main[0].querySelectorAll("[data-payment-amount]")].map((input) => ({ mode_of_payment: input.dataset.method, amount: Number(input.value || 0) })).filter((row) => row.amount > 0);
		const total = Number(this.paymentTotal ?? this.state.totals?.grand_total ?? 0);
		if (!activeGuestPayment && this.paymentDiscount?.value > 0 && !this.paymentDiscount.reason.trim()) return frappe.msgprint(__("Enter a reason for the discount."));
		const tendered = payments.reduce((sum, row) => sum + row.amount, 0);
		if (tendered + 0.01 < total) return frappe.msgprint(__("Payment amounts must cover the order total."));
		const printWindow = print ? window.open("about:blank", "_blank") : null;
		if (print && !printWindow) return frappe.msgprint(__("Your browser blocked the print window. Allow pop-ups for this POS, then try again."));
		this.paymentSubmitting = true;
		const paymentButtons = this.page.main.find('[data-action="payment-pay"], [data-action="payment-pay-print"]');
		paymentButtons.prop("disabled", true);
		let paymentRecorded = false;
		try {
			const result = activeGuestPayment
				? await this.call("pay_guest_check", { order_name: this.state.order_name, guest_check_name: activeGuestPayment.guest_check_name, payments: JSON.stringify(payments), discount_type: this.paymentDiscount?.type || "Percentage", discount_value: this.paymentDiscount?.value || 0, discount_reason: this.paymentDiscount?.reason || "", discount_approval_code: this.paymentDiscountApprovalCode || null, discount_approval_approver: this.paymentDiscountApprovalApprover || null })
				: await this.call("pay_order", { order_name: this.state.order_name, payments: JSON.stringify(payments), guest_breakdown: isSplit ? JSON.stringify(guestRows) : null, discount_type: this.paymentDiscount?.type || "Percentage", discount_value: this.paymentDiscount?.value || 0, discount_reason: this.paymentDiscount?.reason || "", discount_approval_code: this.paymentDiscountApprovalCode || null, discount_approval_approver: this.paymentDiscountApprovalApprover || null });
			paymentRecorded = true;
			if (activeGuestPayment) {
				if (result.guest_checks?.length) this.guestCheckState = { order_name: this.state.order_name, guest_checks: result.guest_checks };
				if (this.state.totals && result.order_grand_total !== undefined) this.state.totals.grand_total = Number(result.order_grand_total || 0);
				if (this.state.totals && result.order_discount_amount !== undefined) this.state.totals.discount_amount = Number(result.order_discount_amount || 0);
				const check = this.guestCheckState?.guest_checks.find((row) => row.name === activeGuestPayment.guest_check_name);
				if (check) { check.status = "Paid"; check.pos_invoice = result.pos_invoice; }
				const guest = this.paymentGuests?.[activeGuestPayment.index];
				if (guest) guest.paid = true;
			}
			if (print) {
				try {
					const html = await this.call("get_pos_invoice_print_html", { order_name: this.state.order_name, ...(activeGuestPayment ? { invoice_name: result.pos_invoice } : {}) });
					printWindow.document.open(); printWindow.document.write(html); printWindow.document.close();
					setTimeout(() => printWindow.print(), 500);
				} catch (error) {
					printWindow.close();
					frappe.msgprint({ title: __("Payment recorded; print unavailable"), message: __("The payment was recorded as {0}, but the receipt could not be prepared. Reprint it from Sales History.", [result.pos_invoice]), indicator: "orange" });
				}
			}
			if (activeGuestPayment && result.status !== "Paid") {
				this.activeGuestPayment = null;
				this.showPaymentScreen();
				return;
			}
			this.state.order_status = "Paid"; this.state.last_invoice = result.pos_invoice;
			if (activeGuestPayment) this.guestCheckState = null;
			this.page.main.find("[data-screen]").prop("hidden", true);
			this.page.main.find(".rms-pos-shell").prop("hidden", false);
			this.onAction("new-sale");
		} catch (error) { if (printWindow && !printWindow.closed) printWindow.close(); this.showError(error); }
		finally {
			this.paymentSubmitting = false;
			if (!paymentRecorded) paymentButtons.prop("disabled", false);
		}
	}

	async ensureGuestChecks() {
		if (this.guestCheckState?.order_name === this.state.order_name) return this.guestCheckState.guest_checks;
		const guest_checks = [...this.page.main[0].querySelectorAll(".rms-guest-check")].map((card, index) => ({
			guest_name: (card.querySelector("[data-guest-name]").value || __("Guest {0}", [index + 1])).trim(),
			items: Object.entries(this.paymentItemAssignments || {}).flatMap(([itemName, allocation]) => Number(allocation?.[index] || 0) > 0 ? [{ name: itemName, qty: Number(allocation[index]) }] : []),
		}));
		const result = await this.call("save_guest_check_allocations", { order_name: this.state.order_name, guest_checks: JSON.stringify(guest_checks) });
		this.guestCheckState = { order_name: this.state.order_name, guest_checks: result.guest_checks };
		return result.guest_checks;
	}

	async showSalesHistory() {
		if (!this.state.store) return frappe.msgprint(__("Select a Store to view sales history."));
		try {
			const sales = await this.call("get_pos_sales_history", { store: this.state.store });
			const rows = sales.map((sale) => `<tr><td><b>${this.escape(sale.pos_invoice)}</b><small>${this.escape(sale.name)} · ${this.escape(sale.guest_name || sale.order_type || "")}${sale.dining_table ? ` · ${this.escape(sale.dining_table)}` : ""}</small></td><td>${this.currency(sale.grand_total)}</td><td>${this.escape(__(sale.invoice_status || "Paid"))}</td><td>${this.state.permissions.can_reprint_receipts ? `<button type="button" class="btn btn-default btn-xs" data-reprint-order="${this.escape(sale.name)}" data-reprint-invoice="${this.escape(sale.pos_invoice)}">${__("Reprint")}</button>` : ""}</td></tr>`).join("");
			const html = rows ? `<div class="rms-pos-sales-history"><table class="table table-bordered"><thead><tr><th>${__("Invoice")}</th><th>${__("Total")}</th><th>${__("Status")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p>${__("No paid invoices are available in this Store for your account.")}</p>`;
			const dialog = new frappe.ui.Dialog({ title: __("Closed Sales and Reprints"), size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "sales_history", options: html }],
				primary_action_label: __("Close"), primary_action: () => dialog.hide() });
			dialog.show();
			dialog.$wrapper.on("click", "[data-reprint-order]", async (event) => {
				const printWindow = window.open("about:blank", "_blank");
				if (!printWindow) return frappe.msgprint(__("Allow pop-ups to open the receipt for reprinting."));
				try {
					const html = await this.call("get_pos_invoice_print_html", { order_name: event.currentTarget.dataset.reprintOrder, invoice_name: event.currentTarget.dataset.reprintInvoice });
					printWindow.document.open(); printWindow.document.write(html); printWindow.document.close();
					setTimeout(() => printWindow.print(), 700);
				} catch (error) { printWindow.close(); this.showError(error); }
			});
		} catch (error) { this.showError(error); }
	}

	async showOpenOrderOverview(orderName) {
		const order = await this.call("get_open_order_overview", { order_name: orderName });
		const lines = (order.items || []).map((row) => `<li>${this.escape(row.title)} × ${this.escape(row.qty)} ${this.escape(row.uom || "")} <b>${this.currency(row.amount)}</b>${(row.modifiers || []).map((modifier) => `<small>+ ${this.escape(modifier.title || modifier.modifier_product)}</small>`).join("")}</li>`).join("");
		const html = `<div class="rms-pos-open-order-overview"><p>${this.escape(order.status)} · ${this.escape(order.cashier || "")} · ${this.escape(order.check_label || order.dining_table || order.order_type || "")}</p><ul>${lines}</ul><hr><p>${__("Subtotal")}: ${this.currency(order.subtotal)}</p><p>${__("Discount")}: − ${this.currency(order.discount_amount)}</p><p>${__("Taxes")}: ${this.currency(order.tax_total)}</p><h3>${__("Total")}: ${this.currency(order.grand_total)}</h3></div>`;
		const dialog = new frappe.ui.Dialog({ title: `${__("View order")}: ${this.escape(this.orderNumber(order.name))}`, size: "large", fields: [{ fieldtype: "HTML", fieldname: "overview", options: html }], primary_action_label: __("Close"), primary_action: () => dialog.hide() });
		dialog.show();
	}

	async showTableMap() {
		if (!this.state.store) return frappe.msgprint(__("Select a Store to view table availability."));
		try {
			this.tableMapRows = await this.call("get_tables", { store: this.state.store });
			this.page.main.find(".rms-pos-shell").prop("hidden", true);
			this.page.main.find('[data-screen="tables"]').prop("hidden", false);
			this.renderTableMap();
			return;

		} catch (error) { this.showError(error); }
	}

	renderTableMap() {
		const root = this.page.main.find('[data-screen="tables"]');
		const rows = this.tableMapRows || [];
		const area = root.find("[data-table-area-filter]").val() || "";
		const status = root.find("[data-table-status-filter]").val() || "All";
		const query = (root.find("[data-table-search]").val() || "").toLowerCase();
		const visible = rows.filter((row) => {
			const occupied = Boolean(row.occupied);
			return (!area || row.dining_area === area) && (status === "All" || (status === "Occupied" ? occupied : !occupied))
				&& `${row.title} ${row.dining_area_title || ""} ${row.name}`.toLowerCase().includes(query);
		});
		const cards = visible.map((row) => {
			const orders = row.open_orders || [];
			const occupied = Boolean(row.occupied);
			const current = orders.some((order) => order.order === this.state.order_name);
			const orderActions = orders.filter((order) => order.order !== this.state.order_name).map((order) => {
				const ownSession = order.cashier_session === this.state.session?.name && this.state.session?.status === "Open" && this.state.permissions.can_checkout;
				const canEdit = this.state.session?.status === "Open" && this.state.permissions.can_checkout
					&& (ownSession || this.state.permissions.can_edit_open_orders);
				return canEdit
					? `<button type="button" class="rms-table-order-action" data-action="table-order" data-order="${this.escape(order.order)}">${ownSession ? __("Open order") : __("Open to add items")} · ${this.escape(order.check_label || this.orderNumber(order.order))}</button>`
					: `<button type="button" class="rms-table-order-action" data-action="table-view-order" data-order="${this.escape(order.order)}">${__("View details")} · ${this.escape(order.check_label || this.orderNumber(order.order))}</button>`;
			}).join("");
			const canSelect = !occupied && !this.state.order_name && this.state.session?.status === "Open" && this.state.permissions.can_checkout;
			const action = canSelect
				? `<button type="button" class="rms-screen-primary" data-action="table-choice" data-table="${this.escape(row.name)}" data-area="${this.escape(row.dining_area)}">${__("Start Dine In order")}</button>`
				: !this.state.session || !this.state.permissions.can_checkout
					? `<button type="button" class="rms-screen-secondary" disabled>${__("Cashier session required")}</button>`
					: occupied ? `<button type="button" class="rms-screen-secondary" disabled>${__("Busy")}</button>` : "";
			return `<article class="rms-table-tile ${occupied ? "is-busy" : "is-available"}"><div class="rms-table-tile-top"><span class="rms-table-icon" aria-hidden="true"><i></i><i></i><i></i></span><span class="rms-table-status">${occupied ? __("Busy") : __("Available")}</span></div><h2>${this.escape(row.title)}</h2><p>${this.escape(row.dining_area_title || row.dining_area)}${row.capacity ? ` · ${this.escape(row.capacity)} ${__("seats")}` : ""}</p>${current ? `<strong class="rms-table-current">${__("Current order")}</strong>` : ""}${orderActions ? `<div class="rms-table-order-actions">${orderActions}</div>` : ""}${action}</article>`;
		}).join("");
		const areas = this.state.areas || [];
		const counts = { available: visible.filter((row) => !row.occupied).length, occupied: visible.filter((row) => row.occupied).length };
		root.html(`<header class="rms-workspace-head"><button class="rms-screen-back" data-action="screen-back">‹ ${__("Back to register")}</button><div><span class="rms-pos-eyebrow">${__("DINING ROOM")}</span><h1>${__("Tables")}</h1><p>${__("Check table availability and open active checks without leaving the POS.")}</p></div><button class="rms-screen-secondary" data-action="refresh-tables">${__("Refresh")}</button></header><div class="rms-table-toolbar"><label>${__("Station / area")}<select data-table-area-filter><option value="">${__("All areas")}</option>${areas.map((row) => `<option value="${this.escape(row.name)}" ${row.name === area ? "selected" : ""}>${this.escape(row.title || row.name)}</option>`).join("")}</select></label><label>${__("Availability")}<select data-table-status-filter><option value="All" ${status === "All" ? "selected" : ""}>${__("All tables")}</option><option value="Available" ${status === "Available" ? "selected" : ""}>${__("Available")}</option><option value="Occupied" ${status === "Occupied" ? "selected" : ""}>${__("Busy")}</option></select></label><label class="rms-table-search">${__("Find a table")}<input type="search" data-table-search placeholder="${__("Table name or station")}" value="${this.escape(root.find("[data-table-search]").val() || "")}"></label><span class="rms-table-count">${counts.available} ${__("available")} · ${counts.occupied} ${__("busy")}</span></div><div class="rms-table-tiles">${cards || `<div class="rms-screen-empty">${__("No tables match these filters.")}</div>`}</div>`);
	}

	mapOrderItems(order) {
		return (order.items || []).map((row) => ({ local_id: row.name, selling_product: row.selling_product, option_parent: row.option_parent, sent_to_kitchen: Boolean(row.sent_to_kitchen),
			saved_to_order: true, order_item_name: row.name, read_only: this.state.cross_session_edit,
				title: row.title || row.selling_product, qty: row.qty, cancelled_qty: Number(row.cancelled_qty) || 0, price: row.selling_price, notes: row.notes || "",
			uom: row.uom, must_be_whole_number: Boolean(row.must_be_whole_number),
			modifiers: (row.modifiers || []).map((modifier) => ({ modifier_group: modifier.modifier_group, modifier_product: modifier.modifier_product, qty: modifier.qty })),
			modifier_labels: (row.modifiers || []).map((modifier) => ({ title: modifier.title || modifier.modifier_product, price: modifier.selling_price })) }));
	}

	async loadOrder(order, { deferMenu = false } = {}) {
		this.cartTab = null; this.cartPendingCount = 0;
		this.currentOrderScreen = "sale";
		this.state.order_name = order.name; this.state.order_status = order.status; this.state.brand = order.restaurant_brand; this.state.order_type = order.order_type;
		this.state.cross_session_edit = Boolean(order.cashier_session && order.cashier_session !== this.state.session?.name);
		this.state.category = null; this.state.search = "";
		this.state.customer = order.customer; this.state.dining_area = order.dining_area; this.state.dining_table = order.dining_table;
		this.state.order_notes = order.order_notes || "";
		this.state.external_reference = order.external_reference;
		this.state.discount_type = order.discount_type || "Percentage"; this.state.discount_scope = order.discount_scope || "Net Total";
		this.state.discount_value = Number(order.discount_value) || 0; this.state.discount_reason = order.discount_reason || "";
		this.state.cart = this.mapOrderItems(order);
		this.rememberOrderSnapshot(order);
		this.state.totals = { subtotal: order.subtotal, discount_amount: order.discount_amount, tax_total: order.tax_total, grand_total: order.grand_total };
		const checksPromise = this.call("get_guest_checks", { order_name: order.name }).then(checks => {
			this.guestCheckState = checks.guest_checks?.length ? { order_name: order.name, guest_checks: checks.guest_checks } : null;
		}).catch(() => { this.guestCheckState = null; });
		if (deferMenu) {
			await checksPromise;
		} else {
			const [categories, tables, products] = await Promise.all([
				this.call("get_categories", { brand: this.state.brand, store: this.state.store }),
				this.call("get_tables", { store: this.state.store, dining_area: this.state.dining_area }),
				this.loadCatalog(),
				checksPromise,
			]);
			Object.assign(this.state, {categories, tables, products});
		}
		this.render(); this.renderCart();
	}

	cancelConfirmedItem(index) {
		const row = this.state.cart[index];
		if (row?.order_item_name) return this.cancelConfirmedItems([row.order_item_name]);
	}

	async cancelConfirmedItems(initialSelection = []) {
		const orderName = this.state.order_name, revision = this.saleRevision || 0;
		if (!orderName || !await this.ensureCurrentOrderActive()) return;
		try {
			await this.flushDraftSave();
			if (orderName !== this.state.order_name || revision !== (this.saleRevision || 0)) return;
			const options = await this.call("get_order_item_cancellation_options", { order_name: orderName });
			if (orderName !== this.state.order_name || revision !== (this.saleRevision || 0)) return;
			if (!options.items.length) return frappe.msgprint(__("There are no confirmed quantities available to void."));
			const selected = new Set(initialSelection);
			let submitting = false;
			const defaultReason = options.reasons.length === 1 ? options.reasons[0].name : "";
			const html = `<div class="rms-cancel-toolbar"><span data-cancel-count aria-live="polite"></span><button type="button" data-cancel-select-all>${__("Select all")}</button></div>
				<div class="rms-cancel-items">${options.items.map((row, index) => `<div class="rms-cancel-item"><label><input type="checkbox" data-cancel-select="${index}" ${selected.has(row.name) ? "checked" : ""}><span><strong>${this.escape(row.title)}</strong><small>${__("Available")}: ${row.remaining_qty}</small></span></label><div class="rms-cancel-stepper"><button type="button" data-cancel-adjust="-1" data-cancel-index="${index}" aria-label="${__("Decrease void quantity")}">−</button><input type="number" data-cancel-qty="${index}" min="0" max="${row.remaining_qty}" step="${row.must_be_whole_number ? 1 : "0.001"}" value="${selected.has(row.name) ? row.remaining_qty : 0}" aria-label="${__("Void quantity")}"><button type="button" data-cancel-adjust="1" data-cancel-index="${index}" aria-label="${__("Increase void quantity")}">+</button></div></div>`).join("")}</div>
				<div class="rms-cancel-options"><b>${__("Void reason")}</b><div class="rms-cancel-reasons" role="group" aria-label="${__("Void reason")}">${options.reasons.map(row => `<button type="button" data-cancel-reason="${this.escape(row.name)}" aria-pressed="${row.name === defaultReason}">${this.escape(row.reason)}</button>`).join("") || `<p>${__("Configure an enabled cancellation reason before continuing.")}</p>`}</div>
				<label class="rms-cancel-comment">${__("Comment")}<textarea data-cancel-comment maxlength="1000" rows="2" placeholder="${__("Optional comment")}"></textarea></label><label class="rms-pos-waste-toggle"><input type="checkbox" data-cancel-waste><span>${__("Waste")}</span></label><p class="rms-cancel-error" data-cancel-error role="alert" hidden></p></div>`;
			const dialog = new frappe.ui.Dialog({ title: __("Void items"), size: "large", fields: [
				{ fieldtype: "HTML", fieldname: "items_html", options: html },
				{ fieldtype: "Data", fieldname: "action_reason", hidden: 1, default: defaultReason },
			], primary_action_label: __("Void selected items"), primary_action: async () => {
				if (submitting) return;
				if (orderName !== this.state.order_name || revision !== (this.saleRevision || 0)) { dialog.hide(); return; }
				const items = [];
				let invalid = false;
				dialog.$wrapper[0].querySelectorAll("[data-cancel-select]:checked").forEach(check => {
					const index = Number(check.dataset.cancelSelect), row = options.items[index];
					const qty = Number(dialog.$wrapper[0].querySelector(`[data-cancel-qty="${index}"]`).value);
					if (!Number.isFinite(qty) || qty <= 0 || qty > row.remaining_qty || (row.must_be_whole_number && !Number.isInteger(qty))) invalid = true;
					items.push({ item_name: row.name, qty });
				});
				const reason = dialog.get_value("action_reason");
				const showValidation = message => dialog.$wrapper.find("[data-cancel-error]").text(message).prop("hidden", false);
				if (invalid || !items.length) return showValidation(__("Choose quantities to void using + and −."));
				if (!options.reasons.some(row => row.name === reason)) return showValidation(__("Choose a void reason."));
				submitting = true;
				dialog.disable_primary_action();
				try {
					const args = {order_name: orderName, items: JSON.stringify(items), action_reason: reason, expected_modified: options.modified,
						is_waste: dialog.$wrapper[0].querySelector("[data-cancel-waste]").checked ? 1 : 0, comment: dialog.$wrapper.find("[data-cancel-comment]").val() || ""};
					const result = await this.completeAuthorizedOperation("cancel_confirmed_order_items", args, dialog);
					if (!result) { submitting = false; update(); return; }
					if (orderName === this.state.order_name && revision === (this.saleRevision || 0)) {
						for (const cancelled of result.items) {
							const row = this.state.cart.find(row => row.order_item_name === cancelled.name);
							if (row) row.cancelled_qty = Number(cancelled.cancelled_qty);
						}
						this.state.order_status = result.status;
						this.state.totals = { ...this.state.totals, ...result };
						this.orderModified = result.modified; this.watchCurrentOrder(); this.renderCart();
						if (result.status !== "Cancelled") await this.syncCurrentOrder(null, true);
					}
					dialog.hide(); frappe.show_alert({ message: __("Selected items voided"), indicator: "orange" });
				} catch (error) { submitting = false; update(); this.showError(error); }
			} });
			dialog.$wrapper.addClass("rms-pos-batch-cancel-dialog");
			const update = () => {
				const checks = [...dialog.$wrapper[0].querySelectorAll("[data-cancel-select]")];
				const count = checks.filter(check => check.checked).length;
				for (const check of checks) {
					const index = Number(check.dataset.cancelSelect), row = options.items[index];
					const input = dialog.$wrapper[0].querySelector(`[data-cancel-qty="${index}"]`);
					const item = check.closest(".rms-cancel-item");
					item.classList.toggle("is-selected", check.checked);
					item.querySelector('[data-cancel-adjust="-1"]').disabled = Number(input.value) <= 0;
					item.querySelector('[data-cancel-adjust="1"]').disabled = Number(input.value) >= row.remaining_qty;
				}
				dialog.$wrapper.find("[data-cancel-count]").text(__("{0} items selected", [count]));
				dialog.$wrapper.find("[data-cancel-select-all]").text(count === checks.length ? __("Clear selection") : __("Select all"));
				dialog.$wrapper.find("[data-cancel-error]").prop("hidden", true);
				if (!submitting && count && dialog.get_value("action_reason")) dialog.enable_primary_action(); else dialog.disable_primary_action();
			};
			const setQuantity = (index, value) => {
				const row = options.items[index];
				let qty = Number(value);
				if (!Number.isFinite(qty)) qty = 0;
				qty = Math.max(0, Math.min(row.remaining_qty, row.must_be_whole_number ? Math.round(qty) : Math.round(qty * 1000) / 1000));
				dialog.$wrapper[0].querySelector(`[data-cancel-qty="${index}"]`).value = qty;
				dialog.$wrapper[0].querySelector(`[data-cancel-select="${index}"]`).checked = qty > 0;
			};
			dialog.$wrapper.on("change", "[data-cancel-select]", event => {
				const index = Number(event.target.dataset.cancelSelect);
				setQuantity(index, event.target.checked ? Math.min(1, options.items[index].remaining_qty) : 0); update();
			});
			dialog.$wrapper.on("change", "[data-cancel-qty]", event => { setQuantity(Number(event.target.dataset.cancelQty), event.target.value); update(); });
			dialog.$wrapper.on("click", "[data-cancel-adjust]", event => {
				const button = event.currentTarget, index = Number(button.dataset.cancelIndex), row = options.items[index];
				const current = Number(dialog.$wrapper[0].querySelector(`[data-cancel-qty="${index}"]`).value);
				const step = row.must_be_whole_number ? 1 : Math.min(1, row.remaining_qty);
				setQuantity(index, current + Number(button.dataset.cancelAdjust) * step); update();
			});
			dialog.$wrapper.on("click", "[data-cancel-reason]", event => {
				const button = event.currentTarget;
				dialog.set_value("action_reason", button.dataset.cancelReason);
				dialog.$wrapper.find("[data-cancel-reason]").attr("aria-pressed", "false");
				button.setAttribute("aria-pressed", "true"); update();
			});
			dialog.$wrapper.on("click", "[data-cancel-select-all]", () => {
				const checks = [...dialog.$wrapper[0].querySelectorAll("[data-cancel-select]")];
				const selectAll = checks.some(check => !check.checked);
				checks.forEach(check => { const index = Number(check.dataset.cancelSelect); setQuantity(index, selectAll ? options.items[index].remaining_qty : 0); }); update();
			});
			dialog.show(); update();
		} catch (error) { this.showError(error); }
	}

	showError(error) {
		const response = error?.responseJSON || error;
		// Frappe already renders server validation messages as a dialog. A POS
		// toast here duplicates the same message in the lower-right corner.
		if (response?._server_messages && !error?.rmsSilent) return;
		let message = "";
		try {
			const serverMessages = typeof response?._server_messages === "string"
				? JSON.parse(response._server_messages) : response?._server_messages;
			for (const entry of Array.isArray(serverMessages) ? serverMessages : []) {
				const parsed = typeof entry === "string" ? JSON.parse(entry) : entry;
				if (parsed?.message) { message = String(parsed.message); break; }
			}
		} catch (_) {}
		if (!message && typeof response?.message === "string") message = response.message;
		if (!message && typeof error?.message === "string" && !/traceback|exception|internal server error/i.test(error.message)) message = error.message;
		if (!message || /traceback|exception|internal server error/i.test(message)) message = __("The operation could not be completed. Please try again.");
		frappe.show_alert({ message, indicator: "red" }, 7);
	}

	renderReturnSteps(step) {
		return `<ol class="rms-return-steps" aria-label="${__("Return progress")}">${[__("Invoice"), __("Items"), __("Refund")].map((label, index) => `<li class="${index + 1 === step ? "is-active" : index + 1 < step ? "is-complete" : ""}" ${index + 1 === step ? 'aria-current="step"' : ""}><span>${index + 1 < step ? "✓" : index + 1}</span>${label}</li>`).join("")}</ol>`;
	}

	returnInvoiceContext(invoice) {
		return `<div class="rms-return-invoice-context"><span class="rms-return-invoice-icon" aria-hidden="true">↶</span><div><strong>${this.escape(invoice.customer || __("Walk-in Customer"))}</strong><span>${this.escape(invoice.name)} · ${this.escape(invoice.posting_date || "")}</span></div><span class="rms-return-context-label">${__("Original total")}<b>${this.currency(invoice.grand_total)}</b></span></div>`;
	}

	async startReturnFlow() {
		if (!this.state.session) return frappe.msgprint(__("Open a cashier session before processing a return."));
		this.closeReturnSalesDialog();
		try {
			await this.ensureReturnSalesStyles();
			const data = await this.call("get_returnable_sales", { store: this.state.store });
			if (!data.invoices?.length) return frappe.msgprint(__("There are no returnable POS invoices for this Store."));
			const html = `<div class="rms-pos-return-sale-backdrop" data-return-sale-backdrop><section class="rms-pos-return-sale-dialog" role="dialog" aria-modal="true" aria-labelledby="rms-pos-return-sale-title">
				<header class="rms-pos-return-sale-header"><div><span>${__("RETURNS")}</span><h2 id="rms-pos-return-sale-title">${__("Return a Sale")}</h2><p>${__("Find the original sale to get started.")}</p></div><button type="button" data-return-sale-close aria-label="${__("Close")}">×</button></header>
				${this.renderReturnSteps(1)}<div class="rms-pos-return-sale-body"><label class="rms-pos-return-sale-search"><span aria-hidden="true">⌕</span><span class="sr-only">${__("Search POS invoices")}</span><input type="search" data-return-search placeholder="${this.escape(__("Search by POS Invoice, customer, or date"))}" autocomplete="off"></label>
				<div class="rms-return-list-caption"><strong>${__("Recent sales")}</strong><span data-return-matches aria-live="polite">${data.invoices.length} ${__("invoices")}</span></div>
				<div class="rms-pos-return-sale-list">${data.invoices.map((invoice) => `<article class="rms-pos-return-sale-row" data-return-invoice-card data-search="${this.escape(`${invoice.name} ${invoice.customer || ""} ${invoice.posting_date || ""}`)}"><span class="rms-return-invoice-icon" aria-hidden="true">↶</span><div class="rms-pos-return-sale-info"><strong>${this.escape(invoice.customer || __("Walk-in Customer"))}</strong><span>${this.escape(invoice.name)}</span><small>${this.escape(invoice.posting_date || "")}<span class="rms-return-item-badge">${invoice.returnable_lines.length} ${__("items")}</span></small></div><div class="rms-pos-return-sale-total"><small>${__("Original total")}</small><strong>${this.currency(invoice.grand_total)}</strong></div><button type="button" data-return-invoice="${this.escape(invoice.name)}">${__("Select")} <span aria-hidden="true">›</span></button></article>`).join("")}<div class="rms-pos-return-sale-empty" data-return-no-results hidden><span aria-hidden="true">⌕</span><strong>${__("No matching POS invoices.")}</strong><p>${__("Try another customer name, invoice number or date.")}</p></div></div></div>
				<footer class="rms-pos-return-sale-footer"><span>${__("Choose a sale, then select the items to return.")}</span><button type="button" class="btn btn-default" data-return-sale-close>${__("Close")}</button></footer></section></div>`;
			this.returnSalesFocus = document.activeElement;
			document.body.insertAdjacentHTML("beforeend", html);
			const overlay = document.querySelector("[data-return-sale-backdrop]");
			const search = overlay.querySelector("[data-return-search]");
			search.focus();
			search.addEventListener("input", () => {
				const query = search.value.trim().toLocaleLowerCase();
				const cards = [...overlay.querySelectorAll("[data-return-invoice-card]")];
				let visible = 0;
				cards.forEach((card) => {
					card.hidden = !card.dataset.search.toLocaleLowerCase().includes(query);
					if (!card.hidden) visible++;
				});
				overlay.querySelector("[data-return-no-results]").hidden = visible > 0;
				overlay.querySelector("[data-return-matches]").textContent = `${visible} ${__("invoices")}`;
			});
			overlay.addEventListener("click", async (event) => {
				if (event.target === overlay || event.target.closest("[data-return-sale-close]")) {
					this.closeReturnSalesDialog();
					return;
				}
				const select = event.target.closest("[data-return-invoice]");
				if (!select) return;
				const invoice = data.invoices.find((row) => row.name === select.dataset.returnInvoice);
				this.closeReturnSalesDialog();
				if (invoice) await this.openReturnItems(invoice, data.refund_methods || [], data.action_reasons || []);
			});
			overlay.addEventListener("keydown", (event) => {
				if (event.key === "Escape") this.closeReturnSalesDialog();
				if (event.key === "Tab") {
					const focusable = [...overlay.querySelectorAll('button, input')].filter(node => node.getClientRects().length);
					const first = focusable[0], last = focusable[focusable.length - 1];
					if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
					else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
				}
			});
		} catch (error) { this.showError(error); }
	}

	async ensureReturnSalesStyles() {
		const version = "pos-a-100";
		const href = `/assets/rms/css/point_of_sale.css?v=${version}`;
		let link = [...document.querySelectorAll('link[rel="stylesheet"]')].find((node) => node.href.includes("/assets/rms/css/point_of_sale.css"));
		if (link?.href.includes(`v=${version}`)) return;
		if (!link) {
			link = document.createElement("link");
			link.rel = "stylesheet";
			document.head.appendChild(link);
		}
		await new Promise((resolve) => {
			const done = () => resolve();
			link.addEventListener("load", done, { once: true });
			link.addEventListener("error", done, { once: true });
			link.href = href;
			window.setTimeout(done, 2500);
		});
	}

	closeReturnSalesDialog() {
		document.querySelector("[data-return-sale-backdrop]")?.remove();
		this.returnSalesFocus?.focus?.();
		this.returnSalesFocus = null;
	}

	async openReturnItems(invoice, refundMethods, actionReasons, previous = null) {
		const previousItems = new Map((previous?.items || []).map((row) => [row.source_pos_invoice_item, row]));
		const groups = new Map();
		invoice.returnable_lines.forEach((row) => {
			const key = JSON.stringify([row.item_code, row.rate, row.uom]);
			if (!groups.has(key)) groups.set(key, { ...row, qty: 0, lines: [], must_be_whole_number: true });
			const group = groups.get(key);
			group.qty += Number(row.qty || 0);
			group.lines.push(row);
			group.must_be_whole_number = group.must_be_whole_number && row.must_be_whole_number;
		});
		const items = [...groups.values()];
		items.forEach((group) => {
			group.initialQty = group.lines.reduce((total, line) => total + Number(previousItems.get(line.name)?.qty || 0), 0);
			group.initialChecked = group.initialQty > 0;
		});
		const reasons = actionReasons || [];
		const initialWaste = [...previousItems.values()].some((row) => row.is_waste);
		const reasonPicker = `<div class="rms-expense-category-picker rms-pos-return-reason-picker"><label class="rms-pos-picker-label">${__("Return reason")} <span class="text-danger">*</span></label><input class="form-control" type="search" role="combobox" aria-label="${__("Return reason")}" aria-required="true" aria-autocomplete="list" aria-expanded="false" data-return-reason-search placeholder="${this.escape(__("Choose or search a return reason"))}" autocomplete="off"><div class="rms-expense-category-list" data-return-reason-list role="listbox" hidden>${reasons.map((row) => `<div class="rms-expense-category-option" role="option" tabindex="-1" data-return-reason="${this.escape(row.name)}" data-return-reason-search-text="${this.escape(`${row.reason} ${row.name}`)}" aria-selected="false">${this.escape(row.reason)}</div>`).join("")}</div><p class="rms-expense-category-empty" data-return-reason-empty hidden>${this.escape(reasons.length ? __("No matching return reasons.") : __("No enabled return reasons are configured."))}</p><p class="rms-return-reason-error" data-return-reason-error role="alert" hidden>${__("Choose a return reason before reviewing the refund.")}</p></div>`;
		const html = `${this.renderReturnSteps(2)}${this.returnInvoiceContext(invoice)}<div class="rms-pos-return-selection"><div class="rms-return-selection-toolbar"><div><strong>${__("Choose items to return")}</strong><span data-return-selection-count aria-live="polite"></span></div><button type="button" data-return-toggle-all>${__("Select all")}</button></div><div class="rms-pos-return-lines">${items.map((row, index) => {
			const checked = row.initialChecked ? " checked" : "";
			const disabled = row.initialChecked ? "" : " disabled";
			const qty = row.initialChecked ? row.initialQty : row.qty;
			return `<div class="rms-pos-return-line"><label class="rms-pos-return-item"><input type="checkbox" data-return-select="${index}"${checked}><span><b>${this.escape(row.title || row.item_code)}</b><small>${this.escape(row.item_code)} · ${this.currency(row.rate)} / ${this.escape(row.uom || "")}</small></span></label><span class="rms-pos-return-available">${__("Available")}: <b>${row.qty}</b></span><div class="rms-pos-qty rms-pos-return-qty" data-return-qty-control><button type="button" data-return-qty-adjust="-1" aria-label="${__("Decrease return quantity")}"${disabled}>−</button><input type="number" data-return-qty="${index}" min="${row.must_be_whole_number ? 1 : 0.001}" max="${row.qty}" step="${row.must_be_whole_number ? 1 : "any"}" value="${qty}" aria-label="${__("Return quantity")}"${disabled}><button type="button" data-return-qty-adjust="1" aria-label="${__("Increase return quantity")}"${disabled}>+</button></div></div>`;
		}).join("")}</div><label class="rms-pos-waste-toggle rms-pos-return-waste"><input type="checkbox" data-return-waste${initialWaste ? " checked" : ""}><span>${__("Is Waste")}</span></label></div>`;
		const dialog = new frappe.ui.Dialog({ title: __("Select Return Items"), size: "large", fields: [
			{ fieldtype: "HTML", fieldname: "items_html", options: html },
			{ fieldtype: "HTML", fieldname: "reason_picker", options: reasonPicker },
			{ fieldtype: "Data", fieldname: "action_reason", label: __("Return reason"), hidden: 1 },
		], primary_action_label: __("Review refund"), primary_action: async (values) => {
			const selected = [];
			const invalid = [...dialog.$wrapper[0].querySelectorAll("[data-return-select]:checked")].some((check) => {
				const index = Number(check.dataset.returnSelect);
				const group = items[index];
				const qty = Number(dialog.$wrapper[0].querySelector(`[data-return-qty="${index}"]`)?.value);
				if (!group || !Number.isFinite(qty) || qty <= 0 || qty > group.qty || (group.must_be_whole_number && !Number.isInteger(qty))) return true;
				const isWaste = Boolean(dialog.$wrapper[0].querySelector("[data-return-waste]")?.checked);
				let remaining = qty;
				group.lines.forEach((line) => {
					const lineQty = Math.min(remaining, Number(line.qty));
					if (lineQty > 0) selected.push({ source_pos_invoice_item: line.name, qty: lineQty, is_waste: isWaste, max: line.qty });
					remaining = Number((remaining - lineQty).toFixed(6));
				});
				return remaining > 0.000001;
			});
			if (invalid || !selected.length || selected.some((row) => !Number.isFinite(row.qty) || row.qty <= 0 || row.qty > row.max)) {
				return frappe.msgprint(__("Select valid quantities for at least one return item."));
			}
			if (!reasons.some(row => row.name === values.action_reason)) {
				dialog.$wrapper.find("[data-return-reason-error]").prop("hidden", false);
				dialog.$wrapper.find("[data-return-reason-search]").attr("aria-invalid", "true").trigger("focus");
				return;
			}
			dialog.disable_primary_action();
			try {
				const preview = await this.call("preview_pos_return", { source_pos_invoice: invoice.name,
					items: JSON.stringify(selected.map(({ max, ...row }) => row)), action_reason: values.action_reason });
				dialog.hide();
				await this.openReturnPayments(invoice, selected, values.action_reason, preview, refundMethods, reasons);
			} catch (error) { this.showError(error); }
			finally { dialog.enable_primary_action(); }
		} });
		dialog.$wrapper.addClass("rms-pos-return-items-dialog");
		const updateSelection = () => {
			const checks = [...dialog.$wrapper[0].querySelectorAll("[data-return-select]")];
			const selected = checks.filter(check => check.checked).length;
			dialog.$wrapper.find("[data-return-selection-count]").text(__("{0} of {1} items selected", [selected, checks.length]));
			dialog.$wrapper.find("[data-return-toggle-all]").text(selected === checks.length ? __("Clear selection") : __("Select all"));
			checks.forEach(check => check.closest(".rms-pos-return-line")?.classList.toggle("is-selected", check.checked));
			if (selected) dialog.enable_primary_action(); else dialog.disable_primary_action();
		};
		dialog.$wrapper.on("click", "[data-return-toggle-all]", () => {
			const checks = [...dialog.$wrapper[0].querySelectorAll("[data-return-select]")];
			const selectAll = checks.some(check => !check.checked);
			checks.forEach(check => { check.checked = selectAll; $(check).trigger("change"); });
			updateSelection();
		});
		dialog.$wrapper.on("input", "[data-return-reason-search]", (event) => {
			const input = event.currentTarget;
			const query = input.value.trim().toLocaleLowerCase();
			dialog.set_value("action_reason", "");
			input.setAttribute("aria-expanded", "true");
			const options = dialog.$wrapper.find("[data-return-reason]");
			let visible = 0;
			options.each((_, option) => {
				option.hidden = !option.dataset.returnReasonSearchText.toLocaleLowerCase().includes(query);
				if (!option.hidden) visible++;
			});
			dialog.$wrapper.find("[data-return-reason-list]").prop("hidden", false);
			dialog.$wrapper.find("[data-return-reason-empty]").prop("hidden", visible > 0);
		});
		dialog.$wrapper.find("[data-return-reason-search]").on("focus", (event) => {
			const input = event.currentTarget;
			input.setAttribute("aria-expanded", "true");
			dialog.$wrapper.find("[data-return-reason]").prop("hidden", false);
			dialog.$wrapper.find("[data-return-reason-list]").prop("hidden", false);
			dialog.$wrapper.find("[data-return-reason-empty]").prop("hidden", reasons.length > 0);
			window.requestAnimationFrame(() => dialog.$wrapper.find(".rms-pos-return-reason-picker")[0]?.scrollIntoView({ block: "nearest" }));
		});
		dialog.$wrapper.find("[data-return-reason-search]").on("blur", (event) => {
			const input = event.currentTarget;
			window.setTimeout(() => {
				const list = dialog.$wrapper.find("[data-return-reason-list]")[0];
				if (list && !list.contains(document.activeElement)) {
					list.hidden = true;
					input.setAttribute("aria-expanded", "false");
				}
			}, 0);
		});
		dialog.$wrapper.on("mousedown", "[data-return-reason]", (event) => event.preventDefault());
		dialog.$wrapper.on("click", "[data-return-reason]", (event) => {
			const option = event.currentTarget;
			const input = dialog.$wrapper.find("[data-return-reason-search]")[0];
			dialog.set_value("action_reason", option.dataset.returnReason);
			dialog.$wrapper.find("[data-return-reason-error]").prop("hidden", true);
			input.removeAttribute("aria-invalid");
			dialog.$wrapper.find("[data-return-reason]").attr("aria-selected", "false").removeClass("is-selected");
			$(option).attr("aria-selected", "true").addClass("is-selected");
			input.value = option.textContent;
			input.setAttribute("aria-expanded", "false");
			dialog.$wrapper.find("[data-return-reason-list], [data-return-reason-empty]").prop("hidden", true);
		});
		dialog.$wrapper.find("[data-return-reason-search]").on("keydown", (event) => {
			const options = [...dialog.$wrapper.find("[data-return-reason]:not([hidden])")];
			if (event.key === "Escape") {
				dialog.$wrapper.find("[data-return-reason-list]").prop("hidden", true);
				event.currentTarget.setAttribute("aria-expanded", "false");
			} else if (event.key === "ArrowDown" && options.length) {
				event.preventDefault();
				options[0].focus();
			} else if (event.key === "Enter" && options.length === 1) {
				event.preventDefault();
				options[0].click();
			}
		});
		dialog.$wrapper.on("keydown", "[data-return-reason]", (event) => {
			const options = [...dialog.$wrapper.find("[data-return-reason]:not([hidden])")];
			const index = options.indexOf(event.currentTarget);
			if (event.key === "ArrowDown" || event.key === "ArrowUp") {
				event.preventDefault();
				options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length]?.focus();
			} else if (event.key === "Enter") {
				event.preventDefault();
				event.currentTarget.click();
			} else if (event.key === "Escape") {
				const input = dialog.$wrapper.find("[data-return-reason-search]")[0];
				dialog.$wrapper.find("[data-return-reason-list]").prop("hidden", true);
				input.setAttribute("aria-expanded", "false");
				input.focus();
			}
		});
		dialog.$wrapper.on("change", "[data-return-select]", (event) => {
			const check = event.currentTarget;
			const index = check.dataset.returnSelect;
			const control = dialog.$wrapper[0].querySelector(`[data-return-qty-control] [data-return-qty="${index}"]`)?.closest("[data-return-qty-control]");
			updateSelection();
			if (!control) return;
			const input = control.querySelector("[data-return-qty]");
			input.disabled = !check.checked;
			control.querySelectorAll("button").forEach((button) => { button.disabled = !check.checked; });
			if (check.checked) {
				const qty = Number(input.value || 0);
				control.querySelector('[data-return-qty-adjust="-1"]').disabled = qty <= Number(input.min || 0.001);
				control.querySelector('[data-return-qty-adjust="1"]').disabled = qty >= Number(input.max || 0);
			}
		});
		dialog.$wrapper.on("click", "[data-return-qty-adjust]", (event) => {
			const button = event.currentTarget;
			const control = button.closest("[data-return-qty-control]");
			const input = control?.querySelector("[data-return-qty]");
			if (!input) return;
			const min = Number(input.min || 0.001);
			const max = Number(input.max || 0);
			const step = input.step === "any" ? 0.001 : Number(input.step || 1);
			const current = Number(input.value || min);
			const next = Math.min(max, Math.max(min, current + Number(button.dataset.returnQtyAdjust) * step));
			input.value = input.step === "any" ? String(Number(next.toFixed(3))) : String(next);
			control.querySelector('[data-return-qty-adjust="-1"]').disabled = next <= min;
			control.querySelector('[data-return-qty-adjust="1"]').disabled = next >= max;
		});
		dialog.$wrapper.find("[data-return-qty-control]").each((_, control) => {
			const input = control.querySelector("[data-return-qty]");
			const qty = Number(input?.value || 0);
			const selected = control.closest(".rms-pos-return-line")?.querySelector("[data-return-select]")?.checked;
			input.disabled = !selected;
			control.querySelector('[data-return-qty-adjust="-1"]').disabled = !selected || qty <= Number(input?.min || 0.001);
			control.querySelector('[data-return-qty-adjust="1"]').disabled = !selected || qty >= Number(input?.max || 0);
		});
		dialog.$wrapper.on("change input", "[data-return-qty]", (event) => {
			const input = event.currentTarget;
			const control = input.closest("[data-return-qty-control]");
			const qty = Number(input.value || 0);
			control.querySelector('[data-return-qty-adjust="-1"]').disabled = qty <= Number(input.min || 0.001);
			control.querySelector('[data-return-qty-adjust="1"]').disabled = qty >= Number(input.max || 0);
		});
		dialog.show();
		updateSelection();
		const previousReason = reasons.find((row) => row.name === previous?.reason);
		if (previousReason) {
			dialog.set_value("action_reason", previousReason.name);
			const input = dialog.$wrapper.find("[data-return-reason-search]")[0];
			input.value = previousReason.reason;
			const option = [...dialog.$wrapper[0].querySelectorAll("[data-return-reason]")]
				.find((row) => row.dataset.returnReason === previousReason.name);
			if (option) $(option).attr("aria-selected", "true").addClass("is-selected");
		}
	}

	async openReturnPayments(invoice, items, reason, preview, methods, actionReasons) {
		if (!methods.length) return frappe.msgprint(__("Configure at least one POS Profile payment method with Allow In Returns enabled."));
		const returnItems = items.map(({ max, ...row }) => row);
		const initialMethod = methods[0].mode_of_payment;
		const refundMethodPicker = this.renderStaticPicker("return-refund-method", __("Refund method"),
			methods.map((row) => ({ value: row.mode_of_payment, label: row.mode_of_payment })), initialMethod);
		const fields = [
			{ fieldtype: "HTML", fieldname: "refund_summary", options: `${this.renderReturnSteps(3)}${this.returnInvoiceContext(invoice)}<div class="rms-return-refund-hero"><span>${__("Refund total")}</span><strong>${this.currency(preview.refund_total)}</strong><small>${__("Review the amount and choose how to refund the customer.")}</small></div>` },
			{ fieldtype: "HTML", fieldname: "refund_method_picker", options: refundMethodPicker },
			{ fieldtype: "Data", fieldname: "mode_of_payment", default: initialMethod, hidden: 1, reqd: 1 },
			{ fieldtype: "Small Text", fieldname: "comment", label: __("Comment"), default: this.returnComment || "" },
			{ fieldtype: "HTML", fieldname: "refund_details", options: `<div class="rms-return-refund-details"><span>${__("Items")}<b>${items.reduce((sum, row) => sum + Number(row.qty), 0)}</b></span><span>${__("Reason")}<b>${this.escape(actionReasons.find(row => row.name === reason)?.reason || reason)}</b></span></div>` },
		];
		const dialog = new frappe.ui.Dialog({ title: __("Review refund"), fields,
			primary_action_label: __("Confirm refund"), primary_action: async (values) => {
				if (!values.mode_of_payment) return frappe.msgprint(__("Choose a refund method."));
				dialog.disable_primary_action();
				const payments = [{ mode_of_payment: values.mode_of_payment, amount: Number(preview.refund_total) }];
				try {
					this.returnComment = dialog.get_value("comment") || "";
					const result = await this.completeAuthorizedOperation("request_pos_return", {source_pos_invoice: invoice.name,
						items: JSON.stringify(returnItems), payments: JSON.stringify(payments), action_reason: reason, comment: this.returnComment}, dialog);
					if (!result) { dialog.enable_primary_action(); return; }
					dialog.hide(); this.returnComment = "";
					this.showReturnConfirmed(result, values.mode_of_payment);
				} catch (error) { dialog.enable_primary_action(); this.showError(error); }
			} });
		dialog.$wrapper.addClass("rms-pos-return-payment-dialog");
		this.bindStaticPicker(dialog, "return-refund-method", "mode_of_payment");
		dialog.$wrapper.find(".modal-header").prepend(`<button type="button" class="rms-pos-return-back" data-return-payment-back aria-label="${__("Back to return items")}">←</button>`);
		dialog.$wrapper.on("click", "[data-return-payment-back]", () => {
			this.returnComment = dialog.get_value("comment") || "";
			dialog.hide();
			this.openReturnItems(invoice, methods, actionReasons, { items, reason });
		});
		dialog.show();
	}


	async completeAuthorizedOperation(method, args, origin) {
		const result = await this.call(method, args);
		if (!result.requires_manager_authorization) return result;
		if (!result.approvers?.length) {
			frappe.msgprint(__("No different manager with permission for this operation and Store is available."));
			return null;
		}
		return new Promise(resolve => {
			let completed = false, busy = false;
			const dialog = new frappe.ui.Dialog({title:__("Manager approval"), fields:[
				{fieldtype:"Select",fieldname:"approver",label:__("Manager"),reqd:1,
					options:[{value:"",label:__("Choose a manager")},...result.approvers.map(row=>({value:row.user,label:row.full_name}))]},
				{fieldtype:"Select",fieldname:"method",label:__("Approval method"),options:[{value:"Password",label:__("Fixed password")},{value:"OTP",label:__("One-time code")}],default:"Password"},
				{fieldtype:"Password",fieldname:"credential",label:__("Manager password / one-time code"),reqd:1},
				{fieldtype:"HTML",fieldname:"otp_request",options:`<button type="button" class="btn btn-default" data-operation-request-otp hidden>${__("Retry sending code")}</button><p data-operation-otp-status role="status"></p>`},
			],primary_action_label:__("Verify and confirm"),primary_action:async values=>{
				if (busy) return;
				busy=true;dialog.disable_primary_action();
				try {
					const credential = dialog.get_value("credential") || "";
					const response=await this.call(method,{...args,approval_approver:values.approver,
						...(dialog.get_value("method")==="OTP"?{approval_code:credential}:{approval_password:credential})});
					if (response.requires_manager_authorization) throw Error(__("Manager approval is still required."));
					completed=true;dialog.hide();resolve(response);
				} catch(error) {this.showError(error);}
				finally {busy=false;dialog.enable_primary_action();}
			}});
			dialog.$wrapper.addClass("rms-pos-operation-approval-dialog");
			const sendCode = (resend = false) => {
				const approver=dialog.get_value("approver");
				if (!approver || dialog.get_value("method")!=="OTP") return;
				return this.deliverApprovalCode("request_pos_operation_approval",{operation_context:JSON.stringify(result.operation_context),approver},
					dialog.$wrapper.find("[data-operation-otp-status]")[0],dialog.$wrapper.find("[data-operation-request-otp]")[0],resend===true);
			};
			const changed = () => {dialog.set_value("credential","");return sendCode();};
			for (const name of ["approver","method"]) {
				if (dialog.fields_dict?.[name]) dialog.fields_dict[name].df.onchange=changed;
			}
			dialog.$wrapper.on("change", '[data-fieldname="method"] select, [data-fieldname="approver"] select',changed);
			dialog.$wrapper.on("click","[data-operation-request-otp]",()=>sendCode(true));
			dialog.onhide=()=>{if (!completed) {origin.show();resolve(null);}};
			origin.hide();dialog.show();
		});
	}

	async showOperationApprovals() {
		try {
			const rows=await this.call("get_pending_pos_operation_approvals",{store:this.state.store});
			const html=rows.map((row,index)=>`<article class="rms-operation-request"><b>${this.escape(row.action)} · ${this.escape(row.subject)}</b><p>${this.escape(row.requester)}${row.context.payload.is_waste?" · "+__("Waste"):""}</p><ul>${row.context.payload.items.map(item=>`<li>${this.escape(item.title||item.item_name||item.source_pos_invoice_item)} × ${this.escape(item.qty)}</li>`).join("")}</ul>${row.context.payload.comment?`<p>${this.escape(row.context.payload.comment)}</p>`:""}${row.status === "Issued" ? (row.notification_log ? `<button type="button" class="btn btn-primary" data-operation-notification="${index}">${__("View code in notifications")}</button>` : `<span>${__("Code already issued")}</span>`) : `<button type="button" class="btn btn-primary" data-operation-issue="${index}">${__("Generate one-time code")}</button>`}</article>`).join("")||`<p>${__("No pending approvals")}</p>`;
			const dialog=new frappe.ui.Dialog({title:__("Operation approvals"),fields:[{fieldtype:"HTML",fieldname:"requests",options:html}]});
			dialog.$wrapper.on("click", "[data-operation-notification]", event => {
				const row = rows[Number(event.currentTarget.dataset.operationNotification)];
				dialog.hide(); window.rmsShowApprovalPopup({notification_name:row.notification_log,challenge_name:row.name});
			});
			dialog.$wrapper.on("click","[data-operation-issue]",async event=>{
				const button=event.currentTarget;button.disabled=true;
				try {
					const result=await this.call("issue_pos_operation_approval_code",{challenge_name:rows[Number(button.dataset.operationIssue)].name});
					frappe.msgprint({title:__("One-time approval code"),message:`<strong class="rms-operation-code">${this.escape(result.code)}</strong><p>${__("Valid for five minutes for this operation only.")}</p>`});
				} catch(error) {button.disabled=false;this.showError(error);}
			});dialog.show();
		} catch(error) {this.showError(error);}
	}

	showReturnConfirmed(result, paymentMethod) {
		const details = [
			`${__("Credit note")}: <strong>${this.escape(result.return_pos_invoice || "—")}</strong>`,
			`${__("Refund method")}: <strong>${this.escape(paymentMethod || "—")}</strong>`,
			`${__("Refund total")}: <strong>${this.currency(result.refund_total)}</strong>`,
		];
		if (result.stock_entry) details.push(`${__("Stock Entry")}: <strong>${this.escape(result.stock_entry)}</strong>`);
		frappe.msgprint({ title: __("Return confirmed"), message: `<p>${this.escape(result.name)}</p>${details.map((row) => `<p>${row}</p>`).join("")}` });
	}

	renderOrderTypePicker() {
		const picker = this.page.main[0]?.querySelector("[data-order-type-picker]");
		if (!picker) return;
		const toggle = picker.querySelector("[data-order-type-toggle]");
		const list = picker.querySelector("[data-order-type-list]");
		const selected = this.state.order_types.find(row => row.name === this.state.order_type);
		const label = selected?.title || selected?.name || this.state.order_type || __("No order types available");
		picker.querySelector('[data-role="order-type-label"]').textContent = label;
		toggle.setAttribute("aria-label", `${__("Order Type")}: ${label}`);
		toggle.disabled = Boolean(this.state.bootstrap_loading || !this.state.store || !this.state.order_types.length);
		const focused = document.activeElement?.dataset?.orderTypeOption;
		list.innerHTML = this.state.order_types.map(row => `<button type="button" role="option" tabindex="-1" data-order-type-option="${this.escape(row.name)}" aria-selected="${row.name === this.state.order_type}"><span>${this.escape(row.title || row.name)}</span><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg></button>`).join("");
		if (toggle.disabled) this.setOrderTypePickerOpen(false);
		else if (focused && this.orderTypePickerOpen) [...list.children].find(row => row.dataset.orderTypeOption === focused)?.focus();
	}

	setOrderTypePickerOpen(open, focus = false) {
		const picker = this.page.main[0]?.querySelector("[data-order-type-picker]");
		if (!picker) return;
		const toggle = picker.querySelector("[data-order-type-toggle]");
		const list = picker.querySelector("[data-order-type-list]");
		open = Boolean(open && !toggle.disabled);
		this.orderTypePickerOpen = open;
		list.hidden = !open;
		toggle.setAttribute("aria-expanded", String(open));
		if (open) {
			list.style.left = "0px";
			const rect = list.getBoundingClientRect();
			if (rect.left < 12) list.style.left = `${12 - rect.left}px`;
			else if (rect.right > window.innerWidth - 12) list.style.left = `${window.innerWidth - 12 - rect.right}px`;
			list.style.maxHeight = `${Math.max(0, Math.min(320, window.innerHeight - rect.top - 12))}px`;
			if (focus) (list.querySelector('[aria-selected="true"]') || list.firstElementChild)?.focus();
		} else if (focus) toggle.focus();
	}

	handleOrderTypePickerKey(event) {
		const picker = event.target.closest("[data-order-type-picker]");
		if (!picker) return false;
		if (event.key === "Escape" && this.orderTypePickerOpen) {
			event.preventDefault(); event.stopPropagation(); this.setOrderTypePickerOpen(false, true); return true;
		}
		if (event.key === "Tab" && this.orderTypePickerOpen) { this.setOrderTypePickerOpen(false, true); return false; }
		if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return false;
		event.preventDefault();
		const wasOpen = this.orderTypePickerOpen;
		this.setOrderTypePickerOpen(true);
		const options = [...picker.querySelectorAll("[data-order-type-option]")];
		if (!options.length || !this.orderTypePickerOpen) return true;
		const current = options.indexOf(event.target);
		const selected = Math.max(0, options.findIndex(row => row.getAttribute("aria-selected") === "true"));
		const index = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
			: !wasOpen || current < 0 ? selected : (current + (event.key === "ArrowUp" ? -1 : 1) + options.length) % options.length;
		options[index].focus();
		return true;
	}

	showMyAccount() {
		const root = this.page.main[0];
		const setup = root?.querySelector("[data-pos-setup]");
		if (!setup) return;
		this.setActionsMenuOpen(false);
		this.renderSaleSetup();
		setup.hidden = false;
		setup.style.right = "0px";
		const rect = setup.getBoundingClientRect();
		setup.style.maxHeight = `${Math.max(0, window.innerHeight - rect.top - 12)}px`;
		if (rect.left < 12) setup.style.right = `${rect.left - 12}px`;
		else if (rect.right > window.innerWidth - 12) setup.style.right = `${rect.right - window.innerWidth + 12}px`;
		const toggle = root.querySelector("[data-more-toggle]");
		toggle?.setAttribute("aria-expanded", "true");
		toggle?.setAttribute("aria-controls", "rms-pos-setup-panel");
		toggle?.setAttribute("aria-haspopup", "dialog");
		setup.querySelector("select:not(:disabled), [data-setup-back]")?.focus();
	}

	closeMyAccount(focus = false) {
		const root = this.page.main[0];
		const setup = root?.querySelector("[data-pos-setup]");
		if (!setup || setup.hidden) return;
		setup.hidden = true;
		const toggle = root.querySelector("[data-more-toggle]");
		toggle?.setAttribute("aria-expanded", "false");
		toggle?.setAttribute("aria-controls", "rms-pos-actions-menu");
		toggle?.setAttribute("aria-haspopup", "menu");
		if (focus) toggle?.focus();
	}

	renderSaleSetup() {
		const root = this.page.main;
		root.find('[data-select="store"]').html(this.selectOptions("store", this.state.stores, this.state.store, this.state.store ? null : __("Select Store"))).prop("disabled", Boolean(this.state.session || this.state.bootstrap_loading));
		root.find('[data-select="brand"]').html(this.selectOptions("brand", this.state.brands, this.state.brand, this.state.brands.length ? null : __("No brands available"))).prop("disabled", Boolean(this.state.bootstrap_loading || !this.state.store || !this.state.brands.length));
		root.find('[data-select="order_type"]').html(this.selectOptions("order_type", this.state.order_types, this.state.order_type, this.state.order_types.length ? null : __("No order types available"))).prop("disabled", Boolean(this.state.bootstrap_loading || !this.state.store || !this.state.order_types.length));
		this.renderOrderTypePicker();
		const store = this.state.stores.find(row => row.name === this.state.store);
		const brand = this.state.brands.find(row => row.name === this.state.brand);
		const summary = [store?.title || this.state.store, brand?.title || this.state.brand].filter(Boolean).join(" · ");
		root.find('[data-role="setup-summary"]').text(summary || __("Store and brand")).attr?.("title", summary);
		root.find('[data-role="setup-hint"]').text(this.state.session ? __("Close the cashier session to change the Store.") : __("Choose the Store and Brand for this register."));
	}

	selectOptions(key, rows, selected, emptyLabel) {
		return `${emptyLabel ? `<option value="">${this.escape(emptyLabel)}</option>` : ""}${rows.map((row) => `<option value="${this.escape(row.name)}" ${row.name === selected ? "selected" : ""}>${this.escape(row.title || row.name)}</option>`).join("")}`;
	}

	render() {
		const root = this.page.main;
		root.toggleClass?.("rms-pos-restoring", Boolean(this.state.bootstrap_loading && this.state.restoring_order));
		this.renderSaleSetup();
		const canBrowseMenu = Boolean(this.state.store && this.state.brand && this.state.order_type);
		root.find('[data-search]').prop("disabled", !canBrowseMenu);
		root.find('[data-action="scan"]').prop("disabled", !canBrowseMenu);
		this.renderHeaderActions();
		this.renderLanguageChoices();
		root.find('[data-action="session"]').prop("hidden", !this.state.session && !this.state.permissions.can_checkout);
		root.find('[data-action="session"]').text(this.state.session ? __("Close Session") : __("Open Session"));
		root.find('[data-role="context"]').html(this.state.session ? `<span class="rms-pos-live is-on"></span><span>${__("Cashier session open")} · ${this.escape(this.state.session.business_date)}</span>` : `<span class="rms-pos-live"></span><span>${__("Cashier session closed")}</span>`);
		root.find('[data-role="catalog-hint"]').text(this.state.session ? __("Find an item, add it to the order, then take payment.") : __("Browse the menu and prices. Open a cashier session when you are ready to sell."));
		this.updateOrderTypeFields(); this.renderFields(); this.renderCategories(); this.renderProducts(); this.renderCart();
	}

	updateOrderTypeFields() {
		this.renderOrderTypePicker();
		const orderType = this.state.order_types.find((row) => row.name === this.state.order_type);
		this.page.main.find('[data-role="reference-wrap"]').prop("hidden", !orderType?.require_external_reference);
		this.page.main.find('[data-role="dining-wrap"]').prop("hidden", !orderType?.require_table);
	}

	renderFields() {
		const root = this.page.main;
		root.find('[data-select="dining_area"]').html(this.selectOptions("dining_area", this.state.areas || [], this.state.dining_area, __("Not applicable"))).prop("disabled", !this.state.session || !this.state.permissions.can_checkout || !(this.state.areas || []).length);
		root.find('[data-select="dining_table"]').html(this.selectOptions("dining_table", this.state.tables || [], this.state.dining_table, __("Select Table"))).prop("disabled", !this.state.session || !this.state.permissions.can_checkout || !(this.state.tables || []).length);
		root.find('[data-action="customer"]').text(this.state.customer || __("Walk-in Customer"));
		root.find('[data-input="external_reference"]').val(this.state.external_reference || "");
	}

	categoryLevel() {
		const categories = this.state.categories || [];
		const byName = new Map(categories.map(row => [row.name, row]));
		const selected = byName.get(this.state.category);
		const names = new Set(categories.map(row => row.name));
		const children = categories.filter(row => selected ? row.parent_product_category === selected.name : !names.has(row.parent_product_category));
		const roots = categories.filter(row => !row.parent_product_category);
		const path = [], seen = new Set();
		let current = selected;
		while (current && !seen.has(current.name)) {
			seen.add(current.name); path.unshift(current);
			current = byName.get(current.parent_product_category);
		}
		const descendants = new Set(selected ? [selected.name] : []);
		const byParent = new Map();
		for (const row of categories) {
			if (!byParent.has(row.parent_product_category)) byParent.set(row.parent_product_category, []);
			byParent.get(row.parent_product_category).push(row);
		}
		for (const name of descendants) for (const child of byParent.get(name) || []) descendants.add(child.name);
		return {selected, children, path, roots, descendants};
	}

	selectCategory(name, source = null) {
		const category = name || null;
		if (category && !this.state.categories.some(row => row.name === category)) return;
		const fromRail = Boolean(source?.closest('[data-role="subcategories"]'));
		const fromTop = Boolean(source?.closest('[data-role="categories"]'));
		clearTimeout(this.searchTimer);
		this.state.category = category;
		this.state.search = "";
		const root = this.page.main[0];
		const search = root?.querySelector("[data-search]");
		if (search) search.value = "";
		this.categoryNavOpen = Boolean(this.categoryLevel().children.length && category);
		this.renderCategories();
		const grid = root?.querySelector('[data-role="products"]');
		if (grid) grid.scrollTop = 0;
		const toggle = root?.querySelector("[data-category-nav-toggle]");
		const compact = Boolean(toggle?.getClientRects().length);
		if (compact && this.categoryNavOpen) this.setCategoryNavigationOpen(true, true);
		else if (compact && fromRail) toggle?.focus();
		else {
			const area = root?.querySelector(fromRail ? '[data-role="subcategories"]' : fromTop || !category ? '[data-role="categories"]' : '[data-role="category-context"]');
			const button = [...(area?.querySelectorAll("[data-category]") || [])].find(row => (row.dataset.category || null) === category);
			(button || (fromRail ? area?.querySelector("[data-category], [data-category-back]") : source?.matches("[data-catalog-mode]") ? source : area?.querySelector('[aria-current="page"]')) || root?.querySelector(".rms-pos-category-current"))?.focus();
		}
		return this.loadCatalog();
	}

	setCategoryNavigationOpen(open, focus = false) {
		this.categoryNavOpen = Boolean(open);
		const root = this.page.main[0];
		root?.querySelector("[data-category-browser]")?.classList.toggle("is-nav-open", this.categoryNavOpen);
		const toggle = root?.querySelector("[data-category-nav-toggle]");
		toggle?.setAttribute("aria-expanded", String(this.categoryNavOpen));
		const backdrop = root?.querySelector("[data-category-nav-close]");
		if (backdrop) backdrop.hidden = !this.categoryNavOpen;
		const rail = root?.querySelector('[data-role="subcategories"]');
		if (rail) {
			if (this.categoryNavOpen && toggle?.getClientRects().length) rail.style.maxHeight = `${Math.max(80, Math.min(360, window.innerHeight - rail.getBoundingClientRect().top - 12))}px`;
			else rail.style.removeProperty("max-height");
		}
		if (focus) {
			(this.categoryNavOpen ? rail?.querySelector('[aria-current="page"], [data-category]') || rail?.querySelector("button") : toggle)?.focus();
		}
	}

	handleCategoryNavigationKey(event) {
		if (event.key === "Escape" && this.categoryNavOpen && event.target.closest("[data-category-browser]")
			&& this.page.main[0]?.querySelector("[data-category-nav-toggle]")?.getClientRects().length) {
			event.preventDefault(); event.stopPropagation(); this.setCategoryNavigationOpen(false, true); return true;
		}
		const rail = event.target.closest('[data-role="subcategories"]');
		if (!rail || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return false;
		const items = [...rail.querySelectorAll("button")].filter(button => !button.hidden && !button.disabled);
		if (!items.length) return false;
		event.preventDefault();
		const current = items.indexOf(event.target.closest("button"));
		const index = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
			: (current + (event.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
		items[index].focus(); return true;
	}

	renderCategories() {
		const {selected, children, path, roots} = this.categoryLevel();
		const root = this.page.main;
		root.find("[data-catalog-mode]").each((_, button) => {
			const active = button.dataset.catalogMode === this.state.catalog_mode;
			$(button).toggleClass("is-active", active).attr("aria-selected", String(active));
		});
		root.find(".rms-pos-toolbar").toggle(true);
		const categories = this.state.categories || [];
		const activeRoot = roots.find(row => path.some(ancestor => ancestor.name === row.name));
		root.find('[data-role="categories"]').html(`<button type="button" data-category="" class="${selected ? "" : "is-active"}" aria-pressed="${!selected}">${__("All categories")}</button>${roots.map(row => `<button type="button" class="${activeRoot?.name === row.name ? "is-active" : ""}" data-category="${this.escape(row.name)}" aria-pressed="${activeRoot?.name === row.name}">${this.escape(row.title || row.name)}</button>`).join("")}`);
		const parent = categories.find(row => row.name === selected?.parent_product_category);
		const railRows = !selected ? [] : children.length ? children : parent ? categories.filter(row => row.parent_product_category === parent.name) : [];
		const hasRail = Boolean(parent && railRows.length);
		const breadcrumb = `<nav class="rms-pos-category-breadcrumb" aria-label="${__("Category path")}"><button type="button" data-category="">${__("All categories")}</button>${path.map(row => `<span aria-hidden="true">›</span>${row.name === selected?.name ? `<span class="rms-pos-category-current" tabindex="-1" aria-current="page">${this.escape(row.title || row.name)}</span>` : `<button type="button" data-category="${this.escape(row.name)}">${this.escape(row.title || row.name)}</button>`}`).join("")}</nav>`;
		root.find('[data-role="category-context"]').prop("hidden", !selected).html(`${hasRail ? `<button type="button" class="rms-pos-category-nav-toggle" data-category-nav-toggle aria-controls="rms-pos-subcategories" aria-expanded="${Boolean(this.categoryNavOpen)}"><span aria-hidden="true">☷</span>${__("Subcategories")}<span class="rms-pos-category-nav-count">${railRows.length}</span></button>` : ""}${breadcrumb}`);
		root.find('[data-role="subcategories"]').prop("hidden", !hasRail).html(!hasRail ? "" : `<button type="button" class="rms-pos-category-up" data-category-back="${this.escape(parent?.name || "")}" title="${this.escape(__("Back to {0}", [parent?.title || __("All categories")]))}"><span class="rms-pos-category-arrow" aria-hidden="true">‹</span><span>${this.escape(parent?.title || __("All categories"))}</span></button>${children.length ? `<h3 class="rms-pos-category-rail-title">${this.escape(selected.title || selected.name)}</h3>` : ""}<div class="rms-pos-category-branch">${railRows.map(row => `<button type="button" data-category="${this.escape(row.name)}" class="${row.name === selected.name ? "is-active" : ""}" ${row.name === selected.name ? 'aria-current="page"' : ""}><span>${this.escape(row.title || row.name)}</span>${categories.some(child => child.parent_product_category === row.name) ? '<span class="rms-pos-category-arrow" aria-hidden="true">›</span>' : ""}</button>`).join("")}</div>`);
		root.find("[data-category-browser]").toggleClass?.("has-subcategories", hasRail);
		this.setCategoryNavigationOpen(hasRail && this.categoryNavOpen);
		const crumb = root[0]?.querySelector(".rms-pos-category-breadcrumb");
		if (crumb) crumb.scrollLeft = frappe.utils.is_rtl() ? -crumb.scrollWidth : crumb.scrollWidth;
	}

	renderProducts() {
		const {selected, children, descendants} = this.categoryLevel();
		const searching = Boolean(this.state.search?.trim());
		const rows = (this.state.products || []).filter(row => !selected || (searching ? descendants.has(row.product_category) : row.product_category === selected.name));
		const showSections = !searching && (selected || this.state.catalog_mode === "categories");
		const showProducts = searching || selected || this.state.catalog_mode !== "categories";
		const heading = text => `<h2 class="rms-pos-menu-heading">${this.escape(text)}</h2>`;
		const cards = showSections && children.length ? `${heading(__("Sections"))}<div class="rms-pos-category-grid">${children.map(row => `<button type="button" class="rms-pos-category-card" data-category="${this.escape(row.name)}" data-category-card><span class="rms-pos-category-image">${row.image ? `<img src="${this.escape(row.image)}" alt="" loading="lazy" decoding="async">` : '<span aria-hidden="true">▦</span>'}</span><b>${this.escape(row.title)}</b><span>${__("Open section")} ›</span></button>`).join("")}</div>` : "";
		let products = "";
		if (showProducts && rows.length) {
			products = (cards ? heading(__("Products in this section")) : "") + rows.map((row) => `<button type="button" class="rms-pos-product" data-product="${this.escape(row.name)}" title="${this.escape(row.title)}" aria-label="${this.escape(row.title)}${row.price != null ? `, ${this.currency(row.price)}` : ""}" ${row.price == null && !row.has_options || !this.state.permissions.can_checkout ? "disabled" : ""}><span class="rms-pos-product-image">${row.image ? `<img src="${this.escape(row.image)}" alt="" loading="lazy" decoding="async">` : `<span aria-hidden="true">＋</span>`}</span><span class="rms-pos-product-category">${this.escape(row.category_title || "")}</span><b>${this.escape(row.title)}</b><span class="rms-pos-product-price${row.has_options ? " is-options" : ""}">${row.price == null ? row.has_options ? __("Choose option") : __("Price not set") : this.currency(row.price)}</span></button>`).join("");
		} else if (showProducts && this.state.catalog_loading) {
			products = `<div class="rms-pos-loading" role="status"><span class="rms-pos-loading-indicator" aria-hidden="true"></span><span>${__("Loading the menu…")}</span></div>`;
		} else if (!cards) {
			products = `<div class="rms-pos-empty"><div class="rms-pos-empty-icon">⌕</div><h2>${__("No products found")}</h2><p>${__("Check the Brand menu, product availability and search terms.")}</p></div>`;
		}
		let html = cards + products;
		if (!this.state.store || !this.state.brand || !this.state.order_type) html = `<div class="rms-pos-empty"><h2>${__("Browse the menu")}</h2><p>${__("Select a Store, Brand and Order Type to view products and prices.")}</p></div>`;
		else if (this.state.bootstrap_loading && !cards) html = `<div class="rms-pos-loading" role="status">${__("Loading the menu…")}</div>`;
		this.page.main.find('[data-role="catalog-count"]').text(this.state.store && this.state.brand && this.state.order_type ? (showProducts ? __("{0} products", [rows.length]) : __("{0} sections", [children.length])) : "");
		const grid = this.page.main[0]?.querySelector('[data-role="products"]');
		grid?.setAttribute("aria-busy", String(Boolean(this.state.catalog_loading)));
		if (!grid || grid.rmsCatalogMarkup !== html) {
			this.page.main.find('[data-role="products"]').html(html);
			if (grid) grid.rmsCatalogMarkup = html;
		}
		const key = JSON.stringify([this.state.store, this.state.brand, this.state.order_type, this.state.category, this.state.search, this.state.catalog_mode]);
		if (grid && !this.state.catalog_loading && grid.rmsCategoryKey !== key) {
			grid.rmsCategoryKey = key;
			if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) grid.animate?.([{ opacity: .6, transform: "translateY(3px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 140, easing: "ease-out" });
		}
	}

	renderCart() {
		const root = this.page.main;
		const orderClosed = ["Paid", "Cancelled"].includes(this.state.order_status);
		root.find('[data-action="order-notes"]').prop("disabled", orderClosed || !this.state.permissions.can_checkout)
			.text(this.state.order_notes ? __("Edit order comment") : __("Order comment"));
		root.find('[data-role="order-notes"]').text(this.state.order_notes || "").prop("hidden", !this.state.order_notes);
		const confirmed = ["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status);
				const cancellable = this.state.cart.filter(row => row.sent_to_kitchen && Number(row.qty) > Number(row.cancelled_qty || 0));
		const canCancel = !orderClosed && confirmed && cancellable.length && Boolean(this.state.session)
			&& !this.guestCheckState?.guest_checks?.length && (!this.state.cross_session_edit || this.state.permissions.can_edit_open_orders);
		const groups = { pending: [], confirmed: [], cancelled: [] };
		this.state.cart.forEach((row, index) => {
			const sent = Boolean(row.sent_to_kitchen);
			const remainingQty = Math.max(0, Number(row.qty) - Number(row.cancelled_qty || 0));
			const locked = orderClosed || sent || Boolean(row.read_only) || (row.saved_to_order && Boolean(this.guestCheckState?.guest_checks?.length));
			// Persistence does not confirm an item: unsent rows remain editable.
			const pending = !orderClosed && !sent;
			const status = orderClosed ? __(this.state.order_status) : sent ? (remainingQty ? __("Confirmed") : __("Voided")) : __("Not confirmed");
			const modifiers = row.modifier_labels || [];
			const comment = locked ? "" : `<button type="button" class="rms-pos-line-comment" data-action="notes" data-index="${index}" title="${__(row.notes ? "Edit comment" : "Add comment")}" aria-label="${__(row.notes ? "Edit comment" : "Add comment")}"><span aria-hidden="true">✎</span></button>`;
			const quantity = locked ? `<span class="rms-pos-fixed-qty" aria-label="${__("Quantity")}"><b>${remainingQty}</b></span>` : `<div class="rms-pos-qty"><button type="button" data-action="quantity" data-index="${index}" data-delta="-1" aria-label="${__("Decrease quantity")}">−</button><input type="number" data-quantity="${index}" min="0.001" step="${row.must_be_whole_number ? "1" : "any"}" value="${row.qty}" aria-label="${__("Ordered quantity")}"><button type="button" data-action="quantity" data-index="${index}" data-delta="1" aria-label="${__("Increase quantity")}">+</button></div>`;
			const card = `<article class="rms-pos-cart-line ${pending ? "is-unconfirmed" : "is-sent"} ${remainingQty === 0 ? "is-cancelled" : ""}" aria-label="${status}" data-cart-confirmation="${pending ? "pending" : "confirmed"}" data-cart-item="${this.escape(row.order_item_name || row.local_id || index)}">
				<div class="rms-pos-line-main"><b>${this.escape(row.title)}</b><span class="rms-pos-line-flags">${comment}${locked ? "" : `<button type="button" data-action="remove" data-index="${index}" aria-label="${__("Remove")}">×</button>`}</span></div>
				${row.option_parent ? `<small>${__("Option of")} ${this.escape(row.option_parent)}</small>` : ""}
				${modifiers.map(modifier => `<small>+ ${this.escape(modifier.title)}${modifier.price ? ` · ${this.currency(modifier.price)}` : ""}</small>`).join("")}
				${row.notes ? `<small class="rms-pos-line-note">${this.escape(row.notes)}</small>` : ""}
				${row.cancelled_qty ? `<small class="rms-pos-cancel-note">${__("Cancelled")}: ${this.escape(row.cancelled_qty)}</small>` : ""}
				<div class="rms-pos-line-bottom">${quantity}<strong>${this.currency(remainingQty * (Number(row.price) + modifiers.reduce((sum, modifier) => sum + Number(modifier.price || 0), 0)))}</strong></div></article>`;
			groups[remainingQty === 0 ? "cancelled" : pending ? "pending" : "confirmed"].push(card);
		});
		const section = (key, title) => !groups[key].length ? "" : key === "cancelled"
			? `<details class="rms-cart-section is-cancelled"><summary><strong>${title}</strong><span>${groups[key].length}</span></summary><div class="rms-cart-cancelled-rows">${groups[key].join("")}</div></details>`
			: `<section class="rms-cart-section is-${key}" aria-label="${title}">${groups[key].join("")}</section>`;
		if (!["pending", "confirmed"].includes(this.cartTab)) this.cartTab = groups.pending.length ? "pending" : "confirmed";
		if (orderClosed || (this.cartTab === "pending" && this.cartPendingCount > 0 && !groups.pending.length)) this.cartTab = "confirmed";
		this.cartPendingCount = groups.pending.length;
		root.find('[data-role="cart-tabs"]').html([ ["pending", __("Not confirmed"), groups.pending.length], ["confirmed", __("Confirmed"), groups.confirmed.length] ]
			.map(([key, title, count]) => `<button type="button" role="tab" id="rms-cart-tab-${key}" aria-controls="rms-cart-panel-${key}" aria-selected="${this.cartTab === key}" data-action="cart-tab" data-tab="${key}">${title}<span>${count}</span></button>`).join(""))
			.prop("hidden", !this.state.cart.length);
		root.find('[data-role="cart-actions"]').html(`<span>${__("Manage confirmed items")}</span><button type="button" data-action="cancel-confirmed-items">${__("Void")}</button>`).prop("hidden", !canCancel || this.cartTab !== "confirmed");
		const empty = text => `<p class="rms-cart-tab-empty">${text}</p>`;
		const panel = (key, content) => `<div role="tabpanel" id="rms-cart-panel-${key}" aria-labelledby="rms-cart-tab-${key}" data-cart-panel="${key}"${this.cartTab === key ? "" : " hidden"}>${content}</div>`;
		const html = this.state.cart.length ? panel("pending", section("pending", __("Not confirmed")) || empty(__("No unconfirmed items")))
			+ panel("confirmed", (section("confirmed", __("Confirmed")) || empty(__("No confirmed items yet"))) + section("cancelled", __("Voided items")))
			: `<div class="rms-pos-cart-empty"><span>＋</span><p>${__("Add products to begin")}</p></div>`;
		root.find('[data-role="cart"]').html(html);
		root.find('[data-role="cart-title"]').text(this.orderNumber(this.state.order_name) || __("New sale"));
		root.find('[data-action="new-sale"]').prop("hidden", !this.state.order_name);
		root.find('[data-role="ticket"]').text(orderClosed ? __(this.state.order_status) : confirmed ? __("In progress") : __("Draft"));
		root.find('[data-role="subtotal"]').text(this.state.totals ? this.currency(this.state.totals.subtotal) : "—");
		root.find('[data-role="discount"]').text(this.state.totals?.discount_amount ? `− ${this.currency(this.state.totals.discount_amount)}` : "—");
		root.find('[data-role="taxes"]').text(this.state.totals ? this.currency(this.state.totals.tax_total) : "—");
		const rawTotal = Number(this.state.totals?.grand_total || 0);
		const payableTotal = this.roundPosPayable(rawTotal);
		const roundingAdjustment = Number((payableTotal - rawTotal).toFixed(2));
		root.find('[data-role="rounding-row"]').prop("hidden", !this.state.totals || !roundingAdjustment);
		root.find('[data-role="rounding-adjustment"]').text(this.currency(roundingAdjustment));
		root.find('[data-role="total"]').text(this.state.totals ? this.currency(payableTotal) : "—");
		const orderCancelled = this.state.order_status === "Cancelled";
		const unconfirmedItems = this.state.cart.some((row) => !row.sent_to_kitchen);
		const awaitingOwnerPayment = Boolean(this.state.cross_session_edit && confirmed && !unconfirmedItems);
		const checkoutDisabled = Boolean(orderClosed || !this.state.cart.length || !this.state.session
			|| !this.state.permissions.can_checkout || this.state.busy || awaitingOwnerPayment);
		root.find('[data-action="discount"]').prop("hidden", true);
		root.find('[data-action="checkout"]').prop("disabled", checkoutDisabled)
			.text(orderCancelled ? __("Order cancelled") : awaitingOwnerPayment ? __("Payment by order owner") : confirmed && !unconfirmedItems ? __("Take Payment") : this.state.busy ? __("Saving…") : __("Confirm"));
	}
}
