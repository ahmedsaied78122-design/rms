// Drop the legacy duplicate-loaded Page cache once, without touching saved sales.
(() => {
	try {
		const key = "rms-page-cache-v82";
		if (localStorage.getItem(key) !== "1") {
			localStorage.removeItem("_page:point-of-sale");
			localStorage.removeItem("_page:kitchen-display");
			localStorage.setItem(key, "1");
		}
	} catch (_) { /* Navigation remains usable when storage is unavailable. */ }
})();

(() => {
	const menuIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
	const closeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg>';
	const collapseIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16m6-11-3 3 3 3"/></svg>';

	class RMSManagementShell {
		constructor() {
			this.compact = window.matchMedia("(max-width: 1199px)");
			this.drawerOpen = false;
			this.expandedGroups = new Set();
			this.query = "";
			this.collapsed = false;
			this.viewportWidth = window.innerWidth;
			this.studio = window.RMSWorkspaceStudio ? new window.RMSWorkspaceStudio(this) : null;
			try { this.collapsed = localStorage.getItem(this.storageKey()) === "1"; } catch (_) {}
			this.onRoute = () => { this.closeAccountMenu(); this.studio?.reset(); this.setSearchOpen(false); this.setDrawerOpen(false); this.scheduleSync(); };
			frappe.router?.on?.("change", this.onRoute);
			this.onResize = () => {
				// A phone keyboard changes height; keep the workspace search usable.
				if (this.viewportWidth !== window.innerWidth) { this.closeAccountMenu(); this.setDrawerOpen(false); this.setSearchOpen(false); }
				this.viewportWidth = window.innerWidth;
				this.updateVisibleViewport();
				this.scheduleSync();
			};
			window.addEventListener("resize", this.onResize);
			window.visualViewport?.addEventListener("resize", () => this.updateVisibleViewport());
			this.updateVisibleViewport();
			document.addEventListener("keydown", event => this.handleKey(event), true);
			document.addEventListener("pointerdown", event => {
				if (this.accountMenu && !this.accountMenu.contains(event.target) && !this.accountButton?.contains(event.target)) this.closeAccountMenu();
			}, true);
			document.addEventListener("click", event => {
				if (event.target.closest(".btn-edit-workspace")) this.studio?.prepareNativeEditing();
				if (event.target.closest(".btn-edit-workspace, .btn-discard-workspace, .btn-save-workspace")) this.scheduleSync();
			}, true);
			const content = document.getElementById("body") || document.body;
			this.observer = new MutationObserver(() => this.scheduleSync());
			this.observer.observe(content, { childList: true, subtree: true });
			this.sync();
			let attempts = 0;
			this.startTimer = window.setInterval(() => {
				if (this.sync() || ++attempts >= 60) window.clearInterval(this.startTimer);
			}, 150);
		}

		storageKey() { return `rms-management-nav:${frappe.session?.user || ""}`; }

		updateVisibleViewport() {
			const height = Math.round(window.visualViewport?.height || window.innerHeight);
			document.documentElement.style.setProperty("--rms-visible-height", `${height}px`);
			if (this.accountMenu) this.positionAccountMenu();
		}

		getWorkspaces() {
			const pages = Array.isArray(frappe.workspace?.all_pages) ? frappe.workspace.all_pages
				: frappe.boot?.allowed_workspaces || frappe.boot?.workspaces?.pages || [];
			return pages.filter(page => typeof page.name === "string" && page.name.trim()
				&& !Number(page.is_hidden || 0) && ![false, 0, "0"].includes(page.has_access));
		}

		label(page) {
			const productLabels = { "ERPNext Settings": "Business settings", "ERPNext Integrations": "Business integrations", "Home": "Overview", "Stock": "Inventory", "Buying": "Purchasing", "Selling": "Sales", "Users": "People & access", "Build": "Customization", "Tools": "Utilities" };
			return __(productLabels[page.name] || page.title || page.name);
		}

		workspacePath(page) {
			const privatePage = [false, 0, "0"].includes(page.public);
			return frappe.router.slug(`${privatePage ? "private/" : ""}${page.name}`);
		}

		routeState(pages = this.getWorkspaces()) {
			const route = (frappe.get_route?.() || []).map(String);
			const part = (route[0] || "").toLowerCase();
			const path = window.location.pathname.toLowerCase();
			const excluded = ["point-of-sale", "table-management", "kitchen-display"];
			const active = !excluded.some(name => part === name || (!route.length
				&& (path === `/app/${name}` || path.startsWith(`/app/${name}/`))));
			const workspace = !part || ["workspaces", "workspace", "private"].includes(part)
				|| pages.some(page => this.workspacePath(page) === route.join("/"));
			return { active, workspace, route };
		}

		activeWorkspace(pages, state) {
			if (state.workspace) {
				const route = state.route.join("/").toLowerCase();
				const exact = pages.find(page => this.workspacePath(page).toLowerCase() === route
					|| state.route.slice(1).some(value => value === page.name));
				return exact?.name || frappe.workspace?.current_page?.name || pages.find(page => page.selected)?.name;
			}
			let module;
			try {
				if (["List", "Form", "Tree"].includes(state.route[0])) module = frappe.get_meta?.(state.route[1])?.module;
				else if (state.route[0]?.toLowerCase() === "query-report") module = frappe.query_report?.report_doc?.module;
			} catch (_) { /* Metadata may still be loading during a route change. */ }
			return module ? pages.find(page => page.module === module && !page.parent_page)?.name : null;
		}

		scheduleSync() {
			if (this.frame) return;
			this.frame = requestAnimationFrame(() => { this.frame = null; this.sync(); });
		}

		mount() {
			const navbar = document.querySelector("header.navbar > .container");
			if (!navbar || !frappe.boot?.user) return false;
			if (this.sidebar?.isConnected && this.toggle?.isConnected) return true;
			this.closeAccountMenu(); this.sidebar?.remove(); this.toggle?.remove(); this.backdrop?.remove();
			this.searchToggle?.remove(); this.searchBackdrop?.remove(); this.languageItem?.remove();
			document.getElementById("rms-desk-search")?.remove();
			this.sidebar = document.createElement("aside");
			this.sidebar.id = "rms-management-sidebar";
			this.sidebar.className = "rms-management-sidebar";
			const icon = name => window.RMSWorkspaceStudio?.icon(name) || menuIcon;
			this.sidebar.innerHTML = `<div class="rms-management-brand"><a href="/app" class="rms-management-home"><img src="/assets/rms/images/rms-mark.svg" alt="" width="36" height="36"><span><strong>RMS<span class="rms-brand-dot">.</span></strong><small data-rms-label="Business suite"></small></span></a><button type="button" class="rms-sidebar-collapse">${collapseIcon}</button></div><div class="rms-management-nav-head"><span data-rms-label="YOUR WORKSPACE"></span><label class="rms-nav-search-wrap">${icon('search')}<input type="search" data-rms-nav-search autocomplete="off"></label></div><nav class="rms-management-links"></nav><div class="rms-management-nav-footer"><button type="button" class="rms-management-account"><span class="rms-account-avatar"></span><span class="rms-account-meta"><strong></strong><small data-rms-label="My account"></small></span><span aria-hidden="true">···</span></button></div>`;
			this.backdrop = document.createElement("button");
			this.backdrop.type = "button";
			this.backdrop.className = "rms-management-backdrop";
			this.backdrop.tabIndex = -1;
			this.backdrop.hidden = true;
			this.backdrop.addEventListener("click", () => this.setDrawerOpen(false, true));
			document.body.append(this.backdrop, this.sidebar);
			this.toggle = document.createElement("button");
			this.toggle.type = "button";
			this.toggle.className = "rms-management-toggle";
			this.toggle.innerHTML = collapseIcon;
			this.toggle.setAttribute("aria-controls", this.sidebar.id);
			navbar.prepend(this.toggle);
			this.mountSearch(navbar);
			this.mountLanguage(navbar);
			const fullName = frappe.session?.user_fullname || frappe.boot.user.full_name || frappe.boot.user.name || "RMS";
			this.sidebar.querySelector(".rms-account-meta strong").textContent = fullName;
			this.sidebar.querySelector(".rms-account-avatar").textContent = [...fullName.trim()][0] || "R";
			this.accountButton = this.sidebar.querySelector(".rms-management-account");
			this.accountButton.id = "rms-sidebar-account";
			this.accountButton.setAttribute("aria-haspopup", "menu");
			this.accountButton.setAttribute("aria-expanded", "false");
			this.accountButton.addEventListener("click", event => {
				event.stopPropagation();
				this.toggleAccountMenu();
			});
			this.toggle.addEventListener("click", () => this.toggleNavigation());
			this.sidebar.querySelector(".rms-sidebar-collapse").addEventListener("click", () => this.toggleNavigation());
			this.search = this.sidebar.querySelector("[data-rms-nav-search]");
			this.search.value = this.query;
			this.search.addEventListener("input", () => {
				this.query = this.search.value.trim().toLocaleLowerCase(); this.signature = null; this.sync();
			});
			this.search.addEventListener("keydown", event => {
				if (event.key === "ArrowDown") { event.preventDefault(); this.sidebar.querySelector(".rms-management-links a")?.focus(); }
			});
			this.sidebar.addEventListener("click", event => {
				const group = event.target.closest("[data-rms-group]");
				if (group) {
					const name = group.dataset.rmsGroup;
					this.expandedGroups.has(name) ? this.expandedGroups.delete(name) : this.expandedGroups.add(name);
					const children = group.closest(".rms-nav-group").querySelector(".rms-nav-children");
					const open = this.expandedGroups.has(name);
					children.hidden = !open; group.setAttribute("aria-expanded", String(open)); return;
				}
				const link = event.target.closest("a[data-rms-workspace]");
				if (!link || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
				event.preventDefault(); event.stopPropagation();
				// Respect the native Workspace loading lock, including keyboard activation.
				if (link.dataset.rmsWorkspace && this.routeState().workspace
					&& document.querySelector(".desk-sidebar .item-anchor.disable-click")) return;
				this.setDrawerOpen(false);
				frappe.set_route(link.dataset.rmsWorkspace);
			});
			this.signature = null;
			return true;
		}

		closeAccountMenu(focus = false) {
			this.accountMenu?.remove(); this.accountMenu = null;
			this.accountButton?.setAttribute("aria-expanded", "false");
			if (focus) this.accountButton?.focus({preventScroll: true});
		}

		positionAccountMenu() {
			if (!this.accountMenu || !this.accountButton) return;
			const anchor = this.accountButton.getBoundingClientRect();
			const width = this.accountMenu.getBoundingClientRect().width;
			const height = this.accountMenu.getBoundingClientRect().height;
			const viewportWidth = document.documentElement.clientWidth;
			const viewportHeight = window.visualViewport?.height || window.innerHeight;
			const rtl = document.documentElement.dir === "rtl";
			const preferred = this.compact.matches ? anchor.left : (rtl ? anchor.left - width - 12 : anchor.right + 12);
			const left = Math.max(12, Math.min(preferred, viewportWidth - width - 12));
			const top = Math.max(12, Math.min(this.compact.matches ? anchor.top - height - 10 : anchor.bottom - height, viewportHeight - height - 12));
			this.accountMenu.style.left = `${left}px`;this.accountMenu.style.top = `${top}px`;
		}

		toggleAccountMenu() {
			if (this.accountMenu) return this.closeAccountMenu(true);
			const source = document.getElementById("toolbar-user") || document.querySelector(".dropdown-navbar-user .dropdown-menu");
			if (!source) return;
			const menu = document.createElement("div");menu.id = "rms-account-menu";
			menu.className = "rms-account-popover dropdown-menu show";
			menu.setAttribute("role", "menu");menu.setAttribute("aria-labelledby", this.accountButton.id);
			for (const entry of source.children) {
				if (entry.hidden || entry.classList.contains("hidden") || entry.classList.contains("hide")) continue;
				if (entry.classList.contains("dropdown-divider")) { const divider=document.createElement("div");divider.className="dropdown-divider";menu.append(divider);continue; }
				if (!["A", "BUTTON"].includes(entry.tagName)) continue;
				const link = entry.tagName === "A";
				const item = document.createElement(link ? "a" : "button");item.className = "dropdown-item";item.setAttribute("role", "menuitem");item.textContent = entry.textContent.trim();
				if (link) {
					item.href = entry.href;
					if(entry.target)item.target=entry.target;if(entry.rel)item.rel=entry.rel;
					item.addEventListener("click", () => this.closeAccountMenu());
				} else {
					item.type = "button";item.disabled = entry.disabled;
					item.addEventListener("click", () => {this.closeAccountMenu();entry.click();});
				}
				menu.append(item);
			}
			if (!menu.children.length) return;
			document.body.append(menu);this.accountMenu = menu;
			this.accountButton.setAttribute("aria-expanded", "true");this.positionAccountMenu();
			requestAnimationFrame(() => menu.querySelector("[role=menuitem]:not(:disabled)")?.focus({preventScroll: true}));
		}

		handleAccountKey(event) {
			if (event.key === "Escape") {event.preventDefault();event.stopPropagation();this.closeAccountMenu(true);return true;}
			const items = [...this.accountMenu.querySelectorAll("[role=menuitem]:not(:disabled)")];
			if (!items.length) return false;
			const index = items.indexOf(document.activeElement);
			let next;
			if (event.key === "ArrowDown") next = (index + 1) % items.length;
			else if (event.key === "ArrowUp") next = (index - 1 + items.length) % items.length;
			else if (event.key === "Home") next = 0;
			else if (event.key === "End") next = items.length - 1;
			else if (event.key === "Tab") {
				if (event.shiftKey && index === 0) next = items.length - 1;
				else if (!event.shiftKey && index === items.length - 1) next = 0;
			}
			if (next === undefined) return false;
			event.preventDefault();items[next].focus();return true;
		}

		mountSearch(navbar) {
			const form = navbar.querySelector('form[role="search"]');
			if (!form) return;
			for (const hint of navbar.querySelectorAll(".rms-search-shortcut")) hint.remove();
			this.searchForm = form; form.id = "rms-global-search-panel";
			this.searchToggle = document.createElement("button"); this.searchToggle.type = "button";
			this.searchToggle.className = "rms-global-search-toggle";
			this.searchToggle.innerHTML = window.RMSWorkspaceStudio?.icon("search") || menuIcon;
			this.searchToggle.setAttribute("aria-controls", form.id);
			const actions = navbar.querySelector(".navbar-collapse > .navbar-nav");
			actions?.prepend(this.searchToggle);
			this.searchToggle.addEventListener("click", () => { this.setDrawerOpen(false); this.setSearchOpen(!this.searchOpen, true); });
			this.searchBackdrop = document.createElement("button"); this.searchBackdrop.type = "button";
			this.searchBackdrop.className = "rms-global-search-backdrop"; this.searchBackdrop.tabIndex = -1;
			this.searchBackdrop.hidden = true; document.body.append(this.searchBackdrop);
			this.searchBackdrop.addEventListener("click", () => this.setSearchOpen(false, true));
			if (!navbar.rmsSearchDismissBound) {
				navbar.rmsSearchDismissBound = true;
				navbar.addEventListener("click", event => {
					if (event.target.closest(".dropdown-notifications,.dropdown-navbar-user,.dropdown-help,.navbar-home")) this.setSearchOpen(false);
				}, true);
			}
			this.searchHint = document.createElement("kbd"); this.searchHint.className = "rms-search-shortcut"; this.searchHint.textContent = "⌘ / Ctrl G";
			form.querySelector(".search-bar")?.append(this.searchHint);
		}

		updateSearch() {
			const input = document.getElementById("navbar-search");
			if (input && this.active) {
				input.placeholder = __("Search RMS…"); input.setAttribute("aria-label", __("Search RMS…"));
			}
			if (this.searchToggle) {
				this.searchToggle.setAttribute("aria-label", __("Search RMS…"));
				this.searchToggle.setAttribute("aria-expanded", String(Boolean(this.searchOpen)));
			}
			this.searchBackdrop?.setAttribute("aria-label", __("Close search"));
		}

		setSearchOpen(open, focus = false) {
			this.searchOpen = Boolean(open && this.active && window.innerWidth <= 600);
			document.body.classList.toggle("rms-global-search-open", this.searchOpen);
			if (this.searchBackdrop) this.searchBackdrop.hidden = !this.searchOpen;
			this.updateSearch();
			if (focus) requestAnimationFrame(() => (open ? document.getElementById("navbar-search") : this.searchToggle)?.focus({preventScroll:true}));
		}

		mountLanguage(navbar) {
			const actions = navbar.querySelector(".navbar-collapse > .navbar-nav");
			if (!actions) return;
			this.languageItem = document.createElement("li"); this.languageItem.className = "nav-item rms-language-item";
			this.languageButton = document.createElement("button"); this.languageButton.type = "button";
			this.languageButton.className = "rms-language-toggle";
			this.languageButton.innerHTML = `${window.RMSWorkspaceStudio?.icon("website") || menuIcon}<span class="rms-language-long"></span><span class="rms-language-short" aria-hidden="true"></span>`;
			this.languageItem.append(this.languageButton);
			actions.insertBefore(this.languageItem, actions.querySelector(".dropdown-notifications"));
			this.languageButton.addEventListener("click", () => this.switchLanguage());
			this.updateLanguage();
		}

		updateLanguage() {
			if (!this.languageButton) return;
			const arabic = (frappe.boot.lang || "en").split("-")[0] === "ar";
			this.languageButton.querySelector(".rms-language-long").textContent = arabic ? "English" : "العربية";
			this.languageButton.querySelector(".rms-language-short").textContent = arabic ? "EN" : "ع";
			const label = arabic ? "Switch to English" : "التبديل إلى العربية";
			this.languageButton.title = label; this.languageButton.setAttribute("aria-label", label);
			this.languageButton.disabled = Boolean(this.changingLanguage);
			this.languageButton.setAttribute("aria-busy", String(Boolean(this.changingLanguage)));
		}

		hasUnsavedChanges() {
			if (window.cur_frm?.is_dirty?.()) return true;
			if (frappe.workspace?.is_read_only === false) return true;
			return Object.values(window.locals || {}).some(group => group && typeof group === "object"
				&& Object.values(group).some(doc => doc && doc.__unsaved && !doc.parenttype));
		}

		async switchLanguage() {
			if (!this.active || this.changingLanguage) return;
			if (this.hasUnsavedChanges()) {
				frappe.msgprint(__("Save or discard your changes before switching language.")); return;
			}
			this.changingLanguage = true; this.updateLanguage(); this.setSearchOpen(false);
			try {
				const language = (frappe.boot.lang || "en").split("-")[0] === "ar" ? "en" : "ar";
				await frappe.call({method: "rms.interface_preferences.set_language", type: "POST", args: {language}, freeze: true, freeze_message: __("Switching language…")});
				window.location.reload();
			} catch (_) {
				// The native request handler presents server/network errors. Keep this page usable.
				this.changingLanguage = false; this.updateLanguage();
			}
		}

		renderNavigation(pages, active) {
			const locale = frappe.boot.lang || "en";
			const signature = JSON.stringify([locale, this.query, active, pages.map(page => [page.name, page.title, page.parent_page, page.public, page.icon])]);
			if (signature === this.signature) return;
			this.signature = signature;
			for (const element of this.sidebar.querySelectorAll("[data-rms-label]")) element.textContent = __(element.dataset.rmsLabel);
			this.sidebar.setAttribute("aria-label", __("Management navigation"));
			this.backdrop.setAttribute("aria-label", __("Close navigation"));
			this.search.placeholder = __("Find a module");
			this.search.setAttribute("aria-label", __("Find a module"));
			const nav = this.sidebar.querySelector(".rms-management-links");
			nav.setAttribute("aria-label", __("Workspaces"));
			const names = new Set(pages.map(page => page.name));
			const children = new Map();
			for (const page of pages) {
				const parent = names.has(page.parent_page) ? page.parent_page : "";
				if (!children.has(parent)) children.set(parent, []);
				children.get(parent).push(page);
			}
			const matched = new Set(pages.filter(page => `${this.label(page)} ${page.name} ${page.module || ""}`.toLocaleLowerCase().includes(this.query)).map(page => page.name));
			const visible = new Set(matched);
			for (const page of pages) if (matched.has(page.name)) {
				let parent = page.parent_page;
				const seen = new Set([page.name]);
				while (names.has(parent) && !seen.has(parent)) {
					seen.add(parent); visible.add(parent); parent = pages.find(row => row.name === parent)?.parent_page;
				}
			}
			const visited = new Set();
			const activeAncestors = new Set();
			let activeParent = pages.find(page => page.name === active)?.parent_page;
			while (names.has(activeParent) && !activeAncestors.has(activeParent)) {
				activeAncestors.add(activeParent); activeParent = pages.find(page => page.name === activeParent)?.parent_page;
			}
			const fragment = document.createDocumentFragment();
			const append = (page, host, ancestorMatch = false) => {
				if (visited.has(page.name) || (this.query && !ancestorMatch && !visible.has(page.name))) return;
				visited.add(page.name);
				const group = document.createElement("div"); group.className = "rms-nav-group";
				const row = document.createElement("div"); row.className = "rms-nav-row";
				const link = document.createElement("a"); link.className = "rms-management-link";
				link.href = `/app/${this.workspacePath(page)}`;
				link.dataset.rmsWorkspace = this.workspacePath(page);
				link.title = this.label(page);
				if (page.name === active) { link.classList.add("is-active"); link.setAttribute("aria-current", "page"); }
				if (activeAncestors.has(page.name)) link.classList.add("has-active-child");
				const marker = document.createElement("span"); marker.className = "rms-workspace-marker";
				marker.setAttribute("aria-hidden", "true");
				marker.innerHTML = window.RMSWorkspaceStudio ? window.RMSWorkspaceStudio.icon(window.RMSWorkspaceStudio.workspaceIcon(page)) : frappe.utils.icon("folder-normal", "sm");
				const label = document.createElement("span"); label.className = "rms-workspace-link-label"; label.textContent = this.label(page);
				link.append(marker, label); row.append(link); group.append(row); host.append(group);
				const descendants = children.get(page.name) || [];
				if (!descendants.length) return;
				const nested = document.createElement("div"); nested.className = "rms-nav-children";
				nested.id = `rms-nav-group-${visited.size}`;
				const toggle = document.createElement("button"); toggle.type = "button";
				toggle.dataset.rmsGroup = page.name; toggle.className = "rms-nav-group-toggle";
				toggle.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 8 4 4 4-4"/></svg>';
				toggle.setAttribute("aria-controls", nested.id);
				toggle.setAttribute("aria-label", __("Show sections in {0}", [this.label(page)]));
				const activeChild = activeAncestors.has(page.name);
				if (activeChild || (this.query && visible.has(page.name))) this.expandedGroups.add(page.name);
				const open = this.expandedGroups.has(page.name);
				toggle.setAttribute("aria-expanded", String(open)); nested.hidden = !open;
				row.append(toggle); group.append(nested);
				for (const child of descendants) append(child, nested, ancestorMatch || matched.has(page.name));
			};
			const roots = children.get("") || [];
			const sections = new Map();
			for (const page of roots) {
				const category = window.RMSWorkspaceStudio?.group(page) || "Business";
				if (!sections.has(category)) sections.set(category, []);
				sections.get(category).push(page);
			}
			for (const [category, entries] of sections) {
				const section = document.createElement("section"); section.className = "rms-nav-section";
				const heading = document.createElement("h2"); heading.textContent = __(category); section.append(heading);
				for (const page of entries) append(page, section);
				if (section.childNodes.length > 1) fragment.append(section);
			}
			if (!fragment.childNodes.length) {
				const empty = document.createElement("p"); empty.className = "rms-nav-empty";
				empty.textContent = pages.length ? __("No matching workspaces") : __("No workspaces available"); fragment.append(empty);
			}
			nav.replaceChildren(fragment);
		}

		sync() {
			if (!this.mount()) return false;
			const pages = this.getWorkspaces(), state = this.routeState(pages);
			const changed = this.active !== state.active;
			this.active = state.active;
			document.body.classList.toggle("rms-management", this.active);
			document.body.classList.toggle("rms-management-workspace", this.active && state.workspace);
			document.body.classList.toggle("rms-workspace-editing", this.active && state.workspace && frappe.workspace?.is_read_only === false);
			document.body.classList.toggle("rms-nav-collapsed", this.collapsed);
			if (!this.active) { this.closeAccountMenu(); this.setDrawerOpen(false); this.setSearchOpen(false); }
			this.sidebar.inert = !this.active || (this.compact.matches && !this.drawerOpen);
			this.renderNavigation(pages, this.activeWorkspace(pages, state));
			this.studio?.sync(state, pages, this.activeWorkspace(pages, state));
			this.decorateRecordHeader(state);
			this.updateSearch();
			this.updateLanguage();
			this.updateControls();
			this.showWelcome();
			if (changed) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
			return true;
		}

		updateControls() {
			const open = this.compact.matches ? this.drawerOpen : !this.collapsed;
			this.toggle.setAttribute("aria-expanded", String(open));
			const label = this.compact.matches ? (open ? __("Close navigation") : __("Open navigation"))
				: open ? __("Collapse navigation") : __("Expand navigation");
			this.toggle.setAttribute("aria-label", label); this.toggle.title = label;
			const collapse = this.sidebar.querySelector(".rms-sidebar-collapse");
			collapse.setAttribute("aria-label", label);
			collapse.title = label;
			collapse.setAttribute("aria-controls", this.sidebar.id);
			collapse.setAttribute("aria-expanded", String(open));
			const iconType = this.compact.matches ? "close" : (this.collapsed ? "expand" : "collapse");
			if (collapse.rmsIconType !== iconType) {
				collapse.rmsIconType = iconType; collapse.innerHTML = this.compact.matches ? closeIcon : collapseIcon;
			}
		}

		decorateRecordHeader(state) {
			if (!state.active || state.workspace) return;
			const page = window.cur_page && frappe.pages?.[window.cur_page];
			const element = page?.page?.wrapper?.[0] || document.querySelector('.page-container:not([style*="display: none"])');
			const host = element?.querySelector('.page-head .title-area > div');
			if (!host) return;
			let context = host.querySelector('.rms-record-context');
			if (!context) { context = document.createElement('span'); context.className = 'rms-record-context'; host.prepend(context); }
			const label = state.route[0]?.toLowerCase() === 'query-report' ? __('Reports & analytics')
				: state.route[0] === 'Form' ? __(state.route[1] || 'Management') : __('Business records');
			if (context.textContent !== label) context.textContent = label;
		}

		toggleNavigation() {
			if (this.compact.matches) { this.setSearchOpen(false); return this.setDrawerOpen(!this.drawerOpen, true); }
			this.collapsed = !this.collapsed;
			try { localStorage.setItem(this.storageKey(), this.collapsed ? "1" : "0"); } catch (_) {}
			this.sync(); window.dispatchEvent(new Event("resize"));
		}

		setDrawerOpen(open, focus = false) {
			this.drawerOpen = Boolean(open && this.active && this.compact.matches);
			document.body.classList.toggle("rms-nav-open", this.drawerOpen);
			document.documentElement.classList.toggle("rms-management-drawer-open", this.drawerOpen);
			if (this.backdrop) this.backdrop.hidden = !this.drawerOpen;
			if (this.sidebar) this.sidebar.inert = !this.active || (this.compact.matches && !this.drawerOpen);
			if (this.toggle) this.updateControls();
			if (focus) {
				if (this.drawerOpen) requestAnimationFrame(() => { if (this.drawerOpen) this.search?.focus({ preventScroll: true }); });
				else this.toggle?.focus({ preventScroll: true });
			}
		}

		handleKey(event) {
			if (this.accountMenu && this.handleAccountKey(event)) return true;
			const modal = document.querySelector(".modal.show, .modal.in");
			if (!modal && this.active && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "g") {
				this.setDrawerOpen(false); this.setSearchOpen(true, true); return false;
			}
			if (this.searchOpen && !modal && event.key === "Escape") {
				this.setSearchOpen(false, true); return false;
			}
			if (!this.drawerOpen || !this.compact.matches) return false;
			if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "g") { this.setDrawerOpen(false); return false; }
			if (document.querySelector(".modal.show, .modal.in")) return false;
			if (event.key === "Escape") {
				event.preventDefault(); event.stopPropagation(); this.setDrawerOpen(false, true); return true;
			}
			if (event.key !== "Tab") return false;
			const items = [...this.sidebar.querySelectorAll('a[href], button, input')].filter(item => !item.disabled && item.getClientRects().length);
			const first = items[0], last = items.at(-1);
			if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); return true; }
			if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); return true; }
			return false;
		}

		showWelcome() {
			if (window.__rmsSystemWelcomeShown || !frappe.boot?.user?.name || frappe.boot.user.name === "Guest") return;
			const message = "كسم فوديستا";
			const description = "";
			let notification;
			if (typeof frappe.ui?.toast === "function") {
				notification = frappe.ui.toast({ message, description, type: "success", duration: 8000, id: "rms-system-welcome" });
			} else if (typeof frappe.show_alert === "function") {
				notification = frappe.show_alert({ message: frappe.utils.escape_html(message), subtitle: frappe.utils.escape_html(description), indicator: "green" }, 8);
			} else return;
			const element = notification?.$el || notification;
			element?.addClass?.("rms-system-welcome-toast");
			element?.attr?.({ dir: "rtl", lang: "ar", "aria-label": "رسالة ترحيب من RMS" });
			window.__rmsSystemWelcomeShown = true;
		}
	}

	window.RMSManagementShell = RMSManagementShell;
	const start = () => { if (!window.rmsManagementUI) window.rmsManagementUI = new RMSManagementShell(); };
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
	else start();
})();
