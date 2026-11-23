"""
Context processor — injects school_settings into every template context.
This allows all templates to access school branding without repetitive view code.
"""

from django.conf import settings
from django.templatetags.static import static

from .models import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    SchoolSettings,
)


def _rgb_components(color):
    try:
        if len(color) != 7 or color[0] != '#':
            raise ValueError
        return ', '.join(str(int(color[index:index + 2], 16)) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return '15, 23, 42'


def school_settings_processor(request):
    """
    Returns the active SchoolSettings so templates can use:
        {{ school.school_name }}, {{ school.logo }}, etc.
    """
    school = SchoolSettings.get_settings()
    default_logo_url = static('images/default-school-logo.png')
    try:
        uploaded_logo_url = school.logo.url if school.has_logo else ''
    except Exception:
        uploaded_logo_url = ''
    try:
        uploaded_favicon_url = school.favicon.url if school.favicon else ''
    except Exception:
        uploaded_favicon_url = ''
    # Render instances use Cloudinary for durable uploads. If credentials are
    # missing, or an old /media/ reference remains, use the bundled logo rather
    # than showing a broken image.
    local_media_reference = uploaded_logo_url.startswith('/media/')
    if local_media_reference and not settings.DEBUG and not getattr(
        settings, 'CLOUDINARY_CONFIGURED', False
    ):
        school_logo_url = default_logo_url
    else:
        school_logo_url = uploaded_logo_url or default_logo_url
    local_favicon_reference = uploaded_favicon_url.startswith('/media/')
    if local_favicon_reference and not settings.DEBUG and not getattr(
        settings, 'CLOUDINARY_CONFIGURED', False
    ):
        school_favicon_url = default_logo_url
    else:
        school_favicon_url = uploaded_favicon_url or default_logo_url
    branding_version = (
        school.updated_at.strftime('%Y%m%d%H%M%S')
        if school.updated_at else '1'
    )
    if school.has_logo:
        separator = '&' if '?' in school_logo_url else '?'
        school_logo_url = f'{school_logo_url}{separator}v={branding_version}'
    if school.favicon:
        separator = '&' if '?' in school_favicon_url else '?'
        school_favicon_url = f'{school_favicon_url}{separator}v={branding_version}'
    palette = school.effective_palette or [
        school.effective_primary,
        school.effective_secondary,
        school.effective_accent,
    ]
    palette_slots = [palette[index % len(palette)] for index in range(6)]
    return {
        'school': school,
        'default_logo_url': default_logo_url,
        'school_logo_url': school_logo_url,
        'school_favicon_url': school_favicon_url,
        'default_primary_color': DEFAULT_PRIMARY_COLOR,
        'default_secondary_color': DEFAULT_SECONDARY_COLOR,
        'default_accent_color': DEFAULT_ACCENT_COLOR,
        'primary_color': school.effective_primary,
        'secondary_color': school.effective_secondary,
        'accent_color': school.effective_accent,
        'primary_rgb': _rgb_components(school.effective_primary),
        'secondary_rgb': _rgb_components(school.effective_secondary),
        'accent_rgb': _rgb_components(school.effective_accent),
        'logo_palette': palette,
        'brand_palette_slots': palette_slots,
    }
