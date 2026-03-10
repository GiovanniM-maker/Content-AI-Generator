"""
Carousel image renderer — generates 1080x1080 PNG slides from text.
Uses Playwright (headless Chromium) to render HTML/CSS → PNG.
"""

import hashlib
import re
from pathlib import Path
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # Playwright not installed (e.g. production Docker)

OUTPUT_DIR = Path(__file__).parent / "static" / "carousel_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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


def _cover_html(title: str, palette: dict, total_slides: int) -> str:
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
        <span class="brand-name">Juan | AI Automation</span>
        <span class="brand-handle">@juan.ai</span>
    </div>
    </body></html>"""


def _content_html(text: str, slide_num: int, total_slides: int, palette: dict) -> str:
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

    total_chars = sum(len(l) for l in body_lines)
    font_size = 34 if total_chars < 120 else 30 if total_chars < 200 else 26 if total_chars < 300 else 22

    return f"""<!DOCTYPE html><html><head><style>
    {_base_css(palette)}
    .slide-header {{
        font-size: 42px;
        font-weight: 800;
        color: {palette['accent2']};
        margin-bottom: 28px;
        line-height: 1.15;
        letter-spacing: -0.5px;
    }}
    .body-line {{
        font-size: {font_size}px;
        font-weight: 400;
        line-height: 1.65;
        color: {palette['text']};
        margin-bottom: 14px;
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
        <span class="brand-name">Juan | AI Automation</span>
        <span class="brand-handle">@juan.ai</span>
    </div>
    </body></html>"""


def _cta_html(text: str, slide_num: int, total_slides: int, palette: dict) -> str:
    """Final slide: CTA — engagement + follow."""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    body = '<br>'.join(_html_esc(l) for l in lines)

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
        font-size: 36px;
        font-weight: 600;
        line-height: 1.45;
        max-width: 780px;
    }}
    .cta-action {{
        margin-top: 48px;
    }}
    .cta-btn {{
        display: inline-block;
        padding: 22px 56px;
        background: linear-gradient(135deg, {palette['accent']}, {palette['accent2']});
        color: white;
        font-size: 24px;
        font-weight: 700;
        border-radius: 60px;
        letter-spacing: 0.5px;
        box-shadow: 0 8px 32px {palette['accent']}44;
    }}
    .cta-follow {{
        margin-top: 28px;
        font-size: 18px;
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
            <span class="cta-btn">Segui per altri tips</span>
        </div>
        <div class="cta-follow">Salva questo post &bull; Condividi con un collega</div>
    </div>
    <div class="brand">
        <span class="brand-name">Juan | AI Automation</span>
        <span class="brand-handle">@juan.ai</span>
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


def render_carousel(text: str, palette_idx: int = 0) -> dict:
    """
    Render carousel text into PNG images.
    Returns: { 'slides': ['/static/carousel_output/xxx_1.png', ...], 'caption': '...' }
    """
    slides_text, caption = parse_carousel_text(text)
    if not slides_text:
        return {"slides": [], "caption": caption, "error": "No slides found"}

    palette = PALETTES[palette_idx % len(PALETTES)]
    total = len(slides_text)

    # Generate a unique prefix for this carousel
    content_hash = hashlib.md5(text.encode()).hexdigest()[:10]
    prefix = f"carousel_{content_hash}"

    image_paths = []

    if sync_playwright is None:
        raise RuntimeError("Playwright non è installato. Installa con: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 1080})

        for i, slide in enumerate(slides_text):
            # Choose template based on position
            if i == 0:
                html = _cover_html(slide, palette, total)
            elif i == total - 1 and total > 2:
                html = _cta_html(slide, i + 1, total, palette)
            else:
                html = _content_html(slide, i + 1, total, palette)

            page.set_content(html, wait_until="networkidle")
            # Small wait for fonts to load
            page.wait_for_timeout(500)

            filename = f"{prefix}_{i+1}.png"
            filepath = OUTPUT_DIR / filename
            page.screenshot(path=str(filepath), type="png")
            image_paths.append(f"/static/carousel_output/{filename}")

        browser.close()

    return {"slides": image_paths, "caption": caption}


def render_carousel_async(text: str, palette_idx: int = 0) -> dict:
    """Wrapper that can be called from Flask thread."""
    return render_carousel(text, palette_idx)
