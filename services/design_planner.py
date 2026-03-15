"""AI Design Planner — two-stage system for stable design decisions.

Stage 1 (LLM): Classify the user prompt into structured categories
    (post_type, tone, visual_style).
Stage 2 (Rules): Map the classification to a concrete design using
    a deterministic rule engine validated against the registry.

Usage::

    from services.design_planner import plan_design

    plan = plan_design("5 strategie per aumentare le vendite online")
    # {
    #     "template": "minimal_layout",
    #     "variant": "split",
    #     "theme": "clean_light",
    #     "asset_roles": {"background_asset": "abstract"},
    #     "classification": {"post_type": "educational", "tone": "professional", "visual_style": "clean"}
    # }
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid classification values
# ---------------------------------------------------------------------------

VALID_POST_TYPES = ["educational", "promotional", "motivational", "luxury", "product_showcase"]
VALID_TONES = ["professional", "playful", "minimal"]
VALID_VISUAL_STYLES = ["clean", "bold", "luxury", "modern"]
VALID_ASSET_ROLE_TYPES = ["texture", "product", "abstract", "architecture", "gradient"]

FALLBACK_CLASSIFICATION = {
    "post_type": "educational",
    "tone": "professional",
    "visual_style": "clean",
}

FALLBACK_PLAN = {
    "template": "minimal_layout",
    "variant": "center",
    "theme": "industrial_dark",
    "asset_roles": {
        "background_asset": "texture",
    },
}

# ---------------------------------------------------------------------------
# Rule engine: classification → design mapping
# ---------------------------------------------------------------------------

# Primary mapping keyed by post_type.  Each entry defines a base design
# that can be refined by tone and visual_style modifiers below.
_POST_TYPE_RULES: dict[str, dict] = {
    "educational": {
        "template": "minimal_layout",
        "variant": "split",
        "theme": "clean_light",
        "asset_roles": {"background_asset": "abstract"},
    },
    "promotional": {
        "template": "bold_layout",
        "variant": "center",
        "theme": "tech_vibrant",
        "asset_roles": {"background_asset": "product"},
    },
    "motivational": {
        "template": "bold_layout",
        "variant": "center",
        "theme": "tech_vibrant",
        "asset_roles": {"background_asset": "gradient"},
    },
    "luxury": {
        "template": "minimal_layout",
        "variant": "center",
        "theme": "luxury_gold",
        "asset_roles": {"background_asset": "texture"},
    },
    "product_showcase": {
        "template": "minimal_layout",
        "variant": "split",
        "theme": "startup_blue",
        "asset_roles": {"background_asset": "product"},
    },
}

# Tone modifiers — override specific fields when tone matches
_TONE_OVERRIDES: dict[str, dict] = {
    "professional": {},  # no change — professional is the default feel
    "playful": {
        "theme": "tech_vibrant",
        "asset_roles": {"background_asset": "abstract"},
    },
    "minimal": {
        "template": "minimal_layout",
        "theme": "industrial_dark",
        "asset_roles": {"background_asset": "texture"},
    },
}

# Visual-style modifiers — applied after tone overrides
_VISUAL_STYLE_OVERRIDES: dict[str, dict] = {
    "clean": {},  # clean is the default — no extra override
    "bold": {
        "template": "bold_layout",
        "variant": "center",
    },
    "luxury": {
        "theme": "luxury_gold",
        "asset_roles": {"background_asset": "texture"},
    },
    "modern": {
        "theme": "startup_blue",
        "asset_roles": {"background_asset": "gradient"},
    },
}


# ---------------------------------------------------------------------------
# Stage 1: Prompt classification (LLM)
# ---------------------------------------------------------------------------

def classify_prompt(prompt: str) -> dict:
    """Classify a user prompt into post_type, tone, and visual_style.

    Uses a constrained LLM call with explicit valid values.
    Falls back to ``FALLBACK_CLASSIFICATION`` on any error.
    """
    from services.carousel_pipeline import _llm_json

    messages = [
        {
            "role": "system",
            "content": (
                "You are a social media content analyst. "
                "Classify the following user prompt into exactly three categories. "
                "Reply ONLY with a JSON object, no extra text.\n\n"
                "Categories and their valid values:\n\n"
                "post_type (what kind of post is this):\n"
                "- educational: teaches something, tips, how-to, strategies\n"
                "- promotional: sells a product/service, discounts, offers\n"
                "- motivational: inspires, quotes, personal growth\n"
                "- luxury: premium brands, high-end lifestyle, elegance\n"
                "- product_showcase: shows a specific product, features, specs\n\n"
                "tone (the communication style):\n"
                "- professional: formal, business, corporate\n"
                "- playful: fun, colorful, casual, energetic\n"
                "- minimal: simple, understated, clean\n\n"
                "visual_style (the desired visual feel):\n"
                "- clean: white space, structured, readable\n"
                "- bold: large type, strong contrasts, impactful\n"
                "- luxury: dark backgrounds, gold/rose accents, elegant\n"
                "- modern: gradients, blue tones, tech-forward\n\n"
                "Reply format:\n"
                "{\n"
                '  "post_type": "<value>",\n'
                '  "tone": "<value>",\n'
                '  "visual_style": "<value>"\n'
                "}"
            ),
        },
        {
            "role": "user",
            "content": f"Classify this prompt: {prompt}",
        },
    ]

    try:
        result = _llm_json(messages)
    except Exception as exc:
        log.warning("[planner] classification LLM call failed: %s", exc)
        return dict(FALLBACK_CLASSIFICATION)

    return _validate_classification(result)


def _validate_classification(raw: dict) -> dict:
    """Ensure all classification values are within the valid sets."""
    post_type = raw.get("post_type", "")
    tone = raw.get("tone", "")
    visual_style = raw.get("visual_style", "")

    if post_type not in VALID_POST_TYPES:
        log.warning("[planner] invalid post_type '%s', defaulting to 'educational'", post_type)
        post_type = "educational"
    if tone not in VALID_TONES:
        log.warning("[planner] invalid tone '%s', defaulting to 'professional'", tone)
        tone = "professional"
    if visual_style not in VALID_VISUAL_STYLES:
        log.warning("[planner] invalid visual_style '%s', defaulting to 'clean'", visual_style)
        visual_style = "clean"

    return {
        "post_type": post_type,
        "tone": tone,
        "visual_style": visual_style,
    }


# ---------------------------------------------------------------------------
# Stage 2: Rule engine (deterministic)
# ---------------------------------------------------------------------------

def select_design(
    classification: dict,
    registry: dict,
    available_themes: list[str],
) -> dict:
    """Map a classification to a concrete design using deterministic rules.

    Applies rules in order: post_type base → tone override → visual_style
    override.  Then validates the result against the registry.
    """
    post_type = classification.get("post_type", "educational")
    tone = classification.get("tone", "professional")
    visual_style = classification.get("visual_style", "clean")

    # Start with post_type base rule
    design = dict(_POST_TYPE_RULES.get(post_type, _POST_TYPE_RULES["educational"]))
    # Deep copy asset_roles
    design["asset_roles"] = dict(design["asset_roles"])

    # Apply tone overrides
    tone_ov = _TONE_OVERRIDES.get(tone, {})
    _apply_overrides(design, tone_ov)

    # Apply visual_style overrides
    style_ov = _VISUAL_STYLE_OVERRIDES.get(visual_style, {})
    _apply_overrides(design, style_ov)

    # Validate against registry
    return _validate_against_registry(design, registry, available_themes)


def _apply_overrides(design: dict, overrides: dict) -> None:
    """Apply override dict onto design in-place."""
    for key, val in overrides.items():
        if key == "asset_roles" and isinstance(val, dict):
            design["asset_roles"].update(val)
        else:
            design[key] = val


def _validate_against_registry(
    design: dict,
    registry: dict,
    available_themes: list[str],
) -> dict:
    """Ensure the design references valid registry entries."""
    template = design.get("template", "")
    if template not in registry:
        log.warning("[planner] rule produced invalid template '%s', using fallback", template)
        return dict(FALLBACK_PLAN)

    meta = registry[template]
    valid_variants = meta.get("variants", [])
    valid_themes = meta.get("themes", available_themes)

    # Validate variant
    variant = design.get("variant", "")
    if valid_variants:
        if variant not in valid_variants:
            design["variant"] = valid_variants[0]
            log.warning("[planner] variant '%s' invalid for %s, using '%s'",
                        variant, template, design["variant"])
    else:
        design["variant"] = None  # Legacy template

    # Validate theme
    theme = design.get("theme", "")
    if theme not in valid_themes and theme not in available_themes:
        design["theme"] = meta.get("default_theme", "") or "industrial_dark"
        log.warning("[planner] theme '%s' invalid, using '%s'", theme, design["theme"])

    # Validate asset roles
    roles = design.get("asset_roles", {})
    validated_roles = {}
    for role_id, role_type in roles.items():
        if isinstance(role_type, str) and role_type in VALID_ASSET_ROLE_TYPES:
            validated_roles[role_id] = role_type
        else:
            validated_roles[role_id] = "texture"
    design["asset_roles"] = validated_roles or {"background_asset": "texture"}

    return design


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_design(prompt: str) -> dict:
    """Two-stage design planning: LLM classification + deterministic rules.

    Stage 1: Classify the prompt (post_type, tone, visual_style) via LLM.
    Stage 2: Map the classification to a design via the rule engine.

    Falls back to ``FALLBACK_PLAN`` on any failure.
    """
    from services.carousel_pipeline import _load_registry, list_theme_ids

    # Load registry and themes
    try:
        registry = _load_registry()
        available_themes = list_theme_ids()
    except Exception as exc:
        log.warning("[planner] failed to load registry/themes: %s", exc)
        return dict(FALLBACK_PLAN)

    if not registry:
        log.warning("[planner] registry is empty, using fallback")
        return dict(FALLBACK_PLAN)

    # Stage 1: Classify
    classification = classify_prompt(prompt)
    log.info("[planner] classification: %s", classification)

    # Stage 2: Rule engine
    design = select_design(classification, registry, available_themes)
    design["classification"] = classification

    log.info(
        "[planner] plan: template=%s variant=%s theme=%s roles=%s",
        design["template"],
        design["variant"],
        design["theme"],
        design["asset_roles"],
    )
    return design
