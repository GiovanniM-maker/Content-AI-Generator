"""Layout Patch System — JSON patch-based layout editing for Personalizza.

Enables precise structural modifications to slide elements without
letting the LLM rewrite the full design_spec or generate freeform HTML.

The LLM emits only structured patch operations. This module validates
and applies them to the design_spec's `element_overlays` list, which
the HTML renderer then consumes during slide generation.

ARCHITECTURE
============
1. User says "aggiungi @Juan in basso a destra"
2. Mode detection → LAYOUT_EDIT
3. LLM generates JSON patch operations (not HTML, not full spec)
4. This module validates operations against strict schemas
5. Valid operations are stored in design_spec["element_overlays"]
6. template_renderer.py reads overlays and injects HTML at render time
7. All other design_spec fields remain untouched

SUPPORTED OPERATIONS
====================
- add_element: inject a new positioned element into target slides
- update_element: modify properties of an existing element (by id)
- remove_element: hide/remove an element by id
- move_element: change position (anchor/box) of an element
- update_style: change style properties of an element
- update_opacity: change opacity of an element
- update_slide_scope: change which slides an element appears on

ELEMENT MODEL
=============
Each overlay element has:
- id: stable unique identifier (e.g. "brand_handle", "custom_text_1")
- type: "text" | "image" | "shape" | "divider"
- text_value: literal text (for type=text)
- asset_url: image URL (for type=image)
- anchor: position preset (top_left, center, bottom_right, etc.)
- box: {width, height, margin_x, margin_y}
- style: {font_size, font_weight, color, font_family, opacity, ...}
- target_slides: list of slide types, or null for all slides
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATCH_OPS = frozenset({
    "add_element",
    "update_element",
    "remove_element",
    "move_element",
    "update_style",
    "update_opacity",
    "update_slide_scope",
})

ELEMENT_TYPES = frozenset({"text", "image", "shape", "divider"})

VALID_ANCHORS = frozenset({
    "top_left", "top_center", "top_right",
    "center_left", "center", "center_right",
    "bottom_left", "bottom_center", "bottom_right",
    "full_bg",
})

VALID_SLIDE_TYPES = frozenset({"cover", "content", "list", "cta"})

# Well-known element IDs that map to built-in renderer elements.
# These can be targeted by update_element / move_element / remove_element.
BUILTIN_ELEMENT_IDS = frozenset({
    # Cover
    "cover_title", "cover_subtitle", "cover_accent_line",
    "cover_logo", "cover_counter", "cover_brand_footer",
    "cover_image", "cover_background",
    # Content
    "content_header", "content_body",
    "content_counter", "content_brand_footer",
    # List
    "list_header", "list_items",
    "list_counter", "list_brand_footer",
    # CTA
    "cta_text", "cta_button",
    "cta_counter", "cta_brand_footer",
    # Global (appear on all slides)
    "global_logo", "global_counter", "global_brand_footer",
    "global_background",
})

# Safe dimension limits
MAX_BOX_DIMENSION = 2160  # 2x canvas
MIN_BOX_DIMENSION = 1
MAX_MARGIN = 1080
MAX_FONT_SIZE = 200
MIN_FONT_SIZE = 8
MAX_OPACITY = 1.0
MIN_OPACITY = 0.0

# Element ID format: alphanumeric + underscores, 1-64 chars
_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class PatchValidationResult:
    """Result of validating a list of patch operations."""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def __bool__(self) -> bool:
        return self.valid


# ---------------------------------------------------------------------------
# Schema validators
# ---------------------------------------------------------------------------

def _validate_element_id(eid: str, prefix: str) -> list[str]:
    """Validate an element ID string."""
    errors = []
    if not isinstance(eid, str):
        errors.append(f"{prefix}: id must be a string, got {type(eid).__name__}")
    elif not _ID_RE.match(eid):
        errors.append(
            f"{prefix}: invalid id {eid!r} — must be alphanumeric+underscores, "
            f"start with letter, max 64 chars"
        )
    return errors


def _validate_anchor(anchor, prefix: str) -> list[str]:
    """Validate an anchor value."""
    if anchor is not None and anchor not in VALID_ANCHORS:
        return [f"{prefix}: invalid anchor {anchor!r}"]
    return []


def _validate_box(box, prefix: str) -> list[str]:
    """Validate a box dict."""
    errors = []
    if box is None:
        return []
    if not isinstance(box, dict):
        return [f"{prefix}: box must be a dict"]

    for dim in ("width", "height"):
        val = box.get(dim)
        if val is not None:
            if not isinstance(val, (int, float)) or val < MIN_BOX_DIMENSION:
                errors.append(f"{prefix}.box.{dim}: must be >= {MIN_BOX_DIMENSION}, got {val!r}")
            elif val > MAX_BOX_DIMENSION:
                errors.append(f"{prefix}.box.{dim}: must be <= {MAX_BOX_DIMENSION}, got {val!r}")

    for margin in ("margin_x", "margin_y"):
        val = box.get(margin)
        if val is not None:
            if not isinstance(val, (int, float)) or val < 0:
                errors.append(f"{prefix}.box.{margin}: must be >= 0, got {val!r}")
            elif val > MAX_MARGIN:
                errors.append(f"{prefix}.box.{margin}: must be <= {MAX_MARGIN}, got {val!r}")

    return errors


def _validate_style(style, prefix: str) -> list[str]:
    """Validate a style dict."""
    errors = []
    if style is None:
        return []
    if not isinstance(style, dict):
        return [f"{prefix}: style must be a dict"]

    fs = style.get("font_size")
    if fs is not None:
        if not isinstance(fs, (int, float)):
            errors.append(f"{prefix}.style.font_size: must be a number")
        elif fs < MIN_FONT_SIZE or fs > MAX_FONT_SIZE:
            errors.append(f"{prefix}.style.font_size: must be {MIN_FONT_SIZE}-{MAX_FONT_SIZE}, got {fs}")

    fw = style.get("font_weight")
    if fw is not None:
        if not isinstance(fw, int) or fw < 100 or fw > 900:
            errors.append(f"{prefix}.style.font_weight: must be 100-900, got {fw!r}")

    opacity = style.get("opacity")
    if opacity is not None:
        if not isinstance(opacity, (int, float)):
            errors.append(f"{prefix}.style.opacity: must be a number")
        elif opacity < MIN_OPACITY or opacity > MAX_OPACITY:
            errors.append(f"{prefix}.style.opacity: must be 0.0-1.0, got {opacity}")

    color = style.get("color")
    if color is not None and not isinstance(color, str):
        errors.append(f"{prefix}.style.color: must be a string")

    font_family = style.get("font_family")
    if font_family is not None and not isinstance(font_family, str):
        errors.append(f"{prefix}.style.font_family: must be a string")

    bg = style.get("background")
    if bg is not None and not isinstance(bg, str):
        errors.append(f"{prefix}.style.background: must be a string")

    return errors


def _validate_target_slides(slides, prefix: str) -> list[str]:
    """Validate target_slides field."""
    if slides is None:
        return []  # null = all slides
    if not isinstance(slides, list):
        return [f"{prefix}: target_slides must be a list or null"]
    errors = []
    for s in slides:
        if s not in VALID_SLIDE_TYPES:
            errors.append(f"{prefix}: invalid slide type {s!r}")
    return errors


def _validate_element_def(element: dict, prefix: str) -> list[str]:
    """Validate a full element definition (for add_element)."""
    errors = []
    if not isinstance(element, dict):
        return [f"{prefix}: element must be a dict"]

    etype = element.get("type")
    if etype not in ELEMENT_TYPES:
        errors.append(f"{prefix}: unknown element type {etype!r}")

    if etype == "text":
        tv = element.get("text_value")
        if tv is not None and not isinstance(tv, str):
            errors.append(f"{prefix}: text_value must be a string")
        elif tv is not None and len(tv) > 500:
            errors.append(f"{prefix}: text_value too long ({len(tv)} chars, max 500)")

    if etype == "image":
        url = element.get("asset_url")
        if url is not None and not isinstance(url, str):
            errors.append(f"{prefix}: asset_url must be a string")

    errors.extend(_validate_anchor(element.get("anchor"), prefix))
    errors.extend(_validate_box(element.get("box"), prefix))
    errors.extend(_validate_style(element.get("style"), prefix))

    return errors


# ---------------------------------------------------------------------------
# Operation validators
# ---------------------------------------------------------------------------

def _validate_add_element(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](add_element)"
    errors = []

    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))

    element = op.get("element")
    if element is None:
        errors.append(f"{prefix}: 'element' field is required")
    else:
        errors.extend(_validate_element_def(element, prefix))

    errors.extend(_validate_target_slides(op.get("target_slides"), prefix))
    return errors


def _validate_update_element(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](update_element)"
    errors = []

    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))

    changes = op.get("changes")
    if changes is None:
        errors.append(f"{prefix}: 'changes' field is required")
    elif not isinstance(changes, dict):
        errors.append(f"{prefix}: 'changes' must be a dict")
    else:
        errors.extend(_validate_style(changes.get("style"), prefix))
        errors.extend(_validate_anchor(changes.get("anchor"), prefix))
        errors.extend(_validate_box(changes.get("box"), prefix))

        # text_value update
        tv = changes.get("text_value")
        if tv is not None and not isinstance(tv, str):
            errors.append(f"{prefix}: changes.text_value must be a string")

    errors.extend(_validate_target_slides(op.get("target_slides"), prefix))
    return errors


def _validate_remove_element(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](remove_element)"
    errors = []
    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))
    errors.extend(_validate_target_slides(op.get("target_slides"), prefix))
    return errors


def _validate_move_element(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](move_element)"
    errors = []

    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))

    anchor = op.get("anchor")
    if anchor is None:
        errors.append(f"{prefix}: 'anchor' is required for move_element")
    else:
        errors.extend(_validate_anchor(anchor, prefix))

    errors.extend(_validate_box(op.get("box"), prefix))
    errors.extend(_validate_target_slides(op.get("target_slides"), prefix))
    return errors


def _validate_update_style(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](update_style)"
    errors = []

    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))

    style = op.get("style")
    if style is None:
        errors.append(f"{prefix}: 'style' field is required")
    else:
        errors.extend(_validate_style(style, prefix))

    errors.extend(_validate_target_slides(op.get("target_slides"), prefix))
    return errors


def _validate_update_opacity(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](update_opacity)"
    errors = []

    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))

    opacity = op.get("opacity")
    if opacity is None:
        errors.append(f"{prefix}: 'opacity' is required")
    elif not isinstance(opacity, (int, float)):
        errors.append(f"{prefix}: opacity must be a number")
    elif opacity < MIN_OPACITY or opacity > MAX_OPACITY:
        errors.append(f"{prefix}: opacity must be 0.0-1.0, got {opacity}")

    errors.extend(_validate_target_slides(op.get("target_slides"), prefix))
    return errors


def _validate_update_slide_scope(op: dict, idx: int) -> list[str]:
    prefix = f"op[{idx}](update_slide_scope)"
    errors = []

    eid = op.get("id")
    errors.extend(_validate_element_id(eid, prefix))

    slides = op.get("target_slides")
    if slides is None:
        errors.append(f"{prefix}: 'target_slides' is required (use list or [] to clear)")
    else:
        errors.extend(_validate_target_slides(slides, prefix))

    return errors


_OP_VALIDATORS = {
    "add_element": _validate_add_element,
    "update_element": _validate_update_element,
    "remove_element": _validate_remove_element,
    "move_element": _validate_move_element,
    "update_style": _validate_update_style,
    "update_opacity": _validate_update_opacity,
    "update_slide_scope": _validate_update_slide_scope,
}


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_patch_operations(operations: list[dict]) -> PatchValidationResult:
    """Validate a list of layout patch operations.

    Returns PatchValidationResult with errors (fatal) and warnings.
    """
    result = PatchValidationResult()

    if not isinstance(operations, list):
        result.errors.append("operations must be a list")
        return result

    if len(operations) > 50:
        result.errors.append(f"too many operations ({len(operations)}), max 50")
        return result

    seen_ids: dict[str, int] = {}  # id -> first occurrence index

    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            result.errors.append(f"op[{i}]: must be a dict")
            continue

        op_type = op.get("op")
        if op_type not in PATCH_OPS:
            result.errors.append(f"op[{i}]: unknown op {op_type!r}")
            continue

        # Check for duplicate add_element with same id
        eid = op.get("id")
        if op_type == "add_element" and eid:
            if eid in seen_ids:
                result.warnings.append(
                    f"op[{i}]: duplicate add_element for id {eid!r} "
                    f"(first at op[{seen_ids[eid]}])"
                )
            seen_ids[eid] = i

        # Run type-specific validator
        validator = _OP_VALIDATORS.get(op_type)
        if validator:
            errors = validator(op, i)
            result.errors.extend(errors)

    return result


# ---------------------------------------------------------------------------
# Patch execution — apply operations to design_spec
# ---------------------------------------------------------------------------

def apply_patch_operations(
    design_spec: dict,
    operations: list[dict],
) -> dict:
    """Apply validated patch operations to a design_spec.

    Stores results in design_spec["element_overlays"].
    Returns the updated design_spec (a deep copy).

    IMPORTANT: Call validate_patch_operations() first.
    This function assumes operations are already validated.
    """
    spec = copy.deepcopy(design_spec)
    overlays = spec.setdefault("element_overlays", [])

    for op in operations:
        op_type = op["op"]
        eid = op.get("id")

        if op_type == "add_element":
            _apply_add(overlays, op)
        elif op_type == "update_element":
            _apply_update(overlays, op)
        elif op_type == "remove_element":
            _apply_remove(overlays, op)
        elif op_type == "move_element":
            _apply_move(overlays, op)
        elif op_type == "update_style":
            _apply_update_style(overlays, op)
        elif op_type == "update_opacity":
            _apply_update_opacity(overlays, op)
        elif op_type == "update_slide_scope":
            _apply_update_slide_scope(overlays, op)

        log.info("[layout_patch] applied op=%s, id=%s", op_type, eid)

    return spec


def _find_overlay(overlays: list[dict], eid: str) -> dict | None:
    """Find an existing overlay by element id."""
    for ov in overlays:
        if ov.get("id") == eid:
            return ov
    return None


def _apply_add(overlays: list[dict], op: dict) -> None:
    """Add a new element overlay."""
    eid = op["id"]
    element = op["element"]

    # Remove existing overlay with same id (replace semantics)
    overlays[:] = [ov for ov in overlays if ov.get("id") != eid]

    overlay = {
        "id": eid,
        "op": "add",
        "type": element.get("type", "text"),
        "target_slides": op.get("target_slides"),  # null = all
    }

    # Copy element properties
    for key in ("text_value", "asset_url", "anchor", "box", "style"):
        val = element.get(key)
        if val is not None:
            overlay[key] = copy.deepcopy(val) if isinstance(val, (dict, list)) else val

    overlays.append(overlay)


def _apply_update(overlays: list[dict], op: dict) -> None:
    """Update properties of an existing element."""
    eid = op["id"]
    changes = op["changes"]
    existing = _find_overlay(overlays, eid)

    if existing:
        # Merge changes into existing overlay
        for key in ("text_value", "anchor"):
            if key in changes:
                existing[key] = changes[key]
        if "box" in changes:
            existing_box = existing.setdefault("box", {})
            existing_box.update(changes["box"])
        if "style" in changes:
            existing_style = existing.setdefault("style", {})
            existing_style.update(changes["style"])
        if "target_slides" in op:
            existing["target_slides"] = op["target_slides"]
    else:
        # Create a new overlay as an update directive for a built-in element
        overlay = {
            "id": eid,
            "op": "update",
            "target_slides": op.get("target_slides"),
        }
        for key in ("text_value", "anchor"):
            if key in changes:
                overlay[key] = changes[key]
        if "box" in changes:
            overlay["box"] = dict(changes["box"])
        if "style" in changes:
            overlay["style"] = dict(changes["style"])
        overlays.append(overlay)


def _apply_remove(overlays: list[dict], op: dict) -> None:
    """Mark an element for removal."""
    eid = op["id"]
    # Remove any existing overlay for this id
    overlays[:] = [ov for ov in overlays if ov.get("id") != eid]
    # Add a remove directive
    overlays.append({
        "id": eid,
        "op": "remove",
        "target_slides": op.get("target_slides"),
    })


def _apply_move(overlays: list[dict], op: dict) -> None:
    """Change position of an element."""
    eid = op["id"]
    existing = _find_overlay(overlays, eid)

    if existing:
        existing["anchor"] = op["anchor"]
        if "box" in op:
            existing["box"] = dict(op["box"])
        if "target_slides" in op:
            existing["target_slides"] = op["target_slides"]
    else:
        overlay = {
            "id": eid,
            "op": "move",
            "anchor": op["anchor"],
            "target_slides": op.get("target_slides"),
        }
        if "box" in op:
            overlay["box"] = dict(op["box"])
        overlays.append(overlay)


def _apply_update_style(overlays: list[dict], op: dict) -> None:
    """Update style properties of an element."""
    eid = op["id"]
    existing = _find_overlay(overlays, eid)

    if existing:
        existing_style = existing.setdefault("style", {})
        existing_style.update(op["style"])
    else:
        overlays.append({
            "id": eid,
            "op": "update_style",
            "style": dict(op["style"]),
            "target_slides": op.get("target_slides"),
        })


def _apply_update_opacity(overlays: list[dict], op: dict) -> None:
    """Update opacity of an element."""
    eid = op["id"]
    existing = _find_overlay(overlays, eid)

    if existing:
        existing.setdefault("style", {})["opacity"] = op["opacity"]
    else:
        overlays.append({
            "id": eid,
            "op": "update_opacity",
            "style": {"opacity": op["opacity"]},
            "target_slides": op.get("target_slides"),
        })


def _apply_update_slide_scope(overlays: list[dict], op: dict) -> None:
    """Change which slides an element appears on."""
    eid = op["id"]
    existing = _find_overlay(overlays, eid)

    if existing:
        existing["target_slides"] = op["target_slides"]
    else:
        overlays.append({
            "id": eid,
            "op": "update_slide_scope",
            "target_slides": op["target_slides"],
        })


# ---------------------------------------------------------------------------
# HTML overlay generation — used by template_renderer.py
# ---------------------------------------------------------------------------

def resolve_overlay_position(anchor: str, box: dict | None, canvas_w: int = 1080, canvas_h: int = 1080) -> dict:
    """Resolve anchor + box to absolute CSS position properties.

    Returns dict with CSS property names and values.
    """
    if not box:
        box = {}

    width = box.get("width", 200)
    height = box.get("height", 40)
    mx = box.get("margin_x", 32)
    my = box.get("margin_y", 32)

    css = {
        "position": "absolute",
        "width": f"{width}px",
        "height": f"{height}px",
        "z-index": "10",
    }

    pos_map = {
        "top_left":      {"top": f"{my}px", "left": f"{mx}px"},
        "top_center":    {"top": f"{my}px", "left": "50%", "transform": "translateX(-50%)"},
        "top_right":     {"top": f"{my}px", "right": f"{mx}px"},
        "center_left":   {"top": "50%", "left": f"{mx}px", "transform": "translateY(-50%)"},
        "center":        {"top": "50%", "left": "50%", "transform": "translate(-50%, -50%)"},
        "center_right":  {"top": "50%", "right": f"{mx}px", "transform": "translateY(-50%)"},
        "bottom_left":   {"bottom": f"{my}px", "left": f"{mx}px"},
        "bottom_center": {"bottom": f"{my}px", "left": "50%", "transform": "translateX(-50%)"},
        "bottom_right":  {"bottom": f"{my}px", "right": f"{mx}px"},
        "full_bg":       {"top": "0", "left": "0", "width": "100%", "height": "100%", "z-index": "0"},
    }

    css.update(pos_map.get(anchor, pos_map["center"]))
    return css


def render_overlay_html(overlay: dict, slide_type: str, spec: dict) -> str:
    """Render a single overlay element to an HTML string.

    Args:
        overlay: An overlay dict from design_spec["element_overlays"]
        slide_type: Current slide type being rendered
        spec: The full design_spec (for inheriting colors/fonts)

    Returns:
        HTML string to inject, or "" if overlay doesn't apply.
    """
    # Check if this overlay applies to the current slide
    target = overlay.get("target_slides")
    if target is not None and slide_type not in target:
        return ""

    op = overlay.get("op")
    eid = overlay.get("id", "")

    # Remove directives produce CSS to hide built-in elements
    if op == "remove":
        return _render_remove_css(eid, slide_type)

    # Move/update_style/update_opacity for built-in elements produce CSS overrides
    if op in ("move", "update_style", "update_opacity", "update") and eid in BUILTIN_ELEMENT_IDS:
        return _render_builtin_override_css(overlay, eid, slide_type, spec)

    # Add operations produce new HTML elements
    if op == "add":
        return _render_added_element(overlay, spec)

    return ""


def _esc(text: str) -> str:
    """Escape HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_added_element(overlay: dict, spec: dict) -> str:
    """Render a new overlay element as positioned HTML."""
    etype = overlay.get("type", "text")
    eid = overlay.get("id", "overlay")
    anchor = overlay.get("anchor", "center")
    box = overlay.get("box")
    style = overlay.get("style", {})

    # Resolve position
    pos_css = resolve_overlay_position(anchor, box)

    # Build inline style
    css_parts = [f"{k}:{v}" for k, v in pos_css.items()]

    # Apply style overrides
    if style.get("font_size"):
        css_parts.append(f"font-size:{style['font_size']}px")
    if style.get("font_weight"):
        css_parts.append(f"font-weight:{style['font_weight']}")
    if style.get("color"):
        css_parts.append(f"color:{style['color']}")
    elif spec.get("colors", {}).get("secondary_text"):
        css_parts.append(f"color:{spec['colors']['secondary_text']}")
    if style.get("font_family"):
        css_parts.append(f"font-family:'{style['font_family']}',sans-serif")
    if style.get("opacity") is not None:
        css_parts.append(f"opacity:{style['opacity']}")
    if style.get("background"):
        css_parts.append(f"background:{style['background']}")

    # Add display properties
    css_parts.append("display:flex")
    css_parts.append("align-items:center")
    css_parts.append("overflow:hidden")

    style_str = ";".join(css_parts)

    if etype == "text":
        text_val = overlay.get("text_value", "")
        return f'<div class="overlay-element overlay-{_esc(eid)}" style="{style_str}">{_esc(text_val)}</div>'
    elif etype == "image":
        url = overlay.get("asset_url", "")
        return (
            f'<div class="overlay-element overlay-{_esc(eid)}" style="{style_str}">'
            f'<img src="{_esc(url)}" style="width:100%;height:100%;object-fit:contain;" />'
            f'</div>'
        )
    elif etype == "shape":
        bg = style.get("background", spec.get("colors", {}).get("accent", "#7c5ce7"))
        radius = style.get("border_radius", 0)
        css_parts.append(f"background:{bg}")
        css_parts.append(f"border-radius:{radius}px")
        style_str = ";".join(css_parts)
        return f'<div class="overlay-element overlay-{_esc(eid)}" style="{style_str}"></div>'
    elif etype == "divider":
        color = style.get("color", spec.get("colors", {}).get("accent", "#7c5ce7"))
        return (
            f'<div class="overlay-element overlay-{_esc(eid)}" style="{style_str}">'
            f'<div style="width:100%;height:4px;background:{color};border-radius:2px;"></div>'
            f'</div>'
        )

    return ""


# CSS class mapping for built-in element IDs
_BUILTIN_CSS_SELECTORS = {
    "cover_title": ".cover-title",
    "cover_subtitle": ".cover-subtitle",
    "cover_accent_line": ".accent-line",
    "cover_logo": ".slide-container > img",
    "cover_counter": ".slide-counter",
    "cover_brand_footer": ".brand-footer",
    "cover_image": ".cover-image",
    "cover_background": ".bg-image",
    "content_header": ".content-header",
    "content_body": ".content-body, .body-text",
    "content_counter": ".slide-counter",
    "content_brand_footer": ".brand-footer",
    "list_header": ".heading",
    "list_items": ".list-item",
    "list_counter": ".slide-counter",
    "list_brand_footer": ".brand-footer",
    "cta_text": ".cta-main-text",
    "cta_button": ".cta-button",
    "cta_counter": ".slide-counter",
    "cta_brand_footer": ".brand-footer",
    "global_logo": ".slide-container > img",
    "global_counter": ".slide-counter",
    "global_brand_footer": ".brand-footer",
    "global_background": ".bg-image",
}


def _render_remove_css(eid: str, slide_type: str) -> str:
    """Generate CSS to hide a built-in element."""
    selector = _BUILTIN_CSS_SELECTORS.get(eid)
    if not selector:
        return ""
    return f'<style>{selector} {{ display: none !important; }}</style>'


def _render_builtin_override_css(overlay: dict, eid: str, slide_type: str, spec: dict) -> str:
    """Generate CSS overrides for a built-in element."""
    selector = _BUILTIN_CSS_SELECTORS.get(eid)
    if not selector:
        return ""

    css_props = []
    style = overlay.get("style", {})

    if style.get("font_size"):
        css_props.append(f"font-size: {style['font_size']}px !important")
    if style.get("font_weight"):
        css_props.append(f"font-weight: {style['font_weight']} !important")
    if style.get("color"):
        css_props.append(f"color: {style['color']} !important")
    if style.get("font_family"):
        css_props.append(f"font-family: '{style['font_family']}', sans-serif !important")
    if style.get("opacity") is not None:
        css_props.append(f"opacity: {style['opacity']} !important")
    if style.get("background"):
        css_props.append(f"background: {style['background']} !important")

    # Position overrides for move
    anchor = overlay.get("anchor")
    if anchor:
        box = overlay.get("box")
        pos = resolve_overlay_position(anchor, box)
        for k, v in pos.items():
            css_props.append(f"{k}: {v} !important")

    if not css_props:
        return ""

    props_str = "; ".join(css_props)
    return f'<style>{selector} {{ {props_str}; }}</style>'


def render_all_overlays(spec: dict, slide_type: str) -> str:
    """Render all overlay elements for a given slide type.

    Called by template_renderer.py during slide generation.
    Returns HTML string to inject before </body>.
    """
    overlays = spec.get("element_overlays", [])
    if not overlays:
        return ""

    parts = []
    for ov in overlays:
        html = render_overlay_html(ov, slide_type, spec)
        if html:
            parts.append(html)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM prompt builder for LAYOUT_EDIT_MODE
# ---------------------------------------------------------------------------

LAYOUT_EDIT_SYSTEM_PROMPT = """Sei un layout editor per slide Instagram. Il tuo compito è generare SOLO operazioni di patch JSON strutturate.

══ OPERAZIONI SUPPORTATE ══
1. add_element — aggiunge un nuovo elemento posizionato
2. update_element — modifica proprietà di un elemento esistente
3. remove_element — rimuove/nasconde un elemento
4. move_element — cambia posizione di un elemento
5. update_style — modifica lo stile di un elemento
6. update_opacity — cambia l'opacità
7. update_slide_scope — cambia su quali slide appare

══ ANCHORS VALIDI ══
top_left, top_center, top_right, center_left, center, center_right,
bottom_left, bottom_center, bottom_right, full_bg

══ SLIDE TYPES ══
cover, content, list, cta
(null/omesso = tutte le slide)

══ ELEMENT TYPES ══
text, image, shape, divider

══ BUILT-IN ELEMENT IDS ══
Cover: cover_title, cover_subtitle, cover_accent_line, cover_logo, cover_counter, cover_brand_footer, cover_image
Content: content_header, content_body, content_counter, content_brand_footer
List: list_header, list_items, list_counter, list_brand_footer
CTA: cta_text, cta_button, cta_counter, cta_brand_footer
Global: global_logo, global_counter, global_brand_footer, global_background

══ FORMATO RISPOSTA ══
Rispondi SEMPRE con JSON in questo formato:
{
  "reply": "breve descrizione di cosa hai fatto",
  "operations": [
    {
      "op": "add_element|update_element|remove_element|move_element|update_style|update_opacity|update_slide_scope",
      "id": "element_id",
      "target_slides": ["cover", "content"] o null per tutte,
      ... campi specifici per operazione ...
    }
  ]
}

══ REGOLE ══
1. NON generare HTML
2. NON modificare colori/font/layout globali (quelli sono STYLE_MODE)
3. NON modificare il testo del contenuto a meno che l'utente lo chieda esplicitamente
4. USA gli element ID built-in per elementi esistenti
5. CREA nuovi ID per elementi aggiunti (es: "brand_handle", "custom_watermark")
6. OGNI operazione deve avere "op" e "id"

══ ESEMPI ══

Richiesta: "aggiungi @Juan in basso a destra in tutte le slide"
{
  "reply": "Ho aggiunto @Juan in basso a destra su tutte le slide.",
  "operations": [
    {
      "op": "add_element",
      "id": "brand_handle",
      "target_slides": null,
      "element": {
        "type": "text",
        "text_value": "@Juan",
        "anchor": "bottom_right",
        "box": {"width": 180, "height": 40, "margin_x": 32, "margin_y": 24},
        "style": {"font_size": 18, "font_weight": 600}
      }
    }
  ]
}

Richiesta: "sposta il titolo più in alto nella cover"
{
  "reply": "Ho spostato il titolo più in alto nella cover.",
  "operations": [
    {
      "op": "move_element",
      "id": "cover_title",
      "target_slides": ["cover"],
      "anchor": "top_center",
      "box": {"width": 920, "height": 200, "margin_x": 80, "margin_y": 120}
    }
  ]
}

Richiesta: "usa il logo su tutte le slide"
{
  "reply": "Ho aggiunto il logo su tutte le slide.",
  "operations": [
    {
      "op": "update_slide_scope",
      "id": "global_logo",
      "target_slides": null
    }
  ]
}

Richiesta: "rendi lo sfondo di marmo più scuro"
{
  "reply": "Ho reso lo sfondo più scuro aumentando l'overlay.",
  "operations": [
    {
      "op": "update_opacity",
      "id": "global_background",
      "target_slides": null,
      "opacity": 0.2
    }
  ]
}

Richiesta: "metti l'immagine della cucina sotto il titolo nella cover"
{
  "reply": "Ho posizionato l'immagine sotto il titolo nella cover.",
  "operations": [
    {
      "op": "move_element",
      "id": "cover_image",
      "target_slides": ["cover"],
      "anchor": "center",
      "box": {"width": 600, "height": 400, "margin_x": 40, "margin_y": 300}
    }
  ]
}
"""


def build_layout_edit_prompt(
    user_message: str,
    current_spec: dict,
    current_overlays: list[dict] | None = None,
) -> str:
    """Build the user-facing prompt for the LLM in LAYOUT_EDIT_MODE.

    Returns the user prompt string (system prompt is separate).
    """
    import json

    parts = [f"RICHIESTA UTENTE: {user_message}"]

    # Include current overlays so LLM knows what's already there
    if current_overlays:
        parts.append(
            f"\nELEMENT OVERLAYS ATTUALI:\n```json\n{json.dumps(current_overlays, indent=2)}\n```"
        )
    else:
        parts.append("\nNessun overlay attualmente applicato.")

    # Include relevant spec context (not the full thing)
    context = {
        "slide_types": ["cover", "content", "list", "cta"],
        "has_logo": bool(current_spec.get("images", {}).get("logo_url")),
        "has_background": bool(current_spec.get("images", {}).get("background_image_url")),
        "has_cover_image": bool(current_spec.get("images", {}).get("slide_images", {}).get("cover")),
    }
    parts.append(f"\nCONTESTO SLIDE:\n```json\n{json.dumps(context, indent=2)}\n```")

    parts.append(
        "\nGenera SOLO le operazioni JSON necessarie. "
        "NON modificare il design globale. NON generare HTML."
    )

    return "\n".join(parts)
