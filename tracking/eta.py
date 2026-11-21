"""
ETA calculation utility.

Calculates estimated time of arrival based on:
  - Current bus position
  - Route destination coordinates
  - Recent GPS speed

This is an initial implementation designed to be extended later with:
  - Traffic data
  - Historical travel time
  - Stop-by-stop granularity
"""

import math


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance in kilometers between two points
    on Earth using the Haversine formula.
    """
    R = 6371.0  # Earth radius in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def calculate_eta(bus):
    """
    Estimate arrival time in minutes for the given bus.

    Returns:
        str: Human-readable ETA string, e.g. "~8 minutes" or "ETA unavailable"
    """
    # Need a route with a known destination
    if not bus.route:
        return 'ETA unavailable'

    dest_lat = bus.route.destination_latitude
    dest_lon = bus.route.destination_longitude
    if dest_lat is None or dest_lon is None:
        return 'ETA unavailable'

    # Need a recent location
    location = bus.latest_location
    if location is None:
        return 'ETA unavailable'

    distance_km = haversine_distance(
        location.latitude, location.longitude,
        dest_lat, dest_lon,
    )

    # Use current speed; fall back to a reasonable average of 30 km/h
    speed = location.speed if (location.speed and location.speed > 1) else 30.0

    if speed <= 0:
        return 'ETA unavailable'

    # Time in hours → minutes
    eta_minutes = (distance_km / speed) * 60

    if eta_minutes < 1:
        return 'Arriving now'
    elif eta_minutes > 120:
        return 'More than 2 hours away'
    else:
        return f'~{round(eta_minutes)} minutes'
