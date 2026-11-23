"""
Tracking views — live bus list, live tracking page, and admin dashboard.
"""
import json
from datetime import timedelta, datetime
import math

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from buses.models import Bus
from .eta import calculate_eta
from accounts.decorators import admin_required
from django.contrib import messages
from school_settings.models import SchoolSettings
from routes.models import Route

from django.contrib.auth.decorators import login_required

@login_required
def bus_list(request):
    """Public page listing all active buses with their current status."""
    buses = (
        Bus.objects.filter(active=True)
        .select_related('route', 'driver')
        .order_by('bus_number')
    )
    return render(request, 'tracking/bus_list.html', {'buses': buses})


@login_required
def journey_planner(request):
    """Let a student choose a destination before choosing a shuttle."""
    routes = Route.objects.filter(active=True).order_by('destination', 'name')
    return render(request, 'tracking/journey_planner.html', {'routes': routes})


def _distance_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres, accurate for local pickup selection."""
    radius = 6_371_000
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lng / 2) ** 2)
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@require_GET
def route_search_api(request):
    """Find active routes and assigned buses between two persisted stops."""
    pickup = request.GET.get('pickup', '').strip()
    destination = request.GET.get('destination', '').strip()
    if not pickup or not destination or pickup.casefold() == destination.casefold():
        return JsonResponse(
            {'detail': 'Choose two different pickup and destination stops.'},
            status=400,
        )

    now = timezone.now()
    live_since = now - timedelta(minutes=2)
    routes = (
        Route.objects.filter(active=True)
        .prefetch_related('stops')
        .order_by('name')
    )
    matching_routes = []

    for route in routes:
        stop_names = [
            route.start_location,
            *(stop.name for stop in route.stops.all()),
            route.destination,
        ]
        stop_names = [name.strip() for name in stop_names]
        pickup_indexes = [
            index for index, name in enumerate(stop_names)
            if name.casefold() == pickup.casefold()
        ]
        destination_indexes = [
            index for index, name in enumerate(stop_names)
            if name.casefold() == destination.casefold()
        ]
        segment_indexes = next(
            (
                (pickup_index, destination_index)
                for pickup_index in pickup_indexes
                for destination_index in destination_indexes
                if pickup_index < destination_index
            ),
            None,
        )
        if segment_indexes is None:
            continue

        start, end = segment_indexes
        buses = []
        for bus in (
            route.buses.filter(active=True)
            .select_related('driver')
            .order_by('bus_number')
        ):
            location = bus.latest_location
            if location and location.timestamp >= live_since:
                gps_status = 'Live GPS'
            elif location:
                seconds_ago = max(0, int((now - location.timestamp).total_seconds()))
                if seconds_ago < 3600:
                    age = f'{max(1, seconds_ago // 60)} min'
                elif seconds_ago < 86400:
                    age = f'{seconds_ago // 3600} hr'
                else:
                    days = seconds_ago // 86400
                    age = f'{days} day' if days == 1 else f'{days} days'
                gps_status = f'Last location {age} ago'
            else:
                gps_status = 'No GPS update yet'

            buses.append({
                'bus_number': bus.bus_number,
                'status': bus.get_status_display(),
                'driver': bus.driver_name,
                'available_seats': bus.available_seats,
                'capacity': bus.capacity,
                'gps_status': gps_status,
                'track_url': reverse('tracking:live_tracking', args=[bus.pk]),
            })

        matching_routes.append({
            'name': route.name,
            'pickup': stop_names[start],
            'destination': stop_names[end],
            'stops': stop_names[start:end + 1],
            'buses': buses,
        })

    return JsonResponse({
        'pickup': pickup,
        'destination': destination,
        'routes': matching_routes,
    })


@require_GET
@login_required
def journey_plan_api(request):
    """Return the best live shuttle and closest pickup for a student's trip."""
    try:
        route_id = int(request.GET['route_id'])
        student_lat = float(request.GET['lat'])
        student_lng = float(request.GET['lng'])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({'detail': 'A destination and valid location are required.'}, status=400)

    if not (-90 <= student_lat <= 90 and -180 <= student_lng <= 180):
        return JsonResponse({'detail': 'Location coordinates are out of range.'}, status=400)

    route = get_object_or_404(Route.objects.prefetch_related('stops'), pk=route_id, active=True)
    ordered_stops = list(route.stops.all())
    pickups = []
    if route.start_latitude is not None and route.start_longitude is not None:
        pickups.append({'name': route.start_location, 'lat': route.start_latitude, 'lng': route.start_longitude,
                        'next_stop': ordered_stops[0].name if ordered_stops else route.destination,
                        'route_index': 0})
    for index, stop in enumerate(ordered_stops):
        if stop.latitude is None or stop.longitude is None:
            continue
        pickups.append({'name': stop.name, 'lat': stop.latitude, 'lng': stop.longitude,
                        'next_stop': ordered_stops[index + 1].name if index + 1 < len(ordered_stops) else route.destination,
                        'route_index': len(pickups)})

    if not pickups:
        return JsonResponse({'detail': 'This route has no pickup points with map coordinates.'}, status=422)

    nearest_pickup = min(pickups, key=lambda point: _distance_m(student_lat, student_lng, point['lat'], point['lng']))
    nearest_walk_distance = _distance_m(student_lat, student_lng, nearest_pickup['lat'], nearest_pickup['lng'])
    live_since = timezone.now() - timedelta(minutes=15)
    live_now_since = timezone.now() - timedelta(minutes=2)
    route_buses = Bus.objects.filter(active=True, route=route).select_related('route')
    buses = (Bus.objects.filter(active=True, route=route, status__in=[Bus.STATUS_MOVING, Bus.STATUS_STOPPED],
                                locations__timestamp__gte=live_since).select_related('route').distinct())

    route_bus_statuses = []
    for route_bus in route_buses:
        route_location = route_bus.latest_location
        if route_location and route_location.timestamp >= live_now_since:
            tracking_label = 'Live location active'
        elif route_location:
            tracking_label = 'Last known location'
        else:
            tracking_label = 'Not live yet'
        route_bus_statuses.append({
            'bus_id': route_bus.pk,
            'bus_number': route_bus.bus_number,
            'tracking_label': tracking_label,
            'is_live': bool(route_location and route_location.timestamp >= live_now_since),
            'last_update': route_location.timestamp.isoformat() if route_location else None,
            'occupied_seats': route_bus.occupied_seats,
            'capacity': route_bus.capacity,
            'available_seats': route_bus.available_seats,
            'track_url': f'/tracking/{route_bus.pk}/',
        })

    recommendations = []
    for bus in buses:
        location = bus.latest_location
        if location is None:
            continue
        bus_route_index = min(
            range(len(pickups)),
            key=lambda index: _distance_m(location.latitude, location.longitude,
                                          pickups[index]['lat'], pickups[index]['lng']),
        )
        pickup = nearest_pickup
        pickup_changed = False
        # Do not direct a student to a distant stop that the bus has passed.
        if nearest_walk_distance > 200 and bus_route_index > nearest_pickup['route_index']:
            upcoming_pickups = [point for point in pickups if point['route_index'] > bus_route_index]
            if not upcoming_pickups:
                continue
            pickup = min(upcoming_pickups,
                         key=lambda point: _distance_m(student_lat, student_lng, point['lat'], point['lng']))
            pickup_changed = True
        speed = location.speed if location.speed and location.speed > 1 else 25
        eta_minutes = max(1, round(_distance_m(location.latitude, location.longitude, pickup['lat'], pickup['lng']) / 1000 / speed * 60))
        recommendations.append({'bus_id': bus.pk, 'bus_number': bus.bus_number, 'status': bus.status,
                                'eta_minutes': eta_minutes, 'last_update': location.timestamp.isoformat(),
                                'track_url': f'/tracking/{bus.pk}/', 'pickup': pickup,
                                'pickup_changed': pickup_changed, 'occupied_seats': bus.occupied_seats,
                                'capacity': bus.capacity, 'available_seats': bus.available_seats})
    recommendations.sort(key=lambda bus: bus['eta_minutes'])

    # When the selected direction has no bus, show students which live route
    # is actually operating so they do not mistake an opposite-direction bus
    # for an unavailable tracking system.
    other_live_buses = (Bus.objects.filter(
        active=True,
        route__isnull=False,
        status__in=[Bus.STATUS_MOVING, Bus.STATUS_STOPPED],
        locations__timestamp__gte=live_since,
    ).exclude(route=route).select_related('route').distinct())
    other_live_routes = [{
        'bus_number': bus.bus_number,
        'route_name': bus.route.name,
        'destination': bus.route.destination,
        'tracking_label': 'Live location active' if bus.latest_location and bus.latest_location.timestamp >= live_now_since else 'Last known location',
        'occupied_seats': bus.occupied_seats,
        'capacity': bus.capacity,
        'available_seats': bus.available_seats,
        'track_url': f'/tracking/{bus.pk}/',
    } for bus in other_live_buses]

    recommended_pickup = recommendations[0]['pickup'] if recommendations else nearest_pickup
    walk_distance = _distance_m(student_lat, student_lng, recommended_pickup['lat'], recommended_pickup['lng'])
    return JsonResponse({'destination': route.destination, 'route_name': route.name, 'pickup': recommended_pickup,
                         'nearest_pickup': nearest_pickup, 'walking_distance_m': round(walk_distance),
                         'walk_required': walk_distance > 200,
                         'buses': recommendations, 'route_buses': route_bus_statuses,
                         'other_live_routes': other_live_routes})


@login_required
def live_tracking(request, bus_id):
    """
    Live tracking page for a single bus.
    Loads Leaflet.js and connects to WebSocket.
    """
    bus = get_object_or_404(Bus, pk=bus_id, active=True)
    location = bus.latest_location
    eta = calculate_eta(bus)

    # Build stop data for Leaflet
    stops = []
    if bus.route:
        for stop in bus.route.stops.all():
            stops.append({
                'name': stop.name,
                'lat': stop.latitude,
                'lng': stop.longitude,
                'order': stop.stop_order,
            })

    # Validate that each stop has latitude and longitude
    missing_coords = []
    for s in stops:
        if s.get('lat') is None or s.get('lng') is None:
            missing_coords.append(s['name'])
    if missing_coords:
        messages.warning(request, f"The following stops are missing coordinates: {', '.join(missing_coords)}")
        stops_missing_coords = True
    else:
        stops_missing_coords = False

    school = SchoolSettings.get_settings()

    context = {
        'bus': bus,
        'location': location,
        'eta': eta,
        'stops_json': json.dumps(stops),
        'route': bus.route,
        'stops_missing_coords': stops_missing_coords,
        'primary_color': school.effective_primary,
    }
    return render(request, 'tracking/live_tracking.html', context)


@require_GET
def bus_status_api(request, bus_id):
    """
    REST endpoint returning the current bus status as JSON.
    Used by the tracking JS as a fallback when WebSocket is unavailable.
    """
    bus = get_object_or_404(Bus, pk=bus_id, active=True)
    location = bus.latest_location
    eta = calculate_eta(bus)

    data = {
        'bus_id': bus.pk,
        'bus_number': bus.bus_number,
        'status': bus.status,
        'driver_name': bus.driver_name,
        'route_name': bus.route_name,
        'eta': eta,
        'latitude': location.latitude if location else None,
        'longitude': location.longitude if location else None,
        'speed': location.speed if location else None,
        'last_update': location.timestamp.isoformat() if location else None,
        'occupied_seats': bus.occupied_seats,
        'capacity': bus.capacity,
        'available_seats': bus.available_seats,
    }
    return JsonResponse(data)


# ------------------------------------------------------------------
# Admin Dashboard
# ------------------------------------------------------------------

@admin_required
def admin_dashboard(request):
    """Custom admin dashboard with system statistics."""
    from accounts.models import User

    total_buses = Bus.objects.count()
    active_buses = Bus.objects.filter(active=True, status__in=['moving', 'stopped']).count()
    offline_buses = Bus.objects.filter(active=True, status='offline').count()
    total_drivers = User.objects.filter(role=User.ROLE_DRIVER).count()
    total_students = User.objects.filter(role=User.ROLE_STUDENT).count()

    from routes.models import Route
    active_routes = Route.objects.filter(active=True).count()

    # Aggregate completed trip records into a readable performance scorecard.
    from .models import EmergencyAlert, Trip
    performance = {}
    for trip in Trip.objects.filter(ended_at__isnull=False, driver__isnull=False).select_related('driver'):
        item = performance.setdefault(trip.driver_id, {
            'name': trip.driver.get_full_name() or trip.driver.username,
            'score_total': 0, 'adherence_total': 0, 'speed_total': 0,
            'driving_seconds': 0, 'completed_trips': 0, 'trips': 0,
        })
        item['score_total'] += trip.safety_score
        item['adherence_total'] += trip.route_adherence
        item['speed_total'] += trip.speed_compliance
        item['driving_seconds'] += trip.driving_seconds
        item['completed_trips'] += int(trip.completed)
        item['trips'] += 1
    driver_performance = []
    for item in performance.values():
        trips = item['trips']
        average_seconds = item['driving_seconds'] // trips
        item.update({
            'safety_score': round(item['score_total'] / trips),
            'route_adherence': round(item['adherence_total'] / trips),
            'speed_compliance': round(item['speed_total'] / trips),
            'average_driving_time': f'{average_seconds // 60}m {average_seconds % 60}s',
        })
        driver_performance.append(item)
    driver_performance.sort(key=lambda item: item['safety_score'], reverse=True)
    active_emergencies = EmergencyAlert.objects.filter(status=EmergencyAlert.STATUS_ACTIVE).select_related('bus', 'driver')

    # Recent buses with location data
    recent_buses = (
        Bus.objects.filter(active=True)
        .select_related('driver', 'route')
        .order_by('bus_number')
    )

    context = {
        'total_buses': total_buses,
        'active_buses': active_buses,
        'offline_buses': offline_buses,
        'total_drivers': total_drivers,
        'total_students': total_students,
        'active_routes': active_routes,
        'recent_buses': recent_buses,
        'driver_performance': driver_performance,
        'active_emergencies': active_emergencies,
    }
    return render(request, 'admin_dashboard/dashboard.html', context)


@require_POST
@admin_required
def acknowledge_emergency(request, alert_id):
    """Clear an SOS only after an administrator has seen and acknowledged it."""
    from .models import EmergencyAlert, EmergencyMessage
    alert = get_object_or_404(EmergencyAlert, pk=alert_id)
    message = request.POST.get('message', '').strip() or 'We have received your emergency alert. Help is on the way.'
    if alert.status == EmergencyAlert.STATUS_ACTIVE:
        alert.status = EmergencyAlert.STATUS_ACKNOWLEDGED
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = request.user
        alert.admin_message = message
        alert.responded_at = timezone.now()
        alert.save(update_fields=['status', 'acknowledged_at', 'acknowledged_by', 'admin_message', 'responded_at'])
        EmergencyMessage.objects.create(alert=alert, sender=request.user, body=message)
        if alert.driver_id:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            async_to_sync(get_channel_layer().group_send)(
                f'driver_alerts_{alert.driver_id}',
                {'type': 'emergency_response', 'alert_id': alert.pk, 'message': message,
                 'admin_name': request.user.get_full_name() or request.user.username,
                 'responded_at': alert.responded_at.isoformat()},
            )
        messages.success(request, f'Emergency alert for Bus {alert.bus.bus_number} acknowledged.')
    return redirect('admin_dashboard')


@require_POST
@admin_required
def admin_emergency_message(request, alert_id):
    """Send a non-acknowledgement message from an admin to a driver."""
    from .models import EmergencyAlert, EmergencyMessage
    alert = get_object_or_404(EmergencyAlert, pk=alert_id)
    body = request.POST.get('message', '').strip()
    if not body:
        return JsonResponse({'detail': 'Enter a message.'}, status=400)
    item = EmergencyMessage.objects.create(alert=alert, sender=request.user, body=body)
    payload = {'type': 'emergency_message', 'alert_id': alert.pk, 'sender_name': request.user.get_full_name() or request.user.username,
               'sender_role': 'admin', 'body': item.body, 'created_at': item.created_at.isoformat()}
    if alert.driver_id:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        async_to_sync(get_channel_layer().group_send)(f'driver_alerts_{alert.driver_id}', payload)
    return JsonResponse(payload, status=201)


@admin_required
def trip_history(request):
    """Completed GPS trips retained for operational and incident review."""
    from .models import Trip
    trips = Trip.objects.filter(ended_at__isnull=False).select_related('bus', 'driver', 'route')
    return render(request, 'tracking/trip_history.html', {'trips': trips})


@admin_required
def trip_replay(request, trip_id):
    """Replay a completed trip with its recorded stops and diversions."""
    from .models import Location, Trip
    from .safety import _on_route, _route_points

    trip = get_object_or_404(Trip.objects.select_related('bus', 'driver', 'route'), pk=trip_id, ended_at__isnull=False)
    locations = list(Location.objects.filter(
        bus=trip.bus, timestamp__gte=trip.started_at, timestamp__lte=trip.ended_at,
    ).order_by('timestamp'))
    route_points = _route_points(trip.route)
    points = [{'lat': location.latitude, 'lng': location.longitude, 'speed': location.speed or 0,
               'time': location.timestamp.isoformat(),
               'off_route': not _on_route(location.latitude, location.longitude, route_points)} for location in locations]

    events = []
    if locations:
        events.append({'kind': 'Start', 'time': locations[0].timestamp.isoformat(), 'lat': locations[0].latitude, 'lng': locations[0].longitude})
    stopped_at = None
    diversion_at = None
    for point in points:
        timestamp = point['time']
        if point['speed'] <= 2 and stopped_at is None:
            stopped_at = point
        elif point['speed'] > 2 and stopped_at is not None:
            start_time = datetime.fromisoformat(stopped_at['time'])
            end_time = datetime.fromisoformat(timestamp)
            if (end_time - start_time).total_seconds() >= 30:
                events.append({'kind': 'Stop', 'time': stopped_at['time'], 'end_time': timestamp,
                               'lat': stopped_at['lat'], 'lng': stopped_at['lng']})
            stopped_at = None
        if point['off_route'] and diversion_at is None:
            diversion_at = point
        elif not point['off_route'] and diversion_at is not None:
            events.append({'kind': 'Diversion', 'time': diversion_at['time'], 'end_time': timestamp,
                           'lat': diversion_at['lat'], 'lng': diversion_at['lng']})
            diversion_at = None
    if stopped_at:
        events.append({'kind': 'Stop', 'time': stopped_at['time'], 'lat': stopped_at['lat'], 'lng': stopped_at['lng']})
    if diversion_at:
        events.append({'kind': 'Diversion', 'time': diversion_at['time'], 'lat': diversion_at['lat'], 'lng': diversion_at['lng']})
    if locations:
        events.append({'kind': 'Arrival' if trip.completed else 'Trip end', 'time': locations[-1].timestamp.isoformat(),
                       'lat': locations[-1].latitude, 'lng': locations[-1].longitude})

    return render(request, 'tracking/trip_replay.html', {
        'trip': trip, 'points': points, 'route_points': [{'lat': lat, 'lng': lng} for lat, lng in route_points],
        'events': events,
    })
