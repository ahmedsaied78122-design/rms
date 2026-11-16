(() => {
 const esc = value => frappe.utils.escape_html(String(value ?? ''));
 const amount = (value, currency) => format_currency(Number(value || 0), currency || undefined);
 window.rmsShowApprovalPopup = async (args) => {
  try {
   const response = await frappe.call({method:'rms.approval_notifications.get_approval_details',args});
   const doc=response.message, p=doc.payload || {}, discount=doc.action==='POS Order Discount';
   const labels={'Issued':'كود ساري','Expired':'انتهت الصلاحية','Consumed':'تم استخدام الكود','Revoked':'تم إلغاء الكود','Pending':'بانتظار إصدار الكود','Changed':'تغيّر الأوردر — يلزم طلب كود جديد'};
   const operation=discount?'اعتماد خصم':doc.action==='POS Void'?'اعتماد إلغاء أصناف':doc.action==='POS Return'?'اعتماد مرتجع':'اعتماد مصروف';
   const row=(label,value)=>value!==undefined && value!==null && value!=='' ? `<div class="rms-approval-detail"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`:'';
   const items=(p.items || []).map(item=>`<tr><td>${esc(item.title || item.item_name || item.source_pos_invoice_item)}${item.modifiers?.length?`<small>الإضافات: ${esc(item.modifiers.join("، "))}</small>`:""}${item.notes?`<small>${esc(item.notes)}</small>`:''}</td><td>${esc(item.qty)}</td>${discount?`<td>${item.rate!==undefined?amount(item.rate,p.currency):'—'}</td><td>${item.amount!==undefined?amount(item.amount,p.currency):'—'}</td>`:''}</tr>`).join('');
   const summary=discount?`المستخدم ${doc.requester_name} (${doc.requester}) يطلب خصم ${p.discount_value}${p.discount_type==='Percentage'?'%':' '+(p.currency || '')}`:`المستخدم ${doc.requester_name} (${doc.requester}) يطلب ${operation}`;
   const financial=discount && p.total_before!==undefined ? `<div class="rms-approval-totals"><div><span>الإجمالي قبل الخصم</span><b>${amount(p.payable_before ?? p.total_before,p.currency)}</b></div><div class="is-discount"><span>قيمة الخصم</span><b>${amount(p.discount_amount,p.currency)}</b></div><div><span>المطلوب تحصيله بعد الخصم</span><b>${amount(p.payable_after ?? p.total_after,p.currency)}</b></div></div>${doc.historical_snapshot?'':`<p class="rms-approval-muted">قيم الأوردر الحالية؛ الطلب القديم لم يحفظ لقطة للمبالغ وقت إرساله.</p>`}`:p.amount!==undefined?`<div class="rms-approval-totals"><div><span>${doc.action==='POS Return'?'مبلغ الاسترداد':'قيمة المصروف'}</span><b>${amount(p.amount,p.currency)}</b></div></div>`:'';
   const html=`<section class="rms-approval-popup" dir="rtl"><h3>${esc(summary)}</h3><div class="rms-approval-code-box"><span data-approval-state>${esc(labels[doc.status] || doc.status)}</span>${doc.code?`<div class="rms-approval-code-reveal"><strong data-approval-code dir="ltr" aria-label="الكود مخفي">••••••</strong><button type="button" class="btn btn-default rms-approval-eye" data-approval-reveal aria-label="إظهار الكود" title="إظهار الكود" aria-pressed="false"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path data-approval-eye-slash d="m3 3 18 18" style="display:none"/></svg></button></div><button type="button" class="btn btn-default" data-approval-copy disabled>نسخ الكود</button><small data-approval-countdown></small>`:`<p>الكود غير متاح. لو انتهت صلاحيته، يطلب الكاشير كودًا جديدًا بعد مراجعة العملية.</p>`}</div>${financial}<div class="rms-approval-details">${row('رقم الأوردر / المستند',doc.subject)}${row('الفرع',doc.store)}${row('البراند',p.brand)}${row('نوع الطلب',p.order_type)}${row('العميل',p.customer)}${row('الترابيزة',p.table)}${row('حساب الضيف',p.guest_check_name)}${row('هالك',p.is_waste?'نعم':null)}${row('تصنيف المصروف',p.category)}${row('طريقة الدفع',p.mode_of_payment)}${row('السبب / التعليق',p.reason ? p.reason+(p.comment?' — '+p.comment:'') : p.comment)}${row('حد خصم المستخدم',p.requester_limit_percent!==undefined && p.requester_limit_percent!==null?p.requester_limit_percent+'%':null)}</div>${items?`<div class="rms-approval-items"><table><thead><tr><th>الصنف</th><th>الكمية</th>${discount?'<th>سعر الوحدة</th><th>القيمة</th>':''}</tr></thead><tbody>${items}</tbody></table></div>`:''}<p class="rms-approval-muted">شارك الكود مع الكاشير فقط لو موافق على التفاصيل دي. الكود يُستخدم مرة واحدة.</p></section>`;
   const dialog=new frappe.ui.Dialog({title:operation,size:'large',fields:[{fieldtype:'HTML',fieldname:'details',options:html}],primary_action_label:__('Close'),primary_action:()=>dialog.hide()});
   dialog.$wrapper.addClass('rms-approval-popup-dialog');
   let timer, revealed=false;
   const maskCode=()=>{revealed=false;dialog.$wrapper.find("[data-approval-code]").text("••••••").attr("aria-label","الكود مخفي");dialog.$wrapper.find("[data-approval-copy]").prop("disabled",true);dialog.$wrapper.find("[data-approval-reveal]").attr({"aria-label":"إظهار الكود",title:"إظهار الكود","aria-pressed":"false"});dialog.$wrapper.find("[data-approval-eye-slash]").attr("style","display:none");};
   if(doc.code){
    const deadline=Date.now()+doc.remaining_seconds*1000;
    const tick=()=>{const seconds=Math.max(0,Math.ceil((deadline-Date.now())/1000));dialog.$wrapper.find('[data-approval-countdown]').text(`متبقي ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`);if(!seconds){clearInterval(timer);maskCode();dialog.$wrapper.find('[data-approval-reveal]').prop('disabled',true);dialog.$wrapper.find('[data-approval-state]').text('انتهت الصلاحية');}};
    dialog.$wrapper.on('click','[data-approval-reveal]',()=>{
     if(Date.now()>=deadline)return;
     if(revealed){maskCode();return;}
     revealed=true;dialog.$wrapper.find('[data-approval-code]').text(doc.code).attr('aria-label','كود الموافقة');
     dialog.$wrapper.find('[data-approval-copy]').prop('disabled',false);
     dialog.$wrapper.find('[data-approval-reveal]').attr({'aria-label':'إخفاء الكود',title:'إخفاء الكود','aria-pressed':'true'});
     dialog.$wrapper.find('[data-approval-eye-slash]').attr('style','');
    });
    dialog.$wrapper.on('click','[data-approval-copy]',()=>{if(revealed && Date.now()<deadline)frappe.utils.copy_to_clipboard(doc.code);});
    tick();timer=setInterval(tick,1000);
   }
   dialog.onhide=()=>{clearInterval(timer);if(doc.code)maskCode();};dialog.show();return dialog;
  } catch(error){frappe.msgprint(error.message || __('Could not load approval details.'));}
 };
 // Capture approval notifications before Desk's link/router handlers navigate away.
 document.addEventListener('click',event=>{
  if(event.target.closest?.('.mark-as-read'))return;
  const link=event.target.closest?.('a.notification-item[data-name], a.recent-item[data-name]');
  if(!link)return;
  const href=link.getAttribute('href') || '';
  const match=href.match(/(?:\/app\/approval-challenge\/|#Form\/Approval%20Challenge\/)([^?#/]+)/i);
  if(!match)return;
  event.preventDefault();event.stopImmediatePropagation();
  window.rmsShowApprovalPopup({notification_name:link.dataset.name,challenge_name:decodeURIComponent(match[1])}).then(dialog=>{if(dialog)link.classList.remove('unread');});
 },true);
})();
