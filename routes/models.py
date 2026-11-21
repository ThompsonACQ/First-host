"""
Route and RouteStop models for the School Shuttle Tracking System.
"""

from django.db import models


class Route(models.Model):
    """
    Represents a shuttle bus route with a start and destination.
    Each route can have multiple ordered stops.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Start and end locations (human-readable names + coordinates)
    start_location = models.CharField(max_length=255)
    start_latitude = models.FloatField(null=True, blank=True)
    start_longitude = models.FloatField(null=True, blank=True)

    destination = models.CharField(max_length=255)
    destination_latitude = models.FloatField(null=True, blank=True)
    destination_longitude = models.FloatField(null=True, blank=True)

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Route'
        verbose_name_plural = 'Routes'
        ordering = ['name']

    def __str__(self):
        return f'{self.name}: {self.start_location} → {self.destination}'

    @property
    def stop_count(self):
        return self.stops.count()


class RouteStop(models.Model):
    """
    An ordered stop on a route.
    stop_order determines the sequence (1 = first stop after start).
    """
    route = models.ForeignKey(
        Route, on_delete=models.CASCADE, related_name='stops'
    )
    name = models.CharField(max_length=255)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    stop_order = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = 'Route Stop'
        verbose_name_plural = 'Route Stops'
        ordering = ['stop_order']
        unique_together = [['route', 'stop_order']]

    def __str__(self):
        return f'Stop {self.stop_order}: {self.name} ({self.route.name})'
