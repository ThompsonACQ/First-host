"""
School Settings views — home page, settings CRUD, and live branding API.
"""

import json
import logging
import xml.etree.ElementTree as ET

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError

from .models import SchoolSettings
from .branding import apply_default_branding, extract_colors_from_logo
from accounts.decorators import admin_required

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# School Settings form
# -----------------------------------------------------------------------

class SchoolSettingsForm(forms.ModelForm):
    class Meta:
        model = SchoolSettings
        fields = [
            'school_name', 'motto', 'description', 'about',
            'address', 'phone', 'email', 'website',
            'logo', 'favicon',
            'primary_color', 'secondary_color', 'accent_color',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'about': forms.Textarea(attrs={'rows': 4}),
            'primary_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'secondary_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'accent_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and hasattr(logo, 'content_type'):
            allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml']
            if logo.content_type not in allowed:
                raise forms.ValidationError(
                    'Invalid image type. Please upload JPG, PNG, GIF, WebP, or SVG.'
                )
            if logo.size > 5 * 1024 * 1024:  # 5 MB
                raise forms.ValidationError('Logo file too large. Maximum size is 5 MB.')
        if logo:
            if getattr(logo, 'content_type', '').lower() == 'image/svg+xml':
                try:
                    logo.seek(0)
                    ET.fromstring(logo.read(1024 * 1024))
                    logo.seek(0)
                except (ET.ParseError, OSError, ValueError):
                    raise forms.ValidationError('The uploaded SVG is not valid.')
                return logo
            try:
                logo.seek(0)
                with Image.open(logo) as image:
                    image.verify()
                logo.seek(0)
            except (OSError, UnidentifiedImageError, ValueError):
                raise forms.ValidationError('The uploaded logo is not a valid image.')
        return logo

    def clean_favicon(self):
        favicon = self.cleaned_data.get('favicon')
        if favicon and hasattr(favicon, 'content_type'):
            if favicon.size > 1 * 1024 * 1024:
                raise forms.ValidationError('Favicon too large. Maximum size is 1 MB.')
        return favicon


# -----------------------------------------------------------------------
# Home page
# -----------------------------------------------------------------------

def home(request):
    """
    Public home page — all content comes from SchoolSettings in the DB.
    """
    from routes.models import Route

    routes = Route.objects.filter(active=True).prefetch_related('stops').order_by('name')
    locations = {}
    for route in routes:
        route_locations = [
            route.start_location,
            *(stop.name for stop in route.stops.all()),
            route.destination,
        ]
        for location in route_locations:
            location = location.strip()
            if location:
                locations.setdefault(location.casefold(), location)

    return render(request, 'home.html', {
        'route_locations': sorted(locations.values(), key=str.casefold),
    })


# -----------------------------------------------------------------------
# Admin: Website Settings
# -----------------------------------------------------------------------

@admin_required
def settings_view(request):
    """Display and save the school settings form."""
    school = SchoolSettings.get_settings()

    if request.method == 'POST':
        form = SchoolSettingsForm(request.POST, request.FILES, instance=school)
        if form.is_valid():
            instance = form.save(commit=False)

            logo_cleared = 'logo' in form.changed_data and not instance.logo
            # A new logo always becomes the active source of the brand palette.
            if 'logo' in request.FILES:
                logo_file = request.FILES['logo']
                logo_file.seek(0)
                colors = extract_colors_from_logo(logo_file)
                logo_file.seek(0)  # Reset pointer so Django can save the file!
                if colors:
                    palette = list(colors)
                    primary = palette[0]
                    secondary = palette[1] if len(palette) > 1 else primary
                    accent = palette[2] if len(palette) > 2 else secondary
                    instance.auto_palette = palette
                    instance.auto_primary_color = primary
                    instance.auto_secondary_color = secondary
                    instance.auto_accent_color = accent
                    instance.primary_color = primary
                    instance.secondary_color = secondary
                    instance.accent_color = accent
                else:
                    instance.auto_palette = []
                    instance.auto_primary_color = ''
                    instance.auto_secondary_color = ''
                    instance.auto_accent_color = ''
                    logger.warning('Could not extract a color palette from uploaded school logo.')
                    messages.warning(
                        request,
                        'Logo saved, but its colors could not be detected. Set the theme colors manually.',
                    )
            elif logo_cleared:
                apply_default_branding(instance)

            try:
                instance.save()
            except Exception:
                logger.exception(
                    'Failed to save SchoolSettings or upload branding image to Cloudinary.',
                    extra={'username': getattr(request.user, 'username', '')},
                )
                messages.error(
                    request,
                    'The branding change could not be saved. Check the image and Cloudinary configuration, then try again.',
                )
            else:
                messages.success(request, 'School settings saved successfully.')
            return redirect('school_settings:settings')
    else:
        form = SchoolSettingsForm(instance=school)

    return render(request, 'school_settings/settings.html', {
        'form': form,
        'school': school,
    })


@admin_required
def reset_colors(request):
    """Reset manually changed colors back to auto-detected values."""
    school = SchoolSettings.get_settings()
    if school.auto_primary_color:
        school.primary_color = school.auto_primary_color
        school.secondary_color = school.auto_secondary_color
        school.accent_color = school.auto_accent_color
        school.save(update_fields=[
            'primary_color', 'secondary_color', 'accent_color', 'updated_at',
        ])
        messages.success(request, 'Colors reset to auto-detected values.')
    else:
        messages.info(request, 'No auto-detected colors available. Upload a logo first.')
    return redirect('school_settings:settings')


# -----------------------------------------------------------------------
# AJAX: Live preview data
# -----------------------------------------------------------------------

def preview_api(request):
    """
    Returns current school settings as JSON for the live preview panel.
    Called by the settings JS before the admin saves.
    """
    school = SchoolSettings.get_settings()
    logo_url = request.build_absolute_uri('/static/images/default-school-logo.png')
    if school.has_logo:
        uploaded_url = school.logo.url
        if not (
            uploaded_url.startswith('/media/')
            and not settings.DEBUG
            and not getattr(settings, 'CLOUDINARY_CONFIGURED', False)
        ):
            logo_url = uploaded_url
    return JsonResponse({
        'school_name': school.school_name,
        'motto': school.motto,
        'primary_color': school.effective_primary,
        'secondary_color': school.effective_secondary,
        'accent_color': school.effective_accent,
        'logo_url': logo_url,
    })
