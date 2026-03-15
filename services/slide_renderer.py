"""Template-driven Pillow slide renderer for Instagram carousels.

Architecture: **Layout + Theme + Overrides**

The renderer is fully generic — it reads layout structure from a *template*,
visual styling from a *theme*, and allows per-request *overrides*.

Merge priority (highest wins):
    user overrides  >  theme  >  element defaults

Supported element types
-----------------------
- ``image``        — background or positioned image (asset or solid fill)
- ``rect``         — filled rectangle (accent lines, overlays, dividers)
- ``title``        — word-wrapped title text from content
- ``subtitle``     — word-wrapped subtitle text from content
- ``body``         — word-wrapped body paragraph from content
- ``bullet_list``  — bulleted list from content["bullets"]
- ``cta``          — call-to-action text (optionally inside a button rect)
- ``slide_counter``— slide number indicator

Theme-aware styling
-------------------
Layout elements specify position (``x``, ``y``, ``max_width``).
Theme fills in style (``font``, ``size``, ``weight``, ``color``).
Rect elements use a ``role`` field to look up themed colors::

    {"type": "rect", "role": "accent", ...}  →  theme.colors.accent
    {"type": "rect", "role": "overlay", ...} →  theme.colors.overlay

Asset mapping
-------------
Image elements reference assets by ``asset_id``.  The caller passes an
``asset_map`` dict mapping IDs to PIL Images.

User overrides
--------------
Keys follow ``{element_type}_{property}``::

    {"title_font": "Montserrat", "title_color": "#FFD700"}
"""

from __future__ import annotations

import io
import logging
import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

_FONT_DIRS = [
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "fonts"),
    "/usr/share/fonts/truetype",
]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _resolve_font(family: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    """Load a font at the requested size, falling back to Inter or default."""
    cache_key = (family, size, weight)
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    candidates = []
    if family.lower() == "inter":
        candidates = ["InterVariable.ttf", "Inter.ttc"]
    elif family.lower() == "playfair display":
        candidates = ["PlayfairDisplay-VariableFont_wght.ttf"]
    else:
        candidates = [f"{family}.ttf", f"{family}.ttc"]

    candidates += ["InterVariable.ttf", "Inter.ttc"]

    for font_dir in _FONT_DIRS:
        for candidate in candidates:
            path = os.path.join(font_dir, candidate)
            if os.path.isfile(path):
                try:
                    font = ImageFont.truetype(path, size)
                    _font_cache[cache_key] = font
                    return font
                except Exception:
                    continue

    log.warning("[renderer] no font found for %s/%d, using default", family, size)
    font = ImageFont.load_default(size=size)
    _font_cache[cache_key] = font
    return font


# ---------------------------------------------------------------------------
# Color parsing
# ---------------------------------------------------------------------------

def _parse_color(color_str: str) -> tuple[int, ...]:
    """Parse a CSS-style hex color to an RGBA tuple."""
    c = color_str.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)
    if len(c) == 8:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16))
    return (255, 255, 255, 255)


# ---------------------------------------------------------------------------
# Text wrapping
# ---------------------------------------------------------------------------

def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
               max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines or [""]


# ---------------------------------------------------------------------------
# Theme + Override merge
# ---------------------------------------------------------------------------

_STYLE_PROPS = ("font", "size", "weight", "color")
_RECT_ROLE_MAP = {
    "accent": "accent",
    "overlay": "overlay",
    "overlay_heavy": "overlay_heavy",
    "marker": "marker",
    "button": "button",
}


def apply_theme(element: dict, theme: dict | None) -> dict:
    """Merge theme styling into a layout element (non-mutating).

    For text-like elements (title, subtitle, body, cta, bullet_list,
    slide_counter), the theme provides font, size, weight, color based
    on the element type.

    For ``rect`` elements, the ``role`` field maps to a theme color.
    For ``cta`` elements, ``button_color/padding/radius`` come from theme.
    """
    if not theme:
        return element
    merged = dict(element)
    etype = element.get("type", "")

    # Text-style elements: font, size, weight, color from theme
    if etype in ("title", "subtitle", "body", "cta", "bullet_list", "slide_counter"):
        fonts = theme.get("fonts", {})
        sizes = theme.get("sizes", {})
        weights = theme.get("weights", {})
        colors = theme.get("colors", {})

        if "font" not in element and etype in fonts:
            merged["font"] = fonts[etype]
        if "size" not in element and etype in sizes:
            merged["size"] = sizes[etype]
        if "weight" not in element and etype in weights:
            merged["weight"] = weights[etype]
        if "color" not in element and etype in colors:
            merged["color"] = colors[etype]

        # bullet_list extras
        if etype == "bullet_list":
            if "marker_color" not in element and "marker" in colors:
                merged["marker_color"] = colors["marker"]

        # cta button styling
        if etype == "cta":
            if "button_color" not in element and "button" in colors:
                merged["button_color"] = colors["button"]
            btn = theme.get("button", {})
            if "button_padding_x" not in element and "padding_x" in btn:
                merged["button_padding_x"] = btn["padding_x"]
            if "button_padding_y" not in element and "padding_y" in btn:
                merged["button_padding_y"] = btn["padding_y"]
            if "button_radius" not in element and "radius" in btn:
                merged["button_radius"] = btn["radius"]

    # Rect elements: color from role
    elif etype == "rect":
        role = element.get("role", "")
        colors = theme.get("colors", {})
        if role and "color" not in element and role in colors:
            merged["color"] = colors[role]

    return merged


def apply_overrides(element: dict, overrides: dict) -> dict:
    """Apply user overrides on top of a (theme-merged) element.

    Override keys: ``{element_type}_{property}``, e.g. ``title_font``.
    ``accent_color`` applies to rect elements with role=accent.
    """
    if not overrides:
        return element
    etype = element.get("type", "")
    merged = dict(element)

    for prop in ("font", "size", "color", "weight"):
        key = f"{etype}_{prop}"
        if key in overrides:
            merged[prop] = overrides[key]

    # bullet_list marker_color override
    if etype == "bullet_list" and "bullet_list_marker_color" in overrides:
        merged["marker_color"] = overrides["bullet_list_marker_color"]

    # accent_color override for accent rects
    if etype == "rect" and element.get("role") == "accent" and "accent_color" in overrides:
        merged["color"] = overrides["accent_color"]

    # button_color override for CTA
    if etype == "cta" and "cta_button_color" in overrides:
        merged["button_color"] = overrides["cta_button_color"]

    return merged


# ---------------------------------------------------------------------------
# Element renderers
# ---------------------------------------------------------------------------

def _draw_image(
    img: Image.Image, draw: ImageDraw.ImageDraw,
    el: dict, content: dict, asset_map: dict,
    slide_number: int,
) -> None:
    """Draw an image element (background asset, logo, etc.).

    Supports two positioning modes:
    1. Explicit x/y/width/height (original behavior).
    2. Anchor-based: ``anchor`` field resolved via asset_placement module.
    """
    asset_id = el.get("asset_id", "")
    pil_asset = asset_map.get(asset_id) if asset_id else None
    if pil_asset is None:
        fill = el.get("fill")
        if fill:
            overlay = Image.new("RGBA", img.size, _parse_color(fill))
            img.paste(Image.alpha_composite(img.convert("RGBA"), overlay), (0, 0))
        return

    # Resolve position: anchor-based or explicit x/y
    anchor = el.get("anchor")
    if anchor:
        from services.asset_placement import resolve_anchor
        box = el.get("box") or {
            "width": el.get("width", img.width),
            "height": el.get("height", img.height),
            "margin_x": el.get("margin_x", 40),
            "margin_y": el.get("margin_y", 40),
        }
        coords = resolve_anchor(anchor, box=box, canvas_w=img.width, canvas_h=img.height)
        x, y, w, h = coords["x"], coords["y"], coords["width"], coords["height"]
    else:
        x, y = int(el.get("x", 0)), int(el.get("y", 0))
        w, h = int(el.get("width", img.width)), int(el.get("height", img.height))

    resized = pil_asset.resize((w, h), Image.LANCZOS).convert("RGBA")
    img.paste(Image.alpha_composite(
        img.crop((x, y, x + w, y + h)).convert("RGBA"), resized
    ), (x, y))


def _draw_rect(
    img: Image.Image, draw: ImageDraw.ImageDraw,
    el: dict, content: dict, asset_map: dict,
    slide_number: int,
) -> None:
    """Draw a filled rectangle (accent line, divider, overlay)."""
    x, y = int(el.get("x", 0)), int(el.get("y", 0))
    w = int(el.get("width", 64))
    h = int(el.get("height", 5))
    color = _parse_color(el.get("color", "#ffffff"))
    radius = int(el.get("radius", 0))
    if radius:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=color)
    else:
        draw.rectangle([x, y, x + w, y + h], fill=color)


def _draw_text_element(
    img: Image.Image, draw: ImageDraw.ImageDraw,
    el: dict, content: dict, asset_map: dict,
    slide_number: int,
) -> None:
    """Draw a single text block (title, subtitle, body)."""
    content_key = el.get("content_key", el.get("type", "title"))
    text = content.get(content_key, "")
    if not text:
        return

    font = _resolve_font(
        el.get("font", "Inter"),
        int(el.get("size", 36)),
        int(el.get("weight", 400)),
    )
    color = _parse_color(el.get("color", "#ffffff"))
    x, y = int(el.get("x", 0)), int(el.get("y", 0))
    max_w = int(el.get("max_width", img.width - x - 80))
    align = el.get("align", "left")
    line_gap = int(el.get("line_gap", 10))

    lines = _wrap_text(draw, text, font, max_w)
    for line in lines:
        if align == "center":
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            tx = x + (max_w - lw) // 2
        elif align == "right":
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            tx = x + max_w - lw
        else:
            tx = x
        draw.text((tx, y), line, fill=color, font=font)
        bbox = draw.textbbox((0, 0), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap


def _draw_bullet_list(
    img: Image.Image, draw: ImageDraw.ImageDraw,
    el: dict, content: dict, asset_map: dict,
    slide_number: int,
) -> None:
    """Draw a bulleted list from content['bullets']."""
    bullets = content.get(el.get("content_key", "bullets"), [])
    if not bullets:
        return

    font = _resolve_font(
        el.get("font", "Inter"),
        int(el.get("size", 32)),
        int(el.get("weight", 400)),
    )
    text_color = _parse_color(el.get("color", "#ffffff"))
    marker_color = _parse_color(el.get("marker_color", el.get("color", "#ffffff")))
    x, y = int(el.get("x", 0)), int(el.get("y", 0))
    max_w = int(el.get("max_width", img.width - x - 80))
    indent = int(el.get("indent", 30))
    marker_size = int(el.get("marker_size", 12))
    item_gap = int(el.get("item_gap", 16))
    line_gap = int(el.get("line_gap", 8))

    for bullet in bullets:
        my = y + 8
        draw.ellipse(
            [x, my, x + marker_size, my + marker_size],
            fill=marker_color,
        )
        lines = _wrap_text(draw, bullet, font, max_w - indent)
        for line in lines:
            draw.text((x + indent, y), line, fill=text_color, font=font)
            bbox = draw.textbbox((0, 0), line, font=font)
            y += (bbox[3] - bbox[1]) + line_gap
        y += item_gap


def _draw_cta(
    img: Image.Image, draw: ImageDraw.ImageDraw,
    el: dict, content: dict, asset_map: dict,
    slide_number: int,
) -> None:
    """Draw a call-to-action element, optionally with a button background."""
    text = content.get(el.get("content_key", "cta"), "")
    if not text:
        return

    font = _resolve_font(
        el.get("font", "Inter"),
        int(el.get("size", 40)),
        int(el.get("weight", 700)),
    )
    text_color = _parse_color(el.get("color", "#ffffff"))
    x, y = int(el.get("x", 0)), int(el.get("y", 0))
    max_w = int(el.get("max_width", img.width - x - 80))
    align = el.get("align", "center")
    line_gap = int(el.get("line_gap", 10))

    lines = _wrap_text(draw, text, font, max_w)

    btn_color = el.get("button_color")
    if btn_color:
        total_h = 0
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            total_h += (bbox[3] - bbox[1]) + line_gap
        btn_pad_x = int(el.get("button_padding_x", 60))
        btn_pad_y = int(el.get("button_padding_y", 30))
        btn_radius = int(el.get("button_radius", 12))
        btn_w = max_w
        btn_h = total_h + 2 * btn_pad_y
        btn_x = x
        btn_y = y
        draw.rounded_rectangle(
            [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
            radius=btn_radius,
            fill=_parse_color(btn_color),
        )
        y = btn_y + btn_pad_y
        x = btn_x

    for line in lines:
        if align == "center":
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            tx = x + (max_w - lw) // 2
        else:
            tx = x
        draw.text((tx, y), line, fill=text_color, font=font)
        bbox = draw.textbbox((0, 0), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap


def _draw_slide_counter(
    img: Image.Image, draw: ImageDraw.ImageDraw,
    el: dict, content: dict, asset_map: dict,
    slide_number: int,
) -> None:
    """Draw the slide number indicator."""
    font = _resolve_font(
        el.get("font", "Inter"),
        int(el.get("size", 24)),
    )
    color = _parse_color(el.get("color", "#aaaaaa"))
    x, y = int(el.get("x", img.width - 120)), int(el.get("y", img.height - 80))
    draw.text((x, y), str(slide_number), fill=color, font=font)


# ---------------------------------------------------------------------------
# Element dispatcher
# ---------------------------------------------------------------------------

_ELEMENT_RENDERERS = {
    "image": _draw_image,
    "rect": _draw_rect,
    "title": _draw_text_element,
    "subtitle": _draw_text_element,
    "body": _draw_text_element,
    "bullet_list": _draw_bullet_list,
    "cta": _draw_cta,
    "slide_counter": _draw_slide_counter,
}


# ---------------------------------------------------------------------------
# Single-slide renderer
# ---------------------------------------------------------------------------

def _render_slide(
    canvas: dict,
    elements: list[dict],
    content: dict,
    asset_map: dict,
    theme: dict | None,
    overrides: dict,
    slide_number: int,
) -> Image.Image:
    """Render one slide: merge theme → overrides → draw elements."""
    w = int(canvas.get("width", 1080))
    h = int(canvas.get("height", 1080))
    bg = _parse_color(canvas.get("background", "#111111"))

    img = Image.new("RGBA", (w, h), bg)
    draw = ImageDraw.Draw(img)

    for el in elements:
        el = apply_theme(el, theme)
        el = apply_overrides(el, overrides)
        etype = el.get("type", "")
        renderer = _ELEMENT_RENDERERS.get(etype)
        if renderer is None:
            log.warning("[renderer] unknown element type '%s', skipping", etype)
            continue
        renderer(img, draw, el, content, asset_map, slide_number)
        draw = ImageDraw.Draw(img)

    return img


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_slides(
    template: dict,
    content: dict,
    asset_map: dict | None = None,
    theme: dict | None = None,
    overrides: dict | None = None,
    # Legacy compat
    asset_img: Optional[Image.Image] = None,
) -> list[bytes]:
    """Render all slides and return PNG byte buffers.

    Args:
        template: Layout template (from templates/layouts/).
        content:  Structured content from the LLM.
        asset_map: Dict mapping asset_id strings to PIL Images.
        theme: Theme dict (from templates/themes/). Optional — if the
               template has inline styles they still work.
        overrides: User overrides (highest priority).
        asset_img: Legacy — single background image.

    Returns:
        List of PNG byte buffers, one per slide.
    """
    asset_map = dict(asset_map or {})
    overrides = overrides or {}

    if asset_img is not None and "background_asset" not in asset_map:
        asset_map["background_asset"] = asset_img

    # Resolve canvas: theme background overrides template if template
    # doesn't specify one.
    canvas = dict(template.get("canvas", {"width": 1080, "height": 1080}))
    if "background" not in canvas and theme:
        canvas["background"] = theme.get("canvas", {}).get("background", "#111111")
    elif theme and "background" in theme.get("canvas", {}):
        # Theme provides canvas background; only use if template doesn't
        # already have one OR it's a layout-only template.
        if "background" not in template.get("canvas", {}):
            canvas["background"] = theme["canvas"]["background"]

    slides = template.get("slides", [])

    png_buffers: list[bytes] = []
    for idx, slide_def in enumerate(slides):
        elements = slide_def.get("elements", [])
        pil_img = _render_slide(
            canvas, elements, content, asset_map, theme, overrides, idx + 1,
        )

        buf = io.BytesIO()
        pil_img.convert("RGB").save(buf, format="PNG", optimize=True)
        png_buffers.append(buf.getvalue())
        log.info("[renderer] slide %d → %d bytes (%d elements)",
                 idx + 1, len(buf.getvalue()), len(elements))

    return png_buffers


def load_asset_image(source: str | bytes) -> Image.Image:
    """Load an asset image from a URL, file path, or raw bytes."""
    import requests as http_requests

    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source))

    if source.startswith("http"):
        resp = http_requests.get(source, timeout=30)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content))

    return Image.open(source)
