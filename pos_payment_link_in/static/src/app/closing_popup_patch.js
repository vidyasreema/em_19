/** @odoo-module **/

import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";

if (Array.isArray(ClosePosPopup.props)) {
    ClosePosPopup.props.push("payment_link_in_details?");
} else {
    ClosePosPopup.props = {
        ...ClosePosPopup.props,
        payment_link_in_details: { type: Object, optional: true },
    };
}