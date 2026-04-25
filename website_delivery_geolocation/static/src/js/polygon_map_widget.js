/** @odoo-module **/
import { Component, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class PolygonMapWidget extends Component {
    static template = "PolygonMapWidget";
    static props = {
        ...standardFieldProps,
    };
    static supportedTypes = ["text"];

    setup() {
        this.mapRef = useRef("map");
        this.searchRef = useRef("search");
        this.searchBtnRef = useRef("searchBtn");
        this.exclusionSearchRef = useRef("exclusionSearch");
        this.exclusionSearchBtnRef = useRef("exclusionSearchBtn");
        this.map = null;
        this.drawingManager = null;
        this.currentPolygon = null;
        this.exclusionZones = [];
        this.searchMarkers = [];
        this.geocoder = null;
        this.infoWindow = null;
        this.resizeObserver = null;
        this.isDrawingExclusion = false;

        // ⚠️ Replace with your actual Google API Key
        this.googleApiKey = "AIzaSyDPWub_dzNyAs7-56kyNKd3TrEvKBiVG6w";

        onMounted(() => {
            this.loadGoogleMaps();
        });

        onWillUnmount(() => {
            if (this.currentPolygon) {
                this.currentPolygon.setMap(null);
            }
            this.exclusionZones.forEach(zone => zone.setMap(null));
            this.searchMarkers.forEach(marker => marker.setMap(null));
            if (this.infoWindow) {
                this.infoWindow.close();
            }
            if (this.drawingManager) {
                this.drawingManager.setMap(null);
            }
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
            }
        });
    }

    get fieldName() {
        return this.props.name;
    }

    get fieldValue() {
        return this.props.record && this.props.record.data
            ? this.props.record.data[this.fieldName]
            : null;
    }

    async loadGoogleMaps() {
        try {
            if (window.google && window.google.maps) {
                this.initMap();
                return;
            }

            await new Promise((resolve, reject) => {
                const script = document.createElement("script");
                script.src = `https://maps.googleapis.com/maps/api/js?key=${this.googleApiKey}&libraries=drawing,geometry&callback=initGoogleMap`;
                script.async = true;
                script.defer = true;
                script.onerror = () => reject(new Error("Failed to load Google Maps"));

                window.initGoogleMap = () => {
                    delete window.initGoogleMap;
                    resolve();
                };

                document.head.appendChild(script);
            });

            this.initMap();
        } catch (error) {
            console.error("❌ Error loading Google Maps:", error);
        }
    }

    initMap() {
        try {
            console.log("✅ Initializing Google Map...");

            const mapEl = this.mapRef.el;
            mapEl.style.height = "600px";
            mapEl.style.width = "100%";

            this.map = new google.maps.Map(mapEl, {
                center: { lat: 25.2048, lng: 55.2708 },
                zoom: 11,
                mapTypeId: google.maps.MapTypeId.ROADMAP,
                restriction: {
                    latLngBounds: {
                        north: 85,
                        south: -85,
                        west: -180,
                        east: 180
                    },
                    strictBounds: false
                },
                // Disable world wrapping
                gestureHandling: 'greedy',
                mapTypeControl: true,
                streetViewControl: false,
                fullscreenControl: true,
            });

            setTimeout(() => {
                if (this.map) {
                    google.maps.event.trigger(this.map, "resize");
                    this.map.setCenter({ lat: 25.2048, lng: 55.2708 });
                }
            }, 300);

            this.resizeObserver = new ResizeObserver(() => {
                if (this.map) {
                    google.maps.event.trigger(this.map, "resize");
                }
            });
            this.resizeObserver.observe(mapEl);

            this.geocoder = new google.maps.Geocoder();
            this.infoWindow = new google.maps.InfoWindow();

            this.setupDrawingManager();
            this.setupDrawingControls();
            this.setupSearch();
            this.loadExistingPolygon();

            console.log("✅ Google Map initialized!");
        } catch (error) {
            console.error("❌ Error in initMap:", error);
        }
    }

    setupDrawingManager() {
        console.log("🎨 Setting up Drawing Manager...");

        // Initialize drawing manager
        this.drawingManager = new google.maps.drawing.DrawingManager({
            drawingMode: null,
            drawingControl: false, // We'll use custom buttons instead
            polygonOptions: {
                fillColor: "#4CAF50",
                fillOpacity: 0.3,
                strokeColor: "#2E7D32",
                strokeWeight: 2,
                editable: true,
                draggable: false,
            },
        });

        console.log("✅ Drawing Manager created");

        this.drawingManager.setMap(this.map);

        console.log("✅ Drawing Manager set to map");

        // Listen for polygon completion
        google.maps.event.addListener(
            this.drawingManager,
            "polygoncomplete",
            (polygon) => {
                console.log("🎨 Polygon completed, isDrawingExclusion:", this.isDrawingExclusion);
                this.handlePolygonComplete(polygon);
            }
        );

        console.log("✅ Drawing Manager listeners attached");
    }

    setupDrawingControls() {
        // Create custom control buttons
        const controlDiv = document.createElement('div');
        controlDiv.style.cssText = 'margin: 10px; display: flex; gap: 10px; flex-direction: column;';

        // Target Zone Button
        const targetBtn = this.createControlButton(
            '🎯 Draw Target Zone',
            '#4CAF50',
            () => {
                this.startDrawingMode('target');
            }
        );

        // Exclusion Zone Button
        const exclusionBtn = this.createControlButton(
            '🚫 Draw Exclusion Zone',
            '#f44336',
            () => {
                if (!this.currentPolygon) {
                    alert("⚠️ Please draw a TARGET zone first!");
                    return;
                }
                this.startDrawingMode('exclusion');
            }
        );

        // Clear All Button
        const clearBtn = this.createControlButton(
            '🗑️ Clear All',
            '#757575',
            () => {
                if (confirm('Delete all zones?')) {
                    if (this.currentPolygon) {
                        this.currentPolygon.setMap(null);
                        this.currentPolygon = null;
                    }
                    this.exclusionZones.forEach(zone => zone.setMap(null));
                    this.exclusionZones = [];
                    this.saveAllZones();
                }
            }
        );

        // Add instruction text
        const instructionDiv = document.createElement('div');
        instructionDiv.style.cssText = `
            background: white;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 12px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            max-width: 200px;
        `;
        instructionDiv.innerHTML = '<strong>📍 Click button then draw on map</strong><br/>Double-click to finish';

        controlDiv.appendChild(instructionDiv);
        controlDiv.appendChild(targetBtn);
        controlDiv.appendChild(exclusionBtn);
        controlDiv.appendChild(clearBtn);

        this.map.controls[google.maps.ControlPosition.TOP_LEFT].push(controlDiv);
    }

    startDrawingMode(type) {
        this.isDrawingExclusion = (type === 'exclusion');

        console.log(`🎨 Starting ${type} drawing mode`);
        console.log(`📍 Drawing Manager exists:`, !!this.drawingManager);
        console.log(`📍 Map exists:`, !!this.map);

        if (!this.drawingManager) {
            console.error('❌ Drawing manager not initialized!');
            alert('Drawing manager not ready. Please refresh the page.');
            return;
        }

        // Set the appropriate polygon options
        const polygonOptions = this.isDrawingExclusion ? {
            fillColor: "#f44336",
            fillOpacity: 0.5,
            strokeColor: "#c62828",
            strokeWeight: 2,
            editable: true,
            draggable: false,
            clickable: true,
        } : {
            fillColor: "#4CAF50",
            fillOpacity: 0.3,
            strokeColor: "#2E7D32",
            strokeWeight: 2,
            editable: true,
            draggable: false,
            clickable: true,
        };

        console.log(`📍 Setting polygon options:`, polygonOptions);

        // Update drawing manager options
        this.drawingManager.setOptions({
            polygonOptions: polygonOptions
        });

        // Activate polygon drawing mode
        this.drawingManager.setDrawingMode(google.maps.drawing.OverlayType.POLYGON);

        const currentMode = this.drawingManager.getDrawingMode();
        console.log(`✅ Drawing mode set to:`, currentMode);
        console.log(`✅ isDrawingExclusion = ${this.isDrawingExclusion}`);

        if (currentMode !== google.maps.drawing.OverlayType.POLYGON) {
            console.error('❌ Drawing mode did not activate properly!');
            alert('Drawing mode failed to activate. Please try again or refresh the page.');
        } else {
            console.log('✅ Ready to draw! Click on the map to start drawing.');
        }
    }

    createControlButton(text, color, onClick) {
        const button = document.createElement('button');
        button.textContent = text;
        button.style.cssText = `
            background: ${color};
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            font-size: 14px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        `;
        button.addEventListener('click', onClick);
        button.addEventListener('mouseenter', () => {
            button.style.opacity = '0.9';
        });
        button.addEventListener('mouseleave', () => {
            button.style.opacity = '1';
        });
        return button;
    }

    handlePolygonComplete(polygon) {
        // Stop drawing mode
        this.drawingManager.setDrawingMode(null);

        // Normalize coordinates to prevent world wrapping
        const path = polygon.getPath();
        const normalizedPath = [];
        for (let i = 0; i < path.getLength(); i++) {
            const point = path.getAt(i);
            let lng = point.lng();

            // Normalize longitude to -180 to 180 range
            while (lng > 180) lng -= 360;
            while (lng < -180) lng += 360;

            normalizedPath.push({
                lat: point.lat(),
                lng: lng
            });
        }

        // Remove the old polygon and create a new one with normalized coordinates
        polygon.setMap(null);

        const normalizedPolygon = new google.maps.Polygon({
            paths: normalizedPath,
            fillColor: this.isDrawingExclusion ? "#f44336" : "#4CAF50",
            fillOpacity: this.isDrawingExclusion ? 0.5 : 0.3,
            strokeColor: this.isDrawingExclusion ? "#c62828" : "#2E7D32",
            strokeWeight: 2,
            editable: true,
            draggable: false,
            clickable: true,
        });

        if (this.isDrawingExclusion) {
            // Check if we have a target zone
            if (!this.currentPolygon) {
                alert("⚠️ Please draw a TARGET zone first!");
                normalizedPolygon.setMap(null);
                return;
            }

            // Add as exclusion zone
            normalizedPolygon.zoneType = 'exclusion';
            normalizedPolygon.zoneName = `Exclusion Zone ${this.exclusionZones.length + 1}`;
            normalizedPolygon.setMap(this.map);
            this.exclusionZones.push(normalizedPolygon);
            this.addPolygonEditListeners(normalizedPolygon);
            console.log("✅ Exclusion zone added manually");

            // Reset flag
            this.isDrawingExclusion = false;
        } else {
            // Replace target zone
            if (this.currentPolygon) {
                this.currentPolygon.setMap(null);
                // Clear exclusions when target changes
                this.exclusionZones.forEach(zone => zone.setMap(null));
                this.exclusionZones = [];
            }

            normalizedPolygon.zoneType = 'inclusion';
            normalizedPolygon.zoneName = 'Target Zone';
            normalizedPolygon.setMap(this.map);
            this.currentPolygon = normalizedPolygon;
            this.addPolygonEditListeners(normalizedPolygon);
            console.log("✅ Target zone set manually");
        }

        this.saveAllZones();
    }

    setupSearch() {
        const searchInput = this.searchRef.el;
        const searchButton = this.searchBtnRef.el;
        const exclusionSearchInput = this.exclusionSearchRef.el;
        const exclusionSearchButton = this.exclusionSearchBtnRef.el;

        searchButton.addEventListener("click", () => {
            this.searchPlace(searchInput.value, 'inclusion');
        });

        searchInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                this.searchPlace(searchInput.value, 'inclusion');
            }
        });

        exclusionSearchButton.addEventListener("click", () => {
            this.searchPlace(exclusionSearchInput.value, 'exclusion');
        });

        exclusionSearchInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                this.searchPlace(exclusionSearchInput.value, 'exclusion');
            }
        });
    }

    async searchPlace(query, zoneType = 'inclusion') {
        if (!query || query.trim() === "") {
            alert("Please enter a location to search");
            return;
        }

        const isExclusion = zoneType === 'exclusion';

        if (isExclusion && !this.currentPolygon) {
            alert("⚠️ Please select a TARGET area first before adding exclusions!");
            return;
        }

        console.log(`🔍 Searching for ${isExclusion ? 'EXCLUSION' : 'TARGET'} area: ${query}`);

        // Show loading message
        const loadingMsg = document.createElement('div');
        loadingMsg.id = 'loading-overlay';
        loadingMsg.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 9999;';
        loadingMsg.innerHTML = '<strong>🔍 Searching for precise boundaries...</strong><br/><small>Searching worldwide for best match</small>';
        document.body.appendChild(loadingMsg);

        try {
            // Use Nominatim for global search with boundaries
            const boundaryData = await this.searchWithNominatim(query);

            // Remove loading message
            document.getElementById('loading-overlay')?.remove();

            if (boundaryData && boundaryData.length > 0) {
                console.log(`✅ Found ${boundaryData.length} precise boundaries`);

                // Auto-select the best match
                const bestMatch = this.selectBestMatch(boundaryData, query);
                console.log(`✅ Auto-selected: ${bestMatch.display_name || bestMatch.tags?.name}`);
                console.log('Best match details:', bestMatch);

                this.createBoundaryZone(bestMatch, zoneType);
            } else {
                alert(`❌ No administrative boundaries found for '${query}'.\n\nPlease try:\n• Full city/state name\n• Add country name (e.g., "Paris, France")\n• Try different spelling\n• Or use manual drawing tools`);
            }
        } catch (error) {
            document.getElementById('loading-overlay')?.remove();
            console.error("❌ Search error:", error);
            alert("Error searching for location. Please try again or use manual drawing.");
        }
    }

    async searchWithNominatim(query) {
        try {
            // Global search with Nominatim - NO country restrictions
            const nominatimUrl = `https://nominatim.openstreetmap.org/search?` +
                `q=${encodeURIComponent(query)}` +
                `&format=json` +
                `&polygon_geojson=1` +
                `&addressdetails=1` +
                `&limit=20`;

            const response = await fetch(nominatimUrl, {
                headers: {
                    'Accept': 'application/json',
                }
            });

            const results = await response.json();

            if (!results || results.length === 0) {
                return null;
            }

            console.log('Nominatim results:', results.map(r => ({
                name: r.display_name,
                type: r.type,
                class: r.class,
                osm_type: r.osm_type,
                place_rank: r.place_rank
            })));

            // Filter results with boundaries
            let resultsWithBoundaries = results.filter(r => r.geojson &&
                (r.geojson.type === 'Polygon' || r.geojson.type === 'MultiPolygon'));

            if (resultsWithBoundaries.length === 0) {
                return null;
            }

            // Prioritize administrative boundaries (relations)
            const adminBoundaries = resultsWithBoundaries.filter(r => {
                const isRelation = r.osm_type === 'relation';
                const isAdministrative = r.class === 'boundary' && r.type === 'administrative';
                return isRelation && isAdministrative;
            });

            // If we found admin boundaries, prefer those
            if (adminBoundaries.length > 0) {
                console.log(`✅ Found ${adminBoundaries.length} administrative boundaries`);
                return adminBoundaries;
            }

            // Otherwise return all results with boundaries
            return resultsWithBoundaries;
        } catch (error) {
            console.error('Nominatim error:', error);
            return null;
        }
    }

    selectBestMatch(results, query) {
        const queryLower = query.toLowerCase().trim();

        // Score each result
        const scored = results.map(result => {
            let score = 0;
            const displayName = (result.display_name || result.tags?.name || '').toLowerCase();
            const type = (result.type || '').toLowerCase();
            const resultClass = (result.class || '').toLowerCase();
            const osmType = (result.osm_type || '').toLowerCase();
            const placeRank = result.place_rank || 999;
            const adminLevel = result.tags?.admin_level ? parseInt(result.tags.admin_level) : null;

            // HIGHEST PRIORITY: Exact name match at start of display name
            if (displayName.startsWith(queryLower + ',') || displayName === queryLower) {
                score += 200;
            } else if (displayName.startsWith(queryLower)) {
                score += 150;
            } else if (displayName.includes(', ' + queryLower + ',')) {
                score += 100;
            } else if (displayName.includes(queryLower)) {
                score += 50;
            }

            // VERY HIGH PRIORITY: Admin level (lower = larger area)
            if (adminLevel !== null) {
                if (adminLevel === 4) score += 200; // Emirate level
                else if (adminLevel === 5) score += 150; // Large region
                else if (adminLevel === 6) score += 120; // City
                else if (adminLevel === 7) score += 80;  // District
                else if (adminLevel === 8) score += 50;  // Suburb
            }

            // VERY HIGH PRIORITY: Administrative boundaries (relations are usually larger areas)
            if (osmType === 'relation') {
                score += 100;
            }

            // HIGH PRIORITY: Type-based scoring (prefer larger administrative areas)
            const typeScores = {
                'state': 150,
                'emirate': 150,
                'administrative': 120,
                'province': 110,
                'region': 100,
                'city': 80,
                'town': 60,
                'municipality': 70,
                'district': 50,
                'suburb': 30,
                'neighbourhood': 20,
                'quarter': 10
            };

            score += typeScores[type] || 0;
            score += typeScores[resultClass] || 0;

            // PRIORITY: Place rank (lower is better - higher admin level)
            if (placeRank <= 12) {
                score += 150; // Emirate/state level
            } else if (placeRank <= 14) {
                score += 100; // Large city
            } else if (placeRank <= 16) {
                score += 70; // City
            } else if (placeRank <= 18) {
                score += 40; // District
            }

            // PRIORITY: Importance score from Nominatim
            if (result.importance) {
                score += result.importance * 100;
            }

            // BONUS: If result has "United Arab Emirates" in name (for UAE searches)
            if (displayName.includes('united arab emirates')) {
                score += 50;
            }

            // BONUS: Prefer results with more coordinate points (more detailed boundaries)
            if (result.geojson) {
                const coords = result.geojson.coordinates;
                if (coords && coords[0] && coords[0].length > 100) {
                    score += 30; // Detailed boundary
                }
            }

            return { result, score };
        });

        // Sort by score (highest first)
        scored.sort((a, b) => b.score - a.score);

        console.log('🏆 Scored results (top 5):');
        scored.slice(0, 5).forEach((s, i) => {
            const adminLevel = s.result.tags?.admin_level || 'N/A';
            console.log(`${i + 1}. ${s.result.display_name || s.result.tags?.name}`);
            console.log(`   Admin Level: ${adminLevel}, Type: ${s.result.type}, Rank: ${s.result.place_rank}, Score: ${s.score}`);
        });

        return scored[0].result;
    }

    createBoundaryZone(result, zoneType) {
        const isExclusion = zoneType === 'exclusion';
        const geojson = result.geojson;

        console.log(`✅ Creating ${isExclusion ? 'EXCLUSION' : 'TARGET'} zone:`, result.display_name || result.tags?.name);
        console.log('GeoJSON type:', geojson.type);

        let paths = [];

        if (geojson.type === 'Polygon') {
            // Simple polygon
            paths = geojson.coordinates[0].map(coord => ({
                lat: coord[1],
                lng: coord[0]
            }));
        } else if (geojson.type === 'MultiPolygon') {
            // Use the largest polygon from multipolygon
            let largestPolygon = geojson.coordinates[0][0];
            let maxArea = 0;

            geojson.coordinates.forEach(polygon => {
                const coords = polygon[0];
                if (coords.length > largestPolygon.length) {
                    largestPolygon = coords;
                }
            });

            paths = largestPolygon.map(coord => ({
                lat: coord[1],
                lng: coord[0]
            }));
        }

        // Remove last point if it duplicates the first (GeoJSON convention)
        if (paths.length > 0) {
            const first = paths[0];
            const last = paths[paths.length - 1];
            if (first.lat === last.lat && first.lng === last.lng) {
                paths.pop();
            }
        }

        // Simplify if too many points (for performance)
        if (paths.length > 500) {
            console.log(`⚠️ Simplifying boundary (${paths.length} points)`);
            paths = this.simplifyPath(paths, 0.001);
            console.log(`✅ Simplified to ${paths.length} points`);
        }

        // Create polygon
        const polygon = new google.maps.Polygon({
            paths: paths,
            fillColor: isExclusion ? "#f44336" : "#4CAF50",
            fillOpacity: isExclusion ? 0.5 : 0.3,
            strokeColor: isExclusion ? "#c62828" : "#2E7D32",
            strokeWeight: 2,
            editable: true,
            draggable: false,
        });

        polygon.zoneType = zoneType;
        polygon.zoneName = result.display_name || result.tags?.name;
        polygon.setMap(this.map);
        this.addPolygonEditListeners(polygon);

        if (isExclusion) {
            this.exclusionZones.push(polygon);
        } else {
            if (this.currentPolygon) {
                this.currentPolygon.setMap(null);
            }
            this.currentPolygon = polygon;
        }

        // Clear markers
        this.searchMarkers.forEach(marker => marker.setMap(null));
        this.searchMarkers = [];

        // Fit map to polygon
        const bounds = new google.maps.LatLngBounds();
        paths.forEach(point => {
            bounds.extend(new google.maps.LatLng(point.lat, point.lng));
        });
        this.map.fitBounds(bounds);

        this.saveAllZones();
        this.showSuccessMessage(result.display_name || result.tags?.name, isExclusion);
    }

    // Simplify path using Douglas-Peucker algorithm
    simplifyPath(points, tolerance) {
        if (points.length < 3) return points;

        const sqTolerance = tolerance * tolerance;

        const simplified = [points[0]];
        this.simplifyDPStep(points, 0, points.length - 1, sqTolerance, simplified);
        simplified.push(points[points.length - 1]);

        return simplified;
    }

    simplifyDPStep(points, first, last, sqTolerance, simplified) {
        let maxSqDist = sqTolerance;
        let index = -1;

        for (let i = first + 1; i < last; i++) {
            const sqDist = this.getSqSegDist(points[i], points[first], points[last]);
            if (sqDist > maxSqDist) {
                index = i;
                maxSqDist = sqDist;
            }
        }

        if (maxSqDist > sqTolerance) {
            if (index - first > 1) this.simplifyDPStep(points, first, index, sqTolerance, simplified);
            simplified.push(points[index]);
            if (last - index > 1) this.simplifyDPStep(points, index, last, sqTolerance, simplified);
        }
    }

    getSqSegDist(p, p1, p2) {
        let x = p1.lat, y = p1.lng;
        let dx = p2.lat - x;
        let dy = p2.lng - y;

        if (dx !== 0 || dy !== 0) {
            const t = ((p.lat - x) * dx + (p.lng - y) * dy) / (dx * dx + dy * dy);
            if (t > 1) {
                x = p2.lat;
                y = p2.lng;
            } else if (t > 0) {
                x += dx * t;
                y += dy * t;
            }
        }

        dx = p.lat - x;
        dy = p.lng - y;
        return dx * dx + dy * dy;
    }

    showSuccessMessage(name, isExclusion) {
        const color = isExclusion ? '#f44336' : '#4CAF50';
        const icon = isExclusion ? '🚫' : '✅';

        let message = `<div style="padding: 15px; min-width: 300px;">`;
        message += `<div style="background: ${color}; color: white; padding: 12px; margin: -15px -15px 12px -15px;">`;
        message += `<strong>${icon} ${isExclusion ? 'Exclusion' : 'Target'} Area Selected!</strong>`;
        message += `</div>`;
        message += `<p style="margin: 0 0 10px 0;"><strong>${name}</strong></p>`;
        message += `<div style="background: #f5f5f5; padding: 10px; border-radius: 4px; font-size: 13px;">`;
        message += `<strong>✏️ You can:</strong><br/>`;
        message += `• Drag corner points to adjust<br/>`;
        message += `• Right-click to delete<br/>`;
        if (!isExclusion) {
            message += `• Use RED search to exclude areas`;
        }
        message += `</div></div>`;

        this.infoWindow.setContent(message);
        this.infoWindow.setPosition(this.currentPolygon.getPath().getAt(0));
        this.infoWindow.open(this.map);
    }

    addPolygonEditListeners(polygon) {
        ['set_at', 'insert_at', 'remove_at'].forEach(event => {
            google.maps.event.addListener(polygon.getPath(), event, () => {
                this.saveAllZones();
            });
        });

        google.maps.event.addListener(polygon, "rightclick", (event) => {
            this.showDeleteMenu(polygon, event.latLng);
        });
    }

    showDeleteMenu(polygon, latLng) {
        const isExclusion = polygon.zoneType === 'exclusion';
        const html =
            `<div style="padding: 10px;">` +
            `<strong style="display: block; margin-bottom: 8px;">${polygon.zoneName || (isExclusion ? 'Exclusion' : 'Target') + ' Zone'}</strong>` +
            `<button onclick="document.dispatchEvent(new CustomEvent('deleteZone', {detail: ${Date.now()}}))" ` +
            `style="background: #f44336; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; width: 100%; font-weight: bold;">` +
            `🗑️ Delete Zone</button>` +
            `</div>`;

        this.infoWindow.setContent(html);
        this.infoWindow.setPosition(latLng);
        this.infoWindow.open(this.map);

        const deleteHandler = () => {
            polygon.setMap(null);
            if (isExclusion) {
                const idx = this.exclusionZones.indexOf(polygon);
                if (idx > -1) this.exclusionZones.splice(idx, 1);
            } else {
                this.currentPolygon = null;
                this.exclusionZones.forEach(z => z.setMap(null));
                this.exclusionZones = [];
            }
            this.infoWindow.close();
            this.saveAllZones();
            document.removeEventListener('deleteZone', deleteHandler);
        };

        document.addEventListener('deleteZone', deleteHandler, { once: true });
    }

    loadExistingPolygon() {
        try {
            const savedData = this.fieldValue;
            if (!savedData) return;

            const data = JSON.parse(savedData);

            if (data.inclusion?.coordinates) {
                const paths = data.inclusion.coordinates[0].map(c => ({ lat: c[1], lng: c[0] }));
                paths.pop();

                this.currentPolygon = new google.maps.Polygon({
                    paths,
                    fillColor: "#4CAF50",
                    fillOpacity: 0.3,
                    strokeColor: "#2E7D32",
                    strokeWeight: 2,
                    editable: true,
                });

                this.currentPolygon.zoneType = 'inclusion';
                this.currentPolygon.setMap(this.map);
                this.addPolygonEditListeners(this.currentPolygon);

                const bounds = new google.maps.LatLngBounds();
                paths.forEach(p => bounds.extend(p));
                this.map.fitBounds(bounds);
            }

            if (data.exclusions) {
                data.exclusions.forEach(excl => {
                    if (excl.coordinates) {
                        const paths = excl.coordinates[0].map(c => ({ lat: c[1], lng: c[0] }));
                        paths.pop();

                        const poly = new google.maps.Polygon({
                            paths,
                            fillColor: "#f44336",
                            fillOpacity: 0.5,
                            strokeColor: "#c62828",
                            strokeWeight: 2,
                            editable: true,
                        });

                        poly.zoneType = 'exclusion';
                        poly.setMap(this.map);
                        this.addPolygonEditListeners(poly);
                        this.exclusionZones.push(poly);
                    }
                });
            }
        } catch (e) {
            console.error("Error loading:", e);
        }
    }

    saveAllZones() {
        try {
            const data = { inclusion: null, exclusions: [] };

            if (this.currentPolygon) {
                const coords = [];
                const path = this.currentPolygon.getPath();
                for (let i = 0; i < path.getLength(); i++) {
                    const p = path.getAt(i);
                    coords.push([p.lng(), p.lat()]);
                }
                coords.push([...coords[0]]);
                data.inclusion = { type: "Polygon", coordinates: [coords] };
            }

            this.exclusionZones.forEach(zone => {
                const coords = [];
                const path = zone.getPath();
                for (let i = 0; i < path.getLength(); i++) {
                    const p = path.getAt(i);
                    coords.push([p.lng(), p.lat()]);
                }
                coords.push([...coords[0]]);
                data.exclusions.push({ type: "Polygon", coordinates: [coords] });
            });

            if (this.props.record?.update) {
                this.props.record.update({ [this.fieldName]: JSON.stringify(data) });
            }
        } catch (e) {
            console.error("Save error:", e);
        }
    }
}

registry.category("fields").add("polygon_map_widget", {
    component: PolygonMapWidget,
    supportedTypes: ["text"],
});