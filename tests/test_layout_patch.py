"""Tests for services/layout_patch.py — layout patch system.

Covers:
- Patch operation validation (all 7 op types)
- Element ID validation
- Anchor validation
- Box dimension validation
- Style validation
- Target slide validation
- Patch application (add, update, remove, move, etc.)
- HTML overlay generation
- Position resolution
- Built-in element overrides
- Edge cases and error handling
- Mode detection for LAYOUT_EDIT
"""

import copy
import pytest

from services.layout_patch import (
    PATCH_OPS,
    ELEMENT_TYPES,
    VALID_ANCHORS,
    VALID_SLIDE_TYPES,
    BUILTIN_ELEMENT_IDS,
    PatchValidationResult,
    validate_patch_operations,
    apply_patch_operations,
    resolve_overlay_position,
    render_overlay_html,
    render_all_overlays,
    build_layout_edit_prompt,
    LAYOUT_EDIT_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_spec():
    """Minimal design_spec for testing."""
    return {
        "colors": {
            "background": "#0f0f0f",
            "primary_text": "#ffffff",
            "secondary_text": "rgba(255,255,255,0.7)",
            "accent": "#7c5ce7",
        },
        "typography": {
            "heading_font": "Inter",
            "body_font": "Inter",
        },
        "images": {
            "logo_url": "https://example.com/logo.png",
            "background_image_url": "",
            "slide_images": {"cover": ""},
        },
    }


@pytest.fixture
def add_text_op():
    """Valid add_element operation."""
    return {
        "op": "add_element",
        "id": "brand_handle",
        "target_slides": None,
        "element": {
            "type": "text",
            "text_value": "@Juan",
            "anchor": "bottom_right",
            "box": {"width": 180, "height": 40, "margin_x": 32, "margin_y": 24},
            "style": {"font_size": 18, "font_weight": 600},
        },
    }


@pytest.fixture
def move_op():
    """Valid move_element operation."""
    return {
        "op": "move_element",
        "id": "cover_title",
        "target_slides": ["cover"],
        "anchor": "top_center",
        "box": {"width": 920, "height": 200, "margin_x": 80, "margin_y": 120},
    }


# ===========================================================================
# SECTION 1: PatchValidationResult
# ===========================================================================

class TestPatchValidationResult:
    def test_valid_when_no_errors(self):
        r = PatchValidationResult()
        assert r.valid
        assert bool(r)

    def test_invalid_when_errors(self):
        r = PatchValidationResult(errors=["bad"])
        assert not r.valid
        assert not bool(r)

    def test_warnings_dont_invalidate(self):
        r = PatchValidationResult(warnings=["hmm"])
        assert r.valid


# ===========================================================================
# SECTION 2: Operation validation — valid operations
# ===========================================================================

class TestValidOperations:
    def test_add_element_text(self, add_text_op):
        result = validate_patch_operations([add_text_op])
        assert result.valid, result.errors

    def test_add_element_image(self):
        op = {
            "op": "add_element",
            "id": "custom_watermark",
            "element": {
                "type": "image",
                "asset_url": "https://example.com/watermark.png",
                "anchor": "top_right",
                "box": {"width": 100, "height": 100, "margin_x": 20, "margin_y": 20},
            },
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_add_element_shape(self):
        op = {
            "op": "add_element",
            "id": "accent_bar",
            "element": {
                "type": "shape",
                "anchor": "bottom_center",
                "box": {"width": 200, "height": 5},
                "style": {"background": "#ff0000"},
            },
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_add_element_divider(self):
        op = {
            "op": "add_element",
            "id": "separator",
            "element": {"type": "divider", "anchor": "center"},
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_update_element(self):
        op = {
            "op": "update_element",
            "id": "cover_title",
            "changes": {
                "style": {"font_size": 48, "font_weight": 700},
            },
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_remove_element(self):
        op = {"op": "remove_element", "id": "cover_accent_line"}
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_move_element(self, move_op):
        result = validate_patch_operations([move_op])
        assert result.valid, result.errors

    def test_update_style(self):
        op = {
            "op": "update_style",
            "id": "cover_subtitle",
            "style": {"color": "#ff0000", "opacity": 0.8},
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_update_opacity(self):
        op = {
            "op": "update_opacity",
            "id": "global_background",
            "opacity": 0.2,
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_update_slide_scope(self):
        op = {
            "op": "update_slide_scope",
            "id": "global_logo",
            "target_slides": ["cover", "cta"],
        }
        result = validate_patch_operations([op])
        assert result.valid, result.errors

    def test_multiple_valid_operations(self, add_text_op, move_op):
        result = validate_patch_operations([add_text_op, move_op])
        assert result.valid, result.errors

    def test_target_slides_null_means_all(self, add_text_op):
        add_text_op["target_slides"] = None
        result = validate_patch_operations([add_text_op])
        assert result.valid, result.errors

    def test_all_valid_slide_types(self, add_text_op):
        add_text_op["target_slides"] = ["cover", "content", "list", "cta"]
        result = validate_patch_operations([add_text_op])
        assert result.valid, result.errors


# ===========================================================================
# SECTION 3: Operation validation — invalid operations
# ===========================================================================

class TestInvalidOperations:
    def test_unknown_op(self):
        result = validate_patch_operations([{"op": "destroy_everything", "id": "x"}])
        assert not result.valid
        assert "unknown op" in result.errors[0]

    def test_not_a_list(self):
        result = validate_patch_operations("bad")
        assert not result.valid

    def test_op_not_a_dict(self):
        result = validate_patch_operations(["bad"])
        assert not result.valid

    def test_too_many_operations(self):
        ops = [{"op": "remove_element", "id": f"e{i}"} for i in range(51)]
        result = validate_patch_operations(ops)
        assert not result.valid
        assert "too many" in result.errors[0]

    def test_add_missing_element(self):
        op = {"op": "add_element", "id": "foo"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_add_unknown_element_type(self):
        op = {
            "op": "add_element",
            "id": "foo",
            "element": {"type": "video"},
        }
        result = validate_patch_operations([op])
        assert not result.valid

    def test_update_missing_changes(self):
        op = {"op": "update_element", "id": "cover_title"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_move_missing_anchor(self):
        op = {"op": "move_element", "id": "cover_title"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_update_style_missing_style(self):
        op = {"op": "update_style", "id": "cover_title"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_update_opacity_missing(self):
        op = {"op": "update_opacity", "id": "x"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_update_slide_scope_missing_slides(self):
        op = {"op": "update_slide_scope", "id": "x"}
        result = validate_patch_operations([op])
        assert not result.valid


# ===========================================================================
# SECTION 4: Element ID validation
# ===========================================================================

class TestElementIdValidation:
    def test_valid_ids(self):
        for eid in ["brand_handle", "a", "custom_text_1", "myElement"]:
            op = {"op": "remove_element", "id": eid}
            result = validate_patch_operations([op])
            assert result.valid, f"id={eid!r} should be valid: {result.errors}"

    def test_invalid_id_starts_with_number(self):
        op = {"op": "remove_element", "id": "1bad"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_invalid_id_special_chars(self):
        op = {"op": "remove_element", "id": "bad-id"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_invalid_id_empty(self):
        op = {"op": "remove_element", "id": ""}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_invalid_id_too_long(self):
        op = {"op": "remove_element", "id": "a" * 65}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_invalid_id_not_string(self):
        op = {"op": "remove_element", "id": 123}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_duplicate_add_warns(self, add_text_op):
        ops = [add_text_op, copy.deepcopy(add_text_op)]
        result = validate_patch_operations(ops)
        assert result.valid  # warnings only
        assert len(result.warnings) >= 1
        assert "duplicate" in result.warnings[0].lower()


# ===========================================================================
# SECTION 5: Anchor validation
# ===========================================================================

class TestAnchorValidation:
    def test_all_valid_anchors(self):
        for anchor in VALID_ANCHORS:
            op = {"op": "move_element", "id": "x", "anchor": anchor}
            result = validate_patch_operations([op])
            assert result.valid, f"anchor={anchor} should be valid"

    def test_invalid_anchor(self):
        op = {"op": "move_element", "id": "x", "anchor": "middle_ish"}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_anchor_none_in_add(self):
        op = {
            "op": "add_element",
            "id": "foo",
            "element": {"type": "text", "text_value": "test"},
        }
        result = validate_patch_operations([op])
        assert result.valid


# ===========================================================================
# SECTION 6: Box dimension validation
# ===========================================================================

class TestBoxValidation:
    def test_valid_box(self):
        op = {
            "op": "move_element",
            "id": "x",
            "anchor": "center",
            "box": {"width": 200, "height": 100, "margin_x": 32, "margin_y": 24},
        }
        result = validate_patch_operations([op])
        assert result.valid

    def test_box_too_large(self):
        op = {
            "op": "move_element",
            "id": "x",
            "anchor": "center",
            "box": {"width": 5000},
        }
        result = validate_patch_operations([op])
        assert not result.valid

    def test_box_negative_dimensions(self):
        op = {
            "op": "move_element",
            "id": "x",
            "anchor": "center",
            "box": {"width": -10},
        }
        result = validate_patch_operations([op])
        assert not result.valid

    def test_box_negative_margin(self):
        op = {
            "op": "move_element",
            "id": "x",
            "anchor": "center",
            "box": {"margin_x": -5},
        }
        result = validate_patch_operations([op])
        assert not result.valid

    def test_box_not_a_dict(self):
        op = {
            "op": "add_element",
            "id": "x",
            "element": {"type": "text", "box": "bad"},
        }
        result = validate_patch_operations([op])
        assert not result.valid


# ===========================================================================
# SECTION 7: Style validation
# ===========================================================================

class TestStyleValidation:
    def test_valid_style(self):
        op = {
            "op": "update_style",
            "id": "x",
            "style": {
                "font_size": 24,
                "font_weight": 700,
                "color": "#ff0000",
                "opacity": 0.5,
            },
        }
        result = validate_patch_operations([op])
        assert result.valid

    def test_font_size_too_small(self):
        op = {"op": "update_style", "id": "x", "style": {"font_size": 2}}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_font_size_too_large(self):
        op = {"op": "update_style", "id": "x", "style": {"font_size": 300}}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_font_weight_invalid(self):
        op = {"op": "update_style", "id": "x", "style": {"font_weight": 1000}}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_opacity_out_of_range(self):
        op = {"op": "update_style", "id": "x", "style": {"opacity": 1.5}}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_opacity_negative(self):
        op = {"op": "update_style", "id": "x", "style": {"opacity": -0.1}}
        result = validate_patch_operations([op])
        assert not result.valid

    def test_style_not_a_dict(self):
        op = {"op": "update_style", "id": "x", "style": "bold"}
        result = validate_patch_operations([op])
        assert not result.valid


# ===========================================================================
# SECTION 8: Target slides validation
# ===========================================================================

class TestTargetSlidesValidation:
    def test_valid_slides(self):
        op = {
            "op": "remove_element",
            "id": "x",
            "target_slides": ["cover", "cta"],
        }
        result = validate_patch_operations([op])
        assert result.valid

    def test_invalid_slide_type(self):
        op = {
            "op": "remove_element",
            "id": "x",
            "target_slides": ["cover", "nonexistent"],
        }
        result = validate_patch_operations([op])
        assert not result.valid

    def test_target_slides_not_list(self):
        op = {
            "op": "remove_element",
            "id": "x",
            "target_slides": "cover",
        }
        result = validate_patch_operations([op])
        assert not result.valid


# ===========================================================================
# SECTION 9: Text value validation
# ===========================================================================

class TestTextValueValidation:
    def test_text_too_long(self):
        op = {
            "op": "add_element",
            "id": "x",
            "element": {"type": "text", "text_value": "a" * 501},
        }
        result = validate_patch_operations([op])
        assert not result.valid

    def test_text_value_not_string(self):
        op = {
            "op": "add_element",
            "id": "x",
            "element": {"type": "text", "text_value": 123},
        }
        result = validate_patch_operations([op])
        assert not result.valid


# ===========================================================================
# SECTION 10: Patch application — add_element
# ===========================================================================

class TestApplyAddElement:
    def test_add_creates_overlay(self, base_spec, add_text_op):
        result = apply_patch_operations(base_spec, [add_text_op])
        overlays = result.get("element_overlays", [])
        assert len(overlays) == 1
        assert overlays[0]["id"] == "brand_handle"
        assert overlays[0]["op"] == "add"
        assert overlays[0]["type"] == "text"
        assert overlays[0]["text_value"] == "@Juan"
        assert overlays[0]["anchor"] == "bottom_right"

    def test_add_replaces_existing(self, base_spec, add_text_op):
        # Apply twice — should replace, not duplicate
        spec = apply_patch_operations(base_spec, [add_text_op])
        modified = copy.deepcopy(add_text_op)
        modified["element"]["text_value"] = "@NewHandle"
        spec = apply_patch_operations(spec, [modified])
        overlays = spec["element_overlays"]
        assert len(overlays) == 1
        assert overlays[0]["text_value"] == "@NewHandle"

    def test_add_does_not_mutate_input(self, base_spec, add_text_op):
        original = copy.deepcopy(base_spec)
        apply_patch_operations(base_spec, [add_text_op])
        assert base_spec == original

    def test_add_preserves_existing_spec(self, base_spec, add_text_op):
        result = apply_patch_operations(base_spec, [add_text_op])
        assert result["colors"] == base_spec["colors"]
        assert result["images"] == base_spec["images"]


# ===========================================================================
# SECTION 11: Patch application — update_element
# ===========================================================================

class TestApplyUpdateElement:
    def test_update_existing_overlay(self, base_spec, add_text_op):
        spec = apply_patch_operations(base_spec, [add_text_op])
        update_op = {
            "op": "update_element",
            "id": "brand_handle",
            "changes": {"text_value": "@NewName", "style": {"font_size": 24}},
        }
        spec = apply_patch_operations(spec, [update_op])
        ov = spec["element_overlays"][0]
        assert ov["text_value"] == "@NewName"
        assert ov["style"]["font_size"] == 24
        # Original font_weight should be preserved
        assert ov["style"]["font_weight"] == 600

    def test_update_builtin_creates_directive(self, base_spec):
        op = {
            "op": "update_element",
            "id": "cover_title",
            "changes": {"style": {"font_size": 48}},
        }
        spec = apply_patch_operations(base_spec, [op])
        overlays = spec["element_overlays"]
        assert len(overlays) == 1
        assert overlays[0]["id"] == "cover_title"
        assert overlays[0]["op"] == "update"


# ===========================================================================
# SECTION 12: Patch application — remove_element
# ===========================================================================

class TestApplyRemoveElement:
    def test_remove_creates_directive(self, base_spec):
        op = {"op": "remove_element", "id": "cover_accent_line"}
        spec = apply_patch_operations(base_spec, [op])
        overlays = spec["element_overlays"]
        assert len(overlays) == 1
        assert overlays[0]["op"] == "remove"
        assert overlays[0]["id"] == "cover_accent_line"

    def test_remove_replaces_add(self, base_spec, add_text_op):
        spec = apply_patch_operations(base_spec, [add_text_op])
        remove_op = {"op": "remove_element", "id": "brand_handle"}
        spec = apply_patch_operations(spec, [remove_op])
        overlays = spec["element_overlays"]
        assert len(overlays) == 1
        assert overlays[0]["op"] == "remove"


# ===========================================================================
# SECTION 13: Patch application — move_element
# ===========================================================================

class TestApplyMoveElement:
    def test_move_existing_overlay(self, base_spec, add_text_op):
        spec = apply_patch_operations(base_spec, [add_text_op])
        move_op = {
            "op": "move_element",
            "id": "brand_handle",
            "anchor": "top_left",
            "box": {"width": 200, "height": 50, "margin_x": 40, "margin_y": 40},
        }
        spec = apply_patch_operations(spec, [move_op])
        ov = spec["element_overlays"][0]
        assert ov["anchor"] == "top_left"
        assert ov["box"]["width"] == 200

    def test_move_builtin(self, base_spec, move_op):
        spec = apply_patch_operations(base_spec, [move_op])
        overlays = spec["element_overlays"]
        assert len(overlays) == 1
        assert overlays[0]["anchor"] == "top_center"


# ===========================================================================
# SECTION 14: Patch application — update_style / opacity / scope
# ===========================================================================

class TestApplyStyleOps:
    def test_update_style_existing(self, base_spec, add_text_op):
        spec = apply_patch_operations(base_spec, [add_text_op])
        style_op = {
            "op": "update_style",
            "id": "brand_handle",
            "style": {"color": "#ff0000"},
        }
        spec = apply_patch_operations(spec, [style_op])
        ov = spec["element_overlays"][0]
        assert ov["style"]["color"] == "#ff0000"
        assert ov["style"]["font_weight"] == 600  # preserved

    def test_update_opacity(self, base_spec, add_text_op):
        spec = apply_patch_operations(base_spec, [add_text_op])
        op = {"op": "update_opacity", "id": "brand_handle", "opacity": 0.5}
        spec = apply_patch_operations(spec, [op])
        ov = spec["element_overlays"][0]
        assert ov["style"]["opacity"] == 0.5

    def test_update_slide_scope(self, base_spec, add_text_op):
        spec = apply_patch_operations(base_spec, [add_text_op])
        op = {
            "op": "update_slide_scope",
            "id": "brand_handle",
            "target_slides": ["cover", "cta"],
        }
        spec = apply_patch_operations(spec, [op])
        ov = spec["element_overlays"][0]
        assert ov["target_slides"] == ["cover", "cta"]


# ===========================================================================
# SECTION 15: Position resolution
# ===========================================================================

class TestResolveOverlayPosition:
    def test_top_left(self):
        pos = resolve_overlay_position("top_left", {"width": 100, "height": 50, "margin_x": 20, "margin_y": 10})
        assert pos["top"] == "10px"
        assert pos["left"] == "20px"

    def test_bottom_right(self):
        pos = resolve_overlay_position("bottom_right", {"width": 100, "height": 50, "margin_x": 32, "margin_y": 24})
        assert pos["bottom"] == "24px"
        assert pos["right"] == "32px"

    def test_center(self):
        pos = resolve_overlay_position("center", None)
        assert "50%" in pos["top"]
        assert "50%" in pos["left"]
        assert "translate" in pos.get("transform", "")

    def test_full_bg(self):
        pos = resolve_overlay_position("full_bg", None)
        assert pos["width"] == "100%"
        assert pos["height"] == "100%"

    def test_default_box_values(self):
        pos = resolve_overlay_position("top_left", None)
        assert pos["width"] == "200px"  # default
        assert pos["height"] == "40px"  # default


# ===========================================================================
# SECTION 16: HTML overlay rendering
# ===========================================================================

class TestRenderOverlayHtml:
    def test_added_text_element(self, base_spec):
        overlay = {
            "id": "handle",
            "op": "add",
            "type": "text",
            "text_value": "@Juan",
            "anchor": "bottom_right",
            "box": {"width": 180, "height": 40, "margin_x": 32, "margin_y": 24},
            "style": {"font_size": 18},
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "@Juan" in html
        assert "overlay-handle" in html
        assert "bottom" in html
        assert "right" in html
        assert "font-size:18px" in html

    def test_added_image_element(self, base_spec):
        overlay = {
            "id": "watermark",
            "op": "add",
            "type": "image",
            "asset_url": "https://example.com/wm.png",
            "anchor": "top_right",
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "img" in html
        assert "https://example.com/wm.png" in html

    def test_skip_wrong_slide(self, base_spec):
        overlay = {
            "id": "x",
            "op": "add",
            "type": "text",
            "text_value": "test",
            "anchor": "center",
            "target_slides": ["cover"],
        }
        html = render_overlay_html(overlay, "content", base_spec)
        assert html == ""

    def test_remove_generates_css(self, base_spec):
        overlay = {
            "id": "cover_accent_line",
            "op": "remove",
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "display: none" in html
        assert "accent-line" in html

    def test_builtin_style_override(self, base_spec):
        overlay = {
            "id": "cover_title",
            "op": "update_style",
            "style": {"font_size": 48, "color": "#ff0000"},
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "font-size: 48px" in html
        assert "#ff0000" in html

    def test_builtin_move_override(self, base_spec):
        overlay = {
            "id": "cover_title",
            "op": "move",
            "anchor": "top_center",
            "box": {"width": 920, "height": 200, "margin_x": 80, "margin_y": 120},
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "position: absolute" in html


# ===========================================================================
# SECTION 17: render_all_overlays
# ===========================================================================

class TestRenderAllOverlays:
    def test_empty_overlays(self, base_spec):
        assert render_all_overlays(base_spec, "cover") == ""

    def test_multiple_overlays(self, base_spec):
        base_spec["element_overlays"] = [
            {
                "id": "handle",
                "op": "add",
                "type": "text",
                "text_value": "@Juan",
                "anchor": "bottom_right",
                "target_slides": None,
            },
            {
                "id": "cover_accent_line",
                "op": "remove",
                "target_slides": None,
            },
        ]
        html = render_all_overlays(base_spec, "cover")
        assert "@Juan" in html
        assert "display: none" in html

    def test_filters_by_slide_type(self, base_spec):
        base_spec["element_overlays"] = [
            {
                "id": "handle",
                "op": "add",
                "type": "text",
                "text_value": "@Juan",
                "anchor": "center",
                "target_slides": ["cover"],
            },
        ]
        assert "@Juan" in render_all_overlays(base_spec, "cover")
        assert render_all_overlays(base_spec, "content") == ""


# ===========================================================================
# SECTION 18: LLM prompt builder
# ===========================================================================

class TestBuildLayoutEditPrompt:
    def test_includes_user_message(self, base_spec):
        prompt = build_layout_edit_prompt("aggiungi @Juan", base_spec)
        assert "aggiungi @Juan" in prompt

    def test_includes_context(self, base_spec):
        prompt = build_layout_edit_prompt("test", base_spec)
        assert "has_logo" in prompt

    def test_includes_existing_overlays(self, base_spec):
        overlays = [{"id": "existing", "op": "add"}]
        prompt = build_layout_edit_prompt("test", base_spec, overlays)
        assert "existing" in prompt

    def test_system_prompt_has_examples(self):
        assert "add_element" in LAYOUT_EDIT_SYSTEM_PROMPT
        assert "move_element" in LAYOUT_EDIT_SYSTEM_PROMPT
        assert "@Juan" in LAYOUT_EDIT_SYSTEM_PROMPT


# ===========================================================================
# SECTION 19: Mode detection for LAYOUT_EDIT
# ===========================================================================

class TestLayoutEditModeDetection:
    """Test that layout-edit requests are correctly classified."""

    def test_add_handle(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("aggiungi @Juan in basso a destra in tutte le slide")
        assert mode == CommandMode.LAYOUT_EDIT

    def test_move_title(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("sposta il titolo più in alto")
        assert mode == CommandMode.LAYOUT_EDIT

    def test_hide_element(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("nascondi il contatore delle slide")
        assert mode == CommandMode.LAYOUT_EDIT

    def test_opacity_request(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("riduci l'opacità dello sfondo")
        assert mode == CommandMode.LAYOUT_EDIT

    def test_under_title(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("metti l'immagine sotto il titolo nella cover")
        assert mode == CommandMode.LAYOUT_EDIT

    def test_element_positioning_layout(self):
        from services.personalizza_commands import detect_mode, CommandMode
        # Adding non-asset text with position → LAYOUT_EDIT
        mode, _, _ = detect_mode("inserisci un separatore sotto il titolo nella cover")
        assert mode == CommandMode.LAYOUT_EDIT

    def test_logo_assignment_stays_asset(self):
        from services.personalizza_commands import detect_mode, CommandMode
        # "usa il logo su tutte le slide" triggers asset keywords (usa + logo)
        mode, _, _ = detect_mode("usa il logo su tutte le slide")
        assert mode == CommandMode.ASSET

    def test_design_mode_still_works(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("cambia il font in Poppins")
        assert mode == CommandMode.DESIGN

    def test_design_mode_with_sfondo_color(self):
        from services.personalizza_commands import detect_mode, CommandMode
        # "colore di sfondo" has competing signals but design dominates
        mode, _, _ = detect_mode("cambia il font in Poppins e il colore di sfondo in nero")
        assert mode in (CommandMode.DESIGN, CommandMode.MIXED)

    def test_asset_mode_still_works(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("genera un'immagine di una cucina moderna")
        assert mode == CommandMode.ASSET

    def test_content_mode(self):
        from services.personalizza_commands import detect_mode, CommandMode
        mode, _, _ = detect_mode("cambia il titolo in 'Nuovo Titolo'")
        assert mode == CommandMode.CONTENT


# ===========================================================================
# SECTION 20: Constants completeness
# ===========================================================================

class TestConstants:
    def test_all_patch_ops_have_validators(self):
        from services.layout_patch import _OP_VALIDATORS
        for op in PATCH_OPS:
            assert op in _OP_VALIDATORS, f"Missing validator for op: {op}"

    def test_element_types_are_frozen(self):
        assert isinstance(ELEMENT_TYPES, frozenset)

    def test_valid_anchors_match_renderer(self):
        from services.renderer_validators import VALID_ANCHORS as RV_ANCHORS
        assert VALID_ANCHORS == RV_ANCHORS

    def test_builtin_ids_cover_all_slides(self):
        for slide in ["cover", "content", "list", "cta"]:
            found = [eid for eid in BUILTIN_ELEMENT_IDS if eid.startswith(slide)]
            assert len(found) >= 2, f"Expected at least 2 builtin IDs for {slide}"

    def test_all_builtin_ids_have_css_selectors(self):
        from services.layout_patch import _BUILTIN_CSS_SELECTORS
        for eid in BUILTIN_ELEMENT_IDS:
            assert eid in _BUILTIN_CSS_SELECTORS, f"Missing CSS selector for: {eid}"


# ===========================================================================
# SECTION 21: HTML escaping
# ===========================================================================

class TestHtmlEscaping:
    def test_escapes_xss_in_text_value(self, base_spec):
        overlay = {
            "id": "xss_test",
            "op": "add",
            "type": "text",
            "text_value": "<script>alert('xss')</script>",
            "anchor": "center",
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_escapes_xss_in_id(self, base_spec):
        overlay = {
            "id": "test",
            "op": "add",
            "type": "text",
            "text_value": "safe",
            "anchor": "center",
            "target_slides": None,
        }
        html = render_overlay_html(overlay, "cover", base_spec)
        assert "overlay-test" in html


# ===========================================================================
# SECTION 22: Integration — full patch cycle
# ===========================================================================

class TestIntegrationPatchCycle:
    def test_add_then_move_then_update_style(self, base_spec):
        """Full lifecycle: add → move → style update → verify."""
        ops1 = [{
            "op": "add_element",
            "id": "social_handle",
            "element": {
                "type": "text",
                "text_value": "@brand",
                "anchor": "bottom_right",
                "box": {"width": 180, "height": 40},
                "style": {"font_size": 16},
            },
        }]
        spec = apply_patch_operations(base_spec, ops1)

        ops2 = [{
            "op": "move_element",
            "id": "social_handle",
            "anchor": "bottom_left",
            "box": {"width": 200, "height": 50},
        }]
        spec = apply_patch_operations(spec, ops2)
        assert spec["element_overlays"][0]["anchor"] == "bottom_left"

        ops3 = [{
            "op": "update_style",
            "id": "social_handle",
            "style": {"color": "#00ff00"},
        }]
        spec = apply_patch_operations(spec, ops3)
        ov = spec["element_overlays"][0]
        assert ov["style"]["color"] == "#00ff00"
        assert ov["style"]["font_size"] == 16  # preserved

        # Render should include overlay
        html = render_all_overlays(spec, "cover")
        assert "@brand" in html
        assert "#00ff00" in html

    def test_add_to_specific_slides_then_remove(self, base_spec):
        ops1 = [{
            "op": "add_element",
            "id": "watermark",
            "target_slides": ["cover", "cta"],
            "element": {
                "type": "text",
                "text_value": "DRAFT",
                "anchor": "center",
                "style": {"font_size": 72, "opacity": 0.2},
            },
        }]
        spec = apply_patch_operations(base_spec, ops1)

        # Should appear on cover and cta
        assert "DRAFT" in render_all_overlays(spec, "cover")
        assert "DRAFT" in render_all_overlays(spec, "cta")
        assert render_all_overlays(spec, "content") == ""

        # Remove it
        ops2 = [{"op": "remove_element", "id": "watermark"}]
        spec = apply_patch_operations(spec, ops2)
        # Now it's a remove directive — no text rendered
        html = render_all_overlays(spec, "cover")
        assert "DRAFT" not in html
