import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

const DEFAULT_CENTER = { lat: 24.4539, lng: 54.3773 }; // Abu Dhabi
// Ask the browser permission once per device, not on every page.
const ASKED_KEY = "journey_location_asked";

let mapsPromise = null;

export function loadGoogleMaps(apiKey) {
    if (window.google?.maps?.Map) {
        return Promise.resolve();
    }
    if (!apiKey) {
        return Promise.reject(new Error("no key"));
    }
    if (!mapsPromise) {
        mapsPromise = new Promise((resolve, reject) => {
            window.journeyMapsReady = resolve;
            const script = document.createElement("script");
            script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&loading=async&callback=journeyMapsReady`;
            script.async = true;
            script.onerror = () => {
                mapsPromise = null;
                reject(new Error("load"));
            };
            document.head.appendChild(script);
        });
    }
    return mapsPromise;
}

function storage(action, value) {
    try {
        return action === "get" ? window.localStorage.getItem(ASKED_KEY) : window.localStorage.setItem(ASKED_KEY, value);
    } catch {
        return null; // private window, blocked storage
    }
}

/**
 * "Deliver to" bar: the location is asked through the browser permission on
 * entry; if refused, the customer keeps browsing and sets it from the bar.
 */
export class JourneyLocationBar extends Interaction {
    static selector = ".o_journey_location_bar";
    dynamicContent = {
        _root: { "t-on-click": this.onClick },
    };

    setup() {
        this.modalEl = this.el.querySelector(".o_journey_location_modal");
        this.modal = window.Modal.getOrCreateInstance(this.modalEl);
        this.registerCleanup(() => this.modal.dispose());
        this.point = null;
    }

    start() {
        if (this.el.dataset.hasLocation !== "1") {
            this.locateOnEntry();
        }
    }

    async locateOnEntry() {
        if (!navigator.geolocation) {
            return;
        }
        let state = "prompt";
        try {
            state = (await navigator.permissions.query({ name: "geolocation" })).state;
        } catch {
            // Permissions API not available: ask once
        }
        if (state === "denied" || (state === "prompt" && storage("get"))) {
            return;
        }
        storage("set", "1");
        navigator.geolocation.getCurrentPosition(
            (position) => this.save(position.coords.latitude, position.coords.longitude),
            () => {}, // refused: the customer keeps browsing
            { timeout: 15000, maximumAge: 600000 },
        );
    }

    onClick(ev) {
        if (ev.target.closest(".o_journey_change")) {
            this.openPicker();
        } else if (ev.target.closest(".o_journey_confirm")) {
            this.confirm();
        } else if (ev.target.closest(".o_journey_locate")) {
            this.useCurrentLocation();
        } else if (ev.target.closest(".o_journey_search_btn")) {
            this.search();
        }
    }

    async areaName(lat, lng) {
        try {
            await loadGoogleMaps(this.el.dataset.apiKey);
            this.geocoder ??= new google.maps.Geocoder();
            const { results } = await this.geocoder.geocode({ location: { lat, lng } });
            const types = ["sublocality", "neighborhood", "locality", "administrative_area_level_2"];
            for (const type of types) {
                const component = results
                    .flatMap((r) => r.address_components)
                    .find((c) => c.types.includes(type));
                if (component) {
                    return component.long_name;
                }
            }
        } catch {
            // No Google Maps: the zone name is shown instead
        }
        return "";
    }

    async save(lat, lng) {
        const area = await this.waitFor(this.areaName(lat, lng));
        const result = await this.waitFor(rpc("/shop/journey/set_location", { latitude: lat, longitude: lng, area }));
        this.el.dataset.hasLocation = "1";
        this.el.querySelector(".o_journey_location_content").innerHTML = result.bar_html;
        // The "Address details" sheet follows the pin
        document.dispatchEvent(new CustomEvent("journey_location_changed", {
            detail: { lat, lng, area: result.area, zoneFound: result.zone_found },
        }));
        return result;
    }

    async openPicker() {
        this.modal.show();
        if (this.map) {
            return;
        }
        try {
            await this.waitFor(loadGoogleMaps(this.el.dataset.apiKey));
        } catch {
            this.showMessage(_t("The map is not available. Use “Use my current location”."), "warning");
            return;
        }
        this.map = new google.maps.Map(this.modalEl.querySelector(".o_journey_map"), {
            center: DEFAULT_CENTER,
            zoom: 12,
            gestureHandling: "greedy",
            streetViewControl: false,
            fullscreenControl: false,
            clickableIcons: false,
        });
        this.geocoder ??= new google.maps.Geocoder();
        // Fixed pin in the centre: the customer moves the map under it.
        this.map.addListener("idle", () => {
            const center = this.map.getCenter();
            this.point = { lat: center.lat(), lng: center.lng() };
            this.modalEl.querySelector(".o_journey_confirm").disabled = false;
        });
    }

    moveTo(lat, lng) {
        this.point = { lat, lng };
        this.modalEl.querySelector(".o_journey_confirm").disabled = false;
        if (this.map) {
            this.map.setCenter(this.point);
            this.map.setZoom(16);
        }
    }

    useCurrentLocation() {
        if (!navigator.geolocation) {
            this.showMessage(_t("Your browser cannot share your location."), "warning");
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (position) => this.moveTo(position.coords.latitude, position.coords.longitude),
            () => this.showMessage(_t("We could not get your location. Please move the map to it."), "warning"),
        );
    }

    async search() {
        const query = this.modalEl.querySelector(".o_journey_search").value.trim();
        if (!query || !this.geocoder) {
            return;
        }
        try {
            const { results } = await this.waitFor(this.geocoder.geocode({ address: query, region: "ae" }));
            const location = results[0].geometry.location;
            this.moveTo(location.lat(), location.lng());
        } catch {
            this.showMessage(_t("Location not found, try another search."), "warning");
        }
    }

    async confirm() {
        if (!this.point) {
            return;
        }
        const result = await this.save(this.point.lat, this.point.lng);
        if (result.zone_found) {
            this.modal.hide();
        } else {
            this.showMessage(_t("Sorry, we don't deliver to this location yet. Please choose another one."), "warning");
        }
    }

    showMessage(text, type) {
        const message = this.modalEl.querySelector(".o_journey_location_message");
        message.classList.remove("d-none", "alert-success", "alert-warning");
        message.classList.add(`alert-${type}`);
        message.textContent = text;
    }
}

registry.category("public.interactions").add("website_purchase_journey.location_bar", JourneyLocationBar);
