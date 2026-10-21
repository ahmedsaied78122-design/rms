frappe.pages["print-dispatch-queue"].on_page_load = (wrapper) => new RMSPrintDispatchQueue(wrapper);

class RMSPrintDispatchQueue {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Print Jobs"), single_column: true });
		this.page.main.addClass("rms-print-queue-page");
		this.state = { stores: [], store: "", status: "", jobs: [] };
		this.mount();
		this.bind();
		this.load();
	}

	call(method, args = {}) {
		return new Promise((resolve, reject) => frappe.call({ method: `rms.api.printing.${method}`, args,
			callback: (response) => resolve(response.message), error: (error) => reject(error) }));
	}

	escape(value) { return frappe.utils.escape_html(String(value ?? "")); }

	mount() {
		this.page.main.html(`<main class="rms-print-queue-shell">
			<header class="rms-print-queue-header">
				<div class="rms-print-queue-brand"><span class="rms-print-queue-mark">R</span><div><b>RMS Operations</b><small>${__("Back Office")}</small></div></div>
				<div class="rms-print-queue-title"><h1>${__("Print Dispatch Queue")}</h1><p>${__("Track kitchen print jobs and retry failed deliveries.")}</p></div>
				<button class="btn btn-default" data-action="refresh">${__("Refresh")}</button>
			</header>
			<section class="rms-print-queue-summary">
				<div><span>${__("All jobs")}</span><strong data-count="all">0</strong></div>
				<div class="is-queued"><span>${__("Queued / Printing")}</span><strong data-count="active">0</strong></div>
				<div class="is-failed"><span>${__("Failed")}</span><strong data-count="failed">0</strong></div>
				<div class="is-printed"><span>${__("Printed")}</span><strong data-count="printed">0</strong></div>
			</section>
			<section class="rms-print-queue-toolbar">
				<label><span>${__("Store")}</span><select data-filter="store"></select></label>
				<label><span>${__("Status")}</span><select data-filter="status">
					<option value="">${__("All statuses")}</option><option>Queued</option><option>Printing</option><option>Printed</option><option>Failed</option><option>Cancelled</option>
				</select></label>
				<button class="btn btn-primary" data-action="apply">${__("Apply filters")}</button>
			</section>
			<section class="rms-print-queue-table-wrap" data-role="content" aria-live="polite"></section>
		</main>`);
	}

	bind() {
		const root = this.page.main;
		root.on("click", '[data-action="refresh"], [data-action="apply"]', () => {
			this.state.store = root.find('[data-filter="store"]').val() || "";
			this.state.status = root.find('[data-filter="status"]').val() || "";
			this.loadJobs();
		});
		root.on("click", "[data-retry-job]", (event) => this.retry(event.currentTarget.dataset.retryJob));
	}

	async load() {
		try {
			const bootstrap = await this.call("get_bootstrap");
			this.state.stores = bootstrap.stores || [];
			if (!this.state.stores.length) throw new Error(__("No assigned Store is available."));
			const select = this.page.main.find('[data-filter="store"]');
			select.html(`<option value="">${__("All assigned Stores")}</option>` + this.state.stores.map((row) => `<option value="${this.escape(row.name)}">${this.escape(row.title || row.name)}</option>`).join(""));
			await this.loadJobs();
		} catch (error) { this.renderError(error); }
	}

	async loadJobs() {
		const content = this.page.main.find('[data-role="content"]');
		content.html(`<div class="rms-print-queue-state">${__("Loading print jobs…")}</div>`);
		try {
			this.state.jobs = await this.call("get_print_dispatch_jobs", { store: this.state.store || null, status: this.state.status || null }) || [];
			this.render();
		} catch (error) { this.renderError(error); }
	}

	render() {
		const jobs = this.state.jobs;
		this.page.main.find('[data-count="all"]').text(jobs.length);
		this.page.main.find('[data-count="active"]').text(jobs.filter((job) => ["Queued", "Printing"].includes(job.status)).length);
		this.page.main.find('[data-count="failed"]').text(jobs.filter((job) => job.status === "Failed").length);
		this.page.main.find('[data-count="printed"]').text(jobs.filter((job) => job.status === "Printed").length);
		if (!jobs.length) {
			this.page.main.find('[data-role="content"]').html(`<div class="rms-print-queue-state"><b>${__("No print jobs found")}</b><span>${__("Try another Store or status filter.")}</span></div>`);
			return;
		}
		const rows = jobs.map((job) => {
			const canRetry = ["Failed", "Cancelled"].includes(job.status);
			const status = this.escape(__(job.status));
			return `<tr><td><b>${this.escape(job.name)}</b><small>${this.escape(job.document_type)} · ${this.escape(job.document_name)}</small></td>
				<td>${this.escape(job.store)}<small>${this.escape(job.preparation_area || "")}</small></td>
				<td>${this.escape(job.print_device)}</td><td><span class="rms-print-status is-${this.escape(job.status.toLowerCase())}">${status}</span></td>
				<td>${this.escape(job.attempt_count || 0)}</td><td>${job.last_error ? `<span class="rms-print-error" title="${this.escape(job.last_error)}">${this.escape(job.last_error)}</span>` : "—"}</td>
				<td>${this.escape(job.queued_at || "—")}</td><td>${canRetry ? `<button class="btn btn-default btn-xs" data-retry-job="${this.escape(job.name)}">${__("Retry")}</button>` : "—"}</td></tr>`;
		}).join("");
		this.page.main.find('[data-role="content"]').html(`<table class="rms-print-queue-table"><thead><tr><th>${__("Job / Source")}</th><th>${__("Store / Area")}</th><th>${__("Device")}</th><th>${__("Status")}</th><th>${__("Attempts")}</th><th>${__("Last error")}</th><th>${__("Queued")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`);
	}

	async retry(name) {
		try {
			await this.call("retry_print_job", { print_job_name: name });
			frappe.show_alert({ message: __("Print job queued for retry"), indicator: "green" });
			await this.loadJobs();
		} catch (error) { this.renderError(error); }
	}

	renderError(error) {
		this.page.main.find('[data-role="content"]').html(`<div class="rms-print-queue-state is-error"><b>${__("Unable to load print jobs")}</b><span>${this.escape(error?.message || error)}</span></div>`);
	}
}
