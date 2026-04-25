/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.MapAddressCheckout = publicWidget.Widget.extend({
    selector: '.oe_website_sale',

    config: {
        defaultLat: 25.2048,
        defaultLng: 55.2708,
        defaultZoom: 12,
        googleApiKey: "AIzaSyDPWub_dzNyAs7-56kyNKd3TrEvKBiVG6w",
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
        script.src = `https://maps.googleapis.com/maps/api/js?key=${self.config.googleApiKey}&libraries=places&callback=${callbackName}`;
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

            // ✅ NO form submit interception — Odoo 19 handles the save button
            // natively via its own fetch → reads {"redirectUrl":"..."} → redirects.
            // We must NOT touch that flow. Coordinates are saved to server session
            // immediately when the user picks a location on the map instead.

            console.log("✅ Map initialized!");

        } catch (error) {
            console.error("❌ Map init error:", error);
            this._showError('Error: ' + error.message);
        }
    },

    // ⭐ KEY: Save coordinates to server session THE MOMENT user picks a location.
    // This is called before the user ever touches the save button, so Odoo's
    // native save flow can proceed completely untouched.
    _saveCoordinatesToSession: function (lat, lng) {
        var self = this;

        fetch('/shop/address/map_update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                id: 1,
                params: {
                    latitude: lat,
                    longitude: lng,
                }
            })
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            if (data.result && data.result.success) {
                console.log("✅ Coordinates saved to session:", lat, lng);
            } else {
                console.error("❌ Failed to save coordinates to session:", data);
            }
        })
        .catch(function (err) {
            console.error("❌ Fetch error:", err);
        });
    },

    _bindMapEvents: function () {
        var self = this;

        google.maps.event.addListener(this.map, "click", function (event) {
            self._selectLocation(event.latLng.lat(), event.latLng.lng());
        });

        google.maps.event.addListener(this.marker, "dragend", function (event) {
            var pos = event.target.getPosition();
            self._selectLocation(pos.lat(), pos.lng());
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

        // ⭐ Save to server session immediately — don't wait for save button
        this._saveCoordinatesToSession(lat, lng);

        this.geocoder.geocode({ location: latLng }, function (results, status) {
            if (status === google.maps.GeocoderStatus.OK && results.length > 0) {
                $('#o_map_selected_address').text(results[0].formatted_address);
                self._fillOdooAddressForm(results[0]);
            } else {
                $('#o_map_selected_address').html(
                    '<span class="text-warning">Could not get address</span>'
                );
            }
        });
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
        if (!components) return;

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

        $('#o_street').val(street.trim()).trigger('change');
        $('#o_street2').val(street2).trigger('change');
        $('#o_city').val(city).trigger('change');
        $('#o_zip').val(zip || '00000').trigger('change');

        if (country) {
            var countryCode = country.short_name.toUpperCase();
            var $countrySelect = $('#o_country_id');
            var $countryOption = $countrySelect.find('option').filter(function () {
                return $(this).attr('code') === countryCode;
            });

            if ($countryOption.length > 0) {
                $countryOption.prop('selected', true);
                var stateToSet = state ? state.long_name : null;
                $countrySelect.trigger('change');

                if (stateToSet) {
                    setTimeout(function () {
                        self._selectStateWhenReady(stateToSet, 0);
                    }, 800);
                }
            }
        }
    },

    _selectStateWhenReady: function (stateName, attempts) {
        var self = this;
        var maxAttempts = 30;
        var $stateSelect = $('#o_state_id');

        if ($stateSelect.length === 0 && attempts < maxAttempts) {
            setTimeout(function () {
                self._selectStateWhenReady(stateName, attempts + 1);
            }, 200);
            return;
        }

        var optionCount = $stateSelect.find('option').length;
        if (optionCount <= 1 && attempts < maxAttempts) {
            setTimeout(function () {
                self._selectStateWhenReady(stateName, attempts + 1);
            }, 200);
            return;
        }

        var $option = $stateSelect.find('option').filter(function () {
            var optionText = $(this).text().trim();
            return optionText.toLowerCase() === stateName.toLowerCase() ||
                optionText.toLowerCase().indexOf(stateName.toLowerCase()) !== -1;
        });

        if ($option.length > 0) {
            $option.first().prop('selected', true);
            $stateSelect.val($option.first().val()).trigger('change');
        }
    },

    _clearSelection: function () {
        this.selectedLatitude = null;
        this.selectedLongitude = null;

        $('#o_map_selected_location').addClass('d-none');
        $('#o_map_search_input').val('');

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