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
.exclusive { padding: 28px 32px; background: #f8f9fa; border-left: 4px solid #333; margin: 0 32px; border-radius: 0 8px 8px 0; }
.exclusive h3 { font-size: 18px; font-weight: 600; color: #1a1a1a; margin: 0 0 10px; }
.exclusive p { font-size: 15px; color: #555; line-height: 1.65; margin: 0; }
.footer { padding: 24px 32px; text-align: center; font-size: 13px; color: #999; border-top: 1px solid #eee; }
.footer a { color: #666; text-decoration: underline; }
</style></head><body>
<div class="container">
    <div class="header"><h1>{{NEWSLETTER_TITLE}}</h1></div>
    <div class="section">{{SECTION_1}}</div>
    <div class="divider"></div>
    <div class="section">{{SECTION_2}}</div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
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
.exclusive {
    padding: 32px; margin: 0 32px 24px;
    background: linear-gradient(135deg, #0f3460 0%, #16213e 100%);
    border-radius: 12px; color: #ffffff;
}
.exclusive h3 { font-size: 20px; font-weight: 700; margin: 0 0 12px; color: #e94560; }
.exclusive p { font-size: 15px; line-height: 1.7; margin: 0; color: rgba(255,255,255,0.85); }
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
    <div class="section">{{SECTION_1}}</div>
    <div class="section section-alt">{{SECTION_2}}</div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
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
.section { padding: 24px 32px; }
.section h2 { font-size: 19px; font-weight: 600; color: #16213e; margin: 0 0 12px; }
.section p, .section ul, .section ol { font-size: 15px; color: #576574; line-height: 1.7; margin: 0 0 12px; }
.divider { height: 1px; background: #e8ecef; margin: 0 32px; }
.exclusive {
    padding: 24px 28px; margin: 16px 32px;
    background: #f0f8ff; border: 1px solid #0abde333; border-radius: 8px;
}
.exclusive h3 { font-size: 17px; font-weight: 600; color: #0abde3; margin: 0 0 10px; }
.exclusive p { font-size: 14px; color: #576574; line-height: 1.65; margin: 0; }
.footer {
    padding: 24px 32px; text-align: center; font-size: 12px; color: #8395a7;
    background: #f8f9fa; border-top: 1px solid #e8ecef;
}
.footer a { color: #0abde3; text-decoration: none; }
</style></head><body>
<div class="container">
    <div class="top-bar"></div>
    <div class="header"><h1>{{NEWSLETTER_TITLE}}</h1></div>
    <div class="section">{{SECTION_1}}</div>
    <div class="divider"></div>
    <div class="section">{{SECTION_2}}</div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
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
.exclusive {
    padding: 28px 36px; margin: 8px 28px 20px;
    background: #ffeaa7; border-radius: 12px;
}
.exclusive h3 { font-size: 18px; font-weight: 700; color: #2d3436; margin: 0 0 10px; }
.exclusive p { font-size: 15px; color: #636e72; line-height: 1.7; margin: 0; }
.footer { padding: 28px 36px; text-align: center; font-size: 13px; color: #b2bec3; }
.footer a { color: #e17055; text-decoration: none; }
</style></head><body>
<div class="container">
    <div class="header">
        <h1>{{NEWSLETTER_TITLE}}</h1>
        <div class="greeting">Ciao! Ecco cosa ho preparato per te questa settimana...</div>
    </div>
    <div class="section">{{SECTION_1}}</div>
    <div class="divider">&#8226; &#8226; &#8226;</div>
    <div class="section">{{SECTION_2}}</div>
    <div class="exclusive">{{EXCLUSIVE_SECTION}}</div>
    <div class="footer">{{FOOTER}}</div>
</div>
</body></html>"""


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
    # NL — html_content is still plain HTML string
    {"template_type": "newsletter", "name": "Minimal",    "html_content": NL_MINIMAL,    "aspect_ratio": "1:1"},
    {"template_type": "newsletter", "name": "Magazine",   "html_content": NL_MAGAZINE,   "aspect_ratio": "1:1"},
    {"template_type": "newsletter", "name": "Corporate",  "html_content": NL_CORPORATE,  "aspect_ratio": "1:1"},
    {"template_type": "newsletter", "name": "Personal",   "html_content": NL_PERSONAL,   "aspect_ratio": "1:1"},
]


def seed():
    existing = sb.table("preset_templates").select("id, name, template_type").execute()
    existing_map = {(r["name"], r["template_type"]): r["id"] for r in (existing.data or [])}

    updated = 0
    created = 0

    for preset in PRESETS:
        key = (preset["name"], preset["template_type"])
        if key in existing_map:
            sb.table("preset_templates").update({
                "html_content": preset["html_content"],
                "aspect_ratio": preset["aspect_ratio"],
            }).eq("id", existing_map[key]).execute()
            updated += 1
            print(f"  Updated: {preset['template_type']}/{preset['name']}")
        else:
            sb.table("preset_templates").insert({
                "template_type": preset["template_type"],
                "name": preset["name"],
                "html_content": preset["html_content"],
                "aspect_ratio": preset["aspect_ratio"],
            }).execute()
            created += 1
            print(f"  Created: {preset['template_type']}/{preset['name']}")

    print(f"\nDone! Updated: {updated}, Created: {created}")


if __name__ == "__main__":
    print("Seeding preset templates (multi-type IG)...\n")
    seed()
