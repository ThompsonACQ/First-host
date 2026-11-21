"""Server-side driver safety calculations based on recorded GPS fixes."""

import math

from django.utils import timezone

from .models import Trip

SPEED_LIMIT_KMH = 50
HARD_BRAKE_DROP_KMH = 15
HARD_BRAKE_WINDOW_SECONDS = 10
STOP_SECONDS = 90
ROUTE_THRESHOLD_M = 150
DESTINATION_THRESHOLD_M = 200


def distance_m(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _route_points(route):
    if not route:
        return []
    points = []
    if route.start_latitude is not None and route.start_longitude is not None:
        points.append((route.start_latitude, route.start_longitude))
    points.extend((stop.latitude, stop.longitude) for stop in route.stops.order_by('stop_order') if stop.latitude is not None and stop.longitude is not None)
    if route.destination_latitude is not None and route.destination_longitude is not None:
        points.append((route.destination_latitude, route.destination_longitude))
    return points


def _on_route(lat, lng, points):
    # A conservative point-to-waypoint check is used when a route only has
    # one coordinate; otherwise check the nearest projected route segment.
    if len(points) < 2:
        return True
    distances = []
    for (a_lat, a_lng), (b_lat, b_lng) in zip(points, points[1:]):
        d_lat, d_lng = b_lat - a_lat, b_lng - a_lng
        length_squared = d_lat * d_lat + d_lng * d_lng
        factor = 0 if length_squared == 0 else max(0, min(1, ((lat - a_lat) * d_lat + (lng - a_lng) * d_lng) / length_squared))
        distances.append(distance_m(lat, lng, a_lat + factor * d_lat, a_lng + factor * d_lng))
    nearest = min(distances)
    return nearest <= ROUTE_THRESHOLD_M


def _near_declared_stop(lat, lng, route):
    return any(distance_m(lat, lng, point_lat, point_lng) <= ROUTE_THRESHOLD_M for point_lat, point_lng in _route_points(route))


def update_trip_for_location(bus, driver, location):
    """Create/update the active trip and recalculate its current score."""
    trip = Trip.objects.filter(bus=bus, driver=driver, ended_at__isnull=True).first()
    if trip is None:
        trip = Trip.objects.create(bus=bus, driver=driver, route=bus.route)

    previous = bus.locations.exclude(pk=location.pk).order_by('-timestamp').first()
    route_points = _route_points(trip.route)
    trip.point_count += 1
    trip.speed_points += 1
    if _on_route(location.latitude, location.longitude, route_points):
        trip.on_route_points += 1
    if (location.speed or 0) > SPEED_LIMIT_KMH:
        trip.speeding_events += 1
    if previous and previous.speed is not None and location.speed is not None:
        elapsed = (location.timestamp - previous.timestamp).total_seconds()
        if 0 < elapsed <= HARD_BRAKE_WINDOW_SECONDS and previous.speed - location.speed >= HARD_BRAKE_DROP_KMH:
            trip.hard_braking_events += 1

    if (location.speed or 0) <= 2:
        if trip.stop_started_at is None:
            trip.stop_started_at = location.timestamp
        elif (not trip.unnecessary_stop_recorded and
              (location.timestamp - trip.stop_started_at).total_seconds() >= STOP_SECONDS and
              not _near_declared_stop(location.latitude, location.longitude, trip.route)):
            trip.unnecessary_stops += 1
            trip.unnecessary_stop_recorded = True
    else:
        trip.stop_started_at = None
        trip.unnecessary_stop_recorded = False

    _set_score(trip)
    trip.save()
    return trip


def finish_active_trip(bus, driver):
    trip = Trip.objects.filter(bus=bus, driver=driver, ended_at__isnull=True).first()
    if not trip:
        return None
    location = bus.latest_location
    route = trip.route
    if location and route and route.destination_latitude is not None and route.destination_longitude is not None:
        trip.completed = distance_m(location.latitude, location.longitude, route.destination_latitude, route.destination_longitude) <= DESTINATION_THRESHOLD_M
    trip.ended_at = timezone.now()
    _set_score(trip)
    trip.save(update_fields=['completed', 'ended_at', 'safety_score'])
    return trip


def _set_score(trip):
    adherence = trip.route_adherence
    speed = trip.speed_compliance
    brake = max(0, 100 - trip.hard_braking_events * 10)
    completion = 100 if trip.completed else 0
    trip.safety_score = round(adherence * .40 + speed * .35 + brake * .15 + completion * .10)
