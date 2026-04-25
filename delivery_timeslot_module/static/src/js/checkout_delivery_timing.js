/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

// ─────────────────────────────────────────────────────────────
// Widget 1: Checkout / Delivery Address Page
// Selector: #o_delivery_form
// Banner only — no popup ever on this page
// ─────────────────────────────────────────────────────────────
publicWidget.registry.DeliveryTimingWidget = publicWidget.Widget.extend({
    selector: '#o_delivery_form',

    events: {
        'change input[name="o_delivery_radio"]': '_onDeliveryChange',
    },

    start: function () {
        this._setupMutationObserver();
        this._startPolling();
        this._checkAndLoadTiming();
        return this._super.apply(this, arguments);
    },

    destroy: function () {
        if (this._observer) {
            this._observer.disconnect();
        }
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
        }
        this._super.apply(this, arguments);
    },

    // ── Mutation Observer ──────────────────────────────────────
    _setupMutationObserver: function () {
        const self = this;
        this._observer = new MutationObserver(function (mutations) {
            const hasChanges = mutations.some(m => m.addedNodes.length > 0);
            if (hasChanges) {
                setTimeout(() => self._checkAndLoadTiming(), 300);
            }
        });
        this._observer.observe(this.el, { childList: true, subtree: true });
    },

    // ── Polling (backup) ───────────────────────────────────────
    _startPolling: function () {
        const self = this;
        this._lastCarrier = null;
        this._pollInterval = setInterval(function () {
            const current = self._getCurrentCarrierId();
            if (current !== self._lastCarrier) {
                self._lastCarrier = current;
                if (current) {
                    self._loadDeliveryTiming(current);
                } else {
                    self._hideBanner();
                }
            }
        }, 500);
    },

    // ── Helpers ────────────────────────────────────────────────
    _getCurrentCarrierId: function () {
        const $checked = this.$('input[name="o_delivery_radio"]:checked');
        return $checked.length ? $checked.data('dm-id') : null;
    },

    _checkAndLoadTiming: function () {
        const carrierId = this._getCurrentCarrierId();
        if (carrierId) {
            this._loadDeliveryTiming(carrierId);
        } else {
            this._hideBanner();
        }
    },

    _onDeliveryChange: function (ev) {
        const carrierId = $(ev.currentTarget).data('dm-id');
        this._loadDeliveryTiming(carrierId);
    },

    _getSelectedAddressId: function () {
        const $select = this.$('select[name="partner_id"]');
        if ($select.length && $select.val()) {
            return parseInt($select.val(), 10);
        }
        const $radio = this.$('input[name="shipping_id"]:checked');
        if ($radio.length && $radio.val()) {
            return parseInt($radio.val(), 10);
        }
        return null;
    },

    // ── Main RPC ───────────────────────────────────────────────
    _loadDeliveryTiming: function (carrierId) {
        const self = this;
        if (!carrierId) {
            self._hideBanner();
            return;
        }

        const addressId = this._getSelectedAddressId();

        rpc('/shop/delivery/timing', {
            carrier_id: parseInt(carrierId, 10),
            address_id: addressId,
        })
        .then(function (result) {
            if (!result || !result.delivery_date) {
                self._hideBanner();
                return;
            }

            try {
                sessionStorage.setItem('delivery_carrier_id', carrierId.toString());
            } catch (e) {
                console.warn('Could not store carrier id:', e);
            }

            // ⭐ Always show banner on checkout if delivery_date exists.
            // show_popup is intentionally ignored here — no popup on checkout.
            self._renderBanner(result);
            self._showBanner();
        })
        .catch(function (err) {
            console.error('Timing error:', err);
            self._hideBanner();
        });
    },

    // ── Render ─────────────────────────────────────────────────
    _renderBanner: function (result) {
        const $msg = $('#delivery_timing_text');
        if (result.message) {
            $msg.text(result.message).show();
        } else {
            $msg.hide();
        }

        const $dateDisplay = $('#delivery_date_display');
        if (result.delivery_date) {
            $('#delivery_date_text').text(result.delivery_date);
            $dateDisplay.show();
        } else {
            $dateDisplay.hide();
        }
    },

    _showBanner: function () {
        $('#delivery_timing_container').slideDown(300);
    },

    _hideBanner: function () {
        $('#delivery_timing_container').slideUp(300);
    },
});


// ─────────────────────────────────────────────────────────────
// Widget 2: Payment / Confirmation Page
// Selector: .oe_website_sale
// Banner + Popup — popup always shown on payment if date exists
// ─────────────────────────────────────────────────────────────
publicWidget.registry.DeliveryTimingConfirmation = publicWidget.Widget.extend({
    selector: '.oe_website_sale',

    start: function () {
        const path = window.location.pathname;
        if (path.includes('/shop/payment') || path.includes('/shop/confirm_order')) {
            this._loadConfirmationTiming();
        }
        return this._super.apply(this, arguments);
    },

    // ── Get carrier ID ─────────────────────────────────────────
    _getCarrierId: function () {
        try {
            const id = sessionStorage.getItem('delivery_carrier_id');
            if (id) return id;
        } catch (e) {}

        const $hidden = $('input[type="hidden"][name="delivery_type"]');
        if ($hidden.length && $hidden.val()) return $hidden.val();

        const $radio = $('input[name="delivery_type"]:checked');
        if ($radio.length && $radio.val()) return $radio.val();

        const $carrier = $('.o_delivery_carrier_select input[type="radio"]:checked');
        if ($carrier.length) return $carrier.val();

        return null;
    },

    // ── Main RPC ───────────────────────────────────────────────
    _loadConfirmationTiming: function () {
        const self = this;
        const carrierId = this._getCarrierId();

        if (!carrierId) {
            console.warn('No carrier ID found on confirmation page');
            return;
        }

        rpc('/shop/delivery/timing', {
            carrier_id: parseInt(carrierId, 10),
        })
        .then(function (result) {
            if (!result || !result.delivery_date) return;

            // ⭐ Always save commitment date
            rpc('/shop/save_delivery_timing', {
                delivery_data: { delivery_date: result.delivery_date },
            })
            .then(function (saveResult) {
                console.log('Delivery date saved:', saveResult);
            })
            .catch(function (err) {
                console.warn('Could not save delivery date:', err);
            });

            // ⭐ Always render banner on payment page if delivery_date exists
            self._renderConfirmationBanner(result);

            // ⭐ Always show popup on payment page — show_popup flag is ignored here
            self._showDeliveryPopup(result.delivery_date, result.message);
        })
        .catch(function (err) {
            console.error('Confirmation timing error:', err);
        });
    },

    // ── Render confirmation banner ─────────────────────────────
    _renderConfirmationBanner: function (result) {
        const $msg = $('#payment_delivery_timing_text');
        if (result.message) {
            $msg.text(result.message).show();
        } else {
            $msg.hide();
        }

        const $dateDisplay = $('#payment_delivery_date_display');
        if (result.delivery_date) {
            $('#payment_delivery_date_text').text(result.delivery_date);
            $dateDisplay.show();
        } else {
            $dateDisplay.hide();
        }

        $('#delivery_timing_confirmation_banner').slideDown(300);
    },

    // ── Popup modal ────────────────────────────────────────────
    _showDeliveryPopup: function (deliveryDate, message) {
        $('#delivery_timing_confirm_modal').remove();

        const escapedDate = this._escapeHtml(deliveryDate);
        const escapedMsg  = message ? this._escapeHtml(message) : '';

        const modal = `
            <div class="modal fade" id="delivery_timing_confirm_modal" tabindex="-1" role="dialog">
                <div class="modal-dialog modal-dialog-centered" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                <i class="fa fa-truck text-primary me-2"></i>
                                Delivery Information
                            </h5>
                            <button type="button" class="btn-close"
                                    data-bs-dismiss="modal" data-dismiss="modal"
                                    aria-label="Close"></button>
                        </div>
                        <div class="modal-body text-center">
                            ${escapedMsg ? `<p class="mb-2 text-muted">${escapedMsg}</p>` : ''}
                            <p class="mb-1">Your estimated delivery date is:</p>
                            <h4 class="text-success fw-bold">${escapedDate}</h4>
                        </div>
                        <div class="modal-footer justify-content-center">
                            <button type="button" class="btn btn-primary"
                                    data-bs-dismiss="modal" data-dismiss="modal">
                                <i class="fa fa-check me-1"></i> Got it
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        $('body').append(modal);
        const $modal = $('#delivery_timing_confirm_modal');

        try {
            if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                new bootstrap.Modal($modal[0]).show();
            } else if ($.fn.modal) {
                $modal.modal('show');
            } else {
                $modal.addClass('show').css('display', 'block');
                $('body').addClass('modal-open')
                         .append('<div class="modal-backdrop fade show"></div>');
            }
        } catch (e) {
            console.error('Error showing modal:', e);
        }

        $modal.on('hidden.bs.modal hidden', function () {
            setTimeout(() => $modal.remove(), 100);
            $('.modal-backdrop').remove();
            $('body').removeClass('modal-open');
        });
    },

    _escapeHtml: function (text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
});

export default publicWidget.registry.DeliveryTimingWidget;