/* First-run role selection. Master retains the native Frappe/ERPNext slides. */
(() => {
	const call = (method, args = {}) => frappe.call({ method: `rms.onboarding.${method}`, args });
	const NativeWizard = frappe.setup.SetupWizard;

	frappe.setup.on("before_load", () => {
		frappe.setup.slides.unshift({
			name: "rms_site_type",
			title: __("Choose installation type"),
			help: __("Set up a central Master, or connect a Slave to an existing Master."),
			fields: [{
				fieldname: "rms_site_type", fieldtype: "Select", label: __("Installation Type"),
				options: "\nMaster\nSlave", reqd: 1,
			}],
		});
	});

	frappe.setup.SetupWizard = class extends NativeWizard {
		show_slide(id) {
			if (Number(id) === 1 && this.current_slide?.name === "rms_site_type"
				&& this.current_slide.get_value("rms_site_type") === "Slave") {
				this.show_slave();
				return;
			}
			return super.show_slide(id);
		}

		show_slave() {
			this.container.hide();
			this.$slide_progress.hide();
			this.disable_keyboard_nav();
			if (!this.slave_panel) this.make_slave_panel();
			this.slave_panel.show();
		}

		make_slave_panel() {
			this.slave_panel = $("<div class='container setup-wizard-slide with-form'></div>")
				.appendTo(this.parent);
			$("<h1 class='slide-title text-center'></h1>")
				.text(__("Connect this Slave")).appendTo(this.slave_panel);
			$("<p class='text-muted text-center'></p>")
				.text(__("Company and Store settings will be copied from the Master. You do not need to create a company here."))
				.appendTo(this.slave_panel);
			const body = $("<div class='form'></div>").appendTo(this.slave_panel);
			this.slave_form = new frappe.ui.FieldGroup({ body: body[0], fields: [
				{ fieldname: "master_url", fieldtype: "Data", label: __("Master URL"), reqd: 1,
					description: __("The HTTPS address of the existing Master.") },
				{ fieldname: "access_key", fieldtype: "Data", label: __("Access Key"), reqd: 1 },
				{ fieldname: "secret", fieldtype: "Password", label: __("Secret"), reqd: 1,
					description: __("Use an Instance Key issued by the Master, not your login password.") },
				{ fieldname: "test_connection", fieldtype: "Button", label: __("Test connection and load Stores") },
				{ fieldname: "store", fieldtype: "Select", label: __("Store"), options: "", reqd: 1,
					description: __("Only available Stores with an enabled Streaming Branch are listed.") },
				{ fieldname: "site_url", fieldtype: "Data", label: __("This Slave URL"), reqd: 1,
					default: window.location.origin },
			] });
			this.slave_form.make();
			this.slave_form.get_field("test_connection").$input.on("click", () => this.test_master());
			this.slave_stores = [];
			for (const name of ["master_url", "access_key", "secret"]) {
				this.slave_form.get_field(name).$input.on("input change", () => {
					this.slave_stores = [];
					this.slave_form.set_value("store", "");
					this.slave_start.prop("disabled", true);
				});
			}
			const footer = $("<div class='my-4 d-flex justify-content-between'></div>").appendTo(this.slave_panel);
			this.slave_back = $("<button class='btn btn-secondary'></button>").text(__("Back"))
				.appendTo(footer).on("click", () => {
					this.slave_panel.hide(); this.container.show(); this.$slide_progress.show();
					this.setup_keyboard_nav();
				});
			this.slave_start = $("<button class='btn btn-primary'></button>")
				.text(__("Connect and synchronize")).prop("disabled", true)
				.appendTo(footer).on("click", () => this.start_slave());
			this.slave_progress = $("<div role='status' aria-live='polite' class='my-4'></div>")
				.appendTo(this.slave_panel);
			this.slave_resume = $("<button class='btn btn-primary'></button>")
				.text(__("Resume synchronization")).hide().appendTo(this.slave_panel)
				.on("click", () => this.resume_slave());
		}

		async test_master() {
			const values = this.slave_form.get_values(true);
			if (!values.master_url || !values.access_key || !values.secret) {
				frappe.msgprint(__("Enter the Master URL, Access Key and Secret first."));
				return;
			}
			const button = this.slave_form.get_field("test_connection").$input;
			button.prop("disabled", true);
			this.slave_start.prop("disabled", true);
			try {
				const { message } = await call("test_master", {
					master_url: values.master_url, access_key: values.access_key, secret: values.secret,
				});
				// Ignore a response if the operator edited credentials while it was loading.
				if (["master_url", "access_key", "secret"].some(
					name => this.slave_form.get_value(name) !== values[name])) return;
				this.slave_stores = message.stores;
				const field = this.slave_form.get_field("store");
				field.df.options = [{ value: "", label: "" }, ...message.stores.map(s => ({
					value: s.name, label: `${s.title || s.name} (${s.streaming_branch})`,
				}))];
				field.refresh();
				if (message.stores.length === 1) await this.slave_form.set_value("store", message.stores[0].name);
				this.slave_start.prop("disabled", false);
				this.slave_progress.text(__("Connection verified. Select the Store to continue."));
			} catch (_) {
				this.slave_stores = [];
				this.slave_progress.text(__("Connection could not be verified. Check the Master URL and Instance Key."));
			} finally { button.prop("disabled", false); }
		}

		async start_slave() {
			const values = this.slave_form.get_values();
			if (!values || !this.slave_stores.some(s => s.name === values.store)) return;
			this.lock_slave_form();
			this.slave_progress.text(__("Connecting to the Master and preparing the initial copy…"));
			try {
				await call("start_slave", {
					master_url: values.master_url, access_key: values.access_key,
					secret: values.secret, store: values.store, site_url: values.site_url,
				});
				await this.slave_form.set_value("secret", "");
				await this.poll_slave();
			} catch (_) {
				// A remote link may have succeeded before a timeout. Inspect durable state.
				const status = await this.poll_slave();
				if (status?.status === "Not Started" && !status.store) {
					this.unlock_slave_form();
					this.slave_progress.text(__("Setup has not started. Check the connection details and try again."));
				}
			}
		}

		lock_slave_form() {
			for (const field of Object.values(this.slave_form.fields_dict)) {
				field.df.read_only = 1; field.refresh();
			}
			this.slave_back.hide(); this.slave_start.hide();
		}

		unlock_slave_form() {
			for (const field of Object.values(this.slave_form.fields_dict)) {
				field.df.read_only = 0; field.refresh();
			}
			this.slave_back.show(); this.slave_start.show();
		}

		async resume_slave() {
			this.slave_resume.prop("disabled", true);
			try { await call("resume_slave"); }
			finally {
				this.slave_resume.prop("disabled", false);
				await this.poll_slave();
			}
		}

		async poll_slave() {
			clearTimeout(this.slave_timer);
			try {
				const { message: status } = await call("slave_status");
				if (!status.store) return status;
				this.show_slave(); this.lock_slave_form();
				if (status.setup_complete) {
					this.slave_progress.text(__("Synchronization complete. Opening RMS…"));
					window.location.assign("/app"); return status;
				}
				this.slave_progress.text(status.error || (status.status === "Not Started"
					? __("Connection saved. Use Resume synchronization to finish setup.")
					: __("Synchronizing {0}: {1}%", [status.store, Math.round(status.progress)])));
				this.slave_resume.toggle(status.status !== "In Progress");
				if (status.status === "In Progress") {
					this.slave_timer = setTimeout(() => this.poll_slave(), 3000);
				}
				return status;
			} catch (_) {
				this.slave_progress?.text(__("Connection interrupted. Checking synchronization again…"));
				this.slave_timer = setTimeout(() => this.poll_slave(), 5000);
			}
		}
	};

	frappe.setup.on("after_load", () => {
		// A refresh during an initial copy must return to its progress, not company setup.
		frappe.wizard.poll_slave();
	});
})();
