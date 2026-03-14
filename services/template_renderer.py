"""Deterministic HTML renderer for Instagram carousel slides and newsletter layouts.

Replaces the old architecture where the LLM generated raw HTML.
Now the LLM produces a structured DesignSystemSpec (JSON), and this module
converts it into pixel-perfect HTML deterministically — no LLM involved.

Usage:
    from services.template_renderer import render_instagram_slide, render_instagram_template

    spec = { "colors": {...}, "typography": {...}, "layout": {...}, ... }
    html = render_instagram_slide(spec, "cover", {"title": "Hello", "subtitle": "World"})
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

# ─────────────────────────────────────────────────────────────────────
# DesignSystemSpec schema definition & defaults
# ─────────────────────────────────────────────────────────────────────

DEFAULT_DESIGN_SPEC: dict[str, Any] = {
    "theme_name": "Default Modern",
    "colors": {
        "background": "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)",
        "primary_text": "#ffffff",
        "secondary_text": "rgba(255,255,255,0.7)",
        "accent": "#7c5ce7",
        "accent2": "#a29bfe",
        "card_bg": "rgba(255,255,255,0.06)",
    },
    "typography": {
        "heading_font": "Inter",
        "body_font": "Inter",
        "heading_weight": 800,
        "body_weight": 400,
        "heading_size_px": 68,
        "body_size_px": 32,
        "line_height": 1.3,
    },
    "layout": {
        "padding_px": 80,
        "corner_radius_px": 0,
        "show_slide_counter": True,
        "show_brand_footer": True,
        "accent_line": True,
        "accent_line_width_px": 64,
        "decorative_orbs": True,
        "brand_position": "bottom",
    },
    "slide_layouts": {
        "cover": "cover_centered",
        "content": "header_body",
        "list": "header_bullets",
        "cta": "cta_centered",
    },
    "images": {
        "logo_url": "",
        "background_image_url": "",
    },
}

# Allowed values for validation
ALLOWED_SLIDE_LAYOUTS = {
    "cover": ["cover_centered", "cover_left", "cover_bold"],
    "content": ["header_body", "body_only", "two_column"],
    "list": ["header_bullets", "numbered", "icon_list"],
    "cta": ["cta_centered", "cta_split", "cta_minimal"],
}

ALLOWED_FONTS = [
    "Inter", "Syne", "Poppins", "Montserrat", "Playfair Display",
    "Roboto", "Open Sans", "Lato", "Raleway", "Oswald",
    "Nunito", "Work Sans", "DM Sans", "Space Grotesk", "Outfit",
    "Bebas Neue", "Archivo", "Manrope", "Rubik", "Quicksand",
]

# ─────────────────────────────────────────────────────────────────────
# Validation & clamping
# ─────────────────────────────────────────────────────────────────────

def _clamp(value: int | float, lo: int | float, hi: int | float) -> int | float:
    return max(lo, min(hi, value))


def _safe_int(value, default: int) -> int:
    """Convert to int safely, returning default on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value, default: float) -> float:
    """Convert to float safely, returning default on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _is_valid_color(c: str) -> bool:
    """Check if a color string looks safe (hex, rgb, rgba, hsl, or named CSS)."""
    if not isinstance(c, str):
        return False
    c = c.strip()
    # Block CSS injection characters
    if '}' in c or ';' in c:
        return False
    if re.match(r'^#[0-9a-fA-F]{3,8}$', c):
        return True
    if re.match(r'^(rgb|rgba|hsl|hsla|linear-gradient|radial-gradient)\(', c):
        return True
    if re.match(r'^[a-zA-Z]+$', c) and len(c) < 30:
        return True
    return False


def validate_design_spec(spec: dict) -> dict[str, Any]:
    """Validate and sanitize a DesignSystemSpec, clamping unsafe values.

    Returns a clean spec with defaults applied for missing fields.
    Raises ValueError for fundamentally invalid input.
    """
    if not isinstance(spec, dict):
        raise ValueError("design_spec must be a JSON object")

    clean = copy.deepcopy(DEFAULT_DESIGN_SPEC)

    # Theme name
    if "theme_name" in spec and isinstance(spec["theme_name"], str):
        clean["theme_name"] = spec["theme_name"][:60]

    # Colors
    if "colors" in spec and isinstance(spec["colors"], dict):
        for key in clean["colors"]:
            if key in spec["colors"] and _is_valid_color(str(spec["colors"][key])):
                clean["colors"][key] = str(spec["colors"][key])

    # Typography
    if "typography" in spec and isinstance(spec["typography"], dict):
        typo = spec["typography"]
        if "heading_font" in typo and str(typo["heading_font"]) in ALLOWED_FONTS:
            clean["typography"]["heading_font"] = str(typo["heading_font"])
        if "body_font" in typo and str(typo["body_font"]) in ALLOWED_FONTS:
            clean["typography"]["body_font"] = str(typo["body_font"])
        if "heading_weight" in typo:
            v = _safe_int(typo["heading_weight"], clean["typography"]["heading_weight"])
            clean["typography"]["heading_weight"] = int(_clamp(v, 100, 900))
        if "body_weight" in typo:
            v = _safe_int(typo["body_weight"], clean["typography"]["body_weight"])
            clean["typography"]["body_weight"] = int(_clamp(v, 100, 900))
        if "heading_size_px" in typo:
            v = _safe_int(typo["heading_size_px"], clean["typography"]["heading_size_px"])
            clean["typography"]["heading_size_px"] = int(_clamp(v, 24, 120))
        if "body_size_px" in typo:
            v = _safe_int(typo["body_size_px"], clean["typography"]["body_size_px"])
            clean["typography"]["body_size_px"] = int(_clamp(v, 14, 60))
        if "line_height" in typo:
            v = _safe_float(typo["line_height"], clean["typography"]["line_height"])
            clean["typography"]["line_height"] = float(_clamp(v, 0.8, 2.5))

    # Layout
    if "layout" in spec and isinstance(spec["layout"], dict):
        lay = spec["layout"]
        if "padding_px" in lay:
            v = _safe_int(lay["padding_px"], clean["layout"]["padding_px"])
            clean["layout"]["padding_px"] = int(_clamp(v, 20, 160))
        if "corner_radius_px" in lay:
            v = _safe_int(lay["corner_radius_px"], clean["layout"]["corner_radius_px"])
            clean["layout"]["corner_radius_px"] = int(_clamp(v, 0, 60))
        for bool_key in ["show_slide_counter", "show_brand_footer", "accent_line", "decorative_orbs"]:
            if bool_key in lay and isinstance(lay[bool_key], bool):
                clean["layout"][bool_key] = lay[bool_key]
        if "accent_line_width_px" in lay:
            v = _safe_int(lay["accent_line_width_px"], clean["layout"]["accent_line_width_px"])
            clean["layout"]["accent_line_width_px"] = int(_clamp(v, 0, 200))
        if "brand_position" in lay and lay["brand_position"] in ("bottom", "top", "none"):
            clean["layout"]["brand_position"] = lay["brand_position"]

    # Slide layouts
    if "slide_layouts" in spec and isinstance(spec["slide_layouts"], dict):
        for slide_type, allowed in ALLOWED_SLIDE_LAYOUTS.items():
            if slide_type in spec["slide_layouts"]:
                val = str(spec["slide_layouts"][slide_type])
                if val in allowed:
                    clean["slide_layouts"][slide_type] = val

    # Images
    if "images" in spec and isinstance(spec["images"], dict):
        for key in ("logo_url", "background_image_url"):
            if key in spec["images"] and isinstance(spec["images"][key], str):
                url = spec["images"][key].strip()
                if url == "" or (url.startswith("https://") and len(url) <= 2048):
                    clean["images"][key] = url

    return clean


# ─────────────────────────────────────────────────────────────────────
# HTML escaping
# ─────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _esc_keep_strong(text: str) -> str:
    """HTML-escape but preserve **bold** → <strong>."""
    escaped = _esc(text)
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)


# ─────────────────────────────────────────────────────────────────────
# Adaptive font sizing (matches carousel_renderer.py behavior)
# ─────────────────────────────────────────────────────────────────────

def _adaptive_heading_size(text: str, base_size: int) -> int:
    """Scale heading font size down for longer text."""
    length = len(text)
    if length < 30:
        return base_size
    if length < 50:
        return max(int(base_size * 0.85), 36)
    if length < 80:
        return max(int(base_size * 0.72), 32)
    return max(int(base_size * 0.6), 28)


def _adaptive_body_size(text: str, base_size: int) -> int:
    """Scale body font size down for longer text."""
    length = len(text)
    if length < 80:
        return base_size
    if length < 150:
        return max(int(base_size * 0.9), 24)
    if length < 250:
        return max(int(base_size * 0.8), 22)
    if length < 400:
        return max(int(base_size * 0.75), 20)
    return max(int(base_size * 0.65), 18)


# ─────────────────────────────────────────────────────────────────────
# Google Fonts import URL builder
# ─────────────────────────────────────────────────────────────────────

def _google_fonts_import(spec: dict) -> str:
    """Build @import URL for Google Fonts used in the spec."""
    fonts = set()
    typo = spec.get("typography", {})
    for key in ("heading_font", "body_font"):
        font = typo.get(key, "Inter")
        if font and font != "Inter":  # Inter is loaded via file://
            fonts.add(font)

    if not fonts:
        return ""

    parts = []
    for font in sorted(fonts):
        family = font.replace(" ", "+")
        parts.append(f"family={family}:wght@400;600;700;800;900")
    url = "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"
    return f"@import url('{url}');"


# ─────────────────────────────────────────────────────────────────────
# Base CSS generator (from design_spec)
# ─────────────────────────────────────────────────────────────────────

def _background_image_css(spec: dict) -> str:
    """Generate CSS for background image overlay if present in spec."""
    bg_url = spec.get("images", {}).get("background_image_url", "")
    if not bg_url:
        return ""
    return f"""
        body::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background: url('{bg_url}') center/cover no-repeat;
            opacity: 0.25;
            z-index: 0;
        }}"""


def _generate_base_css(spec: dict, width: int, height: int) -> str:
    """Generate the base CSS from a DesignSystemSpec."""
    colors = spec["colors"]
    typo = spec["typography"]
    layout = spec["layout"]
    padding = layout["padding_px"]

    bg = colors["background"]
    # Determine if background is a gradient or solid color
    if bg.startswith("linear-gradient") or bg.startswith("radial-gradient"):
        bg_css = f"background: {bg};"
    else:
        bg_css = f"background-color: {bg};"

    google_import = _google_fonts_import(spec)

    # Build font-face for Inter (local file, same as carousel_renderer.py)
    inter_face = ""
    if typo["heading_font"] == "Inter" or typo["body_font"] == "Inter":
        inter_face = """
        @font-face {
            font-family: 'Inter';
            src: url('file:///usr/share/fonts/truetype/inter/Inter-VariableFont_opsz,wght.ttf') format('truetype');
            font-weight: 100 900;
        }"""

    orb_css = ""
    if layout.get("decorative_orbs", False):
        accent = colors.get("accent", "#7c5ce7")
        accent2 = colors.get("accent2", accent)
        orb_css = f"""
        .orb {{
            position: absolute;
            border-radius: 50%;
            filter: blur(80px);
            opacity: 0.15;
            z-index: 0;
        }}
        .orb-1 {{
            width: 400px; height: 400px;
            background: {accent};
            top: -100px; right: -100px;
        }}
        .orb-2 {{
            width: 300px; height: 300px;
            background: {accent2};
            bottom: -50px; left: -80px;
        }}"""

    return f"""
        {inter_face}
        {google_import}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            width: {width}px;
            height: {height}px;
            overflow: hidden;
            {bg_css}
            font-family: '{typo["body_font"]}', 'Inter', sans-serif;
            font-weight: {typo["body_weight"]};
            color: {colors["primary_text"]};
            position: relative;
        }}

        .slide-container {{
            position: relative;
            width: 100%;
            height: 100%;
            padding: {padding}px;
            display: flex;
            flex-direction: column;
            z-index: 1;
        }}

        h1, .heading {{
            font-family: '{typo["heading_font"]}', 'Inter', sans-serif;
            font-weight: {typo["heading_weight"]};
            line-height: {typo["line_height"]};
            color: {colors["primary_text"]};
        }}

        .body-text {{
            font-family: '{typo["body_font"]}', 'Inter', sans-serif;
            font-weight: {typo["body_weight"]};
            color: {colors["secondary_text"]};
            line-height: 1.6;
        }}

        .accent-line {{
            width: {layout["accent_line_width_px"]}px;
            height: 5px;
            background: {colors["accent"]};
            border-radius: 3px;
            margin: 16px 0;
        }}

        .slide-counter {{
            position: absolute;
            top: {padding}px;
            right: {padding}px;
            font-size: 18px;
            color: {colors["secondary_text"]};
            font-weight: 600;
            z-index: 2;
        }}

        .brand-footer {{
            position: absolute;
            bottom: {padding - 36}px;
            left: {padding}px;
            right: {padding}px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 2;
        }}

        .brand-name {{
            font-weight: 700;
            font-size: 20px;
            color: {colors["primary_text"]};
        }}

        .brand-handle {{
            font-size: 18px;
            color: {colors["secondary_text"]};
        }}

        .cta-button {{
            display: inline-block;
            padding: 18px 48px;
            background: linear-gradient(135deg, {colors["accent"]}, {colors.get("accent2", colors["accent"])});
            color: {colors["primary_text"]};
            border-radius: {max(layout["corner_radius_px"], 30)}px;
            font-size: 24px;
            font-weight: 700;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }}

        .card-bg {{
            background: {colors.get("card_bg", "rgba(255,255,255,0.06)")};
            border-radius: {layout["corner_radius_px"]}px;
            padding: 24px;
        }}

        strong {{
            font-weight: 700;
            color: {colors["primary_text"]};
        }}

        {orb_css}
        {_background_image_css(spec)}
    """


# ─────────────────────────────────────────────────────────────────────
# Slide HTML generators — one function per slide type
# ─────────────────────────────────────────────────────────────────────

def _render_cover(spec: dict, content: dict, width: int, height: int,
                  slide_num: int, total_slides: int,
                  brand_name: str, brand_handle: str) -> str:
    """Render a cover slide."""
    colors = spec["colors"]
    typo = spec["typography"]
    layout = spec["layout"]

    title = content.get("title", "")
    subtitle = content.get("subtitle", "")

    title_size = _adaptive_heading_size(title, typo["heading_size_px"])
    subtitle_size = max(int(title_size * 0.4), 20)

    accent_line_html = ""
    if layout.get("accent_line", False):
        accent_line_html = '<div class="accent-line"></div>'

    counter_html = ""
    if layout.get("show_slide_counter", False):
        counter_html = f'<div class="slide-counter">{slide_num}/{total_slides}</div>'

    brand_html = ""
    if layout.get("show_brand_footer", False) and brand_name:
        brand_html = f"""
        <div class="brand-footer">
            <span class="brand-name">{_esc(brand_name)}</span>
            <span class="brand-handle">{_esc(brand_handle)}</span>
        </div>"""

    orbs_html = ""
    if layout.get("decorative_orbs", False):
        orbs_html = '<div class="orb orb-1"></div><div class="orb orb-2"></div>'

    logo_html = ""
    logo_url = spec.get("images", {}).get("logo_url", "")
    if logo_url:
        logo_html = f'<img src="{_esc(logo_url)}" style="height:50px;width:auto;margin-bottom:16px;" />'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
{_generate_base_css(spec, width, height)}
.cover-content {{
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.cover-title {{
    font-size: {title_size}px;
}}
.cover-subtitle {{
    font-size: {subtitle_size}px;
    color: {colors["secondary_text"]};
    margin-top: 16px;
}}
</style>
</head>
<body>
{orbs_html}
{counter_html}
<div class="slide-container">
    {logo_html}
    <div class="cover-content">
        <h1 class="heading cover-title">{_esc_keep_strong(title)}</h1>
        {accent_line_html}
        <p class="body-text cover-subtitle">{_esc_keep_strong(subtitle)}</p>
    </div>
</div>
{brand_html}
</body>
</html>"""


def _render_content(spec: dict, content: dict, width: int, height: int,
                    slide_num: int, total_slides: int,
                    brand_name: str, brand_handle: str) -> str:
    """Render a content slide (header + body paragraphs)."""
    colors = spec["colors"]
    typo = spec["typography"]
    layout = spec["layout"]

    header = content.get("header", "")
    body = content.get("body", "")

    header_size = _adaptive_heading_size(header, min(typo["heading_size_px"], 56))
    body_size = _adaptive_body_size(body, typo["body_size_px"])

    # Split body into paragraphs
    body_paragraphs = [p.strip() for p in body.split("\n") if p.strip()]
    body_html = "\n".join(
        f'<p class="body-text" style="font-size:{body_size}px;margin-bottom:12px;">'
        f'{_esc_keep_strong(p)}</p>'
        for p in body_paragraphs
    )

    accent_line_html = ""
    if layout.get("accent_line", False) and header:
        accent_line_html = '<div class="accent-line"></div>'

    counter_html = ""
    if layout.get("show_slide_counter", False):
        counter_html = f'<div class="slide-counter">{slide_num}/{total_slides}</div>'

    brand_html = ""
    if layout.get("show_brand_footer", False) and brand_name:
        brand_html = f"""
        <div class="brand-footer">
            <span class="brand-name">{_esc(brand_name)}</span>
            <span class="brand-handle">{_esc(brand_handle)}</span>
        </div>"""

    orbs_html = ""
    if layout.get("decorative_orbs", False):
        orbs_html = '<div class="orb orb-1"></div><div class="orb orb-2"></div>'

    header_html = ""
    if header:
        header_html = f'<h1 class="heading" style="font-size:{header_size}px;">{_esc_keep_strong(header)}</h1>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
{_generate_base_css(spec, width, height)}
.content-body {{
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
</style>
</head>
<body>
{orbs_html}
{counter_html}
<div class="slide-container">
    <div class="content-body">
        {header_html}
        {accent_line_html}
        <div style="margin-top:16px;">
            {body_html}
        </div>
    </div>
</div>
{brand_html}
</body>
</html>"""


def _render_list(spec: dict, content: dict, width: int, height: int,
                 slide_num: int, total_slides: int,
                 brand_name: str, brand_handle: str) -> str:
    """Render a list slide (header + bullet points)."""
    colors = spec["colors"]
    typo = spec["typography"]
    layout = spec["layout"]

    header = content.get("header", "")
    items = content.get("items", [])
    if isinstance(items, str):
        # Parse bullet text into list items
        items = [re.sub(r'^[\s•\-\*►▸▹·✓✔→]+', '', line).strip()
                 for line in items.split("\n") if line.strip()]

    header_size = _adaptive_heading_size(header, min(typo["heading_size_px"], 52))
    item_size = _adaptive_body_size("\n".join(items), typo["body_size_px"])
    item_size = max(item_size, 20)

    items_html = "\n".join(
        f'<li style="font-size:{item_size}px;margin-bottom:12px;padding-left:8px;">'
        f'{_esc_keep_strong(item)}</li>'
        for item in items[:8]  # Max 8 items to avoid overflow
    )

    accent_line_html = ""
    if layout.get("accent_line", False):
        accent_line_html = '<div class="accent-line"></div>'

    counter_html = ""
    if layout.get("show_slide_counter", False):
        counter_html = f'<div class="slide-counter">{slide_num}/{total_slides}</div>'

    brand_html = ""
    if layout.get("show_brand_footer", False) and brand_name:
        brand_html = f"""
        <div class="brand-footer">
            <span class="brand-name">{_esc(brand_name)}</span>
            <span class="brand-handle">{_esc(brand_handle)}</span>
        </div>"""

    orbs_html = ""
    if layout.get("decorative_orbs", False):
        orbs_html = '<div class="orb orb-1"></div><div class="orb orb-2"></div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
{_generate_base_css(spec, width, height)}
.list-content {{
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
ul {{
    list-style: none;
    margin-top: 20px;
}}
ul li::before {{
    content: '';
    display: inline-block;
    width: 10px;
    height: 10px;
    background: {colors["accent"]};
    border-radius: 50%;
    margin-right: 16px;
    vertical-align: middle;
}}
</style>
</head>
<body>
{orbs_html}
{counter_html}
<div class="slide-container">
    <div class="list-content">
        <h1 class="heading" style="font-size:{header_size}px;">{_esc_keep_strong(header)}</h1>
        {accent_line_html}
        <ul>
            {items_html}
        </ul>
    </div>
</div>
{brand_html}
</body>
</html>"""


def _render_cta(spec: dict, content: dict, width: int, height: int,
                slide_num: int, total_slides: int,
                brand_name: str, brand_handle: str) -> str:
    """Render a CTA (call-to-action) slide."""
    colors = spec["colors"]
    typo = spec["typography"]
    layout = spec["layout"]

    text = content.get("text", "")
    button_text = content.get("button", "")

    text_size = _adaptive_body_size(text, typo["body_size_px"])

    counter_html = ""
    if layout.get("show_slide_counter", False):
        counter_html = f'<div class="slide-counter">{slide_num}/{total_slides}</div>'

    brand_html = ""
    if layout.get("show_brand_footer", False) and brand_name:
        brand_html = f"""
        <div class="brand-footer">
            <span class="brand-name">{_esc(brand_name)}</span>
            <span class="brand-handle">{_esc(brand_handle)}</span>
        </div>"""

    orbs_html = ""
    if layout.get("decorative_orbs", False):
        orbs_html = '<div class="orb orb-1"></div><div class="orb orb-2"></div>'

    button_html = ""
    if button_text:
        button_html = f'<div class="cta-button" style="margin-top:32px;">{_esc(button_text)}</div>'

    follow_html = f"""
    <p style="font-size:18px;color:{colors["secondary_text"]};margin-top:24px;text-align:center;">
        Salva questo post &bull; Condividi con un collega
    </p>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
{_generate_base_css(spec, width, height)}
.cta-content {{
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
}}
</style>
</head>
<body>
{orbs_html}
{counter_html}
<div class="slide-container">
    <div class="cta-content">
        <p class="body-text" style="font-size:{text_size}px;">{_esc_keep_strong(text)}</p>
        {button_html}
        {follow_html}
    </div>
</div>
{brand_html}
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────
# Public API: render individual slides and full templates
# ─────────────────────────────────────────────────────────────────────

SLIDE_RENDERERS = {
    "cover": _render_cover,
    "content": _render_content,
    "list": _render_list,
    "cta": _render_cta,
}

ASPECT_DIMENSIONS = {
    "1:1": (1080, 1080),
    "4:3": (1080, 810),
    "3:4": (1080, 1440),
}


def render_instagram_slide(
    spec: dict,
    slide_type: str,
    content: dict,
    aspect_ratio: str = "1:1",
    slide_num: int = 1,
    total_slides: int = 1,
    brand_name: str = "",
    brand_handle: str = "",
) -> str:
    """Render a single Instagram slide to HTML from a DesignSystemSpec.

    Args:
        spec: A validated DesignSystemSpec dict
        slide_type: One of "cover", "content", "list", "cta"
        content: Dict with type-specific keys:
            cover:   {"title": "...", "subtitle": "..."}
            content: {"header": "...", "body": "..."}
            list:    {"header": "...", "items": ["...", "..."]}
            cta:     {"text": "...", "button": "..."}
        aspect_ratio: "1:1", "4:3", or "3:4"
        slide_num: Current slide number (for counter)
        total_slides: Total slides (for counter)
        brand_name: Brand name for footer
        brand_handle: Brand handle for footer

    Returns:
        Complete HTML string ready for Playwright rendering.
    """
    renderer = SLIDE_RENDERERS.get(slide_type, _render_content)
    width, height = ASPECT_DIMENSIONS.get(aspect_ratio, (1080, 1080))
    return renderer(spec, content, width, height, slide_num, total_slides,
                    brand_name, brand_handle)


def render_instagram_template(
    spec: dict,
    slides_content: list[dict],
    aspect_ratio: str = "1:1",
    brand_name: str = "",
    brand_handle: str = "",
) -> dict[str, str]:
    """Render all slides for a carousel from a DesignSystemSpec.

    Args:
        spec: A validated DesignSystemSpec dict
        slides_content: List of dicts, each with "type" + type-specific content keys.
            Example: [
                {"type": "cover", "title": "Hello", "subtitle": "World"},
                {"type": "content", "header": "Key Point", "body": "Details here"},
                {"type": "list", "header": "Steps", "items": ["One", "Two"]},
                {"type": "cta", "text": "Follow me!", "button": "Save"},
            ]
        aspect_ratio: "1:1", "4:3", or "3:4"
        brand_name: Brand name for footer
        brand_handle: Brand handle for footer

    Returns:
        Dict mapping slide index to HTML: {"0": "<html>...", "1": "<html>...", ...}
    """
    total = len(slides_content)
    result = {}
    for i, slide in enumerate(slides_content):
        slide_type = slide.get("type", "content")
        content = {k: v for k, v in slide.items() if k != "type"}
        html = render_instagram_slide(
            spec, slide_type, content,
            aspect_ratio=aspect_ratio,
            slide_num=i + 1,
            total_slides=total,
            brand_name=brand_name,
            brand_handle=brand_handle,
        )
        result[str(i)] = html
    return result


def render_preview_slides(
    spec: dict,
    aspect_ratio: str = "1:1",
    brand_name: str = "Il Tuo Brand",
    brand_handle: str = "@tuobrand",
) -> dict[str, str]:
    """Render preview slides with example content for all 4 slide types.

    Returns: {"cover": "<html>...", "content": "<html>...", "list": "<html>...", "cta": "<html>..."}
    """
    example_content = {
        "cover": {"title": "Strategia di Marketing", "subtitle": "5 idee per crescere online"},
        "content": {"header": "Perché funziona", "body": "Contenuti chiari e visivi migliorano\nl'engagement sui social."},
        "list": {"header": "3 cose da fare", "items": ["Ottimizza il profilo", "Pubblica contenuti utili", "Usa CTA chiare"]},
        "cta": {"text": "Seguici per altri contenuti", "button": "@tuobrand"},
    }

    result = {}
    slide_types = ["cover", "content", "list", "cta"]
    for i, slide_type in enumerate(slide_types):
        result[slide_type] = render_instagram_slide(
            spec, slide_type, example_content[slide_type],
            aspect_ratio=aspect_ratio,
            slide_num=i + 1,
            total_slides=4,
            brand_name=brand_name,
            brand_handle=brand_handle,
        )
    return result


# ─────────────────────────────────────────────────────────────────────
# Carousel text parser → structured content
# (Bridges old ---SLIDE--- text format to new structured content)
# ─────────────────────────────────────────────────────────────────────

def parse_carousel_text_to_content(text: str) -> list[dict]:
    """Parse carousel text (---SLIDE--- delimited) into structured slide content dicts.

    This bridges the existing content generation output (which produces ---SLIDE--- text)
    with the new DesignSystemSpec renderer.
    """
    # Split on ---SLIDE--- or ---CAPTION--- (same as carousel_renderer.py)
    parts = re.split(r'---\s*SLIDE\s*---', text, flags=re.IGNORECASE)
    # Remove caption section
    clean_parts = []
    for part in parts:
        caption_split = re.split(r'---\s*CAPTION\s*---', part, flags=re.IGNORECASE)
        clean_parts.append(caption_split[0].strip())
    slides_text = [p for p in clean_parts if p]

    if not slides_text:
        return []

    result = []
    total = len(slides_text)

    # CTA keywords (same as carousel_renderer.py:463-468)
    CTA_KEYWORDS = [
        "segui", "follow", "salva", "save", "condividi", "share",
        "iscriviti", "subscribe", "commenta", "comment", "like",
        "link in bio", "scopri", "clicca", "tap", "swipe",
        "metti like", "lascia un", "tagga", "repost",
    ]

    BULLET_MARKERS = re.compile(r'^[\s]*[•\-\*✓✔→▸▹►·]|\d+[\.\)]\s')

    for idx, slide_text in enumerate(slides_text):
        lines = [l.strip() for l in slide_text.split("\n") if l.strip()]
        if not lines:
            continue

        # Detect slide type (same logic as carousel_renderer.py:452-485)
        if idx == 0:
            slide_type = "cover"
        elif idx == total - 1 and total > 2:
            lower_text = slide_text.lower()
            if any(kw in lower_text for kw in CTA_KEYWORDS):
                slide_type = "cta"
            else:
                # Check for bullet list
                bullet_count = sum(1 for l in lines if BULLET_MARKERS.match(l))
                slide_type = "list" if len(lines) > 1 and bullet_count / len(lines) >= 0.5 else "content"
        else:
            bullet_count = sum(1 for l in lines if BULLET_MARKERS.match(l))
            slide_type = "list" if len(lines) > 1 and bullet_count / len(lines) >= 0.5 else "content"

        # Build structured content based on type
        if slide_type == "cover":
            result.append({
                "type": "cover",
                "title": lines[0],
                "subtitle": " ".join(lines[1:]) if len(lines) > 1 else "",
            })
        elif slide_type == "content":
            header = ""
            body_lines = lines
            if len(lines) > 1 and len(lines[0]) < 60:
                header = lines[0]
                body_lines = lines[1:]
            result.append({
                "type": "content",
                "header": header,
                "body": "\n".join(body_lines),
            })
        elif slide_type == "list":
            header = ""
            item_lines = lines
            if len(lines) > 1 and len(lines[0]) < 60 and not BULLET_MARKERS.match(lines[0]):
                header = lines[0]
                item_lines = lines[1:]
            items = [re.sub(r'^[\s•\-\*►▸▹·✓✔→]+', '', l).strip() for l in item_lines]
            items = [re.sub(r'^\d+[\.\)]\s*', '', l) for l in items]
            result.append({
                "type": "list",
                "header": header,
                "items": [i for i in items if i],
            })
        elif slide_type == "cta":
            text_lines = lines
            button = ""
            if len(lines) > 1 and len(lines[-1]) < 40:
                button = lines[-1]
                text_lines = lines[:-1]
            result.append({
                "type": "cta",
                "text": "\n".join(text_lines),
                "button": button,
            })

    return result


# ─────────────────────────────────────────────────────────────────────
# Preset design specs
# ─────────────────────────────────────────────────────────────────────

PRESET_SPECS: dict[str, dict] = {
    "minimal_industrial": {
        "theme_name": "Minimal Industrial",
        "colors": {
            "background": "linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 100%)",
            "primary_text": "#ffffff",
            "secondary_text": "rgba(255,255,255,0.6)",
            "accent": "#7c5ce7",
            "accent2": "#a29bfe",
            "card_bg": "rgba(255,255,255,0.05)",
        },
        "typography": {
            "heading_font": "Syne",
            "body_font": "Inter",
            "heading_weight": 800,
            "body_weight": 400,
            "heading_size_px": 72,
            "body_size_px": 32,
            "line_height": 1.2,
        },
        "layout": {
            "padding_px": 80,
            "corner_radius_px": 0,
            "show_slide_counter": True,
            "show_brand_footer": True,
            "accent_line": True,
            "accent_line_width_px": 64,
            "decorative_orbs": True,
            "brand_position": "bottom",
        },
        "slide_layouts": {
            "cover": "cover_centered",
            "content": "header_body",
            "list": "header_bullets",
            "cta": "cta_centered",
        },
        "images": {"logo_url": "", "background_image_url": ""},
    },
    "warm_gradient": {
        "theme_name": "Warm Gradient",
        "colors": {
            "background": "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
            "primary_text": "#ffffff",
            "secondary_text": "rgba(255,255,255,0.7)",
            "accent": "#e94560",
            "accent2": "#ff6b81",
            "card_bg": "rgba(255,255,255,0.06)",
        },
        "typography": {
            "heading_font": "Montserrat",
            "body_font": "Inter",
            "heading_weight": 700,
            "body_weight": 400,
            "heading_size_px": 64,
            "body_size_px": 30,
            "line_height": 1.3,
        },
        "layout": {
            "padding_px": 72,
            "corner_radius_px": 16,
            "show_slide_counter": True,
            "show_brand_footer": True,
            "accent_line": True,
            "accent_line_width_px": 48,
            "decorative_orbs": True,
            "brand_position": "bottom",
        },
        "slide_layouts": {
            "cover": "cover_centered",
            "content": "header_body",
            "list": "header_bullets",
            "cta": "cta_centered",
        },
        "images": {"logo_url": "", "background_image_url": ""},
    },
    "teal_fresh": {
        "theme_name": "Teal Fresh",
        "colors": {
            "background": "linear-gradient(135deg, #0a0f0d 0%, #1a3a2a 50%, #0d1f17 100%)",
            "primary_text": "#ffffff",
            "secondary_text": "rgba(255,255,255,0.7)",
            "accent": "#00b894",
            "accent2": "#55efc4",
            "card_bg": "rgba(255,255,255,0.06)",
        },
        "typography": {
            "heading_font": "Space Grotesk",
            "body_font": "Inter",
            "heading_weight": 700,
            "body_weight": 400,
            "heading_size_px": 66,
            "body_size_px": 30,
            "line_height": 1.3,
        },
        "layout": {
            "padding_px": 76,
            "corner_radius_px": 8,
            "show_slide_counter": True,
            "show_brand_footer": True,
            "accent_line": True,
            "accent_line_width_px": 56,
            "decorative_orbs": True,
            "brand_position": "bottom",
        },
        "slide_layouts": {
            "cover": "cover_centered",
            "content": "header_body",
            "list": "header_bullets",
            "cta": "cta_centered",
        },
        "images": {"logo_url": "", "background_image_url": ""},
    },
    "clean_light": {
        "theme_name": "Clean Light",
        "colors": {
            "background": "#f8f9fa",
            "primary_text": "#1a1a2e",
            "secondary_text": "#6b7280",
            "accent": "#6c5ce7",
            "accent2": "#a29bfe",
            "card_bg": "#ffffff",
        },
        "typography": {
            "heading_font": "DM Sans",
            "body_font": "Inter",
            "heading_weight": 700,
            "body_weight": 400,
            "heading_size_px": 60,
            "body_size_px": 28,
            "line_height": 1.4,
        },
        "layout": {
            "padding_px": 80,
            "corner_radius_px": 20,
            "show_slide_counter": True,
            "show_brand_footer": True,
            "accent_line": True,
            "accent_line_width_px": 48,
            "decorative_orbs": False,
            "brand_position": "bottom",
        },
        "slide_layouts": {
            "cover": "cover_centered",
            "content": "header_body",
            "list": "header_bullets",
            "cta": "cta_centered",
        },
        "images": {"logo_url": "", "background_image_url": ""},
    },
    "bold_corporate": {
        "theme_name": "Bold Corporate",
        "colors": {
            "background": "#0f172a",
            "primary_text": "#f8fafc",
            "secondary_text": "#94a3b8",
            "accent": "#3b82f6",
            "accent2": "#60a5fa",
            "card_bg": "rgba(255,255,255,0.05)",
        },
        "typography": {
            "heading_font": "Bebas Neue",
            "body_font": "Inter",
            "heading_weight": 400,
            "body_weight": 400,
            "heading_size_px": 80,
            "body_size_px": 28,
            "line_height": 1.1,
        },
        "layout": {
            "padding_px": 72,
            "corner_radius_px": 0,
            "show_slide_counter": True,
            "show_brand_footer": True,
            "accent_line": True,
            "accent_line_width_px": 80,
            "decorative_orbs": False,
            "brand_position": "bottom",
        },
        "slide_layouts": {
            "cover": "cover_centered",
            "content": "header_body",
            "list": "header_bullets",
            "cta": "cta_centered",
        },
        "images": {"logo_url": "", "background_image_url": ""},
    },
}
