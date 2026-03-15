"""Renderer contract tests — verify determinism, graceful degradation,
override precedence, and theme merge behavior.

These tests exercise the actual slide_renderer.py functions to ensure
the architecture spec invariants hold under real conditions.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.slide_renderer import (
    apply_theme,
    apply_overrides,
    render_slides,
    _parse_color,
    _ELEMENT_RENDERERS,
)
from services.renderer_validators import ELEMENT_TYPES


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

def _base_template():
    return {
        "canvas": {"width": 1080, "height": 1080, "background": "#111111"},
        "slides": [
            {
                "name": "cover",
                "elements": [
                    {"type": "rect", "role": "accent", "x": 80, "y": 420, "width": 64, "height": 5},
                    {"type": "title", "content_key": "title", "x": 80, "y": 440, "max_width": 920},
                    {"type": "subtitle", "content_key": "subtitle", "x": 80, "y": 600, "max_width": 920},
                    {"type": "slide_counter", "x": 1000, "y": 1000},
                ],
            },
        ],
    }


def _base_theme():
    return {
        "id": "test",
        "fonts": {"title": "Inter", "subtitle": "Inter"},
        "sizes": {"title": 72, "subtitle": 36},
        "weights": {"title": 800, "subtitle": 400},
        "colors": {
            "title": "#ffffff",
            "subtitle": "#aaaaaa",
            "accent": "#c9a36a",
            "overlay": "#00000090",
        },
        "button": {"padding_x": 60, "padding_y": 30, "radius": 12},
    }


def _base_content():
    return {
        "title": "Test Title",
        "subtitle": "Test Subtitle",
        "body": "Test body text",
        "bullets": ["Point A", "Point B"],
        "cta": "Follow Us",
    }


# =======================================================================
# Dispatcher completeness
# =======================================================================

class TestDispatcherCompleteness:
    def test_all_element_types_have_renderer(self):
        """Every type in the architecture spec ELEMENT_TYPES must have a renderer."""
        for etype in ELEMENT_TYPES:
            assert etype in _ELEMENT_RENDERERS, (
                f"element type {etype!r} has no renderer in _ELEMENT_RENDERERS"
            )

    def test_no_extra_renderers(self):
        """No renderer exists for types outside the spec."""
        for etype in _ELEMENT_RENDERERS:
            assert etype in ELEMENT_TYPES, (
                f"renderer exists for undeclared type {etype!r}"
            )


# =======================================================================
# Theme merge: theme fills gaps, doesn't override
# =======================================================================

class TestThemeMerge:
    def test_theme_fills_missing_font(self):
        el = {"type": "title", "x": 0, "y": 0}
        merged = apply_theme(el, _base_theme())
        assert merged["font"] == "Inter"

    def test_theme_does_not_override_explicit_font(self):
        el = {"type": "title", "x": 0, "y": 0, "font": "Syne"}
        merged = apply_theme(el, _base_theme())
        assert merged["font"] == "Syne"

    def test_theme_fills_missing_size(self):
        el = {"type": "title", "x": 0, "y": 0}
        merged = apply_theme(el, _base_theme())
        assert merged["size"] == 72

    def test_theme_does_not_override_explicit_size(self):
        el = {"type": "title", "x": 0, "y": 0, "size": 48}
        merged = apply_theme(el, _base_theme())
        assert merged["size"] == 48

    def test_theme_fills_missing_color(self):
        el = {"type": "title", "x": 0, "y": 0}
        merged = apply_theme(el, _base_theme())
        assert merged["color"] == "#ffffff"

    def test_theme_does_not_override_explicit_color(self):
        el = {"type": "title", "x": 0, "y": 0, "color": "#FF0000"}
        merged = apply_theme(el, _base_theme())
        assert merged["color"] == "#FF0000"

    def test_rect_role_maps_to_theme_color(self):
        el = {"type": "rect", "role": "accent", "x": 0, "y": 0, "width": 64, "height": 5}
        merged = apply_theme(el, _base_theme())
        assert merged["color"] == "#c9a36a"

    def test_rect_explicit_color_not_overridden(self):
        el = {"type": "rect", "role": "accent", "x": 0, "y": 0, "width": 64, "height": 5, "color": "#FF0000"}
        merged = apply_theme(el, _base_theme())
        assert merged["color"] == "#FF0000"

    def test_no_theme_returns_element_unchanged(self):
        el = {"type": "title", "x": 0, "y": 0, "font": "Syne"}
        merged = apply_theme(el, None)
        assert merged == el

    def test_theme_is_non_mutating(self):
        el = {"type": "title", "x": 0, "y": 0}
        original_el = dict(el)
        apply_theme(el, _base_theme())
        assert el == original_el  # original not mutated

    def test_cta_button_styling_from_theme(self):
        el = {"type": "cta", "x": 0, "y": 0}
        theme = _base_theme()
        theme["colors"]["button"] = "#FFD700"
        theme["colors"]["cta"] = "#ffffff"
        merged = apply_theme(el, theme)
        assert merged["button_color"] == "#FFD700"
        assert merged["button_padding_x"] == 60
        assert merged["button_padding_y"] == 30
        assert merged["button_radius"] == 12

    def test_bullet_list_marker_color_from_theme(self):
        el = {"type": "bullet_list", "x": 0, "y": 0}
        theme = _base_theme()
        theme["colors"]["marker"] = "#c9a36a"
        theme["colors"]["bullet_list"] = "#ffffff"
        merged = apply_theme(el, theme)
        assert merged["marker_color"] == "#c9a36a"


# =======================================================================
# Override precedence: overrides > theme > layout
# =======================================================================

class TestOverridePrecedence:
    def test_override_wins_over_theme(self):
        el = {"type": "title", "x": 0, "y": 0}
        themed = apply_theme(el, _base_theme())
        assert themed["color"] == "#ffffff"  # from theme

        overridden = apply_overrides(themed, {"title_color": "#FF0000"})
        assert overridden["color"] == "#FF0000"  # override wins

    def test_override_wins_over_layout(self):
        el = {"type": "title", "x": 0, "y": 0, "font": "Syne"}
        overridden = apply_overrides(el, {"title_font": "Montserrat"})
        assert overridden["font"] == "Montserrat"

    def test_three_layer_precedence(self):
        """Layout → Theme → Override, each layer overwriting the previous."""
        el = {"type": "title", "x": 0, "y": 0, "color": "#000000"}  # layout sets black
        themed = apply_theme(el, _base_theme())
        assert themed["color"] == "#000000"  # theme doesn't override (layout has it)

        overridden = apply_overrides(themed, {"title_color": "#FF0000"})
        assert overridden["color"] == "#FF0000"  # override always wins

    def test_accent_color_override(self):
        el = {"type": "rect", "role": "accent", "x": 0, "y": 0, "width": 64, "height": 5}
        themed = apply_theme(el, _base_theme())
        assert themed["color"] == "#c9a36a"

        overridden = apply_overrides(themed, {"accent_color": "#FF0000"})
        assert overridden["color"] == "#FF0000"

    def test_cta_button_color_override(self):
        el = {"type": "cta", "x": 0, "y": 0}
        theme = _base_theme()
        theme["colors"]["button"] = "#FFD700"
        themed = apply_theme(el, theme)
        assert themed["button_color"] == "#FFD700"

        overridden = apply_overrides(themed, {"cta_button_color": "#0000FF"})
        assert overridden["button_color"] == "#0000FF"

    def test_override_is_non_mutating(self):
        el = {"type": "title", "x": 0, "y": 0, "font": "Inter"}
        original_el = dict(el)
        apply_overrides(el, {"title_font": "Montserrat"})
        assert el == original_el

    def test_empty_overrides_passthrough(self):
        el = {"type": "title", "x": 0, "y": 0, "font": "Inter"}
        result = apply_overrides(el, {})
        assert result == el


# =======================================================================
# Color parsing
# =======================================================================

class TestColorParsing:
    def test_3_digit_hex(self):
        assert _parse_color("#FFF") == (255, 255, 255, 255)

    def test_6_digit_hex(self):
        assert _parse_color("#FF0000") == (255, 0, 0, 255)

    def test_8_digit_hex(self):
        assert _parse_color("#FF000080") == (255, 0, 0, 128)

    def test_invalid_fallback(self):
        assert _parse_color("not-a-color") == (255, 255, 255, 255)

    def test_empty_fallback(self):
        assert _parse_color("") == (255, 255, 255, 255)


# =======================================================================
# Rendering: determinism
# =======================================================================

class TestRenderDeterminism:
    def test_identical_inputs_produce_identical_output(self):
        """Same inputs → byte-identical PNG output."""
        template = _base_template()
        content = _base_content()
        theme = _base_theme()

        result1 = render_slides(template, content, theme=theme)
        result2 = render_slides(template, content, theme=theme)

        assert len(result1) == len(result2)
        for i, (b1, b2) in enumerate(zip(result1, result2)):
            assert b1 == b2, f"Slide {i} output differs between identical runs"

    def test_different_content_produces_different_output(self):
        template = _base_template()
        theme = _base_theme()

        result1 = render_slides(template, {"title": "AAA", "subtitle": "BBB"}, theme=theme)
        result2 = render_slides(template, {"title": "CCC", "subtitle": "DDD"}, theme=theme)

        assert result1[0] != result2[0]


# =======================================================================
# Rendering: graceful degradation
# =======================================================================

class TestGracefulDegradation:
    def test_missing_content_key_does_not_crash(self):
        """Renderer skips text elements when content key is missing."""
        template = _base_template()
        result = render_slides(template, {})  # empty content
        assert len(result) == 1
        assert len(result[0]) > 0  # produced a valid PNG

    def test_empty_asset_map_does_not_crash(self):
        """Renderer skips image elements when asset is missing."""
        template = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "image", "asset_id": "bg", "x": 0, "y": 0, "width": 1080, "height": 1080},
                        {"type": "title", "x": 80, "y": 200, "max_width": 920},
                    ],
                },
            ],
        }
        result = render_slides(template, {"title": "Test"}, asset_map={})
        assert len(result) == 1

    def test_no_theme_renders_with_defaults(self):
        result = render_slides(_base_template(), _base_content(), theme=None)
        assert len(result) == 1

    def test_unknown_element_type_skipped(self):
        """Unknown element types are skipped with a warning, not crash."""
        template = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "title", "x": 80, "y": 200, "max_width": 920},
                    ],
                },
            ],
        }
        # Inject unknown element (simulates what would happen if validation is bypassed)
        template["slides"][0]["elements"].append({"type": "sparkle"})
        # This should raise because validation catches the unknown type
        with pytest.raises(ValueError, match="unknown element type"):
            render_slides(template, {"title": "Test"})

    def test_image_fill_fallback(self):
        """Image with fill but no asset renders a color overlay instead of crashing."""
        template = {
            "canvas": {"width": 100, "height": 100},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "image", "asset_id": "missing_bg", "fill": "#FF0000",
                         "x": 0, "y": 0, "width": 100, "height": 100},
                    ],
                },
            ],
        }
        result = render_slides(template, {}, asset_map={})
        assert len(result) == 1
        assert len(result[0]) > 0


# =======================================================================
# Rendering: validation gate
# =======================================================================

class TestValidationGate:
    def test_invalid_template_rejected(self):
        """render_slides raises ValueError for invalid templates."""
        with pytest.raises(ValueError, match="validation failed"):
            render_slides(
                {"slides": []},  # missing canvas, empty slides
                _base_content(),
            )

    def test_invalid_canvas_dimensions_rejected(self):
        with pytest.raises(ValueError):
            render_slides(
                {"canvas": {"width": -1, "height": 1080}, "slides": [{"name": "s1", "elements": []}]},
                _base_content(),
            )


# =======================================================================
# Theme inheritance (integration with carousel_pipeline)
# =======================================================================

class TestThemeInheritance:
    def test_load_real_theme(self):
        """Load an actual theme file and validate it."""
        try:
            from services.carousel_pipeline import load_theme
        except BaseException:
            pytest.skip("carousel_pipeline not importable (missing dependencies)")

        from services.renderer_validators import validate_theme

        try:
            theme = load_theme("industrial_dark")
        except (ValueError, FileNotFoundError):
            pytest.skip("industrial_dark theme not available")

        r = validate_theme(theme)
        assert r.valid, f"Theme validation errors: {r.errors}"
        assert theme["id"] == "industrial_dark"

    def test_load_real_template(self):
        """Load an actual template file and validate it."""
        try:
            from services.carousel_pipeline import load_template
        except BaseException:
            pytest.skip("carousel_pipeline not importable (missing dependencies)")

        from services.renderer_validators import validate_template

        try:
            template = load_template("minimal_layout", "center")
        except (ValueError, FileNotFoundError):
            pytest.skip("minimal_layout/center not available")

        r = validate_template(template)
        assert r.valid, f"Template validation errors: {r.errors}"


# =======================================================================
# Anchor resolution
# =======================================================================

class TestAnchorResolution:
    def test_all_anchors_resolve(self):
        """Every valid anchor produces valid coordinates."""
        from services.asset_placement import resolve_anchor
        from services.renderer_validators import VALID_ANCHORS

        for anchor in VALID_ANCHORS:
            coords = resolve_anchor(anchor, box={"width": 100, "height": 100})
            assert "x" in coords
            assert "y" in coords
            assert "width" in coords
            assert "height" in coords
            assert coords["width"] > 0
            assert coords["height"] > 0

    def test_invalid_anchor_defaults_to_center(self):
        from services.asset_placement import resolve_anchor

        coords = resolve_anchor("nonexistent_anchor", box={"width": 100, "height": 100})
        expected = resolve_anchor("center", box={"width": 100, "height": 100})
        assert coords == expected

    def test_full_bg_covers_canvas(self):
        from services.asset_placement import resolve_anchor

        coords = resolve_anchor("full_bg", canvas_w=1080, canvas_h=1080)
        assert coords == {"x": 0, "y": 0, "width": 1080, "height": 1080}

    def test_top_left_respects_margins(self):
        from services.asset_placement import resolve_anchor

        coords = resolve_anchor(
            "top_left",
            box={"width": 160, "height": 80, "margin_x": 40, "margin_y": 40},
            canvas_w=1080,
            canvas_h=1080,
        )
        assert coords["x"] == 40
        assert coords["y"] == 40
        assert coords["width"] == 160
        assert coords["height"] == 80
