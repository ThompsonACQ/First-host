"""Helpers for extracting exact brand colors from a school logo."""

import colorsys
import math

from PIL import Image, UnidentifiedImageError


def _hex_color(rgb):
    return '#{:02X}{:02X}{:02X}'.format(*rgb)


def _distance(first, second):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def extract_colors_from_logo(logo_file):
    """Return up to six prominent, distinct colors present in the logo."""
    try:
        with Image.open(logo_file) as source:
            source.thumbnail((256, 256), Image.Resampling.NEAREST)
            pixels = source.convert('RGBA').getdata()
    except (OSError, UnidentifiedImageError, ValueError):
        return None

    counts = {}
    for red, green, blue, alpha in pixels:
        if alpha < 200:
            continue
        rgb = (red, green, blue)
        if red > 235 and green > 235 and blue > 235:
            continue
        counts[rgb] = counts.get(rgb, 0) + 1

    if not counts:
        return None

    total_pixels = sum(counts.values())
    min_color_pixels = max(2, round(total_pixels * 0.0001))
    candidates = [
        color for color, count in counts.items()
        if count >= min_color_pixels
    ]

    def saturation(color):
        return colorsys.rgb_to_hls(*(channel / 255 for channel in color))[2]

    chromatic = sorted(
        (color for color in candidates if saturation(color) >= 0.18),
        key=lambda color: counts[color] * (0.4 + saturation(color)),
        reverse=True,
    )
    neutral = sorted(
        (color for color in candidates if saturation(color) < 0.18),
        key=lambda color: counts[color],
        reverse=True,
    )
    distinct = []
    for color in chromatic + neutral:
        if all(_distance(color, previous) >= 38 for previous in distinct):
            distinct.append(color)
            if len(distinct) == 6:
                break

    if not distinct:
        return None

    return tuple(_hex_color(color) for color in distinct)
