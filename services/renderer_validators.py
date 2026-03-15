"""Renderer validation layers — enforce architecture spec guardrails.

Validates templates, themes, overrides, placement configs, and asset
mappings BEFORE they reach the renderer.  Every validator returns a
``ValidationResult`` with warnings and errors.  Errors are fatal
(the pipeline should not proceed).  Warnings are informational
(the renderer will degrade gracefully).

Usage::

    from services.renderer_validators import (
        validate_template,
        validate_theme,
        validate_overrides,
        validate_placement_overrides,
        validate_asset_mapping,
        validate_content,
        validate_registry,
    )

    result = validate_template(template_dict)
    if result.errors:
        raise ValueError(f"Invalid template: {result.errors}")
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Container for validation warnings and errors."""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def __bool__(self) -> bool:
        return self.valid

    def merge(self, other: ValidationResult) -> ValidationResult:
        return ValidationResult(
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# ---------------------------------------------------------------------------
# Constants (closed sets from architecture spec)
# ---------------------------------------------------------------------------

ELEMENT_TYPES = frozenset({
    "image", "rect", "title", "subtitle", "body",
    "bullet_list", "cta", "slide_counter",
})

TEXT_ELEMENT_TYPES = frozenset({
    "title", "subtitle", "body", "cta", "bullet_list", "slide_counter",
})

VALID_ANCHORS = frozenset({
    "top_left", "top_center", "top_right",
    "center_left", "center", "center_right",
    "bottom_left", "bottom_center", "bottom_right",
    "full_bg",
})

VALID_RECT_ROLES = frozenset({
    "accent", "overlay", "overlay_heavy", "marker", "button",
})

VALID_ALIGNS = frozenset({"left", "center", "right"})

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3}([0-9a-fA-F]{2})?)?$")

OVERRIDE_PROPERTIES = frozenset({"font", "size", "color", "weight"})

VALID_OVERRIDE_KEYS = frozenset(
    f"{etype}_{prop}"
    for etype in TEXT_ELEMENT_TYPES
    for prop in OVERRIDE_PROPERTIES
) | frozenset({
    "accent_color",
    "bullet_list_marker_color",
    "cta_button_color",
})


# ---------------------------------------------------------------------------
# Color validation
# ---------------------------------------------------------------------------

def is_valid_color(color: str) -> bool:
    """Check if a color string is a valid hex color."""
    if not isinstance(color, str):
        return False
    return bool(_HEX_RE.match(color.strip()))


# ---------------------------------------------------------------------------
# Template validation
# ---------------------------------------------------------------------------

def validate_template(template: dict) -> ValidationResult:
    """Validate a layout template against the architecture spec.

    Checks:
    - canvas dict with width/height (positive ints)
    - slides list with >= 1 entry
    - each slide has a unique name and elements list
    - each element has a type in ELEMENT_TYPES
    - image elements have asset_id or (x+y+width+height) or anchor
    - text elements have x, y
    - rect elements have x, y, width, height
    - no duplicate slide names
    """
    r = ValidationResult()

    if not isinstance(template, dict):
        r.errors.append("template must be a dict")
        return r

    # Canvas
    canvas = template.get("canvas")
    if not isinstance(canvas, dict):
        r.errors.append("template.canvas must be a dict")
    else:
        w = canvas.get("width")
        h = canvas.get("height")
        if not isinstance(w, (int, float)) or w <= 0:
            r.errors.append(f"canvas.width must be a positive number, got {w!r}")
        if not isinstance(h, (int, float)) or h <= 0:
            r.errors.append(f"canvas.height must be a positive number, got {h!r}")
        bg = canvas.get("background")
        if bg is not None and not is_valid_color(str(bg)):
            r.warnings.append(f"canvas.background is not a valid hex color: {bg!r}")

    # Slides
    slides = template.get("slides")
    if not isinstance(slides, list) or len(slides) == 0:
        r.errors.append("template.slides must be a non-empty list")
        return r

    slide_names = set()
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            r.errors.append(f"slide[{i}] must be a dict")
            continue

        name = slide.get("name")
        if not name or not isinstance(name, str):
            r.errors.append(f"slide[{i}].name must be a non-empty string")
        elif name in slide_names:
            r.errors.append(f"duplicate slide name: {name!r}")
        else:
            slide_names.add(name)

        elements = slide.get("elements")
        if not isinstance(elements, list):
            r.errors.append(f"slide[{i}] ({name}).elements must be a list")
            continue

        for j, el in enumerate(elements):
            el_result = _validate_element(el, i, j, name or f"slide_{i}")
            r = r.merge(el_result)

    return r


def _validate_element(el: dict, slide_idx: int, el_idx: int, slide_name: str) -> ValidationResult:
    """Validate a single layout element."""
    r = ValidationResult()
    prefix = f"slide[{slide_idx}]({slide_name}).element[{el_idx}]"

    if not isinstance(el, dict):
        r.errors.append(f"{prefix}: element must be a dict")
        return r

    etype = el.get("type")
    if etype not in ELEMENT_TYPES:
        r.errors.append(f"{prefix}: unknown element type {etype!r}")
        return r

    # Image elements
    if etype == "image":
        has_asset_id = bool(el.get("asset_id"))
        has_anchor = bool(el.get("anchor"))
        has_explicit = all(k in el for k in ("x", "y", "width", "height"))

        if not has_asset_id and not has_anchor and not has_explicit:
            r.warnings.append(
                f"{prefix}: image element has no asset_id, anchor, or explicit x/y/w/h"
            )

        anchor = el.get("anchor")
        if anchor and anchor not in VALID_ANCHORS:
            r.errors.append(f"{prefix}: invalid anchor {anchor!r}")

    # Rect elements
    elif etype == "rect":
        for field_name in ("x", "y", "width", "height"):
            if field_name not in el:
                r.warnings.append(f"{prefix}: rect missing {field_name}")

        role = el.get("role")
        if role and role not in VALID_RECT_ROLES:
            r.warnings.append(f"{prefix}: unknown rect role {role!r}")

        color = el.get("color")
        if color and not is_valid_color(str(color)):
            r.warnings.append(f"{prefix}: invalid color {color!r}")

    # Text-like elements
    elif etype in TEXT_ELEMENT_TYPES:
        if "x" not in el:
            r.warnings.append(f"{prefix}: text element missing x")
        if "y" not in el:
            r.warnings.append(f"{prefix}: text element missing y")

        align = el.get("align")
        if align and align not in VALID_ALIGNS:
            r.warnings.append(f"{prefix}: invalid align {align!r}")

        color = el.get("color")
        if color and not is_valid_color(str(color)):
            r.warnings.append(f"{prefix}: invalid color {color!r}")

        size = el.get("size")
        if size is not None and (not isinstance(size, (int, float)) or size <= 0):
            r.warnings.append(f"{prefix}: size must be positive, got {size!r}")

        weight = el.get("weight")
        if weight is not None and (not isinstance(weight, int) or weight < 100 or weight > 900):
            r.warnings.append(f"{prefix}: weight must be 100-900, got {weight!r}")

    return r


# ---------------------------------------------------------------------------
# Theme validation
# ---------------------------------------------------------------------------

def validate_theme(theme: dict) -> ValidationResult:
    """Validate a resolved theme (after inheritance + token resolution).

    Checks:
    - has id
    - fonts values are strings
    - sizes values are positive ints
    - weights values are ints 100-900
    - colors values are valid hex colors
    """
    r = ValidationResult()

    if not isinstance(theme, dict):
        r.errors.append("theme must be a dict")
        return r

    if not theme.get("id"):
        r.warnings.append("theme missing id field")

    # Fonts
    fonts = theme.get("fonts", {})
    if isinstance(fonts, dict):
        for key, val in fonts.items():
            if not isinstance(val, str):
                r.warnings.append(f"theme.fonts.{key} must be a string, got {type(val).__name__}")
    elif fonts:
        r.errors.append("theme.fonts must be a dict")

    # Sizes
    sizes = theme.get("sizes", {})
    if isinstance(sizes, dict):
        for key, val in sizes.items():
            if not isinstance(val, (int, float)) or val <= 0:
                r.warnings.append(f"theme.sizes.{key} must be positive, got {val!r}")
            # Detect unresolved token reference
            if isinstance(val, str) and "." in val:
                r.warnings.append(f"theme.sizes.{key} has unresolved token: {val!r}")

    # Weights
    weights = theme.get("weights", {})
    if isinstance(weights, dict):
        for key, val in weights.items():
            if isinstance(val, str) and "." in val:
                r.warnings.append(f"theme.weights.{key} has unresolved token: {val!r}")
            elif not isinstance(val, int) or val < 100 or val > 900:
                r.warnings.append(f"theme.weights.{key} must be 100-900, got {val!r}")

    # Colors
    colors = theme.get("colors", {})
    if isinstance(colors, dict):
        for key, val in colors.items():
            if isinstance(val, str):
                if "." in val and not val.startswith("#"):
                    r.warnings.append(f"theme.colors.{key} has unresolved token: {val!r}")
                elif not is_valid_color(val):
                    r.warnings.append(f"theme.colors.{key} is not a valid hex color: {val!r}")
            else:
                r.warnings.append(f"theme.colors.{key} must be a string, got {type(val).__name__}")

    # Button
    button = theme.get("button", {})
    if isinstance(button, dict):
        for key in ("padding_x", "padding_y", "radius"):
            val = button.get(key)
            if val is not None and (not isinstance(val, (int, float)) or val < 0):
                r.warnings.append(f"theme.button.{key} must be non-negative, got {val!r}")

    return r


# ---------------------------------------------------------------------------
# Override validation
# ---------------------------------------------------------------------------

def validate_overrides(overrides: dict) -> ValidationResult:
    """Validate user overrides against the architecture spec.

    Override keys must follow ``{element_type}_{property}`` format.
    """
    r = ValidationResult()

    if not isinstance(overrides, dict):
        r.errors.append("overrides must be a dict")
        return r

    for key, val in overrides.items():
        if key not in VALID_OVERRIDE_KEYS:
            r.warnings.append(f"unknown override key: {key!r}")

        # Validate value types based on property suffix
        if key.endswith("_color"):
            if isinstance(val, str) and not is_valid_color(val):
                r.warnings.append(f"override {key}: invalid color {val!r}")
        elif key.endswith("_size"):
            if not isinstance(val, (int, float)) or val <= 0:
                r.warnings.append(f"override {key}: size must be positive, got {val!r}")
        elif key.endswith("_weight"):
            if not isinstance(val, int) or val < 100 or val > 900:
                r.warnings.append(f"override {key}: weight must be 100-900, got {val!r}")
        elif key.endswith("_font"):
            if not isinstance(val, str) or not val.strip():
                r.warnings.append(f"override {key}: font must be a non-empty string")

    return r


# ---------------------------------------------------------------------------
# Placement override validation
# ---------------------------------------------------------------------------

def validate_placement_overrides(
    placement_overrides: dict,
    template: dict | None = None,
) -> ValidationResult:
    """Validate placement overrides before applying them to a template.

    Checks:
    - each entry has a valid anchor (if present)
    - box dimensions are positive (if present)
    - slides targets reference actual slide names (if template provided)
    """
    r = ValidationResult()

    if not isinstance(placement_overrides, dict):
        r.errors.append("placement_overrides must be a dict")
        return r

    # Collect valid slide names from template
    valid_slides = set()
    if template:
        for slide in template.get("slides", []):
            name = slide.get("name")
            if name:
                valid_slides.add(name)

    for slot_id, config in placement_overrides.items():
        prefix = f"placement_overrides[{slot_id!r}]"

        if not isinstance(config, dict):
            r.errors.append(f"{prefix}: must be a dict")
            continue

        anchor = config.get("anchor")
        if anchor and anchor not in VALID_ANCHORS:
            r.errors.append(f"{prefix}: invalid anchor {anchor!r}")

        box = config.get("box")
        if box is not None:
            if not isinstance(box, dict):
                r.errors.append(f"{prefix}.box: must be a dict")
            else:
                for dim in ("width", "height"):
                    val = box.get(dim)
                    if val is not None and (not isinstance(val, (int, float)) or val <= 0):
                        r.errors.append(f"{prefix}.box.{dim}: must be positive, got {val!r}")
                for margin in ("margin_x", "margin_y"):
                    val = box.get(margin)
                    if val is not None and (not isinstance(val, (int, float)) or val < 0):
                        r.warnings.append(f"{prefix}.box.{margin}: should be non-negative, got {val!r}")

        slides = config.get("slides")
        if slides is not None:
            if not isinstance(slides, list):
                r.errors.append(f"{prefix}.slides: must be a list")
            elif valid_slides:
                for s in slides:
                    if s not in valid_slides:
                        r.warnings.append(
                            f"{prefix}.slides: unknown slide {s!r}, "
                            f"valid: {sorted(valid_slides)}"
                        )

    return r


# ---------------------------------------------------------------------------
# Asset mapping validation
# ---------------------------------------------------------------------------

def validate_asset_mapping(
    asset_map: dict,
    template: dict,
) -> ValidationResult:
    """Validate asset mapping against template-declared asset slots.

    Warns when:
    - template declares a slot that has no asset in the map
    - asset_map provides an asset not referenced by any template slot
    """
    r = ValidationResult()

    if not isinstance(asset_map, dict):
        r.errors.append("asset_map must be a dict")
        return r

    # Collect all asset_ids declared in template
    declared_slots: set[str] = set()
    for slide in template.get("slides", []):
        for el in slide.get("elements", []):
            if el.get("type") == "image":
                aid = el.get("asset_id")
                if aid:
                    declared_slots.add(aid)

    # Check for undeclared assets in map (might be injected via placement overrides)
    provided = set(asset_map.keys())
    extra = provided - declared_slots
    for slot_id in sorted(extra):
        r.warnings.append(
            f"asset_map contains {slot_id!r} which is not declared "
            f"in template (may be injected via placement overrides)"
        )

    # Check for declared slots without assets
    missing = declared_slots - provided
    for slot_id in sorted(missing):
        r.warnings.append(
            f"template declares slot {slot_id!r} but no asset provided; "
            f"element will use fill fallback or be skipped"
        )

    return r


# ---------------------------------------------------------------------------
# Content validation
# ---------------------------------------------------------------------------

_CONTENT_LIMITS = {
    "title": 200,
    "subtitle": 300,
    "body": 1000,
    "cta": 100,
}

_BULLET_MAX_ITEMS = 8
_BULLET_MAX_LENGTH = 200


def validate_content(content: dict) -> ValidationResult:
    """Validate content dict before rendering.

    Checks string lengths and bullet list size limits.
    """
    r = ValidationResult()

    if not isinstance(content, dict):
        r.errors.append("content must be a dict")
        return r

    for key, max_len in _CONTENT_LIMITS.items():
        val = content.get(key)
        if val is not None:
            if not isinstance(val, str):
                r.warnings.append(f"content.{key} should be a string, got {type(val).__name__}")
            elif len(val) > max_len:
                r.warnings.append(
                    f"content.{key} is {len(val)} chars (max {max_len}), will be truncated"
                )

    bullets = content.get("bullets")
    if bullets is not None:
        if not isinstance(bullets, list):
            r.warnings.append("content.bullets should be a list")
        else:
            if len(bullets) > _BULLET_MAX_ITEMS:
                r.warnings.append(
                    f"content.bullets has {len(bullets)} items (max {_BULLET_MAX_ITEMS})"
                )
            for i, b in enumerate(bullets):
                if not isinstance(b, str):
                    r.warnings.append(f"content.bullets[{i}] should be a string")
                elif len(b) > _BULLET_MAX_LENGTH:
                    r.warnings.append(
                        f"content.bullets[{i}] is {len(b)} chars (max {_BULLET_MAX_LENGTH})"
                    )

    return r


# ---------------------------------------------------------------------------
# Registry validation
# ---------------------------------------------------------------------------

def validate_registry(
    registry: dict,
    layouts_dir: str | None = None,
    themes_dir: str | None = None,
) -> ValidationResult:
    """Validate the template registry against the filesystem.

    Checks:
    - each layout entry has corresponding layout files
    - each variant has a corresponding .json file
    - default_theme exists in themes dir
    - all listed themes exist
    """
    r = ValidationResult()

    if not isinstance(registry, dict):
        r.errors.append("registry must be a dict")
        return r

    base_dir = os.path.dirname(os.path.dirname(__file__))
    layouts_dir = layouts_dir or os.path.join(base_dir, "templates", "layouts")
    themes_dir = themes_dir or os.path.join(base_dir, "templates", "themes")

    # Collect available theme files
    available_themes = set()
    if os.path.isdir(themes_dir):
        for f in os.listdir(themes_dir):
            if f.endswith(".json"):
                available_themes.add(f.replace(".json", ""))

    for layout_id, meta in registry.items():
        prefix = f"registry[{layout_id!r}]"

        if not isinstance(meta, dict):
            r.errors.append(f"{prefix}: must be a dict")
            continue

        variants = meta.get("variants", [])

        # Check layout exists
        layout_dir = os.path.join(layouts_dir, layout_id)
        layout_flat = os.path.join(layouts_dir, f"{layout_id}.json")

        if variants:
            # Directory-based layout
            if not os.path.isdir(layout_dir):
                r.errors.append(f"{prefix}: layout directory not found at {layout_dir}")
            else:
                for v in variants:
                    vpath = os.path.join(layout_dir, f"{v}.json")
                    if not os.path.isfile(vpath):
                        r.errors.append(f"{prefix}: variant file not found: {vpath}")
        else:
            # Flat or legacy layout
            if not os.path.isdir(layout_dir) and not os.path.isfile(layout_flat):
                r.errors.append(f"{prefix}: layout not found (no dir or flat file)")

        # Check default_theme
        default_theme = meta.get("default_theme", "")
        if default_theme and default_theme not in available_themes:
            r.warnings.append(f"{prefix}: default_theme {default_theme!r} not found in themes/")

        # Check theme list
        themes = meta.get("themes", [])
        for tid in themes:
            if tid not in available_themes:
                r.warnings.append(f"{prefix}: theme {tid!r} listed but not found in themes/")

    return r


# ---------------------------------------------------------------------------
# Composite validation for the full pipeline
# ---------------------------------------------------------------------------

def validate_render_inputs(
    template: dict,
    theme: dict | None = None,
    content: dict | None = None,
    asset_map: dict | None = None,
    overrides: dict | None = None,
    placement_overrides: dict | None = None,
) -> ValidationResult:
    """Run all relevant validators on render inputs.

    Returns a merged ValidationResult.  If result.errors is non-empty,
    the caller should abort rendering.
    """
    result = validate_template(template)

    if theme is not None:
        result = result.merge(validate_theme(theme))

    if content is not None:
        result = result.merge(validate_content(content))

    if asset_map is not None:
        result = result.merge(validate_asset_mapping(asset_map, template))

    if overrides:
        result = result.merge(validate_overrides(overrides))

    if placement_overrides:
        result = result.merge(validate_placement_overrides(placement_overrides, template))

    return result
