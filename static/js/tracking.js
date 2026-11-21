/**
 * Live Tracking Consumer JS
 * Route, shuttle, and pickup markers use the active school logo palette.
 *
 * Performance fixes applied:
 *  - Bus icon only recreated when status / off-route state actually changes
 *  - Walking-route OSRM fetch is debounced and only re-triggered when the
 *    nearest stop changes or the student moves > WALK_REFETCH_THRESHOLD_M
 *  - WebSocket reconnect uses exponential back-off (5 s → 60 s cap)
 *  - autoFitMap guard is the very first line so no work is done after fit
 *  - watchPosition maximumAge raised to 10 s to reduce GPS battery drain
 *  - Nearest-stop marker highlight skipped when nearest stop hasn't changed
 */

/* ─── Global state ──────────────────────────────────────────────── */
let map;
let busMarker;
let routePolyline;       // Yellow bus route
let walkPolyline = null; // Green walk route
let socket;
let conf;

const PICKUP_RADIUS_M        = 200;  // metres — "at pickup" threshold
const WALK_REFETCH_THRESHOLD_M = 15; // metres — min student movement to re-fetch walk route

let mapFittedOnce = false;

/* DOM refs */
let speedDisplay, etaDisplay, updateDisplay;
let wsConnDiv, wsConnText;
let offlineOverlay, badge;

/* Student geolocation */
let studentLocation = { latitude: null, longitude: null, available: false };
let studentMarker   = null;

/* Last position used for the walking-route fetch */
let lastWalkFetchLat  = null;
let lastWalkFetchLng  = null;
let lastWalkFetchStop = null; // name of stop the walk was fetched to

/* Stop markers (keyed by stop name) */
window.__stopMarkers = {};
let nearestStop     = null;
let nearestStopName = null; // cached name to skip redundant highlight passes

/* Bus marker state cache */
let lastBusStatusText = null;
let lastBusOffRoute   = null;

/* Off-route state (for student side) */
let busIsOffRoute = false;

/* Last bus position & speed */
let lastBusLat = null;
let lastBusLng = null;
let lastBusSpeed = 0;

/* WebSocket reconnect back-off */
let wsRetryDelay = 5000; // ms; doubles on each failure up to WS_MAX_DELAY
const WS_MAX_DELAY = 60000;

/* ─── Entry point ───────────────────────────────────────────────── */
function initLiveTracking(config) {
    conf = config;

    speedDisplay   = document.getElementById('speed-display');
    etaDisplay     = document.getElementById('eta-display');
    updateDisplay  = document.getElementById('last-update-display');
    wsConnDiv      = document.getElementById('ws-connection');
    wsConnText     = document.getElementById('ws-conn-text');
    offlineOverlay = document.getElementById('offline-overlay');
    badge          = document.getElementById('bus-status-badge');

    initMap();
    drawBusRoute();
    connectWebSocket();
    showLocationPermissionModal();

    const allowBtn = document.getElementById('use-current-location-btn');
    if (allowBtn) allowBtn.addEventListener('click', () => {
        hideLocationPermissionModal();
        requestStudentLocation();
    });
    const pickBtn = document.getElementById('pick-on-map-btn');
    if (pickBtn) pickBtn.addEventListener('click', () => {
        hideLocationPermissionModal();
        enableMapClickForLocation();
    });
}

function brandColor(slot) {
    return getComputedStyle(document.documentElement)
        .getPropertyValue(`--logo-color-${slot}`).trim() || conf.primaryColor;
}

const MAP_COLORS = {
    walking: '#EAB308',
    pickup: '#DC2626',
    shuttle: '#2563EB',
    student: '#16A34A',
    liveBus: '#1E40AF',
};

/* ─── Map initialisation ────────────────────────────────────────── */
function initMap() {
    // Choose a sensible default centre
    let center = [5.6037, -0.1870]; // Accra, Ghana fallback
    let zoom   = 14;

    if (conf.initialLat && conf.initialLng) {
        center = [conf.initialLat, conf.initialLng];
        zoom   = 16;
    } else if (conf.routeStart.lat && conf.routeStart.lng) {
        center = [conf.routeStart.lat, conf.routeStart.lng];
    } else if (conf.stops && conf.stops.length > 0 && conf.stops[0].lat) {
        center = [conf.stops[0].lat, conf.stops[0].lng];
    }

    map = L.map('tracking-map', {
        zoomControl: false,
        maxZoom: 19,
        minZoom: 3,
        zoomAnimation: true,
        fadeAnimation: true,
        markerZoomAnimation: true,
    }).setView(center, zoom);

    // Esri World Street Map is used as the primary provider because it is reachable
    // from restricted networks where standard OpenStreetMap tile hosts are blocked.
    const primaryTiles = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri &mdash; Sources: Esri, HERE, Garmin, USGS',
        }
    );
    primaryTiles.addTo(map);

    let osmFallback = null;
    primaryTiles.on('tileerror', () => {
        if (!osmFallback) {
            osmFallback = L.tileLayer(
                'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
                {
                    subdomains: 'abc',
                    maxZoom: 19,
                    attribution: '&copy; OpenStreetMap contributors',
                }
            );
            osmFallback.addTo(map);
        }
    });

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Use ResizeObserver to call invalidateSize() whenever the map container
    // actually changes size — more reliable than fixed timeouts.
    const mapEl = document.getElementById('tracking-map');
    if (mapEl && typeof ResizeObserver !== 'undefined') {
        let invalidatePending = false;
        const ro = new ResizeObserver(() => {
            if (!invalidatePending) {
                invalidatePending = true;
                requestAnimationFrame(() => {
                    map.invalidateSize();
                    invalidatePending = false;
                });
            }
        });
        ro.observe(mapEl);
    } else {
        // Fallback for browsers without ResizeObserver
        setTimeout(() => map.invalidateSize(), 300);
        setTimeout(() => map.invalidateSize(), 1000);
    }

    // Add bus marker if we already have a last-known position
    if (conf.initialLat && conf.initialLng) {
        busMarker = createBusMarker(conf.initialLat, conf.initialLng);
        showMapBusCard(conf.busStatus === 'moving' ? 'Moving' : 'Stopped');
    }
}

/* ─── Bus marker (blue or orange bus icon) ──────────────────────── */
function createBusMarker(lat, lng, offRoute) {
    const color = offRoute ? '#EA580C' : MAP_COLORS.liveBus;
    const borderColor = color;
    const icon = L.divIcon({
        className: '',
        html: `<div style="
            background:${color}; color:#fff; border-radius:50% 50% 50% 0;
            transform:rotate(-45deg); width:32px; height:32px;
            display:flex; align-items:center; justify-content:center;
            box-shadow:0 2px 8px rgba(0,0,0,0.35); border:2px solid #fff;
        "><span style="transform:rotate(45deg); font-size:16px;">🚌</span></div>
        <div style="
            background:#fff; border:1px solid ${borderColor}; border-radius:6px;
            padding:2px 6px; font-size:11px; font-weight:700; color:${color};
            margin-top:2px; white-space:nowrap; text-align:center;
            box-shadow:0 1px 4px rgba(0,0,0,0.15);
        ">Bus ${conf.busNumber} Stopped</div>`,
        iconSize:   [80, 58],
        iconAnchor: [16, 32]
    });
    const m = L.marker([lat, lng], { icon, zIndexOffset: 1000 }).addTo(map);
    m.bindPopup(`<b>Bus ${conf.busNumber}</b>`);
    return m;
}

/* ─── Red-pin stop marker ───────────────────────────────────────── */
function redPinIcon(highlighted) {
    const color = highlighted ? '#B91C1C' : MAP_COLORS.pickup;
    const size  = highlighted ? 32 : 28;
    return L.divIcon({
        className: '',
        html: `<div style="
            width:${size}px; height:${size}px;
            background:${color}; border-radius:50% 50% 50% 0;
            transform:rotate(-45deg); border:2px solid #fff;
            box-shadow:0 2px 6px rgba(0,0,0,0.4);
        "></div>`,
        iconSize:   [size, size],
        iconAnchor: [size / 2, size]
    });
}

/* ─── Draw the yellow bus route + red-pin stops ─────────────────── */
function drawBusRoute() {
    const pts = [];

    // Start location
    if (conf.routeStart.lat && conf.routeStart.lng) {
        pts.push([conf.routeStart.lat, conf.routeStart.lng]);
        const m = L.marker([conf.routeStart.lat, conf.routeStart.lng], { icon: redPinIcon(false) })
            .addTo(map)
            .bindPopup(`<b>Start:</b> ${conf.routeStart.name}`)
            .bindTooltip(conf.routeStart.name || 'Campus start', {
                permanent: true,
                direction: 'top',
                offset: [0, -10],
                className: 'campus-map-label',
            });
        window.__stopMarkers[conf.routeStart.name] = m;
    }

    // Intermediate stops
    (conf.stops || []).forEach(stop => {
        if (!stop.lat || !stop.lng) return;
        pts.push([stop.lat, stop.lng]);
        const m = L.marker([stop.lat, stop.lng], { icon: redPinIcon(false) })
            .addTo(map)
            .bindPopup(`<b>${stop.name}</b>`);
        window.__stopMarkers[stop.name] = m;
    });

    // Destination
    if (conf.routeEnd.lat && conf.routeEnd.lng) {
        pts.push([conf.routeEnd.lat, conf.routeEnd.lng]);

        // Destination gets a special larger red pin
        const destIcon = L.divIcon({
            className: '',
            html: `<div style="
                width:36px; height:36px; background:${MAP_COLORS.pickup};
                border-radius:50% 50% 50% 0; transform:rotate(-45deg);
                border:3px solid #fff; box-shadow:0 3px 8px rgba(0,0,0,0.5);
            "></div>
            <div style="
                background:#fff; border:1px solid ${MAP_COLORS.pickup}; border-radius:6px;
                padding:2px 6px; font-size:10px; font-weight:700; color:${MAP_COLORS.pickup};
                margin-top:2px; white-space:nowrap; text-align:center;
            ">Destination</div>`,
            iconSize:   [90, 52],
            iconAnchor: [18, 36]
        });
        L.marker([conf.routeEnd.lat, conf.routeEnd.lng], { icon: destIcon })
            .addTo(map)
            .bindPopup(`<b>Destination:</b> ${conf.routeEnd.name}`)
            .bindTooltip(conf.routeEnd.name || 'Campus destination', {
                permanent: true,
                direction: 'top',
                offset: [0, -18],
                className: 'campus-map-label',
            });
    }

    // Draw a thin dashed placeholder while OSRM loads the real road path
    if (pts.length >= 2) {
        routePolyline = L.polyline(pts, {
            color: MAP_COLORS.shuttle, weight: 5, opacity: 0.55, dashArray: '10,8'
        }).addTo(map);

        // Fit map to the route if no bus position yet
        if (!conf.initialLat) {
            map.fitBounds(routePolyline.getBounds(), { padding: [50, 50] });
        }

        // ── Fetch real road-following path from OSRM ──────────────────────
        // OSRM expects "lng,lat" pairs separated by semicolons
        const coordStr = pts.map(([lat, lng]) => `${lng},${lat}`).join(';');
        const osrmUrl  = `https://router.project-osrm.org/route/v1/driving/${coordStr}`
                       + `?overview=full&geometries=geojson`;

        fetch(osrmUrl)
            .then(r => r.json())
            .then(data => {
                if (!data.routes || data.routes.length === 0) return;

                // Remove the dashed placeholder
                if (routePolyline) { map.removeLayer(routePolyline); routePolyline = null; }

                // Draw the actual road-following route as a solid yellow line
                routePolyline = L.geoJSON(data.routes[0].geometry, {
                    style: { color: MAP_COLORS.shuttle, weight: 7, opacity: 0.95 }
                }).addTo(map);

                // Keep the complete road route visible, including when a bus position
                // is already available.
                map.fitBounds(routePolyline.getBounds(), { padding: [50, 50] });
            })
            .catch(err => console.warn('OSRM bus route fetch failed (falling back to straight line):', err));
    }
}

/* ─── Student geolocation ───────────────────────────────────────── */
function requestStudentLocation() {
    if (!navigator.geolocation) {
        setLocationMsg('Geolocation not supported', 'error');
        return;
    }
    navigator.geolocation.watchPosition(onLocationSuccess, onLocationError, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 10000  // Allow cached positions up to 10 s old — reduces battery use
    });
}

function onLocationSuccess(pos) {
    studentLocation = { latitude: pos.coords.latitude, longitude: pos.coords.longitude, available: true };
    setLocationMsg('Location active', 'success');

    const latlng = [studentLocation.latitude, studentLocation.longitude];

    if (!studentMarker) {
        // Blue circle with "You are here" popup
        const icon = L.divIcon({
            className: '',
            html: `<div style="
                width:18px; height:18px; background:${MAP_COLORS.student}; border-radius:50%;
                border:3px solid #fff; box-shadow:0 0 0 3px rgba(37,99,235,0.35),
                0 2px 6px rgba(0,0,0,0.3);
            "></div>`,
            iconSize:   [18, 18],
            iconAnchor: [9, 9]
        });
        studentMarker = L.marker(latlng, { icon, zIndexOffset: 900 })
            .addTo(map)
            .bindPopup('<b>📍 You are here</b>');
    } else {
        studentMarker.setLatLng(latlng);
    }

    updateNearestStop();
    autoFitMap();
}

function onLocationError(err) {
    const msgs = { 1: 'Location permission denied.', 2: 'Position unavailable.', 3: 'Location timed out.' };
    setLocationMsg(msgs[err.code] || 'Location unavailable.', 'error');
}

/* ─── Haversine ─────────────────────────────────────────────────── */
function haversine(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/* ─── Find nearest stop & conditionally draw green walk route ────── */
function updateNearestStop() {
    if (!studentLocation.available) return;

    const allStops = [];
    if (conf.routeStart.lat && conf.routeStart.lng) allStops.push(conf.routeStart);
    (conf.stops || []).forEach(s => { if (s.lat && s.lng) allStops.push(s); });

    if (allStops.length === 0) return;

    let best = null, bestDist = Infinity;
    allStops.forEach(s => {
        const d = haversine(studentLocation.latitude, studentLocation.longitude, s.lat, s.lng);
        if (d < bestDist) { bestDist = d; best = s; }
    });
    if (!best) return;

    nearestStop = best;

    // Update sidebar
    const nm = document.getElementById('nearest-stop-message');
    if (nm) nm.textContent = best.name;

    // Call updateBusStopEta to recalculate ETA since nearest stop changed
    updateBusStopEta();

    // Only re-highlight stop markers if the nearest stop has changed
    if (best.name !== nearestStopName) {
        nearestStopName = best.name;
        Object.entries(window.__stopMarkers).forEach(([name, marker]) => {
            marker.setIcon(redPinIcon(name === best.name));
        });
    }

    if (bestDist <= PICKUP_RADIUS_M) {
        // Student is at the pickup point
        setLocationMsg('At pickup point ✅', 'success');
        const we = document.getElementById('walking-route-status');
        if (we) we.style.display = 'none';
        if (walkPolyline) { map.removeLayer(walkPolyline); walkPolyline = null; }
        hideMapWalkCard();
        // Reset walk-fetch cache so it re-fetches when student moves away
        lastWalkFetchLat  = null;
        lastWalkFetchLng  = null;
        lastWalkFetchStop = null;
    } else {
        // Draw green walking route — but only if student moved enough or stop changed
        const we = document.getElementById('walking-route-status');
        if (we) we.style.display = 'flex';

        const stopChanged    = best.name !== lastWalkFetchStop;
        const studentMoved   = (lastWalkFetchLat === null) ||
            haversine(studentLocation.latitude, studentLocation.longitude,
                      lastWalkFetchLat, lastWalkFetchLng) > WALK_REFETCH_THRESHOLD_M;

        if (stopChanged || studentMoved) {
            lastWalkFetchLat  = studentLocation.latitude;
            lastWalkFetchLng  = studentLocation.longitude;
            lastWalkFetchStop = best.name;
            fetchWalkRoute(studentLocation.latitude, studentLocation.longitude, best.lat, best.lng);
        }
    }

    updateDistanceToBus();
}

/* ─── OSRM walking route ────────────────────────────────────────── */
function fetchWalkRoute(sLat, sLng, eLat, eLng) {
    const url = `https://router.project-osrm.org/route/v1/foot/${sLng},${sLat};${eLng},${eLat}?overview=full&geometries=geojson`;
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (!data.routes || data.routes.length === 0) return;
            const route = data.routes[0];

            // Remove old walk polyline
            if (walkPolyline) map.removeLayer(walkPolyline);

            // Solid GREEN line
            walkPolyline = L.geoJSON(route.geometry, {
                style: { color: MAP_COLORS.walking, weight: 6, opacity: 0.95 }
            }).addTo(map);

            const distStr = route.distance >= 1000
                ? (route.distance / 1000).toFixed(1) + ' km'
                : Math.round(route.distance) + ' m';
            const mins = Math.max(1, Math.round(route.duration / 60));

            // Update sidebar walk info
            const wem = document.getElementById('walking-eta-message');
            if (wem) wem.textContent = `${distStr} · ${mins} min`;

            // Update map walk card
            showMapWalkCard(nearestStop ? nearestStop.name : '', distStr, mins);
        })
        .catch(err => console.warn('OSRM walking route failed:', err));
}

/* ─── Auto-fit map bounds ───────────────────────────────────────── */
function autoFitMap() {
    // Guard at the very top — no object creation after fit has happened
    if (mapFittedOnce) return;
    if (!studentMarker)  return;

    const pts = [studentMarker.getLatLng()];
    if (busMarker)   pts.push(busMarker.getLatLng());
    if (nearestStop) pts.push([nearestStop.lat, nearestStop.lng]);

    if (pts.length >= 1) {
        map.fitBounds(L.latLngBounds(pts), { padding: [60, 60] });
        mapFittedOnce = true;
    }
}

/* ─── Distance student → bus ────────────────────────────────────── */
function updateDistanceToBus() {
    if (!studentLocation.available || !busMarker) return;
    const bl  = busMarker.getLatLng();
    const d   = haversine(studentLocation.latitude, studentLocation.longitude, bl.lat, bl.lng);
    const str = d >= 1000 ? (d / 1000).toFixed(1) + ' km' : Math.round(d) + ' m';
    const el  = document.getElementById('distance-to-bus-message');
    const ce  = document.getElementById('distance-to-bus-status');
    if (el) el.textContent = str;
    if (ce) ce.style.display = 'flex';
}

/* ─── Bus ETA to nearest stop ───────────────────────────────────── */
function updateBusStopEta() {
    if (!nearestStop || lastBusLat === null || lastBusLng === null) return;
    
    const d = haversine(lastBusLat, lastBusLng, nearestStop.lat, nearestStop.lng); // in meters
    
    // speed is in km/h. fallback to 30km/h if very slow
    const speedKmh = (lastBusSpeed && lastBusSpeed > 2) ? lastBusSpeed : 30;
    const speedMs = speedKmh * (1000 / 3600);
    const etaMinutes = Math.max(1, Math.round((d / speedMs) / 60));
    
    let msg = '';
    if (d <= 50) {
        msg = 'Bus arriving now';
    } else {
        msg = `Bus arriving at your stop in approximately ${etaMinutes} minutes`;
    }
    
    const el = document.getElementById('bus-stop-eta-message');
    if (el) el.textContent = msg;
}


/* ─── WebSocket (with exponential back-off) ─────────────────────── */
function connectWebSocket() {
    socket = new WebSocket(conf.wsUrl);

    socket.onopen = () => {
        wsRetryDelay = 5000; // Reset delay on successful connection
        wsConnDiv.className = 'ws-connection-status connected';
        wsConnText.innerHTML = '🟢 Connected – Live Data Active';
    };

    socket.onmessage = e => {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'location_update') {
                onBusLocation(data);
            } else if (data.type === 'occupancy_update') {
                const seats = document.getElementById('seat-availability-message');
                if (seats) seats.textContent = `${data.occupied_seats} / ${data.capacity} occupied · ${data.available_seats} available`;
            } else if (data.type === 'status_update') {
                applyStatus(data.status);
            } else if (data.type === 'bus_offline') {
                applyStatus('offline');
            }
        } catch (err) { console.error('WS parse error:', err); }
    };

    socket.onclose = () => {
        wsConnDiv.className = 'ws-connection-status disconnected';
        wsConnText.innerHTML = `⚫ Reconnecting in ${Math.round(wsRetryDelay / 1000)}s…`;
        setTimeout(connectWebSocket, wsRetryDelay);
        // Exponential back-off: double the delay, cap at WS_MAX_DELAY
        wsRetryDelay = Math.min(wsRetryDelay * 2, WS_MAX_DELAY);
    };
}

/* ─── Handle incoming bus location ─────────────────────────────── */
let staleTimer = null;

function onBusLocation(data) {
    const { latitude: lat, longitude: lng, speed, off_route } = data;

    lastBusLat = lat;
    lastBusLng = lng;
    lastBusSpeed = speed;

    // Handle off-route status change
    const offRoute = !!off_route;
    if (offRoute !== busIsOffRoute) {
        busIsOffRoute = offRoute;
        if (offRoute) {
            showOffRouteBanner();
        } else {
            hideOffRouteBanner();
        }
    }

    if (!busMarker) {
        busMarker = createBusMarker(lat, lng, offRoute);
        if (offlineOverlay) offlineOverlay.style.display = 'none';
    } else {
        busMarker.setLatLng([lat, lng]);
    }

    // Only rebuild the icon HTML when status/off-route state actually changed
    const newStatusText = speed > 2 ? 'Moving' : 'Stopped';
    if (newStatusText !== lastBusStatusText || offRoute !== lastBusOffRoute) {
        lastBusStatusText = newStatusText;
        lastBusOffRoute   = offRoute;
        updateBusLabel(newStatusText, offRoute);
    }

    // Update sidebar
    if (speedDisplay)  speedDisplay.innerText  = `${speed.toFixed(1)} km/h`;
    if (updateDisplay) updateDisplay.innerText  = 'Just now';
    if (data.eta && etaDisplay) etaDisplay.innerText = data.eta;

    // Bus distance to nearest stop
    updateBusStopEta();

    updateDistanceToBus();
    autoFitMap();
    showMapBusCard(newStatusText);
    applyStatus(speed > 2 ? 'moving' : 'stopped');

    // Stale detection
    clearTimeout(staleTimer);
    staleTimer = setTimeout(() => {
        if (updateDisplay) updateDisplay.innerText = 'Stale (>30s)';
        applyStatus('offline');
    }, 30000);
}

/* ─── Update bus marker label (only when state changes) ──────────── */
function updateBusLabel(statusText, offRoute) {
    if (!busMarker) return;
    const color = offRoute ? '#EA580C' : MAP_COLORS.liveBus;
    const borderColor = color;
    const icon = L.divIcon({
        className: '',
        html: `<div style="
            background:${color}; color:#fff; border-radius:50% 50% 50% 0;
            transform:rotate(-45deg); width:32px; height:32px;
            display:flex; align-items:center; justify-content:center;
            box-shadow:0 2px 8px rgba(0,0,0,0.35); border:2px solid #fff;
        "><span style="transform:rotate(45deg); font-size:16px;">🚌</span></div>
        <div style="
            background:#fff; border:1px solid ${borderColor}; border-radius:6px;
            padding:2px 6px; font-size:11px; font-weight:700; color:${color};
            margin-top:2px; white-space:nowrap; text-align:center;
            box-shadow:0 1px 4px rgba(0,0,0,0.15);
        ">Bus ${conf.busNumber} ${statusText}</div>`,
        iconSize:   [90, 58],
        iconAnchor: [16, 32]
    });
    busMarker.setIcon(icon);
}

/* ─── Status badge ──────────────────────────────────────────────── */
function applyStatus(status) {
    conf.busStatus = status;
    if (!badge) return;
    const map_ = {
        moving:  ['status-moving',  '🟢 MOVING'],
        stopped: ['status-stopped', '🟡 STOPPED'],
        offline: ['status-offline', '⚫ OFFLINE']
    };
    const [cls, txt] = map_[status] || map_.offline;
    badge.className = `status-badge-large ${cls}`;
    badge.innerText = txt;

    if (offlineOverlay)
        offlineOverlay.style.display = status === 'offline' ? 'flex' : 'none';
}

/* ─── Map info cards ─────────────────────────────────────────────── */
function showMapBusCard(statusText) {
    const card = document.getElementById('map-bus-card');
    const val  = document.getElementById('map-bus-status');
    if (card) card.style.display = 'block';
    if (val)  val.textContent = statusText;
}

function showMapWalkCard(stopName, distStr, mins) {
    const card  = document.getElementById('map-walk-card');
    const info  = document.getElementById('map-walk-info');
    const tinfo = document.getElementById('map-walk-time');
    if (card) card.style.display = 'block';
    if (info) info.textContent = stopName ? `Walk to ${stopName}` : 'Walk Route';
    if (tinfo) tinfo.textContent = `Distance: ${distStr} · ${mins} min`;
}

function hideMapWalkCard() {
    const card = document.getElementById('map-walk-card');
    if (card) card.style.display = 'none';
}

/* ─── Sidebar geolocation message ───────────────────────────────── */
function setLocationMsg(msg, type) {
    const el = document.getElementById('student-location-message');
    if (!el) return;
    el.textContent  = msg;
    const colorSlot = type === 'success' ? 4 : type === 'error' ? 5 : 6;
    el.style.color = brandColor(colorSlot);
}

/* ─── Location permission modal ─────────────────────────────────── */
function showLocationPermissionModal() {
    const modal = document.getElementById('location-permission-modal');
    if (modal) modal.style.display = 'block';
}

function hideLocationPermissionModal() {
    const modal = document.getElementById('location-permission-modal');
    if (modal) modal.style.display = 'none';
}

/* ─── Map-click location picker ─────────────────────────────────── */
function enableMapClickForLocation() {
    // One-time click listener
    const clickHandler = function(e) {
        const latlng = e.latlng;
        studentLocation = { latitude: latlng.lat, longitude: latlng.lng, available: true };
        setLocationMsg('Location selected', 'success');
        // Create or update student marker
        if (!studentMarker) {
            const icon = L.divIcon({
                className: '',
                html: `<div style="
                    width:18px; height:18px; background:${MAP_COLORS.student}; border-radius:50%; 
                    border:3px solid #fff; box-shadow:0 0 0 3px rgba(37,99,235,0.35),
                    0 2px 6px rgba(0,0,0,0.3);
                "></div>`,
                iconSize:   [18, 18],
                iconAnchor: [9, 9]
            });
            studentMarker = L.marker([latlng.lat, latlng.lng], { icon, zIndexOffset: 900 })
                .addTo(map)
                .bindPopup('<b>📍 You are here</b>');
        } else {
            studentMarker.setLatLng([latlng.lat, latlng.lng]);
        }
        updateNearestStop();
        autoFitMap();
        // Remove click listener after selection
        map.off('click', clickHandler);
    };
    map.on('click', clickHandler);
}

/* ─── Off-route banner (student side) ───────────────────────────── */
function showOffRouteBanner() {
    const banner = document.getElementById('off-route-banner');
    if (banner) banner.style.display = 'flex';
    const sideBadge = document.getElementById('off-route-sidebar-badge');
    if (sideBadge) sideBadge.style.display = 'flex';
    const offRouteLegend = document.getElementById('legend-off-route-note');
    if (offRouteLegend) offRouteLegend.style.display = 'flex';
}

function hideOffRouteBanner() {
    const banner = document.getElementById('off-route-banner');
    if (banner) banner.style.display = 'none';
    const sideBadge = document.getElementById('off-route-sidebar-badge');
    if (sideBadge) sideBadge.style.display = 'none';
    const offRouteLegend = document.getElementById('legend-off-route-note');
    if (offRouteLegend) offRouteLegend.style.display = 'none';
}
