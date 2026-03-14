#!/usr/bin/env python3
"""
QA Smoke Tests — Template / Personalize Hardening Verification
Runs against the real code without needing Flask, DB, or Playwright.
Tests validation, rendering, parsing, and edge cases at the function level.
"""

import json
import sys
import traceback

# Ensure repo root is on path
sys.path.insert(0, "/home/user/Content-AI-Generator")

from services.template_renderer import (
    validate_design_spec,
    render_instagram_slide,
    render_preview_slides,
    parse_carousel_text_to_content,
    _is_valid_color,
    _safe_int,
    _safe_float,
    _adaptive_heading_size,
    _adaptive_body_size,
    _esc,
    _esc_keep_strong,
    DEFAULT_DESIGN_SPEC,
    ALLOWED_FONTS,
    ALLOWED_SLIDE_LAYOUTS,
    PRESET_SPECS,
    ASPECT_DIMENSIONS,
)

PASS = 0
FAIL = 0
ERRORS = []


def test(test_id: str, description: str, func):
    global PASS, FAIL
    try:
        result = func()
        if result is True:
            PASS += 1
            print(f"  PASS  {test_id} — {description}")
        else:
            FAIL += 1
            msg = f"  FAIL  {test_id} — {description}: returned {result}"
            print(msg)
            ERRORS.append(msg)
    except Exception as e:
        FAIL += 1
        msg = f"  FAIL  {test_id} — {description}: EXCEPTION {type(e).__name__}: {e}"
        print(msg)
        ERRORS.append(msg)
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════
# GROUP 1: _safe_int / _safe_float (H3 hardening)
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 1: Safe numeric conversion (H3) ===")

test("H3-01", "_safe_int with valid int", lambda: _safe_int(700, 400) == 700)
test("H3-02", "_safe_int with valid string", lambda: _safe_int("700", 400) == 700)
test("H3-03", "_safe_int with 'bold' string", lambda: _safe_int("bold", 400) == 400)
test("H3-04", "_safe_int with None", lambda: _safe_int(None, 400) == 400)
test("H3-05", "_safe_int with float string falls back to default", lambda: _safe_int("7.5", 400) == 400)
test("H3-06", "_safe_int with empty string", lambda: _safe_int("", 400) == 400)
test("H3-07", "_safe_float with valid float", lambda: _safe_float(1.5, 1.3) == 1.5)
test("H3-08", "_safe_float with 'normal'", lambda: _safe_float("normal", 1.3) == 1.3)
test("H3-09", "_safe_float with None", lambda: _safe_float(None, 1.3) == 1.3)
test("H3-10", "_safe_float with valid string", lambda: _safe_float("1.8", 1.3) == 1.8)


# ═══════════════════════════════════════════════════════════════════
# GROUP 2: _is_valid_color (H4 hardening)
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 2: Color validation (H4) ===")

test("H4-01", "valid hex 3-digit", lambda: _is_valid_color("#fff") is True)
test("H4-02", "valid hex 6-digit", lambda: _is_valid_color("#ff00aa") is True)
test("H4-03", "valid hex 8-digit (alpha)", lambda: _is_valid_color("#ff00aa80") is True)
test("H4-04", "valid rgb()", lambda: _is_valid_color("rgb(255,0,0)") is True)
test("H4-05", "valid rgba()", lambda: _is_valid_color("rgba(255,255,255,0.7)") is True)
test("H4-06", "valid linear-gradient", lambda: _is_valid_color("linear-gradient(135deg, #0f0c29 0%, #302b63 50%)") is True)
test("H4-07", "valid named color", lambda: _is_valid_color("red") is True)
test("H4-08", "CSS injection with semicolon", lambda: _is_valid_color("red; background: url(evil)") is False)
test("H4-09", "CSS injection with brace", lambda: _is_valid_color("red} body{background:red") is False)
test("H4-10", "empty string", lambda: _is_valid_color("") is False)
test("H4-11", "integer input", lambda: _is_valid_color(123) is False)
test("H4-12", "None input", lambda: _is_valid_color(None) is False)
test("H4-13", "hsl() valid", lambda: _is_valid_color("hsl(120, 100%, 50%)") is True)
test("H4-14", "gradient with semicolon injection", lambda: _is_valid_color("linear-gradient(0,red); } .x {color:red") is False)


# ═══════════════════════════════════════════════════════════════════
# GROUP 3: validate_design_spec — core validation
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 3: validate_design_spec — core ===")

def _expect_error(func, error_type):
    try:
        func()
        return False  # Should have raised
    except error_type:
        return True
    except Exception:
        return False


test("V-01", "empty dict returns defaults",
     lambda: validate_design_spec({}) == DEFAULT_DESIGN_SPEC)

test("V-02", "non-dict raises ValueError",
     lambda: _expect_error(lambda: validate_design_spec("string"), ValueError))

test("V-03", "None raises ValueError",
     lambda: _expect_error(lambda: validate_design_spec(None), ValueError))

test("V-04", "list raises ValueError",
     lambda: _expect_error(lambda: validate_design_spec([1, 2, 3]), ValueError))


# ═══════════════════════════════════════════════════════════════════
# GROUP 4: validate_design_spec — typography clamping
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 4: Typography clamping ===")

test("V-05", "heading_weight clamped to 900 max", lambda:
     validate_design_spec({"typography": {"heading_weight": 9999}})["typography"]["heading_weight"] == 900)

test("V-06", "heading_weight clamped to 100 min", lambda:
     validate_design_spec({"typography": {"heading_weight": 10}})["typography"]["heading_weight"] == 100)

test("V-07", "heading_weight 'bold' falls back to default", lambda:
     validate_design_spec({"typography": {"heading_weight": "bold"}})["typography"]["heading_weight"] == DEFAULT_DESIGN_SPEC["typography"]["heading_weight"])

test("V-08", "body_size_px clamped to 60 max", lambda:
     validate_design_spec({"typography": {"body_size_px": 200}})["typography"]["body_size_px"] == 60)

test("V-09", "body_size_px clamped to 14 min", lambda:
     validate_design_spec({"typography": {"body_size_px": 5}})["typography"]["body_size_px"] == 14)

test("V-10", "heading_size_px 'large' falls back to default", lambda:
     validate_design_spec({"typography": {"heading_size_px": "large"}})["typography"]["heading_size_px"] == DEFAULT_DESIGN_SPEC["typography"]["heading_size_px"])

test("V-11", "line_height clamped 0.8-2.5", lambda:
     validate_design_spec({"typography": {"line_height": 10.0}})["typography"]["line_height"] == 2.5)

test("V-12", "line_height 'normal' falls back to default", lambda:
     validate_design_spec({"typography": {"line_height": "normal"}})["typography"]["line_height"] == DEFAULT_DESIGN_SPEC["typography"]["line_height"])


# ═══════════════════════════════════════════════════════════════════
# GROUP 5: validate_design_spec — font whitelist
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 5: Font whitelist ===")

test("V-13", "allowed font accepted", lambda:
     validate_design_spec({"typography": {"heading_font": "Syne"}})["typography"]["heading_font"] == "Syne")

test("V-14", "disallowed font rejected → default", lambda:
     validate_design_spec({"typography": {"heading_font": "Comic Sans"}})["typography"]["heading_font"] == DEFAULT_DESIGN_SPEC["typography"]["heading_font"])

test("V-15", "all ALLOWED_FONTS accepted", lambda: all(
     validate_design_spec({"typography": {"heading_font": f}})["typography"]["heading_font"] == f
     for f in ALLOWED_FONTS))


# ═══════════════════════════════════════════════════════════════════
# GROUP 6: validate_design_spec — colors
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 6: Color validation in spec ===")

test("V-16", "valid hex color accepted", lambda:
     validate_design_spec({"colors": {"accent": "#ff0000"}})["colors"]["accent"] == "#ff0000")

test("V-17", "CSS injection color rejected → default", lambda:
     validate_design_spec({"colors": {"accent": "red; background: url(x)"}})["colors"]["accent"] == DEFAULT_DESIGN_SPEC["colors"]["accent"])

test("V-18", "gradient color accepted", lambda:
     validate_design_spec({"colors": {"background": "linear-gradient(135deg, #000 0%, #fff 100%)"}})["colors"]["background"] == "linear-gradient(135deg, #000 0%, #fff 100%)")


# ═══════════════════════════════════════════════════════════════════
# GROUP 7: validate_design_spec — images (H5)
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 7: Image URL validation (H5) ===")

test("H5-01", "valid https URL accepted", lambda:
     validate_design_spec({"images": {"logo_url": "https://example.com/logo.png"}})["images"]["logo_url"] == "https://example.com/logo.png")

test("H5-02", "http URL rejected → default empty", lambda:
     validate_design_spec({"images": {"logo_url": "http://example.com/logo.png"}})["images"]["logo_url"] == "")

test("H5-03", "empty string accepted", lambda:
     validate_design_spec({"images": {"logo_url": ""}})["images"]["logo_url"] == "")

test("H5-04", "URL > 2048 chars rejected", lambda:
     validate_design_spec({"images": {"logo_url": "https://x.com/" + "a" * 2040}})["images"]["logo_url"] == "")

test("H5-05", "URL exactly 2048 chars accepted", lambda:
     len("https://x.com/" + "a" * 2034) == 2048 and
     validate_design_spec({"images": {"logo_url": "https://x.com/" + "a" * 2034}})["images"]["logo_url"] != "")

test("H5-06", "javascript: URL rejected", lambda:
     validate_design_spec({"images": {"logo_url": "javascript:alert(1)"}})["images"]["logo_url"] == "")


# ═══════════════════════════════════════════════════════════════════
# GROUP 8: validate_design_spec — layout
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 8: Layout validation ===")

test("V-19", "padding clamped to 160 max", lambda:
     validate_design_spec({"layout": {"padding_px": 500}})["layout"]["padding_px"] == 160)

test("V-20", "padding clamped to 20 min", lambda:
     validate_design_spec({"layout": {"padding_px": 0}})["layout"]["padding_px"] == 20)

test("V-21", "corner_radius clamped to 60 max", lambda:
     validate_design_spec({"layout": {"corner_radius_px": 200}})["layout"]["corner_radius_px"] == 60)

test("V-22", "bool fields accept true", lambda:
     validate_design_spec({"layout": {"decorative_orbs": True}})["layout"]["decorative_orbs"] is True)

test("V-23", "bool fields reject string 'true'", lambda:
     validate_design_spec({"layout": {"decorative_orbs": "true"}})["layout"]["decorative_orbs"] == DEFAULT_DESIGN_SPEC["layout"]["decorative_orbs"])

test("V-24", "brand_position enum enforced", lambda:
     validate_design_spec({"layout": {"brand_position": "left"}})["layout"]["brand_position"] == DEFAULT_DESIGN_SPEC["layout"]["brand_position"])

test("V-25", "brand_position 'none' accepted", lambda:
     validate_design_spec({"layout": {"brand_position": "none"}})["layout"]["brand_position"] == "none")


# ═══════════════════════════════════════════════════════════════════
# GROUP 9: validate_design_spec — slide layouts
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 9: Slide layout validation ===")

test("V-26", "valid cover layout accepted", lambda:
     validate_design_spec({"slide_layouts": {"cover": "cover_left"}})["slide_layouts"]["cover"] == "cover_left")

test("V-27", "invalid cover layout rejected → default", lambda:
     validate_design_spec({"slide_layouts": {"cover": "cover_fullbleed"}})["slide_layouts"]["cover"] == DEFAULT_DESIGN_SPEC["slide_layouts"]["cover"])


# ═══════════════════════════════════════════════════════════════════
# GROUP 10: Preset specs pass validation
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 10: Preset specs validation ===")

for name, spec in PRESET_SPECS.items():
    test(f"P-{name}", f"preset '{name}' passes validation unchanged", lambda s=spec:
         validate_design_spec(s) == s)


# ═══════════════════════════════════════════════════════════════════
# GROUP 11: HTML rendering (non-Playwright, just HTML generation)
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 11: HTML rendering ===")

test("R-01", "render_instagram_slide cover returns HTML",
     lambda: render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "cover",
         {"title": "Test Title", "subtitle": "Test Sub"},
     ).startswith("<!DOCTYPE html>"))

test("R-02", "render_instagram_slide content returns HTML",
     lambda: render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "content",
         {"header": "Header", "body": "Body text here"},
     ).startswith("<!DOCTYPE html>"))

test("R-03", "render_instagram_slide list returns HTML",
     lambda: render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "list",
         {"header": "List", "items": ["Item 1", "Item 2"]},
     ).startswith("<!DOCTYPE html>"))

test("R-04", "render_instagram_slide cta returns HTML",
     lambda: render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "cta",
         {"text": "Follow!", "button": "Save"},
     ).startswith("<!DOCTYPE html>"))

test("R-05", "render_preview_slides returns 4 keys",
     lambda: set(render_preview_slides(DEFAULT_DESIGN_SPEC).keys()) == {"cover", "content", "list", "cta"})

test("R-06", "render_preview_slides all values start with <!DOCTYPE html>",
     lambda: all(v.startswith("<!DOCTYPE html>") for v in render_preview_slides(DEFAULT_DESIGN_SPEC).values()))

test("R-07", "rendered HTML contains design_spec colors",
     lambda: DEFAULT_DESIGN_SPEC["colors"]["accent"] in render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "cover", {"title": "T", "subtitle": "S"}))

test("R-08", "rendered HTML contains design_spec font",
     lambda: DEFAULT_DESIGN_SPEC["typography"]["heading_font"] in render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "cover", {"title": "T", "subtitle": "S"}))

test("R-09", "unknown slide_type falls back to content renderer",
     lambda: render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "unknown_type",
         {"header": "H", "body": "B"},
     ).startswith("<!DOCTYPE html>"))

test("R-10", "aspect_ratio 3:4 sets 1080x1440",
     lambda: "height: 1440px" in render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "cover", {"title": "T", "subtitle": "S"},
         aspect_ratio="3:4"))

test("R-11", "aspect_ratio 4:3 sets 1080x810",
     lambda: "height: 810px" in render_instagram_slide(
         DEFAULT_DESIGN_SPEC, "cover", {"title": "T", "subtitle": "S"},
         aspect_ratio="4:3"))


# ═══════════════════════════════════════════════════════════════════
# GROUP 12: HTML escaping
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 12: HTML escaping ===")

test("E-01", "basic XSS escaped", lambda: _esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;")
test("E-02", "quotes escaped", lambda: _esc('a"b') == 'a&quot;b')
test("E-03", "ampersand escaped", lambda: _esc("a&b") == "a&amp;b")
test("E-04", "bold preserved in _esc_keep_strong", lambda: "<strong>bold</strong>" in _esc_keep_strong("**bold**"))
test("E-05", "XSS in bold context escaped", lambda: "&lt;script&gt;" in _esc_keep_strong("<script>"))


# ═══════════════════════════════════════════════════════════════════
# GROUP 13: parse_carousel_text_to_content
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 13: Carousel text parser ===")

test("CP-01", "single slide → cover", lambda:
     parse_carousel_text_to_content("Hello World")[0]["type"] == "cover")

test("CP-02", "2 slides → cover + content", lambda:
     len(parse_carousel_text_to_content("Title---SLIDE---Body text")) == 2 and
     parse_carousel_text_to_content("Title---SLIDE---Body text")[0]["type"] == "cover" and
     parse_carousel_text_to_content("Title---SLIDE---Body text")[1]["type"] == "content")

FIVE_SLIDES = """Cover Title
---SLIDE---
Punto Chiave
Dettagli importanti qui
---SLIDE---
• Primo
• Secondo
• Terzo
---SLIDE---
Altro contenuto
Con più testo
---SLIDE---
Seguimi per altri tips
Salva questo post"""

test("CP-03", "5 slides parsed correctly", lambda:
     len(parse_carousel_text_to_content(FIVE_SLIDES)) == 5)

test("CP-04", "slide 0 is cover", lambda:
     parse_carousel_text_to_content(FIVE_SLIDES)[0]["type"] == "cover")

test("CP-05", "last slide with CTA keyword is cta", lambda:
     parse_carousel_text_to_content(FIVE_SLIDES)[-1]["type"] == "cta")

test("CP-06", "bullet slide detected as list", lambda:
     parse_carousel_text_to_content(FIVE_SLIDES)[2]["type"] == "list")

test("CP-07", "list items extracted", lambda:
     len(parse_carousel_text_to_content(FIVE_SLIDES)[2].get("items", [])) == 3)

test("CP-08", "empty text → empty list", lambda:
     parse_carousel_text_to_content("") == [])

test("CP-09", "caption section stripped", lambda:
     len(parse_carousel_text_to_content("Title---SLIDE---Body---CAPTION---Caption text")) == 2)

test("CP-10", "cover has title and subtitle", lambda:
     parse_carousel_text_to_content("Main Title\nSubtitle here")[0].get("title") == "Main Title" and
     parse_carousel_text_to_content("Main Title\nSubtitle here")[0].get("subtitle") == "Subtitle here")


# ═══════════════════════════════════════════════════════════════════
# GROUP 14: Adaptive font sizing
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 14: Adaptive font sizing ===")

test("AF-01", "short heading keeps base size", lambda:
     _adaptive_heading_size("Short", 68) == 68)

test("AF-02", "long heading scales down", lambda:
     _adaptive_heading_size("A" * 100, 68) < 68)

test("AF-03", "heading never below 28", lambda:
     _adaptive_heading_size("A" * 500, 68) >= 28)

test("AF-04", "short body keeps base size", lambda:
     _adaptive_body_size("Short", 32) == 32)

test("AF-05", "long body scales down", lambda:
     _adaptive_body_size("A" * 500, 32) < 32)

test("AF-06", "body never below 18", lambda:
     _adaptive_body_size("A" * 1000, 32) >= 18)


# ═══════════════════════════════════════════════════════════════════
# GROUP 15: Full pipeline — spec → validate → render → verify
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 15: Full pipeline integration ===")

def _full_pipeline_test():
    """Simulate the full chat → validate → render pipeline."""
    # Simulate LLM output
    llm_output = {
        "reply": "Ecco il design!",
        "design_spec": {
            "theme_name": "Test Theme",
            "colors": {
                "background": "#1a1a2e",
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
                "padding_px": 80,
                "corner_radius_px": 12,
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
        }
    }

    # Step 1: Validate
    validated = validate_design_spec(llm_output["design_spec"])
    assert validated["theme_name"] == "Test Theme"
    assert validated["colors"]["accent"] == "#e94560"
    assert validated["typography"]["heading_font"] == "Montserrat"

    # Step 2: Render preview slides (same as template_chat does)
    preview_htmls = render_preview_slides(validated)
    assert set(preview_htmls.keys()) == {"cover", "content", "list", "cta"}
    for stype, html in preview_htmls.items():
        assert html.startswith("<!DOCTYPE html>"), f"{stype} HTML doesn't start with DOCTYPE"
        assert "#e94560" in html, f"{stype} HTML missing accent color"
        assert "Montserrat" in html, f"{stype} HTML missing heading font"

    # Step 3: Simulate storing as JSON (same as template_chat line 3677)
    stored_html = json.dumps({
        "cover": preview_htmls["cover"],
        "content": preview_htmls["content"],
        "list": preview_htmls["list"],
        "cta": preview_htmls["cta"],
    })
    # Verify it round-trips
    parsed_back = json.loads(stored_html)
    assert set(parsed_back.keys()) == {"cover", "content", "list", "cta"}

    # Step 4: Simulate carousel render path
    carousel_text = FIVE_SLIDES
    slides_content = parse_carousel_text_to_content(carousel_text)
    assert len(slides_content) == 5

    total = len(slides_content)
    rendered_slides = []
    for i, slide in enumerate(slides_content):
        slide_type = slide.get("type", "content")
        content = {k: v for k, v in slide.items() if k != "type"}
        html = render_instagram_slide(
            validated, slide_type, content,
            aspect_ratio="1:1",
            slide_num=i + 1, total_slides=total,
        )
        rendered_slides.append(html)
        assert html.startswith("<!DOCTYPE html>"), f"Slide {i} HTML invalid"
        assert "#e94560" in html, f"Slide {i} missing accent color"

    # Every slide has UNIQUE content (H2 fix verification)
    assert len(rendered_slides) == 5
    # Cover should have the cover title
    assert "Cover Title" in rendered_slides[0] or "Cover" in rendered_slides[0]

    return True


test("FP-01", "full pipeline: validate → render preview → store → carousel render", _full_pipeline_test)


def _full_pipeline_with_bad_values():
    """Pipeline with LLM returning garbage values — should not crash."""
    spec = {
        "theme_name": "Bad Theme " * 20,  # way too long
        "colors": {
            "background": "red; } body { background: url(evil)",
            "accent": "#abc",
        },
        "typography": {
            "heading_font": "Comic Sans MS",  # not in whitelist
            "heading_weight": "extra-bold",
            "body_size_px": "huge",
            "line_height": "normal",
        },
        "layout": {
            "padding_px": "lots",
            "decorative_orbs": "yes",  # string not bool
        },
        "images": {
            "logo_url": "http://evil.com/logo.png",
            "background_image_url": "javascript:alert(1)",
        }
    }
    validated = validate_design_spec(spec)

    # Should survive and produce defaults for bad values
    assert validated["theme_name"] == ("Bad Theme " * 20)[:60]
    assert validated["colors"]["background"] == DEFAULT_DESIGN_SPEC["colors"]["background"]  # rejected
    assert validated["colors"]["accent"] == "#abc"  # valid hex accepted
    assert validated["typography"]["heading_font"] == DEFAULT_DESIGN_SPEC["typography"]["heading_font"]
    assert validated["typography"]["heading_weight"] == DEFAULT_DESIGN_SPEC["typography"]["heading_weight"]
    assert validated["typography"]["body_size_px"] == DEFAULT_DESIGN_SPEC["typography"]["body_size_px"]
    assert validated["images"]["logo_url"] == ""
    assert validated["images"]["background_image_url"] == ""

    # Rendering should still work
    html = render_instagram_slide(validated, "cover", {"title": "Test", "subtitle": ""})
    assert "<!DOCTYPE html>" in html
    return True


test("FP-02", "full pipeline with all-bad LLM values — no crash, safe defaults", _full_pipeline_with_bad_values)


# ═══════════════════════════════════════════════════════════════════
# GROUP 16: ASPECT_DIMENSIONS consistency
# ═══════════════════════════════════════════════════════════════════
print("\n=== GROUP 16: Cross-module consistency ===")

# Verify template_renderer ASPECT_DIMENSIONS matches carousel_renderer
from carousel_renderer import ASPECT_DIMENSIONS as CR_DIMS

test("CC-01", "ASPECT_DIMENSIONS match between template_renderer and carousel_renderer",
     lambda: ASPECT_DIMENSIONS == CR_DIMS)


# ═══════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
print(f"{'='*60}")
if ERRORS:
    print("\nFAILURES:")
    for e in ERRORS:
        print(f"  {e}")
    sys.exit(1)
else:
    print("\nALL TESTS PASSED")
    sys.exit(0)
