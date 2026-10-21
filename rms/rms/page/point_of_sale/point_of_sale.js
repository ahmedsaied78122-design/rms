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
			brand: null, order_type: null, categories: [], category: null, catalog_mode: "products", products: [], cart: [], order_name: null,
			customer: null, dining_area: null, dining_table: null, tables: [], search: "", busy: false,
			bootstrap_loading: true, catalog_loading: false,
			discount_type: "Percentage", discount_scope: "Net Total", discount_value: 0, discount_reason: "" };
		this.catalogRequestId = 0;
		this.saveQueue = Promise.resolve();
		this.pendingLaunchContext = this.readLaunchContext();
		this.mount();
		this.bind();
		window.rmsPointOfSale = this;
		this.loadBootstrap(this.pendingLaunchContext?.store || null);
	}

	readLaunchContext() {
		try {
			const raw = sessionStorage.getItem("rms-pos-launch-context");
			return raw ? JSON.parse(raw) : null;
		} catch (_) { return null; }
	}

	call(method, args = {}) {
		return new Promise((resolve, reject) => frappe.call({ method: `rms.api.pos.${method}`, args,
			callback: (r) => resolve(r.message), error: (e) => reject(e) }));
	}

	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }
	currency(value) { return format_currency(value || 0, this.state.currency || undefined); }

	getSuggestedPaymentAmounts(total) {
		const due = Math.max(0, Number(total) || 0);
		if (!due) return [];
		const nextTen = Math.ceil((due - 1e-9) / 10) * 10;
		const values = [due, nextTen, nextTen + 10, Math.ceil((due - 1e-9) / 50) * 50];
		return [...new Set(values.map((value) => Math.round(value * 100) / 100))];
	}

	handlePaymentKey(key) {
		const input = this.paymentInput || this.page.main[0].querySelector("[data-payment-amount], [data-guest-amount]");
		if (!input) return;
		const value = String(input.value || "");
		input.value = key === "C" ? "" : `${value}${key}`;
		input.dispatchEvent(new Event("input", { bubbles: true }));
	}

	mount() {
		this.page.main.html(`
			<section class="rms-pos-shell" aria-label="${__("Point of Sale")}">
				<header class="rms-pos-topbar">
					<div class="rms-pos-brand"><span class="rms-pos-mark" aria-hidden="true">R</span><div><strong>RMS</strong><small>${__("Restaurant & Retail")}</small></div></div>
					<div class="rms-pos-context-fields" aria-label="${__("Sale setup")}">
						<label>${__("Store")}<select data-select="store"><option value="">${__("Select Store")}</option></select></label>
						<label>${__("Brand")}<select data-select="brand" disabled></select></label>
						<label>${__("Order Type")}<select data-select="order_type" disabled></select></label>
					</div>
					<div class="rms-pos-header-actions">
						<button class="rms-pos-quiet-action rms-pos-switch-apps" data-action="switch-apps">${__("Switch Apps")}</button>
						<div class="rms-pos-session-status" data-role="context"><span class="rms-pos-live"></span><span>${__("Cashier session closed")}</span></div>
						<button class="rms-pos-quiet-action" data-action="expenses">${__("Expenses")}</button>
						<button class="rms-pos-quiet-action" data-action="review-expenses" hidden>${__("Review Expenses")}</button>
						<button class="rms-pos-quiet-action" data-action="returns" data-capability="can_request_returns">${__("Returns")}</button>
						<button class="rms-pos-quiet-action" data-action="sales-history" data-capability="can_view_sales_history">${__("Sales History")}</button>
						<button class="rms-pos-quiet-action" data-action="open-orders" data-capability="can_view_open_orders">${__("Open Orders")}</button>
						<button class="rms-pos-quiet-action" data-action="table-map" data-capability="can_view_tables">${__("Tables")}</button>
						<button class="rms-pos-quiet-action" data-action="kitchen-display">${__("Kitchen")}</button>
						<button class="rms-pos-session-action" data-action="session">${__("Open Session")}</button>
					</div>
				</header>
				<div class="rms-pos-layout">
					<main class="rms-pos-catalog">
						<div class="rms-pos-heading"><div><span class="rms-pos-eyebrow">${__("SELLING")}</span><h1>${__("Build an order")}</h1><p data-role="catalog-hint">${__("Choose a Store and open a cashier session to start.")}</p></div><span class="rms-pos-catalog-count" data-role="catalog-count"></span></div>
						<div class="rms-pos-view-switch" role="tablist" aria-label="${__("Menu view")}"><button type="button" role="tab" data-catalog-mode="categories">${__("Categories")}</button><button type="button" role="tab" data-catalog-mode="products" aria-selected="true">${__("Products")}</button></div>
						<div class="rms-pos-toolbar"><label class="rms-pos-search"><span aria-hidden="true">⌕</span><input data-search type="search" placeholder="${__("Search products or scan a barcode")}" disabled autocomplete="off" aria-label="${__("Search products or scan a barcode")}"></label><button type="button" class="rms-pos-scan" data-action="scan" disabled aria-label="${__("Focus barcode search")}">▦</button></div>
						<nav class="rms-pos-categories" data-role="categories" aria-label="${__("Product categories")}"></nav>
						<div class="rms-pos-product-grid" data-role="products" aria-live="polite"></div>
					</main>
					<aside class="rms-pos-cart" aria-label="${__("Current order")}">
						<div class="rms-pos-cart-head"><div><span class="rms-pos-eyebrow">${__("CURRENT ORDER")}</span><h2 data-role="cart-title">${__("New sale")}</h2></div><div class="rms-pos-cart-head-tools"><button class="rms-pos-new-sale" data-action="new-sale" hidden>${__("New sale")}</button><span class="rms-pos-ticket" data-role="ticket">${__("Draft")}</span></div></div>
						<div class="rms-pos-order-meta"><label>${__("Customer")}<button class="rms-pos-meta-button" data-action="customer">${__("Walk-in Customer")}</button></label><div class="rms-pos-table-fields" data-role="dining-wrap" hidden><label>${__("Dining Area")}<select data-select="dining_area" disabled><option value="">${__("Not applicable")}</option></select></label><label>${__("Table")}<select data-select="dining_table" disabled><option value="">${__("Not applicable")}</option></select></label></div><label data-role="reference-wrap" hidden>${__("External Reference")}<input data-input="external_reference" /></label></div>
						<div class="rms-pos-cart-lines" data-role="cart" aria-live="polite"></div>
						<div class="rms-pos-summary"><div><span>${__("Subtotal")}</span><b data-role="subtotal">—</b></div><div><span>${__("Discount")}</span><b data-role="discount">—</b></div><button type="button" class="rms-pos-discount" data-action="discount" disabled>${__("Apply discount")}</button><div><span>${__("Taxes")}</span><b data-role="taxes">—</b></div><div class="rms-pos-total"><span>${__("Total")}</span><strong data-role="total">—</strong></div><button class="rms-pos-checkout" data-action="checkout" disabled>${__("Continue to payment")}</button></div>
					</aside>
				</div>
			</section>
			<section class="rms-pos-workspace-screen" data-screen="open-orders" hidden></section>
			<section class="rms-pos-workspace-screen" data-screen="tables" hidden></section>
			<section class="rms-pos-workspace-screen" data-screen="payment" hidden></section>`);
	}

	bind() {
		const root = this.page.main.get(0);
		root.addEventListener("change", (event) => {
			if (event.target.matches("[data-table-area-filter], [data-table-status-filter]")) return this.renderTableMap();
			if (event.target.matches("[data-split-check-toggle]")) return this.toggleSplitCheck(event.target.checked);
			if (event.target.matches("[data-payment-split-mode]")) return this.updateGuestSplitAmounts();
			if (event.target.matches("[data-item-guest]")) { this.paymentItemAssignments[event.target.dataset.itemGuest] = event.target.value === "" ? null : Number(event.target.value); return this.updateGuestSplitAmounts(); }
			if (event.target.matches("[data-guest-method]")) return;
			const quantity = event.target.closest("[data-quantity]");
			if (quantity) return this.updateQuantity(quantity);
			const select = event.target.closest("[data-select]");
			if (!select) return;
			const key = select.dataset.select;
			if (["brand", "order_type"].includes(key) && (this.state.cart.length || this.state.order_name)) {
				select.value = this.state[key] || "";
				return frappe.msgprint(__("Finish or start a new sale before changing the Brand or Order Type."));
			}
			this.state[key] = select.value || null;
			if (key === "store") this.onStoreChanged();
			if (key === "brand") this.onBrandChanged();
			if (key === "order_type") this.onOrderTypeChanged();
			if (key === "dining_area") this.onDiningAreaChanged();
			if (key === "dining_table") this.saveDraft();
		});
		root.addEventListener("input", (event) => {
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
			if (event.target.matches("[data-guest-name]")) { const row = event.target.closest(".rms-guest-check"); if (row && this.paymentGuests[Number(row.dataset.guestIndex)]) this.paymentGuests[Number(row.dataset.guestIndex)].name = event.target.value; this.renderPaymentItemAssignments(); }
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
		root.addEventListener("focusin", (event) => { if (event.target.matches("[data-payment-amount], [data-guest-amount]")) this.paymentInput = event.target; });
		root.addEventListener("keydown", (event) => {
			if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
				event.preventDefault();
				const search = root.querySelector("[data-search]");
				if (search && !search.disabled) search.focus();
				return;
			}
			if (!event.target.matches("[data-search]")) return;
			if (event.key === "Enter") { event.preventDefault(); this.searchAndAddBarcode(); }
		});
		root.addEventListener("click", (event) => {
			const modeButton = event.target.closest("[data-catalog-mode]");
			if (modeButton) { this.state.catalog_mode = modeButton.dataset.catalogMode; this.state.category = null; this.state.search = ""; root.querySelector("[data-search]").value = ""; this.renderCategories(); this.renderProducts(); this.loadCatalog(); return; }
			const categoryBack = event.target.closest("[data-category-back]");
			if (categoryBack) { this.state.category = categoryBack.dataset.categoryBack || null; this.state.search = ""; root.querySelector("[data-search]").value = ""; this.renderCategories(); this.renderProducts(); this.loadCatalog(); return; }
			const button = event.target.closest("[data-action]");
			if (button) return this.onAction(button.dataset.action, button.dataset);
			const product = event.target.closest("[data-product]");
			if (product) this.addProduct(product.dataset.product);
			const category = event.target.closest("[data-category]");
			if (category) {
				if (category.dataset.category !== this.state.category) this.state.search = "";
				this.state.category = category.dataset.category || null;
				if (category.hasAttribute("data-category-card")) {
					const selected = this.state.categories.find((row) => row.name === this.state.category);
					const hasChildren = this.state.categories.some((row) => row.parent_product_category === selected?.name);
					if (!hasChildren) this.state.catalog_mode = "products";
				}
				this.renderCategories(); this.renderProducts(); this.loadCatalog();
			}
		});
		this.render();
	}

	async loadBootstrap(store = null) {
		this.state.bootstrap_loading = true;
		try {
			const data = await this.call("get_bootstrap", { store });
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
				if (!this.state.order_type || !this.state.order_types.some((row) => row.name === this.state.order_type)) this.state.order_type = this.state.order_types[0]?.name || null;
				if (this.state.session?.payments) this.state.payment_methods = this.state.session.payments.map((row) => row.mode_of_payment);
				await this.loadContextDetails();
			}
			this.render();
			if (this.state.store && this.state.brand && this.state.order_type && this.state.session) await this.loadCatalog();
			await this.applyLaunchContext();
			this.state.bootstrap_loading = false;
			this.render();
		} catch (error) {
			this.state.bootstrap_loading = false;
			this.state.catalog_loading = false;
			this.render();
			this.showError(error);
		}
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
		this.renderFields();
	}

	async consumeLaunchContext() {
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
		await this.loadTables();
	}

	async onStoreChanged() {
		this.state.session = null; this.state.order_name = null; this.state.cart = []; this.state.brand = null; this.state.order_type = null;
		this.state.category = null; this.state.customer = null; this.state.dining_table = null; this.state.dining_area = null;
		if (this.state.store) await this.loadBootstrap(this.state.store); else this.render();
	}

	async onBrandChanged() {
		this.state.category = null; this.state.cart = []; this.state.order_name = null;
		if (this.state.brand) this.state.categories = await this.call("get_categories", { brand: this.state.brand, store: this.state.store });
		this.renderCategories(); this.loadCatalog(); this.saveDraft();
	}

	async onOrderTypeChanged() {
		this.state.cart = []; this.state.order_name = null;
		const selectedType = this.state.order_types.find((row) => row.name === this.state.order_type);
		if (!selectedType?.require_table) { this.state.dining_area = null; this.state.dining_table = null; }
		this.updateOrderTypeFields(); await this.loadTables(); this.loadCatalog(); this.saveDraft();
	}

	async loadTables() {
		this.state.tables = this.state.store ? await this.call("get_tables", { store: this.state.store, dining_area: this.state.dining_area }) : [];
		this.renderFields();
	}

	async onDiningAreaChanged() { this.state.dining_table = null; await this.loadTables(); this.saveDraft(); }

	async loadCatalog() {
		if (!this.state.store || !this.state.brand || !this.state.order_type || !this.state.session) {
			this.state.catalog_loading = false;
			this.renderProducts();
			return [];
		}
		const requestId = ++this.catalogRequestId;
		this.state.catalog_loading = true;
		this.renderProducts();
		try {
			const products = await this.call("get_catalog", { store: this.state.store, brand: this.state.brand,
				order_type: this.state.order_type, category: this.state.category, search: this.state.search, limit: 200 });
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
		if (["Paid", "Cancelled"].includes(this.state.order_status)) return frappe.msgprint(__("Start a new sale before adding products."));
		if (this.state.order_types.find((row) => row.name === this.state.order_type)?.require_table && !this.state.dining_table) return frappe.msgprint(__("Choose a dining table before adding items to a Dine In order."));
		try {
			const config = configured || await this.call("get_product_configuration", { product: productName,
				store: this.state.store, brand: this.state.brand, order_type: this.state.order_type });
			if (config.has_options) return this.showProductOptions(config, optionParent || config.name, entry);
			if (config.price == null) return frappe.msgprint(__("Set a Selling Price for this product before adding it to an order."));
			if (config.modifier_groups.length) return this.showModifiers(config, optionParent, entry);
			this.pushCart(productName, optionParent, [], config, entry);
		} catch (error) { this.showError(error); }
	}

	showProductOptions(config, rootOptionParent = config.name, entry = {}) {
		const selectable = (row) => row.has_options || row.price != null;
		const configs = [config];
		const selections = [];
		const modifierSelections = new Set();
		let selectedConfig = null;
		let loadingDepth = null;
		const renderFlow = () => {
			const levels = configs.map((parentConfig, depth) => {
				const optionRows = (parentConfig.options || []).map((row) => `<label class="rms-pos-option-row ${selectable(row) ? "" : "is-disabled"}"><input type="radio" name="rms-product-option-${depth}" data-option-depth="${depth}" value="${this.escape(row.name)}" ${selections[depth] === row.name ? "checked" : ""} ${selectable(row) && loadingDepth === null ? "" : "disabled"}><span>${this.escape(row.title)}</span><b>${row.has_options ? __("Choose options") : row.price == null ? __("Price not set") : this.currency(row.price)}</b></label>`).join("");
				return `<section class="rms-pos-option-level"><h4>${this.escape(parentConfig.title)}</h4><div class="rms-pos-choice-list">${optionRows || `<p class="text-muted">${__("No available options")}</p>`}</div></section>`;
			}).join("");
			let modifiers = "";
			if (selectedConfig && !selectedConfig.has_options && selectedConfig.modifier_groups.length) {
				modifiers = selectedConfig.modifier_groups.map((group, depth) => {
					const type = group.allow_multiple_selections ? "checkbox" : "radio";
					const choices = group.options.map((option) => {
						const key = `${group.name}:${option.name}`;
						return `<label class="rms-pos-modifier"><input type="${type}" name="rms-modifier-${depth}-${this.escape(group.name)}" data-modifier="${this.escape(option.name)}" data-group="${this.escape(group.name)}" data-modifier-key="${this.escape(key)}" data-price="${Number(option.selling_price) || 0}" ${modifierSelections.has(key) ? "checked" : ""}><span>${this.escape(option.title)}</span><b>${this.currency(option.selling_price)}</b></label>`;
					}).join("");
					if (group.allow_collapse) return `<details class="rms-pos-modifier-group" ${group.collapsed_by_default ? "" : "open"}><summary>${this.escape(group.title)}</summary><div>${choices}</div></details>`;
					return `<section class="rms-pos-modifier-group"><h4>${this.escape(group.title)}</h4><div>${choices}</div></section>`;
				}).join("");
			}
			const loading = loadingDepth !== null ? `<p class="rms-pos-option-loading" role="status">${__("Loading the next choice…")}</p>` : "";
			const ready = Boolean(selectedConfig && !selectedConfig.has_options && selectedConfig.price != null && loadingDepth === null);
			dialog.$wrapper.find("[data-option-flow]").html(`${levels}${loading}${modifiers}`);
			dialog.$wrapper.find(".modal-footer .btn-primary").prop("disabled", !ready);
		};
		const dialog = new frappe.ui.Dialog({ title: config.title, size: "large", fields: [
			{ fieldtype: "HTML", fieldname: "options_html", options: `<div class="rms-pos-option-intro">${__("Choose each option below. Your selections stay together on this screen.")}</div><div data-option-flow></div>` },
			{ fieldtype: "Float", fieldname: "quantity", label: __("Quantity"), default: entry.qty || 1, reqd: 1, precision: 3 },
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Comment for this item"), default: entry.notes || "", description: __("Optional note for the kitchen or cashier.") },
		], primary_action_label: __("Add to order"), primary_action: async (values) => {
			if (!selectedConfig || selectedConfig.has_options || loadingDepth !== null) return frappe.msgprint(__("Choose each required option first."));
			const qty = Number(values.quantity);
			if (!Number.isFinite(qty) || qty <= 0) return frappe.msgprint(__("Enter a quantity greater than zero."));
			if (selectedConfig.must_be_whole_number && !Number.isInteger(qty)) return frappe.msgprint(__("This option must be ordered in whole quantities."));
			const chosen = [...modifierSelections].map((key) => {
				const [modifier_group, modifier_product] = key.split(":");
				return { modifier_group, modifier_product, qty: 1 };
			});
			dialog.hide();
			this.pushCart(selectedConfig.name, rootOptionParent, chosen, selectedConfig, { qty, notes: values.notes || "" });
		} });
		dialog.$wrapper.addClass("rms-pos-option-dialog");
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
					const groupPrefix = `${event.currentTarget.dataset.group}:`;
					for (const selected of modifierSelections) if (selected.startsWith(groupPrefix)) modifierSelections.delete(selected);
				}
				modifierSelections.add(key);
			}
			else modifierSelections.delete(key);
		});
		dialog.$wrapper.on("hidden.bs.modal.rmsPosOptions", () => dialog.$wrapper.off(".rmsPosOptions"));
		dialog.show();
		renderFlow();
	}

	showModifiers(config, optionParent, entry = {}) {
		const html = config.modifier_groups.map((group) => {
			const type = group.allow_multiple_selections ? "checkbox" : "radio";
			const choices = group.options.map((option) => `<label class="rms-pos-modifier"><input type="${type}" name="rms-modifier-${this.escape(group.name)}" data-modifier="${this.escape(option.name)}" data-group="${this.escape(group.name)}" data-price="${Number(option.selling_price) || 0}"><span>${this.escape(option.title)}</span><b>${this.currency(option.selling_price)}</b></label>`).join("");
			if (group.allow_collapse) return `<details class="rms-pos-modifier-group" ${group.collapsed_by_default ? "" : "open"}><summary>${this.escape(group.title)}</summary><div>${choices}</div></details>`;
			return `<section class="rms-pos-modifier-group"><h4>${this.escape(group.title)}</h4><div>${choices}</div></section>`;
		}).join("");
		const dialog = new frappe.ui.Dialog({ title: config.title, size: "large", fields: [
			{ fieldtype: "HTML", fieldname: "modifier_html", options: `<div class="rms-pos-modifier-intro">${__("Choose any additions, set quantity, and leave a note.")}</div><div class="rms-pos-modifiers">${html}</div>` },
			{ fieldtype: "Float", fieldname: "quantity", label: __("Quantity"), default: entry.qty || 1, reqd: 1, precision: 3 },
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Comment for this item"), default: entry.notes || "" },
		],
			primary_action_label: __("Add to order"), primary_action: () => {
				const chosen = [...dialog.$wrapper.find("[data-modifier]:checked")].map((input) => ({ modifier_group: input.dataset.group, modifier_product: input.dataset.modifier, qty: 1 }));
				const qty = Number(dialog.get_value("quantity"));
				if (!Number.isFinite(qty) || qty <= 0) return frappe.msgprint(__("Enter a quantity greater than zero."));
				const notes = dialog.get_value("notes") || "";
				dialog.hide(); this.pushCart(config.name, optionParent, chosen, config, { qty, notes });
			}, secondary_action_label: __("Cancel"), secondary_action: () => dialog.hide() });
		dialog.$wrapper.addClass("rms-pos-option-dialog");
		dialog.show();
	}

	pushCart(product, optionParent, modifiers, config, entry = {}) {
		const info = this.state.products.find((row) => row.name === product);
		const basePrice = Number(config.price ?? info?.price) || 0;
		this.state.cart.push({ local_id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, saved_to_order: false, selling_product: product, option_parent: optionParent, title: info?.title || config.title,
			qty: Number(entry.qty) || 1, notes: entry.notes || "", sent_to_kitchen: false, uom: config.uom || info?.uom, must_be_whole_number: Boolean(config.must_be_whole_number ?? info?.must_be_whole_number), price: basePrice, modifiers, modifier_labels: modifiers.map((row) => ({ ...row, title: config.modifier_groups.flatMap((group) => group.options).find((option) => option.name === row.modifier_product)?.title,
			price: Number(config.modifier_groups.flatMap((group) => group.options).find((option) => option.name === row.modifier_product)?.selling_price) || 0 })) });
		this.state.order_status = this.state.order_status || "Open"; this.renderCart(); this.saveDraft();
	}

	orderPayload() {
		return { name: this.state.order_name, store: this.state.store, restaurant_brand: this.state.brand,
			order_type: this.state.order_type, customer: this.state.customer, external_reference: this.state.external_reference,
			dining_area: this.state.dining_area, dining_table: this.state.dining_table,
			discount_type: this.state.discount_type, discount_scope: this.state.discount_scope,
			discount_value: this.state.discount_value, discount_reason: this.state.discount_reason,
			append_only: Boolean(this.state.cross_session_edit),
			items: this.state.cart.filter((row) => {
				if (this.state.cross_session_edit) return !row.saved_to_order;
				if (!["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status)) return true;
				return !row.sent_to_kitchen && !row.saved_to_order;
			}).map((row) => ({ client_key: row.local_id, selling_product: row.selling_product, option_parent: row.option_parent,
				qty: row.qty, notes: row.notes || "", modifiers: row.modifiers })) };
	}

	async persistDraft() {
		if (!this.state.session || !this.state.cart.length || !this.state.store || !this.state.brand || !this.state.order_type) return null;
		const save = async () => {
			const result = await this.call("save_order", { order_data: JSON.stringify(this.orderPayload()) });
			this.state.order_name = result.name; this.state.totals = result;
			for (const appended of result.appended_items || []) {
				const line = this.state.cart.find((row) => row.local_id === appended.client_key);
				if (line) { line.saved_to_order = true; line.order_item_name = appended.name; }
			}
			this.renderCart();
			return result;
		};
		const queued = this.saveQueue.catch(() => {}).then(save);
		this.saveQueue = queued;
		return queued;
	}

	async saveDraft() {
		if (!this.state.session || !this.state.cart.length || !this.state.store || !this.state.brand || !this.state.order_type) return;
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
	async onAction(action, data) {
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
			try { await this.call("cancel_order", { order_name: data.order }); frappe.show_alert({ message: __("Order cancelled"), indicator: "orange" }); return this.showOpenOrders(); }
			catch (error) { return this.showError(error); }
		}
		if (action === "cancel-confirmed-item") return this.cancelConfirmedItem(Number(data.index));
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
		if (action === "payment-back") { this.paymentApprovalOnly = false; this.page.main.find('[data-screen="payment"]').prop("hidden", true); this.page.main.find(".rms-pos-shell").prop("hidden", false); return; }
		if (action === "payment-pay") return this.submitPayment(false);
		if (action === "payment-pay-print") return this.submitPayment(true);
		if (action === "payment-key") return this.handlePaymentKey(data.key);
		if (action === "payment-discount-type") { this.setPaymentDiscountType(data.type); this.queuePaymentDiscountPreview(false); return; }
		if (action === "payment-discount-clear") return this.clearPaymentDiscountValue();
		if (action === "payment-open-discount") return this.openPaymentDiscountDialog();
		if (action === "payment-discount-close") return this.closePaymentDiscountDialog();
		if (action === "payment-discount-approver") return this.selectDiscountApprover(data.approver || "");
		if (action === "payment-discount-back-to-managers") { this.paymentDiscountApprovalApprover = null; return this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers || []); }
		if (action === "payment-discount-auth-method") return this.setDiscountApprovalMethod(data.method);
		if (action === "payment-print-only") return this.printOpenOrderCheck();
		if (action === "payment-guest-add") return this.changePaymentGuestCount(1);
		if (action === "payment-guest-remove") return this.changePaymentGuestCount(-1);
		if (action === "payment-apply-discount") return this.applyPaymentDiscount();
		if (action === "payment-quick") {
			return this.applySuggestedPaymentAmount(data.amount);
		}
		if (action === "switch-apps") return window.location.assign("/apps");
		if (action === "kitchen-display") return frappe.set_route("kitchen-display");
		if (action === "new-sale") {
			this.state.order_name = null; this.state.order_status = null; this.state.cart = []; this.state.totals = null;
			this.state.cross_session_edit = false;
			this.state.customer = this.state.default_customer || null; this.state.external_reference = null;
			this.state.discount_type = "Percentage"; this.state.discount_scope = "Net Total"; this.state.discount_value = 0; this.state.discount_reason = "";
			this.state.dining_table = null; this.renderCart(); this.renderFields(); return;
		}
		if (action === "session") return this.state.session ? this.closeSession() : this.openSession();
		if (action === "expenses") return this.openExpenses();
		if (action === "review-expenses") return this.reviewPendingExpenses();
		if (action === "checkout") return this.checkout();
		if (action === "sales-history") return this.showSalesHistory();
		if (action === "customer") return this.chooseCustomer();
		if (action === "open-orders") return this.showOpenOrders();
		if (action === "table-map") return this.showTableMap();
		if (action === "returns") return this.startReturnFlow();
		if (action === "discount") return this.editDiscount();
		if (action === "notes") return this.editItemNotes(data.index);
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

	async openExpenses() {
		if (!this.state.session || this.state.session.status !== "Open") return frappe.msgprint(__("Open a cashier session before recording an expense."));
		try {
			const context = await this.call("get_expense_context");
			const methods = (this.state.session.payments || []).map((row) => row.mode_of_payment);
			const fields = [
				{ fieldtype: "Select", fieldname: "expense_category", label: __("Expense Category"),
					options: (context.categories || []).map((row) => row.name).join("\n"), reqd: 1 },
				{ fieldtype: "Currency", fieldname: "amount", label: __("Amount"), options: context.currency, reqd: 1 },
				{ fieldtype: "Select", fieldname: "mode_of_payment", label: __("Mode of Payment"), options: methods.join("\n"), reqd: 1 },
				{ fieldtype: "Small Text", fieldname: "remarks", label: __("Notes") },
				{ fieldtype: "Attach", fieldname: "attachment", label: __("Receipt Attachment") }
			];
			const dialog = new frappe.ui.Dialog({ title: __("Shift Expenses"), fields,
				primary_action_label: __("Record Expense"), primary_action: async (values) => {
					try {
						const result = await this.call("create_shift_expense", {
							expense_category: values.expense_category, amount: values.amount,
							mode_of_payment: values.mode_of_payment, remarks: values.remarks, attachment: values.attachment
						});
						dialog.hide();
						if (result.requires_approval) frappe.msgprint(__("Expense is waiting for manager approval. After the manager issues a code, reopen Expenses to authorize it.") + ` · ${this.escape(result.name)}`);
						else frappe.show_alert({ message: __("Expense posted") + ` · ${result.name}`, indicator: "green" });
						await this.loadBootstrap(this.state.store);
					} catch (error) { this.showError(error); }
				}
			});
			if (context.pending_expenses?.length) {
				dialog.set_secondary_action_label(__("Authorize Pending Expense"));
				dialog.set_secondary_action(() => { dialog.hide(); this.authorizePendingExpense(context.pending_expenses); });
			}
			dialog.show();
		} catch (error) { this.showError(error); }
	}

	async authorizePendingExpense(pendingExpenses) {
		const options = pendingExpenses.map((row) => row.name);
		const dialog = new frappe.ui.Dialog({ title: __("Authorize Pending Expense"),
			fields: [
				{ fieldtype: "Link", fieldname: "expense_name", label: __("Pending Expense"), options: "Shift Expense", reqd: 1,
					get_query: () => ({ filters: { name: ["in", options], status: "Pending Approval" } }) },
				{ fieldtype: "Data", fieldname: "approval_code", label: __("Manager Approval Code"), description: __("Ask a POS Manager to issue a short lived code for this expense."), reqd: 1 }
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
		dialog.show();
	}

	async reviewPendingExpenses() {
		try {
			const pending = await this.call("get_manager_pending_shift_expenses");
			if (!pending?.length) return frappe.msgprint(__("There are no pending expenses in your assigned Stores."));
			const rows = pending.map((row) => `<tr><td><b>${this.escape(row.name)}</b><small>${this.escape(row.store)} · ${this.escape(row.cashier_full_name || "")}</small></td><td>${this.escape(row.expense_category)}</td><td>${this.escape(format_currency(row.amount || 0, row.currency))}</td><td>${this.escape(row.mode_of_payment)}</td><td>${this.escape(frappe.datetime.str_to_user(row.creation))}</td></tr>`).join("");
			const names = pending.map((row) => row.name);
			const dialog = new frappe.ui.Dialog({ title: __("Pending POS Expenses"), size: "large", fields: [
				{ fieldtype: "HTML", fieldname: "pending_summary", options: `<div class="rms-expense-review-list"><table><thead><tr><th>${__("Expense / Cashier")}</th><th>${__("Category")}</th><th>${__("Amount")}</th><th>${__("Payment Method")}</th><th>${__("Requested")}</th></tr></thead><tbody>${rows}</tbody></table></div>` },
				{ fieldtype: "Link", fieldname: "expense_name", label: __("Pending Expense"), options: "Shift Expense", reqd: 1,
					get_query: () => ({ filters: { name: ["in", names], status: "Pending Approval" } }) }
			], primary_action_label: __("Issue Approval Code"), primary_action: async (values) => {
				if (!values?.expense_name) return;
				try {
					const result = await this.call("issue_shift_expense_approval_code", { expense_name: values.expense_name });
					dialog.hide();
					const codeDialog = new frappe.ui.Dialog({ title: __("One Time Expense Approval Code"), fields: [
						{ fieldtype: "Data", fieldname: "code", label: __("Share this code with the cashier"), read_only: 1, default: result.code },
						{ fieldtype: "Datetime", fieldname: "expires_at", label: __("Expires At"), read_only: 1, default: result.expires_at }
					], primary_action_label: __("Done"), primary_action: () => codeDialog.hide() });
					codeDialog.show();
				} catch (error) { this.showError(error); }
			} });
			dialog.set_secondary_action_label(__("Reject Expense"));
			dialog.set_secondary_action(() => {
				const values = dialog.get_values();
				if (!values?.expense_name) return frappe.msgprint(__("Choose a pending expense first."));
				const expenseName = values.expense_name;
				dialog.hide();
				const rejection = new frappe.ui.Dialog({ title: __("Reject Shift Expense"), fields: [
					{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason"), reqd: 1 }
				], primary_action_label: __("Reject Expense"), primary_action: async (values) => {
					try {
						await this.call("reject_shift_expense", { expense_name: expenseName, reason: values.reason });
						rejection.hide();
						frappe.show_alert({ message: __("Expense rejected"), indicator: "orange" });
					} catch (error) { this.showError(error); }
				} });
				rejection.show();
			});
			dialog.show();
		} catch (error) { this.showError(error); }
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
			const confirmed = ["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status);
			const hasUnconfirmedItems = this.state.cart.some((row) => !row.sent_to_kitchen);
			const saved = confirmed && !hasUnconfirmedItems ? null : await this.persistDraft();
			if (!saved && !confirmed) return;
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

	async chooseCustomer() {
		const customers = await this.call("get_customers", {});
		const dialog = new frappe.ui.Dialog({ title: __("Choose Customer"), fields: [{ fieldtype: "Link", fieldname: "customer", label: __("Customer"), options: "Customer", default: this.state.customer }],
			primary_action_label: __("Apply"), primary_action: (values) => { this.state.customer = values.customer || null; dialog.hide(); this.renderCart(); this.saveDraft(); },
			secondary_action_label: __("Walk-in"), secondary_action: () => { this.state.customer = null; dialog.hide(); this.renderCart(); this.saveDraft(); } });
		dialog.show();
	}

	editItemNotes(index) {
		const row = this.state.cart[Number(index)];
		if (!row || row.read_only || row.sent_to_kitchen || ["Paid", "Cancelled"].includes(this.state.order_status)) return;
		const dialog = new frappe.ui.Dialog({ title: __("Comment for {0}", [row.title]), fields: [
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Comment"), default: row.notes || "", description: __("This comment is saved with the item and shown to preparation staff.") },
		], primary_action_label: __("Save comment"), primary_action: async (values) => {
			const notes = dialog.get_value("notes") || "";
			row.notes = notes;
			try {
				await this.flushDraftSave();
				if (!row.saved_to_order || !row.order_item_name) await this.persistDraft();
				if (!row.order_item_name) {
					const order = await this.call("get_order", { order_name: this.state.order_name });
					const knownItems = new Set(this.state.cart.filter((item) => item !== row).map((item) => item.order_item_name).filter(Boolean));
					const matchingItem = [...(order.items || [])].reverse().find((item) => item.selling_product === row.selling_product && !knownItems.has(item.name));
					if (matchingItem) { row.saved_to_order = true; row.order_item_name = matchingItem.name; }
				}
				if (!row.saved_to_order || !row.order_item_name) throw new Error(__("The item comment could not be saved. Please try again."));
				await this.call("update_order_item_notes", { order_name: this.state.order_name, item_name: row.order_item_name, notes });
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
			return `<article class="rms-open-order-card"><div class="rms-open-order-info"><b>${this.escape(row.check_label || row.name)}</b><span>${this.escape(row.order_type || "")} · ${row.dining_table ? this.escape(row.dining_table) : __("No table")}</span><small>${this.escape(row.name)} · ${this.escape(row.cashier || "")}</small><div class="rms-open-order-prep">${preparationStatus}</div></div><strong class="rms-open-order-total">${this.currency(row.grand_total)}</strong><div class="rms-open-order-actions">${openAction}${splitAction}${moveAction}${own && this.state.permissions.can_cancel_orders ? `<button class="rms-screen-danger" data-action="cancel-pos-order" data-order="${this.escape(row.name)}">${__("Cancel")}</button>` : ""}</div></article>`;
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
				{ fieldtype: "HTML", fieldname: "transfer_hint", options: `<div class="rms-transfer-intro"><p>${__("Move this check to an available table.")}</p><strong>${this.escape(order.check_label || order.name)}</strong><span>${this.escape(order.dining_table || "")}</span></div><div class="rms-table-destinations">${tableCards}</div>` },
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
		const total = Number(this.state.totals?.grand_total || 0);
		this.paymentTotal = total;
		this.paymentDiscount = { type: this.state.discount_type || "Percentage", value: Number(this.state.discount_value || 0), reason: this.state.discount_reason || "" };
		this.paymentDiscountApprovalCode = null;
		this.paymentDiscountApprovalApprover = null;
		this.paymentDiscountApprovers = [];
		const approvalOnly = Boolean(this.paymentApprovalOnly);
		const canEditDiscount = this.state.permissions.can_apply_manual_discount || approvalOnly;
		const firstGuestAmount = Math.floor(total * 50) / 100;
		const methodFields = methods.map((row, index) => `<label class="rms-payment-method"><span>${this.escape(row.mode_of_payment)}${row.default ? ` <small>${__("Default")}</small>` : ""}</span><input type="number" min="0" step="0.01" data-payment-amount data-method="${this.escape(row.mode_of_payment)}" value="${index === 0 ? total.toFixed(2) : "0.00"}" aria-label="${__("Amount for")} ${this.escape(row.mode_of_payment)}"></label>`).join("");
		this.paymentGuestMethods = methods;
		this.paymentGuests = methods.length ? [1, 2].map((number) => ({ name: __("Guest {0}", [number]), method: methods[0].mode_of_payment, amount: number === 1 ? firstGuestAmount : total - firstGuestAmount })) : [];
		const guests = this.renderPaymentGuests();
		const discountTools = canEditDiscount ? `<div class="rms-payment-discount-launch"><span>${__("Discount")}: <b data-discount-preview>${this.currency(this.state.totals?.discount_amount || 0)}</b></span><button type="button" class="rms-screen-secondary" data-action="payment-open-discount">${__("Add discount")}</button></div>` : "";
		const quickAmounts = this.getSuggestedPaymentAmounts(total);
		const quick = quickAmounts.map((amount) => `<button type="button" data-action="payment-quick" data-amount="${amount}">${amount === total ? __("Exact") : this.currency(amount)}</button>`).join("");
		const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "C"].map((key) => `<button type="button" data-action="payment-key" data-key="${key}">${key}</button>`).join("");
		this.page.main.find('[data-screen="payment"]').html(`<header class="rms-workspace-head"><button class="rms-screen-back" data-action="payment-back">‹ ${__("Back to order")}</button><div><span class="rms-pos-eyebrow">${approvalOnly ? __("DISCOUNT APPROVAL") : __("CHECKOUT")}</span><h1>${approvalOnly ? __("Approve cashier discount") : __("Take Payment")}</h1><p>${this.escape(this.state.order_name || "")} · ${this.escape(this.state.order_type || "")}</p></div><strong class="rms-payment-total">${this.currency(total)}</strong></header><div class="rms-payment-layout"><section class="rms-payment-panel">${approvalOnly ? "" : `<h2>${__("Payment methods")}</h2><p>${__("Allocate the total across payment methods or guests.")}</p>`}${discountTools}${approvalOnly ? "" : `<div class="rms-payment-method-list">${methodFields}</div><label class="rms-split-check-toggle"><input type="checkbox" data-split-check-toggle> ${__("Split check")}</label><div class="rms-guest-checks" data-guest-checks hidden><div class="rms-split-toolbar"><label>${__("Split by")}<select data-payment-split-mode><option value="people">${__("People")}</option><option value="items">${__("Items")}</option></select></label><button type="button" data-action="payment-guest-add">+ ${__("Add person")}</button><button type="button" data-action="payment-guest-remove">− ${__("Remove person")}</button></div><div data-payment-guests>${guests}</div><div class="rms-item-assignments" data-item-assignments hidden></div></div><div class="rms-payment-shortcuts"><span>${__("Suggested payment amounts")}</span>${quick}</div><div class="rms-payment-sum">${__("Remaining")}: <b data-payment-remaining>${this.currency(total)}</b></div><div class="rms-payment-change" data-payment-change hidden>${__("Change")}: <b data-change-amount>${this.currency(0)}</b></div><div class="rms-payment-actions"><button class="rms-screen-secondary" data-action="payment-print-only">${__("Print only")}</button><button class="rms-screen-secondary" data-action="payment-pay-print">${__("Pay and print")}</button><button class="rms-screen-primary" data-action="payment-pay">${__("Pay only")}</button></div>`}</section>${approvalOnly ? "" : `<section class="rms-payment-panel rms-payment-keypad"><h2>${__("Keypad")}</h2><p>${__("Select an amount field, then enter the amount.")}</p><div>${keys}</div></section>`}</div><div data-discount-dialog-root></div>`);
		this.paymentItemAssignments = {};
		this.renderPaymentItemAssignments();
		this.page.main.find(".rms-pos-shell").prop("hidden", true);
		this.page.main.find('[data-screen="payment"]').prop("hidden", false);
		this.updatePaymentTotal();
		this.updateGuestSplitAmounts();
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

	renderPaymentGuests() {
		const methods = this.paymentGuestMethods || [];
		return (this.paymentGuests || []).map((guest, index) => `<article class="rms-guest-check" data-guest-index="${index}"><label>${__("Guest {0}", [index + 1])}<input type="text" data-guest-name value="${this.escape(guest.name || __("Guest {0}", [index + 1]))}" aria-label="${__("Guest {0}", [index + 1])}"></label><label>${__("Payment method")}<select data-guest-method>${methods.map((row) => `<option value="${this.escape(row.mode_of_payment)}" ${row.mode_of_payment === guest.method ? "selected" : ""}>${this.escape(row.mode_of_payment)}</option>`).join("")}</select></label><label>${__("Amount tendered")}<input type="number" data-guest-amount data-manual="${guest.manual ? "1" : ""}" min="0" step="0.01" value="${Number(guest.amount || 0).toFixed(2)}"></label><small>${__("Share due")}: <b data-guest-due>${this.currency(guest.due || guest.amount || 0)}</b></small></article>`).join("");
	}

	changePaymentGuestCount(delta) {
		if (this.page.main[0]?.querySelector("[data-payment-guests]")) {
			this.paymentGuests = [...this.page.main[0].querySelectorAll(".rms-guest-check")].map((section) => ({
				name: section.querySelector("[data-guest-name]").value,
				method: section.querySelector("[data-guest-method]").value,
				amount: Number(section.querySelector("[data-guest-amount]").value || 0),
				manual: Boolean(section.querySelector("[data-guest-amount]").dataset.manual),
			}));
		}
		const count = this.paymentGuests?.length || 0;
		if (delta > 0 && count >= 10) return frappe.msgprint(__("A check can be split between up to ten people."));
		if (delta < 0 && count <= 2) return frappe.msgprint(__("A split check needs at least two people."));
		const total = Number(this.paymentTotal || 0);
		if (delta > 0) this.paymentGuests.push({ name: __("Guest {0}", [count + 1]), method: this.paymentGuestMethods?.[0]?.mode_of_payment, amount: total / (count + 1) });
		else this.paymentGuests.pop();
		this.page.main[0].querySelector("[data-payment-guests]").innerHTML = this.renderPaymentGuests();
		this.renderPaymentItemAssignments();
		this.updateGuestSplitAmounts();
	}

	renderPaymentItemAssignments() {
		const target = this.page.main[0]?.querySelector("[data-item-assignments]");
		if (!target) return;
		const items = (this.state.cart || []).filter((row) => row.order_item_name && Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0)) > 0);
		target.innerHTML = items.map((row) => `<label class="rms-item-assignment">${this.escape(row.title)} <select data-item-guest="${this.escape(row.order_item_name)}"><option value="">${__("Choose person")}</option>${this.paymentGuests.map((guest, index) => `<option value="${index}" ${this.paymentItemAssignments?.[row.order_item_name] === index ? "selected" : ""}>${this.escape(guest.name)}</option>`).join("")}</select></label>`).join("");
	}

	updateGuestSplitAmounts() {
		if (!this.page.main[0]?.querySelector("[data-split-check-toggle]")?.checked) return;
		const mode = this.page.main[0].querySelector("[data-payment-split-mode]")?.value || "people";
		const total = Number(this.paymentTotal || 0);
		const dues = this.paymentGuests.map(() => 0);
		if (mode === "people") {
			const share = Math.floor(total * 100 / this.paymentGuests.length) / 100;
			dues.fill(share);
			dues[dues.length - 1] += total - share * dues.length;
		} else {
			const assignmentSelects = [...this.page.main[0].querySelectorAll("[data-item-guest]")];
			const lines = (this.state.cart || []).filter((row) => row.order_item_name && Number(row.qty || 0) > Number(row.cancelled_qty || 0));
			const amountFor = (row) => Math.max(0, Number(row.qty || 0) - Number(row.cancelled_qty || 0)) * (Number(row.price || 0) + (row.modifier_labels || []).reduce((sum, item) => sum + Number(item.price || 0), 0));
			const subtotal = lines.reduce((sum, row) => sum + amountFor(row), 0);
			for (const select of assignmentSelects) {
				if (select.value === "") continue;
				const row = lines.find((item) => item.order_item_name === select.dataset.itemGuest);
				if (row && subtotal > 0) dues[Number(select.value)] += total * amountFor(row) / subtotal;
			}
			const assignedGuests = dues.map((amount, index) => amount > 0 ? index : -1).filter((index) => index >= 0);
			if (assignedGuests.length) {
				let allocated = 0;
				for (const index of assignedGuests.slice(0, -1)) { dues[index] = Math.round(dues[index] * 100) / 100; allocated += dues[index]; }
				const last = assignedGuests[assignedGuests.length - 1]; dues[last] = Math.round((total - allocated) * 100) / 100;
			}
		}
		const sections = [...this.page.main[0].querySelectorAll(".rms-guest-check")];
		sections.forEach((section, index) => {
			const due = Math.round((dues[index] || 0) * 100) / 100;
			const dueLabel = section.querySelector("[data-guest-due]");
			dueLabel.textContent = this.currency(due); dueLabel.dataset.amount = due.toFixed(2);
			const amount = section.querySelector("[data-guest-amount]");
			if (!amount.dataset.manual) amount.value = due.toFixed(2);
		});
		this.page.main.find("[data-item-assignments]").prop("hidden", mode !== "items");
		this.updatePaymentTotal();
	}

	openPaymentDiscountDialog() {
		const root = this.page.main[0].querySelector("[data-discount-dialog-root]");
		if (!root) return;
		root.innerHTML = this.renderPaymentDiscountDialog();
		root.querySelector("[data-discount-dialog]")?.focus();
	}

	closePaymentDiscountDialog(preserveApproval = false) {
		const root = this.page?.main?.[0]?.querySelector("[data-discount-dialog-root]");
		if (root) root.innerHTML = "";
		if (!preserveApproval && !this.paymentDiscountApprovalCode) this.clearDiscountApprovalPrompt();
	}

	renderPaymentDiscountDialog() {
		const type = this.paymentDiscount.type;
		const value = Number(this.paymentDiscount.value || 0);
		const max = Number(this.state.totals?.grand_total || 0);
		const percentageTicks = [0, 10, 20, 30, 50, 80, 100].map((tick) => `<span style="left:${tick}%">${tick}%</span>`).join("");
		return `<div class="rms-discount-backdrop" data-action="payment-discount-backdrop"><section class="rms-discount-dialog" data-discount-dialog role="dialog" aria-modal="true" aria-labelledby="rms-discount-title" tabindex="-1"><header><h2 id="rms-discount-title">${__("Add Discount")}</h2><button type="button" data-action="payment-discount-close" aria-label="${__("Close")}">×</button></header><div class="rms-discount-dialog-body"><div data-discount-edit-fields><div class="rms-discount-type-wrap"><span>${__("Discount type")}</span><input type="hidden" data-pay-discount-type value="${this.escape(type)}"><div class="rms-discount-type-switch" role="group" aria-label="${__("Discount type")}"><button type="button" data-action="payment-discount-type" data-type="Amount" aria-pressed="${type === "Amount"}">${__("Amount")}</button><button type="button" data-action="payment-discount-type" data-type="Percentage" aria-pressed="${type === "Percentage"}">${__("Percentage")}</button></div></div><div class="rms-discount-percentage" data-discount-range-wrap ${type === "Percentage" ? "" : "hidden"}><div class="rms-discount-value-heading"><span>${__("Discount Amount")}</span><strong><b data-discount-percent-label>${type === "Percentage" ? value : 0}%</b></strong></div><input type="range" data-pay-discount-value="percentage" min="0" max="100" step="5" value="${type === "Percentage" ? value : 0}" aria-label="${__("Discount percentage")}"><div class="rms-discount-ticks" aria-hidden="true">${percentageTicks}</div></div><label class="rms-discount-amount-wrap" data-discount-amount-wrap ${type === "Amount" ? "" : "hidden"}>${__("Discount amount")}<span class="rms-discount-value-field"><input type="number" data-pay-discount-value="amount" min="0" max="${max}" step="0.01" value="${type === "Amount" ? value : 0}" aria-label="${__("Discount amount")}"><button type="button" data-action="payment-discount-clear" aria-label="${__("Clear discount amount")}">×</button></span></label><label class="rms-discount-reason">${__("Reason")}<input type="text" data-pay-discount-reason value="${this.escape(this.paymentDiscount.reason)}" placeholder="${__("Reason for discount")}"></label><div class="rms-discount-dialog-summary">${__("Discount")}: <b data-discount-preview>${this.currency(this.state.totals?.discount_amount || 0)}</b></div></div><div class="rms-discount-approval-feedback" data-discount-approval-feedback aria-live="polite"></div></div><footer><button type="button" class="rms-screen-secondary" data-action="payment-discount-close">${__("Cancel")}</button><button type="button" class="rms-screen-primary rms-discount-apply" data-action="payment-apply-discount" ${this.paymentDiscount.reason.trim() ? "" : "disabled"}>${__("Apply")}</button></footer></section></div>`;
	}

	async printOpenOrderCheck() {
		if (this.paymentSubmitting) return;
		const printWindow = window.open("about:blank", "_blank");
		if (!printWindow) return frappe.msgprint(__("Your browser blocked the print window. Allow pop-ups for this POS, then try again."));
		this.paymentSubmitting = true;
		const button = this.page.main.find('[data-action="payment-print-only"]');
		button.prop("disabled", true);
		try {
			const html = await this.call("get_open_order_check_print_html", { order_name: this.state.order_name });
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
		if (!button || button.hidden) return;
		const codeInput = this.page.main[0].querySelector("[data-discount-approval-code]");
		button.disabled = codeInput ? !codeInput.value.trim()
			: !this.page.main[0].querySelector("[data-pay-discount-reason]")?.value.trim();
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
		this.updateDiscountApplyState();
	}

	selectDiscountApprover(approver) {
		this.paymentDiscountApprovalApprover = approver || null;
		this.paymentDiscountAuthMethod = "OTP";
		this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers || [], approver || "", "", "", "OTP");
		this.updateDiscountApplyState();
		this.page.main[0].querySelector("[data-discount-approval-code]")?.focus();
	}

	setDiscountApprovalMethod(method) {
		if (!["OTP", "Password"].includes(method) || !this.paymentDiscountApprovalApprover) return;
		this.paymentDiscountAuthMethod = method;
		this.renderDiscountApprovalPrompt(this.paymentDiscountApprovers || [], this.paymentDiscountApprovalApprover,
			"", "", method);
		this.page.main[0].querySelector("[data-discount-approval-code]")?.focus();
	}

	clearPaymentDiscountValue() {
		const type = this.page.main.find("[data-pay-discount-type]").val() || "Percentage";
		const input = this.page.main[0].querySelector(`[data-pay-discount-value="${type === "Amount" ? "amount" : "percentage"}"]`);
		if (!input) return;
		input.value = "0";
		input.dispatchEvent(new Event("input", { bubbles: true }));
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
					${passwordMode ? `<p class="rms-discount-manager-note">${this.escape(__("Use the fixed approval password configured on this manager's POS User profile."))}</p>` : ""}
					<button type="button" class="rms-discount-back" data-action="payment-discount-back-to-managers">${this.escape(__("Choose another manager"))}</button>
					${errorMessage ? `<p class="rms-discount-error">${this.escape(errorMessage)}</p>` : ""}
				</div>`;
			const applyButton = this.page.main[0].querySelector("[data-action='payment-apply-discount']");
		if (applyButton) { applyButton.textContent = __("Verify and Apply"); applyButton.hidden = false; this.updateDiscountApplyState(); }
			return;
		}
		const options = approvers.map((row) => `<button type="button" class="rms-discount-approver" data-action="payment-discount-approver" data-approver="${this.escape(row.user)}">${this.escape(row.full_name)}<small>${this.escape(row.user)}</small></button>`).join("");
		const title = this.page.main[0].querySelector("#rms-discount-title");
		if (title) title.textContent = __("Select Authorizer");
		feedback.innerHTML = `<div class="rms-discount-approval-flow"><div class="rms-discount-stepper"><b>1</b><i>›</i><span>2</span></div><h3>${this.escape(__("Select Authorizer"))}</h3><p>${this.escape(__("Select a manager to approve this discount."))}</p><div class="rms-discount-approver-list">${options}</div>${errorMessage ? `<p class="rms-discount-error">${this.escape(errorMessage)}</p>` : ""}</div>`;
		const applyButton = this.page.main[0].querySelector("[data-action='payment-apply-discount']");
		if (applyButton) { applyButton.textContent = __("Apply"); applyButton.hidden = true; }
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
		const invoiceTotal = Number(this.state.totals?.grand_total || 0);
		const feedback = this.page.main[0].querySelector("[data-discount-approval-feedback]");
		if (value < 0 || (type === "Percentage" && value > 100) || (type === "Amount" && value > invoiceTotal)) {
			feedback.textContent = type === "Amount" && value > invoiceTotal
				? __("Discount amount cannot exceed the invoice total.")
				: __("Enter a valid discount value.");
			this.paymentDiscountPreview = null;
			return;
		}
		const approvalApprover = this.paymentDiscountApprovalApprover || "";
		if (type === "Percentage") this.page.main.find("[data-discount-percent-label]").text(`${value}%`);
		try {
			const preview = await this.call("preview_order_discount", { order_name: this.state.order_name, discount_type: type, discount_value: value, discount_reason: reason, approval_code: approvalCode || null, approval_approver: approvalApprover || null, approval_method: this.paymentDiscountAuthMethod || "OTP" });
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
		if (!reason) {
			const feedback = this.page.main[0].querySelector("[data-discount-approval-feedback]");
			if (feedback) feedback.textContent = __("Enter a reason for the discount.");
			return;
		}
		this.paymentDiscountPreview = null;
		await this.refreshPaymentDiscountPreview(requestId, approvalCode, true);
		if (!this.paymentDiscountPreview || requestId !== this.discountPreviewRequestId) return;
		this.paymentDiscount = this.paymentDiscountDraft || this.paymentDiscount;
		this.paymentTotal = Number(this.paymentDiscountPreview.grand_total);
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
		const isSplit = Boolean(this.page.main[0].querySelector("[data-split-check-toggle]")?.checked);
		const splitMode = this.page.main[0].querySelector("[data-payment-split-mode]")?.value || "people";
		const guestRows = isSplit ? [...this.page.main[0].querySelectorAll(".rms-guest-check")].map((section, index) => ({
			guest: section.querySelector("[data-guest-name]").value.trim(),
			mode_of_payment: section.querySelector("[data-guest-method]").value,
			amount: Number(section.querySelector("[data-guest-amount]").value || 0),
			due_amount: Number(section.querySelector("[data-guest-due]")?.dataset.amount || 0),
			items: [...this.page.main[0].querySelectorAll("[data-item-guest]")].filter((select) => Number(select.value) === index).map((select) => select.dataset.itemGuest),
			split_mode: splitMode,
		})) : [];
		const payments = isSplit ? guestRows.map(({ mode_of_payment, amount }) => ({ mode_of_payment, amount })) : [...this.page.main[0].querySelectorAll("[data-payment-amount]")].map((input) => ({ mode_of_payment: input.dataset.method, amount: Number(input.value || 0) })).filter((row) => row.amount > 0);
		const total = Number(this.paymentTotal ?? this.state.totals?.grand_total ?? 0);
		if (this.paymentDiscount?.value > 0 && !this.paymentDiscount.reason.trim()) return frappe.msgprint(__("Enter a reason for the discount."));
		const tendered = payments.reduce((sum, row) => sum + row.amount, 0);
		if (tendered + 0.01 < total) return frappe.msgprint(__("Payment amounts must cover the order total."));
		// Reserve the print tab during the user gesture. Opening it after the payment
		// request resolves is blocked by browsers because the async call loses that gesture.
		const printWindow = print ? window.open("about:blank", "_blank") : null;
		if (print && !printWindow) return frappe.msgprint(__("Your browser blocked the print window. Allow pop-ups for this POS, then try again."));
		this.paymentSubmitting = true;
		const paymentButtons = this.page.main.find('[data-action="payment-pay"], [data-action="payment-pay-print"]');
		paymentButtons.prop("disabled", true);
		let paymentRecorded = false;
		try {
			const result = await this.call("pay_order", { order_name: this.state.order_name, payments: JSON.stringify(payments), guest_breakdown: isSplit ? JSON.stringify(guestRows) : null, discount_type: this.paymentDiscount?.type || "Percentage", discount_value: this.paymentDiscount?.value || 0, discount_reason: this.paymentDiscount?.reason || "", discount_approval_code: this.paymentDiscountApprovalCode || null, discount_approval_approver: this.paymentDiscountApprovalApprover || null });
			paymentRecorded = true;
			this.state.order_status = "Paid"; this.state.last_invoice = result.pos_invoice;
			if (print) {
				try {
					const html = await this.call("get_pos_invoice_print_html", { order_name: this.state.order_name });
					printWindow.document.open(); printWindow.document.write(html); printWindow.document.close();
					setTimeout(() => printWindow.print(), 500);
				} catch (error) {
					printWindow.close();
					frappe.msgprint({ title: __("Payment recorded; print unavailable"), message: __("The payment was recorded as {0}, but the receipt could not be prepared. Reprint it from Sales History.", [result.pos_invoice]), indicator: "orange" });
				}
			}
			this.page.main.find("[data-screen]").prop("hidden", true);
			this.page.main.find(".rms-pos-shell").prop("hidden", false);
			this.onAction("new-sale");
		} catch (error) { if (printWindow && !printWindow.closed) printWindow.close(); this.showError(error); }
		finally {
			this.paymentSubmitting = false;
			if (!paymentRecorded) paymentButtons.prop("disabled", false);
		}
	}
	async showSalesHistory() {
		if (!this.state.store) return frappe.msgprint(__("Select a Store to view sales history."));
		try {
			const sales = await this.call("get_pos_sales_history", { store: this.state.store });
			const rows = sales.map((sale) => `<tr><td><b>${this.escape(sale.pos_invoice)}</b><small>${this.escape(sale.name)} · ${this.escape(sale.order_type || "")}${sale.dining_table ? ` · ${this.escape(sale.dining_table)}` : ""}</small></td><td>${this.currency(sale.grand_total)}</td><td>${this.escape(__(sale.invoice_status || "Paid"))}</td><td>${this.state.permissions.can_reprint_receipts ? `<button type="button" class="btn btn-default btn-xs" data-reprint-order="${this.escape(sale.name)}">${__("Reprint")}</button>` : ""}</td></tr>`).join("");
			const html = rows ? `<div class="rms-pos-sales-history"><table class="table table-bordered"><thead><tr><th>${__("Invoice")}</th><th>${__("Total")}</th><th>${__("Status")}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p>${__("No paid invoices are available in this Store for your account.")}</p>`;
			const dialog = new frappe.ui.Dialog({ title: __("Closed Sales and Reprints"), size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "sales_history", options: html }],
				primary_action_label: __("Close"), primary_action: () => dialog.hide() });
			dialog.show();
			dialog.$wrapper.on("click", "[data-reprint-order]", async (event) => {
				const printWindow = window.open("about:blank", "_blank");
				if (!printWindow) return frappe.msgprint(__("Allow pop-ups to open the receipt for reprinting."));
				try {
					const html = await this.call("get_pos_invoice_print_html", { order_name: event.currentTarget.dataset.reprintOrder });
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
		const dialog = new frappe.ui.Dialog({ title: `${__("View order")}: ${this.escape(order.name)}`, size: "large", fields: [{ fieldtype: "HTML", fieldname: "overview", options: html }], primary_action_label: __("Close"), primary_action: () => dialog.hide() });
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
					? `<button type="button" class="rms-table-order-action" data-action="table-order" data-order="${this.escape(order.order)}">${ownSession ? __("Open order") : __("Open to add items")} · ${this.escape(order.check_label || order.order)}</button>`
					: `<button type="button" class="rms-table-order-action" data-action="table-view-order" data-order="${this.escape(order.order)}">${__("View details")} · ${this.escape(order.check_label || order.order)}</button>`;
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

	async loadOrder(order) {
		this.state.order_name = order.name; this.state.order_status = order.status; this.state.brand = order.restaurant_brand; this.state.order_type = order.order_type;
		this.state.cross_session_edit = Boolean(order.cashier_session && order.cashier_session !== this.state.session?.name);
		this.state.category = null; this.state.search = "";
		this.state.customer = order.customer; this.state.dining_area = order.dining_area; this.state.dining_table = order.dining_table;
		this.state.external_reference = order.external_reference;
		this.state.discount_type = order.discount_type || "Percentage"; this.state.discount_scope = order.discount_scope || "Net Total";
		this.state.discount_value = Number(order.discount_value) || 0; this.state.discount_reason = order.discount_reason || "";
		this.state.cart = order.items.map((row) => ({ selling_product: row.selling_product, option_parent: row.option_parent, sent_to_kitchen: Boolean(row.sent_to_kitchen),
			saved_to_order: true, order_item_name: row.name, read_only: this.state.cross_session_edit,
				title: row.title || row.selling_product, qty: row.qty, cancelled_qty: Number(row.cancelled_qty) || 0, price: row.selling_price, notes: row.notes || "",
			uom: row.uom, must_be_whole_number: Boolean(row.must_be_whole_number),
			modifiers: row.modifiers.map((modifier) => ({ modifier_group: modifier.modifier_group, modifier_product: modifier.modifier_product, qty: modifier.qty })),
			modifier_labels: row.modifiers.map((modifier) => ({ title: modifier.title || modifier.modifier_product, price: modifier.selling_price })) }));
		this.state.totals = { subtotal: order.subtotal, discount_amount: order.discount_amount, tax_total: order.tax_total, grand_total: order.grand_total };
		[this.state.categories, this.state.tables, this.state.products] = await Promise.all([
			this.call("get_categories", { brand: this.state.brand, store: this.state.store }),
			this.call("get_tables", { store: this.state.store, dining_area: this.state.dining_area }),
			this.call("get_catalog", { store: this.state.store, brand: this.state.brand, order_type: this.state.order_type, category: null, search: "", limit: 200 })
		]);
		this.render(); this.renderCart();
	}

	cancelConfirmedItem(index) {
		const row = this.state.cart[index];
		if (!row?.sent_to_kitchen || !row.order_item_name
			|| (this.state.cross_session_edit && !this.state.permissions.can_edit_open_orders)) return;
		const dialog = new frappe.ui.Dialog({ title: __("Cancel confirmed item"), fields: [
			{ fieldtype: "Float", fieldname: "qty", label: __("Quantity to cancel"), default: Math.max(0, Number(row.qty) - Number(row.cancelled_qty || 0)), reqd: 1 },
			{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason"), reqd: 1, description: __("A POS Manager approval is recorded with the order and sent to preparation.") }
		], primary_action_label: __("Cancel item"), primary_action: async (values) => {
			dialog.disable_primary_action();
			try {
				const result = await this.call("cancel_confirmed_order_item", { order_name: this.state.order_name, item_name: row.order_item_name, qty: values.qty, reason: values.reason });
				if (result.status === "Cancelled") {
					row.cancelled_qty = Number(result.cancelled_qty) || 0;
					this.state.order_status = result.status;
					this.state.totals = { ...this.state.totals, subtotal: result.subtotal, discount_amount: 0,
						tax_total: result.tax_total, grand_total: result.grand_total };
					this.renderCart();
				} else {
					const order = await this.call("get_order", { order_name: this.state.order_name });
					await this.loadOrder(order);
				}
				dialog.hide(); frappe.show_alert({ message: __("Confirmed item cancellation recorded"), indicator: "orange" });
			} catch (error) { dialog.enable_primary_action(); this.showError(error); }
		} });
		dialog.$wrapper.addClass("rms-pos-workflow-dialog"); dialog.show();
	}

	showError(error) {
		const response = error?.responseJSON || error;
		// Frappe already renders server validation messages as a dialog. A POS
		// toast here duplicates the same message in the lower-right corner.
		if (response?._server_messages) return;
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

	async startReturnFlow() {
		if (!this.state.session) return frappe.msgprint(__("Open a cashier session before processing a return."));
		try {
			const data = await this.call("get_returnable_sales", { store: this.state.store });
			if (!data.invoices?.length) return frappe.msgprint(__("There are no returnable sales in this cashier session."));
			const html = `<div class="rms-pos-open-list">${data.invoices.map((invoice) => `<div class="rms-pos-open-order"><span><b>${this.escape(invoice.name)}</b><small>${this.escape(invoice.customer)} · ${this.escape(invoice.posting_date)} · ${invoice.returnable_lines.length} ${__("items")}</small></span><strong>${this.currency(invoice.grand_total)}</strong><button class="btn btn-default btn-xs" data-return-invoice="${this.escape(invoice.name)}">${__("Select")}</button></div>`).join("")}</div>`;
			const dialog = new frappe.ui.Dialog({ title: __("Return a Sale"), fields: [{ fieldtype: "HTML", fieldname: "sales_html", options: html }],
				primary_action_label: __("Close"), primary_action: () => dialog.hide() });
			dialog.show();
			dialog.$wrapper.on("click", "[data-return-invoice]", async (event) => {
				const invoice = data.invoices.find((row) => row.name === event.currentTarget.dataset.returnInvoice);
				dialog.hide();
				if (invoice) await this.openReturnItems(invoice, data.refund_methods || []);
			});
		} catch (error) { this.showError(error); }
	}

	async openReturnItems(invoice, refundMethods) {
		const rows = invoice.returnable_lines;
		const html = `<div class="rms-pos-return-lines">${rows.map((row) => `<div class="rms-pos-open-order"><label><input type="checkbox" data-return-select="${this.escape(row.name)}"> ${this.escape(row.title || row.item_code)} <small>${this.escape(row.item_code)} · ${this.currency(row.rate)} / ${this.escape(row.uom || "")}</small></label><span>${__("Available")}: ${row.qty}</span><input type="number" data-return-qty="${this.escape(row.name)}" min="${row.must_be_whole_number ? 1 : 0.001}" max="${row.qty}" step="${row.must_be_whole_number ? 1 : "any"}" value="${row.qty}" aria-label="${__("Return quantity")}"><label><input type="checkbox" data-return-waste="${this.escape(row.name)}"> ${__("Is Waste")}</label></div>`).join("")}</div>`;
		const dialog = new frappe.ui.Dialog({ title: __("Select Return Items"), fields: [
			{ fieldtype: "HTML", fieldname: "items_html", options: html },
			{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason") },
		], primary_action_label: __("Continue"), primary_action: async (values) => {
			const selected = [...dialog.$wrapper[0].querySelectorAll("[data-return-select]:checked")].map((check) => {
				const line = check.dataset.returnSelect;
				const row = rows.find((item) => item.name === line);
				const qty = Number(dialog.$wrapper[0].querySelector(`[data-return-qty="${CSS.escape(line)}"]`)?.value);
				return { source_pos_invoice_item: line, qty, is_waste: Boolean(dialog.$wrapper[0].querySelector(`[data-return-waste="${CSS.escape(line)}"]`)?.checked), max: row?.qty };
			});
			if (!selected.length || selected.some((row) => !Number.isFinite(row.qty) || row.qty <= 0 || row.qty > row.max)) {
				return frappe.msgprint(__("Select valid quantities for at least one return item."));
			}
			try {
				const preview = await this.call("preview_pos_return", { source_pos_invoice: invoice.name,
					items: JSON.stringify(selected.map(({ max, ...row }) => row)) });
				dialog.hide();
				await this.openReturnPayments(invoice, selected, values.reason, preview, refundMethods);
			} catch (error) { this.showError(error); }
		} });
		dialog.show();
	}

	async openReturnPayments(invoice, items, reason, preview, methods) {
		if (!methods.length) return frappe.msgprint(__("Configure at least one POS Profile payment method with Allow In Returns enabled."));
		const fields = [{ fieldtype: "HTML", fieldname: "refund_summary", options: `<p>${__("Calculated ERPNext refund total")}: <strong>${this.currency(preview.refund_total)}</strong></p>` }, ...methods.map((row, index) => ({ fieldtype: "Currency", fieldname: `refund_${index}`,
			label: __("Refund") + ` · ${row.mode_of_payment}`, default: index === 0 ? preview.refund_total : 0 }))];
		const dialog = new frappe.ui.Dialog({ title: __("Refund {0}", [invoice.name]), fields,
			primary_action_label: __("Request Manager Approval"), primary_action: async (values) => {
				const payments = methods.map((row, index) => ({ mode_of_payment: row.mode_of_payment,
					amount: Number(values[`refund_${index}`] || 0) })).filter((row) => row.amount > 0);
				try {
					const result = await this.call("request_pos_return", { source_pos_invoice: invoice.name,
						items: JSON.stringify(items.map(({ max, ...row }) => row)), payments: JSON.stringify(payments), reason: reason || "" });
					dialog.hide();
					frappe.msgprint(__("Return {0} is pending manager approval. Refund total: {1}.", [result.name, this.currency(result.refund_total)]));
				} catch (error) { this.showError(error); }
			} });
		dialog.show();
	}

	selectOptions(key, rows, selected, emptyLabel) {
		return `<option value="">${this.escape(emptyLabel)}</option>${rows.map((row) => `<option value="${this.escape(row.name)}" ${row.name === selected ? "selected" : ""}>${this.escape(row.title || row.name)}</option>`).join("")}`;
	}

	render() {
		const root = this.page.main;
		root.find('[data-select="store"]').html(this.selectOptions("store", this.state.stores, this.state.store, __("Select Store")));
		root.find('[data-select="store"]').prop("disabled", Boolean(this.state.session));
		root.find('[data-select="brand"]').html(this.selectOptions("brand", this.state.brands, this.state.brand, __("Select Brand"))).prop("disabled", !this.state.store || !this.state.brands.length);
		root.find('[data-select="order_type"]').html(this.selectOptions("order_type", this.state.order_types, this.state.order_type, __("Select Order Type"))).prop("disabled", !this.state.store || !this.state.order_types.length);
		root.find('[data-search]').prop("disabled", !this.state.session);
		root.find('[data-action="scan"]').prop("disabled", !this.state.session);
		root.find('[data-action="expenses"]').prop("disabled", !this.state.session);
		const roles = frappe.user_roles || [];
		root.find('[data-action="review-expenses"]').prop("hidden", !roles.some((role) => ["POS Manager", "System Manager"].includes(role)));
		root.find("[data-capability]").each((_, element) => { element.hidden = !this.state.permissions[element.dataset.capability]; });
		root.find('[data-action="session"]').prop("hidden", !this.state.session && !this.state.permissions.can_checkout);
		root.find('[data-action="session"]').text(this.state.session ? __("Close Session") : __("Open Session"));
		root.find('[data-role="context"]').html(this.state.session ? `<span class="rms-pos-live is-on"></span><span>${this.escape(this.state.session.user_full_name || this.state.session.user)} · ${this.escape(this.state.session.business_date)}</span>` : `<span class="rms-pos-live"></span><span>${__("Cashier session closed")}</span>`);
		root.find('[data-role="catalog-hint"]').text(this.state.session ? __("Find an item, add it to the order, then take payment.") : __("Choose a Store. Tables and order history remain available without a cashier session."));
		this.updateOrderTypeFields(); this.renderFields(); this.renderCategories(); this.renderProducts(); this.renderCart();
	}

	updateOrderTypeFields() {
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

	renderCategories() {
		const categories = this.state.categories || [];
		const root = this.page.main;
		const selected = categories.find((row) => row.name === this.state.category);
		root.find("[data-catalog-mode]").each((_, button) => {
			const active = button.dataset.catalogMode === this.state.catalog_mode;
			$(button).toggleClass("is-active", active).attr("aria-selected", String(active));
		});
		root.find(".rms-pos-toolbar").toggle(this.state.catalog_mode === "products");
		const nav = root.find('[data-role="categories"]');
		if (this.state.catalog_mode === "categories") {
			nav.empty().prop("hidden", true);
			return;
		}
		nav.prop("hidden", false);
		const parentName = selected ? selected.parent_product_category : null;
		const categoryButtons = categories.map((row) => {
			const path = [];
			let node = row;
			while (node) {
				path.unshift(node.title);
				node = categories.find((entry) => entry.name === node.parent_product_category);
			}
			return `<button type="button" class="${this.state.category === row.name ? "is-active" : ""}" data-category="${this.escape(row.name)}" aria-pressed="${this.state.category === row.name}" title="${this.escape(path.join(" › "))}">${this.escape(path.join(" › "))}</button>`;
		}).join("");
		const allButton = `<button type="button" class="${selected ? "" : "is-active"}" data-category="" aria-pressed="${!selected}">${__("All products")}</button>`;
		const parent = selected && categories.find((row) => row.name === parentName);
		const backButton = selected ? `<button type="button" class="rms-pos-category-back" data-category-back="${this.escape(parentName || "")}" aria-label="${__("Back to parent category")}">‹ ${this.escape(parent?.title || __("All categories"))}</button>` : "";
		const children = selected ? categories.filter((row) => row.parent_product_category === selected.name) : [];
		const descendants = [];
		let current = selected;
		while (current) { descendants.unshift(current); current = categories.find((row) => row.name === current.parent_product_category); }
		const breadcrumb = descendants.length ? `<span class="rms-pos-category-path">${descendants.map((row) => this.escape(row.title)).join(" › ")}</span>` : "";
		nav.html(`${allButton}${backButton}${categoryButtons}${breadcrumb}`);
	}

	renderProducts() {
		const rows = this.state.products || [];
		let html;
		if (this.state.bootstrap_loading || (this.state.catalog_loading && !rows.length)) {
			html = `<div class="rms-pos-loading" role="status"><span class="rms-pos-loading-indicator" aria-hidden="true"></span><span>${__("Loading the menu…")}</span></div>`;
		} else if (this.state.catalog_mode === "categories") {
			const categories = this.state.categories || [];
			const selected = categories.find((row) => row.name === this.state.category);
			const visible = selected ? categories.filter((row) => row.parent_product_category === selected.name) : categories.filter((row) => !row.parent_product_category);
			const parent = selected && categories.find((row) => row.name === selected.parent_product_category);
			const back = selected ? `<button type="button" class="rms-pos-category-back-card" data-category-back="${this.escape(selected.parent_product_category || "")}">‹ ${this.escape(parent?.title || __("All categories"))}</button>` : "";
			const cards = visible.map((row) => `<button type="button" class="rms-pos-category-card" data-category="${this.escape(row.name)}" data-category-card><span class="rms-pos-category-image">${row.image ? `<img src="${this.escape(row.image)}" alt="">` : `<span aria-hidden="true">✳</span>`}</span><b>${this.escape(row.title)}</b><span>${row.is_group ? __("Browse sections") : __("View products")}</span></button>`).join("");
			html = `${back}<div class="rms-pos-category-grid">${cards || `<div class="rms-pos-empty"><h2>${__("No categories found")}</h2><p>${__("Add menu categories to this Brand to begin browsing.")}</p></div>`}</div>`;
		} else {
			html = !this.state.session ? `<div class="rms-pos-empty"><div class="rms-pos-empty-icon">▧</div><h2>${__("Ready when you are")}</h2><p>${__("Select a Store and open a cashier session to load its menu.")}</p><small>${__("You can view tables, open orders and closed sales before opening a session.")}</small></div>` : rows.length ? rows.map((row) => `<button type="button" class="rms-pos-product" data-product="${this.escape(row.name)}" aria-label="${this.escape(row.title)}${row.price != null ? `, ${this.currency(row.price)}` : ""}" ${row.price == null && !row.has_options || !this.state.permissions.can_checkout ? "disabled" : ""}><span class="rms-pos-product-image">${row.image ? `<img src="${this.escape(row.image)}" alt="">` : `<span aria-hidden="true">＋</span>`}</span><span class="rms-pos-product-category">${this.escape(row.category_title || "")}</span><b>${this.escape(row.title)}</b><span class="rms-pos-product-price">${row.price == null ? row.has_options ? __("Choose option") : __("Price not set") : this.currency(row.price)}</span></button>`).join("") : `<div class="rms-pos-empty"><div class="rms-pos-empty-icon">⌕</div><h2>${__("No products found")}</h2><p>${__("Check the Brand menu, product availability and search terms.")}</p></div>`;
		}
		this.page.main.find('[data-role="catalog-count"]').text(this.state.session ? __("{0} products", [rows.length]) : "");
		this.page.main.find('[data-role="products"]').html(html);
	}

	renderCart() {
		const root = this.page.main;
		const html = this.state.cart.length ? this.state.cart.map((row, index) => {
			const sent = Boolean(row.sent_to_kitchen);
			const remainingQty = Math.max(0, Number(row.qty) - Number(row.cancelled_qty || 0));
			const managerRole = (frappe.user_roles || []).some((role) => ["POS Manager", "System Manager"].includes(role));
			const managerCanCancel = sent && remainingQty > 0 && this.state.permissions.can_cancel_orders && managerRole
				&& (!this.state.cross_session_edit || this.state.permissions.can_edit_open_orders);
			const locked = sent || Boolean(row.read_only);
			const status = sent ? (remainingQty ? __("Sent to preparation") : __("Cancelled")) : row.read_only ? __("Not confirmed · existing order item") : __("Not confirmed");
			return `<article class="rms-pos-cart-line ${sent ? "is-sent" : "is-unconfirmed"} ${remainingQty === 0 && sent ? "is-cancelled" : ""}"><div class="rms-pos-line-main"><b>${this.escape(row.title)}</b><span class="rms-pos-line-status">${status}</span><button type="button" data-action="remove" data-index="${index}" aria-label="${__("Remove")}" ${locked ? "hidden" : ""}>×</button></div>${row.option_parent ? `<small>${__("Option of")} ${this.escape(row.option_parent)}</small>` : ""}${row.modifier_labels.map((modifier) => `<small>+ ${this.escape(modifier.title)} ${modifier.price ? `· ${this.currency(modifier.price)}` : ""}</small>`).join("")}${row.notes ? `<small class="rms-pos-line-note">${this.escape(row.notes)}</small>` : ""}${row.cancelled_qty ? `<small class="rms-pos-cancel-note">${__("Cancelled")}: ${this.escape(row.cancelled_qty)} · ${__("Remaining")}: ${this.escape(remainingQty)}</small>` : ""}<button type="button" class="rms-pos-line-comment" data-action="notes" data-index="${index}" ${locked ? "hidden" : ""}>${row.notes ? __("Edit comment") : __("Add comment")}</button>${managerCanCancel ? `<button type="button" class="rms-pos-line-cancel" data-action="cancel-confirmed-item" data-index="${index}">${__("Cancel confirmed quantity")}</button>` : ""}<div class="rms-pos-line-bottom"><div class="rms-pos-qty"><button type="button" data-action="quantity" data-index="${index}" data-delta="-1" aria-label="${__("Decrease quantity")}" ${locked ? "hidden" : ""}>−</button><input type="number" data-quantity="${index}" min="0.001" step="${row.must_be_whole_number ? "1" : "any"}" value="${row.qty}" aria-label="${__("Ordered quantity")}${row.uom ? ` (${this.escape(row.uom)})` : ""}" ${locked ? "disabled" : ""}><button type="button" data-action="quantity" data-index="${index}" data-delta="1" aria-label="${__("Increase quantity")}" ${locked ? "hidden" : ""}>+</button></div><strong>${this.currency(remainingQty * row.price + row.modifier_labels.reduce((sum, modifier) => sum + modifier.price, 0) * remainingQty)}</strong></div></article>`;
		}).join("") : `<div class="rms-pos-cart-empty"><span>＋</span><p>${__("Add products to begin")}</p></div>`;
		root.find('[data-role="cart"]').html(html);
		root.find('[data-role="cart-title"]').text(this.state.order_name || __("New sale"));
		root.find('[data-action="new-sale"]').prop("hidden", !this.state.order_name);
		root.find('[data-role="ticket"]').text(this.state.order_name || __("Draft"));
		root.find('[data-role="subtotal"]').text(this.state.totals ? this.currency(this.state.totals.subtotal) : "—");
		root.find('[data-role="discount"]').text(this.state.totals?.discount_amount ? `− ${this.currency(this.state.totals.discount_amount)}` : "—");
		root.find('[data-role="taxes"]').text(this.state.totals ? this.currency(this.state.totals.tax_total) : "—");
		root.find('[data-role="total"]').text(this.state.totals ? this.currency(this.state.totals.grand_total) : "—");
		const confirmed = ["Confirmed", "In Preparation", "Ready"].includes(this.state.order_status);
		const orderCancelled = this.state.order_status === "Cancelled";
		const unconfirmedItems = this.state.cart.some((row) => !row.sent_to_kitchen);
		const awaitingOwnerPayment = Boolean(this.state.cross_session_edit && confirmed && !unconfirmedItems);
		const checkoutDisabled = Boolean(orderCancelled || !this.state.cart.length || !this.state.session
			|| !this.state.permissions.can_checkout || this.state.busy || awaitingOwnerPayment);
		root.find('[data-action="discount"]').prop("hidden", true);
		root.find('[data-action="checkout"]').prop("disabled", checkoutDisabled)
			.text(orderCancelled ? __("Order cancelled") : awaitingOwnerPayment ? __("Payment by order owner") : confirmed && !unconfirmedItems ? __("Take Payment") : this.state.busy ? __("Saving…") : __("Confirm"));
	}
}
