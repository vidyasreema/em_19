import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

import { loadGoogleMaps } from "./location_bar";

const FIELDS = ["partner_id", "apartment", "building", "directions", "name", "phone", "latitude", "longitude", "area"];

/**
 * "Address details" (v2 prototype). Opened by View cart when the cart has no
 * delivery address, and by Change / Edit / Add on the order page. A new
 * address starts at the pin of the "Deliver to" bar ("Edit pin" opens its
 * map); the building, city and emirate are read from the pin.
 */
export class JourneyAddressSheet extends Interaction {
    static selector = ".o_journey_address_modal";
    dynamicContent = {
        _document: {
            "t-on-journey_open_address": () => this.open(),
            "t-on-journey_location_changed": this.onLocationChanged,
            "t-on-click": this.onDocumentClick,
        },
        ".o_journey_address_edit_pin": { "t-on-click": this.editPin },
        ".o_journey_address_form": { "t-on-submit.prevent": this.locked(this.save, true) },
    };

    setup() {
        this.modal = window.Modal.getOrCreateInstance(this.el);
        this.registerCleanup(() => this.modal.dispose());
        this.form = this.el.querySelector(".o_journey_address_form");
        const elements = this.form.elements;
        // What a new address starts with (the pin of the bar, the customer)
        this.defaults = {
            name: elements.name.value,
            phone: elements.phone.value,
            latitude: elements.latitude.value,
            longitude: elements.longitude.value,
            area: elements.area.value,
        };
        this.editing = false;
        this.editingPin = false;
        this.reopen = false;
        this.pinFilledBuilding = "";
        this.readPin = null;
        const onHidden = () => this.onHidden();
        this.el.addEventListener("hidden.bs.modal", onHidden);
        this.registerCleanup(() => this.el.removeEventListener("hidden.bs.modal", onHidden));
        this.pickerEl = document.querySelector(".o_journey_location_modal");
        if (this.pickerEl) {
            // Back to the sheet once the map is closed
            const onPickerHidden = () => {
                if (this.reopen) {
                    this.reopen = false;
                    this.modal.show();
                }
            };
            this.pickerEl.addEventListener("hidden.bs.modal", onPickerHidden);
            this.registerCleanup(() => this.pickerEl.removeEventListener("hidden.bs.modal", onPickerHidden));
        }
    }

    onDocumentClick(ev) {
        const button = ev.target.closest(".o_journey_address_open");
        if (button) {
            ev.preventDefault();
            this.open(button.dataset.address ? JSON.parse(button.dataset.address) : null, button.dataset.focus);
        }
    }

    /**
     * @param {Object} [address] the address to change (fields of the sheet), none for a new one
     * @param {string} [focus] the field to start with
     */
    open(address = null, focus = null) {
        if (address || this.editing) {
            // Changing an address, or back to a new one after a change: start over
            this.fill(address || { ...this.defaults, label: "home" });
        }
        this.editing = !!address;
        this.clearErrors();
        this.modal.show();
        if (focus) {
            this.el.addEventListener("shown.bs.modal", () => this.form.elements[focus]?.focus(), { once: true });
        }
        if (!address) {
            this.fillFromPin();
        }
    }

    fill(values) {
        const elements = this.form.elements;
        for (const field of FIELDS) {
            elements[field].value = values[field] ?? "";
        }
        for (const radio of this.form.querySelectorAll("input[name='label']")) {
            radio.checked = radio.value === (values.label || "home");
        }
        for (const field of ["city", "state", "country_code"]) {
            elements[field].value = "";
        }
        this.showPin(values.area, !!values.latitude);
        this.pinFilledBuilding = "";
        // A saved address keeps its building: the map is read when its pin moves
        this.readPin = values.partner_id ? `${values.latitude},${values.longitude}` : null;
    }

    showPin(area, hasPin) {
        this.el.querySelector(".o_journey_address_area").textContent = hasPin
            ? area || _t("Your pin")
            : _t("Set your delivery location");
        const editPin = this.el.querySelector(".o_journey_address_edit_pin");
        if (editPin) {
            editPin.textContent = hasPin ? _t("Edit pin") : _t("Set pin");
        }
    }

    editPin() {
        if (!this.pickerEl) {
            return;
        }
        this.editingPin = true;
        this.modal.hide();
    }

    onHidden() {
        // The map opens once the sheet is closed (one dialog at a time)
        if (this.editingPin) {
            this.editingPin = false;
            this.reopen = true;
            document.querySelector(".o_journey_location_bar .o_journey_change")?.click();
        }
    }

    onLocationChanged(ev) {
        const { lat, lng, area, zoneFound } = ev.detail || {};
        Object.assign(this.defaults, { latitude: lat, longitude: lng, area: area || "" });
        if (this.editing && !this.reopen) {
            return; // the bar moved, not the pin of the address being changed
        }
        const elements = this.form.elements;
        elements.latitude.value = lat;
        elements.longitude.value = lng;
        elements.area.value = area || "";
        this.showPin(area, true);
        this.showError("pin", zoneFound ? "" : _t("Sorry, we don't deliver to this location yet. Please move the pin."));
        if (this.reopen && !zoneFound) {
            return; // the map stays open with its own message
        }
        this.fillFromPin();
    }

    /** Building, city, emirate and country of the pin (Google Maps). */
    async fillFromPin() {
        const elements = this.form.elements;
        const lat = parseFloat(elements.latitude.value);
        const lng = parseFloat(elements.longitude.value);
        const key = `${lat},${lng}`;
        if (!lat || !lng || this.readPin === key) {
            return;
        }
        this.readPin = key;
        let results;
        try {
            await this.waitFor(loadGoogleMaps(this.el.dataset.apiKey));
            this.geocoder ??= new google.maps.Geocoder();
            ({ results } = await this.waitFor(this.geocoder.geocode({ location: { lat, lng } })));
        } catch {
            return; // No map: the customer types the building
        }
        const components = results.flatMap((result) => result.address_components);
        const find = (type) => components.find((component) => component.types.includes(type));
        const building =
            (find("premise") || find("establishment") || find("point_of_interest"))?.long_name ||
            [find("street_number")?.long_name, find("route")?.long_name].filter(Boolean).join(" ");
        // Keep what the customer typed, replace what the previous pin filled
        if (building && (!elements.building.value.trim() || elements.building.value === this.pinFilledBuilding)) {
            elements.building.value = building;
            this.pinFilledBuilding = building;
        }
        elements.city.value = find("locality")?.long_name || "";
        elements.state.value = find("administrative_area_level_1")?.long_name || "";
        elements.country_code.value = find("country")?.short_name || "";
    }

    showError(field, message) {
        const error = this.el.querySelector(`.o_journey_field_error[data-field="${field}"]`);
        if (error) {
            error.textContent = message;
        }
        this.form.elements[field]?.closest(".o_journey_field")?.classList.toggle("o_journey_field_bad", !!message);
    }

    clearErrors() {
        for (const error of this.el.querySelectorAll(".o_journey_field_error")) {
            this.showError(error.dataset.field, "");
        }
        this.el.querySelector(".o_journey_address_error").classList.add("d-none");
    }

    async save() {
        this.clearErrors();
        const values = Object.fromEntries(new FormData(this.form).entries());
        let result;
        try {
            result = await this.waitFor(rpc("/shop/journey/address", values));
        } catch {
            result = { error: _t("Something went wrong. Please try again.") };
        }
        if (result.ok) {
            const orderPage = document.querySelector(".o_journey_order");
            if (orderPage) {
                // Like the order page's own reloads: the delivery time popup
                // opens again only if the new address changes the promise
                try {
                    sessionStorage.setItem("journey_reload_promise", orderPage.dataset.promiseMessage || "");
                } catch {
                    // Storage blocked: the popup just opens again
                }
            }
            window.location = "/shop/order";
            return new Promise(() => {}); // keep the button locked while the page changes
        }
        if (result.field) {
            this.showError(result.field, result.error);
            this.form.elements[result.field]?.focus();
        } else {
            const errorEl = this.el.querySelector(".o_journey_address_error");
            errorEl.textContent = result.error;
            errorEl.classList.remove("d-none");
        }
    }
}

registry.category("public.interactions").add("website_purchase_journey.address_sheet", JourneyAddressSheet);
