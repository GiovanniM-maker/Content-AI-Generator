#!/usr/bin/env python3
"""
Seed script: populate preset_templates with real HTML content.
Run once: python seed_presets.py
"""
import os, sys
from pathlib import Path

# Ensure we can import db
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
# INSTAGRAM PRESET TEMPLATES
# =====================================================================

# Common base CSS function — same for all IG presets
# NOTE: NO @font-face here — the renderer injects it at runtime with the
# correct server-side file:// path (see carousel_renderer.py).
def _ig_base(bg, accent, accent2, text_color, text2, card_bg="rgba(255,255,255,0.06)"):
    return f"""
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
    .slide-content {{ font-size: 30px; font-weight: 400; line-height: 1.65; }}
    .slide-content strong {{ font-weight: 700; color: {accent2}; }}
    """


IG_MINIMAL_DARK = f"""<!DOCTYPE html><html><head><style>
{_ig_base(
    bg="linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)",
    accent="#7c5ce7", accent2="#a29bfe",
    text_color="#ffffff", text2="rgba(255,255,255,0.7)"
)}
</style></head><body>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="slide-num">{{{{SLIDE_NUM}}}}/{{{{TOTAL_SLIDES}}}}</div>
<div class="content">
    <div class="accent-line"></div>
    <div class="slide-content">{{{{SLIDE_CONTENT}}}}</div>
</div>
<div class="brand">
    <span class="brand-name">{{{{BRAND_NAME}}}}</span>
    <span class="brand-handle">{{{{BRAND_HANDLE}}}}</span>
</div>
</body></html>"""


IG_CLEAN_LIGHT = f"""<!DOCTYPE html><html><head><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    width: 1080px; height: 1080px;
    background: #fafafa;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #1a1a2e;
    display: flex; flex-direction: column;
    justify-content: center; align-items: center;
    padding: 90px; overflow: hidden; position: relative;
}}
.content {{
    position: relative; z-index: 1; width: 100%; height: 100%;
    display: flex; flex-direction: column; justify-content: center;
}}
.accent-line {{
    width: 64px; height: 5px; background: #2d63e2;
    border-radius: 3px; margin-bottom: 36px;
}}
.slide-content {{
    font-size: 30px; font-weight: 400; line-height: 1.65; color: #2c2c54;
}}
.slide-content strong {{ font-weight: 700; color: #2d63e2; }}
.brand {{
    position: absolute; bottom: 44px; left: 90px; right: 90px;
    display: flex; justify-content: space-between; align-items: center; z-index: 2;
}}
.brand-name {{ font-size: 20px; font-weight: 700; color: #8395a7; letter-spacing: 0.5px; }}
.brand-handle {{ font-size: 18px; color: #2d63e2; font-weight: 600; }}
.slide-num {{
    position: absolute; top: 44px; right: 90px;
    font-size: 16px; color: #8395a7; font-weight: 600; z-index: 2;
}}
/* Subtle corner decoration */
body::before {{
    content: ''; position: absolute; top: 0; right: 0;
    width: 300px; height: 300px;
    background: linear-gradient(135deg, #2d63e208 0%, transparent 60%);
    pointer-events: none;
}}
body::after {{
    content: ''; position: absolute; bottom: 0; left: 0;
    width: 250px; height: 250px;
    background: linear-gradient(315deg, #2d63e205 0%, transparent 60%);
    pointer-events: none;
}}
</style></head><body>
<div class="slide-num">{{{{SLIDE_NUM}}}}/{{{{TOTAL_SLIDES}}}}</div>
<div class="content">
    <div class="accent-line"></div>
    <div class="slide-content">{{{{SLIDE_CONTENT}}}}</div>
</div>
<div class="brand">
    <span class="brand-name">{{{{BRAND_NAME}}}}</span>
    <span class="brand-handle">{{{{BRAND_HANDLE}}}}</span>
</div>
</body></html>"""


IG_BOLD_GRADIENT = f"""<!DOCTYPE html><html><head><style>
{_ig_base(
    bg="linear-gradient(135deg, #ff6b6b 0%, #ee5a24 30%, #f0932b 60%, #f9ca24 100%)",
    accent="#ffffff", accent2="#fff8e7",
    text_color="#ffffff", text2="rgba(255,255,255,0.8)"
)}
.slide-content {{ font-size: 32px; font-weight: 500; line-height: 1.6; }}
.slide-content strong {{ font-weight: 800; color: #ffffff; text-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
.accent-line {{ background: rgba(255,255,255,0.6); }}
</style></head><body>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="slide-num">{{{{SLIDE_NUM}}}}/{{{{TOTAL_SLIDES}}}}</div>
<div class="content">
    <div class="accent-line"></div>
    <div class="slide-content">{{{{SLIDE_CONTENT}}}}</div>
</div>
<div class="brand">
    <span class="brand-name">{{{{BRAND_NAME}}}}</span>
    <span class="brand-handle">{{{{BRAND_HANDLE}}}}</span>
</div>
</body></html>"""


IG_PROFESSIONAL = f"""<!DOCTYPE html><html><head><style>
{_ig_base(
    bg="linear-gradient(180deg, #1a1a2e 0%, #16213e 100%)",
    accent="#0abde3", accent2="#48dbfb",
    text_color="#ffffff", text2="rgba(255,255,255,0.6)"
)}
.content {{ padding-top: 10px; }}
.slide-content {{ font-size: 28px; font-weight: 400; line-height: 1.7; }}
.slide-content strong {{ font-weight: 700; color: #48dbfb; }}
/* Top border accent */
body::after {{
    content: ''; position: absolute; top: 0; left: 0; right: 0;
    height: 6px; background: linear-gradient(90deg, #0abde3, #48dbfb);
    z-index: 3;
}}
</style></head><body>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="slide-num">{{{{SLIDE_NUM}}}}/{{{{TOTAL_SLIDES}}}}</div>
<div class="content">
    <div class="accent-line"></div>
    <div class="slide-content">{{{{SLIDE_CONTENT}}}}</div>
</div>
<div class="brand">
    <span class="brand-name">{{{{BRAND_NAME}}}}</span>
    <span class="brand-handle">{{{{BRAND_HANDLE}}}}</span>
</div>
</body></html>"""


IG_CREATIVE_POP = f"""<!DOCTYPE html><html><head><style>
{_ig_base(
    bg="#0d0d0d",
    accent="#fd79a8", accent2="#e056fd",
    text_color="#ffffff", text2="rgba(255,255,255,0.65)"
)}
.content {{ padding-top: 10px; }}
.slide-content {{ font-size: 30px; font-weight: 400; line-height: 1.65; }}
.slide-content strong {{ font-weight: 700; color: #e056fd; }}
.accent-line {{ background: linear-gradient(90deg, #fd79a8, #e056fd); width: 80px; }}
/* Neon glow effect */
.orb-1 {{ background: #fd79a8; opacity: 0.1; }}
.orb-2 {{ background: #e056fd; opacity: 0.08; }}
/* Geometric decoration */
body::after {{
    content: ''; position: absolute;
    bottom: 180px; right: 60px;
    width: 120px; height: 120px;
    border: 3px solid #fd79a822;
    border-radius: 20px;
    transform: rotate(15deg);
    pointer-events: none;
}}
</style></head><body>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="slide-num">{{{{SLIDE_NUM}}}}/{{{{TOTAL_SLIDES}}}}</div>
<div class="content">
    <div class="accent-line"></div>
    <div class="slide-content">{{{{SLIDE_CONTENT}}}}</div>
</div>
<div class="brand">
    <span class="brand-name">{{{{BRAND_NAME}}}}</span>
    <span class="brand-handle">{{{{BRAND_HANDLE}}}}</span>
</div>
</body></html>"""


# =====================================================================
# NEWSLETTER PRESET TEMPLATES
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
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: #ffffff;
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
.container { max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 0; }
.top-bar { height: 4px; background: linear-gradient(90deg, #0abde3, #48dbfb, #0abde3); }
.header { padding: 36px 32px 28px; }
.header h1 { font-size: 26px; font-weight: 700; color: #16213e; margin: 0; line-height: 1.3; }
.header .date { font-size: 13px; color: #8395a7; margin-top: 8px; }
.section { padding: 24px 32px; }
.section h2 { font-size: 19px; font-weight: 600; color: #16213e; margin: 0 0 12px; }
.section p, .section ul, .section ol { font-size: 15px; color: #576574; line-height: 1.7; margin: 0 0 12px; }
.divider { height: 1px; background: #e8ecef; margin: 0 32px; }
.exclusive {
    padding: 24px 28px; margin: 16px 32px;
    background: #f0f8ff; border: 1px solid #0abde333;
    border-radius: 8px;
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
    <div class="header">
        <h1>{{NEWSLETTER_TITLE}}</h1>
    </div>
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
.container { max-width: 560px; margin: 0 auto; background: #ffffff; padding: 0; }
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
.footer {
    padding: 28px 36px; text-align: center; font-size: 13px; color: #b2bec3;
}
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
    # IG templates
    {"template_type": "instagram", "name": "Minimal Dark",   "html_content": IG_MINIMAL_DARK,   "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Clean Light",    "html_content": IG_CLEAN_LIGHT,    "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Bold Gradient",  "html_content": IG_BOLD_GRADIENT,  "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Professional",   "html_content": IG_PROFESSIONAL,   "aspect_ratio": "1:1"},
    {"template_type": "instagram", "name": "Creative Pop",   "html_content": IG_CREATIVE_POP,   "aspect_ratio": "1:1"},
    # NL templates
    {"template_type": "newsletter", "name": "Minimal",    "html_content": NL_MINIMAL,    "aspect_ratio": "1:1"},
    {"template_type": "newsletter", "name": "Magazine",   "html_content": NL_MAGAZINE,   "aspect_ratio": "1:1"},
    {"template_type": "newsletter", "name": "Corporate",  "html_content": NL_CORPORATE,  "aspect_ratio": "1:1"},
    {"template_type": "newsletter", "name": "Personal",   "html_content": NL_PERSONAL,   "aspect_ratio": "1:1"},
]


def seed():
    # First, check existing presets
    existing = sb.table("preset_templates").select("id, name, template_type").execute()
    existing_map = {(r["name"], r["template_type"]): r["id"] for r in (existing.data or [])}

    updated = 0
    created = 0

    for preset in PRESETS:
        key = (preset["name"], preset["template_type"])
        if key in existing_map:
            # Update existing preset with real HTML
            sb.table("preset_templates").update({
                "html_content": preset["html_content"],
                "aspect_ratio": preset["aspect_ratio"],
            }).eq("id", existing_map[key]).execute()
            updated += 1
            print(f"  Updated: {preset['template_type']}/{preset['name']}")
        else:
            # Insert new preset
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
    print("Seeding preset templates...\n")
    seed()
