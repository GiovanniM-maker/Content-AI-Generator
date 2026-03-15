"""Asset placement system — semantic anchors + box configuration.

Provides deterministic anchor-based positioning for image elements
instead of arbitrary x/y drag behavior.  Templates declare asset slots
with an ``anchor`` preset and optional ``box`` config; this module
resolves those into concrete pixel coordinates on a given canvas.

Supported anchors
-----------------
- top_left, top_right, top_center
- center_left, center, center_right
- bottom_left, bottom_right, bottom_center
- full_bg

Each anchor also respects margin_x / margin_y offsets.

Usage::

    from services.asset_placement import resolve_anchor

    coords = resolve_anchor(
        anchor="top_left",
        box={"width": 160, "height": 80, "margin_x": 40, "margin_y": 40},
        canvas_w=1080,
        canvas_h=1080,
    )
    # {"x": 40, "y": 40, "width": 160, "height": 80}
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anchor presets
# ---------------------------------------------------------------------------

# Each anchor function receives (box_w, box_h, margin_x, margin_y, canvas_w, canvas_h)
# and returns (x, y).

def _top_left(bw, bh, mx, my, cw, ch):
    return mx, my

def _top_center(bw, bh, mx, my, cw, ch):
    return (cw - bw) // 2, my

def _top_right(bw, bh, mx, my, cw, ch):
    return cw - bw - mx, my

def _center_left(bw, bh, mx, my, cw, ch):
    return mx, (ch - bh) // 2

def _center(bw, bh, mx, my, cw, ch):
    return (cw - bw) // 2, (ch - bh) // 2

def _center_right(bw, bh, mx, my, cw, ch):
    return cw - bw - mx, (ch - bh) // 2

def _bottom_left(bw, bh, mx, my, cw, ch):
    return mx, ch - bh - my

def _bottom_center(bw, bh, mx, my, cw, ch):
    return (cw - bw) // 2, ch - bh - my

def _bottom_right(bw, bh, mx, my, cw, ch):
    return cw - bw - mx, ch - bh - my

def _full_bg(bw, bh, mx, my, cw, ch):
    return 0, 0


_ANCHOR_MAP = {
    "top_left": _top_left,
    "top_center": _top_center,
    "top_right": _top_right,
    "center_left": _center_left,
    "center": _center,
    "center_right": _center_right,
    "bottom_left": _bottom_left,
    "bottom_center": _bottom_center,
    "bottom_right": _bottom_right,
    "full_bg": _full_bg,
}

VALID_ANCHORS = list(_ANCHOR_MAP.keys())


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def resolve_anchor(
    anchor: str,
    box: dict | None = None,
    canvas_w: int = 1080,
    canvas_h: int = 1080,
) -> dict:
    """Resolve an anchor preset + box config into pixel coordinates.

    Args:
        anchor: Placement preset name (e.g. "top_left", "center").
        box: Optional sizing config with width, height, margin_x, margin_y.
        canvas_w: Canvas width in pixels.
        canvas_h: Canvas height in pixels.

    Returns:
        Dict with x, y, width, height ready for the renderer.
    """
    box = box or {}

    if anchor == "full_bg":
        return {"x": 0, "y": 0, "width": canvas_w, "height": canvas_h}

    bw = int(box.get("width", 200))
    bh = int(box.get("height", 200))
    mx = int(box.get("margin_x", 40))
    my = int(box.get("margin_y", 40))

    fn = _ANCHOR_MAP.get(anchor)
    if fn is None:
        log.warning("[placement] unknown anchor '%s', defaulting to center", anchor)
        fn = _center

    x, y = fn(bw, bh, mx, my, canvas_w, canvas_h)
    return {"x": int(x), "y": int(y), "width": bw, "height": bh}


def apply_placement_overrides(
    template: dict,
    placement_overrides: dict,
    asset_mapping: dict | None = None,
) -> dict:
    """Apply placement overrides to a template, returning a modified copy.

    Placement overrides specify per-asset_id positioning and slide targeting::

        {
            "logo_asset": {
                "anchor": "top_left",
                "box": {"width": 160, "height": 80, "margin_x": 40, "margin_y": 40},
                "slides": ["cover", "cta"]
            }
        }

    This function:
    1. Injects new image elements for asset_ids not in the template.
    2. Updates existing image elements matching the asset_id.
    3. Removes image elements from slides not in the ``slides`` list.
    """
    if not placement_overrides:
        return template

    canvas = template.get("canvas", {"width": 1080, "height": 1080})
    canvas_w = int(canvas.get("width", 1080))
    canvas_h = int(canvas.get("height", 1080))

    modified = dict(template)
    modified["slides"] = []

    for slide_def in template.get("slides", []):
        slide_name = slide_def.get("name", "")
        new_slide = dict(slide_def)
        new_elements = []

        # Track which overrides already matched existing elements
        matched_overrides = set()

        for el in slide_def.get("elements", []):
            if el.get("type") != "image":
                new_elements.append(el)
                continue

            el_asset_id = el.get("asset_id", "")

            if el_asset_id in placement_overrides:
                ov = placement_overrides[el_asset_id]
                matched_overrides.add(el_asset_id)

                # Check slide targeting
                target_slides = ov.get("slides")
                if target_slides and slide_name not in target_slides:
                    # Skip this element on this slide
                    continue

                # Apply anchor override
                if "anchor" in ov:
                    coords = resolve_anchor(
                        ov["anchor"],
                        box=ov.get("box"),
                        canvas_w=canvas_w,
                        canvas_h=canvas_h,
                    )
                    updated = dict(el)
                    updated.update(coords)
                    new_elements.append(updated)
                else:
                    new_elements.append(el)
            else:
                new_elements.append(el)

        # Inject new image elements for overrides that didn't match
        for asset_id, ov in placement_overrides.items():
            if asset_id in matched_overrides:
                continue

            # Check slide targeting
            target_slides = ov.get("slides")
            if target_slides and slide_name not in target_slides:
                continue

            anchor = ov.get("anchor", "center")
            coords = resolve_anchor(
                anchor,
                box=ov.get("box"),
                canvas_w=canvas_w,
                canvas_h=canvas_h,
            )
            new_el = {
                "type": "image",
                "asset_id": asset_id,
                **coords,
            }

            # Insert after background but before other elements
            # Find the first non-image element as insertion point
            insert_idx = 0
            for i, e in enumerate(new_elements):
                if e.get("type") == "image":
                    insert_idx = i + 1
                else:
                    break
            # For overlay elements (rect with role=overlay), insert after those too
            for i in range(insert_idx, len(new_elements)):
                if (new_elements[i].get("type") == "rect" and
                        new_elements[i].get("role", "").startswith("overlay")):
                    insert_idx = i + 1
                else:
                    break

            new_elements.insert(insert_idx, new_el)

        new_slide["elements"] = new_elements
        modified["slides"].append(new_slide)

    return modified
