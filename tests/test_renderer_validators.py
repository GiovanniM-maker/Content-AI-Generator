"""Tests for renderer validation layers.

Covers every validator in services/renderer_validators.py:
- Template validation (structure, elements, anchors, roles)
- Theme validation (fonts, sizes, weights, colors, tokens)
- Override validation (key format, value types)
- Placement override validation (anchors, boxes, slide targets)
- Asset mapping validation (declared slots vs provided)
- Content validation (lengths, types)
- Registry validation (filesystem cross-check)
"""

import os
import pytest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.renderer_validators import (
    ValidationResult,
    validate_template,
    validate_theme,
    validate_overrides,
    validate_placement_overrides,
    validate_asset_mapping,
    validate_content,
    validate_registry,
    validate_render_inputs,
    is_valid_color,
    ELEMENT_TYPES,
    VALID_ANCHORS,
    VALID_OVERRIDE_KEYS,
)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

def _minimal_template():
    """Return the smallest valid template."""
    return {
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


def _full_template():
    """Return a template with all element types."""
    return {
        "canvas": {"width": 1080, "height": 1080, "background": "#111111"},
        "slides": [
            {
                "name": "cover",
                "elements": [
                    {"type": "image", "asset_id": "background_asset", "x": 0, "y": 0, "width": 1080, "height": 1080},
                    {"type": "rect", "role": "overlay", "x": 0, "y": 0, "width": 1080, "height": 1080},
                    {"type": "rect", "role": "accent", "x": 80, "y": 420, "width": 64, "height": 5},
                    {"type": "title", "content_key": "title", "x": 80, "y": 440, "max_width": 920},
                    {"type": "subtitle", "content_key": "subtitle", "x": 80, "y": 600, "max_width": 920},
                    {"type": "slide_counter", "x": 1000, "y": 1000},
                ],
            },
            {
                "name": "list",
                "elements": [
                    {"type": "image", "asset_id": "background_asset", "x": 0, "y": 0, "width": 1080, "height": 1080},
                    {"type": "rect", "role": "overlay_heavy", "x": 0, "y": 0, "width": 1080, "height": 1080},
                    {"type": "bullet_list", "content_key": "bullets", "x": 80, "y": 280, "max_width": 920},
                    {"type": "slide_counter", "x": 1000, "y": 1000},
                ],
            },
            {
                "name": "cta",
                "elements": [
                    {"type": "image", "asset_id": "background_asset", "x": 0, "y": 0, "width": 1080, "height": 1080},
                    {"type": "cta", "content_key": "cta", "x": 120, "y": 480, "max_width": 840, "align": "center"},
                    {"type": "slide_counter", "x": 1000, "y": 1000},
                ],
            },
        ],
    }


def _minimal_theme():
    """Return the smallest valid theme."""
    return {
        "id": "test_theme",
        "name": "Test Theme",
        "fonts": {"title": "Inter"},
        "sizes": {"title": 72},
        "weights": {"title": 800},
        "colors": {"title": "#ffffff", "accent": "#c9a36a"},
    }


def _valid_content():
    return {
        "title": "Test Title",
        "subtitle": "Test Subtitle",
        "body": "Test body paragraph",
        "bullets": ["Point 1", "Point 2", "Point 3"],
        "cta": "Follow us",
    }


# =======================================================================
# Color validation
# =======================================================================

class TestColorValidation:
    def test_valid_3_digit_hex(self):
        assert is_valid_color("#FFF")

    def test_valid_6_digit_hex(self):
        assert is_valid_color("#FF0000")

    def test_valid_8_digit_hex(self):
        assert is_valid_color("#FF000080")

    def test_invalid_no_hash(self):
        assert not is_valid_color("FF0000")

    def test_invalid_too_short(self):
        assert not is_valid_color("#F")

    def test_invalid_5_digits(self):
        assert not is_valid_color("#FFFFF")

    def test_invalid_non_hex(self):
        assert not is_valid_color("#GGGGGG")

    def test_invalid_empty(self):
        assert not is_valid_color("")

    def test_invalid_none(self):
        assert not is_valid_color(None)

    def test_invalid_css_function(self):
        assert not is_valid_color("rgb(255,0,0)")

    def test_valid_lowercase(self):
        assert is_valid_color("#aabbcc")


# =======================================================================
# Template validation
# =======================================================================

class TestTemplateValidation:
    def test_valid_minimal_template(self):
        r = validate_template(_minimal_template())
        assert r.valid
        assert len(r.errors) == 0

    def test_valid_full_template(self):
        r = validate_template(_full_template())
        assert r.valid

    def test_not_a_dict(self):
        r = validate_template("not a dict")
        assert not r.valid
        assert "must be a dict" in r.errors[0]

    def test_missing_canvas(self):
        t = {"slides": [{"name": "s1", "elements": []}]}
        r = validate_template(t)
        assert not r.valid
        assert any("canvas" in e for e in r.errors)

    def test_canvas_missing_width(self):
        t = {"canvas": {"height": 1080}, "slides": [{"name": "s1", "elements": []}]}
        r = validate_template(t)
        assert not r.valid
        assert any("width" in e for e in r.errors)

    def test_canvas_negative_dimensions(self):
        t = {"canvas": {"width": -1, "height": 1080}, "slides": [{"name": "s1", "elements": []}]}
        r = validate_template(t)
        assert not r.valid

    def test_no_slides(self):
        t = {"canvas": {"width": 1080, "height": 1080}, "slides": []}
        r = validate_template(t)
        assert not r.valid
        assert any("non-empty" in e for e in r.errors)

    def test_slide_missing_name(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [{"elements": []}],
        }
        r = validate_template(t)
        assert not r.valid
        assert any("name" in e for e in r.errors)

    def test_duplicate_slide_names(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {"name": "cover", "elements": []},
                {"name": "cover", "elements": []},
            ],
        }
        r = validate_template(t)
        assert not r.valid
        assert any("duplicate" in e for e in r.errors)

    def test_unknown_element_type(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {"name": "cover", "elements": [{"type": "sparkle_effect"}]},
            ],
        }
        r = validate_template(t)
        assert not r.valid
        assert any("unknown element type" in e for e in r.errors)

    def test_image_element_no_positioning(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {"name": "cover", "elements": [{"type": "image"}]},
            ],
        }
        r = validate_template(t)
        # Warning, not error (renderer will skip gracefully)
        assert r.valid
        assert any("no asset_id" in w for w in r.warnings)

    def test_image_element_invalid_anchor(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "image", "asset_id": "bg", "anchor": "floating_left"},
                    ],
                },
            ],
        }
        r = validate_template(t)
        assert not r.valid
        assert any("invalid anchor" in e for e in r.errors)

    def test_image_element_valid_anchor(self):
        for anchor in VALID_ANCHORS:
            t = {
                "canvas": {"width": 1080, "height": 1080},
                "slides": [
                    {
                        "name": "cover",
                        "elements": [
                            {"type": "image", "asset_id": "bg", "anchor": anchor},
                        ],
                    },
                ],
            }
            r = validate_template(t)
            assert r.valid, f"anchor {anchor!r} should be valid"

    def test_rect_unknown_role(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "rect", "role": "sparkle", "x": 0, "y": 0, "width": 100, "height": 100},
                    ],
                },
            ],
        }
        r = validate_template(t)
        assert r.valid  # warning only
        assert any("unknown rect role" in w for w in r.warnings)

    def test_text_invalid_color(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "title", "x": 80, "y": 200, "color": "not-a-color"},
                    ],
                },
            ],
        }
        r = validate_template(t)
        assert r.valid  # warning only
        assert any("invalid color" in w for w in r.warnings)

    def test_text_invalid_weight(self):
        t = {
            "canvas": {"width": 1080, "height": 1080},
            "slides": [
                {
                    "name": "cover",
                    "elements": [
                        {"type": "title", "x": 80, "y": 200, "weight": 1500},
                    ],
                },
            ],
        }
        r = validate_template(t)
        assert any("weight" in w for w in r.warnings)

    def test_all_element_types_accepted(self):
        """Every type in ELEMENT_TYPES should be accepted."""
        for etype in ELEMENT_TYPES:
            el = {"type": etype, "x": 0, "y": 0}
            if etype == "image":
                el["asset_id"] = "test"
            if etype == "rect":
                el["width"] = 100
                el["height"] = 100
            t = {
                "canvas": {"width": 1080, "height": 1080},
                "slides": [{"name": "cover", "elements": [el]}],
            }
            r = validate_template(t)
            assert r.valid, f"element type {etype!r} should be accepted"


# =======================================================================
# Theme validation
# =======================================================================

class TestThemeValidation:
    def test_valid_theme(self):
        r = validate_theme(_minimal_theme())
        assert r.valid

    def test_not_a_dict(self):
        r = validate_theme("not a dict")
        assert not r.valid

    def test_missing_id(self):
        theme = _minimal_theme()
        del theme["id"]
        r = validate_theme(theme)
        assert r.valid  # warning only
        assert any("missing id" in w for w in r.warnings)

    def test_font_not_string(self):
        theme = _minimal_theme()
        theme["fonts"]["title"] = 123
        r = validate_theme(theme)
        assert any("string" in w for w in r.warnings)

    def test_size_not_positive(self):
        theme = _minimal_theme()
        theme["sizes"]["title"] = -10
        r = validate_theme(theme)
        assert any("positive" in w for w in r.warnings)

    def test_weight_out_of_range(self):
        theme = _minimal_theme()
        theme["weights"]["title"] = 1200
        r = validate_theme(theme)
        assert any("100-900" in w for w in r.warnings)

    def test_invalid_color(self):
        theme = _minimal_theme()
        theme["colors"]["title"] = "not-a-color"
        r = validate_theme(theme)
        assert any("not a valid hex" in w for w in r.warnings)

    def test_unresolved_token_in_sizes(self):
        theme = _minimal_theme()
        theme["sizes"]["body"] = "typography.h1"
        r = validate_theme(theme)
        assert any("unresolved token" in w for w in r.warnings)

    def test_unresolved_token_in_colors(self):
        theme = _minimal_theme()
        theme["colors"]["accent"] = "colors.gold"
        r = validate_theme(theme)
        assert any("unresolved token" in w for w in r.warnings)

    def test_button_negative_padding(self):
        theme = _minimal_theme()
        theme["button"] = {"padding_x": -5}
        r = validate_theme(theme)
        assert any("non-negative" in w for w in r.warnings)


# =======================================================================
# Override validation
# =======================================================================

class TestOverrideValidation:
    def test_valid_overrides(self):
        r = validate_overrides({
            "title_font": "Montserrat",
            "title_color": "#FFD700",
            "title_size": 64,
            "title_weight": 800,
        })
        assert r.valid
        assert len(r.warnings) == 0

    def test_unknown_override_key(self):
        r = validate_overrides({"sparkle_intensity": 9000})
        assert r.valid  # warning only
        assert any("unknown override key" in w for w in r.warnings)

    def test_invalid_color_in_override(self):
        r = validate_overrides({"title_color": "not-valid"})
        assert any("invalid color" in w for w in r.warnings)

    def test_invalid_size_in_override(self):
        r = validate_overrides({"title_size": -10})
        assert any("positive" in w for w in r.warnings)

    def test_invalid_weight_in_override(self):
        r = validate_overrides({"title_weight": 1500})
        assert any("100-900" in w for w in r.warnings)

    def test_empty_font_in_override(self):
        r = validate_overrides({"title_font": ""})
        assert any("non-empty string" in w for w in r.warnings)

    def test_accent_color_accepted(self):
        r = validate_overrides({"accent_color": "#FF0000"})
        assert r.valid
        assert len(r.warnings) == 0

    def test_bullet_list_marker_color_accepted(self):
        r = validate_overrides({"bullet_list_marker_color": "#00FF00"})
        assert r.valid

    def test_cta_button_color_accepted(self):
        r = validate_overrides({"cta_button_color": "#0000FF"})
        assert r.valid

    def test_not_a_dict(self):
        r = validate_overrides("not a dict")
        assert not r.valid


# =======================================================================
# Placement override validation
# =======================================================================

class TestPlacementOverrideValidation:
    def test_valid_placement(self):
        r = validate_placement_overrides({
            "logo_asset": {
                "anchor": "top_left",
                "box": {"width": 160, "height": 80, "margin_x": 40, "margin_y": 40},
                "slides": ["cover", "cta"],
            },
        }, _full_template())
        assert r.valid

    def test_invalid_anchor(self):
        r = validate_placement_overrides({
            "logo_asset": {"anchor": "floating_center"},
        })
        assert not r.valid
        assert any("invalid anchor" in e for e in r.errors)

    def test_negative_box_width(self):
        r = validate_placement_overrides({
            "logo_asset": {
                "anchor": "top_left",
                "box": {"width": -100, "height": 80},
            },
        })
        assert not r.valid
        assert any("positive" in e for e in r.errors)

    def test_unknown_slide_target(self):
        r = validate_placement_overrides(
            {"logo_asset": {"anchor": "center", "slides": ["nonexistent_slide"]}},
            _full_template(),
        )
        assert r.valid  # warning only
        assert any("unknown slide" in w for w in r.warnings)

    def test_valid_all_anchors(self):
        for anchor in VALID_ANCHORS:
            r = validate_placement_overrides(
                {"asset": {"anchor": anchor}},
            )
            assert r.valid, f"anchor {anchor!r} should be valid"

    def test_not_a_dict(self):
        r = validate_placement_overrides("not a dict")
        assert not r.valid


# =======================================================================
# Asset mapping validation
# =======================================================================

class TestAssetMappingValidation:
    def test_all_slots_provided(self):
        r = validate_asset_mapping(
            {"background_asset": "placeholder"},
            _full_template(),
        )
        assert r.valid
        assert len(r.warnings) == 0

    def test_missing_slot(self):
        r = validate_asset_mapping(
            {},
            _full_template(),
        )
        assert r.valid  # warning only
        assert any("no asset provided" in w for w in r.warnings)

    def test_extra_asset(self):
        r = validate_asset_mapping(
            {"background_asset": "img", "logo_asset": "img2"},
            _full_template(),
        )
        assert r.valid  # warning only
        assert any("not declared" in w for w in r.warnings)

    def test_not_a_dict(self):
        r = validate_asset_mapping("not a dict", _full_template())
        assert not r.valid


# =======================================================================
# Content validation
# =======================================================================

class TestContentValidation:
    def test_valid_content(self):
        r = validate_content(_valid_content())
        assert r.valid
        assert len(r.warnings) == 0

    def test_title_too_long(self):
        r = validate_content({"title": "A" * 201})
        assert any("truncated" in w or "200" in w for w in r.warnings)

    def test_subtitle_too_long(self):
        r = validate_content({"subtitle": "A" * 301})
        assert any("300" in w for w in r.warnings)

    def test_body_too_long(self):
        r = validate_content({"body": "A" * 1001})
        assert any("1000" in w for w in r.warnings)

    def test_cta_too_long(self):
        r = validate_content({"cta": "A" * 101})
        assert any("100" in w for w in r.warnings)

    def test_too_many_bullets(self):
        r = validate_content({"bullets": [f"Point {i}" for i in range(9)]})
        assert any("8" in w for w in r.warnings)

    def test_bullet_too_long(self):
        r = validate_content({"bullets": ["A" * 201]})
        assert any("200" in w for w in r.warnings)

    def test_bullets_not_list(self):
        r = validate_content({"bullets": "not a list"})
        assert any("list" in w for w in r.warnings)

    def test_title_not_string(self):
        r = validate_content({"title": 123})
        assert any("string" in w for w in r.warnings)

    def test_not_a_dict(self):
        r = validate_content("not a dict")
        assert not r.valid

    def test_empty_content_valid(self):
        r = validate_content({})
        assert r.valid


# =======================================================================
# Registry validation
# =======================================================================

class TestRegistryValidation:
    def test_real_registry(self):
        """Validate the actual registry.json against the filesystem."""
        import json
        base = os.path.dirname(os.path.dirname(__file__))
        registry_path = os.path.join(base, "templates", "registry.json")
        if not os.path.isfile(registry_path):
            pytest.skip("registry.json not found")

        with open(registry_path, "r") as f:
            registry = json.load(f)

        r = validate_registry(registry)
        # The real registry should have no errors
        assert r.valid, f"Registry errors: {r.errors}"

    def test_missing_layout(self):
        registry = {
            "nonexistent_layout": {
                "name": "Ghost",
                "variants": ["default"],
                "default_theme": "industrial_dark",
                "themes": ["industrial_dark"],
            }
        }
        r = validate_registry(registry)
        assert not r.valid
        assert any("not found" in e for e in r.errors)

    def test_missing_variant_file(self):
        # Use a real layout dir but fake variant
        registry = {
            "minimal_layout": {
                "name": "Minimal",
                "variants": ["center", "nonexistent_variant"],
                "default_theme": "industrial_dark",
                "themes": ["industrial_dark"],
            }
        }
        r = validate_registry(registry)
        assert not r.valid
        assert any("nonexistent_variant" in e for e in r.errors)

    def test_missing_theme_referenced(self):
        registry = {
            "minimal_layout": {
                "name": "Minimal",
                "variants": ["center"],
                "default_theme": "ghost_theme",
                "themes": ["ghost_theme"],
            }
        }
        r = validate_registry(registry)
        # Warnings for missing themes
        assert any("ghost_theme" in w for w in r.warnings)

    def test_not_a_dict(self):
        r = validate_registry("not a dict")
        assert not r.valid


# =======================================================================
# Composite validation
# =======================================================================

class TestCompositeValidation:
    def test_valid_full_inputs(self):
        r = validate_render_inputs(
            template=_full_template(),
            theme=_minimal_theme(),
            content=_valid_content(),
            asset_map={"background_asset": "placeholder"},
            overrides={"title_color": "#FFD700"},
        )
        assert r.valid

    def test_invalid_template_blocks_all(self):
        r = validate_render_inputs(
            template={"slides": []},  # missing canvas, empty slides
            theme=_minimal_theme(),
            content=_valid_content(),
        )
        assert not r.valid

    def test_warnings_accumulate(self):
        r = validate_render_inputs(
            template=_full_template(),
            content={"title": "A" * 300},  # too long
            overrides={"unknown_key": 123},  # unknown key
        )
        assert r.valid  # warnings only
        assert len(r.warnings) >= 2


# =======================================================================
# ValidationResult
# =======================================================================

class TestValidationResult:
    def test_empty_is_valid(self):
        r = ValidationResult()
        assert r.valid
        assert bool(r)

    def test_warning_still_valid(self):
        r = ValidationResult(warnings=["minor issue"])
        assert r.valid

    def test_error_makes_invalid(self):
        r = ValidationResult(errors=["fatal issue"])
        assert not r.valid
        assert not bool(r)

    def test_merge(self):
        a = ValidationResult(errors=["e1"], warnings=["w1"])
        b = ValidationResult(errors=["e2"], warnings=["w2"])
        c = a.merge(b)
        assert len(c.errors) == 2
        assert len(c.warnings) == 2
        assert not c.valid
