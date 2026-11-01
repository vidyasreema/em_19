/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.MapAddressCheckout = publicWidget.Widget.extend({
    // The map block: checkout address and My Account > Addresses
    selector: '.o_map_address_selector',

    config: {
        // Abu Dhabi
        defaultLat: 24.4539,
        defaultLng: 54.3773,
        defaultZoom: 12,
        // The address under the pin is looked up again only when the map moved
        // at least this far (avoids extra Google requests for small nudges/zooms).
        minMoveMeters: 10,
        // Set to false until the /shop/address/map_update controller exists.
        enableSessionSave: false,
    },

    start: function () {
        console.log("🗺️ Map widget starting...");
        var self = this;

        this.selectedLatitude = null;
        this.selectedLongitude = null;

        return this._super.apply(this, arguments).then(function () {
            if ($('#o_delivery_map').length === 0) {
                console.log("ℹ️ Not on map page — widget passive, no interference");
                return;
            }
            console.log("✅ Map page detected");
            self._loadGoogleMaps();
        });
    },

    _loadGoogleMaps: function () {
        var self = this;

        if (window.google && window.google.maps) {
            self._initializeMap();
            return;
        }

        // API key from the Odoo configuration (data-api-key on the map element)
        var apiKey = document.getElementById('o_delivery_map').dataset.apiKey;
        if (!apiKey) {
            self._showError('The map is not available: no Google Maps API key is configured.');
            return;
        }

        var callbackName = "initGoogleMapAddressCheckout";
        var script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=places&loading=async&callback=${callbackName}`;
        script.async = true;
        script.defer = true;

        window[callbackName] = function () {
            delete window[callbackName];
            self._initializeMap();
        };

        document.head.appendChild(script);
    },

    _showError: function (message) {
        $('.o_geo_map_wrap').removeClass('o_geo_ready');
        // No map: the address is typed (no "Pick on map" button)
        $('#div_geo_pick').addClass('d-none');
        $('#o_delivery_map').html('<div class="alert alert-danger">' + message + '</div>');
    },

    // ---------------------------------------------------------------
    // Set a form field so that Odoo 19 (OWL) actually notices.
    //
    // jQuery's .trigger('change') only fires jQuery-bound handlers. Odoo 19's
    // checkout form listens with addEventListener, so a jQuery trigger is
    // invisible to it: the value appears on screen but the framework never
    // updates its own state. That is why the country changed visually while
    // the state select stayed empty and Confirm reported missing fields.
    // ---------------------------------------------------------------
    _setNative: function (selector, value) {
        const el = document.querySelector(selector);
        if (!el) {
            console.warn('⚠️ missing field:', selector);
            return null;
        }
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return el;
    },

    _initializeMap: function () {
        var self = this;

        try {
            var mapEl = document.getElementById('o_delivery_map');
            // Size comes from map_style.css (smaller on mobile).
            // Fixed pin (like Uber / noon): the pin stays in the centre of the
            // map (.o_geo_center_pin) and the customer moves the map under it.
            // 'greedy': one finger (or the mouse) moves the map on every screen.
            // The map is never taller than about half the screen
            // (map_style.css), so the page can still be scrolled around it.
            // Google's fullscreen would hide the pin: the expand button
            // (_addExpandControl) opens our own full-screen picker instead.
            this.map = new google.maps.Map(mapEl, {
                center: { lat: this.config.defaultLat, lng: this.config.defaultLng },
                zoom: this.config.defaultZoom,
                mapTypeId: google.maps.MapTypeId.ROADMAP,
                gestureHandling: 'greedy',
                zoomControl: true,
                streetViewControl: false,
                fullscreenControl: false,
                clickableIcons: false,
            });

            this.geocoder = new google.maps.Geocoder();
            // Last point whose address was looked up (for minMoveMeters).
            this.lastLookup = null;
            // Moves only fill the form after the customer used the map (or the
            // search / current location), never on page load: an address that
            // was typed or saved is not replaced by just opening the page.
            this.userMoved = false;
            this.lookupSeq = 0;

            this._addExpandControl();
            $('.o_geo_map_wrap').addClass('o_geo_ready');

            setTimeout(function () {
                google.maps.event.trigger(self.map, "resize");
            }, 300);

            this._bindMapEvents();
            this._applyInitialPoint(mapEl);

            console.log("✅ Map initialized!");

        } catch (error) {
            console.error("❌ Map init error:", error);
            this._showError('Error: ' + error.message);
        }
    },

    // ---------------------------------------------------------------
    // Save coordinates to the server session.
    //
    // NOTE: /shop/address/map_update currently returns 404 — the controller
    // does not exist. Until it is added, this is disabled via
    // config.enableSessionSave so it stops throwing a JSON parse error on the
    // 404 HTML page. Coordinates are NOT being persisted anywhere right now.
    // ---------------------------------------------------------------
    _saveCoordinatesToSession: function (lat, lng) {
        if (!this.config.enableSessionSave) {
            console.log("ℹ️ Session save disabled (map_update route missing):", lat, lng);
            return;
        }

        fetch('/shop/address/map_update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                id: 1,
                params: { latitude: lat, longitude: lng },
            }),
        })
        .then(function (res) {
            if (!res.ok) {
                throw new Error('map_update returned HTTP ' + res.status);
            }
            return res.json();
        })
        .then(function (data) {
            if (data.result && data.result.success) {
                console.log("✅ Coordinates saved to session:", lat, lng);
            } else {
                console.error("❌ map_update rejected the request:", data);
            }
        })
        .catch(function (err) {
            console.error("❌ Could not save coordinates:", err.message);
        });
    },

    // ---------------------------------------------------------------
    // Start from the initial pin given by the page (data-init-lat/lng):
    // the address being edited, or the location confirmed before shopping.
    // The form is filled automatically only when it is still empty, so an
    // address the customer typed or saved is never replaced.
    // ---------------------------------------------------------------
    _applyInitialPoint: function (mapEl) {
        var lat = parseFloat(mapEl.dataset.initLat);
        var lng = parseFloat(mapEl.dataset.initLng);
        if (!lat || !lng) {
            return;
        }
        var latLng = new google.maps.LatLng(lat, lng);
        this.map.setCenter(latLng);
        this.map.setZoom(16);

        var street = document.querySelector('#o_street');
        if (street && !street.value.trim()) {
            // New address: fill the form from the pin (also sets the hidden inputs)
            this._selectLocation(lat, lng);
        } else {
            // Existing address: only show its pin
            this.selectedLatitude = lat;
            this.selectedLongitude = lng;
            this.lastLookup = { lat: lat, lng: lng };
        }
    },

    // ---------------------------------------------------------------
    // Put the pin in the hidden inputs posted with the address form, so the
    // exact pin is saved on the address (res.partner).
    // ---------------------------------------------------------------
    _setCoordinateInputs: function (lat, lng) {
        [['#o_partner_latitude', lat], ['#o_partner_longitude', lng]].forEach(function (pair) {
            var input = document.querySelector(pair[0]);
            if (input) {
                input.value = pair[1].toFixed(7);
                input.removeAttribute('disabled');
            }
        });
    },

    _bindMapEvents: function () {
        var self = this;
        var mapEl = document.getElementById('o_delivery_map');

        // Any touch / click / wheel on the map is the customer using it
        // (drag, pinch, zoom buttons). Capture phase: Google stops some events.
        ['pointerdown', 'touchstart', 'wheel', 'keydown'].forEach(function (type) {
            mapEl.addEventListener(type, function () {
                self.userMoved = true;
            }, { capture: true, passive: true });
        });

        // Lift the pin while the map moves under it, drop it when it stops.
        google.maps.event.addListener(this.map, "dragstart", function () {
            self.userMoved = true;
            self._setPinMoving(true);
        });

        // Tap / click: bring that point under the pin (looked up on 'idle').
        google.maps.event.addListener(this.map, "click", function (event) {
            self.userMoved = true;
            self.map.panTo(event.latLng);
        });

        google.maps.event.addListener(this.map, "idle", function () {
            self._onMapIdle();
        });

        $('#o_map_collapse_btn, #o_map_confirm_btn').off('click').on('click', function () {
            self._setExpanded(false);
        });

        // Account details: "Pick on map" opens the full-screen picker
        $('#o_map_open_btn').off('click').on('click', function () {
            self._setExpanded(true);
        });
        $('.o_geo_backdrop').off('click').on('click', function () {
            self._setExpanded(false);
        });

        this._onKeydown = function (e) {
            if (e.key === 'Escape' && self.expanded) {
                self._setExpanded(false);
            }
        };
        document.addEventListener('keydown', this._onKeydown);

        $('#o_map_search_btn').off('click').on('click', function () {
            self._searchLocation();
        });

        $('#o_map_search_input').off('keypress').on('keypress', function (e) {
            if (e.which === 13) {
                e.preventDefault();
                self._searchLocation();
            }
        });

        $('#o_map_current_location_btn').off('click').on('click', function () {
            self._getCurrentLocation();
        });

        $('#o_map_clear_btn').off('click').on('click', function () {
            self._clearSelection();
        });
    },

    // ---------------------------------------------------------------
    // Block the Confirm button while the address is still being filled in.
    // Without this the customer can submit during the ~1s gap between picking
    // a location and the state select finishing its round-trip.
    // ---------------------------------------------------------------
    _setFormBusy: function (busy) {
        const buttons = document.querySelectorAll(
            'a[name="website_sale_main_button"], button[name="website_sale_main_button"], .oe_website_sale form button[type="submit"], #save_address'
        );
        buttons.forEach(function (btn) {
            if (busy) {
                btn.setAttribute('disabled', 'disabled');
                btn.classList.add('disabled');
            } else {
                btn.removeAttribute('disabled');
                btn.classList.remove('disabled');
            }
        });
    },

    // End of one address lookup. Only the latest lookup may unblock the
    // form: an older answer arriving late must not release it early.
    _finishSelection: function (seq) {
        if (seq === this.lookupSeq) {
            this.selecting = false;
            this._setFormBusy(false);
        }
    },

    _setPinMoving: function (moving) {
        $('.o_geo_map_wrap').toggleClass('o_geo_moving', moving);
        if (moving) {
            // The point under the pin is changing: no Confirm until it is known.
            this._setFormBusy(true);
        }
    },

    // The map stopped moving: the point under the pin is the map centre.
    _onMapIdle: function () {
        var wasMoving = $('.o_geo_map_wrap').hasClass('o_geo_moving');
        $('.o_geo_map_wrap').removeClass('o_geo_moving');
        if (!this.userMoved) {
            return;
        }
        var center = this.map.getCenter();
        var lat = center.lat();
        var lng = center.lng();
        if (this.lastLookup
                && this._distanceMeters(this.lastLookup.lat, this.lastLookup.lng, lat, lng) < this.config.minMoveMeters) {
            if (wasMoving && !this.selecting) {
                // Barely moved: keep the current address and release the form
                // (unless the previous address is still being filled in).
                this._setFormBusy(false);
            }
            return;
        }
        this._selectLocation(lat, lng);
    },

    // Haversine distance in metres (no extra Google library needed).
    _distanceMeters: function (lat1, lng1, lat2, lng2) {
        var toRad = Math.PI / 180;
        var dLat = (lat2 - lat1) * toRad;
        var dLng = (lng2 - lng1) * toRad;
        var a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
            + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    },

    // Expand button inside the map (top right), styled like Google's controls.
    _addExpandControl: function () {
        var self = this;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'o_map_expand_btn';
        btn.className = 'o_geo_map_control';
        btn.title = 'Full screen';
        btn.setAttribute('aria-label', 'Full screen');
        btn.innerHTML = '<i class="fa fa-expand"></i>';
        // Bound here: Google adds the control to the page asynchronously.
        btn.addEventListener('click', function () {
            self._setExpanded(!self.expanded);
        });
        this.expandBtn = btn;
        this.map.controls[google.maps.ControlPosition.RIGHT_TOP].push(btn);
    },

    // Full-screen location picker (search, map, address, Confirm), like noon.
    _setExpanded: function (expanded) {
        this.expanded = expanded;
        $('.o_map_address_selector').toggleClass('o_geo_expanded', expanded);
        $('.o_geo_backdrop').toggleClass('o_geo_backdrop_show', expanded);
        if (this.expandBtn) {
            this.expandBtn.innerHTML = expanded ? '<i class="fa fa-compress"></i>' : '<i class="fa fa-expand"></i>';
            this.expandBtn.title = expanded ? 'Exit full screen' : 'Full screen';
            this.expandBtn.setAttribute('aria-label', this.expandBtn.title);
        }
        $('body').toggleClass('o_geo_noscroll', expanded);
        // Keep the same point under the pin while the map changes size.
        var self = this;
        var center = this.map.getCenter();
        google.maps.event.trigger(this.map, 'resize');
        this.map.setCenter(center);
        // Once the new size is laid out (the "Pick on map" popup starts hidden)
        setTimeout(function () {
            google.maps.event.trigger(self.map, 'resize');
            self.map.setCenter(center);
        }, 100);
        if (!expanded) {
            var picked = $('#o_map_selected_address').text().trim();
            if (picked) {
                $('#o_map_open_hint').empty().append(
                    $('<i class="fa fa-check-circle text-success me-1" role="presentation"/>'),
                    document.createTextNode(picked));
            }
            var block = document.querySelector('.o_map_address_selector:not(.o_geo_picker_only)')
                || document.getElementById('div_geo_pick');
            if (block) {
                block.scrollIntoView({ block: 'nearest' });
            }
        }
    },

    destroy: function () {
        if (this._onKeydown) {
            document.removeEventListener('keydown', this._onKeydown);
        }
        $('body').removeClass('o_geo_noscroll');
        this._super.apply(this, arguments);
    },

    _selectLocation: function (lat, lng) {
        var self = this;

        this.selectedLatitude = lat;
        this.selectedLongitude = lng;
        this.lastLookup = { lat: lat, lng: lng };
        var seq = ++this.lookupSeq;
        this.selecting = true;

        console.log('📍 Location selected:', lat, lng);

        var latLng = new google.maps.LatLng(lat, lng);

        $('#o_map_selected_location').removeClass('d-none');
        $('#o_map_selected_address').html('<i class="fa fa-spinner fa-spin"></i>');
        $('#o_map_selected_coords').text(lat.toFixed(6) + ', ' + lng.toFixed(6));

        this._setCoordinateInputs(lat, lng);
        this._saveCoordinatesToSession(lat, lng);

        this._setFormBusy(true);

        this.geocoder.geocode({ location: latLng }, function (results, status) {
            if (seq !== self.lookupSeq) {
                return;  // the pin moved again meanwhile: a newer lookup is running
            }
            if (status === google.maps.GeocoderStatus.OK && results.length > 0) {
                $('#o_map_selected_address').text(results[0].formatted_address);
                self._fillOdooAddressForm(results[0], seq);
            } else {
                // No address at this point (sea, desert, unmapped area).
                // Clear the form so a stale address from the previous pin can
                // never be submitted alongside these new coordinates.
                self._clearAddressFields();
                $('#o_map_selected_address').html(
                    '<span class="text-danger"><strong>No address found here.</strong> ' +
                    'Please pick a location on land.</span>'
                );
                self._finishSelection(seq);
            }
        });
    },

    // ---------------------------------------------------------------
    // Blank the address fields. Used when geocoding finds nothing, so the
    // customer cannot confirm new coordinates with an old address attached.
    // Country and state are left alone: clearing the country would force
    // Odoo into another state-list rebuild for no benefit.
    // ---------------------------------------------------------------
    _clearAddressFields: function () {
        this._setNative('#o_street', '');
        this._setNative('#o_street2', '');
        this._setNative('#o_city', '');
        this._setNative('#o_zip', '');
        console.warn('⚠️ no address at these coordinates — address fields cleared');
    },

    _searchLocation: function () {
        var self = this;
        var query = $('#o_map_search_input').val().trim();

        if (!query) {
            alert('Please enter a location');
            return;
        }

        var $btn = $('#o_map_search_btn');
        var originalHTML = $btn.html();
        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        this.geocoder.geocode({ address: query }, function (results, status) {
            $btn.prop('disabled', false).html(originalHTML);

            if (status === google.maps.GeocoderStatus.OK && results.length > 0) {
                var location = results[0].geometry.location;
                self.userMoved = true;
                self.map.setCenter(location);
                self.map.setZoom(15);
                self._selectLocation(location.lat(), location.lng());
            } else {
                alert('Location not found');
            }
        });
    },

    _getCurrentLocation: function () {
        var self = this;

        if (!navigator.geolocation) {
            alert('Geolocation not supported');
            return;
        }

        var $btn = $('#o_map_current_location_btn');
        var originalHTML = $btn.html();
        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        navigator.geolocation.getCurrentPosition(
            function (position) {
                var lat = position.coords.latitude;
                var lng = position.coords.longitude;
                var latLng = new google.maps.LatLng(lat, lng);
                self.userMoved = true;
                self.map.setCenter(latLng);
                self.map.setZoom(16);
                self._selectLocation(lat, lng);
                $btn.prop('disabled', false).html(originalHTML);
            },
            function () {
                alert('Could not get your location');
                $btn.prop('disabled', false).html(originalHTML);
            }
        );
    },

    _fillOdooAddressForm: function (geocodeResult, seq) {
        var self = this;
        var components = geocodeResult.address_components;
        if (!components) {
            this._finishSelection(seq);
            return;
        }

        function getComponent(type) {
            for (var i = 0; i < components.length; i++) {
                if (components[i].types.indexOf(type) !== -1) {
                    return components[i];
                }
            }
            return null;
        }

        var streetNumber = getComponent("street_number");
        var route = getComponent("route");
        var locality = getComponent("locality");
        var sublocalityL2 = getComponent("sublocality_level_2");
        var sublocalityL1 = getComponent("sublocality_level_1");
        var postalCode = getComponent("postal_code");
        var country = getComponent("country");
        var state = getComponent("administrative_area_level_1");

        var street = '';
        if (streetNumber) street += streetNumber.long_name + ' ';
        if (route) street += route.long_name;
        if (!street.trim()) street = geocodeResult.formatted_address.split(',')[0];

        var street2 = '';
        if (sublocalityL2) street2 = sublocalityL2.long_name;
        else if (sublocalityL1) street2 = sublocalityL1.long_name;

        var city = locality ? locality.long_name : '';
        var zip = postalCode ? postalCode.long_name : '';

        // Native events so OWL registers the values.
        this._setNative('#o_street', street.trim());
        this._setNative('#o_street2', street2);
        this._setNative('#o_city', city);
        this._setNative('#o_zip', zip || '00000');

        if (!country) {
            this._finishSelection(seq);
            return;
        }

        var countryCode = country.short_name.toUpperCase();
        var countrySelect = document.querySelector('#o_country_id');

        if (!countrySelect) {
            console.warn('⚠️ country select #o_country_id not found');
            this._finishSelection(seq);
            return;
        }

        var countryOption = Array.from(countrySelect.options).find(function (opt) {
            return (opt.getAttribute('code') || '').toUpperCase() === countryCode
                || (opt.dataset && (opt.dataset.code || '').toUpperCase() === countryCode);
        });

        if (!countryOption) {
            console.warn('⚠️ no country option matched code:', countryCode);
            this._finishSelection(seq);
            return;
        }

        // Only wait for a rebuild if the country is ACTUALLY changing.
        // On a second pick within the same country, setting the same value is a
        // no-op: Odoo never re-fetches, the list never changes, and waiting for
        // it to differ just times out. In that case the list is already correct,
        // so match against it immediately.
        var beforeSelect = document.querySelector('#o_state_id');
        var countryChanged = (countrySelect.value !== countryOption.value);

        if (countryChanged) {
            this._stateSignature = beforeSelect
                ? Array.from(beforeSelect.options).map(function (o) { return o.value; }).join(',')
                : null;
            countrySelect.value = countryOption.value;
            countrySelect.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            this._stateSignature = null;
        }

        if (state) {
            this._selectStateWhenReady(state.long_name, 0, seq);
        } else {
            this._finishSelection(seq);
        }
    },

    _selectStateWhenReady: function (stateName, attempts, seq) {
        var self = this;
        var maxAttempts = 25;   // 25 x 200ms = 5s ceiling
        var stateSelect = document.querySelector('#o_state_id');

        if (seq !== self.lookupSeq) {
            return;  // a newer pin position took over
        }

        // Country has no states in Odoo — the select never appears. Not an error.
        if (!stateSelect) {
            if (attempts < maxAttempts) {
                setTimeout(function () {
                    self._selectStateWhenReady(stateName, attempts + 1, seq);
                }, 200);
            } else {
                console.log('ℹ️ no state select for this country — continuing');
                self._finishSelection(seq);
            }
            return;
        }

        // The list must have REBUILT, not merely be non-empty. On an edit the
        // old country's states are still sitting there and look "ready".
        var signature = Array.from(stateSelect.options).map(function (o) {
            return o.value;
        }).join(',');

        var stillOldList = (self._stateSignature !== null && signature === self._stateSignature);
        var notPopulated = stateSelect.options.length <= 1;

        if (stillOldList || notPopulated) {
            if (attempts < maxAttempts) {
                setTimeout(function () {
                    self._selectStateWhenReady(stateName, attempts + 1, seq);
                }, 200);
            } else {
                console.warn('⚠️ state list never rebuilt for:', stateName);
                self._finishSelection(seq);
            }
            return;
        }

        var wanted = stateName.toLowerCase();
        var match = Array.from(stateSelect.options).find(function (opt) {
            return opt.value && opt.text.trim().toLowerCase() === wanted;
        }) || Array.from(stateSelect.options).find(function (opt) {
            var t = opt.text.trim().toLowerCase();
            return opt.value && (t.indexOf(wanted) !== -1 || wanted.indexOf(t) !== -1);
        });

        if (match) {
            self._setNative('#o_state_id', match.value);
            console.log('✅ state set:', match.text);
        } else {
            // NO FALLBACK. Guessing an emirate silently ships meat to the wrong
            // place. Leave it blank and let the customer pick.
            console.warn('⚠️ no state match for "' + stateName + '" — left blank for the customer');
        }

        self._finishSelection(seq);
    },

    _clearSelection: function () {
        this.selectedLatitude = null;
        this.selectedLongitude = null;

        $('#o_map_selected_location').addClass('d-none');
        $('#o_map_search_input').val('');

        // Cancel a running lookup; moving back to the default point is not
        // a choice of the customer, so it is not looked up.
        this.lookupSeq++;
        this.selecting = false;
        this.userMoved = false;
        this.lastLookup = null;
        this._setFormBusy(false);

        var defaultLatLng = new google.maps.LatLng(this.config.defaultLat, this.config.defaultLng);
        this.map.setCenter(defaultLatLng);
        this.map.setZoom(this.config.defaultZoom);
    },
});

export default publicWidget.registry.MapAddressCheckout;