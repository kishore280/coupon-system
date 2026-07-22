frappe.ui.form.on("Coupon Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Generate Cards"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Generate Cards — {0}", [frm.doc.campaign_name]),
				fields: [
					{
						fieldname: "quantity",
						label: __("Quantity"),
						fieldtype: "Int",
						reqd: 1,
						default: 100,
						description: __("Cards are minted Active, ready to print. Value resolves live from this campaign at scan."),
					},
					{
						fieldname: "item_code",
						label: __("Item (optional, for traceability)"),
						fieldtype: "Link",
						options: "Item",
					},
				],
				primary_action_label: __("Generate"),
				primary_action(values) {
					// A store-owned campaign mints locally AND registers the defs to HQ
					// (store_mint); a central campaign generates on HQ (generate_cards).
					const is_store = !!frm.doc.owned_by_store;
					frappe.call({
						method: is_store
							? "coupon_system.hq_client.store_mint"
							: "coupon_system.api.generate_cards",
						args: is_store
							? { quantity: values.quantity, campaign: frm.doc.name }
							: {
									quantity: values.quantity,
									campaign: frm.doc.name,
									item_code: values.item_code || null,
							  },
						freeze: true,
						freeze_message: is_store
							? __("Minting & registering to HQ…")
							: __("Generating cards…"),
						callback(r) {
							const m = r.message;
							if (m && m.success) {
								const count =
									m.count != null ? m.count : m.codes ? m.codes.length : 0;
								frappe.show_alert({
									message: is_store
										? __("{0} store coupons minted & registered to HQ", [count])
										: __("{0} cards generated", [count]),
									indicator: "green",
								});
								d.hide();
							} else {
								frappe.msgprint(
									(m && m.error) || __("Generation failed")
								);
							}
						},
					});
				},
			});
			d.show();
		});

		if (!frm.doc.is_active) {
			frm.dashboard.set_headline(
				__("This campaign is inactive — its cards cannot be scanned.")
			);
		}

		render_card_stats(frm);
	},
});

function render_card_stats(frm) {
	frappe.call({
		method: "coupon_system.api.campaign_card_counts",
		args: { campaign: frm.doc.name },
		callback(r) {
			const s = r.message;
			if (!s) return;
			const tile = (label, val, color) => `
				<div style="flex:1; min-width:90px; text-align:center; padding:12px 8px;
							border:1px solid var(--border-color); border-radius:8px;">
					<div style="font-size:22px; font-weight:700; color:${color || 'inherit'};">${val}</div>
					<div class="text-muted" style="font-size:11px; text-transform:uppercase;">${label}</div>
				</div>`;
			const html = `
				<div style="display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 4px;">
					${tile(__("Total"), s.total)}
					${tile(__("Active"), s.active, "#2563eb")}
					${tile(__("Redeemed"), s.redeemed, "#16a34a")}
					${tile(__("Expired"), s.expired, "#a16207")}
					${tile(__("Void"), s.void, "#9ca3af")}
					${tile(__("Potential Pts"), s.potential_points, "#7c3aed")}
				</div>`;
			frm.dashboard.add_section(html, __("Card Lifecycle"));
		},
	});
}
