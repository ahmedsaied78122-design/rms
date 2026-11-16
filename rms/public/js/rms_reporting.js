/* Compact native reports and a scoped analytics library. */
(() => {
  try {
    const cacheKey = "rms-insights-cache-4";
    if (localStorage.getItem(cacheKey) !== "1") {
      localStorage.removeItem("_page:rms-insights");
      localStorage.setItem(cacheKey, "1");
    }
  } catch (_) {
    /* Navigation also works without local storage. */
  }
  const groupLabels = {
    invoice: "Invoice",
    date: "Business Date",
    hour: "Hour",
    week: "Week",
    month: "Month",
    store: "Store",
    brand: "Brand",
    order_type: "Order Type",
    customer: "Customer",
    cashier: "Cashier",
    dining_area: "Dining Area",
    dining_table: "Dining Table",
    category: "Product Category",
    product: "Selling Product",
    invoice_product: "Invoice and Product",
  };
  const inventory = new Set([
    "availability",
    "inventory",
    "draft_counts",
    "reposts",
    "fulfillment",
    "purchase_requests",
    "valuation",
    "trade_flow",
    "purchase_prices",
    "purchase_lines",
    "purchase_summary",
    "asset_purchases",
    "stock_sales",
    "material_issues",
    "production",
    "overhead_manufacturing",
    "overhead_sales",
  ]);
  const enterprise = new Set([
    "trade_flow",
    "erp_customers",
    "customer_cohorts",
    "purchase_lines",
    "purchase_summary",
    "asset_purchases",
    "ledger_details",
    "stock_sales",
    "material_issues",
    "production",
    "overhead_manufacturing",
    "overhead_sales",
  ]);
  const staticFamilies = new Set([
    "recipe_compare",
    "planned_margin",
    "scenarios",
    "no_recipe",
    "ingredients",
  ]);
  const salesFamilies = new Set([
    "sales",
    "customers",
    "payments",
    "discounts",
    "rounding",
    "margin",
    "margin_change",
    "engineering",
    "price_impact",
    "consumption",
  ]);
  const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
  const date = (name, label, defaultValue) => ({
    fieldname: name,
    label: __(label),
    fieldtype: "Date",
    default: defaultValue,
    reqd: 1,
  });
  const link = (name, label, doctype, extra = {}) => ({
    fieldname: name,
    label: __(label),
    fieldtype: "Link",
    options: doctype,
    ...extra,
  });
  const check = (name, label, defaultValue = 0) => ({
    fieldname: name,
    label: __(label),
    fieldtype: "Check",
    default: defaultValue,
  });
  function definition(spec) {
    const family = spec.family,
      stock = inventory.has(family),
      stat = staticFamilies.has(family);
    const today = frappe.datetime.get_today();
    const filters = [
      link("company", "Company", "Company", {
        default: frappe.defaults.get_user_default("Company"),
        reqd: 1,
      }),
    ];
    if (!stat)
      filters.push(
        date(
          "from_date",
          "From Date",
          (["business_day", "margin"].includes(family) &&
            spec.key === "daily_margin") ||
            family === "business_day"
            ? today
            : frappe.datetime.month_start()
        ),
        date("to_date", "To Date", today)
      );
    if (!stock && !enterprise.has(family))
      filters.push(
        link("store", "Store", "Store", {
          get_query: () => ({
            filters: {
              company: frappe.query_report?.get_filter_value("company"),
            },
          }),
        })
      );
    if (stock)
      filters.push(
        link("warehouse", "Warehouse", "Warehouse", {
          get_query: () => ({
            filters: {
              company: frappe.query_report?.get_filter_value("company"),
            },
          }),
        }),
        link("item", "Item", "Item"),
        link("item_group", "Item Group", "Item Group")
      );
    if (
      (salesFamilies.has(family) ||
        stat ||
        [
          "dormant",
          "notes",
          "cancellations",
          "returns",
          "kitchen",
          "occupancy",
        ].includes(family)) &&
      family !== "business_day"
    ) {
      filters.push(
        link("brand", "Brand", "Restaurant Brand"),
        link("order_type", "Order Type", "Order Type")
      );
    }
    if (
      salesFamilies.has(family) ||
      stat ||
      ["dormant", "cancellations", "kitchen"].includes(family)
    )
      filters.push(
        link("category", "Product Category", "Product Category"),
        link("product", "Selling Product", "Selling Product")
      );
    if (
      salesFamilies.has(family) ||
      ["notes", "cancellations", "returns", "occupancy"].includes(family)
    )
      filters.push(link("customer", "Customer", "Customer"));
    if (salesFamilies.has(family))
      filters.push(
        link("cashier", "Cashier", "User"),
        check("include_returns", "Include Credit Notes", 1)
      );
    if (
      [
        "sales",
        "discounts",
        "rounding",
        "margin",
        "margin_change",
        "engineering",
      ].includes(family)
    ) {
      const keys =
        family.startsWith("margin") || family === "engineering"
          ? [
              "product",
              "category",
              "store",
              "brand",
              "order_type",
              "customer",
              "cashier",
            ]
          : Object.keys(groupLabels);
      if (!keys.includes(spec.group_by)) keys.unshift(spec.group_by);
      filters.push({
        fieldname: "group_by",
        label: __("Group By"),
        fieldtype: "Select",
        options: keys.map((value) => ({
          label: __(groupLabels[value]),
          value,
        })),
        default: spec.group_by,
      });
      filters.push(
        check(
          "compare_previous",
          "Compare Previous Period",
          family === "margin_change" ? 1 : 0
        )
      );
    }
    if (salesFamilies.has(family) && family !== "consumption")
      filters.push({
        fieldname: "business_period",
        label: __("Date Basis"),
        fieldtype: "Select",
        options: [
          { label: __("Selected Dates"), value: "" },
          { label: __("Current Business Day"), value: "today" },
          { label: __("Current Business Month"), value: "month" },
        ],
        default: "",
      });
    if (family === "occupancy")
      filters.push(
        link("dining_area", "Dining Area", "Dining Area"),
        link("dining_table", "Dining Table", "Dining Table"),
        check("working_hours_only", "Use Configured Working Hours")
      );
    if (family === "kitchen")
      filters.push(
        link("preparation_area", "Preparation Area", "Preparation Area"),
        {
          fieldname: "target_minutes",
          label: __("Analysis Target Minutes"),
          fieldtype: "Float",
        }
      );
    if (family === "printing")
      filters.push(link("print_device", "Print Device", "Print Device"));
    if (stat || family === "dormant")
      filters.push({
        fieldname: "enabled",
        label: __("Product Status"),
        fieldtype: "Select",
        options: [
          { label: __("All"), value: "" },
          { label: __("Enabled"), value: "1" },
          { label: __("Disabled"), value: "0" },
        ],
        default: "1",
      });
    if (family === "ingredients")
      filters.push(link("item", "Ingredient", "Item", { reqd: 1 }));
    if (family === "dormant")
      filters.push({
        fieldname: "dormant_days",
        label: __("Days Without Sales"),
        fieldtype: "Int",
        default: 30,
      });
    if (family === "consumption")
      filters.push(
        link("item", "Ingredient", "Item"),
        check("include_modifiers", "Include Modifiers", 1),
        check("include_waste", "Include Waste")
      );
    if (family === "availability")
      filters.push(
        check("include_recipe", "Show Recipe Capacity"),
        link("order_type", "Order Type", "Order Type"),
        link("product", "Selling Product", "Selling Product"),
        link("category", "Product Category", "Product Category")
      );
    if (family === "production")
      filters.push({
        fieldname: "production_view",
        label: __("Production View"),
        fieldtype: "Select",
        reqd: 1,
        options: [
          { value: "work_orders", label: __("Work Orders") },
          { value: "job_cards", label: __("Job Cards") },
          { value: "quality", label: __("Quality Inspections") },
        ],
        default: "work_orders",
      });
    if (family === "inventory")
      filters.push(check("hide_zero", "Hide Zero Balances", 1));
    if (family === "draft_counts")
      filters.push(
        {
          fieldname: "qty_threshold",
          label: __("Minimum Quantity Variance"),
          fieldtype: "Float",
          default: 0,
        },
        {
          fieldname: "value_threshold",
          label: __("Minimum Value Variance"),
          fieldtype: "Currency",
          default: 0,
        }
      );
    if (family === "business_day")
      filters.push(check("closed_day_only", "Require a Closed Business Day"));
    if (family === "purchase_prices")
      filters.push(link("supplier", "Supplier", "Supplier"));
    if (family === "scenarios") {
      const product = filters.find((f) => f.fieldname === "product");
      if (product) product.reqd = 1;
    }
    if (family === "returns")
      filters.push({
        fieldname: "status",
        label: __("Status"),
        fieldtype: "Select",
        options: ["", "Pending Approval", "Approved", "Rejected"].map(
          (value) => ({ value, label: __(value) })
        ),
      });
    if (["erp_customers", "customer_cohorts"].includes(family))
      filters.push(link("customer", "Customer", "Customer"));
    if (
      ["purchase_lines", "purchase_summary", "asset_purchases"].includes(family)
    )
      filters.push(link("supplier", "Supplier", "Supplier"));
    if (family === "ledger_details" || family.startsWith("overhead_")) {
      const allocation = family.startsWith("overhead_");
      filters.push(
        link(
          "account",
          allocation ? "Overhead Expense Account" : "Account",
          "Account",
          {
            reqd: allocation,
            get_query: () => ({
              filters: {
                company: frappe.query_report?.get_filter_value("company"),
                ...(allocation ? { root_type: "Expense" } : {}),
              },
            }),
          }
        ),
        link("cost_center", "Cost Center", "Cost Center", {
          reqd: allocation,
          get_query: () => ({
            filters: {
              company: frappe.query_report?.get_filter_value("company"),
            },
          }),
        })
      );
    }
    if (family === "ledger_details")
      filters.push(
        {
          fieldname: "party_type",
          label: __("Party Type"),
          fieldtype: "Select",
          options: ["", "Customer", "Supplier"].map((value) => ({
            value,
            label: __(value),
          })),
          on_change: (report) => {
            report.get_filter("party")?.set_input("");
            if (!report._no_refresh) report.refresh();
          },
        },
        link("party", "Party", "Customer", {
          fieldtype: "Dynamic Link",
          options: "party_type",
          get_options: () =>
            frappe.query_report?.get_filter_value("party_type") || "",
          depends_on: "eval:doc.party_type",
        })
      );
    if (family === "recipe_compare") {
      const product = filters.find((f) => f.fieldname === "product");
      Object.assign(product, {
        fieldtype: "MultiSelectList",
        get_data: (txt) => frappe.db.get_link_options("Selling Product", txt),
      });
    }
    const compare = filters.find((f) => f.fieldname === "compare_previous");
    if (compare)
      compare.depends_on =
        "eval:!['week','month'].includes(doc.group_by) && !doc.business_period";
    if (family === "availability")
      for (const f of filters)
        if (["order_type", "product", "category"].includes(f.fieldname))
          f.depends_on = "eval:doc.include_recipe";
    return {
      filters,
      onload: (report) => enhance(report, spec),
      get_datatable_options: (opts) => ({
        ...opts,
        inlineFilters: true,
        serialNoColumn: false,
        checkboxColumn: false,
      }),
      formatter(value, row, column, data, defaultFormatter) {
        if (value == null && ["Currency", "Float", "Percent", "Int", "Check"].includes(column.fieldtype))
          return '<span class="text-muted">—</span>';
        const text = defaultFormatter(value, row, column, data);
        if (
          [
            "gross_profit",
            "value_change",
            "price_impact",
            "change_percent",
            "quantity_variance",
            "value_variance",
          ].includes(column.fieldname) &&
          Number.isFinite(Number(value))
        )
          return `<span class="rms-report-number ${Number(value) < 0 ? "is-negative" : "is-positive"}">${text}</span>`;
        if (column.fieldname === "classification")
          return `<span class="rms-report-position">${escape(__(String(value || "")))}</span>`;
        return text;
      },
    };
  }
  function enhance(report, spec = {}) {
    const root = report.page?.main?.[0] || report.$report?.[0];
    if (!root) return;
    root.classList.add("rms-report-page");
    root.querySelector(".rms-report-tools")?.remove();
    for (const field of report.filters || []) {
      if (field.df.fieldtype !== "Check") {
        const wrapper = $(field.wrapper);
        wrapper.children(".rms-report-filter-label").remove();
        $("<span>", {
          class: "rms-report-filter-label",
          text: field.df.label,
        }).prependTo(wrapper);
        field.$input?.attr("aria-label", field.df.label);
      }
    }
    const basic = new Set([
      "company",
      "from_date",
      "to_date",
      "store",
      "warehouse",
      "group_by",
    ]);
    const advanced = (report.filters || []).filter(
      (f) => !basic.has(f.df.fieldname) && !f.df.reqd
    );
    for (const field of advanced)
      $(field.wrapper).addClass("rms-filter-advanced");
    const active = advanced.filter((f) => {
      const value = f.get_value();
      return (
        value !== undefined &&
        value !== null &&
        value !== "" &&
        JSON.stringify(value) !==
          JSON.stringify(
            f.df.default ?? (f.df.fieldtype === "Check" ? 0 : "")
          ) &&
        !(Array.isArray(value) && !value.length)
      );
    }).length;
    root.classList.toggle("rms-show-advanced", Boolean(report._rmsAdvanced));
    const toolbar = document.createElement("div");
    toolbar.className = "rms-report-tools";
    const timed =
      report.get_filter?.("from_date") && report.get_filter?.("to_date");
    toolbar.innerHTML = `<div class="rms-report-presets">${
      timed
        ? (spec.family === "business_day"
            ? [["today", "Today"]]
            : [
                ["today", "Today"],
                ["week", "Last 7 Days"],
                ["month", "This Month"],
              ]
          )
            .map(
              ([key, label]) =>
                `<button type="button" data-period="${key}">${__(label)}</button>`
            )
            .join("")
        : ""
    }</div>${advanced.length ? `<button type="button" data-advanced aria-expanded="${Boolean(report._rmsAdvanced)}">${__("More Filters")}${active ? ` · ${active}` : ""}</button>` : ""}<span class="rms-report-scope">${__(spec.workspace || "Reports")}</span><button type="button" data-explorer>${__("Report Explorer")} <span aria-hidden="true">↗</span></button>`;
    root.prepend(toolbar);
    toolbar.addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      if (button.hasAttribute("data-advanced")) {
        report._rmsAdvanced = !root.classList.contains("rms-show-advanced");
        root.classList.toggle("rms-show-advanced", report._rmsAdvanced);
        button.setAttribute("aria-expanded", String(report._rmsAdvanced));
        return;
      }
      if (button.hasAttribute("data-explorer")) {
        frappe.set_route("rms-insights");
        return;
      }
      const today = frappe.datetime.get_today();
      const period = button.dataset.period;
      const from =
        period === "today"
          ? today
          : period === "week"
            ? frappe.datetime.add_days(today, -6)
            : frappe.datetime.month_start();
      const values = { from_date: from, to_date: today };
      if (report.get_filter?.("business_period")) values.business_period = "";
      await report.set_filter_value(values);
    });
  }
  function installNumberFormatting() {
    const factory = frappe.widget?.widget_factory;
    if (!factory?.number_card || factory.number_card.rmsCurrency) return;
    const Native = factory.number_card;
    factory.number_card = class extends Native {
      static rmsCurrency = true;
      get_number_for_custom_card(res) {
        if (res?.rms_analytics) {
          this.number = res.value;
          this.set_formatted_number(
            { ...res, options: "currency" },
            { currency: res.currency }
          );
        } else return super.get_number_for_custom_card(res);
      }
    };
  }
  window.RMSReporting = {
    definition,
    enhance,
    installNumberFormatting,
    groupLabels,
  };
  installNumberFormatting();
  $(document).on("app_ready.rmsReports", installNumberFormatting);
})();
