# Slide Renderer Architecture Specification

> Stability contract for the rendering pipeline.
> This system must remain deterministic and scalable to 100+ templates.

---

## 1. Rendering Pipeline Steps

The renderer follows a strict 8-phase pipeline. Each phase has exactly one responsibility,
takes immutable input, and produces a new output. No phase may skip or reorder.

```
Phase 1: LOAD          Load layout JSON + resolve variant
Phase 2: THEME         Load theme JSON + resolve inheritance chain + resolve tokens
Phase 3: PLACEMENT     Apply placement overrides → inject/modify image elements in layout
Phase 4: MERGE         Per-element: apply_theme() then apply_overrides() → resolved element
Phase 5: RESOLVE       Resolve asset_map (generated + user assets → PIL Images by slot ID)
Phase 6: RENDER        Per-slide, per-element: dispatch to typed renderer → composite onto canvas
Phase 7: EXPORT        Convert RGBA canvas → RGB PNG byte buffer per slide
Phase 8: UPLOAD        Upload PNG buffers to storage → return public URLs
```

**Invariant:** Phases 1-7 are pure functions of their inputs (no network, no DB, no LLM).
Phase 5 may perform network I/O (loading remote images) but is idempotent.
Phase 8 is the only write side-effect.

**Determinism guarantee:** Given identical `(template, theme, content, asset_map, overrides)`,
phases 1-7 produce byte-identical PNG output.

---

## 2. Data Structure for Layout Elements

Every element in a layout slide is a flat dict with a required `type` field.
All other fields are optional with well-defined defaults.

### 2.1 Base Element Schema

```python
ElementBase = {
    "type": str,                    # REQUIRED — one of ELEMENT_TYPES
    "x": int,                       # default: 0
    "y": int,                       # default: 0
    "content_key": str | None,      # default: element["type"] (e.g. "title" → content["title"])
}
```

### 2.2 Element Types (closed set)

| Type             | Geometry fields           | Style fields                                       | Content source              |
|------------------|---------------------------|----------------------------------------------------|-----------------------------|
| `image`          | x, y, width, height       | asset_id, anchor, box, fill                        | asset_map[asset_id]         |
| `rect`           | x, y, width, height       | color, radius, role                                | —                           |
| `title`          | x, y, max_width           | font, size, weight, color, align, line_gap         | content[content_key]        |
| `subtitle`       | x, y, max_width           | font, size, weight, color, align, line_gap         | content[content_key]        |
| `body`           | x, y, max_width           | font, size, weight, color, align, line_gap         | content[content_key]        |
| `bullet_list`    | x, y, max_width           | font, size, weight, color, indent, marker_size,    | content[content_key] (list) |
|                  |                           | marker_color, item_gap, line_gap                   |                             |
| `cta`            | x, y, max_width           | font, size, weight, color, align, line_gap,        | content[content_key]        |
|                  |                           | button_color, button_padding_x/y, button_radius    |                             |
| `slide_counter`  | x, y                      | font, size, color                                  | slide_number (injected)     |

**Rule:** No new element types may be added without updating the dispatcher, the theme
merge logic, and the validation schema. Adding a type is a breaking change.

### 2.3 Canonical Defaults

```python
ELEMENT_DEFAULTS = {
    "font": "Inter",
    "size": 36,
    "weight": 400,
    "color": "#ffffff",
    "align": "left",
    "line_gap": 10,
    "radius": 0,
    "indent": 30,
    "marker_size": 12,
    "item_gap": 16,
    "button_padding_x": 60,
    "button_padding_y": 30,
    "button_radius": 12,
}
```

Every renderer function must use these defaults, not ad-hoc magic numbers.

---

## 3. Slot Resolution Logic

"Slots" are the bridge between layout geometry and runtime content/assets.

### 3.1 Text Slots

Text elements declare which content they consume via `content_key`:

```json
{"type": "title", "content_key": "title", "x": 80, "y": 200, "max_width": 920}
```

Resolution: `content_key` → lookup in `content` dict → string or list[str].
If `content_key` is omitted, falls back to `element["type"]`.
If the key is missing from content, the element is skipped silently (no error, no placeholder).

### 3.2 Asset Slots

Image elements declare which asset they consume via `asset_id`:

```json
{"type": "image", "asset_id": "background_asset", "anchor": "full_bg"}
```

Resolution: `asset_id` → lookup in `asset_map` dict → PIL Image.
If the asset_id is missing from asset_map:
- If element has `fill` field → render a solid color overlay instead
- Otherwise → skip silently

### 3.3 Slot Contract

| Slot type | Source dict   | Missing behavior            |
|-----------|---------------|-----------------------------|
| text      | `content`     | Skip element                |
| asset     | `asset_map`   | Use `fill` fallback or skip |
| rect      | —             | Always renders (no slot)    |
| counter   | slide_number  | Always renders              |

---

## 4. Anchor Placement System

Anchors provide semantic, canvas-relative positioning without pixel coordinates.

### 4.1 Anchor Presets (closed set)

```
top_left      top_center      top_right
center_left   center          center_right
bottom_left   bottom_center   bottom_right
full_bg
```

### 4.2 Resolution Formula

```python
resolve_anchor(anchor, box, canvas_w, canvas_h) → {x, y, width, height}
```

Where `box = {width, height, margin_x, margin_y}`.

Each anchor is a pure function:
```
top_left:      (margin_x, margin_y)
top_center:    ((canvas_w - box_w) / 2, margin_y)
center:        ((canvas_w - box_w) / 2, (canvas_h - box_h) / 2)
full_bg:       (0, 0, canvas_w, canvas_h)  # ignores box dimensions
...
```

### 4.3 Anchor vs. Explicit Positioning

An image element uses **exactly one** positioning mode:

1. If `anchor` field is present → use `resolve_anchor()`
2. Else → use explicit `x`, `y`, `width`, `height`

Never mix both. The `anchor` field takes absolute precedence.

### 4.4 Placement Overrides

Placement overrides modify the layout **before** rendering (Phase 3).
They can:
- **Update** existing image elements (change anchor/box)
- **Inject** new image elements (for asset_ids not in the layout)
- **Remove** image elements from specific slides (via `slides` targeting)

```python
placement_overrides = {
    "logo_asset": {
        "anchor": "top_left",
        "box": {"width": 160, "height": 80, "margin_x": 40, "margin_y": 40},
        "slides": ["cover", "cta"]   # only show logo on these slides
    }
}
```

**Injection z-order:** New elements are inserted after all existing `image` elements
and any `rect` elements with overlay roles, but before text elements.
This ensures assets layer correctly: background → overlay → injected asset → text.

---

## 5. Theme Merge Strategy

### 5.1 Theme Structure

```python
Theme = {
    "id": str,
    "name": str,
    "extends": str | None,         # parent theme ID (max 5 levels)
    "canvas": {"background": str}, # canvas background color
    "fonts":   {etype: str},       # font family per element type
    "sizes":   {etype: int},       # font size per element type
    "weights": {etype: int},       # font weight per element type
    "colors":  {key: str},         # colors by element type + role names
    "button":  {str: int},         # CTA button styling
}
```

### 5.2 Inheritance Resolution

```
1. Walk chain: theme → extends → extends → ... (max 5, circular = stop)
2. Reverse the chain (base first)
3. Deep-merge each layer (child wins on conflict)
4. Resolve token references ("typography.h1" → 72)
```

### 5.3 Token References

Strings in format `"namespace.key"` are resolved against `/templates/tokens/`:
```
"typography.h1"  → tokens["typography"]["h1"]  → 72
"colors.gold"    → tokens["colors"]["gold"]    → "#d4af37"
"spacing.xl"     → tokens["spacing"]["xl"]     → 40
```

Unresolved references are kept as-is (no error). This is safe because
unresolved strings will either be used as literal text or fail gracefully
in `_parse_color` / `_resolve_font`.

### 5.4 Element-Theme Merge Rules

```python
def apply_theme(element, theme) → merged_element:
    # Text elements (title, subtitle, body, cta, bullet_list, slide_counter):
    #   font   ← theme.fonts[etype]       IF element lacks "font"
    #   size   ← theme.sizes[etype]       IF element lacks "size"
    #   weight ← theme.weights[etype]     IF element lacks "weight"
    #   color  ← theme.colors[etype]      IF element lacks "color"
    #
    # Rect elements:
    #   color  ← theme.colors[role]       IF element lacks "color" AND has "role"
    #
    # CTA extras:
    #   button_color     ← theme.colors.button
    #   button_padding_x ← theme.button.padding_x
    #   button_padding_y ← theme.button.padding_y
    #   button_radius    ← theme.button.radius
    #
    # bullet_list extras:
    #   marker_color     ← theme.colors.marker
```

**Critical rule:** Theme only fills MISSING properties. If the layout element
already specifies a value, the theme does NOT override it. This guarantees
layout-specific styling survives theming.

---

## 6. Asset Injection

### 6.1 Asset Map Construction

The `asset_map` is a `dict[str, PIL.Image]` built before rendering:

```
Source priority (highest wins):
  1. user_asset_mapping  — user-uploaded assets mapped to slot names
  2. asset_mapping       — explicit index mapping to generated assets
  3. Default             — generated_assets[selected_index] → "background_asset"
```

### 6.2 Asset Loading

```python
load_asset_image(source: str | bytes) → PIL.Image
```

Accepts: URL (http/https), file path, or raw bytes.
Always returns RGBA-capable PIL Image.
Failures raise — caller must handle (log + skip).

### 6.3 Asset Rendering

When an image element is rendered:
1. Look up `asset_map[asset_id]`
2. Resolve position (anchor or explicit x/y)
3. Resize asset to target (width, height) using LANCZOS
4. Alpha-composite onto canvas at (x, y)

Alpha compositing is used instead of paste to preserve transparency layers.

---

## 7. Override Priority System

Three-layer merge with strict precedence:

```
Layout element (lowest)  →  Theme  →  User overrides (highest)
```

### 7.1 Merge Execution Order

```python
# Per element, in this exact order:
element = layout_element              # raw from JSON
element = apply_theme(element, theme) # theme fills gaps
element = apply_overrides(element, overrides)  # overrides win
```

### 7.2 Override Key Format

```
{element_type}_{property}
```

Examples:
```python
overrides = {
    "title_font": "Montserrat",       # title elements → font
    "title_color": "#FFD700",          # title elements → color
    "title_size": 64,                  # title elements → size
    "subtitle_color": "#CCCCCC",
    "accent_color": "#FF0000",         # rect[role=accent] → color
    "bullet_list_marker_color": "#FF0",
    "cta_button_color": "#00FF00",
}
```

### 7.3 Override Scope

Overrides are **global across all slides**. There is no per-slide override
mechanism at the override layer. Per-slide differentiation is handled by:
- Different element lists per slide in the layout
- Placement overrides with `slides` targeting (Phase 3, before merge)

### 7.4 Complete Priority Table

| Property       | Layout | Theme              | Override key                |
|----------------|--------|--------------------|-----------------------------|
| font           | ✓      | theme.fonts[type]  | `{type}_font`               |
| size           | ✓      | theme.sizes[type]  | `{type}_size`               |
| weight         | ✓      | theme.weights[type]| `{type}_weight`             |
| color (text)   | ✓      | theme.colors[type] | `{type}_color`              |
| color (rect)   | ✓      | theme.colors[role] | `accent_color` (accent only)|
| marker_color   | ✓      | theme.colors.marker| `bullet_list_marker_color`  |
| button_color   | ✓      | theme.colors.button| `cta_button_color`          |
| button_padding | ✓      | theme.button.*     | —                           |
| button_radius  | ✓      | theme.button.*     | —                           |
| x, y, width, height | ✓ | —                 | —                           |
| anchor, box    | ✓      | —                  | via placement_overrides     |
| asset_id       | ✓      | —                  | via placement_overrides     |

---

## 8. Slide-Specific Logic

### 8.1 Slide Definition

Each slide in a layout has:
```python
{
    "name": str,          # Unique identifier: "cover", "text", "list", "cta"
    "elements": list[dict] # Ordered element list (z-order = array order)
}
```

### 8.2 Z-Order Contract

Elements render in array order. Index 0 is the bottommost layer.
After each element render, `ImageDraw` is recreated to ensure alpha
compositing from image elements is properly reflected in subsequent draws.

Typical z-order pattern:
```
0: image (background_asset, full_bg)
1: rect  (overlay, semi-transparent)
2: rect  (accent line)
3: image (logo, anchored)
4: title
5: subtitle / body / bullet_list
6: cta
7: slide_counter
```

### 8.3 Slide Numbering

`slide_counter` elements receive `slide_number = idx + 1` (1-based).
The slide number is injected at render time, not stored in content.

### 8.4 Canvas Background Resolution

```
1. template.canvas.background  (if present, use it)
2. theme.canvas.background     (if template doesn't specify)
3. "#111111"                   (hard default)
```

Theme background only applies when the layout canvas omits `background`.
This prevents themes from overriding layout-specific backgrounds.

### 8.5 Per-Slide Content Sharing

All slides share the same `content` dict. Different slides access different
keys through their elements' `content_key` fields:
- Cover slide elements: `content_key: "title"`, `content_key: "subtitle"`
- List slide elements: `content_key: "bullets"`
- CTA slide elements: `content_key: "cta"`

---

## 9. Error Handling

### 9.1 Fail-Safe Philosophy

The renderer **never crashes** on bad input. It degrades gracefully:

| Failure                        | Behavior                           |
|--------------------------------|------------------------------------|
| Unknown element type           | Log warning, skip element          |
| Missing content key            | Skip text element (no render)      |
| Missing asset in asset_map     | Use fill fallback or skip          |
| Invalid color string           | Default to `(255, 255, 255, 255)`  |
| Font not found                 | Fall back to Inter → PIL default   |
| Invalid anchor name            | Default to `center`                |
| Theme not found                | Render without theme (layout-only) |
| Theme circular inheritance     | Stop chain, log warning            |
| Token reference unresolved     | Keep string as-is                  |
| Asset image load failure       | Log warning, skip slot             |
| Placement override for unknown slide | Skip override for that slide  |

### 9.2 Error Boundaries

```
Phase 1 (LOAD):      ValueError if template/variant not found → caller handles
Phase 2 (THEME):     ValueError if theme not found → caller catches, theme=None
Phase 3 (PLACEMENT): Never fails (graceful skip on unknown slides)
Phase 4 (MERGE):     Never fails (missing = use defaults)
Phase 5 (RESOLVE):   Per-asset try/except → log + skip
Phase 6 (RENDER):    Per-element try/except → log + skip (NOT per-slide)
Phase 7 (EXPORT):    PIL save — should not fail on valid RGBA
Phase 8 (UPLOAD):    Network error → propagate to caller
```

### 9.3 Logging Contract

All warnings use the `[renderer]`, `[theme]`, `[placement]`, or `[carousel]`
prefixes for filterability. Debug-level logs for each element render.
Info-level for slide completion with byte count.

---

## 10. Validation Rules

### 10.1 Template Validation (at load time)

```python
def validate_template(template: dict) → list[str]:  # returns list of warnings
    # MUST have: canvas dict with width/height
    # MUST have: slides list with ≥ 1 entry
    # Each slide MUST have: name (unique), elements list
    # Each element MUST have: type in ELEMENT_TYPES
    # Image elements MUST have: asset_id OR (x + y + width + height) OR anchor
    # Text elements MUST have: x, y
    # Rect elements MUST have: x, y, width, height
    # No duplicate slide names
    # No unknown keys (warn but don't reject — forward compatibility)
```

### 10.2 Theme Validation (at load time)

```python
def validate_theme(theme: dict) → list[str]:
    # MUST have: id
    # fonts values: must be strings
    # sizes values: must be positive integers
    # weights values: must be integers 100-900
    # colors values: must be valid hex colors (#RGB, #RRGGBB, #RRGGBBAA)
    # extends: must reference a valid theme ID (or be absent)
    # Inheritance depth: max 5
```

### 10.3 Content Validation (before render)

```python
def validate_content(content: dict) → dict:
    # title: string, max 200 chars (truncate with "…")
    # subtitle: string, max 300 chars
    # body: string, max 1000 chars
    # bullets: list of strings, max 8 items, each max 200 chars
    # cta: string, max 100 chars
    # Unknown keys: ignored (forward compatible)
```

### 10.4 Color Validation

```python
def _parse_color(color_str: str) → tuple[int, int, int, int]:
    # Accept: #RGB, #RRGGBB, #RRGGBBAA
    # Reject: anything else → (255, 255, 255, 255)
    # No CSS functions (rgb(), hsl()) in Pillow renderer
    # No injection vectors (no ";", no "}", no "url()")
```

### 10.5 Registry Validation

The registry (`templates/registry.json`) is the source of truth for
valid template+variant+theme combinations:

```python
def validate_registry_entry(layout_id: str, meta: dict):
    # variants: each must have a corresponding .json file
    # default_theme: must exist in themes/
    # themes: each must exist in themes/
```

### 10.6 Scalability Contract

For 100+ templates:
- Template loading is O(1) — direct file read by ID
- Theme loading is O(depth) where depth ≤ 5 — bounded
- Token resolution is O(keys) per theme — cached after first load
- Registry scan is O(n) but cached — only on list_templates()
- Rendering is O(slides × elements) — bounded by template definition
- No global state mutation during rendering — thread-safe
- Font cache is process-global — amortized O(1) after warmup

---

## Appendix A: File Map

```
services/
├── slide_renderer.py          # Phase 4-7: merge + render + export
├── asset_placement.py         # Phase 3: anchor resolution + placement overrides
├── carousel_pipeline.py       # Orchestrator: Phase 1-2 + asset generation + Phase 8
├── design_planner.py          # Pre-pipeline: LLM classification + rule engine
├── asset_command_interpreter.py  # NL → placement_overrides
├── asset_storage.py           # Asset generation + Supabase upload
├── user_assets.py             # User asset CRUD
└── template_renderer.py       # Alternative HTML renderer (separate system)

templates/
├── registry.json              # Source of truth for valid combinations
├── layouts/{id}/{variant}.json # Layout definitions
├── themes/{id}.json           # Theme definitions
└── tokens/{namespace}.json    # Design tokens
```

## Appendix B: Adding a New Template (Checklist)

1. Create `templates/layouts/{new_id}/{variant}.json`
2. Define canvas, slides array with named slides, elements per slide
3. Add entry to `templates/registry.json` with variants, default_theme, themes
4. Run `validate_template()` on the new layout
5. Test with each compatible theme from the registry entry
6. No code changes required — the renderer is fully data-driven

## Appendix C: Adding a New Theme (Checklist)

1. Create `templates/themes/{new_id}.json`
2. Define id, name, fonts, sizes, weights, colors, button, canvas
3. Optionally set `extends` to inherit from an existing theme
4. Add theme ID to relevant `themes` arrays in `registry.json`
5. Run `validate_theme()` on the new theme
6. No code changes required — themes are pure data

## Appendix D: Anti-Patterns (Do NOT)

- Do NOT add conditional logic inside element renderers based on template name
- Do NOT hard-code pixel values — use layout JSON for geometry, theme for style
- Do NOT access global state during rendering — all inputs passed as arguments
- Do NOT add new element types without updating the full stack (dispatcher + theme merge + validation)
- Do NOT allow themes to override geometry (x, y, width, height) — themes are style-only
- Do NOT add per-slide overrides at the override layer — use layout differentiation instead
- Do NOT resolve anchors during merge — anchors are resolved only in the image renderer
- Do NOT cache rendered images — rendering is fast and deterministic; cache at the upload layer
