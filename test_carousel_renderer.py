"""
QA test script for carousel_renderer.py — real Playwright execution.
"""
import sys
import os
import tempfile
import traceback

sys.path.insert(0, "/home/user/Content-AI-Generator")

from carousel_renderer import (
    render_carousel,
    parse_carousel_text,
    _html_esc,
    _html_esc_keep_tags,
    _cover_html,
    _content_html,
    _cta_html,
    _detect_slide_type,
    _parse_template_html,
    _truncate_to_constraints,
    _inject_slide_image,
    _inject_font,
    _prepare_slide_html,
    render_carousel_from_template,
    render_template_preview,
    PALETTES,
)

results = []

def run_test(test_id, description, fn):
    try:
        fn()
        results.append((test_id, description, "PASS", ""))
    except Exception as e:
        tb = traceback.format_exc()
        results.append((test_id, description, "FAIL", str(e) + "\n" + tb))


# ============================================================
# Unit tests for helper functions (no Playwright needed)
# ============================================================

def test_html_esc():
    assert _html_esc('<script>alert("xss")</script>') == '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
    assert _html_esc("A & B") == "A &amp; B"
    assert _html_esc("it's") == "it&#39;s"
    assert _html_esc("") == ""

run_test("T01", "HTML escaping (_html_esc) handles <, >, &, quotes, empty", test_html_esc)


def test_html_esc_keep_tags():
    result = _html_esc_keep_tags("Use <strong>bold</strong> & <em>italic</em>")
    assert "<strong>bold</strong>" in result
    assert "&amp;" in result
    assert "&lt;em&gt;" in result  # <em> should be escaped

run_test("T02", "HTML escaping keeps <strong> tags only", test_html_esc_keep_tags)


def test_parse_carousel_text_basic():
    text = "Slide 1\n---SLIDE---\nSlide 2\n---SLIDE---\nSlide 3\n---CAPTION---\nMy caption"
    slides, caption = parse_carousel_text(text)
    assert len(slides) == 3
    assert slides[0] == "Slide 1"
    assert slides[1] == "Slide 2"
    assert slides[2] == "Slide 3"
    assert caption == "My caption"

run_test("T03", "parse_carousel_text with 3 slides and caption", test_parse_carousel_text_basic)


def test_parse_carousel_text_no_caption():
    text = "Only slide"
    slides, caption = parse_carousel_text(text)
    assert len(slides) == 1
    assert caption == ""

run_test("T04", "parse_carousel_text with no caption and single slide", test_parse_carousel_text_no_caption)


def test_detect_slide_type():
    assert _detect_slide_type("Title", 0, 5) == "cover"
    assert _detect_slide_type("Some content here", 2, 5) == "content"
    assert _detect_slide_type("Header\n- item1\n- item2\n- item3", 2, 5) == "list"
    assert _detect_slide_type("Seguici per altri tips!\nFollow us", 4, 5) == "cta"
    # Non-CTA last slide (no keywords)
    assert _detect_slide_type("Just a conclusion paragraph", 4, 5) == "content"

run_test("T05", "Slide type detection (cover, content, list, cta)", test_detect_slide_type)


def test_parse_template_html_json():
    import json
    tmpl = json.dumps({"cover": "<h1>C</h1>", "content": "<p>B</p>"})
    result = _parse_template_html(tmpl)
    assert result["cover"] == "<h1>C</h1>"
    assert result["content"] == "<p>B</p>"
    assert result["list"] == "<p>B</p>"  # fallback to content
    assert result["cta"] == "<p>B</p>"

run_test("T06", "Template parser handles JSON with fallback for missing types", test_parse_template_html_json)


def test_parse_template_html_legacy():
    result = _parse_template_html("<html>{{SLIDE_CONTENT}}</html>")
    assert result["cover"] == "<html>{{SLIDE_CONTENT}}</html>"
    assert result["content"] == result["cover"]

run_test("T07", "Template parser handles legacy single HTML string", test_parse_template_html_legacy)


def test_parse_template_html_empty():
    result = _parse_template_html("")
    assert all(v == "" for v in result.values())
    result2 = _parse_template_html(None)
    assert all(v == "" for v in result2.values())

run_test("T08", "Template parser handles empty/None input", test_parse_template_html_empty)


def test_truncate_cover_title():
    rules = {"typography": {"cover_title": {"max_chars": 20}}}
    result = _truncate_to_constraints("A" * 30, "cover_title", rules)
    assert len(result) == 20
    assert result.endswith("...")

run_test("T09", "Truncation: cover title respects max_chars", test_truncate_cover_title)


def test_truncate_no_rules():
    result = _truncate_to_constraints("Hello", "cover_title", None)
    assert result == "Hello"
    result2 = _truncate_to_constraints("", "cover_title", {"typography": {}})
    assert result2 == ""

run_test("T10", "Truncation: no-op with empty rules or empty text", test_truncate_no_rules)


def test_inject_slide_image():
    html = "<html><head><style></style></head><body><div>Hello</div></body></html>"
    result = _inject_slide_image(html, "https://example.com/img.png")
    assert "ai-bg-image" in result
    assert "https://example.com/img.png" in result

run_test("T11", "Image injection adds background overlay div and CSS", test_inject_slide_image)


def test_inject_slide_image_empty():
    html = "<html><body></body></html>"
    assert _inject_slide_image(html, "") == html
    assert _inject_slide_image("", "http://x.com/i.png") == ""

run_test("T12", "Image injection no-op with empty URL or empty HTML", test_inject_slide_image_empty)


# ============================================================
# Playwright rendering tests
# ============================================================

def test_render_normal_slide():
    text = "My Amazing Title\n---SLIDE---\nKey Point\nThis is the body text explaining the key point in detail.\n---SLIDE---\nFollow us for more!\nSegui per altri tips"
    result = render_carousel(text, palette_idx=0, brand_name="TestBrand", brand_handle="@test")
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert len(result["slides_bytes"]) == 3
    for idx, png in enumerate(result["slides_bytes"]):
        assert isinstance(png, bytes)
        size = len(png)
        assert size > 1000, f"Slide {idx} too small: {size} bytes"
        assert png[:8] == b'\x89PNG\r\n\x1a\n', f"Slide {idx} not valid PNG"
        print(f"  Slide {idx}: {size:,} bytes, valid PNG header")

run_test("T13", "Render 3 normal slides (cover+content+cta) with Playwright", test_render_normal_slide)


def test_render_emoji_slide():
    text = "🚀 Launch Day! 🎉\n---SLIDE---\n💡 Key Insight\nUse emojis 🔥 to boost engagement 📈\n---SLIDE---\n❤️ Seguici! Like & Share 🙏"
    result = render_carousel(text, palette_idx=1)
    assert "error" not in result
    assert len(result["slides_bytes"]) == 3
    for idx, png in enumerate(result["slides_bytes"]):
        size = len(png)
        assert size > 1000, f"Emoji slide {idx} too small: {size}"
        print(f"  Emoji slide {idx}: {size:,} bytes")

run_test("T14", "Render slides with emoji/special characters", test_render_emoji_slide)


def test_render_long_text():
    long_body = "\n".join([f"This is line {i} with some additional text to make it quite long and verbose for testing purposes." for i in range(15)])
    text = f"A Very Long Title That Goes On And On And On And Should Trigger Smaller Font Size\n---SLIDE---\nLong Content Slide\n{long_body}"
    result = render_carousel(text, palette_idx=2)
    assert "error" not in result
    assert len(result["slides_bytes"]) == 2
    for idx, png in enumerate(result["slides_bytes"]):
        size = len(png)
        assert size > 1000, f"Long text slide {idx} too small: {size}"
        print(f"  Long text slide {idx}: {size:,} bytes")

run_test("T15", "Render slides with very long text", test_render_long_text)


def test_render_missing_fields():
    # No brand_name, no brand_handle, minimal text
    text = "Just a title"
    result = render_carousel(text)
    assert "error" not in result
    assert len(result["slides_bytes"]) == 1
    size = len(result["slides_bytes"][0])
    assert size > 1000
    print(f"  Missing fields slide: {size:,} bytes")

run_test("T16", "Render slide with missing optional fields (brand, handle)", test_render_missing_fields)


def test_render_empty_content():
    text = ""
    result = render_carousel(text)
    assert result.get("error") == "No slides found" or len(result["slides_bytes"]) == 0
    print(f"  Empty content result: {result}")

run_test("T17", "Render with empty content returns error/empty", test_render_empty_content)


def test_render_multiple_slides():
    slides = [f"Slide {i} content here with enough text" for i in range(7)]
    text = "\n---SLIDE---\n".join(slides)
    result = render_carousel(text, palette_idx=0, brand_name="Multi", brand_handle="@multi")
    assert "error" not in result
    assert len(result["slides_bytes"]) == 7
    total_size = 0
    for idx, png in enumerate(result["slides_bytes"]):
        size = len(png)
        total_size += size
        assert size > 1000
        assert png[:4] == b'\x89PNG'
    print(f"  7 slides rendered, total size: {total_size:,} bytes")

run_test("T18", "Render 7 slides (multiple) all valid PNGs", test_render_multiple_slides)


def test_render_palette_cycling():
    text = "Palette Test"
    for idx in range(5):
        result = render_carousel(text, palette_idx=idx)
        assert "error" not in result
        assert len(result["slides_bytes"]) == 1
        size = len(result["slides_bytes"][0])
        assert size > 1000
        print(f"  Palette {idx} (mod {idx % 3}): {size:,} bytes")

run_test("T19", "Palette index wraps around with modulo", test_render_palette_cycling)


def test_render_write_to_disk():
    text = "Disk Write Test\n---SLIDE---\nBody content here\n---SLIDE---\nSegui per altri consigli"
    result = render_carousel(text, brand_name="DiskTest")
    tmpdir = tempfile.mkdtemp(prefix="carousel_test_")
    paths = []
    for idx, png in enumerate(result["slides_bytes"]):
        path = os.path.join(tmpdir, f"slide_{idx}.png")
        with open(path, "wb") as f:
            f.write(png)
        file_size = os.path.getsize(path)
        assert file_size > 0
        paths.append((path, file_size))
        print(f"  Written: {path} ({file_size:,} bytes)")
    assert len(paths) == 3

run_test("T20", "PNG files actually writable to disk with correct sizes", test_render_write_to_disk)


def test_caption_preserved():
    text = "Title\n---SLIDE---\nBody\n---CAPTION---\nThis is the caption with #hashtags and @mentions"
    result = render_carousel(text)
    assert result["caption"] == "This is the caption with #hashtags and @mentions"
    print(f"  Caption: {result['caption']}")

run_test("T21", "Caption text preserved through rendering pipeline", test_caption_preserved)


def test_cover_html_font_sizing():
    palette = PALETTES[0]
    # Short title -> large font
    html_short = _cover_html("Short", palette, 5)
    assert "font-size: 80px" in html_short
    # Medium title
    html_med = _cover_html("A" * 35, palette, 5)
    assert "font-size: 68px" in html_med
    # Long title
    html_long = _cover_html("A" * 55, palette, 5)
    assert "font-size: 56px" in html_long
    # Very long title
    html_vlong = _cover_html("A" * 70, palette, 5)
    assert "font-size: 46px" in html_vlong

run_test("T22", "Cover slide font size adapts to title length", test_cover_html_font_sizing)


def test_content_html_font_sizing():
    palette = PALETTES[0]
    short = _content_html("H\nShort body", 2, 5, palette)
    assert "font-size: 36px" in short
    long = _content_html("H\n" + "x" * 300, 2, 5, palette)
    assert "font-size: 26px" in long or "font-size: 24px" in long

run_test("T23", "Content slide font size adapts to body length", test_content_html_font_sizing)


def test_content_html_header_detection():
    palette = PALETTES[0]
    # Short first line -> becomes header
    html_with_header = _content_html("Short Header\nBody line 1\nBody line 2", 2, 5, palette)
    assert "slide-header" in html_with_header
    # Long first line -> no header
    html_no_header = _content_html("A" * 70 + "\nBody", 2, 5, palette)
    assert "slide-header" not in html_no_header

run_test("T24", "Content slide header detection based on first line length", test_content_html_header_detection)


def test_html_special_chars_in_title():
    text = "5 Tips: Why <HTML> & 'Quotes' Matter \"Always\""
    result = render_carousel(text)
    assert "error" not in result
    assert len(result["slides_bytes"]) == 1
    size = len(result["slides_bytes"][0])
    assert size > 1000
    print(f"  Special chars slide: {size:,} bytes")

run_test("T25", "Render slide with HTML special characters in title", test_html_special_chars_in_title)


def test_render_template_preview_fn():
    import json
    template = json.dumps({
        "cover": """<!DOCTYPE html><html><head><style>
            body { width:1080px; height:1080px; background:#111; color:white; display:flex; align-items:center; justify-content:center; font-family:sans-serif; }
        </style></head><body><h1>{{COVER_TITLE}}</h1></body></html>""",
        "content": """<!DOCTYPE html><html><head><style>
            body { width:1080px; height:1080px; background:#222; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; font-family:sans-serif; }
        </style></head><body><h2>{{CONTENT_HEADER}}</h2><div>{{CONTENT_BODY}}</div></body></html>""",
        "list": """<!DOCTYPE html><html><head><style>
            body { width:1080px; height:1080px; background:#333; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; font-family:sans-serif; }
        </style></head><body><h2>{{LIST_HEADER}}</h2><ul>{{LIST_ITEMS}}</ul></body></html>""",
        "cta": """<!DOCTYPE html><html><head><style>
            body { width:1080px; height:1080px; background:#444; color:white; display:flex; flex-direction:column; align-items:center; justify-content:center; font-family:sans-serif; }
        </style></head><body><div>{{CTA_TEXT}}</div><button>{{CTA_BUTTON}}</button></body></html>""",
    })
    result = render_template_preview(template)
    assert len(result) == 4
    for stype, png in result.items():
        assert isinstance(png, bytes)
        assert len(png) > 1000
        assert png[:4] == b'\x89PNG'
        print(f"  Preview {stype}: {len(png):,} bytes")

run_test("T26", "render_template_preview generates 4 slide type previews", test_render_template_preview_fn)


def test_render_from_template_with_aspect_ratios():
    template = """<!DOCTYPE html><html><head><style>
        body { width:100%; height:100%; background:#1a1a2e; color:white; display:flex; align-items:center; justify-content:center; font-family:sans-serif; }
    </style></head><body><div>{{SLIDE_CONTENT}}</div><span>{{SLIDE_NUM}}/{{TOTAL_SLIDES}}</span></body></html>"""
    text = "Aspect Ratio Test\n---SLIDE---\nBody content"
    for ratio in ["1:1", "4:3", "3:4"]:
        result = render_carousel_from_template(text, template, aspect_ratio=ratio)
        assert "error" not in result
        assert len(result["slides_bytes"]) == 2
        for png in result["slides_bytes"]:
            assert len(png) > 1000
        print(f"  Ratio {ratio}: {len(result['slides_bytes'][0]):,} bytes")

run_test("T27", "Custom template rendering with different aspect ratios", test_render_from_template_with_aspect_ratios)


def test_prepare_slide_html_placeholders():
    template = "<html><body>{{SLIDE_NUM}}/{{TOTAL_SLIDES}} {{BRAND_NAME}} {{BRAND_HANDLE}} {{CONTENT_HEADER}} {{CONTENT_BODY}}</body></html>"
    result = _prepare_slide_html(template, "Header\nBody text", "content", 2, 10, "MyBrand", "@mybrand")
    assert "3/10" in result  # index 2 -> slide 3
    assert "MyBrand" in result
    assert "@mybrand" in result
    assert "Header" in result  # removed from body, used as header
    assert "Body text" in result

run_test("T28", "Placeholder substitution in _prepare_slide_html", test_prepare_slide_html_placeholders)


def test_cta_html_button_detection():
    palette = PALETTES[0]
    html = _cta_html("Great content!\nFollow us for more", 5, 5, palette)
    # "Follow us for more" contains "follow" keyword -> should become action_line
    assert "cta-btn" in html

run_test("T29", "CTA slide detects follow/subscribe keywords for button", test_cta_html_button_detection)


def test_bold_markdown_rendering():
    text = "Title\n---SLIDE---\nKey Point\nUse **bold text** for emphasis and **another bold** here"
    result = render_carousel(text)
    assert "error" not in result
    assert len(result["slides_bytes"]) == 2
    print(f"  Bold text slide: {len(result['slides_bytes'][1]):,} bytes")

run_test("T30", "Markdown bold (**text**) renders in content slides", test_bold_markdown_rendering)


# ============================================================
# Print report
# ============================================================

print("\n" + "=" * 80)
print("CAROUSEL RENDERER TEST REPORT")
print("=" * 80)
passed = 0
failed = 0
for test_id, desc, status, detail in results:
    icon = "PASS" if status == "PASS" else "FAIL"
    print(f"  [{icon}] {test_id}: {desc}")
    if detail:
        for line in detail.strip().split('\n')[-5:]:
            print(f"         {line}")
    if status == "PASS":
        passed += 1
    else:
        failed += 1

print("=" * 80)
print(f"TOTAL: {passed + failed} | PASSED: {passed} | FAILED: {failed}")
print("=" * 80)
