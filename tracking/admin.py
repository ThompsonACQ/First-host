"""
Admin registrations for the tracking app.
"""
from django.contrib import admin
from .models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ['bus', 'latitude', 'longitude', 'speed', 'timestamp']
    list_filter = ['bus']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']
