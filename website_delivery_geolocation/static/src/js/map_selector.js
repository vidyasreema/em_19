/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.MapAddressCheckout = publicWidget.Widget.extend({
    selector: '.oe_website_sale',

    config: {
        defaultLat: 25.2048,
        defaultLng: 55.2708,
        defaultZoom: 12,
        googleApiKey: "AIzaSyDPWub_dzNyAs7-56kyNKd3TrEvKBiVG6w",
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

        var callbackName = "initGoogleMapAddressCheckout";
        var script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${self.config.googleApiKey}&libraries=places&loading=async&callback=${callbackName}`;
        script.async = true;
        script.defer = true;

        window[callbackName] = function () {
            delete window[callbackName];
            self._initializeMap();
        };

        document.head.appendChild(script);
    },

    _showError: function (message) {
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
            mapEl.style.height = "500px";
            mapEl.style.width = "100%";

            this.map = new google.maps.Map(mapEl, {
                center: { lat: this.config.defaultLat, lng: this.config.defaultLng },
                zoom: this.config.defaultZoom,
                mapTypeId: google.maps.MapTypeId.ROADMAP,
                gestureHandling: 'greedy',
                zoomControl: true,
                streetViewControl: false,
                fullscreenControl: true,
            });

            this.geocoder = new google.maps.Geocoder();

            this.marker = new google.maps.Marker({
                position: { lat: this.config.defaultLat, lng: this.config.defaultLng },
                map: this.map,
                draggable: true,
                animation: google.maps.Animation.DROP,
            });

            this.infoWindow = new google.maps.InfoWindow({
                content: '<strong>📍 Drag to your location!</strong>',
            });
            this.infoWindow.open(this.map, this.marker);

            setTimeout(function () {
                google.maps.event.trigger(self.map, "resize");
            }, 300);

            this._bindMapEvents();

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

    _bindMapEvents: function () {
        var self = this;

        google.maps.event.addListener(this.map, "click", function (event) {
            self._selectLocation(event.latLng.lat(), event.latLng.lng());
        });

        google.maps.event.addListener(this.marker, "dragend", function (event) {
            self._selectLocation(event.latLng.lat(), event.latLng.lng());
        });

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
            'a[name="website_sale_main_button"], button[name="website_sale_main_button"], .oe_website_sale form button[type="submit"]'
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

    _selectLocation: function (lat, lng) {
        var self = this;

        this.selectedLatitude = lat;
        this.selectedLongitude = lng;

        console.log('📍 Location selected:', lat, lng);

        var latLng = new google.maps.LatLng(lat, lng);
        this.marker.setPosition(latLng);
        this.map.panTo(latLng);

        if (this.infoWindow) {
            this.infoWindow.close();
            this.infoWindow = null;
        }

        $('#o_map_selected_location').removeClass('d-none');
        $('#o_map_selected_address').html('<i class="fa fa-spinner fa-spin"></i>');
        $('#o_map_selected_coords')
            .text(lat.toFixed(6) + ', ' + lng.toFixed(6))
            .addClass('text-success')
            .css('font-weight', 'bold');

        this._saveCoordinatesToSession(lat, lng);

        this._setFormBusy(true);

        this.geocoder.geocode({ location: latLng }, function (results, status) {
            if (status === google.maps.GeocoderStatus.OK && results.length > 0) {
                $('#o_map_selected_address').text(results[0].formatted_address);
                self._fillOdooAddressForm(results[0]);
            } else {
                // No address at this point (sea, desert, unmapped area).
                // Clear the form so a stale address from the previous pin can
                // never be submitted alongside these new coordinates.
                self._clearAddressFields();
                $('#o_map_selected_address').html(
                    '<span class="text-danger"><strong>No address found here.</strong> ' +
                    'Please pick a location on land.</span>'
                );
                self._setFormBusy(false);
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
                self.map.setCenter(location);
                self.map.setZoom(15);
                self.marker.setPosition(location);
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
                self.map.setCenter(latLng);
                self.map.setZoom(16);
                self.marker.setPosition(latLng);
                self._selectLocation(lat, lng);
                $btn.prop('disabled', false).html(originalHTML);
            },
            function () {
                alert('Could not get your location');
                $btn.prop('disabled', false).html(originalHTML);
            }
        );
    },

    _fillOdooAddressForm: function (geocodeResult) {
        var self = this;
        var components = geocodeResult.address_components;
        if (!components) {
            this._setFormBusy(false);
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
            this._setFormBusy(false);
            return;
        }

        var countryCode = country.short_name.toUpperCase();
        var countrySelect = document.querySelector('#o_country_id');

        if (!countrySelect) {
            console.warn('⚠️ country select #o_country_id not found');
            this._setFormBusy(false);
            return;
        }

        var countryOption = Array.from(countrySelect.options).find(function (opt) {
            return (opt.getAttribute('code') || '').toUpperCase() === countryCode
                || (opt.dataset && (opt.dataset.code || '').toUpperCase() === countryCode);
        });

        if (!countryOption) {
            console.warn('⚠️ no country option matched code:', countryCode);
            this._setFormBusy(false);
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
            this._selectStateWhenReady(state.long_name, 0);
        } else {
            this._setFormBusy(false);
        }
    },

    _selectStateWhenReady: function (stateName, attempts) {
        var self = this;
        var maxAttempts = 25;   // 25 x 200ms = 5s ceiling
        var stateSelect = document.querySelector('#o_state_id');

        // Country has no states in Odoo — the select never appears. Not an error.
        if (!stateSelect) {
            if (attempts < maxAttempts) {
                setTimeout(function () {
                    self._selectStateWhenReady(stateName, attempts + 1);
                }, 200);
            } else {
                console.log('ℹ️ no state select for this country — continuing');
                self._setFormBusy(false);
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
                    self._selectStateWhenReady(stateName, attempts + 1);
                }, 200);
            } else {
                console.warn('⚠️ state list never rebuilt for:', stateName);
                self._setFormBusy(false);
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

        self._setFormBusy(false);
    },

    _clearSelection: function () {
        this.selectedLatitude = null;
        this.selectedLongitude = null;

        $('#o_map_selected_location').addClass('d-none');
        $('#o_map_search_input').val('');

        this._setFormBusy(false);

        var defaultLatLng = new google.maps.LatLng(this.config.defaultLat, this.config.defaultLng);
        this.marker.setPosition(defaultLatLng);
        this.map.setCenter(defaultLatLng);
        this.map.setZoom(this.config.defaultZoom);

        this.infoWindow = new google.maps.InfoWindow({
            content: '<strong>📍 Drag to your location!</strong>',
        });
        this.infoWindow.open(this.map, this.marker);
    },
});

export default publicWidget.registry.MapAddressCheckout;