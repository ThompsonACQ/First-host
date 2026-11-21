"""
Admin registrations for the buses app.
"""
from django.contrib import admin
from .models import Bus, OccupancyLog


@admin.register(Bus)
class BusAdmin(admin.ModelAdmin):
    list_display = ['bus_number', 'registration_number', 'driver', 'route', 'occupied_seats', 'capacity', 'status', 'active']
    list_filter = ['status', 'active']
    search_fields = ['bus_number', 'registration_number']
    list_editable = ['active', 'status']


@admin.register(OccupancyLog)
class OccupancyLogAdmin(admin.ModelAdmin):
    list_display = ['bus', 'previous_occupied', 'occupied_seats', 'driver', 'recorded_at']
    list_filter = ['bus']
    readonly_fields = ['bus', 'driver', 'previous_occupied', 'occupied_seats', 'recorded_at']
