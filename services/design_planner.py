"""AI Design Planner — automatically selects template, variant, theme, and
asset roles for a given user prompt.

Uses the LLM to analyze the prompt and choose the best design configuration
from the available options in the template registry.

Usage::

    from services.design_planner import plan_design

    plan = plan_design("5 strategie per aumentare le vendite online")
    # {
    #     "template": "minimal_layout",
    #     "variant": "split",
    #     "theme": "industrial_dark",
    #     "asset_roles": {
    #         "background_asset": "texture",
    #         "secondary_asset": "product"
    #     }
    # }
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

# Valid asset role categories the planner may assign
ASSET_ROLE_TYPES = ["texture", "product", "abstract", "architecture", "gradient"]

FALLBACK_PLAN = {
    "template": "minimal_layout",
    "variant": "center",
    "theme": "industrial_dark",
    "asset_roles": {
        "background_asset": "texture",
    },
}


def plan_design(prompt: str) -> dict:
    """Use the LLM to select the best template/variant/theme/asset roles.

    Loads the template registry to build a list of valid options, asks the
    LLM to pick the best combination for the given prompt, validates the
    response, and returns a design plan dict.

    Falls back to ``FALLBACK_PLAN`` on any failure.
    """
    # Import here to avoid circular imports and keep module lightweight
    from services.carousel_pipeline import (
        _load_registry,
        list_theme_ids,
        _llm_json,
    )

    try:
        registry = _load_registry()
        available_themes = list_theme_ids()
    except Exception as exc:
        log.warning("[planner] failed to load registry/themes: %s", exc)
        return dict(FALLBACK_PLAN)

    if not registry:
        log.warning("[planner] registry is empty, using fallback")
        return dict(FALLBACK_PLAN)

    # Build a description of available options for the LLM
    options_text = _build_options_text(registry, available_themes)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a design director for Instagram carousels. "
                "Given a user prompt, choose the best template, variant, "
                "theme, and asset roles from the available options.\n\n"
                f"AVAILABLE OPTIONS:\n{options_text}\n\n"
                f"VALID ASSET ROLE TYPES: {', '.join(ASSET_ROLE_TYPES)}\n\n"
                "Asset roles describe the visual style of background images:\n"
                "- texture: marble, wood, fabric, concrete surfaces\n"
                "- product: product photography, objects, items\n"
                "- abstract: geometric shapes, patterns, abstract art\n"
                "- architecture: buildings, interiors, spaces\n"
                "- gradient: smooth color gradients, soft blends\n\n"
                "Reply ONLY with a JSON object:\n"
                "{\n"
                '  "template": "<template_id>",\n'
                '  "variant": "<variant_name>",\n'
                '  "theme": "<theme_id>",\n'
                '  "asset_roles": {\n'
                '    "background_asset": "<role_type>"\n'
                "  }\n"
                "}\n\n"
                "Rules:\n"
                "- template MUST be one of the listed template IDs\n"
                "- variant MUST be valid for the chosen template\n"
                "- theme MUST be one of the listed theme IDs\n"
                "- asset_roles must use only the valid role types listed above\n"
                "- Pick what best fits the mood and content of the prompt"
            ),
        },
        {
            "role": "user",
            "content": f"Choose the best design for this carousel: {prompt}",
        },
    ]

    try:
        plan = _llm_json(messages)
    except Exception as exc:
        log.warning("[planner] LLM call failed: %s", exc)
        return dict(FALLBACK_PLAN)

    # Validate and sanitize the plan
    validated = _validate_plan(plan, registry, available_themes)
    log.info(
        "[planner] plan: template=%s variant=%s theme=%s roles=%s",
        validated["template"],
        validated["variant"],
        validated["theme"],
        validated["asset_roles"],
    )
    return validated


def _build_options_text(registry: dict, available_themes: list[str]) -> str:
    """Build a human-readable list of available design options."""
    lines = []
    for tid, meta in registry.items():
        variants = meta.get("variants", [])
        themes = meta.get("themes", available_themes)
        name = meta.get("name", tid)
        desc = meta.get("description", "")
        variant_str = ", ".join(variants) if variants else "(none — legacy template)"
        lines.append(
            f"- Template: {tid} ({name})\n"
            f"  Description: {desc}\n"
            f"  Variants: {variant_str}\n"
            f"  Compatible themes: {', '.join(themes)}"
        )

    lines.append(f"\nAll available themes: {', '.join(available_themes)}")
    return "\n".join(lines)


def _validate_plan(
    plan: dict,
    registry: dict,
    available_themes: list[str],
) -> dict:
    """Validate LLM output against registry. Fix or fall back on invalid values."""
    result = dict(FALLBACK_PLAN)

    # Validate template
    template = plan.get("template", "")
    if template in registry:
        result["template"] = template
    else:
        log.warning("[planner] invalid template '%s', using fallback", template)
        return dict(FALLBACK_PLAN)

    meta = registry[result["template"]]
    valid_variants = meta.get("variants", [])
    valid_themes = meta.get("themes", available_themes)

    # Validate variant
    variant = plan.get("variant", "")
    if valid_variants:
        if variant in valid_variants:
            result["variant"] = variant
        else:
            result["variant"] = valid_variants[0]
            log.warning(
                "[planner] invalid variant '%s' for %s, using '%s'",
                variant, result["template"], result["variant"],
            )
    else:
        result["variant"] = None  # Legacy template, no variants

    # Validate theme
    theme = plan.get("theme", "")
    if theme in valid_themes:
        result["theme"] = theme
    elif theme in available_themes:
        # Theme exists but not listed as compatible — allow it with warning
        result["theme"] = theme
        log.warning("[planner] theme '%s' not listed for %s but exists", theme, result["template"])
    else:
        result["theme"] = meta.get("default_theme", "") or "industrial_dark"
        log.warning("[planner] invalid theme '%s', using '%s'", theme, result["theme"])

    # Validate asset_roles
    raw_roles = plan.get("asset_roles", {})
    if isinstance(raw_roles, dict):
        validated_roles = {}
        for role_id, role_type in raw_roles.items():
            if isinstance(role_type, str) and role_type in ASSET_ROLE_TYPES:
                validated_roles[role_id] = role_type
            else:
                validated_roles[role_id] = "texture"
                log.warning("[planner] invalid role type '%s' for '%s', using 'texture'", role_type, role_id)
        if validated_roles:
            result["asset_roles"] = validated_roles
        else:
            result["asset_roles"] = {"background_asset": "texture"}
    else:
        result["asset_roles"] = {"background_asset": "texture"}

    return result
