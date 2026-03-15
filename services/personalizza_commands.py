"""Personalizza command layer — structured command parsing + mode detection.

Translates user chat messages into deterministic structured commands,
and detects whether the request is ASSET MODE or DESIGN MODE.

ASSET MODE: keep template/layout/theme unchanged, only update asset
mappings, placement overrides, and asset generation.

DESIGN MODE: allow the LLM to modify the full design_spec.

Usage::

    from services.personalizza_commands import parse_message, CommandMode

    result = parse_message(
        message="metti il logo in alto a sinistra e genera una cucina moderna come sfondo",
        uploaded_image_urls=["https://...logo.png"],
        user_assets=[{"id": "abc", "type": "logo", "url": "https://..."}],
    )
    # result.mode == CommandMode.ASSET
    # result.commands == [
    #     {"type": "assign_uploaded_asset", "slot": "logo_asset", ...},
    #     {"type": "placement_override", "slot": "logo_asset", "anchor": "top_left", ...},
    #     {"type": "generate_asset", "slot": "background_asset", "prompt": "..."},
    # ]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode enum
# ---------------------------------------------------------------------------

class CommandMode(Enum):
    ASSET = "asset"
    DESIGN = "design"
    MIXED = "mixed"   # has both asset and design intent


# ---------------------------------------------------------------------------
# Command types
# ---------------------------------------------------------------------------

COMMAND_TYPES = frozenset({
    "generate_asset",
    "assign_uploaded_asset",
    "remove_asset",
    "placement_override",
    "slide_scope_override",
})


# ---------------------------------------------------------------------------
# Slot types — strict separation
# ---------------------------------------------------------------------------

SLOT_TYPES = {
    "background_asset": {"role": "background", "max_width": None, "max_height": None, "preserve_ratio": False},
    "logo_asset":       {"role": "logo",       "max_width": 200,  "max_height": 200,  "preserve_ratio": True},
    "product_asset":    {"role": "product",     "max_width": 600,  "max_height": 600,  "preserve_ratio": True},
    "secondary_asset":  {"role": "secondary",   "max_width": 600,  "max_height": 600,  "preserve_ratio": True},
}

# Default boxes per slot (aspect-ratio-safe)
SLOT_DEFAULT_BOXES = {
    "logo_asset":      {"width": 120, "height": 120, "margin_x": 32, "margin_y": 32},
    "product_asset":   {"width": 480, "height": 480, "margin_x": 40, "margin_y": 40},
    "secondary_asset": {"width": 400, "height": 400, "margin_x": 40, "margin_y": 40},
    # background_asset uses full_bg — no box needed
}

# Default anchors when not specified
SLOT_DEFAULT_ANCHORS = {
    "logo_asset": "top_left",
    "product_asset": "center",
    "secondary_asset": "center",
    "background_asset": "full_bg",
}


# ---------------------------------------------------------------------------
# Detection patterns (Italian + English)
# ---------------------------------------------------------------------------

# Asset-related keywords (trigger ASSET MODE)
_ASSET_KEYWORDS = [
    # Logo
    r"\blogo\b",
    # Background/image
    r"\bsfondo\b", r"\bbackground\b", r"\btexture\b", r"\btrama\b",
    # Placement
    r"\bmetti\b", r"\bposiziona\b", r"\bsposta\b", r"\bmuovi\b",
    r"\bplace\b", r"\bmove\b", r"\bput\b",
    # Generation
    r"\bgenera\s+(un[a']?\s+)?immag", r"\bcrea\s+(un[a']?\s+)?immag",
    r"\bgenerate\s+image\b", r"\bcreate\s+image\b",
    # Assignment
    r"\busa\s+(quest[ao]|il|la|l')\s+(immag|logo|foto|sfond)",
    r"\buse\s+(this|the)\s+(image|logo|photo|background)",
    # Removal
    r"\brimuovi\b", r"\btogli\b", r"\belimina\b", r"\bnon\s+usare\b",
    r"\bremove\b", r"\bdelete\b", r"\bdon't\s+use\b",
    # Image references
    r"\bimmag(ine|ini)\b", r"\bfoto\b", r"\bphoto\b",
    r"\bprodott[oi]\b", r"\bproduct\b",
    # Specific assets
    r"\bcucina\b", r"\bkitchen\b", r"\bmarmo\b", r"\bmarble\b",
    r"\blegno\b", r"\bwood\b", r"\bcemento\b", r"\bconcrete\b",
    r"\bfiori\b", r"\bflowers\b", r"\bvini?\b", r"\bwine\b",
    # Slide targeting for assets
    r"\bsu\s+tutt[eio]\s+le\s+slide\b", r"\bon\s+all\s+slides\b",
    r"\bsolo\s+(nella|sulla|sul|su)\b",
]

# Design-change keywords (trigger DESIGN MODE)
_DESIGN_KEYWORDS = [
    r"\bfont\b", r"\bcolore?\b", r"\bcolors?\b",
    r"\btema\b", r"\btheme\b",
    r"\blayout\b", r"\bstile\b", r"\bstyle\b",
    r"\bgradiente?\b", r"\bgradient\b",
    r"\bpadding\b", r"\bspaziatura\b", r"\bspacing\b",
    r"\bdimensione\b", r"\bsize\b",
    r"\bgrassett[oa]\b", r"\bbold\b",
    r"\bcambia\s+(il\s+)?(font|colore|tema|layout|stile)",
    r"\bchange\s+(the\s+)?(font|color|theme|layout|style)",
    r"\brendi\s+(più|piu)\b", r"\bmake\s+(it\s+)?(more|less)\b",
    r"\bminimal\w*\b", r"\belegant\w*\b", r"\bmodern\w*\b",
    r"\bluxury\b", r"\blusso\b",
    r"\bpiù\s+(scuro|chiaro|grande|piccolo|grassetto|leggero)",
    r"\bdarker\b", r"\blighter\b", r"\bbigger\b", r"\bsmaller\b",
    r"\borb\b", r"\bcounter\b", r"\bfooter\b", r"\bbrand\b",
    r"\baccent\b", r"\baccento\b",
    r"\barrotonda\b", r"\brounded\b", r"\bradius\b",
]

# Compiled for performance
_ASSET_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _ASSET_KEYWORDS]
_DESIGN_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _DESIGN_KEYWORDS]


# Position detection (reuse from asset_command_interpreter)
_POSITION_MAP: list[tuple[str, str]] = [
    (r"in alto a sinistra|top.?left", "top_left"),
    (r"in alto a destra|top.?right", "top_right"),
    (r"in alto al centro|in alto|top.?center|at the top", "top_center"),
    (r"in basso a sinistra|bottom.?left", "bottom_left"),
    (r"in basso a destra|bottom.?right", "bottom_right"),
    (r"in basso al centro|in basso|bottom.?center|at the bottom", "bottom_center"),
    (r"al centro a sinistra|a sinistra|center.?left|on the left", "center_left"),
    (r"al centro a destra|a destra|center.?right|on the right", "center_right"),
    (r"al centro|centro|in the center|centered|at center", "center"),
    (r"come sfondo|sfondo intero|background intero|full.?background|as background", "full_bg"),
]

# Slot detection
_SLOT_PATTERNS: list[tuple[str, str]] = [
    (r"\blogo\b", "logo_asset"),
    (r"\bprodott[oi]\b|\bproduct\b", "product_asset"),
    (r"\bsfondo\b|\bbackground\b|\btexture\b|\btrama\b", "background_asset"),
    (r"\bfoto\b|\bphoto\b|\bimmag(?:ine|ini)\b|\bimage\b", "secondary_asset"),
]

# Slide targeting
_SLIDE_MAP: list[tuple[str, str]] = [
    (r"\bcover\b|\bcopertina\b|\bprima\s+slide\b", "cover"),
    (r"\bcta\b|\bcall.?to.?action\b|\bultima\s+slide\b", "cta"),
    (r"\btext\b|\btesto\b|\bcontenut[oi]\b", "text"),
    (r"\blist\b|\blista\b|\belenco\b|\bbullet\b", "list"),
]

# Generation intent
_GENERATION_PATTERNS = [
    re.compile(r"\bgenera\b|\bcrea\b|\bgenerate\b|\bcreate\b", re.IGNORECASE),
    re.compile(r"\bmetti\s+un[a']?\s+\w+\s+come\s+(sfond|background)", re.IGNORECASE),
    re.compile(r"\busa\s+un[a']?\s+\w+\s+come\s+(sfond|background)", re.IGNORECASE),
    re.compile(r"\b(cucina|kitchen|marmo|marble|legno|wood|cemento|concrete|fiori|flowers|vini?|wine|ufficio|office|mare|sea|montagna|mountain|cielo|sky|natura|nature)\b", re.IGNORECASE),
]

# Removal intent
_REMOVAL_PATTERNS = [
    re.compile(r"\brimuovi\b|\btogli\b|\belimina\b", re.IGNORECASE),
    re.compile(r"\bnon\s+usare\b|\bnon\s+mettere\b", re.IGNORECASE),
    re.compile(r"\bremove\b|\bdelete\b|\bdon't\s+use\b", re.IGNORECASE),
]

# Assignment via uploaded image
_ASSIGNMENT_PATTERNS = [
    re.compile(r"\busa\s+(quest[ao]|l'|il|la)\b", re.IGNORECASE),
    re.compile(r"\buse\s+(this|the)\b", re.IGNORECASE),
    re.compile(r"\bcome\s+(logo|sfond|background|prodott)", re.IGNORECASE),
    re.compile(r"\bas\s+(logo|background|product)\b", re.IGNORECASE),
]

# All-slides pattern
_ALL_SLIDES_PATTERN = re.compile(
    r"\btutt[eio]\s+(le\s+)?slide\b|\ball\s+slides?\b|\bogni\s+slide\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    """Result of parsing a Personalizza message."""
    mode: CommandMode
    commands: list[dict] = field(default_factory=list)
    asset_score: int = 0
    design_score: int = 0
    debug: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

def detect_mode(message: str) -> tuple[CommandMode, int, int]:
    """Detect whether a message is ASSET MODE or DESIGN MODE.

    Returns (mode, asset_score, design_score).
    """
    lower = message.lower()

    asset_score = sum(1 for p in _ASSET_PATTERNS if p.search(lower))
    design_score = sum(1 for p in _DESIGN_PATTERNS if p.search(lower))

    log.info("[personalizza] mode detection: asset_score=%d, design_score=%d",
             asset_score, design_score)

    if asset_score > 0 and design_score == 0:
        return CommandMode.ASSET, asset_score, design_score
    if design_score > 0 and asset_score == 0:
        return CommandMode.DESIGN, asset_score, design_score
    if asset_score > 0 and design_score > 0:
        # If asset signals dominate, still use ASSET mode
        if asset_score >= design_score * 2:
            return CommandMode.ASSET, asset_score, design_score
        return CommandMode.MIXED, asset_score, design_score

    # No strong signal → default to DESIGN (let LLM handle it)
    return CommandMode.DESIGN, asset_score, design_score


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _detect_position(text: str) -> str | None:
    lower = text.lower()
    for pattern, anchor in _POSITION_MAP:
        if re.search(pattern, lower):
            return anchor
    return None


def _detect_slot(text: str) -> str | None:
    lower = text.lower()
    for pattern, slot in _SLOT_PATTERNS:
        if re.search(pattern, lower):
            return slot
    return None


def _detect_slides(text: str) -> list[str] | None:
    """Detect targeted slides. Returns None for 'all slides'."""
    lower = text.lower()

    if _ALL_SLIDES_PATTERN.search(lower):
        return None  # all slides

    slides = []
    for pattern, slide_name in _SLIDE_MAP:
        if re.search(pattern, lower):
            slides.append(slide_name)

    return slides if slides else None


def _has_generation_intent(text: str) -> bool:
    return any(p.search(text) for p in _GENERATION_PATTERNS)


def _has_removal_intent(text: str) -> bool:
    return any(p.search(text) for p in _REMOVAL_PATTERNS)


def _has_assignment_intent(text: str) -> bool:
    return any(p.search(text) for p in _ASSIGNMENT_PATTERNS)


def _extract_generation_subject(message: str) -> str:
    """Extract the subject the user wants generated from their message.

    Returns the raw descriptive text (will be refined by the image prompt planner).
    """
    lower = message.lower()

    # Remove command verbs and filler to isolate the subject
    cleaned = re.sub(
        r"\b(metti|usa|genera|crea|aggiungi|posiziona|place|put|use|generate|create|add)\b",
        "", lower,
    )
    cleaned = re.sub(
        r"\b(un[a']?|il|la|lo|le|gli|i|del|della|delle|dei|degli|come|per|su|in|the|a|an|as|for|on)\b",
        "", cleaned,
    )
    cleaned = re.sub(
        r"\b(sfondo|background|immagine|image|foto|photo|slide|tutt[eio])\b",
        "", cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned if cleaned else message.strip()


def _find_uploaded_asset_for_slot(
    slot: str,
    uploaded_image_urls: list[str],
    user_assets: list[dict],
    already_assigned: set[str],
) -> tuple[str | None, str | None]:
    """Find the best uploaded asset for a slot.

    Returns (asset_id, url) or (None, None).
    """
    slot_type = slot.replace("_asset", "")

    # First: match user_assets by type
    for asset in user_assets:
        aid = asset.get("id", "")
        if aid in already_assigned:
            continue
        if asset.get("type") == slot_type:
            return aid, asset.get("url")

    # Second: if there are uploaded images not yet assigned, use the first one
    for url in uploaded_image_urls:
        if url not in already_assigned:
            return None, url  # No asset_id, just a URL

    # Third: any unused user asset
    for asset in user_assets:
        aid = asset.get("id", "")
        if aid not in already_assigned:
            return aid, asset.get("url")

    return None, None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_message(
    message: str,
    uploaded_image_urls: list[str] | None = None,
    user_assets: list[dict] | None = None,
) -> ParseResult:
    """Parse a Personalizza message into structured commands.

    Args:
        message: User's chat message.
        uploaded_image_urls: URLs of images uploaded with this message.
        user_assets: User's stored assets (from user_assets table).

    Returns:
        ParseResult with mode and commands list.
    """
    uploaded_image_urls = uploaded_image_urls or []
    user_assets = user_assets or []

    mode, asset_score, design_score = detect_mode(message)
    commands: list[dict] = []
    assigned: set[str] = set()

    log.info("[personalizza] parsing: mode=%s, message=%r", mode.value, message[:100])

    if mode in (CommandMode.ASSET, CommandMode.MIXED):
        # Parse asset commands from the message
        slot = _detect_slot(message)
        anchor = _detect_position(message)
        target_slides = _detect_slides(message)
        has_gen = _has_generation_intent(message)
        has_remove = _has_removal_intent(message)
        has_assign = _has_assignment_intent(message)

        log.info(
            "[personalizza] parsed: slot=%s, anchor=%s, slides=%s, "
            "gen=%s, remove=%s, assign=%s",
            slot, anchor, target_slides, has_gen, has_remove, has_assign,
        )

        # Infer slot from context if not explicit
        if not slot:
            if uploaded_image_urls:
                # If user uploaded something, guess from assignment context
                if has_assign and re.search(r"\blogo\b", message, re.IGNORECASE):
                    slot = "logo_asset"
                elif has_assign and re.search(r"\bsfond|background", message, re.IGNORECASE):
                    slot = "background_asset"
                else:
                    slot = "secondary_asset"
            elif has_gen:
                # Generating something — likely background unless specified
                slot = "background_asset"

        if not slot:
            # Can't determine what to do — fall through to DESIGN mode
            log.info("[personalizza] no slot detected, falling back to DESIGN mode")
            mode = CommandMode.DESIGN
        else:
            # ── Removal commands ──
            if has_remove:
                commands.append({
                    "type": "remove_asset",
                    "slot": slot,
                    "slides": target_slides,
                })

            # ── Assignment commands (user uploaded image) ──
            elif (has_assign or uploaded_image_urls) and not has_gen:
                asset_id, url = _find_uploaded_asset_for_slot(
                    slot, uploaded_image_urls, user_assets, assigned,
                )
                if url:
                    commands.append({
                        "type": "assign_uploaded_asset",
                        "slot": slot,
                        "asset_id": asset_id,
                        "url": url,
                    })
                    if asset_id:
                        assigned.add(asset_id)
                    else:
                        assigned.add(url)
                elif not uploaded_image_urls:
                    # Assignment words but no images available → treat as generation
                    subject = _extract_generation_subject(message)
                    commands.append({
                        "type": "generate_asset",
                        "slot": slot,
                        "prompt": subject,
                    })

            # ── Generation commands ──
            elif has_gen or (slot == "background_asset" and not uploaded_image_urls):
                subject = _extract_generation_subject(message)
                commands.append({
                    "type": "generate_asset",
                    "slot": slot,
                    "prompt": subject,
                })

            # ── Placement override ──
            if anchor and slot:
                default_box = SLOT_DEFAULT_BOXES.get(slot)
                cmd: dict = {
                    "type": "placement_override",
                    "slot": slot,
                    "anchor": anchor,
                }
                if default_box and anchor != "full_bg":
                    cmd["box"] = dict(default_box)
                if target_slides:
                    cmd["slides"] = target_slides
                commands.append(cmd)
            elif slot and slot != "background_asset":
                # No explicit position → apply default anchor for the slot type
                default_anchor = SLOT_DEFAULT_ANCHORS.get(slot, "center")
                default_box = SLOT_DEFAULT_BOXES.get(slot)
                cmd = {
                    "type": "placement_override",
                    "slot": slot,
                    "anchor": default_anchor,
                }
                if default_box:
                    cmd["box"] = dict(default_box)
                if target_slides:
                    cmd["slides"] = target_slides
                commands.append(cmd)

    result = ParseResult(
        mode=mode,
        commands=commands,
        asset_score=asset_score,
        design_score=design_score,
        debug={
            "detected_slot": _detect_slot(message),
            "detected_anchor": _detect_position(message),
            "detected_slides": _detect_slides(message),
            "has_generation": _has_generation_intent(message),
            "has_removal": _has_removal_intent(message),
            "has_assignment": _has_assignment_intent(message),
        },
    )

    log.info(
        "[personalizza] result: mode=%s, commands=%d, types=%s",
        result.mode.value,
        len(result.commands),
        [c["type"] for c in result.commands],
    )

    return result


# ---------------------------------------------------------------------------
# Command executor — applies commands to a design_spec
# ---------------------------------------------------------------------------

def execute_asset_commands(
    commands: list[dict],
    design_spec: dict,
    user_id: str,
    template_id: str,
) -> dict:
    """Execute structured asset commands against a design_spec.

    Returns a dict with:
        - design_spec: the updated design_spec (may have new image URLs)
        - generated: list of generated asset results
        - errors: list of error messages for failed commands
        - changes: list of human-readable descriptions of what changed

    The caller (template_chat) is responsible for persisting the updated spec.
    """
    result = {
        "design_spec": dict(design_spec),
        "generated": [],
        "errors": [],
        "changes": [],
    }

    # Deep copy images section to avoid mutating the input
    images = dict(result["design_spec"].get("images", {}))
    slide_images = dict(images.get("slide_images", {}))
    images["slide_images"] = slide_images
    result["design_spec"]["images"] = images

    for cmd in commands:
        cmd_type = cmd.get("type")
        slot = cmd.get("slot", "")

        log.info("[personalizza] executing: type=%s, slot=%s", cmd_type, slot)

        if cmd_type == "generate_asset":
            _exec_generate(cmd, result, user_id, template_id)

        elif cmd_type == "assign_uploaded_asset":
            _exec_assign(cmd, result)

        elif cmd_type == "remove_asset":
            _exec_remove(cmd, result)

        elif cmd_type == "placement_override":
            # Placement overrides are handled by the caller when rendering
            # We just log them
            result["changes"].append(
                f"Posizionamento {slot}: anchor={cmd.get('anchor')}, "
                f"slides={cmd.get('slides', 'tutte')}"
            )

        else:
            log.warning("[personalizza] unknown command type: %s", cmd_type)

    return result


def _exec_generate(cmd: dict, result: dict, user_id: str, template_id: str) -> None:
    """Execute a generate_asset command."""
    slot = cmd["slot"]
    prompt = cmd.get("prompt", "")

    log.info("[personalizza] generating asset: slot=%s, prompt=%r", slot, prompt[:100])

    try:
        from services.image_generator import generate_image

        # Determine target from slot
        target = "cover" if slot == "secondary_asset" else "background"

        # Build a proper image prompt using the planner
        # (import here to avoid circular imports with app.py)
        img_result = generate_image(
            prompt=prompt,
            user_id=user_id,
            template_id=template_id,
            target=target,
        )

        url = img_result["url"]
        log.info("[personalizza] generated: slot=%s → url=%s", slot, url[:80])

        # Map slot to design_spec field
        _set_image_url(result["design_spec"], slot, url)
        result["generated"].append({"slot": slot, "url": url})
        result["changes"].append(f"Immagine generata per {slot}")

    except Exception as exc:
        error_msg = f"Generazione immagine fallita per {slot}: {exc}"
        log.error("[personalizza] %s", error_msg)
        result["errors"].append(error_msg)


def _exec_assign(cmd: dict, result: dict) -> None:
    """Execute an assign_uploaded_asset command."""
    slot = cmd["slot"]
    url = cmd.get("url", "")

    if not url:
        result["errors"].append(f"Nessun URL disponibile per {slot}")
        return

    log.info("[personalizza] assigning: slot=%s → url=%s", slot, url[:80])
    _set_image_url(result["design_spec"], slot, url)
    result["changes"].append(f"Asset assegnato a {slot}")


def _exec_remove(cmd: dict, result: dict) -> None:
    """Execute a remove_asset command."""
    slot = cmd["slot"]
    log.info("[personalizza] removing: slot=%s", slot)
    _set_image_url(result["design_spec"], slot, "")
    result["changes"].append(f"Asset rimosso da {slot}")


def _set_image_url(design_spec: dict, slot: str, url: str) -> None:
    """Set an image URL in the design_spec based on slot name."""
    images = design_spec.setdefault("images", {})
    slide_images = images.setdefault("slide_images", {})

    if slot == "background_asset":
        images["background_image_url"] = url
    elif slot == "logo_asset":
        images["logo_url"] = url
    elif slot == "product_asset":
        slide_images["cover"] = url
    elif slot == "secondary_asset":
        slide_images["cover"] = url
    else:
        # Unknown slot → background as fallback
        log.warning("[personalizza] unknown slot %r, using background_image_url", slot)
        images["background_image_url"] = url
