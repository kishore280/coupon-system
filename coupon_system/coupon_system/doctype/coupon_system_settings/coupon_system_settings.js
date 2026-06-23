frappe.ui.form.on("Coupon System Settings", {
	refresh(frm) {
		render_architecture(frm);
	},
});

function render_architecture(frm) {
	const box = (title, lines, color) => `
		<div style="flex:1; min-width:200px; border:1px solid var(--border-color,#e3e3e3);
					border-left:4px solid ${color}; border-radius:8px; padding:12px 14px;
					background:var(--card-bg,#fff);">
			<div style="font-weight:600; font-size:13.5px; margin-bottom:4px;">${title}</div>
			<div style="color:var(--text-muted,#667085); font-size:12px; line-height:1.55;">${lines}</div>
		</div>`;

	const arrow = (label) => `
		<div style="text-align:center; color:var(--text-muted,#98a2b3); font-size:11px; padding:2px 0;">
			▼ <span style="font-style:italic;">${label}</span>
		</div>`;

	const html = `
	<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; max-width:780px; margin:2px 0 18px;">
		<p style="color:var(--text-muted,#667085); font-size:12.5px; margin:0 0 14px;">
			A coupon card is a <b>dumb unique token</b>. Its value is <b>not printed on it</b> — it lives on the
			Campaign and is resolved <b>live at the moment of scanning</b>. Change a campaign and every unscanned
			card instantly follows; points already earned stay frozen.
		</p>

		${box("① CAMPAIGN — the dial",
			"<code>points</code> (live value) · <code>validity_months</code> (card shelf life) · " +
			"<code>is_active</code> (pause) · <code>end_date</code> (retire whole campaign). " +
			"Audience = Customer Group (label).", "#2563eb")}

		${arrow("makes cards — from a Work Order's BOM, or the campaign's “Generate Cards” button")}

		${box("② COUPON CARD — the token",
			"Unique code <code>OXFX-XXXX-XXXX</code> · QR = <b>Scan Base URL</b> + code · " +
			"status: Active → Redeemed → Expired / Retired / Void. Carries no value of its own.", "#7c3aed")}

		${arrow("customer scans the QR (mobile app) → earns the campaign's LIVE points")}

		${box("③ COUPON LEDGER — the truth",
			"Immutable CREDIT / DEBIT rows. <b>Balance = SUM(credits) − SUM(debits)</b>. " +
			"Earn at HQ, redeem at any branch against an invoice — one shared balance.", "#16a34a")}

		<div style="margin-top:16px; padding:11px 14px; border-radius:8px;
					background:var(--bg-color,#f8f9fc); border:1px dashed var(--border-color,#d0d5dd);">
			<div style="font-weight:600; font-size:12.5px; margin-bottom:5px;">⚙️ What the settings below control</div>
			<div style="color:var(--text-muted,#667085); font-size:12px; line-height:1.7;">
				<b>Scan Base URL</b> — the HTTPS link baked into every QR (<code>…/s/&lt;code&gt;</code>); also where the
				app-not-installed fallback page lives.<br>
				<b>Card Code Prefix</b> — optional brand prefix on every code, e.g. <code>OXFX</code>.<br>
				<b>Play / App Store URL</b> — shown on the fallback page when the app isn't installed.
			</div>
		</div>
	</div>`;

	frm.get_field("architecture_help").$wrapper.html(html);
}
