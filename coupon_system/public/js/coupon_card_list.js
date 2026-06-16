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
				title: __("Bulk Generate Coupon Cards"),
				size: "large",
				fields: [
					{
						fieldname: "items",
						fieldtype: "Table",
						label: __("Card Batches"),
						editable_grid: 1,
						cannot_delete_rows: false,
						fields: [
							{
								fieldname: "naming_series",
								fieldtype: "Select",
								label: __("Series"),
								options: "CC-.YYYY.-.#####",
								default: "CC-.YYYY.-.#####",
								in_list_view: 1,
								columns: 2,
							},
							{
								fieldname: "item_code",
								fieldtype: "Link",
								options: "Item",
								label: __("Item Code"),
								in_list_view: 1,
								reqd: 1,
								columns: 3,
							},
							{
								fieldname: "quantity",
								fieldtype: "Int",
								label: __("Qty"),
								in_list_view: 1,
								reqd: 1,
								columns: 1,
							},
							{
								fieldname: "points_value",
								fieldtype: "Float",
								label: __("Points"),
								in_list_view: 1,
								reqd: 1,
								columns: 2,
							},
							{
								fieldname: "expiry_date",
								fieldtype: "Date",
								label: __("Expiry"),
								in_list_view: 1,
								reqd: 1,
								columns: 2,
							},
							{
								fieldname: "batch_no",
								fieldtype: "Data",
								label: __("Batch No"),
								in_list_view: 1,
								columns: 2,
							},
						],
					},
				],
				primary_action_label: __("Generate"),
				primary_action(values) {
					const items = (values.items || []).filter(
						(r) => r.item_code && r.quantity && r.points_value && r.expiry_date
					);
					if (!items.length) {
						frappe.msgprint(__("Add at least one row with all required fields."));
						return;
					}
					dialog.disable_primary_action();
					frappe.call({
						method: "coupon_system.api.generate_cards",
						args: { items: JSON.stringify(items) },
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
