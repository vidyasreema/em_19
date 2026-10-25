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
        this._checkAndLoadTiming();
        return this._super.apply(this, arguments);
    },

    destroy: function () {
        if (this._observer) {
            this._observer.disconnect();
        }
        this._super.apply(this, arguments);
    },

    // ── Mutation Observer ──────────────────────────────────────
    // Odoo re-renders the delivery methods when the address changes.
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

    // ── Helpers ────────────────────────────────────────────────
    _getCurrentCarrierId: function () {
        const $checked = this.$('input[name="o_delivery_radio"]:checked');
        return $checked.length ? $checked.data('dm-id') : null;
    },

    _checkAndLoadTiming: function () {
        const carrierId = this._getCurrentCarrierId();
        if (carrierId === this._lastCarrierId) {
            return;
        }
        this._lastCarrierId = carrierId;
        if (carrierId) {
            this._loadDeliveryTiming(carrierId);
        } else {
            this._hideBanner();
        }
    },

    _onDeliveryChange: function () {
        this._checkAndLoadTiming();
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
        rpc('/shop/delivery/timing', {
            carrier_id: parseInt(carrierId, 10),
            address_id: this._getSelectedAddressId(),
        })
        .then(function (result) {
            if (!result || !result.delivery_date) {
                self._hideBanner();
                return;
            }
            // No popup on this page, only the banner.
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
// Banner always, popup only if the delivery method asks for it
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

    // ── Main RPC ───────────────────────────────────────────────
    _loadConfirmationTiming: function () {
        const self = this;

        // No carrier_id: the server uses the delivery method of the cart.
        rpc('/shop/delivery/timing', {})
        .then(function (result) {
            if (!result || !result.delivery_date) return;

            // The server computes and saves the promise on the cart.
            rpc('/shop/save_delivery_timing', {})
            .catch(function (err) {
                console.warn('Could not save delivery promise:', err);
            });

            self._renderConfirmationBanner(result);

            if (result.show_popup) {
                self._showDeliveryPopup(result.delivery_date, result.message);
            }
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
