import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from .models import Route, RouteStop


class RouteMapPickerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            username='map-admin',
            email='map-admin@example.com',
            password='test-password',
        )
        self.client.force_login(self.admin)

    def test_map_geocoding_returns_place_coordinates_and_uses_identifying_user_agent(self):
        body = json.dumps([{
            'display_name': 'University of Ghana, Accra, Ghana',
            'name': 'University of Ghana',
            'lat': '5.6500',
            'lon': '-0.1900',
        }]).encode('utf-8')
        response_context = patch(
            'routes.views.urlopen',
            return_value=type('Response', (), {
                '__enter__': lambda self: self,
                '__exit__': lambda self, *args: None,
                'read': lambda self: body,
            })(),
        )

        with response_context as open_url:
            response = self.client.get(reverse('routes:geocode'), {'q': 'University of Ghana'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['lat'], '5.6500')
        request = open_url.call_args.args[0]
        self.assertIn('CampusShuttleTracker', request.get_header('User-agent'))
        self.assertIn('nominatim.openstreetmap.org/search', request.full_url)

    def test_reverse_geocoding_validates_coordinates(self):
        response = self.client.get(
            reverse('routes:geocode'),
            {'lat': '91', 'lon': '0'},
        )

        self.assertEqual(response.status_code, 400)

    def test_landmark_lookup_returns_real_named_places_with_details_and_caches_results(self):
        body = json.dumps({
            'elements': [
                {
                    'type': 'way',
                    'id': 42,
                    'center': {'lat': 5.6501, 'lon': -0.1902},
                    'tags': {
                        'name': 'GCTU Library',
                        'amenity': 'university',
                        'addr:street': 'University Avenue',
                        'addr:city': 'Accra',
                    },
                },
                {
                    'type': 'node',
                    'id': 43,
                    'lat': 5.651,
                    'lon': -0.191,
                    'tags': {'amenity': 'restaurant'},
                },
            ],
        }).encode('utf-8')
        response_context = patch(
            'routes.views.urlopen',
            return_value=type('Response', (), {
                '__enter__': lambda self: self,
                '__exit__': lambda self, *args: None,
                'read': lambda self: body,
            })(),
        )
        bounds = {'south': '5.64', 'west': '-0.20', 'north': '5.66', 'east': '-0.18', 'zoom': '16'}

        with response_context as open_url:
            response = self.client.get(reverse('routes:landmarks'), bounds)
            cached_response = self.client.get(reverse('routes:landmarks'), bounds)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['features'], [{
            'id': 'way-42',
            'name': 'GCTU Library',
            'category': 'University',
            'address': 'University Avenue, Accra',
            'lat': 5.6501,
            'lon': -0.1902,
        }])
        self.assertEqual(cached_response.json(), response.json())
        self.assertEqual(open_url.call_count, 1)
        self.assertIn('overpass-api.de/api/interpreter', open_url.call_args.args[0].full_url)

    def test_landmark_lookup_rejects_invalid_bounds_and_skips_broad_zoom(self):
        invalid = self.client.get(reverse('routes:landmarks'), {
            'south': '5', 'west': '-1', 'north': '4', 'east': '0', 'zoom': '15',
        })
        broad = self.client.get(reverse('routes:landmarks'), {
            'south': '4', 'west': '-2', 'north': '6', 'east': '0', 'zoom': '10',
        })

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(broad.status_code, 200)
        self.assertEqual(broad.json(), {'features': []})

    def test_admin_can_save_multiple_pickup_stops_and_exact_coordinates(self):
        response = self.client.post(reverse('routes:route_create'), {
            'name': 'Campus Loop',
            'description': '',
            'start_location': 'Main Gate',
            'start_latitude': '5.600001',
            'start_longitude': '-0.180001',
            'destination': 'Library',
            'destination_latitude': '5.610002',
            'destination_longitude': '-0.190002',
            'active': 'on',
            'stops-TOTAL_FORMS': '2',
            'stops-INITIAL_FORMS': '0',
            'stops-MIN_NUM_FORMS': '0',
            'stops-MAX_NUM_FORMS': '1000',
            'stops-0-name': 'Science Block',
            'stops-0-latitude': '5.605123',
            'stops-0-longitude': '-0.185456',
            'stops-0-stop_order': '1',
            'stops-1-name': 'Sports Complex',
            'stops-1-latitude': '5.607654',
            'stops-1-longitude': '-0.187321',
            'stops-1-stop_order': '2',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('routes:route_list'))
        route = Route.objects.get(name='Campus Loop')
        self.assertEqual(route.start_latitude, 5.600001)
        self.assertEqual(route.destination_longitude, -0.190002)
        stops = list(route.stops.order_by('stop_order'))
        self.assertEqual([stop.name for stop in stops], ['Science Block', 'Sports Complex'])
        self.assertEqual(stops[1].longitude, -0.187321)

    def test_route_form_uses_openstreetmap_tiles_and_has_mobile_friendly_search(self):
        template = get_template('routes/route_form.html')
        with patch('routes.views.render', return_value=HttpResponse()) as render_form:
            response = self.client.get(reverse('routes:route_create'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(template)
        self.assertEqual(render_form.call_args.args[1], 'routes/route_form.html')
        self.assertIn('data-landmarks-url', template.template.source)
        self.assertIn('Use as pickup', template.template.source)
        self.assertIn('Use as destination', template.template.source)
