"""
Bus model for the School Shuttle Tracking System.
"""

from django.db import models
from django.conf import settings


class Bus(models.Model):
    """
    Represents a physical school bus.
    Each bus can have one driver and one active route.
    """

    STATUS_MOVING = 'moving'
    STATUS_STOPPED = 'stopped'
    STATUS_OFFLINE = 'offline'

    STATUS_CHOICES = [
        (STATUS_MOVING, 'Moving'),
        (STATUS_STOPPED, 'Stopped'),
        (STATUS_OFFLINE, 'Offline'),
    ]

    bus_number = models.CharField(max_length=50, unique=True)
    registration_number = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    # Driver — nullable so a bus can exist without an assigned driver
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'driver'},
        related_name='driven_buses',
    )

    # Route — nullable so a bus can exist without an assigned route
    route = models.ForeignKey(
        'routes.Route',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='buses',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OFFLINE,
    )
    active = models.BooleanField(default=True)

    capacity = models.PositiveIntegerField(default=50)
    occupied_seats = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bus'
        verbose_name_plural = 'Buses'
        ordering = ['bus_number']

    def __str__(self):
        return f'Bus {self.bus_number} ({self.status})'

    @property
    def latest_location(self):
        """Return the most recent Location record for this bus, or None."""
        return self.locations.order_by('-timestamp').first()

    @property
    def driver_name(self):
        if self.driver:
            return self.driver.get_full_name() or self.driver.username
        return 'No driver assigned'

    @property
    def route_name(self):
        return self.route.name if self.route else 'No route assigned'

    @property
    def available_seats(self):
        return max(0, self.capacity - self.occupied_seats)


class OccupancyLog(models.Model):
    """Immutable record of a driver's passenger-count update."""
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='occupancy_logs')
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='occupancy_updates')
    previous_occupied = models.PositiveIntegerField()
    occupied_seats = models.PositiveIntegerField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f'{self.bus.bus_number}: {self.previous_occupied} → {self.occupied_seats}'
