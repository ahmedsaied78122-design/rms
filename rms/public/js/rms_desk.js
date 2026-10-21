// Refresh the Page scripts and discard the old duplicate-loaded cache once.
(() => {
const cacheVersion = "rms-page-cache-v14";
	try {
		if (localStorage.getItem(cacheVersion) !== "1") {
			localStorage.removeItem("_page:point-of-sale");
			localStorage.removeItem("_page:kitchen-display");
			localStorage.setItem(cacheVersion, "1");
		}
	} catch (error) {
		console.warn("RMS could not clear stale Desk page cache", error);
	}
})();

// Show one personalized welcome on every Desk document load, across all modules/pages.
(() => {
	function showSystemWelcome() {
		if (window.__rmsSystemWelcomeShown) return true;
		const user = frappe.boot?.user;
		if (!user?.name || user.name === "Guest" || !frappe.msgprint) return false;

		const name = frappe.session.user_fullname || user.full_name || user.name;
		window.__rmsSystemWelcomeShown = true;
		const toast = frappe.ui.toast({
			message: `أهلًا يا ${name}، نورت RMS 🤍`,
			description: "نتمنى لك تجربة جميلة وسلسة ✨ | 🌿 اذكر الله وصلِّ على النبي ﷺ 🤍",
			type: "success",
			duration: 10000,
			id: "rms-system-welcome",
		});
		toast.$el.attr({ dir: "rtl", "aria-label": "رسالة ترحيب من RMS" }).addClass("rms-system-welcome-toast");
		return true;
	}

	window.rmsShowSystemWelcome = showSystemWelcome;
})();

// Replace DocType shortcuts and app sections with one flat list of workspaces permitted for this user.
(() => {
	const navId = "rms-workspace-nav";
	const searchId = "rms-desk-search";
	const defaultWorkspaceName = () => {
		const value = frappe.boot?.user?.default_workspace;
		return typeof value === "string" ? value : value?.name;
	};

	function getWorkspacePages() {
		const pages = frappe.boot?.workspaces?.pages;
		if (!Array.isArray(pages)) return [];
		const defaultName = defaultWorkspaceName();
		return pages
			.filter((page) => page.name && page.has_access !== false)
			.sort((a, b) => {
				const aDefault = a.name === defaultName ? 0 : 1;
				const bDefault = b.name === defaultName ? 0 : 1;
				return aDefault - bDefault ||
					(a.sequence_id ?? 9999) - (b.sequence_id ?? 9999) ||
					(a.title || a.name).localeCompare(b.title || b.name);
			});
	}

	function currentWorkspaceName() {
		const route = frappe.get_route?.() || [];
		const routeParts = route.map((part) => String(part).toLowerCase());
		return getWorkspacePages().find((page) =>
			routeParts.includes(String(frappe.router.slug(page.name)).toLowerCase())
		)?.name;
	}

	function renderWorkspaceNav(host) {
		if (!host || host.querySelector(`#${navId}`)) return;
		const pages = getWorkspacePages();
		if (!pages.length) return;

		const nav = document.createElement("nav");
		nav.id = navId;
		nav.className = "rms-workspace-nav";
		nav.setAttribute("aria-label", "مساحات العمل");

		const list = document.createElement("div");
		list.className = "rms-workspace-list";
		const defaultName = defaultWorkspaceName();
		for (const page of pages) {
			const link = document.createElement("button");
			link.type = "button";
			link.className = "rms-workspace-link";
			link.dataset.workspace = page.name;
			link.setAttribute("title", page.title || page.name);
			if (page.name === defaultName) {
				link.classList.add("is-default");
				link.setAttribute("aria-label", `${page.title || page.name}، مساحة العمل الافتراضية`);
			}
			const marker = document.createElement("span");
			marker.className = "rms-workspace-marker";
			marker.setAttribute("aria-hidden", "true");
			marker.textContent = (page.title || page.name).trim().slice(0, 1).toUpperCase();
			const label = document.createElement("span");
			label.className = "rms-workspace-link-label";
			label.textContent = page.title || page.name;
			link.append(marker, label);
			if (page.name === defaultName) {
				const badge = document.createElement("span");
				badge.className = "rms-workspace-default-badge";
				badge.textContent = "افتراضي";
				link.append(badge);
			}
			list.append(link);
		}
		nav.append(list);

		nav.addEventListener("click", (event) => {
			const link = event.target.closest(".rms-workspace-link");
			if (link) frappe.app?.sidebar?.open_workspace?.(link.dataset.workspace);
		});

		host.append(nav);
		updateActiveWorkspace(nav);
	}

	function updateActiveWorkspace(nav = document.getElementById(navId)) {
		if (!nav) return;
		const activeName = currentWorkspaceName();
		for (const link of nav.querySelectorAll(".rms-workspace-link")) {
			const active = link.dataset.workspace === activeName;
			link.classList.toggle("is-active", active);
			if (active) link.setAttribute("aria-current", "page");
			else link.removeAttribute("aria-current");
		}
	}

	function mount() {
		const host = document.querySelector(".body-sidebar-top");
		if (!host || !frappe.boot?.workspaces?.pages?.length) return false;
		host.querySelector(":scope > .sidebar-items")?.setAttribute("hidden", "");
		document.querySelector(".body-sidebar .standard-items-band")?.setAttribute("hidden", "");
		renderWorkspaceNav(host);
		mountSearch();
		return true;
	}

	function mountSearch() {
		const pageHead = document.querySelector(".page-head-content");
		if (!pageHead || pageHead.querySelector(`#${searchId}`)) return;

		const search = document.createElement("input");
		search.id = searchId;
		search.type = "search";
		search.autocomplete = "off";
		search.placeholder = "ابحث عن صنف أو مستند أو صفحة…";
		search.setAttribute("aria-label", "بحث عام");
		search.title = "اكتب للبحث في النظام";
		search.addEventListener("click", () => {
			if (!search.value) frappe.app?.awesome_bar?.open?.();
		});
		search.addEventListener("input", () => {
			// Start searching from this always-visible field; Frappe supplies the native results.
			const bar = frappe.app?.awesome_bar;
			if (!bar) return;
			if (!bar.is_open()) bar.open();
			const nativeInput = bar.search_modal?.find?.("#navbar-search");
			if (nativeInput?.length) nativeInput.val(search.value).trigger("input");
		});
		search.addEventListener("keydown", (event) => {
			if (event.key === "Escape") search.blur();
			if (event.key === "Enter") frappe.app?.awesome_bar?.search_modal?.find?.("#navbar-search")?.get?.(0)?.focus();
		});
		pageHead.append(search);
	}

	function start() {
		const attempt = () => {
			const mounted = mount();
			const welcomed = window.rmsShowSystemWelcome?.() || false;
			return mounted && welcomed;
		};
		if (attempt()) return;
		let attempts = 0;
		const timer = window.setInterval(() => {
			attempts++;
			if (attempt() || attempts >= 100) window.clearInterval(timer);
		}, 200);
	}

	if (window.frappe?.router?.on) {
		frappe.router.on("change", () => {
			updateActiveWorkspace();
			window.setTimeout(mountSearch, 0);
		});
	}
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start, { once: true });
	} else {
		start();
	}
})();

