from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from PIL import Image, ImageDraw
from unittest.mock import patch

from .admin import SchoolSettingsAdminForm
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


class LogoAdminValidationTests(SimpleTestCase):
    def test_admin_rejects_non_image_logo(self):
        logo = SimpleUploadedFile(
            'logo.txt',
            b'not an image',
            content_type='text/plain',
        )
        form = SchoolSettingsAdminForm(
            data={},
            files={'logo': logo},
        )

        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)

    def test_admin_accepts_valid_png_logo(self):
        image_data = BytesIO()
        Image.new('RGB', (40, 40), '#C8102E').save(image_data, format='PNG')
        logo = SimpleUploadedFile(
            'logo.png',
            image_data.getvalue(),
            content_type='image/png',
        )
        school = SchoolSettings(
            pk=1,
            school_name='Test Shuttle',
        )
        form = SchoolSettingsAdminForm(
            instance=school,
            data={
                'school_name': school.school_name,
                'motto': school.motto,
                'description': school.description,
                'about': school.about,
                'address': school.address,
                'phone': school.phone,
                'email': school.email,
                'website': school.website,
                'primary_color': school.primary_color,
                'secondary_color': school.secondary_color,
                'accent_color': school.accent_color,
            },
            files={'logo': logo},
        )

        self.assertTrue(form.is_valid(), form.errors)


class LogoUploadViewTests(TestCase):
    def test_storage_failure_returns_form_with_friendly_error(self):
        admin = get_user_model().objects.create_superuser(
            username='storage-failure-admin',
            email='storage-failure@example.com',
            password='test-password',
        )
        self.client.force_login(admin)
        school = SchoolSettings.get_settings()
        image_data = BytesIO()
        Image.new('RGB', (40, 40), '#C8102E').save(image_data, format='PNG')

        data = {
            'school_name': school.school_name,
            'motto': school.motto,
            'description': school.description,
            'about': school.about,
            'address': school.address,
            'phone': school.phone,
            'email': school.email,
            'website': school.website,
            'primary_color': school.primary_color,
            'secondary_color': school.secondary_color,
            'accent_color': school.accent_color,
            'logo': SimpleUploadedFile(
                'logo.png',
                image_data.getvalue(),
                content_type='image/png',
            ),
        }

        with patch.object(SchoolSettings, 'save', side_effect=RuntimeError('Cloudinary unavailable')):
            response = self.client.post('/settings/', data)

        self.assertEqual(response.status_code, 302)

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

    def test_clearing_logo_restores_default_logo_and_brand_palette(self):
        image_data = BytesIO()
        Image.new('RGB', (16, 16), '#C8102E').save(image_data, format='PNG')
        admin = get_user_model().objects.create_superuser(
            username='clear-logo-admin',
            email='clear-logo@example.com',
            password='test-password',
        )
        self.client.force_login(admin)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                school = SchoolSettings.get_settings()
                school.logo.save(
                    'custom-logo.png',
                    SimpleUploadedFile(
                        'custom-logo.png',
                        image_data.getvalue(),
                        content_type='image/png',
                    ),
                    save=False,
                )
                school.primary_color = '#C8102E'
                school.secondary_color = '#F4C542'
                school.accent_color = '#2E3192'
                school.auto_primary_color = '#C8102E'
                school.auto_secondary_color = '#F4C542'
                school.auto_accent_color = '#2E3192'
                school.auto_palette = ['#C8102E', '#F4C542', '#2E3192']
                school.save()

                response = self.client.post('/settings/', {
                    'school_name': school.school_name,
                    'motto': school.motto,
                    'description': school.description,
                    'about': school.about,
                    'address': school.address,
                    'phone': school.phone,
                    'email': school.email,
                    'website': school.website,
                    'primary_color': school.primary_color,
                    'secondary_color': school.secondary_color,
                    'accent_color': school.accent_color,
                    'logo-clear': 'on',
                })

                school.refresh_from_db()
                self.assertEqual(response.status_code, 302)
                self.assertFalse(school.logo)
                self.assertEqual(school.primary_color, '#2E3192')
                self.assertEqual(school.secondary_color, '#0F172A')
                self.assertEqual(school.accent_color, '#FFF102')
                self.assertEqual(
                    school.auto_palette,
                    ['#2E3192', '#0F172A', '#FFF102'],
                )
                self.assertEqual(school.auto_primary_color, '#2E3192')
                branding = school_settings_processor(None)
                self.assertEqual(
                    branding['school_logo_url'],
                    branding['default_logo_url'],
                )


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

    def test_default_logo_and_colors_are_used_without_a_custom_logo(self):
        branding = school_settings_processor(None)

        self.assertEqual(branding['school_logo_url'], branding['default_logo_url'])
        self.assertEqual(branding['school_favicon_url'], branding['default_logo_url'])
        self.assertEqual(branding['primary_color'], '#2E3192')
        self.assertEqual(branding['accent_color'], '#FFF102')

    def test_secondary_color_is_not_replaced_with_an_unrelated_fallback(self):
        school = SchoolSettings.get_settings()
        school.secondary_color = '#F1F0F2'
        school.save()

        self.assertEqual(school.effective_secondary, '#F1F0F2')
