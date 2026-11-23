"""
Django Channels WebSocket consumer for real-time bus tracking.

Architecture:
  Driver browser → WebSocket → BusTrackingConsumer → saves Location
                                                    → broadcasts to bus group
                                                    → Student browsers update map
"""

import json
import logging
import math
from datetime import datetime

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Off-route detection helpers ────────────────────────────────────────────

OFF_ROUTE_THRESHOLD_M = 150  # metres — driver is considered off-route beyond this


def _haversine_m(lat1, lon1, lat2, lon2):
    """Return the great-circle distance in metres between two GPS points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_to_segment_distance_m(px, py, ax, ay, bx, by):
    """
    Minimum distance in metres from point P to the segment A→B.
    Coordinates are (latitude, longitude).
    Uses a simple projected-point approach that is accurate enough for short
    distances (≤ a few kilometres).
    """
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        # Segment is a single point
        return _haversine_m(px, py, ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nearest_x = ax + t * dx
    nearest_y = ay + t * dy
    return _haversine_m(px, py, nearest_x, nearest_y)


def _is_off_route(latitude, longitude, waypoints):
    """
    Return True if (latitude, longitude) is more than OFF_ROUTE_THRESHOLD_M
    metres away from every segment of the route polyline.

    `waypoints` is a list of (lat, lng) tuples in route order.
    Returns False (not off-route) when there are fewer than 2 waypoints —
    we can't define a route to check against.
    """
    if len(waypoints) < 2:
        return False
    min_dist = math.inf
    for i in range(len(waypoints) - 1):
        ax, ay = waypoints[i]
        bx, by = waypoints[i + 1]
        d = _point_to_segment_distance_m(latitude, longitude, ax, ay, bx, by)
        if d < min_dist:
            min_dist = d
    return min_dist > OFF_ROUTE_THRESHOLD_M


class BusTrackingConsumer(AsyncWebsocketConsumer):
    """
    Handles both driver (sends GPS) and student (receives updates) connections.

    Group naming: bus_<bus_id>
    All clients tracking bus 5 subscribe to group "bus_5".
    """

    async def _safe_channel_action(self, action, *args, **kwargs):
        """Keep database-backed GPS updates working if Redis is temporarily unavailable."""
        try:
            await action(*args, **kwargs)
            return True
        except Exception:
            logger.exception(
                'Redis channel operation failed for bus %s; continuing WebSocket processing.',
                self.bus_id,
            )
            return False

    async def connect(self):
        self.bus_id = self.scope['url_route']['kwargs']['bus_id']
        self.group_name = f'bus_{self.bus_id}'
        self.user = self.scope.get('user')

        # Join the bus-specific broadcast group
        await self._safe_channel_action(
            self.channel_layer.group_add,
            self.group_name,
            self.channel_name,
        )
        # This group is private to the logged-in driver.  Do not send SOS
        # responses through the public bus group, which students also join.
        self.driver_group_name = None
        if self.user and self.user.is_authenticated and self.user.is_driver:
            self.driver_group_name = f'driver_alerts_{self.user.pk}'
            await self._safe_channel_action(
                self.channel_layer.group_add,
                self.driver_group_name,
                self.channel_name,
            )
        await self.accept()

        # Send an initial connection acknowledgement
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'bus_id': self.bus_id,
            'message': 'Connected to live tracking',
        }))
        logger.info(
            'WebSocket connected: user=%s bus=%s',
            getattr(self.user, 'username', 'anonymous'),
            self.bus_id,
        )

    async def disconnect(self, close_code):
        await self._safe_channel_action(
            self.channel_layer.group_discard,
            self.group_name,
            self.channel_name,
        )
        if self.driver_group_name:
            await self._safe_channel_action(
                self.channel_layer.group_discard,
                self.driver_group_name,
                self.channel_name,
            )
        logger.info(
            'WebSocket disconnected: bus=%s code=%s',
            self.bus_id, close_code,
        )

    async def receive(self, text_data):
        """
        Called when a message arrives from the WebSocket client.
        Only drivers should send location data.
        """
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON',
            }))
            return

        message_type = data.get('type')

        if message_type == 'location_update':
            await self.handle_location_update(data)
        elif message_type == 'stop_sharing':
            await self.handle_stop_sharing(data)
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Unknown message type: {message_type}',
            }))

    # ------------------------------------------------------------------
    # Location update from driver
    # ------------------------------------------------------------------

    async def handle_location_update(self, data):
        """Validate, save, and broadcast a driver's GPS location."""
        # Must be authenticated
        if not self.user or not self.user.is_authenticated:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Authentication required',
            }))
            return

        # Extract fields
        try:
            latitude = float(data['latitude'])
            longitude = float(data['longitude'])
            speed = float(data.get('speed') or 0)
            heading = data.get('heading')
            accuracy = data.get('accuracy')
        except (KeyError, ValueError, TypeError):
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid location data',
            }))
            return

        # Validate latitude/longitude ranges
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Coordinates out of valid range',
            }))
            return

        # Save and broadcast
        result = await self.save_location(
            latitude, longitude, speed, heading, accuracy
        )
        if result is None:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'You are not authorized to update this bus',
            }))
            return

        bus_data, eta = result

        # Broadcast to all clients in the bus group
        broadcast_saved = await self._safe_channel_action(
            self.channel_layer.group_send,
            self.group_name,
            {
                'type': 'broadcast_location',
                'bus_id': self.bus_id,
                'latitude': latitude,
                'longitude': longitude,
                'speed': speed,
                'heading': heading,
                'status': bus_data['status'],
                'last_update': bus_data['last_update'],
                'eta': eta,
                'driver_name': bus_data['driver_name'],
                'bus_number': bus_data['bus_number'],
                'route_name': bus_data['route_name'],
                'off_route': bus_data['off_route'],
            }
        )
        if not broadcast_saved:
            await self.send(text_data=json.dumps({
                'type': 'warning',
                'message': 'Location saved, but live broadcast is temporarily unavailable.',
            }))

    async def handle_stop_sharing(self, data):
        """Driver stopped sharing — mark bus as stopped and notify."""
        if not self.user or not self.user.is_authenticated:
            return

        bus_data = await self.mark_bus_stopped()
        if bus_data:
            await self._safe_channel_action(
                self.channel_layer.group_send,
                self.group_name,
                {
                    'type': 'broadcast_location',
                    'bus_id': self.bus_id,
                    'status': 'stopped',
                    'last_update': datetime.now().isoformat(),
                    'eta': 'ETA unavailable',
                    'bus_number': bus_data.get('bus_number', ''),
                    'driver_name': bus_data.get('driver_name', ''),
                    'route_name': bus_data.get('route_name', ''),
                    'latitude': None,
                    'longitude': None,
                    'speed': 0,
                    'heading': None,
                }
            )

    # ------------------------------------------------------------------
    # Channel layer event handlers (called when group_send fires)
    # ------------------------------------------------------------------

    async def broadcast_location(self, event):
        """Forward a group-broadcast message to this WebSocket client."""
        await self.send(text_data=json.dumps({
            'type': 'location_update',
            **{k: v for k, v in event.items() if k != 'type'},
        }))

    async def broadcast_occupancy(self, event):
        """Forward a driver seat-count update to students tracking this bus."""
        await self.send(text_data=json.dumps({
            'type': 'occupancy_update',
            **{k: v for k, v in event.items() if k != 'type'},
        }))

    async def broadcast_status(self, event):
        """Forward a sharing-status change without discarding last location."""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            **{k: v for k, v in event.items() if k != 'type'},
        }))

    async def emergency_response(self, event):
        """Forward a private administrator response to the driver."""
        await self.send(text_data=json.dumps({
            'type': 'emergency_response',
            **{k: v for k, v in event.items() if k != 'type'},
        }))

    async def emergency_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'emergency_message',
            **{k: v for k, v in event.items() if k != 'type'},
        }))

    # ------------------------------------------------------------------
    # Database helpers (sync → async via database_sync_to_async)
    # ------------------------------------------------------------------

    @database_sync_to_async
    def save_location(self, latitude, longitude, speed, heading, accuracy):
        """
        1. Verify driver is authorized for this bus.
        2. Save Location record.
        3. Update bus status.
        4. Calculate ETA.
        Returns (bus_info_dict, eta_str) or None if unauthorized.
        """
        from buses.models import Bus
        from .models import Location
        from .eta import calculate_eta

        try:
            bus = Bus.objects.get(pk=self.bus_id, active=True)
        except Bus.DoesNotExist:
            return None

        # Security: driver can only update their own assigned bus
        if not (self.user.is_admin or self.user.is_superuser):
            if bus.driver_id != self.user.id:
                return None

        # Determine status from speed
        if speed > 2:
            new_status = Bus.STATUS_MOVING
        else:
            new_status = Bus.STATUS_STOPPED

        # Save location record
        Location.objects.create(
            bus=bus,
            latitude=latitude,
            longitude=longitude,
            speed=speed,
            heading=heading,
            accuracy=accuracy,
            timestamp=timezone.now(),
        )
        location = Location.objects.filter(bus=bus).order_by('-timestamp').first()
        from .safety import update_trip_for_location
        update_trip_for_location(bus, self.user, location)

        # Update bus status
        bus.status = new_status
        bus.save(update_fields=['status', 'updated_at'])

        eta = calculate_eta(bus)

        # ── Off-route detection ────────────────────────────────────────────
        # Build ordered waypoints from the bus route (start → stops → end)
        off_route = False
        if bus.route:
            waypoints = []
            route = bus.route
            if route.start_latitude and route.start_longitude:
                waypoints.append((route.start_latitude, route.start_longitude))
            for stop in route.stops.order_by('stop_order'):
                if stop.latitude and stop.longitude:
                    waypoints.append((stop.latitude, stop.longitude))
            if route.destination_latitude and route.destination_longitude:
                waypoints.append((route.destination_latitude, route.destination_longitude))
            off_route = _is_off_route(latitude, longitude, waypoints)

        return (
            {
                'status': new_status,
                'last_update': timezone.now().isoformat(),
                'driver_name': bus.driver_name,
                'bus_number': bus.bus_number,
                'route_name': bus.route_name,
                'off_route': off_route,
            },
            eta,
        )

    @database_sync_to_async
    def mark_bus_stopped(self):
        """Mark the bus as stopped/offline when driver stops sharing."""
        from buses.models import Bus

        try:
            bus = Bus.objects.get(pk=self.bus_id, active=True)
        except Bus.DoesNotExist:
            return None

        if not (self.user.is_admin or self.user.is_superuser):
            if bus.driver_id != self.user.id:
                return None

        bus.status = Bus.STATUS_STOPPED
        bus.save(update_fields=['status', 'updated_at'])

        from .safety import finish_active_trip
        finish_active_trip(bus, self.user)

        return {
            'bus_number': bus.bus_number,
            'driver_name': bus.driver_name,
            'route_name': bus.route_name,
        }


class AdminAlertConsumer(AsyncWebsocketConsumer):
    """Authenticated admin-only feed for urgent SOS notifications."""
    group_name = 'admin_alerts'

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated or not (user.is_admin or user.is_superuser):
            await self.close(code=4403)
            return
        try:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
        except Exception:
            logger.exception('Redis unavailable while connecting to the admin alert channel.')
        await self.accept()

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            logger.exception('Redis unavailable while disconnecting from the admin alert channel.')

    async def emergency_alert(self, event):
        await self.send(text_data=json.dumps({
            'type': 'emergency_alert',
            **{key: value for key, value in event.items() if key != 'type'},
        }))

    async def emergency_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'emergency_message',
            **{key: value for key, value in event.items() if key != 'type'},
        }))
