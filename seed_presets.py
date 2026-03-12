#!/usr/bin/env python3
"""
Seed script: populate preset_templates with real HTML content.
Each IG preset now has 4 slide types (cover, content, list, cta) stored as JSON.
Newsletter presets remain single HTML.

Run once: python3 seed_presets.py
"""
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# =====================================================================
# HELPER: Generate 4-type IG template from a color palette
# =====================================================================
# NOTE: NO @font-face — the renderer injects it at runtime with the
# correct server-side file:// path (see carousel_renderer.py).

def _make_ig_preset(
    bg: str, accent: str, accent2: str, text_color: str, text2: str,
    extra_css: str = "",
    body_decoration: str = "",
    orb_overrides: str = "",
) -> str:
    """Generate a JSON string with 4 slide-type HTML templates sharing the same palette."""

    base_css = f"""
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        width: 1080px; height: 1080px;
        background: {bg};
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: {text_color};
        display: flex; flex-direction: column;
        justify-content: center; align-items: center;
        padding: 90px; overflow: hidden; position: relative;
    }}
    body::before {{
        content: ''; position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background-image:
            radial-gradient(circle at 20% 80%, {accent}11 0%, transparent 50%),
            radial-gradient(circle at 80% 20%, {accent2}11 0%, transparent 50%);
        pointer-events: none;
    }}
    .orb {{
        position: absolute; width: 500px; height: 500px;
        border-radius: 50%; opacity: 0.07; filter: blur(120px);
    }}
    .orb-1 {{ top: -150px; right: -150px; background: {accent}; }}
    .orb-2 {{ bottom: -150px; left: -150px; opacity: 0.04; background: {accent2}; }}
    {orb_overrides}
    .content {{
        position: relative; z-index: 1; width: 100%; height: 100%;
        display: flex; flex-direction: column; justify-content: center;
    }}
    .brand {{
        position: absolute; bottom: 44px; left: 90px; right: 90px;
        display: flex; justify-content: space-between; align-items: center; z-index: 2;
    }}
    .brand-name {{ font-size: 20px; font-weight: 700; color: {text2}; letter-spacing: 0.5px; }}
    .brand-handle {{ font-size: 18px; color: {accent2}; font-weight: 600; }}
    .slide-num {{
        position: absolute; top: 44px; right: 90px;
        font-size: 16px; color: {text2}; font-weight: 600; z-index: 2;
    }}
    .accent-line {{
        width: 64px; height: 5px; background: {accent};
        border-radius: 3px; margin-bottom: 36px;
    }}
    {extra_css}
    """

    orbs = f"""<div class="orb orb-1"></div><div class="orb orb-2"></div>"""
    brand = """<div class="brand">
    <span class="brand-name">{{BRAND_NAME}}</span>
    <span class="brand-handle">{{BRAND_HANDLE}}</span>
</div>"""
    slide_num = """<div class="slide-num">{{SLIDE_NUM}}/{{TOTAL_SLIDES}}</div>"""

    # --- COVER ---
    cover = f"""<!DOCTYPE html><html><head><style>
{base_css}
.cover-title {{
    font-size: 62px; font-weight: 900; line-height: 1.12;
    letter-spacing: -2px; max-width: 880px;
}}
.cover-title strong {{
    background: linear-gradient(135deg, {accent} 0%, {accent2} 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.cover-subtitle {{
    font-size: 24px; font-weight: 400; color: {text2};
    margin-top: 20px; line-height: 1.5; max-width: 800px;
}}
.swipe {{
    position: absolute; bottom: 100px; right: 90px;
    font-size: 16px; color: {text2};
    display: flex; align-items: center; gap: 10px; z-index: 2;
}}
.swipe-arrow {{ font-size: 28px; color: {accent2}; }}
</style></head><body>
{orbs}
{slide_num}
{body_decoration}
<div class="content">
    <div class="accent-line"></div>
    <h1 class="cover-title">{{{{COVER_TITLE}}}}</h1>
    <p class="cover-subtitle">{{{{COVER_SUBTITLE}}}}</p>
</div>
<div class="swipe">Scorri <span class="swipe-arrow">&#8250;</span></div>
{brand}
</body></html>"""

    # --- CONTENT ---
    content = f"""<!DOCTYPE html><html><head><style>
{base_css}
.content-header {{
    font-size: 42px; font-weight: 800; color: {accent2};
    margin-bottom: 28px; line-height: 1.15; letter-spacing: -0.5px;
}}
.content-body {{ font-size: 28px; font-weight: 400; line-height: 1.7; }}
.content-body p {{ margin-bottom: 14px; }}
.content-body strong {{ font-weight: 700; color: {accent2}; }}
</style></head><body>
{orbs}
{slide_num}
{body_decoration}
<div class="content">
    <div class="accent-line"></div>
    <h2 class="content-header">{{{{CONTENT_HEADER}}}}</h2>
    <div class="content-body">{{{{CONTENT_BODY}}}}</div>
</div>
{brand}
</body></html>"""

    # --- LIST ---
    list_html = f"""<!DOCTYPE html><html><head><style>
{base_css}
.list-header {{
    font-size: 38px; font-weight: 800; color: {accent2};
    margin-bottom: 32px; line-height: 1.15;
}}
.list-items {{
    list-style: none; padding: 0; margin: 0;
}}
.list-items li {{
    font-size: 26px; font-weight: 400; line-height: 1.55;
    padding: 12px 0; padding-left: 36px; position: relative;
    border-bottom: 1px solid {accent}15;
}}
.list-items li:last-child {{ border-bottom: none; }}
.list-items li::before {{
    content: '\\2713'; position: absolute; left: 0; top: 12px;
    color: {accent2}; font-weight: 700; font-size: 22px;
}}
.list-items li strong {{ font-weight: 700; color: {accent2}; }}
</style></head><body>
{orbs}
{slide_num}
{body_decoration}
<div class="content">
    <div class="accent-line"></div>
    <h2 class="list-header">{{{{LIST_HEADER}}}}</h2>
    <ul class="list-items">{{{{LIST_ITEMS}}}}</ul>
</div>
{brand}
</body></html>"""

    # --- CTA ---
    cta = f"""<!DOCTYPE html><html><head><style>
{base_css}
.content {{
    align-items: center; text-align: center;
}}
.accent-line {{ margin: 0 auto 36px; }}
.cta-text {{
    font-size: 36px; font-weight: 600; line-height: 1.45; max-width: 780px;
}}
.cta-action {{ margin-top: 48px; }}
.cta-btn {{
    display: inline-block; padding: 22px 56px;
    background: linear-gradient(135deg, {accent}, {accent2});
    color: white; font-size: 24px; font-weight: 700;
    border-radius: 60px; letter-spacing: 0.5px;
    box-shadow: 0 8px 32px {accent}44;
}}
.cta-follow {{
    margin-top: 28px; font-size: 18px; color: {text2};
}}
</style></head><body>
{orbs}
{slide_num}
{body_decoration}
<div class="content">
    <div class="accent-line"></div>
    <div class="cta-text">{{{{CTA_TEXT}}}}</div>
    <div class="cta-action"><span class="cta-btn">{{{{CTA_BUTTON}}}}</span></div>
    <div class="cta-follow">Salva questo post &bull; Condividi con un collega</div>
</div>
{brand}
</body></html>"""

    return json.dumps({
        "cover": cover,
        "content": content,
        "list": list_html,
        "cta": cta,
    })


# =====================================================================
# INSTAGRAM PRESETS — 5 themes, each with 4 slide types
# =====================================================================

IG_MINIMAL_DARK = _make_ig_preset(
    bg="linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)",
    accent="#7c5ce7", accent2="#a29bfe",
    text_color="#ffffff", text2="rgba(255,255,255,0.7)",
)

IG_CLEAN_LIGHT = _make_ig_preset(
    bg="#fafafa",
    accent="#2d63e2", accent2="#5b8def",
    text_color="#1a1a2e", text2="#8395a7",
    extra_css="""
    body::before {
        content: ''; position: absolute; top: 0; right: 0;
        width: 300px; height: 300px;
        background: linear-gradient(135deg, #2d63e208 0%, transparent 60%);
        pointer-events: none;
    }
    """,
    orb_overrides=".orb { display: none; }",
)

IG_BOLD_GRADIENT = _make_ig_preset(
    bg="linear-gradient(135deg, #ff6b6b 0%, #ee5a24 30%, #f0932b 60%, #f9ca24 100%)",
    accent="#ffffff", accent2="#fff8e7",
    text_color="#ffffff", text2="rgba(255,255,255,0.8)",
    extra_css=".accent-line { background: rgba(255,255,255,0.6); }",
)

IG_PROFESSIONAL = _make_ig_preset(
    bg="linear-gradient(180deg, #1a1a2e 0%, #16213e 100%)",
    accent="#0abde3", accent2="#48dbfb",
    text_color="#ffffff", text2="rgba(255,255,255,0.6)",
    extra_css="""
    body::after {
        content: ''; position: absolute; top: 0; left: 0; right: 0;
        height: 6px; background: linear-gradient(90deg, #0abde3, #48dbfb);
        z-index: 3;
    }
    """,
)

IG_CREATIVE_POP = _make_ig_preset(
    bg="#0d0d0d",
    accent="#fd79a8", accent2="#e056fd",
    text_color="#ffffff", text2="rgba(255,255,255,0.65)",
    extra_css="""
    .accent-line { background: linear-gradient(90deg, #fd79a8, #e056fd); width: 80px; }
    body::after {
        content: ''; position: absolute;
        bottom: 180px; right: 60px;
        width: 120px; height: 120px;
        border: 3px solid #fd79a822; border-radius: 20px;
        transform: rotate(15deg); pointer-events: none;
    }
    """,
    orb_overrides=".orb-1 { background: #fd79a8; opacity: 0.1; } .orb-2 { background: #e056fd; opacity: 0.08; }",
)


# =====================================================================
# NEWSLETTER PRESETS — unchanged (single HTML, not JSON)
# =====================================================================

NL_MINIMAL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body { margin: 0; padding: 0; background: #f5f5f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.container { max-width: 600px; margin: 0 auto; background: #ffffff; }
.header { padding: 40px 32px 24px; border-bottom: 1px solid #eee; }
.header h1 { font-size: 28px; font-weight: 700; color: #1a1a1a; margin: 0; line-height: 1.3; }
.section { padding: 28px 32px; }
.section h2 { font-size: 20px; font-weight: 600; color: #333; margin: 0 0 12px; }
.section p, .section ul, .section ol { font-size: 16px; color: #555; line-height: 1.7; margin: 0 0 14px; }
.divider { height: 1px; background: #eee; margin: 0 32px; }
.btn { display: inline-block; padding: 12px 28px; background: #333; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600; margin-top: 8px; }
.card-row { display: flex; gap: 16px; padding: 0 32px 24px; }
.card { flex: 1; border: 1px solid #eee; border-radius: 8px; overflow: hidden; }
.card-img { width: 100%; height: 120px; background: #f0f0f0; display: flex; align-items: center; justify-content: center; color: #bbb; font-size: 13px; }
.card-body { padding: 14px; }
.card-body h4 { font-size: 15px; font-weight: 600; color: #333; margin: 0 0 6px; }
.card-body p { font-size: 13px; color: #777; line-height: 1.5; margin: 0; }
.exclusive { padding: 28px 32px; background: #f8f9fa; border-left: 4px solid #333; margin: 0 32px; border-radius: 0 8px 8px 0; }
.exclusive h3 { font-size: 18px; font-weight: 600; color: #1a1a1a; margin: 0 0 10px; }
.exclusive p { font-size: 15px; color: #555; line-height: 1.65; margin: 0; }
.social { padding: 20px 32px; text-align: center; }
.social a { display: inline-block; width: 36px; height: 36px; line-height: 36px; margin: 0 6px; background: #f0f0f0; border-radius: 50%; color: #555; text-decoration: none; font-size: 16px; }
.footer { padding: 24px 32px; text-align: center; font-size: 13px; color: #999; border-top: 1px solid #eee; }
.footer a { color: #666; text-decoration: underline; }
</style></head><body>
<div class="container">
    <div class="header"><h1>{{NEWSLETTER_TITLE}}</h1></div>
    <div class="section">{{SECTION_1}}
        <a href="#" class="btn">Scopri di pi&ugrave;</a>
    </div>
    <div class="divider"></div>
    <div class="section">{{SECTION_2}}</div>
    <div class="card-row">
        <div class="card"><div class="card-img">Immagine</div><div class="card-body"><h4>Articolo 1</h4><p>Breve anteprima del contenuto in evidenza.</p></div></div>
        <div class="card"><div class="card-img">Immagine</div><div class="card-body"><h4>Articolo 2</h4><p>Breve anteprima del contenuto in evidenza.</p></div></div>
    </div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
    <div class="social">
        <a href="#">&#x2709;</a>
        <a href="#">&#x1F310;</a>
        <a href="#">&#x260E;</a>
    </div>
    <div class="footer">{{FOOTER}}</div>
</div>
</body></html>"""

NL_MAGAZINE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body { margin: 0; padding: 0; background: #1a1a2e; font-family: Georgia, 'Times New Roman', serif; }
.container { max-width: 600px; margin: 0 auto; background: #ffffff; }
.header {
    padding: 48px 32px 36px; text-align: center;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #ffffff;
}
.header h1 { font-size: 32px; font-weight: 700; margin: 0; line-height: 1.3; letter-spacing: -0.5px; }
.header .subtitle { font-size: 14px; color: rgba(255,255,255,0.6); margin-top: 12px; font-style: italic; }
.section { padding: 32px; }
.section h2 { font-size: 22px; font-weight: 700; color: #1a1a2e; margin: 0 0 16px; border-bottom: 2px solid #e94560; padding-bottom: 8px; display: inline-block; }
.section p, .section ul, .section ol { font-size: 16px; color: #444; line-height: 1.8; margin: 0 0 14px; }
.section-alt { background: #f8f9fa; }
.btn { display: inline-block; padding: 14px 32px; background: #e94560; color: #fff; text-decoration: none; border-radius: 8px; font-size: 15px; font-weight: 700; letter-spacing: 0.3px; }
.btn-outline { display: inline-block; padding: 10px 24px; background: transparent; color: #e94560; text-decoration: none; border: 2px solid #e94560; border-radius: 8px; font-size: 14px; font-weight: 600; margin-top: 10px; }
.featured-img { width: 100%; height: 200px; background: linear-gradient(135deg, #f8f9fa 0%, #e8e8e8 100%); display: flex; align-items: center; justify-content: center; color: #aaa; font-size: 14px; font-style: italic; }
.card-grid { display: flex; gap: 16px; padding: 0 32px 28px; }
.card-grid .card { flex: 1; background: #f8f9fa; border-radius: 10px; overflow: hidden; }
.card-grid .card-img { height: 100px; background: #e8e8e8; display: flex; align-items: center; justify-content: center; color: #bbb; font-size: 12px; }
.card-grid .card-body { padding: 14px; }
.card-grid .card-body h4 { font-size: 15px; font-weight: 700; color: #1a1a2e; margin: 0 0 6px; }
.card-grid .card-body p { font-size: 13px; color: #666; line-height: 1.5; margin: 0; }
.exclusive {
    padding: 32px; margin: 0 32px 24px;
    background: linear-gradient(135deg, #0f3460 0%, #16213e 100%);
    border-radius: 12px; color: #ffffff;
}
.exclusive h3 { font-size: 20px; font-weight: 700; margin: 0 0 12px; color: #e94560; }
.exclusive p { font-size: 15px; line-height: 1.7; margin: 0; color: rgba(255,255,255,0.85); }
.social { padding: 24px 32px; text-align: center; border-top: 1px solid #eee; }
.social a { display: inline-block; width: 40px; height: 40px; line-height: 40px; margin: 0 8px; background: #1a1a2e; border-radius: 50%; color: #fff; text-decoration: none; font-size: 16px; }
.footer {
    padding: 28px 32px; text-align: center; font-size: 13px; color: #999;
    background: #f5f5f5; border-top: 3px solid #1a1a2e;
}
.footer a { color: #e94560; text-decoration: none; }
</style></head><body>
<div class="container">
    <div class="header">
        <h1>{{NEWSLETTER_TITLE}}</h1>
        <div class="subtitle">La tua dose settimanale di contenuti curati</div>
    </div>
    <div class="featured-img">Immagine di copertina</div>
    <div class="section">{{SECTION_1}}
        <br><a href="#" class="btn">Leggi l&#39;articolo</a>
    </div>
    <div class="section section-alt">{{SECTION_2}}
        <br><a href="#" class="btn-outline">Approfondisci</a>
    </div>
    <div class="card-grid">
        <div class="card"><div class="card-img">Img</div><div class="card-body"><h4>In evidenza</h4><p>Contenuto consigliato della settimana.</p></div></div>
        <div class="card"><div class="card-img">Img</div><div class="card-body"><h4>Da non perdere</h4><p>Una risorsa selezionata per te.</p></div></div>
    </div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}
        <br><a href="#" style="display:inline-block;padding:10px 24px;background:#e94560;color:#fff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600;margin-top:10px;">Accedi ora</a>
    </div>
    <div class="social">
        <a href="#">&#x2709;</a>
        <a href="#">&#x1F310;</a>
        <a href="#">&#x260E;</a>
    </div>
    <div class="footer">{{FOOTER}}</div>
</div>
</body></html>"""

NL_CORPORATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body { margin: 0; padding: 0; background: #e8ecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.container { max-width: 600px; margin: 0 auto; background: #ffffff; }
.top-bar { height: 4px; background: linear-gradient(90deg, #0abde3, #48dbfb, #0abde3); }
.header { padding: 36px 32px 28px; }
.header h1 { font-size: 26px; font-weight: 700; color: #16213e; margin: 0; line-height: 1.3; }
.header .date { font-size: 13px; color: #8395a7; margin-top: 8px; }
.section { padding: 24px 32px; }
.section h2 { font-size: 19px; font-weight: 600; color: #16213e; margin: 0 0 12px; }
.section p, .section ul, .section ol { font-size: 15px; color: #576574; line-height: 1.7; margin: 0 0 12px; }
.divider { height: 1px; background: #e8ecef; margin: 0 32px; }
.btn { display: inline-block; padding: 12px 28px; background: #0abde3; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600; margin-top: 8px; }
.btn-secondary { display: inline-block; padding: 10px 22px; background: #16213e; color: #fff; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 600; margin-top: 8px; }
.stats-row { display: flex; gap: 16px; padding: 20px 32px; background: #f8f9fa; }
.stat-box { flex: 1; text-align: center; padding: 16px 8px; background: #fff; border-radius: 8px; border: 1px solid #e8ecef; }
.stat-box .num { font-size: 28px; font-weight: 700; color: #0abde3; margin: 0; }
.stat-box .label { font-size: 12px; color: #8395a7; margin-top: 4px; }
.card-row { display: flex; gap: 14px; padding: 0 32px 24px; }
.card-row .card { flex: 1; border: 1px solid #e8ecef; border-radius: 8px; padding: 18px; }
.card-row .card h4 { font-size: 15px; font-weight: 600; color: #16213e; margin: 0 0 8px; }
.card-row .card p { font-size: 13px; color: #576574; line-height: 1.5; margin: 0; }
.exclusive {
    padding: 24px 28px; margin: 16px 32px;
    background: #f0f8ff; border: 1px solid #0abde333; border-radius: 8px;
}
.exclusive h3 { font-size: 17px; font-weight: 600; color: #0abde3; margin: 0 0 10px; }
.exclusive p { font-size: 14px; color: #576574; line-height: 1.65; margin: 0; }
.social { padding: 20px 32px; text-align: center; }
.social a { display: inline-block; width: 34px; height: 34px; line-height: 34px; margin: 0 5px; background: #16213e; border-radius: 6px; color: #fff; text-decoration: none; font-size: 14px; }
.footer {
    padding: 24px 32px; text-align: center; font-size: 12px; color: #8395a7;
    background: #f8f9fa; border-top: 1px solid #e8ecef;
}
.footer a { color: #0abde3; text-decoration: none; }
</style></head><body>
<div class="container">
    <div class="top-bar"></div>
    <div class="header">
        <h1>{{NEWSLETTER_TITLE}}</h1>
        <div class="date">Newsletter settimanale</div>
    </div>
    <div class="section">{{SECTION_1}}
        <br><a href="#" class="btn">Scopri di pi&ugrave;</a>
    </div>
    <div class="stats-row">
        <div class="stat-box"><div class="num">12K</div><div class="label">Lettori</div></div>
        <div class="stat-box"><div class="num">85%</div><div class="label">Apertura</div></div>
        <div class="stat-box"><div class="num">4.8</div><div class="label">Rating</div></div>
    </div>
    <div class="divider"></div>
    <div class="section">{{SECTION_2}}
        <br><a href="#" class="btn-secondary">Leggi tutto</a>
    </div>
    <div class="card-row">
        <div class="card"><h4>Quick Tip</h4><p>Un consiglio pratico per la tua strategia.</p></div>
        <div class="card"><h4>Risorsa</h4><p>Link e strumenti utili selezionati.</p></div>
    </div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
    <div class="social">
        <a href="#">&#x2709;</a>
        <a href="#">&#x1F310;</a>
        <a href="#">&#x260E;</a>
    </div>
    <div class="footer">{{FOOTER}}</div>
</div>
</body></html>"""

NL_PERSONAL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body { margin: 0; padding: 0; background: #fff5f5; font-family: Georgia, 'Times New Roman', serif; }
.container { max-width: 560px; margin: 0 auto; background: #ffffff; }
.header { padding: 44px 36px 28px; }
.header h1 { font-size: 30px; font-weight: 700; color: #2d3436; margin: 0; line-height: 1.35; }
.header .greeting { font-size: 15px; color: #636e72; margin-top: 12px; font-style: italic; line-height: 1.6; }
.section { padding: 24px 36px; }
.section h2 { font-size: 20px; font-weight: 700; color: #2d3436; margin: 0 0 14px; }
.section p, .section ul, .section ol { font-size: 16px; color: #555; line-height: 1.8; margin: 0 0 14px; }
.divider { text-align: center; padding: 8px 0; color: #dfe6e9; font-size: 20px; letter-spacing: 8px; }
.btn { display: inline-block; padding: 12px 28px; background: #e17055; color: #fff; text-decoration: none; border-radius: 24px; font-size: 14px; font-weight: 700; margin-top: 10px; }
.btn-ghost { display: inline-block; padding: 10px 22px; background: transparent; color: #e17055; text-decoration: none; border: 2px solid #e17055; border-radius: 24px; font-size: 13px; font-weight: 600; margin-top: 8px; }
.highlight-card { margin: 0 36px 20px; padding: 24px; background: linear-gradient(135deg, #fff5f5 0%, #ffeaa7 100%); border-radius: 12px; border: 1px solid #ffeaa744; }
.highlight-card h4 { font-size: 17px; font-weight: 700; color: #2d3436; margin: 0 0 8px; }
.highlight-card p { font-size: 14px; color: #636e72; line-height: 1.6; margin: 0 0 10px; }
.img-placeholder { width: 100%; height: 180px; background: linear-gradient(135deg, #ffeaa7 0%, #fab1a0 100%); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 14px; font-weight: 600; }
.exclusive {
    padding: 28px 36px; margin: 8px 28px 20px;
    background: #ffeaa7; border-radius: 12px;
}
.exclusive h3 { font-size: 18px; font-weight: 700; color: #2d3436; margin: 0 0 10px; }
.exclusive p { font-size: 15px; color: #636e72; line-height: 1.7; margin: 0; }
.social { padding: 20px 36px; text-align: center; }
.social a { display: inline-block; width: 38px; height: 38px; line-height: 38px; margin: 0 6px; background: #fab1a0; border-radius: 50%; color: #fff; text-decoration: none; font-size: 16px; }
.footer { padding: 28px 36px; text-align: center; font-size: 13px; color: #b2bec3; }
.footer a { color: #e17055; text-decoration: none; }
</style></head><body>
<div class="container">
    <div class="header">
        <h1>{{NEWSLETTER_TITLE}}</h1>
        <div class="greeting">Ciao! Ecco cosa ho preparato per te questa settimana...</div>
    </div>
    <div class="img-placeholder">La tua immagine qui</div>
    <div class="section">{{SECTION_1}}
        <br><a href="#" class="btn">Continua a leggere</a>
    </div>
    <div class="divider">&#8226; &#8226; &#8226;</div>
    <div class="section">{{SECTION_2}}
        <br><a href="#" class="btn-ghost">Scopri di pi&ugrave;</a>
    </div>
    <div class="highlight-card">
        <h4>Il consiglio della settimana</h4>
        <p>Un suggerimento pratico selezionato per te.</p>
        <a href="#" class="btn-ghost">Leggi tutto</a>
    </div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
    <div class="social">
        <a href="#">&#x2709;</a>
        <a href="#">&#x1F310;</a>
        <a href="#">&#x260E;</a>
    </div>
    <div class="footer">{{FOOTER}}</div>
</div>
</body></html>"""


# =====================================================================
# NEWSLETTER V2 — Component-based layouts ({{CONTENT}} placeholder)
# =====================================================================

NL_V2_MINIMAL_LAYOUT = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head><body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#ffffff;">
    <div style="padding:40px 32px 24px;border-bottom:1px solid #e5e7eb;">
        <h1 style="margin:0;font-size:28px;font-weight:700;color:#111827;line-height:1.3;">{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div style="padding:28px 32px;">
        {{CONTENT}}
    </div>
    <div style="padding:24px 32px;text-align:center;font-size:13px;color:#9ca3af;border-top:1px solid #e5e7eb;">
        {{FOOTER}}
    </div>
</div>
</body></html>"""

NL_V2_MINIMAL_COMPONENTS = {
    "h1": "font-size:28px;font-weight:700;color:#111827;margin:0 0 16px 0;line-height:1.3;",
    "h2": "font-size:20px;font-weight:600;color:#1f2937;margin:28px 0 12px 0;line-height:1.3;",
    "h3": "font-size:17px;font-weight:600;color:#374151;margin:20px 0 8px 0;",
    "p": "font-size:16px;color:#4b5563;margin:0 0 16px 0;line-height:1.7;",
    "strong": "font-weight:700;color:#1f2937;",
    "em": "font-style:italic;",
    "a": "color:#6c5ce7;text-decoration:underline;",
    "blockquote": "border-left:4px solid #e5e7eb;padding:12px 20px;margin:16px 0;background:#f9fafb;font-style:italic;color:#6b7280;",
    "ul": "margin:0 0 16px 0;padding-left:24px;",
    "ol": "margin:0 0 16px 0;padding-left:24px;",
    "li": "font-size:16px;color:#4b5563;margin:0 0 8px 0;line-height:1.6;",
    "hr": "border:none;border-top:1px solid #e5e7eb;margin:28px 0;",
    "callout": "background:#f0f9ff;border-left:4px solid #3b82f6;padding:16px 20px;margin:20px 0;border-radius:0 8px 8px 0;",
    "callout_title": "font-size:16px;font-weight:700;color:#1d4ed8;margin:0 0 8px 0;",
    "callout_body": "font-size:15px;color:#374151;margin:0;line-height:1.6;",
    "img": "max-width:100%;height:auto;border-radius:8px;margin:16px 0;display:block;",
}

NL_V2_MAGAZINE_LAYOUT = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head><body style="margin:0;padding:0;background:#1a1a2e;font-family:Georgia,'Times New Roman',Times,serif;">
<div style="max-width:600px;margin:0 auto;background:#ffffff;">
    <div style="padding:48px 32px 36px;text-align:center;background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);color:#ffffff;">
        <p style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#a0aec0;margin:0 0 12px;">La tua newsletter settimanale</p>
        <h1 style="font-size:32px;font-weight:700;color:#ffffff;margin:0;line-height:1.2;">{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div style="padding:32px;">
        {{CONTENT}}
    </div>
    <div style="padding:28px 32px;text-align:center;font-size:12px;color:#999;border-top:1px solid #eee;background:#fafafa;">
        {{FOOTER}}
    </div>
</div>
</body></html>"""

NL_V2_MAGAZINE_COMPONENTS = {
    "h1": "font-size:28px;font-weight:700;color:#1a1a2e;margin:0 0 16px 0;line-height:1.3;font-family:Georgia,'Times New Roman',serif;",
    "h2": "font-size:22px;font-weight:700;color:#16213e;margin:28px 0 14px 0;line-height:1.3;font-family:Georgia,'Times New Roman',serif;border-bottom:2px solid #6c5ce7;padding-bottom:8px;",
    "h3": "font-size:18px;font-weight:600;color:#2d3748;margin:20px 0 8px 0;font-family:Georgia,'Times New Roman',serif;",
    "p": "font-size:16px;color:#4a5568;margin:0 0 16px 0;line-height:1.8;",
    "strong": "font-weight:700;color:#1a1a2e;",
    "em": "font-style:italic;color:#6c5ce7;",
    "a": "color:#6c5ce7;text-decoration:none;border-bottom:1px solid #6c5ce7;",
    "blockquote": "border-left:3px solid #6c5ce7;padding:16px 24px;margin:20px 0;background:#f7f6ff;color:#4a5568;font-style:italic;",
    "ul": "margin:0 0 16px 0;padding-left:20px;",
    "ol": "margin:0 0 16px 0;padding-left:20px;",
    "li": "font-size:16px;color:#4a5568;margin:0 0 10px 0;line-height:1.7;",
    "hr": "border:none;height:3px;background:linear-gradient(90deg,#6c5ce7,#a29bfe);margin:32px 0;border-radius:2px;",
    "callout": "background:#f0f0ff;border:1px solid #d4d0fb;padding:20px 24px;margin:24px 0;border-radius:12px;",
    "callout_title": "font-size:16px;font-weight:700;color:#6c5ce7;margin:0 0 8px 0;",
    "callout_body": "font-size:15px;color:#4a5568;margin:0;line-height:1.7;",
    "img": "max-width:100%;height:auto;border-radius:12px;margin:20px 0;display:block;box-shadow:0 2px 8px rgba(0,0,0,0.1);",
}

NL_V2_CORPORATE_LAYOUT = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head><body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#ffffff;">
    <div style="padding:32px;background:#0f172a;text-align:center;">
        <h1 style="font-size:26px;font-weight:700;color:#ffffff;margin:0;">{{NEWSLETTER_TITLE}}</h1>
        <p style="font-size:13px;color:#94a3b8;margin:8px 0 0;">Insights settimanali per professionisti</p>
    </div>
    <div style="padding:32px;">
        {{CONTENT}}
    </div>
    <div style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;font-size:12px;color:#94a3b8;">
        {{FOOTER}}
    </div>
</div>
</body></html>"""

NL_V2_CORPORATE_COMPONENTS = {
    "h1": "font-size:26px;font-weight:700;color:#0f172a;margin:0 0 16px 0;line-height:1.3;",
    "h2": "font-size:20px;font-weight:700;color:#1e293b;margin:28px 0 12px 0;line-height:1.3;text-transform:uppercase;font-size:14px;letter-spacing:1px;color:#0f172a;",
    "h3": "font-size:17px;font-weight:600;color:#334155;margin:20px 0 8px 0;",
    "p": "font-size:15px;color:#475569;margin:0 0 16px 0;line-height:1.7;",
    "strong": "font-weight:700;color:#0f172a;",
    "em": "font-style:italic;",
    "a": "color:#2563eb;text-decoration:none;font-weight:600;",
    "blockquote": "border-left:4px solid #2563eb;padding:12px 20px;margin:16px 0;background:#f8fafc;color:#475569;",
    "ul": "margin:0 0 16px 0;padding-left:20px;",
    "ol": "margin:0 0 16px 0;padding-left:20px;",
    "li": "font-size:15px;color:#475569;margin:0 0 8px 0;line-height:1.6;",
    "hr": "border:none;border-top:2px solid #e2e8f0;margin:28px 0;",
    "callout": "background:#eff6ff;border-left:4px solid #2563eb;padding:16px 20px;margin:20px 0;",
    "callout_title": "font-size:14px;font-weight:700;color:#1e40af;margin:0 0 6px 0;text-transform:uppercase;letter-spacing:0.5px;",
    "callout_body": "font-size:15px;color:#334155;margin:0;line-height:1.6;",
    "img": "max-width:100%;height:auto;margin:16px 0;display:block;",
}

NL_V2_PERSONAL_LAYOUT = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head><body style="margin:0;padding:0;background:#fef7ed;font-family:'Georgia','Times New Roman',serif;">
<div style="max-width:560px;margin:0 auto;background:#fffdf8;border:1px solid #fed7aa;border-radius:0;">
    <div style="padding:36px 32px 20px;">
        <p style="font-size:14px;color:#c2410c;margin:0 0 8px;font-weight:600;">Ciao! 👋</p>
        <h1 style="font-size:26px;font-weight:700;color:#431407;margin:0;line-height:1.3;">{{NEWSLETTER_TITLE}}</h1>
    </div>
    <div style="padding:8px 32px 32px;">
        {{CONTENT}}
    </div>
    <div style="padding:20px 32px;border-top:1px solid #fed7aa;font-size:13px;color:#a8a29e;text-align:center;">
        {{FOOTER}}
    </div>
</div>
</body></html>"""

NL_V2_PERSONAL_COMPONENTS = {
    "h1": "font-size:24px;font-weight:700;color:#431407;margin:0 0 14px 0;line-height:1.3;font-family:Georgia,serif;",
    "h2": "font-size:20px;font-weight:700;color:#7c2d12;margin:24px 0 10px 0;line-height:1.3;font-family:Georgia,serif;",
    "h3": "font-size:17px;font-weight:600;color:#9a3412;margin:18px 0 8px 0;font-family:Georgia,serif;",
    "p": "font-size:16px;color:#57534e;margin:0 0 16px 0;line-height:1.8;",
    "strong": "font-weight:700;color:#431407;",
    "em": "font-style:italic;color:#c2410c;",
    "a": "color:#c2410c;text-decoration:underline;",
    "blockquote": "border-left:3px solid #fb923c;padding:12px 20px;margin:16px 0;background:#fff7ed;color:#78716c;font-style:italic;",
    "ul": "margin:0 0 16px 0;padding-left:20px;",
    "ol": "margin:0 0 16px 0;padding-left:20px;",
    "li": "font-size:16px;color:#57534e;margin:0 0 8px 0;line-height:1.7;",
    "hr": "border:none;border-top:1px dashed #d6d3d1;margin:24px 0;",
    "callout": "background:#fff7ed;border:1px solid #fed7aa;padding:16px 20px;margin:20px 0;border-radius:12px;",
    "callout_title": "font-size:16px;font-weight:700;color:#c2410c;margin:0 0 8px 0;",
    "callout_body": "font-size:15px;color:#57534e;margin:0;line-height:1.7;",
    "img": "max-width:100%;height:auto;border-radius:12px;margin:16px 0;display:block;border:1px solid #fed7aa;",
}


# =====================================================================
# SEED DATA
# =====================================================================

PRESETS = [
    # IG — html_content is now JSON with {cover, content, list, cta}
    {"template_type": "instagram", "name": "Minimal Dark",   "html_content": IG_MINIMAL_DARK,   "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Clean Light",    "html_content": IG_CLEAN_LIGHT,    "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Bold Gradient",  "html_content": IG_BOLD_GRADIENT,  "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Professional",   "html_content": IG_PROFESSIONAL,   "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Creative Pop",   "html_content": IG_CREATIVE_POP,   "aspect_ratio": "1:1"},
    # NL v2 — component-based (layout + components JSON)
    {"template_type": "newsletter", "name": "Minimal",    "html_content": NL_V2_MINIMAL_LAYOUT,    "aspect_ratio": "1:1", "components": NL_V2_MINIMAL_COMPONENTS},
    {"template_type": "newsletter", "name": "Magazine",   "html_content": NL_V2_MAGAZINE_LAYOUT,   "aspect_ratio": "1:1", "components": NL_V2_MAGAZINE_COMPONENTS},
    {"template_type": "newsletter", "name": "Corporate",  "html_content": NL_V2_CORPORATE_LAYOUT,  "aspect_ratio": "1:1", "components": NL_V2_CORPORATE_COMPONENTS},
    {"template_type": "newsletter", "name": "Personal",   "html_content": NL_V2_PERSONAL_LAYOUT,   "aspect_ratio": "1:1", "components": NL_V2_PERSONAL_COMPONENTS},
]


def seed():
    existing = sb.table("preset_templates").select("id, name, template_type").execute()
    existing_map = {(r["name"], r["template_type"]): r["id"] for r in (existing.data or [])}

    # Detect if 'components' column exists (try a select)
    has_components_col = True
    try:
        sb.table("preset_templates").select("id,components").limit(1).execute()
    except Exception:
        has_components_col = False
        print("⚠  Column 'components' not found — run migration_add_components.sql first!")
        print("   NL presets will be seeded WITHOUT components.\n")

    updated = 0
    created = 0

    for preset in PRESETS:
        key = (preset["name"], preset["template_type"])
        update_data = {
            "html_content": preset["html_content"],
            "aspect_ratio": preset["aspect_ratio"],
        }
        insert_data = {
            "template_type": preset["template_type"],
            "name": preset["name"],
            "html_content": preset["html_content"],
            "aspect_ratio": preset["aspect_ratio"],
        }
        # Include components if present AND column exists (newsletter v2)
        if "components" in preset and has_components_col:
            update_data["components"] = preset["components"]
            insert_data["components"] = preset["components"]
        if key in existing_map:
            sb.table("preset_templates").update(update_data).eq("id", existing_map[key]).execute()
            updated += 1
            print(f"  Updated: {preset['template_type']}/{preset['name']}")
        else:
            sb.table("preset_templates").insert(insert_data).execute()
            created += 1
            print(f"  Created: {preset['template_type']}/{preset['name']}")

    print(f"\nDone! Updated: {updated}, Created: {created}")
    if not has_components_col:
        print("\n⚠  Re-run this script AFTER running migration_add_components.sql")
        print("   to populate components for newsletter presets.")


if __name__ == "__main__":
    print("Seeding preset templates (multi-type IG)...\n")
    seed()
