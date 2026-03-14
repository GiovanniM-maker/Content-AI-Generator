"""
Carousel image renderer — generates PNG slides from text.
Uses Playwright (headless Chromium) to render HTML/CSS → PNG bytes.

Images are returned as bytes and uploaded to Supabase Storage by the caller.
No local disk writes happen here (critical for ephemeral hosting like Render).
"""

import re
from pathlib import Path
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # Playwright not installed

FONT_PATH = Path(__file__).parent / "static" / "fonts" / "InterVariable.ttf"
FONT_URI = FONT_PATH.as_uri()  # file:///...

# ---------------------------------------------------------------------------
# Slide HTML templates
# ---------------------------------------------------------------------------

# Color palettes for variety
PALETTES = [
    {  # Deep blue → purple
        "bg": "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)",
        "accent": "#7c5ce7",
        "accent2": "#a29bfe",
        "text": "#ffffff",
        "text2": "rgba(255,255,255,0.7)",
        "card_bg": "rgba(255,255,255,0.06)",
    },
    {  # Dark teal → emerald
        "bg": "linear-gradient(135deg, #0a0f0d 0%, #1a3a2a 50%, #0d1f17 100%)",
        "accent": "#00b894",
        "accent2": "#55efc4",
        "text": "#ffffff",
        "text2": "rgba(255,255,255,0.7)",
        "card_bg": "rgba(255,255,255,0.06)",
    },
    {  # Warm dark
        "bg": "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
        "accent": "#e94560",
        "accent2": "#ff6b81",
        "text": "#ffffff",
        "text2": "rgba(255,255,255,0.7)",
        "card_bg": "rgba(255,255,255,0.06)",
    },
]


def _base_css(palette: dict) -> str:
    return f"""
    @font-face {{
        font-family: 'Inter';
        src: url('{FONT_URI}') format('truetype');
        font-weight: 100 900;
        font-style: normal;
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
        width: 1080px;
        height: 1080px;
        background: {palette['bg']};
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: {palette['text']};
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        padding: 90px;
        overflow: hidden;
        position: relative;
    }}

    /* Subtle noise overlay */
    body::before {{
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background-image:
            radial-gradient(circle at 20% 80%, {palette['accent']}11 0%, transparent 50%),
            radial-gradient(circle at 80% 20%, {palette['accent2']}11 0%, transparent 50%);
        pointer-events: none;
    }}

    /* Glow orb */
    .orb {{
        position: absolute;
        width: 500px;
        height: 500px;
        border-radius: 50%;
        background: {palette['accent']};
        opacity: 0.07;
        filter: blur(120px);
    }}
    .orb-1 {{ top: -150px; right: -150px; }}
    .orb-2 {{ bottom: -150px; left: -150px; opacity: 0.04; background: {palette['accent2']}; }}

    .content {{
        position: relative;
        z-index: 1;
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }}

    /* Branding */
    .brand {{
        position: absolute;
        bottom: 44px;
        left: 90px;
        right: 90px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        z-index: 2;
    }}
    .brand-name {{
        font-size: 20px;
        font-weight: 700;
        color: {palette['text2']};
        letter-spacing: 0.5px;
    }}
    .brand-handle {{
        font-size: 18px;
        color: {palette['accent2']};
        font-weight: 600;
    }}

    /* Slide number */
    .slide-num {{
        position: absolute;
        top: 44px;
        right: 90px;
        font-size: 16px;
        color: {palette['text2']};
        font-weight: 600;
        z-index: 2;
    }}

    /* Accent line */
    .accent-line {{
        width: 64px;
        height: 5px;
        background: {palette['accent']};
        border-radius: 3px;
        margin-bottom: 36px;
    }}
    """


def _cover_html(title: str, palette: dict, total_slides: int,
                brand_name: str = "", brand_handle: str = "") -> str:
    """Slide 1: Big bold title — maximum visual impact."""
    title_len = len(title)
    font_size = 80 if title_len < 25 else 68 if title_len < 40 else 56 if title_len < 60 else 46
    return f"""<!DOCTYPE html><html><head><style>
    {_base_css(palette)}
    .content {{
        justify-content: center;
        align-items: flex-start;
    }}
    .cover-title {{
        font-size: {font_size}px;
        font-weight: 900;
        line-height: 1.12;
        letter-spacing: -2px;
        max-width: 880px;
    }}
    .cover-title span {{
        background: linear-gradient(135deg, {palette['accent']} 0%, {palette['accent2']} 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }}
    .swipe {{
        position: absolute;
        bottom: 100px;
        right: 90px;
        font-size: 16px;
        color: {palette['text2']};
        display: flex;
        align-items: center;
        gap: 10px;
        z-index: 2;
    }}
    .swipe-arrow {{
        font-size: 28px;
        color: {palette['accent2']};
        animation: pulse 2s ease-in-out infinite;
    }}
    </style></head><body>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="slide-num">1/{total_slides}</div>
    <div class="content">
        <div class="accent-line"></div>
        <h1 class="cover-title"><span>{_html_esc(title)}</span></h1>
    </div>
    <div class="swipe">Scorri <span class="swipe-arrow">&#8250;</span></div>
    <div class="brand">
        <span class="brand-name">{_html_esc(brand_name)}</span>
        <span class="brand-handle">{_html_esc(brand_handle)}</span>
    </div>
    </body></html>"""


def _content_html(text: str, slide_num: int, total_slides: int, palette: dict,
                   brand_name: str = "", brand_handle: str = "") -> str:
    """Slides 2-N: Content slide with text."""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]

    # Detect if there's a "header" line (short first line)
    header = ""
    body_lines = lines
    if lines and len(lines[0]) < 60 and len(lines) > 1:
        header = lines[0]
        body_lines = lines[1:]

    body_html = ""
    for line in body_lines:
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        body_html += f'<p class="body-line">{_html_esc_keep_tags(line)}</p>'

    header_html = f'<h2 class="slide-header">{_html_esc(header)}</h2>' if header else ''

    # Balanced font sizing — never too small
    total_chars = sum(len(l) for l in body_lines)
    n_lines = len(body_lines)
    if total_chars < 80:
        font_size = 36
    elif total_chars < 150:
        font_size = 32
    elif total_chars < 250:
        font_size = 28
    elif total_chars < 400:
        font_size = 26
    else:
        font_size = 24  # minimum readable

    # Scale header relative to body (not too disproportionate)
    header_size = min(46, font_size + 14)
    line_gap = max(12, 20 - n_lines)

    return f"""<!DOCTYPE html><html><head><style>
    {_base_css(palette)}
    .slide-header {{
        font-size: {header_size}px;
        font-weight: 800;
        color: {palette['accent2']};
        margin-bottom: 24px;
        line-height: 1.18;
        letter-spacing: -0.5px;
    }}
    .body-line {{
        font-size: {font_size}px;
        font-weight: 400;
        line-height: 1.55;
        color: {palette['text']};
        margin-bottom: {line_gap}px;
    }}
    .body-line strong {{
        font-weight: 700;
        color: {palette['accent2']};
    }}
    </style></head><body>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="slide-num">{slide_num}/{total_slides}</div>
    <div class="content">
        <div class="accent-line"></div>
        {header_html}
        {body_html}
    </div>
    <div class="brand">
        <span class="brand-name">{_html_esc(brand_name)}</span>
        <span class="brand-handle">{_html_esc(brand_handle)}</span>
    </div>
    </body></html>"""


def _cta_html(text: str, slide_num: int, total_slides: int, palette: dict,
              brand_name: str = "", brand_handle: str = "") -> str:
    """Final slide: CTA — engagement + follow."""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]

    # Split into CTA message and action items
    cta_lines = []
    action_line = ""
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in ["segui", "follow", "iscriviti", "subscribe"]):
            action_line = line
        else:
            cta_lines.append(line)

    body = '<br>'.join(_html_esc(l) for l in (cta_lines or lines))
    btn_text = _html_esc(action_line) if action_line else "Segui per altri tips"

    # Adaptive font size based on text length
    total_len = sum(len(l) for l in lines)
    cta_font = 34 if total_len < 100 else 30 if total_len < 180 else 26 if total_len < 280 else 22

    return f"""<!DOCTYPE html><html><head><style>
    {_base_css(palette)}
    .content {{
        align-items: center;
        text-align: center;
    }}
    .accent-line {{
        margin: 0 auto 36px;
    }}
    .cta-text {{
        font-size: {cta_font}px;
        font-weight: 600;
        line-height: 1.4;
        max-width: 780px;
    }}
    .cta-action {{
        margin-top: 40px;
    }}
    .cta-btn {{
        display: inline-block;
        padding: 20px 52px;
        background: linear-gradient(135deg, {palette['accent']}, {palette['accent2']});
        color: white;
        font-size: 22px;
        font-weight: 700;
        border-radius: 60px;
        letter-spacing: 0.5px;
        box-shadow: 0 8px 32px {palette['accent']}44;
    }}
    .cta-follow {{
        margin-top: 24px;
        font-size: 16px;
        color: {palette['text2']};
    }}
    </style></head><body>
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="slide-num">{slide_num}/{total_slides}</div>
    <div class="content">
        <div class="accent-line"></div>
        <div class="cta-text">{body}</div>
        <div class="cta-action">
            <span class="cta-btn">{btn_text}</span>
        </div>
        <div class="cta-follow">Salva questo post &bull; Condividi con un collega</div>
    </div>
    <div class="brand">
        <span class="brand-name">{_html_esc(brand_name)}</span>
        <span class="brand-handle">{_html_esc(brand_handle)}</span>
    </div>
    </body></html>"""


def _html_esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _html_esc_keep_tags(text: str) -> str:
    """Escape HTML but keep <strong> tags."""
    text = _html_esc(text)
    text = text.replace('&lt;strong&gt;', '<strong>').replace('&lt;/strong&gt;', '</strong>')
    return text


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def parse_carousel_text(text: str) -> tuple[list[str], str]:
    """Parse ---SLIDE--- / ---CAPTION--- formatted text into slides + caption."""
    parts = re.split(r'---CAPTION---', text, flags=re.IGNORECASE)
    caption = parts[1].strip() if len(parts) > 1 else ""
    slide_text = parts[0]
    slides = [s.strip() for s in re.split(r'---SLIDE---', slide_text, flags=re.IGNORECASE) if s.strip()]
    return slides, caption


def render_carousel(text: str, palette_idx: int = 0,
                    brand_name: str = "", brand_handle: str = "") -> dict:
    """
    Render carousel text into PNG byte arrays (no disk writes).
    Returns: { 'slides_bytes': [bytes, ...], 'caption': '...' }
    """
    slides_text, caption = parse_carousel_text(text)
    if not slides_text:
        return {"slides_bytes": [], "caption": caption, "error": "No slides found"}

    palette = PALETTES[palette_idx % len(PALETTES)]
    total = len(slides_text)

    slides_bytes = []

    if sync_playwright is None:
        raise RuntimeError("Playwright non è installato. Installa con: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 1080})

        for i, slide in enumerate(slides_text):
            # Choose template based on position
            if i == 0:
                html = _cover_html(slide, palette, total,
                                   brand_name=brand_name, brand_handle=brand_handle)
            elif i == total - 1 and total > 2:
                html = _cta_html(slide, i + 1, total, palette,
                                 brand_name=brand_name, brand_handle=brand_handle)
            else:
                html = _content_html(slide, i + 1, total, palette,
                                     brand_name=brand_name, brand_handle=brand_handle)

            page.set_content(html, wait_until="networkidle")
            # Small wait for fonts to load
            page.wait_for_timeout(500)

            png_bytes = page.screenshot(type="png")
            slides_bytes.append(png_bytes)

        browser.close()

    return {"slides_bytes": slides_bytes, "caption": caption}


def render_carousel_async(text: str, palette_idx: int = 0,
                          brand_name: str = "", brand_handle: str = "") -> dict:
    """Wrapper that can be called from Flask thread."""
    return render_carousel(text, palette_idx, brand_name=brand_name, brand_handle=brand_handle)


# ---------------------------------------------------------------------------
# Custom template rendering
# ---------------------------------------------------------------------------

ASPECT_DIMENSIONS = {
    "1:1": (1080, 1080),
    "4:3": (1080, 810),
    "3:4": (1080, 1440),
}


import json as _json


def _detect_slide_type(slide_text: str, index: int, total: int) -> str:
    """
    Auto-detect slide type from content and position.
    Returns: 'cover' | 'content' | 'list' | 'cta'
    """
    # First slide is always cover
    if index == 0:
        return "cover"

    # Last slide with CTA keywords → cta
    if index == total - 1 and total > 2:
        cta_keywords = [
            "segui", "follow", "salva", "save", "condividi", "share",
            "iscriviti", "subscribe", "commenta", "comment", "like",
            "link in bio", "scopri", "clicca", "tap", "swipe",
            "metti like", "lascia un", "tagga", "repost",
        ]
        lower = slide_text.lower()
        if any(kw in lower for kw in cta_keywords):
            return "cta"

    # Detect list patterns: lines starting with bullet markers
    lines = [l.strip() for l in slide_text.strip().split('\n') if l.strip()]
    bullet_markers = ('•', '-', '*', '✓', '✔', '→', '▸', '▹', '►', '·')
    numbered_pattern = re.compile(r'^\d+[\.\)]\s')
    bullet_lines = sum(
        1 for l in lines
        if l.startswith(bullet_markers) or numbered_pattern.match(l)
    )
    # If more than half the lines are bullets, it's a list slide
    if len(lines) >= 2 and bullet_lines >= len(lines) * 0.5:
        return "list"

    return "content"


def _parse_template_html(template_html: str) -> dict:
    """
    Parse template_html which can be either:
    - A raw HTML string (legacy single-template) → {"cover": html, "content": html, "list": html, "cta": html}
    - A JSON string with keys: cover, content, list, cta

    Returns dict with all 4 keys guaranteed.
    """
    if not template_html:
        return {"cover": "", "content": "", "list": "", "cta": ""}

    stripped = template_html.strip()

    # Try JSON first
    if stripped.startswith('{'):
        try:
            parsed = _json.loads(stripped)
            if isinstance(parsed, dict):
                # Ensure all 4 keys exist; fallback to 'content' for missing ones
                fallback = parsed.get("content", "")
                return {
                    "cover": parsed.get("cover", fallback),
                    "content": parsed.get("content", fallback),
                    "list": parsed.get("list", fallback),
                    "cta": parsed.get("cta", fallback),
                }
        except (ValueError, _json.JSONDecodeError):
            pass

    # Legacy: single HTML string — use for all types
    return {"cover": stripped, "content": stripped, "list": stripped, "cta": stripped}


def _inject_font(html: str) -> str:
    """Inject local @font-face for Inter if template doesn't include it."""
    if not html:
        return html
    if "Inter" in html and str(FONT_URI) not in html and "@font-face" not in html:
        font_css = f"""<style>@font-face {{
            font-family: 'Inter';
            src: url('{FONT_URI}') format('truetype');
            font-weight: 100 900; font-style: normal;
        }}</style>"""
        html = html.replace("</head>", f"{font_css}</head>", 1)
    elif "{{FONT_URI}}" in html:
        html = html.replace("{{FONT_URI}}", FONT_URI)
    return html


def _prepare_slide_html(
    template: str,
    slide_text: str,
    slide_type: str,
    index: int,
    total: int,
    brand_name: str,
    brand_handle: str,
) -> str:
    """
    Prepare the final HTML for a single slide by substituting placeholders.

    Multi-type placeholders:
      Cover:   {{COVER_TITLE}}, {{COVER_SUBTITLE}}
      Content: {{CONTENT_HEADER}}, {{CONTENT_BODY}}
      List:    {{LIST_HEADER}}, {{LIST_ITEMS}}
      CTA:     {{CTA_TEXT}}, {{CTA_BUTTON}}
      Legacy:  {{SLIDE_CONTENT}} (all types)
      Common:  {{SLIDE_NUM}}, {{TOTAL_SLIDES}}, {{BRAND_NAME}}, {{BRAND_HANDLE}}
    """
    html = template
    html = _inject_font(html)

    lines = [l.strip() for l in slide_text.strip().split('\n') if l.strip()]

    # --- Process per slide type ---
    if slide_type == "cover":
        # Cover: first line = title, rest = subtitle
        title = lines[0] if lines else ""
        subtitle = ' '.join(lines[1:]) if len(lines) > 1 else ""
        title = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', title)
        subtitle = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', subtitle)
        html = html.replace("{{COVER_TITLE}}", title)
        html = html.replace("{{COVER_SUBTITLE}}", subtitle)

    elif slide_type == "list":
        # List: first short line = header, rest = list items
        header = ""
        item_lines = lines
        if lines and len(lines[0]) < 60 and len(lines) > 1:
            header = lines[0]
            item_lines = lines[1:]
        # Build HTML list items
        items_html = ""
        for item in item_lines:
            # Strip bullet markers
            clean = re.sub(r'^[\•\-\*✓✔→▸▹►·]\s*', '', item)
            clean = re.sub(r'^\d+[\.\)]\s*', '', clean)
            clean = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', clean)
            items_html += f"<li>{_html_esc_keep_tags(clean)}</li>"
        header = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', header)
        html = html.replace("{{LIST_HEADER}}", header)
        html = html.replace("{{LIST_ITEMS}}", items_html)

    elif slide_type == "cta":
        # CTA: main text + optional button text (last line if short)
        cta_text = ""
        button_text = "Segui per altri tips"
        if lines:
            if len(lines) >= 2 and len(lines[-1]) < 40:
                button_text = lines[-1]
                cta_text = '<br>'.join(_html_esc(l) for l in lines[:-1])
            else:
                cta_text = '<br>'.join(_html_esc(l) for l in lines)
        html = html.replace("{{CTA_TEXT}}", cta_text)
        html = html.replace("{{CTA_BUTTON}}", _html_esc(button_text))

    else:  # content
        # Content: first short line = header, rest = body
        header = ""
        body_lines = lines
        if lines and len(lines[0]) < 60 and len(lines) > 1:
            header = lines[0]
            body_lines = lines[1:]
        body_html = ""
        for line in body_lines:
            line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
            body_html += f'<p>{_html_esc_keep_tags(line)}</p>'
        header = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', header)
        html = html.replace("{{CONTENT_HEADER}}", header)
        html = html.replace("{{CONTENT_BODY}}", body_html)

    # --- Legacy fallback: {{SLIDE_CONTENT}} for old templates ---
    processed_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', slide_text)
    processed_text = processed_text.replace('\n', '<br>')
    html = html.replace("{{SLIDE_CONTENT}}", processed_text)

    # --- Common placeholders ---
    html = html.replace("{{SLIDE_NUM}}", str(index + 1))
    html = html.replace("{{TOTAL_SLIDES}}", str(total))
    html = html.replace("{{BRAND_NAME}}", _html_esc(brand_name))
    html = html.replace("{{BRAND_HANDLE}}", _html_esc(brand_handle))

    return html


def render_carousel_from_template(
    text: str,
    template_html: str,
    aspect_ratio: str = "1:1",
    brand_name: str = "",
    brand_handle: str = "",
) -> dict:
    """
    Render carousel text into PNG byte arrays using a custom user template.

    template_html can be:
    - Legacy: a single HTML string with {{SLIDE_CONTENT}} placeholder
    - Multi-type: a JSON string {"cover": "...", "content": "...", "list": "...", "cta": "..."}
      Each type uses its own placeholders (see _prepare_slide_html).

    Returns: { 'slides_bytes': [bytes, ...], 'caption': '...' }
    """
    slides_text, caption = parse_carousel_text(text)
    if not slides_text:
        return {"slides_bytes": [], "caption": caption, "error": "No slides found"}

    total = len(slides_text)
    width, height = ASPECT_DIMENSIONS.get(aspect_ratio, (1080, 1080))
    templates = _parse_template_html(template_html)

    slides_bytes = []

    if sync_playwright is None:
        raise RuntimeError("Playwright non è installato. Installa con: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})

        for i, slide_text in enumerate(slides_text):
            slide_type = _detect_slide_type(slide_text, i, total)
            template = templates.get(slide_type, templates["content"])

            html = _prepare_slide_html(
                template, slide_text, slide_type, i, total, brand_name, brand_handle
            )

            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(500)

            png_bytes = page.screenshot(type="png")
            slides_bytes.append(png_bytes)

        browser.close()

    return {"slides_bytes": slides_bytes, "caption": caption}


def render_carousel_from_template_async(
    text: str,
    template_html: str,
    aspect_ratio: str = "1:1",
    brand_name: str = "",
    brand_handle: str = "",
) -> dict:
    """Wrapper that can be called from Flask thread."""
    return render_carousel_from_template(text, template_html, aspect_ratio, brand_name, brand_handle)


def render_template_preview(
    template_html: str,
    aspect_ratio: str = "1:1",
    brand_name: str = "Il Tuo Brand",
    brand_handle: str = "@tuobrand",
) -> dict:
    """
    Render preview thumbnails for all 4 slide types of a template.
    Uses example content to show how each type looks.

    Returns: { 'cover': bytes, 'content': bytes, 'list': bytes, 'cta': bytes }
    """
    templates = _parse_template_html(template_html)
    width, height = ASPECT_DIMENSIONS.get(aspect_ratio, (1080, 1080))

    example_content = {
        "cover": "5 Strategie di Marketing\nche Cambieranno il Tuo Business nel 2026",
        "content": "Conosci il tuo pubblico\nPrima di qualsiasi strategia, devi capire chi sono i tuoi clienti. **Analizza i dati**, studia i competitor e crea delle buyer personas dettagliate.",
        "list": "Strumenti essenziali\n• **Google Analytics** per il traffico\n• **Canva** per la grafica\n• **Buffer** per la programmazione\n• **ChatGPT** per i copy\n• **Notion** per l'organizzazione",
        "cta": "Ti è stato utile questo contenuto?\nSalva per dopo e condividi\nSegui per altri tips",
    }

    result = {}

    if sync_playwright is None:
        raise RuntimeError("Playwright non è installato")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})

        for slide_type in ("cover", "content", "list", "cta"):
            template = templates.get(slide_type, templates.get("content", ""))
            if not template:
                continue

            html = _prepare_slide_html(
                template,
                example_content[slide_type],
                slide_type,
                index={"cover": 0, "content": 1, "list": 2, "cta": 3}[slide_type],
                total=4,
                brand_name=brand_name,
                brand_handle=brand_handle,
            )

            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(500)
            result[slide_type] = page.screenshot(type="png")

        browser.close()

    return result
