"""
Admin registrations for the routes app.
"""
from django.contrib import admin
from .models import Route, RouteStop


class RouteStopInline(admin.TabularInline):
    model = RouteStop
    extra = 1
    ordering = ['stop_order']


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_location', 'destination', 'active', 'stop_count']
    list_filter = ['active']
    search_fields = ['name', 'start_location', 'destination']
    inlines = [RouteStopInline]
