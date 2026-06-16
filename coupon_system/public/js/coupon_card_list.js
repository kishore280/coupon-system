frappe.listview_settings["Coupon Card"] = {
	onload(listview) {
		// Shows in the "Actions" dropdown when rows are checked
		listview.page.add_actions_menu_item(__("Print Selected Cards"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Select at least one card."));
				return;
			}
			const filters = [["Coupon Card", "name", "in", names]];
			const params = new URLSearchParams({ filters: JSON.stringify(filters) });
			window.open(`/print_cards?${params}`, "_blank");
		});

		// Always-visible buttons in the page header
		listview.page.add_inner_button(__("Print Filtered Cards"), () => {
			const filters = listview.get_filters_for_args();
			const params = new URLSearchParams({ filters: JSON.stringify(filters) });
			window.open(`/print_cards?${params}`, "_blank");
		});

		listview.page.add_inner_button(__("Generate Cards"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Generate Coupon Cards"),
				fields: [
					{
						fieldname: "quantity",
						label: __("Quantity"),
						fieldtype: "Int",
						reqd: 1,
					},
					{
						fieldname: "item_code",
						label: __("Item Code"),
						fieldtype: "Link",
						options: "Item",
						reqd: 1,
					},
					{
						fieldname: "points_value",
						label: __("Points Value"),
						fieldtype: "Float",
						reqd: 1,
					},
					{
						fieldname: "expiry_date",
						label: __("Expiry Date"),
						fieldtype: "Date",
						reqd: 1,
					},
					{ fieldtype: "Column Break" },
					{
						fieldname: "batch_no",
						label: __("Batch No"),
						fieldtype: "Data",
					},
					{
						fieldname: "work_order",
						label: __("Work Order"),
						fieldtype: "Data",
					},
				],
				primary_action_label: __("Generate"),
				primary_action(values) {
					dialog.disable_primary_action();
					frappe.call({
						method: "coupon_system.api.generate_cards",
						args: values,
						callback(r) {
							dialog.enable_primary_action();
							if (r.message?.success) {
								dialog.hide();
								frappe.show_alert({
									message: __("{0} cards generated.", [r.message.count]),
									indicator: "green",
								});
								listview.refresh();
							} else {
								frappe.msgprint(r.message?.error || __("Generation failed."));
							}
						},
					});
				},
			});
			dialog.show();
		});
	},
};
