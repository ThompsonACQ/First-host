"""
Admin registration for SchoolSettings.
"""
import logging
import xml.etree.ElementTree as ET

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from .branding import apply_default_branding, extract_colors_from_logo
from .models import SchoolSettings


logger = logging.getLogger(__name__)


class SchoolSettingsAdminForm(forms.ModelForm):
    class Meta:
        model = SchoolSettings
        fields = '__all__'

    def _validate_image(self, uploaded, field_name, maximum_bytes):
        if not uploaded:
            return uploaded
        if not getattr(uploaded, 'content_type', '').lower().startswith('image/'):
            raise ValidationError('Only image files may be uploaded.')
        if uploaded.size > maximum_bytes:
            raise ValidationError(
                'Image too large. Maximum size is {} MB.'.format(
                    maximum_bytes // (1024 * 1024)
                )
            )
        content_type = getattr(uploaded, 'content_type', '').lower()
        if content_type == 'image/svg+xml':
            try:
                uploaded.seek(0)
                ET.fromstring(uploaded.read(1024 * 1024))
                uploaded.seek(0)
            except (ET.ParseError, OSError, ValueError):
                raise ValidationError('The uploaded SVG is not valid.')
            return uploaded
        try:
            uploaded.seek(0)
            with Image.open(uploaded) as image:
                image.verify()
            uploaded.seek(0)
        except (OSError, UnidentifiedImageError, ValueError):
            raise ValidationError('The uploaded file is not a valid image.')
        return uploaded

    def clean_logo(self):
        return self._validate_image(self.cleaned_data.get('logo'), 'logo', 5 * 1024 * 1024)

    def clean_favicon(self):
        return self._validate_image(self.cleaned_data.get('favicon'), 'favicon', 1 * 1024 * 1024)


@admin.register(SchoolSettings)
class SchoolSettingsAdmin(admin.ModelAdmin):
    form = SchoolSettingsAdminForm
    list_display = ['school_name', 'primary_color', 'has_logo', 'updated_at']
    readonly_fields = [
        'auto_primary_color', 'auto_secondary_color', 'auto_accent_color',
        'auto_palette', 'created_at', 'updated_at',
    ]

    def save_model(self, request, obj, form, change):
        logo_changed = 'logo' in form.changed_data and bool(request.FILES.get('logo'))
        if logo_changed:
            logo_file = request.FILES['logo']
            logo_file.seek(0)
            try:
                colors = extract_colors_from_logo(logo_file)
            except Exception:
                logger.exception('Unexpected error extracting colors from uploaded school logo.')
                colors = None
            logo_file.seek(0)
        elif 'logo' in form.changed_data:
            apply_default_branding(obj)
        try:
            super().save_model(request, obj, form, change)
        except Exception as exc:
            logger.exception(
                'Failed to save SchoolSettings or upload branding image to media storage.',
                extra={'username': getattr(request.user, 'username', ''), 'logo_changed': logo_changed},
            )
            self.message_user(
                request,
                'The branding change could not be saved. Check Cloudinary credentials and try again.',
                level=messages.ERROR,
            )
            return

        if logo_changed:
            if colors:
                palette = list(colors)
                primary = palette[0]
                secondary = palette[1] if len(palette) > 1 else primary
                accent = palette[2] if len(palette) > 2 else secondary
                obj.auto_palette = palette
                obj.primary_color = obj.auto_primary_color = primary
                obj.secondary_color = obj.auto_secondary_color = secondary
                obj.accent_color = obj.auto_accent_color = accent
                try:
                    obj.save(update_fields=[
                        'primary_color', 'secondary_color', 'accent_color',
                        'auto_primary_color', 'auto_secondary_color',
                        'auto_accent_color', 'auto_palette', 'updated_at',
                    ])
                except Exception:
                    logger.exception('Logo uploaded, but database branding metadata could not be updated.')
                    self.message_user(
                        request,
                        'The logo uploaded, but automatic colors could not be saved.',
                        level=messages.ERROR,
                    )
            else:
                obj.auto_palette = []
                obj.auto_primary_color = ''
                obj.auto_secondary_color = ''
                obj.auto_accent_color = ''
                try:
                    obj.save(update_fields=[
                        'auto_primary_color', 'auto_secondary_color',
                        'auto_accent_color', 'auto_palette', 'updated_at',
                    ])
                except Exception:
                    logger.exception('Logo uploaded, but auto-color metadata could not be cleared.')

    def has_logo(self, obj):
        return bool(obj.logo)
    has_logo.boolean = True
    has_logo.short_description = 'Logo'
