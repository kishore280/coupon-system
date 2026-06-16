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

		// Always-visible button in the page header
		listview.page.add_inner_button(__("Print Filtered Cards"), () => {
			const filters = listview.get_filters_for_args();
			const params = new URLSearchParams({ filters: JSON.stringify(filters) });
			window.open(`/print_cards?${params}`, "_blank");
		});
	},
};
