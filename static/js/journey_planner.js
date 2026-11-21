/* Student journey planner: location -> closest pickup -> live shuttle ETA. */
let journeyMap;
let journeyLayers = [];

const notice = document.getElementById('journey-notice');
const result = document.getElementById('journey-result');

function showNotice(message, type = 'error') {
    notice.textContent = message;
    notice.className = `journey-notice ${type}`;
    notice.style.display = 'block';
}

function metres(distance) {
    return distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${distance} m`;
}

function clearMap() {
    journeyLayers.forEach(layer => journeyMap.removeLayer(layer));
    journeyLayers = [];
}

function createMap(lat, lng) {
    if (journeyMap) return;
    journeyMap = L.map('journey-map', { zoomControl: true, maxZoom: 22 }).setView([lat, lng], 15);
    L.maplibreGL({
        style: 'https://tiles.openfreemap.org/styles/liberty',
        attribution: '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a> &copy; OpenMapTiles &copy; OpenStreetMap contributors',
    }).addTo(journeyMap);
}

async function drawWalkingRoute(student, pickup) {
    createMap(student.lat, student.lng);
    clearMap();
    const you = L.marker([student.lat, student.lng]).bindPopup('Your location').addTo(journeyMap);
    const stop = L.marker([pickup.lat, pickup.lng]).bindPopup(`Pickup: ${pickup.name}`).addTo(journeyMap);
    journeyLayers.push(you, stop);

    const fallback = L.polyline([[student.lat, student.lng], [pickup.lat, pickup.lng]], { color: '#16a34a', weight: 5, dashArray: '8, 8' }).addTo(journeyMap);
    journeyLayers.push(fallback);
    journeyMap.fitBounds(fallback.getBounds(), { padding: [45, 45] });

    try {
        const url = `https://router.project-osrm.org/route/v1/foot/${student.lng},${student.lat};${pickup.lng},${pickup.lat}?overview=full&geometries=geojson`;
        const response = await fetch(url);
        const data = await response.json();
        if (!data.routes?.length) return;
        journeyMap.removeLayer(fallback);
        const route = L.geoJSON(data.routes[0].geometry, { style: { color: '#16a34a', weight: 5, opacity: .9 } }).addTo(journeyMap);
        journeyLayers = journeyLayers.filter(layer => layer !== fallback);
        journeyLayers.push(route);
        journeyMap.fitBounds(route.getBounds(), { padding: [45, 45] });
    } catch (_) {
        // The direct walking line remains available if the routing service is unavailable.
    }
}

function renderPlan(plan) {
    const pickup = plan.pickup;
    const walkMessage = plan.walk_required
        ? `Walk to ${pickup.name} (${metres(plan.walking_distance_m)} away).`
        : `You are close to ${pickup.name} (${metres(plan.walking_distance_m)} away).`;
    const busChangedPickup = plan.buses[0]?.pickup_changed;
    const passedPickupMessage = busChangedPickup
        ? `<br><strong>Your nearest pickup (${plan.nearest_pickup.name}) has already been passed. Follow this path to the next pickup instead.</strong>`
        : '';
    document.getElementById('journey-summary').innerHTML = `<h2>Trip to ${plan.destination}</h2><strong>${walkMessage}</strong><br>Next stop after pickup: ${pickup.next_stop}.${passedPickupMessage}`;
    const busArea = document.getElementById('journey-buses');
    if (!plan.buses.length) {
        const assignedBuses = (plan.route_buses || []).map(bus =>
            `<article class="journey-bus"><div><strong>Shuttle ${bus.bus_number}</strong><p><strong>${bus.tracking_label}</strong> · ${bus.occupied_seats} / ${bus.capacity} seats occupied · <strong>${bus.available_seats} seats available</strong></p></div><a class="btn btn-outline" href="${bus.track_url}">Track shuttle</a></article>`
        ).join('') || '<p>No shuttle has been assigned to this route yet.</p>';
        const otherRoutes = (plan.other_live_routes || []).map(bus =>
            `<a href="${bus.track_url}">Shuttle ${bus.bus_number}: ${bus.route_name} (to ${bus.destination}) — ${bus.tracking_label}, ${bus.available_seats} seats available</a>`
        ).join('<br>');
        const operatingMessage = otherRoutes
            ? `<br><br><strong>Currently operating on other routes:</strong><br>${otherRoutes}`
            : '';
        busArea.innerHTML = `<h3 style="margin:1.25rem 0 .5rem">Shuttles assigned to this route</h3>${assignedBuses}<div class="journey-notice error" style="display:block">No recently tracked shuttle is travelling to this destination right now. You can still follow the walking path to the pickup point.${operatingMessage}</div>`;
    } else {
        busArea.innerHTML = plan.buses.map((bus, index) => `<article class="journey-bus"><div><strong>${index === 0 ? 'Recommended: ' : ''}Shuttle ${bus.bus_number}</strong><p>Pickup ${bus.pickup.name} · ETA ${bus.eta_minutes} min · Next stop ${bus.pickup.next_stop}</p><p>${bus.occupied_seats} / ${bus.capacity} seats occupied · <strong>${bus.available_seats} seats available</strong></p></div><a class="btn btn-outline" href="${bus.track_url}">Track shuttle</a></article>`).join('');
    }
    result.style.display = 'block';
}

document.getElementById('journey-form').addEventListener('submit', event => {
    event.preventDefault();
    const routeId = document.getElementById('destination').value;
    if (!routeId) return showNotice('Please choose where you want to go.');
    if (!navigator.geolocation) return showNotice('Your browser does not support location services.');
    showNotice('Getting your location and finding the best pickup point…', 'info');
    navigator.geolocation.getCurrentPosition(async position => {
        const student = { lat: position.coords.latitude, lng: position.coords.longitude };
        try {
            const response = await fetch(`/api/tracking/journey-plan/?route_id=${encodeURIComponent(routeId)}&lat=${student.lat}&lng=${student.lng}`);
            const plan = await response.json();
            if (!response.ok) throw new Error(plan.detail || 'Unable to plan this trip.');
            renderPlan(plan);
            await drawWalkingRoute(student, plan.pickup);
            showNotice('Your journey plan is ready.', 'info');
        } catch (error) {
            showNotice(error.message);
        }
    }, error => {
        const messages = { 1: 'Location permission was denied. Please allow location access to plan your trip.', 2: 'Your location is unavailable.', 3: 'Location request timed out. Please try again.' };
        showNotice(messages[error.code] || 'Unable to get your location.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
});
