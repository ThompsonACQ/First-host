/**
 * Driver Dashboard Logic
 * Handles Geolocation API, WebSocket communication, and off-route detection.
 *
 * Off-route detection:
 *   Every GPS fix computes the shortest perpendicular distance from the
 *   driver's position to the nearest segment of the assigned route polyline.
 *   If that distance exceeds OFF_ROUTE_THRESHOLD_M the driver sees a full-
 *   screen modal with a mini-map and OSRM navigation back to the route.
 */

/* ── Constants ──────────────────────────────────────────────────────────── */
const OFF_ROUTE_THRESHOLD_M = 150; // metres

/* ── State ──────────────────────────────────────────────────────────────── */
let watchId      = null;
let socket       = null;
let isSharing    = false;
let currentBusId = null;
let wsUrl        = null;
let routeWaypoints = [];   // [{lat, lng}, …] built from DRIVER_CONFIG
let isOffRoute   = false;  // current off-route state
let miniMap      = null;   // Leaflet map inside the modal
let miniMapDriverMarker  = null;
let miniMapRoutePolyline = null;
let miniMapNavPolyline   = null;
let pendingLocationUpdate = null;
let sharingStopNotified = false;
let activeEmergencyAlertId = null;
let wsRetryDelay = 3000;
let wsRetryTimer = null;

/* ── DOM Elements ────────────────────────────────────────────────────────── */
const btnStart        = document.getElementById('btn-start');
const btnStop         = document.getElementById('btn-stop');
const statusCard      = document.getElementById('gps-status-card');
const statusIndicator = document.getElementById('gps-status');
const statusText      = document.getElementById('gps-status-text');
const speedDisplay    = document.getElementById('current-speed');
const latDisplay      = document.getElementById('current-lat');
const lngDisplay      = document.getElementById('current-lng');
const accDisplay      = document.getElementById('current-accuracy');
const timeDisplay     = document.getElementById('last-update');
const errorDiv        = document.getElementById('gps-error');
const errorText       = document.getElementById('gps-error-text');
const wsStatus        = document.getElementById('ws-status');
const wsStatusText    = document.getElementById('ws-status-text');
const occupancyInput  = document.getElementById('occupancy-input');
const occupiedSeats   = document.getElementById('occupied-seats');
const availableSeats  = document.getElementById('available-seats');
const occupancyMessage = document.getElementById('occupancy-message');

function getCookie(name) {
    return document.cookie.split('; ').find(row => row.startsWith(`${name}=`))?.split('=')[1];
}

function changeOccupancy(change) {
    if (!occupancyInput) return;
    const capacity = Number(occupancyInput.max);
    occupancyInput.value = Math.max(0, Math.min(capacity, Number(occupancyInput.value || 0) + change));
}

async function saveOccupancy() {
    if (!occupancyInput) return;
    const occupied = Number(occupancyInput.value);
    if (!Number.isInteger(occupied)) return;
    if (occupancyMessage) occupancyMessage.textContent = 'Saving passenger count…';
    try {
        const response = await fetch('/accounts/driver/occupancy/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(getCookie('csrftoken') || '') },
            body: JSON.stringify({ occupied_seats: occupied }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not save passenger count.');
        occupancyInput.value = data.occupied_seats;
        if (occupiedSeats) occupiedSeats.textContent = data.occupied_seats;
        if (availableSeats) availableSeats.textContent = data.available_seats;
        if (occupancyMessage) occupancyMessage.textContent = `${data.available_seats} seats available — saved.`;
    } catch (error) {
        if (occupancyMessage) occupancyMessage.textContent = error.message;
    }
}

async function sendEmergencyAlert() {
    const button = document.getElementById('btn-sos');
    const message = document.getElementById('sos-message');
    const type = document.getElementById('emergency-type')?.value;
    if (!type) return;
    if (!confirm(`Send a ${type.replace('_', ' ')} SOS alert to all administrators now?`)) return;
    if (button) button.disabled = true;
    if (message) message.textContent = 'Sending emergency alert…';
    try {
        const response = await fetch('/accounts/driver/emergency/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(getCookie('csrftoken') || '') },
            body: JSON.stringify({ emergency_type: type }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not send the emergency alert.');
        activeEmergencyAlertId = data.alert_id;
        document.getElementById('emergency-chat').style.display = 'block';
        if (message) message.textContent = `SOS sent at ${new Date(data.created_at).toLocaleTimeString()}. Administrators have been alerted.`;
    } catch (error) {
        if (message) message.textContent = error.message;
        if (button) button.disabled = false;
    }
}

/* ── Entry point ─────────────────────────────────────────────────────────── */
function initDriverGPS(busId, url, config) {
    currentBusId = busId;
    wsUrl        = url;

    // Build ordered waypoints array from DRIVER_CONFIG
    if (config) {
        if (config.routeStart && config.routeStart.lat && config.routeStart.lng) {
            routeWaypoints.push({ lat: config.routeStart.lat, lng: config.routeStart.lng });
        }
        (config.stops || []).forEach(s => {
            if (s.lat && s.lng) routeWaypoints.push({ lat: s.lat, lng: s.lng });
        });
        if (config.routeEnd && config.routeEnd.lat && config.routeEnd.lng) {
            routeWaypoints.push({ lat: config.routeEnd.lat, lng: config.routeEnd.lng });
        }
    }

    if (!navigator.geolocation) {
        showError('Your browser does not support Geolocation.');
        if (btnStart) btnStart.disabled = true;
    }
    // Keep a private connection open so an SOS acknowledgement can reach the
    // driver even when they have paused regular location sharing.
    connectWebSocket();
    loadLatestEmergencyResponse();
}

/* ── WebSocket ───────────────────────────────────────────────────────────── */
function connectWebSocket() {
    if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) return;
    const connection = new WebSocket(wsUrl);
    socket = connection;

    connection.onopen = function () {
        wsRetryDelay = 3000;
        if (wsRetryTimer) {
            clearTimeout(wsRetryTimer);
            wsRetryTimer = null;
        }
        if (pendingLocationUpdate) {
            connection.send(JSON.stringify(pendingLocationUpdate));
            pendingLocationUpdate = null;
        }
        wsStatus.className    = 'ws-status connected';
        wsStatusText.innerHTML = '🟢 Connected to server';
    };

    connection.onmessage = function (event) {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'error') {
                showError('Server Error: ' + data.message);
            } else if (data.type === 'emergency_response') {
                showEmergencyResponse(data);
            } else if (data.type === 'emergency_message') {
                showEmergencyMessage(data);
            }
        } catch (e) {}
    };

    connection.onclose = function () {
        if (socket !== connection) return;
        wsStatus.className    = 'ws-status disconnected';
        wsStatusText.innerHTML = '⚫ Disconnected from server';
        if (!wsRetryTimer) {
            wsRetryTimer = setTimeout(function () {
                wsRetryTimer = null;
                connectWebSocket();
            }, wsRetryDelay);
            wsRetryDelay = Math.min(wsRetryDelay * 2, 60000);
        }
    };

    connection.onerror = function (error) {
        console.error('[WS error]', error.message);
    };
}

async function loadLatestEmergencyResponse() {
    try {
        const response = await fetch('/accounts/driver/emergency-response/');
        const data = await response.json();
        if (response.ok && data.response) showEmergencyResponse(data.response, false);
    } catch (_) {
        // WebSocket delivery remains available if the recovery check fails.
    }
}

function showEmergencyResponse(data, announce = true) {
    activeEmergencyAlertId = data.alert_id;
    document.getElementById('emergency-chat').style.display = 'block';
    const response = document.getElementById('emergency-response');
    const text = document.getElementById('emergency-response-text');
    const message = `${data.admin_name || 'An administrator'} responded: ${data.message}`;
    if (text) text.textContent = message;
    if (response) response.style.display = 'block';
    // Make an urgent response hard to miss even if the driver is focused on
    // another part of the dashboard.
    if (announce) window.alert(`SOS acknowledged. ${message}`);
}

function showEmergencyMessage(data) {
    activeEmergencyAlertId = data.alert_id || activeEmergencyAlertId;
    const chat = document.getElementById('emergency-chat');
    const messages = document.getElementById('emergency-chat-messages');
    if (chat) chat.style.display = 'block';
    if (messages) {
        const line = document.createElement('div');
        line.textContent = `${data.sender_name || 'Admin'}: ${data.body}`;
        messages.appendChild(line);
    }
}

async function sendDriverEmergencyMessage() {
    const input = document.getElementById('driver-emergency-message');
    const body = input?.value.trim();
    if (!activeEmergencyAlertId || !body) return;
    const response = await fetch(`/accounts/driver/emergencies/${activeEmergencyAlertId}/message/`, {
        method: 'POST', headers: {'Content-Type':'application/x-www-form-urlencoded', 'X-CSRFToken': decodeURIComponent(getCookie('csrftoken') || '')},
        body: new URLSearchParams({message: body}),
    });
    const data = await response.json();
    if (!response.ok) return showError(data.detail || 'Could not send your message.');
    input.value = '';
    showEmergencyMessage({sender_name: 'You', body: data.body, alert_id: data.alert_id});
}

/* ── Sharing controls ────────────────────────────────────────────────────── */
function startSharing() {
    errorDiv.style.display = 'none';
    sharingStopNotified = false;

    try {
        if ('wakeLock' in navigator) navigator.wakeLock.request('screen');
    } catch (e) {}

    if (!socket || socket.readyState !== WebSocket.OPEN) connectWebSocket();

    watchId = navigator.geolocation.watchPosition(successCallback, errorCallback, {
        enableHighAccuracy: true,
        timeout:            10000,
        maximumAge:         0,
    });

    isSharing = true;
    if (btnStart) { btnStart.disabled = true; btnStart.classList.replace('btn-success', 'btn-outline'); }
    if (btnStop)  btnStop.disabled = false;
    if (statusCard) statusCard.style.borderColor = 'var(--success)';
    if (statusIndicator) statusIndicator.className = 'status-indicator active';
    if (statusText)      statusText.innerText = 'Sharing Location';
}

function stopSharing() {
    if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
    }
    isSharing = false;
    notifySharingStopped();

    // Keep the dashboard socket open for private admin SOS responses. GPS
    // updates have already stopped because the browser watch was cleared.

    // Dismiss any off-route modal
    hideOffRouteModal();

    if (btnStart) { btnStart.disabled = false; btnStart.classList.replace('btn-outline', 'btn-success'); }
    if (btnStop)  btnStop.disabled = true;
    if (statusCard) statusCard.style.borderColor = 'transparent';
    if (statusIndicator) statusIndicator.className = 'status-indicator offline';
    if (statusText)      statusText.innerText = 'Not sharing';
    if (speedDisplay)    speedDisplay.innerText = '— km/h';
}

/* ── GPS success callback ────────────────────────────────────────────────── */
function successCallback(position) {
    const lat      = position.coords.latitude;
    const lng      = position.coords.longitude;
    const speed    = position.coords.speed;
    const heading  = position.coords.heading;
    const accuracy = position.coords.accuracy;

    // Convert speed m/s → km/h
    const speedKmh = (speed !== null && speed > 0) ? speed * 3.6 : 0;

    // Update UI
    if (latDisplay)   latDisplay.innerText   = lat.toFixed(6);
    if (lngDisplay)   lngDisplay.innerText   = lng.toFixed(6);
    if (accDisplay)   accDisplay.innerText   = `±${Math.round(accuracy)}m`;
    if (speedDisplay) speedDisplay.innerText = `${Math.round(speedKmh)} km/h`;
    if (timeDisplay)  timeDisplay.innerText  = new Date().toLocaleTimeString();

    // Keep the first GPS fix until the WebSocket is ready instead of dropping it.
    const locationUpdate = {
        type: 'location_update', latitude: lat, longitude: lng,
        speed: speedKmh, heading: heading, accuracy: accuracy,
    };
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(locationUpdate));
    } else {
        pendingLocationUpdate = locationUpdate;
    }

    // ── Off-route check ──────────────────────────────────────────────────
    checkOffRoute(lat, lng);
}

/* ── Off-route detection ─────────────────────────────────────────────────── */

/** Great-circle distance in metres between two GPS points. */
function notifySharingStopped() {
    if (sharingStopNotified || !currentBusId) return;
    sharingStopNotified = true;
    fetch('/accounts/driver/stop-sharing/', {
        method: 'POST',
        keepalive: true,
        headers: { 'X-CSRFToken': decodeURIComponent(getCookie('csrftoken') || '') },
    }).catch(() => {});
}

// Browser GPS ends when this page closes. Preserve the saved point and
// immediately mark it as last known rather than leaving the bus "moving".
window.addEventListener('pagehide', () => {
    if (isSharing) notifySharingStopped();
});

function haversineM(lat1, lon1, lat2, lon2) {
    const R = 6_371_000;
    const toRad = x => x * Math.PI / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2
            + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** Minimum distance in metres from point P to segment A→B. */
function pointToSegmentM(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay;
    if (dx === 0 && dy === 0) return haversineM(px, py, ax, ay);
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
    return haversineM(px, py, ax + t * dx, ay + t * dy);
}

/** Find the nearest point ON the route polyline to (lat, lng). Returns {lat, lng}. */
function nearestRoutePoint(lat, lng) {
    let bestDist = Infinity, bestPt = null;
    for (let i = 0; i < routeWaypoints.length - 1; i++) {
        const { lat: ax, lng: ay } = routeWaypoints[i];
        const { lat: bx, lng: by } = routeWaypoints[i + 1];
        const dx = bx - ax, dy = by - ay;
        const t = (dx === 0 && dy === 0) ? 0
            : Math.max(0, Math.min(1, ((lat - ax) * dx + (lng - ay) * dy) / (dx * dx + dy * dy)));
        const nx = ax + t * dx, ny = ay + t * dy;
        const d = haversineM(lat, lng, nx, ny);
        if (d < bestDist) { bestDist = d; bestPt = { lat: nx, lng: ny }; }
    }
    return bestPt;
}

function checkOffRoute(lat, lng) {
    if (routeWaypoints.length < 2) return; // no route to check against

    let minDist = Infinity;
    for (let i = 0; i < routeWaypoints.length - 1; i++) {
        const { lat: ax, lng: ay } = routeWaypoints[i];
        const { lat: bx, lng: by } = routeWaypoints[i + 1];
        const d = pointToSegmentM(lat, lng, ax, ay, bx, by);
        if (d < minDist) minDist = d;
    }

    if (minDist > OFF_ROUTE_THRESHOLD_M) {
        // Driver is off-route
        if (!isOffRoute) {
            isOffRoute = true;
            showOffRouteModal(lat, lng);
        } else {
            // Already showing — just update the driver pin position
            updateMiniMapDriver(lat, lng);
        }
    } else {
        // Driver is back on route
        if (isOffRoute) {
            isOffRoute = false;
            hideOffRouteModal();
        }
    }
}

/* ── Off-route modal ─────────────────────────────────────────────────────── */

function showOffRouteModal(lat, lng) {
    const modal = document.getElementById('off-route-modal');
    if (!modal) return;
    modal.style.display = 'flex';

    // Initialise the mini-map (only once)
    if (!miniMap) {
        miniMap = L.map('driver-mini-map', { zoomControl: true }).setView([lat, lng], 16);
        L.tileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
            {
                attribution: 'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Sources: Esri, HERE, Garmin, FAO, NOAA, USGS, OpenStreetMap contributors',
                maxZoom: 19,
            }
        ).addTo(miniMap);

        // Fetch road-following route for the mini-map (OSRM driving)
        if (routeWaypoints.length >= 2) {
            const coordStr = routeWaypoints.map(p => `${p.lng},${p.lat}`).join(';');
            const routeUrl = `https://router.project-osrm.org/route/v1/driving/${coordStr}`
                           + `?overview=full&geometries=geojson`;
            fetch(routeUrl)
                .then(r => r.json())
                .then(data => {
                    if (!data.routes || data.routes.length === 0) return;
                    if (miniMapRoutePolyline) miniMap.removeLayer(miniMapRoutePolyline);
                    miniMapRoutePolyline = L.geoJSON(data.routes[0].geometry, {
                        style: { color: '#eab308', weight: 5, opacity: 0.9 }
                    }).addTo(miniMap);
                })
                .catch(() => {
                    // Fallback to straight line if OSRM unavailable
                    if (miniMapRoutePolyline) miniMap.removeLayer(miniMapRoutePolyline);
                    miniMapRoutePolyline = L.polyline(
                        routeWaypoints.map(p => [p.lat, p.lng]),
                        { color: '#eab308', weight: 5, opacity: 0.9 }
                    ).addTo(miniMap);
                });
        }
    } else {
        setTimeout(() => miniMap.invalidateSize(), 100);
    }

    // Place / move the driver marker
    updateMiniMapDriver(lat, lng);

    // Fetch OSRM navigation path to nearest route point
    const nearest = nearestRoutePoint(lat, lng);
    if (nearest) {
        fetchNavRoute(lat, lng, nearest.lat, nearest.lng);
    }

    setTimeout(() => miniMap.invalidateSize(), 300);
}

function updateMiniMapDriver(lat, lng) {
    if (!miniMap) return;
    const icon = L.divIcon({
        className: '',
        html: `<div style="
            background:#dc2626; color:#fff; border-radius:50% 50% 50% 0;
            transform:rotate(-45deg); width:34px; height:34px;
            display:flex; align-items:center; justify-content:center;
            box-shadow:0 2px 8px rgba(0,0,0,0.45); border:2px solid #fff;
        "><span style="transform:rotate(45deg); font-size:18px;">🚌</span></div>`,
        iconSize:   [34, 34],
        iconAnchor: [17, 34],
    });
    if (!miniMapDriverMarker) {
        miniMapDriverMarker = L.marker([lat, lng], { icon, zIndexOffset: 1000 })
            .addTo(miniMap)
            .bindPopup('<b>You are here</b>');
    } else {
        miniMapDriverMarker.setLatLng([lat, lng]);
    }
    miniMap.setView([lat, lng], miniMap.getZoom());
}

function fetchNavRoute(sLat, sLng, eLat, eLng) {
    const url = `https://router.project-osrm.org/route/v1/driving/${sLng},${sLat};${eLng},${eLat}?overview=full&geometries=geojson`;
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (!data.routes || data.routes.length === 0) return;
            if (miniMapNavPolyline) miniMap.removeLayer(miniMapNavPolyline);
            miniMapNavPolyline = L.geoJSON(data.routes[0].geometry, {
                style: { color: '#2563eb', weight: 5, opacity: 0.95, dashArray: '8,6' }
            }).addTo(miniMap);

            // Fit mini-map to show both driver + nav route
            const bounds = miniMapNavPolyline.getBounds();
            if (miniMapRoutePolyline) bounds.extend(miniMapRoutePolyline.getBounds());
            miniMap.fitBounds(bounds, { padding: [30, 30] });

            // Show distance info
            const distM = data.routes[0].distance;
            const distStr = distM >= 1000 ? (distM / 1000).toFixed(1) + ' km' : Math.round(distM) + ' m';
            const mins = Math.max(1, Math.round(data.routes[0].duration / 60));
            const infoEl = document.getElementById('off-route-nav-info');
            if (infoEl) infoEl.textContent = `${distStr} · ~${mins} min back to route`;
        })
        .catch(err => console.warn('OSRM nav route failed:', err));
}

function hideOffRouteModal() {
    const modal = document.getElementById('off-route-modal');
    if (modal) modal.style.display = 'none';
}

/* ── GPS error callback ──────────────────────────────────────────────────── */
function errorCallback(error) {
    const msgs = {
        1: 'Location permission denied. Please enable GPS and allow location access.',
        2: 'Location information is unavailable. Check GPS signal.',
        3: 'The request to get user location timed out.',
    };
    showError(msgs[error.code] || 'An unknown error occurred.');
    if (error.code === 1) stopSharing();
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function showError(msg) {
    if (errorText) errorText.innerText = msg;
    if (errorDiv)  errorDiv.style.display = 'flex';
}
