"""Pillow-based deterministic slide renderer for Instagram carousels.

Renders slides from three inputs:
  - **template** — layout, fonts, colors, spacing (JSON dict)
  - **content**  — structured text from the LLM (title, subtitle, bullets, cta)
  - **asset**    — optional background/overlay image (PIL Image or URL)

Output: list of PNG byte buffers, one per slide (1080x1080 by default).

No HTML, no browser, no Playwright.  Pure pixel-level rendering with Pillow.
"""

from __future__ import annotations

import io
import logging
import os
import textwrap
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

    # Map font family names to filenames we might have
    candidates = []
    if family.lower() == "inter":
        candidates = ["InterVariable.ttf", "Inter.ttc"]
    elif family.lower() == "playfair display":
        candidates = ["PlayfairDisplay-VariableFont_wght.ttf"]
    else:
        # Try the family name as a filename
        candidates = [f"{family}.ttf", f"{family}.ttc"]

    # Always add Inter as fallback
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

    # Ultimate fallback: Pillow default
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
# Text wrapping helper
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
# Individual slide renderers
# ---------------------------------------------------------------------------

def _render_cover(
    template: dict, content: dict, asset_img: Optional[Image.Image],
) -> Image.Image:
    """Render the cover slide: big title + subtitle over background."""
    colors = template["colors"]
    typo = template["typography"]
    layout = template["layout"]
    w, h = layout["width"], layout["height"]
    pad = layout["padding"]

    bg_color = _parse_color(colors["background"])
    img = Image.new("RGBA", (w, h), bg_color)

    # Composite asset as background if available
    if asset_img:
        asset_resized = asset_img.resize((w, h), Image.LANCZOS)
        # Darken overlay for text readability
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 140))
        img = Image.alpha_composite(img, asset_resized.convert("RGBA"))
        img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    text_area_w = w - 2 * pad

    # Accent line
    if layout.get("accent_line"):
        accent_color = _parse_color(colors["accent"])
        line_w = layout.get("accent_line_width", 64)
        line_h = layout.get("accent_line_height", 5)
        draw.rectangle(
            [pad, h // 2 - 120, pad + line_w, h // 2 - 120 + line_h],
            fill=accent_color,
        )

    # Title
    title = content.get("title", "")
    title_font = _resolve_font(
        template["fonts"]["title"], typo["title_size"], typo["title_weight"]
    )
    title_lines = _wrap_text(draw, title, title_font, text_area_w)
    y = h // 2 - 100
    for line in title_lines:
        draw.text((pad, y), line, fill=_parse_color(colors["text"]), font=title_font)
        bbox = draw.textbbox((0, 0), line, font=title_font)
        y += (bbox[3] - bbox[1]) + 10

    # Subtitle
    subtitle = content.get("subtitle", "")
    if subtitle:
        sub_font = _resolve_font(
            template["fonts"]["body"], typo["subtitle_size"], typo["subtitle_weight"]
        )
        y += 20
        sub_lines = _wrap_text(draw, subtitle, sub_font, text_area_w)
        for line in sub_lines:
            draw.text(
                (pad, y), line,
                fill=_parse_color(colors.get("secondary_text", colors["text"])),
                font=sub_font,
            )
            bbox = draw.textbbox((0, 0), line, font=sub_font)
            y += (bbox[3] - bbox[1]) + 8

    # Slide counter
    if layout.get("show_slide_counter"):
        counter_font = _resolve_font(template["fonts"]["body"], 24)
        draw.text(
            (w - pad - 40, h - pad),
            "1",
            fill=_parse_color(colors.get("secondary_text", colors["text"])),
            font=counter_font,
        )

    return img


def _render_text(
    template: dict, content: dict, asset_img: Optional[Image.Image],
    slide_number: int = 2,
) -> Image.Image:
    """Render a text/content slide: subtitle heading + body text."""
    colors = template["colors"]
    typo = template["typography"]
    layout = template["layout"]
    w, h = layout["width"], layout["height"]
    pad = layout["padding"]

    bg_color = _parse_color(colors["background"])
    img = Image.new("RGBA", (w, h), bg_color)

    if asset_img:
        asset_resized = asset_img.resize((w, h), Image.LANCZOS)
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 160))
        img = Image.alpha_composite(img, asset_resized.convert("RGBA"))
        img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    text_area_w = w - 2 * pad

    # Heading
    heading = content.get("subtitle", content.get("title", ""))
    heading_font = _resolve_font(
        template["fonts"]["title"], typo.get("subtitle_size", 36), typo.get("subtitle_weight", 400)
    )
    y = pad + 40

    if layout.get("accent_line"):
        accent_color = _parse_color(colors["accent"])
        draw.rectangle(
            [pad, y, pad + layout.get("accent_line_width", 64), y + layout.get("accent_line_height", 5)],
            fill=accent_color,
        )
        y += 30

    heading_lines = _wrap_text(draw, heading, heading_font, text_area_w)
    for line in heading_lines:
        draw.text((pad, y), line, fill=_parse_color(colors["text"]), font=heading_font)
        bbox = draw.textbbox((0, 0), line, font=heading_font)
        y += (bbox[3] - bbox[1]) + 10

    # Body (use first bullet or body text)
    body = content.get("body", "")
    if not body and content.get("bullets"):
        body = " ".join(content["bullets"][:2])
    if body:
        body_font = _resolve_font(
            template["fonts"]["body"], typo["body_size"], typo["body_weight"]
        )
        y += 40
        body_lines = _wrap_text(draw, body, body_font, text_area_w)
        for line in body_lines:
            draw.text(
                (pad, y), line,
                fill=_parse_color(colors.get("secondary_text", colors["text"])),
                font=body_font,
            )
            bbox = draw.textbbox((0, 0), line, font=body_font)
            y += (bbox[3] - bbox[1]) + 10

    if layout.get("show_slide_counter"):
        counter_font = _resolve_font(template["fonts"]["body"], 24)
        draw.text(
            (w - pad - 40, h - pad),
            str(slide_number),
            fill=_parse_color(colors.get("secondary_text", colors["text"])),
            font=counter_font,
        )

    return img


def _render_list(
    template: dict, content: dict, asset_img: Optional[Image.Image],
    slide_number: int = 3,
) -> Image.Image:
    """Render a list/bullets slide."""
    colors = template["colors"]
    typo = template["typography"]
    layout = template["layout"]
    w, h = layout["width"], layout["height"]
    pad = layout["padding"]

    bg_color = _parse_color(colors["background"])
    img = Image.new("RGBA", (w, h), bg_color)

    if asset_img:
        asset_resized = asset_img.resize((w, h), Image.LANCZOS)
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 160))
        img = Image.alpha_composite(img, asset_resized.convert("RGBA"))
        img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    text_area_w = w - 2 * pad

    # Heading
    heading = content.get("subtitle", content.get("title", ""))
    heading_font = _resolve_font(
        template["fonts"]["title"], typo.get("subtitle_size", 36), typo.get("subtitle_weight", 400)
    )
    y = pad + 40

    if layout.get("accent_line"):
        accent_color = _parse_color(colors["accent"])
        draw.rectangle(
            [pad, y, pad + layout.get("accent_line_width", 64), y + layout.get("accent_line_height", 5)],
            fill=accent_color,
        )
        y += 30

    heading_lines = _wrap_text(draw, heading, heading_font, text_area_w)
    for line in heading_lines:
        draw.text((pad, y), line, fill=_parse_color(colors["text"]), font=heading_font)
        bbox = draw.textbbox((0, 0), line, font=heading_font)
        y += (bbox[3] - bbox[1]) + 10

    # Bullets
    bullets = content.get("bullets", [])
    bullet_font = _resolve_font(
        template["fonts"]["body"], typo["body_size"], typo["body_weight"]
    )
    accent_color = _parse_color(colors["accent"])
    text_color = _parse_color(colors["text"])
    y += 40
    bullet_indent = 30

    for bullet in bullets:
        # Bullet marker (accent colored circle)
        draw.ellipse(
            [pad, y + 8, pad + 12, y + 20],
            fill=accent_color,
        )
        # Bullet text
        bullet_lines = _wrap_text(draw, bullet, bullet_font, text_area_w - bullet_indent)
        for i, line in enumerate(bullet_lines):
            draw.text(
                (pad + bullet_indent, y), line,
                fill=text_color, font=bullet_font,
            )
            bbox = draw.textbbox((0, 0), line, font=bullet_font)
            y += (bbox[3] - bbox[1]) + 8
        y += 16  # gap between bullets

    if layout.get("show_slide_counter"):
        counter_font = _resolve_font(template["fonts"]["body"], 24)
        draw.text(
            (w - pad - 40, h - pad),
            str(slide_number),
            fill=_parse_color(colors.get("secondary_text", colors["text"])),
            font=counter_font,
        )

    return img


def _render_cta(
    template: dict, content: dict, asset_img: Optional[Image.Image],
    slide_number: int = 4,
) -> Image.Image:
    """Render a call-to-action slide: CTA text centered with accent button."""
    colors = template["colors"]
    typo = template["typography"]
    layout = template["layout"]
    w, h = layout["width"], layout["height"]
    pad = layout["padding"]

    bg_color = _parse_color(colors["background"])
    img = Image.new("RGBA", (w, h), bg_color)

    if asset_img:
        asset_resized = asset_img.resize((w, h), Image.LANCZOS)
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 140))
        img = Image.alpha_composite(img, asset_resized.convert("RGBA"))
        img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    text_area_w = w - 2 * pad

    cta_text = content.get("cta", "Scopri di più")
    cta_font = _resolve_font(
        template["fonts"]["title"], typo.get("cta_size", 40), typo.get("cta_weight", 700)
    )

    # Center CTA text
    cta_lines = _wrap_text(draw, cta_text, cta_font, text_area_w - 80)
    total_text_height = 0
    for line in cta_lines:
        bbox = draw.textbbox((0, 0), line, font=cta_font)
        total_text_height += (bbox[3] - bbox[1]) + 10

    # Draw accent button background
    accent_color = _parse_color(colors["accent"])
    btn_pad_x, btn_pad_y = 60, 30
    btn_w = text_area_w - 80
    btn_h = total_text_height + 2 * btn_pad_y
    btn_x = (w - btn_w) // 2
    btn_y = (h - btn_h) // 2

    draw.rounded_rectangle(
        [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
        radius=12,
        fill=accent_color,
    )

    # Draw CTA text centered inside button
    y = btn_y + btn_pad_y
    for line in cta_lines:
        bbox = draw.textbbox((0, 0), line, font=cta_font)
        line_w = bbox[2] - bbox[0]
        x = (w - line_w) // 2
        draw.text((x, y), line, fill=_parse_color(colors["text"]), font=cta_font)
        y += (bbox[3] - bbox[1]) + 10

    # Optional subtitle above button
    subtitle = content.get("subtitle", "")
    if subtitle:
        sub_font = _resolve_font(
            template["fonts"]["body"], typo.get("subtitle_size", 36)
        )
        sub_lines = _wrap_text(draw, subtitle, sub_font, text_area_w)
        sub_y = btn_y - 80
        for line in sub_lines:
            bbox = draw.textbbox((0, 0), line, font=sub_font)
            line_w = bbox[2] - bbox[0]
            x = (w - line_w) // 2
            draw.text(
                (x, sub_y), line,
                fill=_parse_color(colors.get("secondary_text", colors["text"])),
                font=sub_font,
            )
            sub_y += (bbox[3] - bbox[1]) + 8

    if layout.get("show_slide_counter"):
        counter_font = _resolve_font(template["fonts"]["body"], 24)
        draw.text(
            (w - pad - 40, h - pad),
            str(slide_number),
            fill=_parse_color(colors.get("secondary_text", colors["text"])),
            font=counter_font,
        )

    return img


# ---------------------------------------------------------------------------
# Slide-type dispatcher
# ---------------------------------------------------------------------------

_RENDERERS = {
    "cover": _render_cover,
    "text": _render_text,
    "list": _render_list,
    "cta": _render_cta,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_slides(
    template: dict,
    content: dict,
    asset_img: Optional[Image.Image] = None,
) -> list[bytes]:
    """Render all slides defined in the template and return PNG byte buffers.

    Args:
        template: Parsed template dict (from templates/layouts/*.json).
        content:  Structured content from the LLM::

                    {
                      "title": "...",
                      "subtitle": "...",
                      "bullets": ["...", "..."],
                      "cta": "...",
                      "body": "..."   # optional
                    }

        asset_img: Optional PIL Image to use as slide background.

    Returns:
        List of PNG byte buffers, one per slide in template["slides"] order.
    """
    slides_spec = template.get("slides", [
        {"type": "cover"},
        {"type": "text"},
        {"type": "list"},
        {"type": "cta"},
    ])

    png_buffers: list[bytes] = []
    for idx, slide_def in enumerate(slides_spec):
        slide_type = slide_def["type"]
        renderer = _RENDERERS.get(slide_type, _render_text)

        if slide_type == "cover":
            pil_img = renderer(template, content, asset_img)
        else:
            pil_img = renderer(template, content, asset_img, slide_number=idx + 1)

        # Convert to PNG bytes
        buf = io.BytesIO()
        pil_img.convert("RGB").save(buf, format="PNG", optimize=True)
        png_buffers.append(buf.getvalue())
        log.info("[renderer] slide %d (%s) → %d bytes", idx + 1, slide_type, len(buf.getvalue()))

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

    # Local file path
    return Image.open(source)
