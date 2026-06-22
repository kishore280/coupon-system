frappe.ui.form.on("Coupon Card", {
	refresh(frm) {
		render_codes(frm);
	},
	code(frm) {
		render_codes(frm);
	},
});

function render_codes(frm) {
	const wrapper = frm.get_field("qr_preview").$wrapper;
	if (!frm.doc.code) {
		wrapper.empty();
		return;
	}
	wrapper.html(`<div class="text-muted">Loading codes…</div>`);

	frappe.call({
		method: "coupon_system.api.get_card_images",
		args: { codes: JSON.stringify([frm.doc.code]), img_type: "qr" },
		callback(r) {
			const qr = r.message && r.message[frm.doc.code];
			frappe.call({
				method: "coupon_system.api.get_card_images",
				args: { codes: JSON.stringify([frm.doc.code]), img_type: "barcode" },
				callback(r2) {
					const bar = r2.message && r2.message[frm.doc.code];
					wrapper.html(`
						<div style="display:flex; gap:32px; align-items:center; flex-wrap:wrap; padding:8px 0;">
							${qr ? `<div style="text-align:center;">
								<img src="${qr}" style="width:160px;height:160px;"/>
								<div class="text-muted" style="font-size:11px;margin-top:4px;">Scan (QR)</div>
							</div>` : ""}
							${bar ? `<div style="text-align:center;">
								<img src="${bar}" style="height:60px;"/>
								<div class="text-muted" style="font-size:11px;margin-top:4px;">${frappe.utils.escape_html(frm.doc.code)}</div>
							</div>` : ""}
						</div>`);
				},
			});
		},
	});
}
