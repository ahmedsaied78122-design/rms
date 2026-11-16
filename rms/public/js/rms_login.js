frappe.ready(() => {
	// Native login handlers still own submission, recovery, providers and MFA.
	const toggles = document.querySelectorAll(".rms-native-login .toggle-password");
	for (const toggle of toggles) {
		const input = document.querySelector(toggle.getAttribute("toggle"));
		if (!input) continue;
		toggle.setAttribute("role", "button");
		toggle.setAttribute("tabindex", "0");
		toggle.setAttribute("aria-controls", input.id);
		const sync = () => {
			const visible = input.type === "text";
			toggle.setAttribute("aria-pressed", String(visible));
			toggle.setAttribute("aria-label", visible ? __("Hide password") : __("Show password"));
		};
		toggle.addEventListener("click", sync);
		toggle.addEventListener("keydown", event => {
			if (["Enter", " "].includes(event.key)) { event.preventDefault(); toggle.click(); }
		});
		sync();
	}
	for (const id of ["forgot_email", "login_with_email_link_email"]) {
		const input = document.getElementById(id);
		if (!input || document.querySelector(`label[for="${id}"]`)) continue;
		const label = document.createElement("label");
		label.className = "form-label";
		label.htmlFor = id;
		label.textContent = __("Email Address");
		input.closest(".email-field").before(label);
	}
	for (const link of document.querySelectorAll(".rms-auth-footer nav a")) {
		link.addEventListener("click", () => { link.hash = window.location.hash; });
	}
});
