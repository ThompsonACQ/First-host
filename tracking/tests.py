from datetime import timedelta
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from buses.models import Bus
from routes.models import Route, RouteStop
from school_settings.views import home
from .models import Location


class PublicRouteSearchTests(TestCase):
    def setUp(self):
        self.route = Route.objects.create(
            name='North Campus',
            start_location='Main Gate',
            destination='Science Block',
        )
        RouteStop.objects.create(
            route=self.route,
            name='Library',
            stop_order=1,
        )

    def test_homepage_uses_active_route_stops_for_pickup_choices(self):
        Route.objects.create(
            name='Inactive route',
            start_location='Closed Gate',
            destination='Old Hall',
            active=False,
        )

        with patch('school_settings.views.render', return_value=HttpResponse()) as render_page:
            response = home(RequestFactory().get('/'))

        self.assertEqual(response.status_code, 200)
        template_name, context = render_page.call_args.args[1:]
        self.assertEqual(template_name, 'home.html')
        self.assertEqual(context['route_locations'], [
            'Library', 'Main Gate', 'Science Block',
        ])

    def test_search_returns_matching_route_stops_and_assigned_bus_data(self):
        bus = Bus.objects.create(
            bus_number='BUS-12',
            registration_number='TEST-12',
            route=self.route,
            status=Bus.STATUS_MOVING,
            capacity=40,
            occupied_seats=7,
        )
        Location.objects.create(
            bus=bus,
            latitude=5.6500,
            longitude=-0.1900,
            timestamp=timezone.now(),
        )

        response = self.client.get(
            reverse('route_search_api'),
            {'pickup': 'Library', 'destination': 'Science Block'},
        )

        self.assertEqual(response.status_code, 200)
        route = response.json()['routes'][0]
        self.assertEqual(route['name'], 'North Campus')
        self.assertEqual(route['stops'], ['Library', 'Science Block'])
        self.assertEqual(len(route['buses']), 1)
        self.assertEqual(route['buses'][0]['bus_number'], 'BUS-12')
        self.assertEqual(route['buses'][0]['available_seats'], 33)
        self.assertEqual(route['buses'][0]['gps_status'], 'Live GPS')
        self.assertEqual(route['buses'][0]['track_url'], '/tracking/{}/'.format(bus.pk))

    def test_search_does_not_match_a_route_in_the_wrong_direction(self):
        response = self.client.get(
            reverse('route_search_api'),
            {'pickup': 'Science Block', 'destination': 'Main Gate'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['routes'], [])

    def test_search_formats_stale_location_age_in_days(self):
        bus = Bus.objects.create(
            bus_number='BUS-13',
            registration_number='TEST-13',
            route=self.route,
        )
        Location.objects.create(
            bus=bus,
            latitude=5.6500,
            longitude=-0.1900,
            timestamp=timezone.now() - timedelta(days=2),
        )

        response = self.client.get(
            reverse('route_search_api'),
            {'pickup': 'Main Gate', 'destination': 'Science Block'},
        )

        self.assertEqual(response.json()['routes'][0]['buses'][0]['gps_status'], 'Last location 2 days ago')

    def test_search_rejects_missing_or_identical_stops(self):
        url = reverse('route_search_api')

        self.assertEqual(self.client.get(url).status_code, 400)
        self.assertEqual(
            self.client.get(url, {'pickup': 'Library', 'destination': 'library'}).status_code,
            400,
        )
