"""Semantic asset command interpreter — natural-language → structured overrides.

Translates user instructions like:
- "metti il logo in alto a sinistra"
- "metti il prodotto al centro"
- "usa questa immagine come sfondo"
- "usa il logo solo nella cover"
- "metti il prodotto nella CTA"

into structured asset_mapping + placement_overrides dicts.

MVP strategy: deterministic keyword matching (no LLM needed).
Covers Italian + English commands with simple regex patterns.

Usage::

    from services.asset_command_interpreter import interpret_asset_commands

    result = interpret_asset_commands(
        commands=["metti il logo in alto a sinistra", "metti il prodotto al centro"],
        available_assets={"asset_001": {"type": "logo"}, "asset_002": {"type": "product"}},
    )
    # {
    #     "asset_mapping": {"logo_asset": "asset_001", "product_asset": "asset_002"},
    #     "placement_overrides": {
    #         "logo_asset": {"anchor": "top_left"},
    #         "product_asset": {"anchor": "center"}
    #     }
    # }
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position keyword mappings (Italian + English)
# ---------------------------------------------------------------------------

_POSITION_PATTERNS: list[tuple[str, str]] = [
    # Italian
    (r"in alto a sinistra", "top_left"),
    (r"in alto a destra", "top_right"),
    (r"in alto al centro|in alto", "top_center"),
    (r"in basso a sinistra", "bottom_left"),
    (r"in basso a destra", "bottom_right"),
    (r"in basso al centro|in basso", "bottom_center"),
    (r"al centro a sinistra|a sinistra", "center_left"),
    (r"al centro a destra|a destra", "center_right"),
    (r"al centro|centro", "center"),
    (r"come sfondo|sfondo|background", "full_bg"),
    # English
    (r"top.?left", "top_left"),
    (r"top.?right", "top_right"),
    (r"top.?center|at the top", "top_center"),
    (r"bottom.?left", "bottom_left"),
    (r"bottom.?right", "bottom_right"),
    (r"bottom.?center|at the bottom", "bottom_center"),
    (r"center.?left|on the left", "center_left"),
    (r"center.?right|on the right", "center_right"),
    (r"in the center|centered|at center", "center"),
    (r"as background|full background", "full_bg"),
]

# Asset type keyword detection (Italian + English)
_ASSET_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"\blogo\b", "logo"),
    (r"\bprodotto\b|\bproduct\b", "product"),
    (r"\bfoto\b|\bphoto\b|\bimmagine\b|\bimage\b", "photo"),
    (r"\btexture\b|\btrama\b|\bsfondo\b", "texture"),
]

# Slide targeting keywords
_SLIDE_PATTERNS: list[tuple[str, str]] = [
    (r"\bcover\b|\bcopertina\b", "cover"),
    (r"\bcta\b|\bcall.?to.?action\b", "cta"),
    (r"\btext\b|\btesto\b", "text"),
    (r"\blist\b|\blista\b|\belenco\b", "list"),
    (r"\btutt[eio]\b|\ball\b", "__all__"),
]

# "only" / "solo" → restrict to specified slides only
_ONLY_PATTERN = re.compile(r"\bsolo\b|\bonly\b|\bsoltanto\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Default box sizes per asset type
# ---------------------------------------------------------------------------

_DEFAULT_BOXES: dict[str, dict] = {
    "logo": {"width": 160, "height": 80, "margin_x": 40, "margin_y": 40},
    "product": {"width": 480, "height": 480, "margin_x": 40, "margin_y": 40},
    "photo": {"width": 480, "height": 480, "margin_x": 40, "margin_y": 40},
    "texture": {},  # full_bg by default
    "other": {"width": 300, "height": 300, "margin_x": 40, "margin_y": 40},
}

# Map asset type → standard slot name
_TYPE_TO_SLOT: dict[str, str] = {
    "logo": "logo_asset",
    "product": "product_asset",
    "photo": "secondary_asset",
    "texture": "background_asset",
    "other": "secondary_asset",
}


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def _detect_position(text: str) -> str | None:
    """Extract anchor position from text."""
    lower = text.lower()
    for pattern, anchor in _POSITION_PATTERNS:
        if re.search(pattern, lower):
            return anchor
    return None


def _detect_asset_type(text: str) -> str | None:
    """Extract asset type keyword from text."""
    lower = text.lower()
    for pattern, atype in _ASSET_TYPE_PATTERNS:
        if re.search(pattern, lower):
            return atype
    return None


def _detect_slides(text: str) -> list[str] | None:
    """Extract target slide names from text."""
    lower = text.lower()
    has_only = bool(_ONLY_PATTERN.search(lower))
    slides = []

    for pattern, slide_name in _SLIDE_PATTERNS:
        if re.search(pattern, lower):
            if slide_name == "__all__":
                return None  # all slides = no restriction
            slides.append(slide_name)

    if slides:
        return slides
    if has_only:
        # "solo" without a specific slide → keep as is (no filter)
        return None
    return None


def _find_asset_for_type(
    asset_type: str,
    available_assets: dict[str, dict],
    already_used: set[str],
) -> str | None:
    """Find the first available asset matching the requested type."""
    # Exact type match
    for aid, meta in available_assets.items():
        if aid in already_used:
            continue
        if meta.get("type") == asset_type:
            return aid

    # Fallback: any unused asset
    for aid in available_assets:
        if aid not in already_used:
            return aid

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def interpret_asset_commands(
    commands: list[str],
    available_assets: dict[str, dict],
) -> dict:
    """Interpret natural-language asset commands into structured overrides.

    Args:
        commands: List of user instructions (Italian or English).
        available_assets: Dict of asset_id → metadata (must include "type").

    Returns::

        {
            "asset_mapping": {
                "logo_asset": "asset_001",
                "product_asset": "asset_002"
            },
            "placement_overrides": {
                "logo_asset": {
                    "anchor": "top_left",
                    "box": {"width": 160, "height": 80, ...},
                    "slides": ["cover"]
                }
            }
        }
    """
    asset_mapping: dict[str, str] = {}
    placement_overrides: dict[str, dict] = {}
    used_assets: set[str] = set()

    for cmd in commands:
        if not cmd or not cmd.strip():
            continue

        asset_type = _detect_asset_type(cmd)
        position = _detect_position(cmd)
        target_slides = _detect_slides(cmd)

        if not asset_type:
            log.info("[interpreter] no asset type detected in: %s", cmd[:80])
            continue

        # Find matching asset
        asset_id = _find_asset_for_type(asset_type, available_assets, used_assets)
        if not asset_id:
            log.warning("[interpreter] no asset available for type '%s'", asset_type)
            continue

        used_assets.add(asset_id)
        slot_name = _TYPE_TO_SLOT.get(asset_type, "secondary_asset")

        # If slot already used, make it unique
        if slot_name in asset_mapping:
            slot_name = f"{slot_name}_{len(asset_mapping)}"

        asset_mapping[slot_name] = asset_id

        # Build placement override
        override: dict = {}
        if position:
            override["anchor"] = position
        else:
            # Default position based on type
            if asset_type == "logo":
                override["anchor"] = "top_left"
            elif asset_type == "texture":
                override["anchor"] = "full_bg"
            else:
                override["anchor"] = "center"

        # Apply default box size for the type
        default_box = _DEFAULT_BOXES.get(asset_type, {})
        if default_box and override.get("anchor") != "full_bg":
            override["box"] = dict(default_box)

        if target_slides:
            override["slides"] = target_slides

        placement_overrides[slot_name] = override
        log.info(
            "[interpreter] %s → slot=%s anchor=%s slides=%s",
            cmd[:60], slot_name, override.get("anchor"), target_slides,
        )

    return {
        "asset_mapping": asset_mapping,
        "placement_overrides": placement_overrides,
    }
