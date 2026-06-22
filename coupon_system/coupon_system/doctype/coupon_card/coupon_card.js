frappe.ui.form.on("Coupon Card", {
	refresh(frm) {
		render_codes(frm);

		if (!frm.is_new() && frm.doc.code) {
			frm.add_custom_button(
				__("This Card"),
				() => open_print_page([["Coupon Card", "code", "=", frm.doc.code]]),
				__("Print"),
			);
		}
		if (!frm.is_new() && frm.doc.item_code) {
			frm.add_custom_button(
				__("All Cards for this Item"),
				() => open_print_page([["Coupon Card", "item_code", "=", frm.doc.item_code]]),
				__("Print"),
			);
		}
	},
	code(frm) {
		render_codes(frm);
	},
});

function open_print_page(filters) {
	const url = "/print_cards?filters=" + encodeURIComponent(JSON.stringify(filters));
	window.open(url, "_blank");
}

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
						<div style="display:flex; flex-direction:column; gap:16px; align-items:center;
									padding:16px; border:1px solid var(--border-color, #e0e0e0);
									border-radius:8px; background:var(--card-bg, #fff);">
							${qr ? `<div style="text-align:center;">
								<img src="${qr}" style="width:170px;height:170px;"/>
								<div class="text-muted" style="font-size:11px;margin-top:4px;">Scan to open app (QR)</div>
							</div>` : ""}
							${bar ? `<div style="text-align:center;">
								<img src="${bar}" style="width:100%;max-width:220px;height:55px;object-fit:contain;"/>
								<div class="text-muted" style="font-size:11px;margin-top:4px;">${frappe.utils.escape_html(frm.doc.code)}</div>
							</div>` : ""}
						</div>`);
				},
			});
		},
	});
}
