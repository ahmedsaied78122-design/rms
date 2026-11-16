frappe.pages["rms-insights"].on_page_load = (wrapper) =>
  new RMSInsights(wrapper);
class RMSInsights {
  constructor(wrapper) {
    this.page = frappe.ui.make_app_page({
      parent: wrapper,
      title: __("Report Explorer"),
      single_column: true,
    });
    this.category = "all";
    this.query = "";
    this.rows = [];
    this.page.main.addClass("rms-insights");
    this.page.main.html(
      `<header class="rms-insights-head"><div><h2>${__("A clearer view of your business")}</h2><p>${__("Find a report, explore the details and follow the numbers back to their documents.")}</p></div><div class="rms-insights-mark" aria-hidden="true">R</div></header><div class="rms-insights-filters"><input class="rms-insights-search" type="search" aria-label="${__("Find a report")}" placeholder="${__("Find a report")}"><div class="rms-insights-tabs" role="group" aria-label="${__("Workspace")}"></div></div><div class="rms-insights-count" role="status"></div><div class="rms-insights-grid"></div>`
    );
    this.page.main.on("input", ".rms-insights-search", (event) => {
      this.query = event.target.value.trim().toLocaleLowerCase();
      this.render();
    });
    this.page.main.on("click", "[data-workspace]", (event) => {
      this.category = event.currentTarget.dataset.workspace;
      this.render();
    });
    this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
    this.load();
  }
  async load() {
    const ticket = (this.ticket || 0) + 1;
    this.ticket = ticket;
    this.page.main.find(".rms-insights-count").text(__("Loading…"));
    try {
      const response = await frappe.xcall(
        "rms.analytics.dashboard.get_catalog"
      );
      if (ticket !== this.ticket) return;
      this.rows = response.reports;
      if (response.business_dashboard)
        this.page
          .set_primary_action(
            __("Business Dashboard"),
            () =>
              frappe.set_route("dashboard-view", response.business_dashboard),
            "chart"
          )
          .attr("aria-label", __("Business Dashboard"))
          .attr("title", __("Business Dashboard"));
      else this.page.clear_primary_action();
      this.render();
    } catch (error) {
      if (ticket === this.ticket)
        this.page.main
          .find(".rms-insights-count")
          .text(__("Unable to load reports. Refresh to try again."));
    }
  }
  render() {
    const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
    const spaces = [...new Set(this.rows.map((r) => r.workspace))].sort(
      (a, b) => __(a).localeCompare(__(b))
    );
    this.page.main
      .find(".rms-insights-tabs")
      .html(
        [["all", "All Reports"], ...spaces.map((x) => [x, x])]
          .map(
            ([value, label]) =>
              `<button type="button" data-workspace="${esc(value)}" aria-pressed="${this.category === value}">${esc(__(label))}</button>`
          )
          .join("")
      );
    const visible = this.rows.filter(
      (r) =>
        (this.category === "all" || r.workspace === this.category) &&
        (!this.query ||
          [r.title, r.name, __(r.workspace), __(r.ref_doctype)]
            .join(" ")
            .toLocaleLowerCase()
            .includes(this.query))
    );
    this.page.main
      .find(".rms-insights-count")
      .text(__("{0} reports", [visible.length]));
    const icon =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 3v18h17M8 15l4-5 4 3 5-7"/></svg>';
    this.page.main
      .find(".rms-insights-grid")
      .html(
        visible.length
          ? visible
              .map(
                (r) =>
                  `<a class="rms-insight-card" href="/app/${r.report_type === "Report Builder" ? frappe.router.slug(r.ref_doctype) + "/view/report/" : "query-report/"}${encodeURIComponent(r.name)}"><span class="rms-insight-icon">${icon}</span><span><b>${esc(r.title)}</b><small>${esc(__(r.workspace))} · ${esc(__(r.ref_doctype))}</small></span></a>`
              )
              .join("")
          : `<div class="rms-insights-empty">${__("No matching reports")}</div>`
      );
  }
}
