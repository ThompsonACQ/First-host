from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from PIL import Image, ImageDraw

from .branding import extract_colors_from_logo
from .context_processors import school_settings_processor
from .models import SchoolSettings


class LogoColorExtractionTests(SimpleTestCase):
    def test_extracts_all_exact_logo_colors_and_ignores_white_background(self):
        image = Image.new('RGBA', (120, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 68, 72), fill='#c8102e')
        draw.rectangle((72, 8, 94, 72), fill='#f4c542')
        draw.rectangle((98, 8, 118, 72), fill='#2e3192')
        logo = BytesIO()
        image.save(logo, format='PNG')
        logo.seek(0)

        colors = extract_colors_from_logo(logo)

        self.assertIsNotNone(colors)
        self.assertEqual(len(colors), 3)
        self.assertEqual(colors[0], '#C8102E')
        self.assertEqual(colors[1], '#F4C542')
        self.assertEqual(colors[2], '#2E3192')

    def test_rejects_images_without_detectable_brand_colors(self):
        image = Image.new('RGB', (40, 40), '#ffffff')
        logo = BytesIO()
        image.save(logo, format='PNG')
        logo.seek(0)

        self.assertIsNone(extract_colors_from_logo(logo))

    def test_extracts_up_to_six_distinct_logo_colors(self):
        logo_colors = [
            '#C8102E', '#F4C542', '#2E3192',
            '#009739', '#00A6D2', '#F26A21',
        ]
        image = Image.new('RGB', (180, 60), 'white')
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(logo_colors):
            draw.rectangle((index * 30, 0, (index + 1) * 30 - 1, 59), fill=color)
        logo = BytesIO()
        image.save(logo, format='PNG')
        logo.seek(0)

        colors = extract_colors_from_logo(logo)

        self.assertEqual(len(colors), 6)
        self.assertEqual(set(colors), set(logo_colors))


class LogoUploadViewTests(TestCase):
    def test_uploading_logo_applies_detected_colors_over_old_manual_colors(self):
        image = Image.new('RGBA', (120, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 68, 72), fill='#c8102e')
        draw.rectangle((72, 8, 94, 72), fill='#f4c542')
        draw.rectangle((98, 8, 118, 72), fill='#2e3192')
        image_data = BytesIO()
        image.save(image_data, format='PNG')

        admin = get_user_model().objects.create_superuser(
            username='branding-admin',
            email='branding@example.com',
            password='test-password',
        )
        self.client.force_login(admin)
        data = {
            'school_name': 'Test Shuttle',
            'motto': '',
            'description': '',
            'about': '',
            'address': '',
            'phone': '',
            'email': '',
            'website': '',
            'primary_color': '#123456',
            'secondary_color': '#222222',
            'accent_color': '#abcdef',
            'logo': SimpleUploadedFile(
                'school-logo.png',
                image_data.getvalue(),
                content_type='image/png',
            ),
        }

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post('/settings/', data)

        self.assertEqual(response.status_code, 302)
        school = SchoolSettings.get_settings()
        self.assertEqual(school.primary_color, '#C8102E')
        self.assertEqual(school.secondary_color, '#F4C542')
        self.assertEqual(school.accent_color, '#2E3192')
        self.assertEqual(school.auto_palette, ['#C8102E', '#F4C542', '#2E3192'])
        self.assertEqual(school.primary_color, school.auto_primary_color)


class BrandingContextTests(TestCase):
    def test_injects_rgb_values_for_dynamic_css(self):
        school = SchoolSettings.get_settings()
        school.primary_color = '#C8102E'
        school.secondary_color = '#441B22'
        school.accent_color = '#F4C542'
        school.save()

        branding = school_settings_processor(None)

        self.assertEqual(branding['primary_rgb'], '200, 16, 46')
        self.assertEqual(branding['secondary_rgb'], '68, 27, 34')
        self.assertEqual(branding['accent_rgb'], '244, 197, 66')
        self.assertEqual(branding['brand_palette_slots'], [
            '#C8102E', '#441B22', '#F4C542',
            '#C8102E', '#441B22', '#F4C542',
        ])

    def test_secondary_color_is_not_replaced_with_an_unrelated_fallback(self):
        school = SchoolSettings.get_settings()
        school.secondary_color = '#F1F0F2'
        school.save()

        self.assertEqual(school.effective_secondary, '#F1F0F2')
