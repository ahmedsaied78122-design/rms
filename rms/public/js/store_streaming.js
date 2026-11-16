frappe.ui.form.on('Store', {
	refresh(frm) {
		const field = frm.fields_dict.streaming_connection;
		if (!field) return;
		const data = frm.doc.__onload?.rms_streaming_connection;
		if (!data) { field.$wrapper.empty(); return; }
		const esc = frappe.utils.escape_html, peer = data.peer;
		const value = peer ? `<a href="/app/${frappe.router.slug(data.doctype)}/${encodeURIComponent(peer.name)}">${esc(peer.domain || peer.name)}</a> · ${esc(__(peer.connection_status))}` : esc(__('No Slave is connected to this Store. Select this Store when connecting a Slave.'));
		field.$wrapper.html(`<label class="control-label">${__('Streaming connection')}</label><p>${value}</p>`);
	}
});
