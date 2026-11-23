"""
Routes views — admin CRUD for routes and stops.
"""
import hashlib
import json
import logging
import math
import threading
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET

from .models import Route, RouteStop
from accounts.decorators import admin_required

logger = logging.getLogger(__name__)
NOMINATIM_URL = 'https://nominatim.openstreetmap.org'
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
_nominatim_lock = threading.Lock()
_last_nominatim_request = 0.0
_overpass_lock = threading.Lock()
_last_overpass_request = 0.0


class RouteForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = [
            'name', 'description',
            'start_location', 'start_latitude', 'start_longitude',
            'destination', 'destination_latitude', 'destination_longitude',
            'active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }


class RouteStopForm(forms.ModelForm):
    """
    Custom form for each stop row.
    A row is treated as empty (silently skipped) when 'name' is blank,
    so extra unused rows never cause unique_together validation errors.
    """
    class Meta:
        model = RouteStop
        fields = ['name', 'latitude', 'longitude', 'stop_order']

    def has_changed(self):
        # If name is blank, treat the whole row as unchanged so Django skips it.
        name_value = self.data.get(self.add_prefix('name'), '').strip()
        if not name_value:
            return False
        return super().has_changed()


RouteStopFormSet = inlineformset_factory(
    Route, RouteStop,
    form=RouteStopForm,
    fields=['name', 'latitude', 'longitude', 'stop_order'],
    extra=1,          # Only 1 blank extra row to reduce clutter
    can_delete=True,
)


@admin_required
@require_GET
def route_geocode(request):
    """Proxy route-editor place lookups through a policy-compliant Nominatim client."""
    query = request.GET.get('q', '').strip()
    latitude = request.GET.get('lat', '').strip()
    longitude = request.GET.get('lon', '').strip()
    if query:
        if len(query) > 200:
            return JsonResponse({'detail': 'Search text must be 200 characters or fewer.'}, status=400)
        params = {'q': query, 'format': 'jsonv2', 'limit': 5, 'addressdetails': 1}
        cache_key = 'route-geocode-search-' + hashlib.sha256(query.casefold().encode('utf-8')).hexdigest()
        endpoint = '/search'
        cache_timeout = 60 * 60
    elif latitude and longitude:
        try:
            lat = float(latitude)
            lon = float(longitude)
        except ValueError:
            return JsonResponse({'detail': 'Valid latitude and longitude are required.'}, status=400)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return JsonResponse({'detail': 'Coordinates are out of range.'}, status=400)
        params = {
            'lat': '{:.6f}'.format(lat),
            'lon': '{:.6f}'.format(lon),
            'format': 'jsonv2',
            'zoom': 18,
            'addressdetails': 1,
        }
        cache_key = 'route-geocode-reverse-' + hashlib.sha256(
            '{}:{}'.format(params['lat'], params['lon']).encode('ascii')
        ).hexdigest()
        endpoint = '/reverse'
        cache_timeout = 24 * 60 * 60
    else:
        return JsonResponse({'detail': 'Enter a place name or map coordinates.'}, status=400)

    try:
        cached_result = cache.get(cache_key)
    except Exception:
        logger.exception('Could not read the Nominatim result cache.')
        cached_result = None
    if cached_result is not None:
        return JsonResponse(cached_result, safe=not isinstance(cached_result, list))

    global _last_nominatim_request
    try:
        if not cache.add('nominatim-last-request', time.time(), timeout=1):
            return JsonResponse(
                {'detail': 'Please wait a moment before searching the map again.'},
                status=429,
                headers={'Retry-After': '1'},
            )
    except Exception:
        logger.exception('Could not access cache while rate-limiting Nominatim requests.')
        with _nominatim_lock:
            elapsed = time.monotonic() - _last_nominatim_request
            if elapsed < 1:
                return JsonResponse(
                    {'detail': 'Please wait a moment before searching the map again.'},
                    status=429,
                    headers={'Retry-After': '1'},
                )
            _last_nominatim_request = time.monotonic()

    hostname = getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', '') or 'localhost'
    user_agent = getattr(
        settings,
        'NOMINATIM_USER_AGENT',
        'CampusShuttleTracker/1.0 (+https://{})'.format(hostname),
    )
    request_url = '{}{}?{}'.format(NOMINATIM_URL, endpoint, urlencode(params))
    try:
        geocode_request = Request(
            request_url,
            headers={
                'User-Agent': user_agent,
                'Accept': 'application/json',
                'Accept-Language': 'en',
            },
        )
        with urlopen(geocode_request, timeout=8) as response:
            result = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, HTTPException, TimeoutError, OSError, ValueError):
        logger.exception('Nominatim lookup failed for the route editor.')
        return JsonResponse(
            {'detail': 'Place search is temporarily unavailable. Please try again.'},
            status=503,
        )

    if endpoint == '/reverse':
        if not result.get('display_name'):
            result = {}
        else:
            result = {
                'display_name': result['display_name'],
                'name': result.get('name') or result['display_name'].split(',')[0],
                'lat': result.get('lat', params['lat']),
                'lon': result.get('lon', params['lon']),
            }
    else:
        result = [
            {
                'display_name': item.get('display_name', ''),
                'name': item.get('name') or item.get('display_name', '').split(',')[0],
                'lat': item.get('lat'),
                'lon': item.get('lon'),
            }
            for item in result
            if item.get('lat') and item.get('lon')
        ]
    try:
        cache.set(cache_key, result, cache_timeout)
    except Exception:
        logger.exception('Could not cache Nominatim lookup result.')
    return JsonResponse(result, safe=not isinstance(result, list))


@admin_required
@require_GET
def route_landmarks_api(request):
    """Return cached, named OpenStreetMap features around the route editor map."""
    try:
        south, west, north, east = (
            float(request.GET[key]) for key in ('south', 'west', 'north', 'east')
        )
        zoom = int(request.GET.get('zoom', '0'))
    except (KeyError, TypeError, ValueError):
        return JsonResponse({'detail': 'Valid map bounds and zoom are required.'}, status=400)

    if not (
        -90 <= south < north <= 90
        and -180 <= west < east <= 180
        and 0 <= zoom <= 22
    ):
        return JsonResponse({'detail': 'Map bounds are out of range.'}, status=400)
    if zoom < 12:
        return JsonResponse({'features': []})

    center_lat = (south + north) / 2
    center_lon = (west + east) / 2
    max_span = {12: 0.12, 13: 0.07, 14: 0.045, 15: 0.03}.get(zoom, 0.02)
    lat_span = min(north - south, max_span)
    lon_span = min(
        east - west,
        max_span / max(0.2, abs(math.cos(math.radians(center_lat)))),
    )
    south = max(-90, center_lat - lat_span / 2)
    north = min(90, center_lat + lat_span / 2)
    west = max(-180, center_lon - lon_span / 2)
    east = min(180, center_lon + lon_span / 2)
    bbox = '{:.5f},{:.5f},{:.5f},{:.5f}'.format(south, west, north, east)
    cache_key = 'route-landmarks-' + hashlib.sha256(
        '{}:{}'.format(zoom, bbox).encode('ascii')
    ).hexdigest()

    try:
        cached_result = cache.get(cache_key)
    except Exception:
        logger.exception('Could not read the OSM landmark cache.')
        cached_result = None
    if cached_result is not None:
        return JsonResponse({'features': cached_result})

    global _last_overpass_request
    try:
        if not cache.add('overpass-last-request', time.time(), timeout=2):
            return JsonResponse(
                {'detail': 'Nearby-place search is cooling down. Please try again shortly.'},
                status=429,
                headers={'Retry-After': '2'},
            )
    except Exception:
        logger.exception('Could not access cache while rate-limiting Overpass requests.')
        with _overpass_lock:
            elapsed = time.monotonic() - _last_overpass_request
            if elapsed < 2:
                return JsonResponse(
                    {'detail': 'Nearby-place search is cooling down. Please try again shortly.'},
                    status=429,
                    headers={'Retry-After': '2'},
                )
            _last_overpass_request = time.monotonic()

    query = (
        '[out:json][timeout:15];('
        'nwr["name"]["amenity"~"^(university|college|school|hospital|clinic|place_of_worship|restaurant|fast_food|cafe|fuel|bus_station|marketplace|pharmacy|library|community_centre|bank|post_office|police|fire_station)$"]({bbox});'
        'nwr["name"]["shop"]({bbox});'
        'nwr["name"]["tourism"~"^(hotel|guest_house|attraction|museum)$"]({bbox});'
        'nwr["name"]["building"]({bbox});'
        'nwr["name"]["highway"~"^(bus_stop|platform)$"]({bbox});'
        'nwr["name"]["public_transport"~"^(platform|station)$"]({bbox});'
        'nwr["name"]["place"~"^(city|town|suburb|village|neighbourhood|hamlet)$"]({bbox});'
        ');out center tags 150;'
    ).format(bbox=bbox)
    hostname = getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', '') or 'localhost'
    user_agent = getattr(
        settings,
        'NOMINATIM_USER_AGENT',
        'CampusShuttleTracker/1.0 (+https://{})'.format(hostname),
    )
    overpass_request = Request(
        OVERPASS_URL,
        data=urlencode({'data': query}).encode('ascii'),
        headers={
            'User-Agent': user_agent,
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    try:
        with urlopen(overpass_request, timeout=20) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, HTTPException, TimeoutError, OSError, ValueError):
        logger.exception('OpenStreetMap Overpass lookup failed for the route editor.')
        return JsonResponse(
            {'detail': 'Nearby map places are temporarily unavailable. The map and route fields still work.'},
            status=503,
        )
    if not isinstance(payload, dict) or not isinstance(payload.get('elements'), list):
        logger.error('OpenStreetMap Overpass returned an unexpected response shape.')
        return JsonResponse(
            {'detail': 'Nearby map places are temporarily unavailable. The map and route fields still work.'},
            status=503,
        )

    def category_for(tags):
        amenity = tags.get('amenity', '').replace('_', ' ').title()
        if amenity:
            return amenity
        if tags.get('shop'):
            return tags['shop'].replace('_', ' ').title()
        tourism = tags.get('tourism', '')
        if tourism:
            return tourism.replace('_', ' ').title()
        if tags.get('highway') == 'bus_stop' or tags.get('public_transport') in ('platform', 'station'):
            return 'Bus stop or station'
        if tags.get('place'):
            return tags['place'].replace('_', ' ').title()
        if tags.get('building'):
            return 'Building'
        return 'Place'

    features = []
    for element in payload.get('elements', []):
        if not isinstance(element, dict):
            continue
        tags = element.get('tags', {})
        if not isinstance(tags, dict):
            continue
        name = tags.get('name', '').strip()
        point = element if 'lat' in element and 'lon' in element else element.get('center', {})
        if not name or 'lat' not in point or 'lon' not in point:
            continue
        address = tags.get('addr:full', '')
        if not address:
            address = ', '.join(
                value for value in (
                    ' '.join(filter(None, (tags.get('addr:housenumber'), tags.get('addr:street')))),
                    tags.get('addr:suburb') or tags.get('addr:neighbourhood'),
                    tags.get('addr:city') or tags.get('addr:town') or tags.get('addr:village'),
                )
                if value
            )
        features.append({
            'id': '{}-{}'.format(element.get('type', 'feature'), element.get('id', '')),
            'name': name,
            'category': category_for(tags),
            'address': address,
            'lat': point['lat'],
            'lon': point['lon'],
        })
    try:
        cache.set(cache_key, features, 15 * 60)
    except Exception:
        logger.exception('Could not cache OpenStreetMap landmarks.')
    return JsonResponse({'features': features})


@admin_required
def route_list(request):
    routes = Route.objects.prefetch_related('stops').order_by('name')
    return render(request, 'routes/route_list.html', {'routes': routes})


@admin_required
def route_create(request):
    if request.method == 'POST':
        form = RouteForm(request.POST)
        formset = RouteStopFormSet(request.POST, prefix='stops')
        if form.is_valid() and formset.is_valid():
            route = form.save()
            formset.instance = route
            formset.save()
            messages.success(request, f'Route "{route.name}" created.')
            return redirect('routes:route_list')
        else:
            # Surface errors as flash messages so admin can see what went wrong
            if not form.is_valid():
                messages.error(request, f'Route form errors: {form.errors.as_text()}')
            if not formset.is_valid():
                for i, err in enumerate(formset.errors):
                    if err:
                        messages.error(request, f'Stop row {i + 1} errors: {err}')
                nfe = formset.non_form_errors()
                if nfe:
                    messages.error(request, f'Stops error: {nfe}')
    else:
        form = RouteForm()
        formset = RouteStopFormSet(prefix='stops')
    return render(request, 'routes/route_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Add Route',
    })


@admin_required
def route_edit(request, pk):
    route = get_object_or_404(Route, pk=pk)
    if request.method == 'POST':
        form = RouteForm(request.POST, instance=route)
        formset = RouteStopFormSet(request.POST, instance=route, prefix='stops')
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f'Route "{route.name}" updated.')
            return redirect('routes:route_list')
        else:
            if not form.is_valid():
                messages.error(request, f'Route form errors: {form.errors.as_text()}')
            if not formset.is_valid():
                for i, err in enumerate(formset.errors):
                    if err:
                        messages.error(request, f'Stop row {i + 1} errors: {err}')
                nfe = formset.non_form_errors()
                if nfe:
                    messages.error(request, f'Stops error: {nfe}')
    else:
        form = RouteForm(instance=route)
        formset = RouteStopFormSet(instance=route, prefix='stops')
    return render(request, 'routes/route_form.html', {
        'form': form,
        'formset': formset,
        'title': f'Edit Route: {route.name}',
        'route': route,
    })


@admin_required
def route_toggle_active(request, pk):
    route = get_object_or_404(Route, pk=pk)
    route.active = not route.active
    route.save(update_fields=['active'])
    status = 'activated' if route.active else 'deactivated'
    messages.success(request, f'Route "{route.name}" {status}.')
    return redirect('routes:route_list')


@admin_required
def route_delete(request, pk):
    route = get_object_or_404(Route, pk=pk)
    if request.method == 'POST':
        name = route.name
        route.delete()
        messages.success(request, f'Route "{name}" deleted.')
        return redirect('routes:route_list')
    return render(request, 'routes/route_confirm_delete.html', {'route': route})
