"""Tests for Personalizza command layer.

Covers:
- Mode detection (ASSET vs DESIGN vs MIXED)
- Slot detection from natural language
- Position/anchor detection
- Slide targeting
- Generation intent extraction
- Removal commands
- Assignment commands
- Placement override generation
- Logo slot constraints
- Command execution (unit-level, no I/O)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.personalizza_commands import (
    CommandMode,
    ParseResult,
    detect_mode,
    parse_message,
    execute_asset_commands,
    _detect_position,
    _detect_slot,
    _detect_slides,
    _has_generation_intent,
    _has_removal_intent,
    _has_assignment_intent,
    _extract_generation_subject,
    _set_image_url,
    SLOT_TYPES,
    SLOT_DEFAULT_BOXES,
    SLOT_DEFAULT_ANCHORS,
)


# =======================================================================
# Mode detection
# =======================================================================

class TestModeDetection:
    def test_logo_placement_is_asset_mode(self):
        mode, a, d = detect_mode("metti il logo in alto a sinistra")
        assert mode == CommandMode.ASSET
        assert a > 0
        assert d == 0

    def test_background_image_is_asset_mode(self):
        mode, a, d = detect_mode("usa questa immagine come sfondo")
        assert mode == CommandMode.ASSET

    def test_kitchen_background_is_asset_mode(self):
        mode, a, d = detect_mode("metti una cucina moderna come sfondo")
        assert mode == CommandMode.ASSET

    def test_logo_on_all_slides_is_asset_mode(self):
        mode, a, d = detect_mode("usa il logo su tutte le slide")
        assert mode == CommandMode.ASSET

    def test_remove_logo_is_asset_mode(self):
        mode, a, d = detect_mode("non usare il logo come immagine di copertina")
        assert mode == CommandMode.ASSET

    def test_generate_image_is_asset_mode(self):
        mode, a, d = detect_mode("genera un'immagine di marmo scuro")
        assert mode == CommandMode.ASSET

    def test_change_font_is_design_mode(self):
        mode, a, d = detect_mode("cambia font a Montserrat")
        assert mode == CommandMode.DESIGN
        assert d > 0

    def test_more_minimal_is_design_mode(self):
        mode, a, d = detect_mode("rendilo più minimal")
        assert mode == CommandMode.DESIGN

    def test_change_theme_is_design_mode(self):
        mode, a, d = detect_mode("cambia tema")
        assert mode == CommandMode.DESIGN

    def test_luxury_colors_is_design_mode(self):
        mode, a, d = detect_mode("usa colori più luxury")
        assert mode == CommandMode.DESIGN

    def test_bold_layout_is_design_mode(self):
        mode, a, d = detect_mode("fammi un layout più bold")
        assert mode == CommandMode.DESIGN

    def test_mixed_message(self):
        mode, a, d = detect_mode("metti il logo in alto a sinistra e cambia il font a Montserrat")
        assert mode in (CommandMode.MIXED, CommandMode.ASSET)
        assert a > 0
        assert d > 0

    def test_vague_message_defaults_to_design(self):
        mode, a, d = detect_mode("fammi qualcosa di bello")
        assert mode == CommandMode.DESIGN

    def test_english_asset_mode(self):
        mode, a, d = detect_mode("put the logo on the top left")
        assert mode == CommandMode.ASSET

    def test_english_design_mode(self):
        mode, a, d = detect_mode("make it darker and more elegant")
        assert mode == CommandMode.DESIGN


# =======================================================================
# Position detection
# =======================================================================

class TestPositionDetection:
    def test_italian_top_left(self):
        assert _detect_position("metti in alto a sinistra") == "top_left"

    def test_italian_top_right(self):
        assert _detect_position("metti in alto a destra") == "top_right"

    def test_italian_bottom_center(self):
        assert _detect_position("metti in basso al centro") == "bottom_center"

    def test_italian_center(self):
        assert _detect_position("metti al centro") == "center"

    def test_italian_background(self):
        assert _detect_position("usa come sfondo") == "full_bg"

    def test_english_top_left(self):
        assert _detect_position("put it top-left") == "top_left"

    def test_english_center(self):
        assert _detect_position("place it in the center") == "center"

    def test_english_background(self):
        assert _detect_position("use as background") == "full_bg"

    def test_no_position(self):
        assert _detect_position("fai qualcosa") is None


# =======================================================================
# Slot detection
# =======================================================================

class TestSlotDetection:
    def test_logo(self):
        assert _detect_slot("metti il logo") == "logo_asset"

    def test_product(self):
        assert _detect_slot("aggiungi il prodotto") == "product_asset"

    def test_background(self):
        assert _detect_slot("cambia lo sfondo") == "background_asset"

    def test_photo(self):
        assert _detect_slot("metti questa foto") == "secondary_asset"

    def test_image(self):
        assert _detect_slot("usa questa immagine") == "secondary_asset"

    def test_texture(self):
        assert _detect_slot("aggiungi una texture") == "background_asset"

    def test_no_slot(self):
        assert _detect_slot("fai qualcosa di bello") is None


# =======================================================================
# Slide targeting
# =======================================================================

class TestSlideDetection:
    def test_cover(self):
        assert _detect_slides("solo nella cover") == ["cover"]

    def test_cta(self):
        assert _detect_slides("metti nella CTA") == ["cta"]

    def test_all_slides(self):
        assert _detect_slides("su tutte le slide") is None  # None = all

    def test_multiple_slides(self):
        slides = _detect_slides("metti nella cover e nella CTA")
        assert "cover" in slides
        assert "cta" in slides

    def test_no_targeting(self):
        assert _detect_slides("metti il logo") is None


# =======================================================================
# Intent detection
# =======================================================================

class TestIntentDetection:
    def test_generation_genera(self):
        assert _has_generation_intent("genera un'immagine di cucina")

    def test_generation_crea(self):
        assert _has_generation_intent("crea un'immagine di marmo")

    def test_generation_subject(self):
        assert _has_generation_intent("metti una cucina moderna come sfondo")

    def test_no_generation(self):
        assert not _has_generation_intent("metti il logo in alto")

    def test_removal_rimuovi(self):
        assert _has_removal_intent("rimuovi lo sfondo")

    def test_removal_non_usare(self):
        assert _has_removal_intent("non usare il logo")

    def test_removal_togli(self):
        assert _has_removal_intent("togli l'immagine")

    def test_no_removal(self):
        assert not _has_removal_intent("metti il logo")

    def test_assignment_usa_questa(self):
        assert _has_assignment_intent("usa questa immagine come logo")

    def test_assignment_come_logo(self):
        assert _has_assignment_intent("come logo")

    def test_no_assignment(self):
        assert not _has_assignment_intent("genera un'immagine")


# =======================================================================
# Subject extraction
# =======================================================================

class TestSubjectExtraction:
    def test_kitchen(self):
        subject = _extract_generation_subject("metti una cucina moderna come sfondo")
        assert "cucina" in subject.lower() or "moderna" in subject.lower()

    def test_marble(self):
        subject = _extract_generation_subject("genera un'immagine di marmo scuro")
        assert "marmo" in subject.lower() or "scuro" in subject.lower()


# =======================================================================
# Full message parsing
# =======================================================================

class TestMessageParsing:
    def test_logo_top_left(self):
        result = parse_message(
            "metti il logo in alto a sinistra",
            uploaded_image_urls=["https://example.com/logo.png"],
        )
        assert result.mode == CommandMode.ASSET
        assert len(result.commands) >= 1

        # Should have assignment + placement
        types = [c["type"] for c in result.commands]
        assert "assign_uploaded_asset" in types or "placement_override" in types

        # Check placement
        placement = [c for c in result.commands if c["type"] == "placement_override"]
        if placement:
            assert placement[0]["slot"] == "logo_asset"
            assert placement[0]["anchor"] == "top_left"

    def test_generate_kitchen_background(self):
        result = parse_message(
            "metti una cucina moderna come sfondo",
        )
        assert result.mode == CommandMode.ASSET

        gen_cmds = [c for c in result.commands if c["type"] == "generate_asset"]
        assert len(gen_cmds) == 1
        assert gen_cmds[0]["slot"] == "background_asset"

    def test_remove_logo(self):
        result = parse_message("rimuovi il logo")
        assert result.mode == CommandMode.ASSET

        remove_cmds = [c for c in result.commands if c["type"] == "remove_asset"]
        assert len(remove_cmds) == 1
        assert remove_cmds[0]["slot"] == "logo_asset"

    def test_assign_uploaded_background(self):
        result = parse_message(
            "usa questa immagine come sfondo",
            uploaded_image_urls=["https://example.com/bg.jpg"],
        )
        assert result.mode == CommandMode.ASSET

        assign_cmds = [c for c in result.commands if c["type"] == "assign_uploaded_asset"]
        assert len(assign_cmds) == 1
        assert assign_cmds[0]["slot"] == "background_asset"
        assert assign_cmds[0]["url"] == "https://example.com/bg.jpg"

    def test_design_mode_no_commands(self):
        result = parse_message("cambia il font a Montserrat")
        assert result.mode == CommandMode.DESIGN
        assert len(result.commands) == 0

    def test_logo_all_slides(self):
        result = parse_message(
            "usa il logo su tutte le slide",
            uploaded_image_urls=["https://example.com/logo.png"],
        )
        assert result.mode == CommandMode.ASSET

        # Placement override should NOT have slides restriction (all slides)
        placement = [c for c in result.commands if c["type"] == "placement_override"]
        if placement:
            assert placement[0].get("slides") is None

    def test_logo_only_cover(self):
        result = parse_message(
            "metti il logo solo nella cover",
            uploaded_image_urls=["https://example.com/logo.png"],
        )
        assert result.mode == CommandMode.ASSET

        placement = [c for c in result.commands if c["type"] == "placement_override"]
        if placement:
            assert placement[0]["slides"] == ["cover"]


# =======================================================================
# Slot constraints
# =======================================================================

class TestSlotConstraints:
    def test_logo_has_max_dimensions(self):
        constraints = SLOT_TYPES["logo_asset"]
        assert constraints["max_width"] is not None
        assert constraints["max_height"] is not None
        assert constraints["max_width"] <= 200
        assert constraints["max_height"] <= 200
        assert constraints["preserve_ratio"] is True

    def test_background_has_no_max(self):
        constraints = SLOT_TYPES["background_asset"]
        assert constraints["max_width"] is None
        assert constraints["max_height"] is None
        assert constraints["preserve_ratio"] is False

    def test_logo_default_box_reasonable(self):
        box = SLOT_DEFAULT_BOXES["logo_asset"]
        assert box["width"] <= 200
        assert box["height"] <= 200
        assert box["margin_x"] > 0
        assert box["margin_y"] > 0

    def test_logo_default_anchor_is_top_left(self):
        assert SLOT_DEFAULT_ANCHORS["logo_asset"] == "top_left"

    def test_background_default_anchor_is_full_bg(self):
        assert SLOT_DEFAULT_ANCHORS["background_asset"] == "full_bg"


# =======================================================================
# _set_image_url mapping
# =======================================================================

class TestSetImageUrl:
    def test_background_slot(self):
        spec = {"images": {"background_image_url": "", "slide_images": {}}}
        _set_image_url(spec, "background_asset", "https://bg.png")
        assert spec["images"]["background_image_url"] == "https://bg.png"

    def test_logo_slot(self):
        spec = {"images": {"logo_url": "", "slide_images": {}}}
        _set_image_url(spec, "logo_asset", "https://logo.png")
        assert spec["images"]["logo_url"] == "https://logo.png"

    def test_product_slot(self):
        spec = {"images": {"slide_images": {}}}
        _set_image_url(spec, "product_asset", "https://product.png")
        assert spec["images"]["slide_images"]["cover"] == "https://product.png"

    def test_remove_clears_url(self):
        spec = {"images": {"logo_url": "https://old.png", "slide_images": {}}}
        _set_image_url(spec, "logo_asset", "")
        assert spec["images"]["logo_url"] == ""


# =======================================================================
# Command execution (no I/O — only assign/remove)
# =======================================================================

class TestCommandExecution:
    def _base_spec(self):
        return {
            "theme_name": "Test",
            "colors": {"background": "#111111"},
            "typography": {},
            "layout": {},
            "slide_layouts": {},
            "images": {
                "logo_url": "",
                "background_image_url": "",
                "slide_images": {"cover": ""},
            },
        }

    def test_assign_logo(self):
        commands = [{
            "type": "assign_uploaded_asset",
            "slot": "logo_asset",
            "url": "https://example.com/logo.png",
        }]
        result = execute_asset_commands(commands, self._base_spec(), "user1", "tpl1")
        assert result["design_spec"]["images"]["logo_url"] == "https://example.com/logo.png"
        assert len(result["changes"]) == 1
        assert len(result["errors"]) == 0

    def test_assign_background(self):
        commands = [{
            "type": "assign_uploaded_asset",
            "slot": "background_asset",
            "url": "https://example.com/bg.jpg",
        }]
        result = execute_asset_commands(commands, self._base_spec(), "user1", "tpl1")
        assert result["design_spec"]["images"]["background_image_url"] == "https://example.com/bg.jpg"

    def test_remove_logo(self):
        spec = self._base_spec()
        spec["images"]["logo_url"] = "https://example.com/old_logo.png"
        commands = [{"type": "remove_asset", "slot": "logo_asset"}]
        result = execute_asset_commands(commands, spec, "user1", "tpl1")
        assert result["design_spec"]["images"]["logo_url"] == ""
        assert len(result["changes"]) == 1

    def test_multiple_commands(self):
        commands = [
            {"type": "assign_uploaded_asset", "slot": "logo_asset", "url": "https://logo.png"},
            {"type": "assign_uploaded_asset", "slot": "background_asset", "url": "https://bg.jpg"},
        ]
        result = execute_asset_commands(commands, self._base_spec(), "user1", "tpl1")
        assert result["design_spec"]["images"]["logo_url"] == "https://logo.png"
        assert result["design_spec"]["images"]["background_image_url"] == "https://bg.jpg"
        assert len(result["changes"]) == 2

    def test_does_not_mutate_input(self):
        spec = self._base_spec()
        original_logo = spec["images"]["logo_url"]
        commands = [{"type": "assign_uploaded_asset", "slot": "logo_asset", "url": "https://new.png"}]
        execute_asset_commands(commands, spec, "user1", "tpl1")
        assert spec["images"]["logo_url"] == original_logo

    def test_assign_without_url_produces_error(self):
        commands = [{"type": "assign_uploaded_asset", "slot": "logo_asset"}]
        result = execute_asset_commands(commands, self._base_spec(), "user1", "tpl1")
        assert len(result["errors"]) == 1
        assert len(result["changes"]) == 0

    def test_placement_override_logged_as_change(self):
        commands = [{
            "type": "placement_override",
            "slot": "logo_asset",
            "anchor": "top_left",
        }]
        result = execute_asset_commands(commands, self._base_spec(), "user1", "tpl1")
        assert len(result["changes"]) == 1
        assert "logo_asset" in result["changes"][0]


# =======================================================================
# ParseResult dataclass
# =======================================================================

class TestParseResult:
    def test_default_values(self):
        r = ParseResult(mode=CommandMode.DESIGN)
        assert r.commands == []
        assert r.asset_score == 0
        assert r.design_score == 0

    def test_with_commands(self):
        r = ParseResult(
            mode=CommandMode.ASSET,
            commands=[{"type": "generate_asset", "slot": "background_asset"}],
            asset_score=3,
        )
        assert len(r.commands) == 1
        assert r.asset_score == 3
