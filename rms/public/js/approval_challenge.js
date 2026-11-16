frappe.ui.form.on('Approval Challenge', {
 refresh(frm) {
  if (frm.doc.approver===frappe.session.user) frm.add_custom_button(__("View approval details"),()=>window.rmsShowApprovalPopup({challenge_name:frm.doc.name}));
  let context;
  try { context=JSON.parse(frm.doc.operation_payload || '{}'); } catch { return; }
  if (context?.payload) {
   const esc=frappe.utils.escape_html;
   frm.fields_dict.operation_summary.$wrapper.html(`<div><b>${esc(frm.doc.action)}${context.payload.is_waste?' · '+__('Waste'):''}</b><ul>${context.payload.items.map(row=>`<li>${esc(row.title||row.item_name||row.source_pos_invoice_item)} × ${esc(String(row.qty))}</li>`).join('')}</ul><p>${esc(context.payload.comment||'')}</p></div>`);
  }
  if (frm.doc.status==='Pending' && frm.doc.approver===frappe.session.user && ['POS Void','POS Return'].includes(frm.doc.action)) {
   frm.add_custom_button(__('Generate one-time code'),async()=>{
    const response=await frappe.call({method:'rms.api.pos.issue_pos_operation_approval_code',args:{challenge_name:frm.doc.name}});
    await frm.reload_doc();frappe.msgprint({title:__('One-time approval code'),message:`<strong style="font-size:30px;letter-spacing:6px">${frappe.utils.escape_html(response.message.code)}</strong>`});
   });
  }
 }
});
