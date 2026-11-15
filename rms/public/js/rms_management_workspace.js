/* RMS's workspace presentation. Widgets keep their original controllers and data. */
(() => {
  const paths = {
    overview:
      '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><path d="M14 17.5h7m-3.5-3.5v7"/>',
    finance:
      '<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 9h18m-4 5h4M7 5V3m10 2V3"/><circle cx="16" cy="14" r=".5"/>',
    sales:
      '<path d="M5 7h14l1 13H4L5 7Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2m-6 6 2 2 4-4"/>',
    purchase:
      '<path d="M3 4h2l2 12h11l3-8H6m3 12h.01M17 20h.01"/><path d="M12 3v7m-3-3 3 3 3-3"/>',
    inventory:
      '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8m-9 5v9M7.5 5.5l9 5"/>',
    factory: '<path d="M3 21V10l6 3V8l6 3V3h4l2 18H3Zm4-4h1m3 0h1m4 0h1"/>',
    projects:
      '<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 5V3m8 2V3M8 10h8m-8 5 2 2 5-5"/>',
    people:
      '<circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2m1-16a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 4v2"/>',
    assets:
      '<path d="m12 3 8 4v6c0 4-4 7-8 9-4-2-8-5-8-9V7l8-4Zm-3 9 2 2 4-4"/>',
    quality:
      '<circle cx="12" cy="10" r="6"/><path d="m8 15-1 7 5-3 5 3-1-7m-7-5 2 2 3-4"/>',
    support:
      '<path d="M4 13v-1a8 8 0 0 1 16 0v1m-16 0H3v5h4v-5H4Zm16 0h1v5h-4v-5h3Zm0 5c0 3-3 4-6 4"/>',
    website:
      '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z"/>',
    connections:
      '<rect x="3" y="3" width="6" height="6" rx="2"/><rect x="15" y="15" width="6" height="6" rx="2"/><path d="M9 6h6a3 3 0 0 1 3 3v6m-3-3 3 3 3-3M9 18H6a3 3 0 0 1-3-3v-3"/>',
    settings:
      '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
    tools:
      '<path d="m14 5-3 3 5 5 3-3a6 6 0 0 1-7 7l-6 5-4-4 6-6a6 6 0 0 1 6-7Z"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    edit: '<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14v6Z"/>',
    plus: '<path d="M12 4v16M4 12h16"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    chart: '<path d="M4 3v18h17M8 15l4-5 4 3 5-7"/>',
    calendar:
      '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 5h.01M12 16h.01M16 16h.01"/>',
  };
  const svg = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${
      paths[name] || paths.overview
    }</svg>`;
  const groups = {
    Home: "Overview",
    Management: "Overview",
    الإدارة: "Overview",
    Accounting: "Business",
    Payables: "Business",
    Receivables: "Business",
    "Financial Reports": "Business",
    Buying: "Business",
    Selling: "Business",
    Stock: "Business",
    Assets: "Business",
    Manufacturing: "Business",
    Quality: "Business",
    Projects: "Business",
    CRM: "Business",
    Support: "People & service",
    Users: "People & service",
    HR: "People & service",
    Payroll: "People & service",
    Website: "Platform",
    Tools: "Platform",
    "ERPNext Settings": "Platform",
    Integrations: "Platform",
    "ERPNext Integrations": "Platform",
    Build: "Platform",
  };
  const workspaceIcons = {
    Home: "overview",
    Management: "overview",
    الإدارة: "overview",
    Accounting: "finance",
    Buying: "purchase",
    Selling: "sales",
    Stock: "inventory",
    Assets: "assets",
    Manufacturing: "factory",
    Quality: "quality",
    Projects: "projects",
    CRM: "people",
    Users: "people",
    Support: "support",
    Website: "website",
    Tools: "tools",
    "ERPNext Settings": "settings",
    Integrations: "connections",
    "ERPNext Integrations": "connections",
    Build: "settings",
    HR: "people",
    Payroll: "finance",
  };

  class RMSWorkspaceStudio {
    constructor(shell) {
      this.shell = shell;
      this.portals = new Map();
      this.sections = new Map();
      this.installCharts();
    }
    static icon(name) {
      return svg(name);
    }
    static group(page) {
      return [false, 0, "0"].includes(page.public)
        ? "Personal"
        : groups[page.name] || "Business";
    }
    static workspaceIcon(page) {
      return workspaceIcons[page.name] || "overview";
    }
    static chartOptions(original) {
      // Copy presentation options only: retain datasets, formatting, events and chart types.
      const palette = [
        "#24785e",
        "#bed865",
        "#78aaa5",
        "#dc9c68",
        "#9394bd",
        "#cb7476",
      ];
      // Color identity follows series/category order, never translated display names.
      const datasets = original.data?.datasets || [];
      const names = ["pie", "donut", "percentage"].includes(original.type)
        ? original.data?.labels || []
        : datasets.map((row) => row.name || "");
      // SVG morphs swap the live canvas asynchronously; resizing during a morph
      // can leave the engine holding a detached SVG. Draw updates atomically.
      const options = {
        ...original,
        animate: false,
        disableEntryAnimation: true,
        colors: names.length
          ? names.map((_, i) => palette[i % palette.length])
          : palette,
      };
      if (original.type === "bar")
        options.barOptions = { ...original.barOptions, spaceRatio: 0.55 };
      if (original.type === "line")
        options.lineOptions = {
          hideDots: 0,
          dotSize: 4,
          regionFill: 1,
          ...original.lineOptions,
        };
      // Heatmaps need an ordered intensity scale rather than categorical colors.
      if (original.type === "heatmap")
        options.colors = [
          "#eef3e5",
          "#d3e1b0",
          "#a4c677",
          "#63a16a",
          "#24785e",
        ];
      return options;
    }
    installCharts() {
      const factory = window.frappe?.widget?.widget_factory;
      if (!factory?.chart || factory.chart.rmsPresentation) return;
      const NativeChart = factory.chart;
      factory.chart = class RMSChart extends NativeChart {
        static rmsPresentation = true;
        get_chart_args() {
          const args = super.get_chart_args();
          return document.body.classList.contains("rms-management")
            ? RMSWorkspaceStudio.chartOptions(args)
            : args;
        }
      };
    }
    releaseWidgets() {
      for (const [node, marker] of this.portals) {
        node.classList.remove("rms-directory-filtered");
        node
          .querySelectorAll(".rms-directory-filtered")
          .forEach((item) => item.classList.remove("rms-directory-filtered"));
        node.querySelector("[data-rms-widget-badge]")?.remove();
        node.querySelector(".rms-edit-card-tools")?.remove();
        node.classList.remove("rms-chart-wide");
        if (node.rmsMetricAttributes) {
          for (const [key, value] of Object.entries(node.rmsMetricAttributes)) {
            if (value === null) node.removeAttribute(key);
            else node.setAttribute(key, value);
          }
          delete node.rmsMetricAttributes;
        }
        if (marker.isConnected) marker.replaceWith(node);
        else node.remove();
      }
      this.portals.clear();
    }
    restore() {
      this.releaseWidgets();
      this.sections.clear();
      this.root?.remove();
      this.root = null;
      this.heroSignature = null;
      document.body.classList.remove("rms-studio-active");
      document.body.classList.remove("rms-studio-editing");
    }
    reset() {
      this.restore();
      this.routeKey = null;
    }
    section(kind, title, detail) {
      if (this.sections.has(kind)) return this.sections.get(kind);
      const section = document.createElement("section");
      section.className = `rms-studio-section rms-studio-${kind}`;
      section.dataset.rmsSection = kind;
      const heading = document.createElement("div");
      heading.className = "rms-studio-section-heading";
      const h2 = document.createElement("h2");
      h2.textContent = __(title);
      heading.append(h2);
      if (detail) {
        const subtitle = document.createElement("span");
        subtitle.textContent = __(detail);
        heading.append(subtitle);
      }
      const content = document.createElement("div");
      content.className = "rms-studio-grid";
      section.append(heading, content);
      const order = [
        "metrics",
        "charts",
        "shortcuts",
        "resources",
        "activity",
        "content",
      ];
      const next = [...this.root.querySelectorAll("[data-rms-section]")].find(
        (el) => order.indexOf(el.dataset.rmsSection) > order.indexOf(kind)
      );
      this.root.insertBefore(section, next || this.footnote);
      this.sections.set(kind, content);
      return content;
    }
    makeRoot(host) {
      this.root = document.createElement("div");
      this.root.className = "rms-workspace-studio";
      this.hero = document.createElement("section");
      this.hero.className = "rms-studio-hero";
      this.hero.innerHTML = `<img class="rms-studio-art" src="/assets/rms/images/rms-workspace-street-art-v1.webp" alt="" aria-hidden="true"><div class="rms-studio-hero-copy"><div class="rms-studio-eyebrow">RMS <span> / </span><span data-rms-hero-eyebrow></span></div><h1></h1><p></p><div class="rms-studio-meta"><span class="rms-studio-date">${svg(
        "calendar"
      )}<span></span></span><span class="rms-studio-app-count"></span></div></div><div class="rms-studio-hero-actions"><span class="rms-studio-hero-mark" aria-hidden="true"><i></i><b>R</b><i></i></span></div>`;
      this.editToolbar = document.createElement("div");
      this.editToolbar.className = "rms-layout-toolbar";
      this.editToolbar.hidden = true;
      this.editToolbar.innerHTML = `<span data-rms-editing-label></span><div><select data-rms-add-type></select><button type="button" data-rms-add-block>${svg(
        "plus"
      )}<span></span></button><button type="button" data-rms-discard-layout></button><button type="button" class="rms-layout-save" data-rms-save-layout></button></div>`;
      this.editToolbar
        .querySelector("[data-rms-add-block]")
        .addEventListener("click", () => this.addBlock());
      this.editToolbar
        .querySelector("[data-rms-save-layout]")
        .addEventListener("click", () => this.runNativeAction("primary"));
      this.editToolbar
        .querySelector("[data-rms-discard-layout]")
        .addEventListener("click", () => this.runNativeAction("secondary"));
      this.directory = document.createElement("div");
      this.directory.className = "rms-workspace-directory";
      this.directory.hidden = true;
      const search = document.createElement("label");
      search.innerHTML = svg("search");
      this.directoryInput = document.createElement("input");
      this.directoryInput.type = "search";
      this.directoryInput.autocomplete = "off";
      this.directoryInput.addEventListener("input", () =>
        this.shell.scheduleSync()
      );
      this.directoryInput.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !this.directoryInput.value) return;
        event.preventDefault();
        event.stopPropagation();
        this.directoryInput.value = "";
        this.shell.scheduleSync();
      });
      this.directoryInput.setAttribute(
        "aria-controls",
        "rms-workspace-directory-results"
      );
      search.append(this.directoryInput);
      this.directoryStatus = document.createElement("span");
      this.directoryStatus.setAttribute("role", "status");
      this.directoryStatus.setAttribute("aria-live", "polite");
      this.directory.append(search, this.directoryStatus);
      this.footnote = document.createElement("div");
      this.footnote.className = "rms-studio-footnote";
      this.footnote.innerHTML = `<span>RMS</span><div class="rms-studio-footer-tools"><span data-rms-studio-footer></span><details class="rms-workspace-options"><summary></summary><div><button type="button" data-rms-edit-layout>${svg(
        "edit"
      )}<span></span></button><button type="button" data-rms-new-workspace>${svg(
        "plus"
      )}<span></span></button></div></details></div>`;
      this.footnote
        .querySelector("[data-rms-edit-layout]")
        .addEventListener("click", () => {
          this.footnote.querySelector("details").open = false;
          const button = host.querySelector(".btn-edit-workspace:not(.hide)");
          if (!button) return;
          this.prepareNativeEditing();
          button.click();
        });
      this.footnote
        .querySelector("[data-rms-new-workspace]")
        .addEventListener("click", () => {
          this.footnote.querySelector("details").open = false;
          host.querySelector(".btn-new-workspace:not(.hide)")?.click();
        });
      this.root.append(
        this.hero,
        this.editToolbar,
        this.directory,
        this.footnote
      );
      host.prepend(this.root);
    }
    prepareNativeEditing() {
      this.releaseWidgets();
      this.shell.scheduleSync();
    }
    installNativeSave(ws) {
      if (!ws?.save_page || ws.rmsSaveBridge) return;
      const native = ws.save_page;
      ws.rmsSaveBridge = true;
      ws.save_page = function (...args) {
        const studio = window.rmsManagementUI?.studio;
        if (!studio?.root) return native.apply(this, args);
        studio.suspendPortals = true;
        studio.releaseWidgets();
        try {
          return Promise.resolve(native.apply(this, args)).finally(() => {
            studio.suspendPortals = false;
            studio.shell.scheduleSync();
          });
        } catch (error) {
          studio.suspendPortals = false;
          studio.shell.scheduleSync();
          throw error;
        }
      };
    }
    nativeAction(kind) {
      const ws = frappe.workspace;
      return (
        (kind === "primary"
          ? ws?.page?.btn_primary?.[0]
          : ws?.page?.btn_secondary?.[0]) ||
        ws?.page?.wrapper?.[0]?.querySelector(
          `.page-head .${
            kind === "primary" ? "primary-action" : "btn-secondary"
          }`
        )
      );
    }
    runNativeAction(kind) {
      const button = this.nativeAction(kind);
      if (!button || button.disabled || button.classList.contains("hide"))
        return;
      if (kind === "secondary") this.releaseWidgets();
      button.click();
    }
    addBlock() {
      const ws = frappe.workspace;
      if (ws?.is_read_only !== false || !ws.editor?.blocks) return;
      const type = this.editToolbar.querySelector("[data-rms-add-type]").value;
      if (
        ![
          "number_card",
          "chart",
          "shortcut",
          "card",
          "quick_list",
          "custom_block",
        ].includes(type)
      )
        return;
      ws.editor.blocks.insert(type, { col: type === "chart" ? 12 : 4 });
    }
    blockIndex(node) {
      const marker = this.portals.get(node);
      const block = marker?.parentElement?.closest(".ce-block");
      const editor = frappe.workspace?.editor;
      if (!block || !editor?.blocks) return -1;
      for (let i = 0; i < editor.blocks.getBlocksCount(); i++) {
        if (editor.blocks.getBlockByIndex(i)?.holder === block) return i;
      }
      return -1;
    }
    editBlock(node, action) {
      const editor = frappe.workspace?.editor;
      if (frappe.workspace?.is_read_only !== false || !editor?.blocks) return;
      const index = this.blockIndex(node);
      if (index < 0) return;
      if (action === "remove") editor.blocks.delete(index);
      else if (action === "up" || action === "down") {
        const siblings = [...node.parentElement.children];
        const peer =
          siblings[siblings.indexOf(node) + (action === "up" ? -1 : 1)];
        const target = peer ? this.blockIndex(peer) : -1;
        if (target >= 0) editor.blocks.move(target, index);
      } else if (action === "width") {
        const holder = editor.blocks.getBlockByIndex(index).holder;
        const full =
          holder.classList.contains("col-xs-12") &&
          !holder.classList.contains("col-sm-6");
        for (const name of [...holder.classList])
          if (name.startsWith("col-")) holder.classList.remove(name);
        holder.classList.add("col-xs-12");
        if (full) holder.classList.add("col-sm-6");
      }
      this.shell.scheduleSync();
    }
    updateEditing(ws) {
      const editing = ws.is_read_only === false;
      document.body.classList.toggle("rms-studio-editing", editing);
      this.editToolbar.hidden = !editing;
      if (editing && !this.wasEditing)
        requestAnimationFrame(() =>
          this.editToolbar?.scrollIntoView({
            block: "nearest",
            behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
              .matches
              ? "auto"
              : "smooth",
          })
        );
      this.wasEditing = editing;
      if (!editing) {
        for (const node of this.portals.keys())
          node.querySelector(".rms-edit-card-tools")?.remove();
        return;
      }
      const setText = (node, value) => {
        if (node.textContent !== value) node.textContent = value;
      };
      setText(
        this.editToolbar.querySelector("[data-rms-editing-label]"),
        __("Editing your workspace")
      );
      setText(
        this.editToolbar.querySelector("[data-rms-add-block] span"),
        __("Add widget")
      );
      const select = this.editToolbar.querySelector("[data-rms-add-type]");
      if (select.dataset.lang !== (frappe.boot.lang || "en")) {
        const types = [
          ["number_card", "Key figure"],
          ["chart", "Chart"],
          ["shortcut", "Shortcut"],
          ["card", "Links"],
          ["quick_list", "Quick list"],
          ["custom_block", "Custom block"],
        ];
        select.replaceChildren(
          ...types.map(([value, label]) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = __(label);
            return option;
          })
        );
        select.dataset.lang = frappe.boot.lang || "en";
      }
      select.setAttribute("aria-label", __("Widget type"));
      for (const [kind, key, label] of [
        ["primary", "save", "Save"],
        ["secondary", "discard", "Discard"],
      ]) {
        const source = this.nativeAction(kind),
          target = this.editToolbar.querySelector(`[data-rms-${key}-layout]`);
        setText(target, __(label));
        target.disabled =
          !source || source.disabled || source.classList.contains("hide");
      }
      for (const [node, marker] of this.portals) {
        if (
          !node.classList.contains("widget") ||
          node.classList.contains("new-widget")
        )
          continue;
        let tools = node.querySelector(".rms-edit-card-tools");
        if (!tools) {
          tools = document.createElement("div");
          tools.className = "rms-edit-card-tools";
          for (const [action, label, text] of [
            ["up", "Move up", "↑"],
            ["down", "Move down", "↓"],
            ["remove", "Remove widget", "×"],
          ]) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = text;
            button.title = __(label);
            button.setAttribute("aria-label", __(label));
            button.addEventListener("click", (event) => {
              event.stopPropagation();
              this.editBlock(node, action);
            });
            tools.append(button);
          }
          if (node.classList.contains("dashboard-widget-box")) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = "↔";
            button.title = __("Change chart width");
            button.setAttribute("aria-label", button.title);
            button.addEventListener("click", (event) => {
              event.stopPropagation();
              this.editBlock(node, "width");
            });
            tools.prepend(button);
          }
          node.append(tools);
        }
        if (node.classList.contains("dashboard-widget-box")) {
          const holder = marker.parentElement?.closest(".ce-block");
          node.classList.toggle(
            "rms-chart-wide",
            !!holder?.classList.contains("col-xs-12") &&
              !holder?.classList.contains("col-sm-6")
          );
        }
      }
      const order = new Map(
        [...ws.body[0].querySelectorAll(".editor-js-container .ce-block")].map(
          (node, i) => [node, i]
        )
      );
      for (const grid of this.sections.values()) {
        const desired = [...grid.children].sort(
          (a, b) =>
            (order.get(
              this.portals.get(a)?.parentElement?.closest(".ce-block")
            ) ?? 999) -
            (order.get(
              this.portals.get(b)?.parentElement?.closest(".ce-block")
            ) ?? 999)
        );
        desired.forEach((node, i) => {
          if (grid.children[i] !== node)
            grid.insertBefore(node, grid.children[i] || null);
        });
      }
    }

    heroContent(pages, active, host) {
      const page = pages.find((row) => row.name === active) || {
        name: active || "Home",
      };
      const locale = frappe.boot.lang || "en";
      const editable =
        frappe.workspace?.is_read_only !== false &&
        !!host.querySelector(".btn-edit-workspace:not(.hide)");
      const creatable =
        frappe.workspace?.is_read_only !== false &&
        !!host.querySelector(".btn-new-workspace:not(.hide)");
      const signature = JSON.stringify([
        locale,
        page.name,
        editable,
        creatable,
        pages.length,
        new Date().toDateString(),
      ]);
      if (signature === this.heroSignature) return;
      this.heroSignature = signature;
      const descriptions = {
        Home: "Your people, operations and numbers. One connected view.",
        Management: "Your RMS operations and setup, organized in one place.",
        الإدارة: "Your RMS operations and setup, organized in one place.",
        Stock:
          "A clear view of your inventory, warehouses and stock movements.",
        Accounting: "Accounts, cash flow and financial performance, connected.",
        Buying: "Purchases, suppliers and sourcing, working together.",
        Selling: "Customers, sales and growth, in one workspace.",
        Manufacturing: "Plan production and keep every operation moving.",
        Projects: "Bring your projects, tasks and progress together.",
        Users: "Manage your team and access to your business.",
      };
      this.hero.querySelector("[data-rms-hero-eyebrow]").textContent =
        __("Management");
      this.hero.querySelector("h1").textContent =
        page.name === "Home"
          ? __("Your business, at a glance.")
          : this.shell.label(page);
      this.hero.querySelector("p").textContent = __(
        descriptions[page.name] ||
          "Everything you need to move your business forward."
      );
      const date = new Date();
      try {
        this.hero.querySelector(".rms-studio-date span").textContent =
          new Intl.DateTimeFormat(locale, {
            weekday: "short",
            day: "numeric",
            month: "long",
          }).format(date);
      } catch (_) {
        this.hero.querySelector(".rms-studio-date span").textContent =
          date.toLocaleDateString();
      }
      const count = pages.filter((row) => !row.parent_page).length;
      this.hero.querySelector(".rms-studio-app-count").textContent = __(
        "{0} connected modules",
        [count]
      );
      const edit = this.root.querySelector("[data-rms-edit-layout]");
      edit.hidden = !editable;
      edit.querySelector("span").textContent = __("Edit layout");
      const create = this.root.querySelector("[data-rms-new-workspace]");
      create.hidden = !creatable;
      create.setAttribute("aria-label", __("New workspace"));
      create.title = __("New workspace");
      create.querySelector("span").textContent = __("New workspace");
      const options = this.footnote.querySelector("details");
      options.hidden = !editable && !creatable;
      options.querySelector("summary").textContent = "···";
      options
        .querySelector("summary")
        .setAttribute("aria-label", __("Workspace options"));
      this.footnote.querySelector("[data-rms-studio-footer]").textContent = __(
        "One business. Everything connected."
      );
    }
    classify(node) {
      if (
        node.classList.contains("onboarding-widget-box") ||
        node.classList.contains("spacer")
      )
        return null;
      if (node.classList.contains("number-widget-box"))
        return ["metrics", "Key figures", "Your workspace at a glance"];
      if (node.classList.contains("dashboard-widget-box"))
        return [
          "charts",
          "Business pulse",
          "Explore the numbers behind your operations",
        ];
      if (node.classList.contains("shortcut-widget-box"))
        return ["shortcuts", "Quick access", "Go straight to your daily work"];
      if (node.classList.contains("links-widget-box"))
        return [
          "resources",
          "Explore your workspace",
          "Records, reports and tools",
        ];
      if (node.classList.contains("quick-list-widget-box"))
        return ["activity", "Latest activity", "Keep work moving"];
      return ["content", "Your workspace", null];
    }
    static directoryMatch(text, query) {
      const normalize = (value) =>
        String(value || "")
          .normalize("NFKD")
          .replace(/[\u064b-\u065f\u0670\u0640\u0300-\u036f]/g, "")
          .replace(/[إأآ]/g, "ا")
          .replace(/ى/g, "ي")
          .replace(/[-_/]/g, " ")
          .toLocaleLowerCase();
      const haystack = normalize(text);
      return normalize(query)
        .trim()
        .split(/\s+/)
        .every((word) => haystack.includes(word));
    }
    updateDirectory(active, ws) {
      const isHub = ["Management", "الإدارة"].includes(active);
      this.root.classList.toggle("rms-operations-hub", isHub);
      const enabled = isHub && ws.is_read_only !== false;
      this.directory.hidden = !enabled;
      this.directoryInput.placeholder = __("Find a screen or setting");
      this.directoryInput.setAttribute(
        "aria-label",
        __("Find a screen or setting")
      );
      const query = enabled ? this.directoryInput.value.trim() : "";
      let matched = 0;
      for (const node of this.portals.keys()) {
        const links = [...node.querySelectorAll("a.link-item")];
        const title = node.querySelector(".widget-title")?.textContent || "";
        const groupMatch =
          query && RMSWorkspaceStudio.directoryMatch(title, query);
        const searchable = (item) => {
          let href = item.getAttribute("href") || "";
          try {
            href = decodeURIComponent(href);
          } catch (_) {
            /* Native labels still work. */
          }
          return `${item.textContent} ${href.replace(/[-_/]/g, " ")}`;
        };
        let visible = !query;
        if (links.length) {
          let count = 0;
          for (const link of links) {
            const show =
              !query ||
              groupMatch ||
              RMSWorkspaceStudio.directoryMatch(searchable(link), query);
            link.classList.toggle("rms-directory-filtered", !show);
            if (show && !link.hidden && !link.classList.contains("hide"))
              count++;
          }
          matched += count;
          visible = count > 0;
        } else {
          visible =
            !query ||
            RMSWorkspaceStudio.directoryMatch(
              `${title} ${node.dataset.widgetName || ""} ${searchable(node)}`,
              query
            );
          if (
            query &&
            visible &&
            node.classList.contains("shortcut-widget-box")
          )
            matched++;
        }
        node.classList.toggle("rms-directory-filtered", !visible);
      }
      const resources = this.sections.get("resources");
      if (resources) resources.id = "rms-workspace-directory-results";
      const status = query
        ? matched
          ? __("{0} matching links", [matched])
          : __("No matching screens. Try another name.")
        : __("Browse by task, or search by name.");
      if (this.directoryStatus.textContent !== status)
        this.directoryStatus.textContent = status;
    }
    decorateBadge(node, active) {
      const badge = node.querySelector("[data-rms-widget-badge]");
      if (!badge) return;
      const name = (
        node.querySelector(".widget-title")?.textContent || ""
      ).toLowerCase();
      if (node.rmsMetricAttributes)
        node.setAttribute(
          "aria-label",
          node.querySelector(".widget-title")?.textContent.trim() ||
            __("Key figures")
        );
      const hubIcons = {
        "Daily operations": "overview",
        "Products and menus": "sales",
        "Stores and cashier access": "people",
        "Dining and preparation": "tools",
        "Payments and operational rules": "finance",
        "Stock and waste": "inventory",
        "Printing and devices": "tools",
        "Operational reports": "chart",
        "System and synchronization": "connections",
      };
      const group = Object.keys(hubIcons).find((key) =>
        [key.toLowerCase(), __(key).toLowerCase()].includes(name.trim())
      );
      const icon =
        (group && hubIcons[group]) ||
        (/stock|warehouse|item|inventory|مخزون|مستودع|صنف/.test(name)
          ? "inventory"
          : /sales|invoice|selling|بيع|فاتور/.test(name)
            ? "sales"
            : /supplier|purchase|buying|شراء|مورد/.test(name)
              ? "purchase"
              : /customer|employee|user|عميل|عملاء|موظف/.test(name)
                ? "people"
                : /account|cash|bank|حساب|نقد/.test(name)
                  ? "finance"
                  : RMSWorkspaceStudio.workspaceIcon({ name: active }));
      if (badge.dataset.rmsIcon === icon) return;
      badge.dataset.rmsIcon = icon;
      badge.innerHTML = svg(icon);
    }
    adopt(node, kind, title, detail) {
      const marker = document.createComment("RMS widget position");
      node.before(marker);
      this.portals.set(node, marker);
      this.section(kind, title, detail).append(node);
      if (["metrics", "shortcuts", "resources", "activity"].includes(kind)) {
        const badge = document.createElement("span");
        badge.className = "rms-widget-badge";
        badge.dataset.rmsWidgetBadge = "1";
        const name = (
          node.dataset.widgetName ||
          node.querySelector(".widget-title")?.textContent ||
          ""
        ).toLowerCase();
        const icon = /stock|warehouse|item|inventory|مخزون/.test(name)
          ? "inventory"
          : /sales|invoice|selling|بيع/.test(name)
            ? "sales"
            : /supplier|purchase|buying|شراء/.test(name)
              ? "purchase"
              : /customer|employee|user|عميل/.test(name)
                ? "people"
                : /account|cash|bank|حساب/.test(name)
                  ? "finance"
                  : "overview";
        badge.innerHTML = svg(icon);
        node.prepend(badge);
      }
      if (kind === "charts") {
        node.dataset.rmsChart = "1";
        const sourceBlock = marker.parentElement?.closest(".ce-block");
        if (
          sourceBlock?.classList.contains("col-12") ||
          node.classList.contains("full-width")
        )
          node.classList.add("rms-chart-wide");
      }
      if (kind === "shortcuts" && !node.rmsShortcutKeyboard) {
        node.rmsShortcutKeyboard = true;
        node.addEventListener("keydown", (event) => {
          if (event.key === "Enter" && event.target === node) {
            event.preventDefault();
            node.click();
          }
        });
      }
      if (kind === "metrics") {
        node.rmsMetricAttributes = Object.fromEntries(
          ["role", "tabindex", "aria-label"].map((key) => [
            key,
            node.getAttribute(key),
          ])
        );
        node.setAttribute("role", "link");
        node.tabIndex = 0;
        if (!node.rmsMetricKeyboard) {
          node.rmsMetricKeyboard = true;
          node.addEventListener("keydown", (event) => {
            if (
              event.key === "Enter" &&
              event.target === node &&
              document.body.classList.contains("rms-studio-active")
            ) {
              event.preventDefault();
              node.querySelector(".widget-body")?.click();
            }
          });
          node.addEventListener("click", (event) => {
            if (
              document.body.classList.contains("rms-studio-active") &&
              !event.target.closest(".widget-control,.widget-body") &&
              event.target.closest(".rms-widget-badge,.widget-head")
            )
              node.querySelector(".widget-body")?.click();
          });
        }
      }
    }
    brandInterfaceCopy() {
      // Only interface guidance. Record values, report cells and source notices stay intact.
      const selector =
        ".onboarding-widget-box .widget-title,.onboarding-widget-box .widget-subtitle,.onboarding-widget-box .onboarding-step-preview,.rms-management .help-box,.rms-management .field-description";
      for (const host of document.querySelectorAll(selector)) {
        const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          const next = node.nodeValue.replace(/\bERPNext\b|\bFrappe\b/g, "RMS");
          if (next !== node.nodeValue) node.nodeValue = next;
        }
      }
    }
    sync(state, pages, active) {
      this.installCharts();
      if (state.active) this.brandInterfaceCopy();
      const ws = frappe.workspace;
      this.installNativeSave(ws);
      if (!state.active || !state.workspace) {
        if (this.root) this.restore();
        return;
      }
      const host = ws?.body?.[0];
      if (!host?.isConnected) return;
      const key = state.route.join("/");
      if (this.routeKey !== key) {
        this.restore();
        this.routeKey = key;
      }
      if (!this.root?.isConnected) this.makeRoot(host);
      document.body.classList.add("rms-studio-active");
      this.heroContent(pages, active, host);
      const loading =
        !!host.querySelector(".page-skeleton") ||
        !!document.querySelector(".desk-sidebar .item-anchor.disable-click");
      this.root.setAttribute("aria-busy", String(loading));
      if (loading || this.suspendPortals) return;
      let added = false;
      for (const node of host.querySelectorAll(
        ".editor-js-container .widget"
      )) {
        const classification = this.classify(node);
        if (!classification) continue;
        this.adopt(node, ...classification);
        added = true;
      }
      const standardHeadings = [
        "Your Shortcuts",
        "Shortcuts",
        "Quick Access",
        "Masters & Reports",
        "Reports & Masters",
        "Charts",
        "Number Cards",
        "Getting Started",
      ];
      for (const block of host.querySelectorAll(
        ".editor-js-container .ce-block"
      )) {
        const paragraph = block.querySelector(".ce-paragraph"),
          heading = block.querySelector(".ce-header");
        if (!paragraph && !heading) continue;
        if (
          heading &&
          standardHeadings.some((text) =>
            [text, __(text)].includes(heading.textContent.trim())
          )
        )
          continue;
        this.adopt(block, "content", "Your workspace", null);
        added = true;
      }
      // EditorJS may dispose old blocks on a route change or a refresh.
      for (const [node, marker] of this.portals)
        if (!marker.isConnected || !node.isConnected) {
          marker.remove();
          node.remove();
          this.portals.delete(node);
        }
      for (const node of this.portals.keys()) this.decorateBadge(node, active);
      this.updateDirectory(active, ws);
      for (const [kind, content] of this.sections) {
        const count = [...content.children].filter(
          (node) =>
            !node.hidden &&
            !node.classList.contains("hidden") &&
            !node.classList.contains("hide") &&
            !node.classList.contains("rms-directory-filtered") &&
            node.style.display !== "none"
        ).length;
        content.parentElement.hidden = !count;
        content.style.setProperty(
          "--rms-card-count",
          String(Math.min(count, 4))
        );
      }
      this.updateEditing(ws);
      if (added)
        requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    }
  }
  window.RMSWorkspaceStudio = RMSWorkspaceStudio;
})();
