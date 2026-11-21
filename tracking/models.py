"""
Location model — stores the full GPS history for every bus.

Each record is immutable (never updated). New records are always appended
so that administrators can analyze historical trip data.
"""

from django.db import models
from django.utils import timezone
from django.conf import settings


class Location(models.Model):
    """
    A single GPS fix for a bus at a point in time.
    Records are NEVER overwritten — always inserted.
    """
    bus = models.ForeignKey(
        'buses.Bus',
        on_delete=models.CASCADE,
        related_name='locations',
    )
    latitude = models.FloatField()
    longitude = models.FloatField()

    # Speed in km/h (nullable — not all GPS devices report speed)
    speed = models.FloatField(null=True, blank=True)

    # Heading in degrees 0-360 (optional, used for map marker rotation)
    heading = models.FloatField(null=True, blank=True)

    # Accuracy in meters (optional)
    accuracy = models.FloatField(null=True, blank=True)

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'Location'
        verbose_name_plural = 'Locations'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['bus', '-timestamp']),
        ]

    def __str__(self):
        return (
            f'Bus {self.bus.bus_number} @ '
            f'{self.latitude:.4f},{self.longitude:.4f} '
            f'[{self.timestamp.strftime("%Y-%m-%d %H:%M:%S")}]'
        )

    @property
    def speed_display(self):
        if self.speed is not None:
            return f'{self.speed:.1f} km/h'
        return 'N/A'


class Trip(models.Model):
    """A GPS-sharing session and its server-calculated safety summary."""
    bus = models.ForeignKey('buses.Bus', on_delete=models.CASCADE, related_name='safety_trips')
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='safety_trips')
    route = models.ForeignKey('routes.Route', on_delete=models.SET_NULL, null=True, blank=True, related_name='safety_trips')
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    point_count = models.PositiveIntegerField(default=0)
    on_route_points = models.PositiveIntegerField(default=0)
    speed_points = models.PositiveIntegerField(default=0)
    speeding_events = models.PositiveIntegerField(default=0)
    hard_braking_events = models.PositiveIntegerField(default=0)
    unnecessary_stops = models.PositiveIntegerField(default=0)
    stop_started_at = models.DateTimeField(null=True, blank=True)
    unnecessary_stop_recorded = models.BooleanField(default=False)
    completed = models.BooleanField(default=False)
    safety_score = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    @property
    def route_adherence(self):
        return round(100 * self.on_route_points / self.point_count) if self.point_count else 0

    @property
    def speed_compliance(self):
        return round(100 * (self.speed_points - self.speeding_events) / self.speed_points) if self.speed_points else 100

    @property
    def driving_seconds(self):
        end = self.ended_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds()))

    def __str__(self):
        return f'{self.bus} trip started {self.started_at:%Y-%m-%d %H:%M}'


class EmergencyAlert(models.Model):
    """SOS raised by a driver; an admin must acknowledge it explicitly."""
    STATUS_ACTIVE = 'active'
    STATUS_ACKNOWLEDGED = 'acknowledged'
    STATUS_CHOICES = [(STATUS_ACTIVE, 'Active'), (STATUS_ACKNOWLEDGED, 'Acknowledged')]
    TYPE_ACCIDENT = 'accident'
    TYPE_MECHANICAL = 'mechanical'
    TYPE_SECURITY = 'security'
    TYPE_MEDICAL = 'medical'
    TYPE_CHOICES = [
        (TYPE_ACCIDENT, 'Accident'),
        (TYPE_MECHANICAL, 'Mechanical problem'),
        (TYPE_SECURITY, 'Security issue'),
        (TYPE_MEDICAL, 'Medical emergency'),
    ]

    bus = models.ForeignKey('buses.Bus', on_delete=models.CASCADE, related_name='emergency_alerts')
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='emergency_alerts')
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, null=True, blank=True, related_name='emergency_alerts')
    emergency_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_ACCIDENT)
    route_name = models.CharField(max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='acknowledged_emergencies')
    admin_message = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'SOS: {self.bus} at {self.created_at:%Y-%m-%d %H:%M}'


class EmergencyMessage(models.Model):
    """An auditable message exchanged about a specific SOS alert."""
    alert = models.ForeignKey(EmergencyAlert, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='sent_emergency_messages')
    body = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Message for SOS {self.alert_id} at {self.created_at:%Y-%m-%d %H:%M}'
