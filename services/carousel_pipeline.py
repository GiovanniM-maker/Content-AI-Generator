"""Carousel generation pipeline — layout + theme + content + assets.

Orchestrates the full flow:
  1. LLM generates structured content (title, subtitle, bullets, cta)
  2. LLM generates 2-3 image prompts from the user prompt
  3. Image model generates assets
  4. Assets are stored in Supabase
  5. Renderer composes slides using layout + theme + content + asset
  6. Slides exported as PNG and uploaded to Supabase

Template registry
-----------------
Layouts live in ``templates/layouts/{layout_name}/{variant}.json``.
Themes live in ``templates/themes/{theme_id}.json``.
Legacy flat files (``templates/layouts/{name}.json``) are also supported
for backward compatibility.

Usage::

    from services.carousel_pipeline import generate_instagram_carousel

    result = generate_instagram_carousel(
        prompt="5 strategie per aumentare le vendite online",
        user_id="abc123",
        template_id="minimal_layout",
        variant="center",
        theme_id="industrial_dark",
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

import requests as http_requests

import db as _db
from services.asset_storage import generate_assets_batch
from services.slide_renderer import render_slides, load_asset_image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_CONTENT = os.getenv("CAROUSEL_LLM_MODEL", "google/gemini-2.5-flash")

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LAYOUTS_DIR = os.path.join(_BASE_DIR, "templates", "layouts")
THEMES_DIR = os.path.join(_BASE_DIR, "templates", "themes")
TOKENS_DIR = os.path.join(_BASE_DIR, "templates", "tokens")
REGISTRY_PATH = os.path.join(_BASE_DIR, "templates", "registry.json")


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

_tokens_cache: dict[str, dict] | None = None


def _load_tokens() -> dict[str, dict]:
    """Load all token files from templates/tokens/ into a flat namespace.

    Token files are keyed by filename (without extension).
    Example: ``typography.json`` → accessible as ``typography.h1``.
    """
    global _tokens_cache
    if _tokens_cache is not None:
        return _tokens_cache

    _tokens_cache = {}
    if not os.path.isdir(TOKENS_DIR):
        return _tokens_cache

    for fname in os.listdir(TOKENS_DIR):
        if not fname.endswith(".json"):
            continue
        ns = fname.replace(".json", "")
        with open(os.path.join(TOKENS_DIR, fname), "r", encoding="utf-8") as f:
            _tokens_cache[ns] = json.load(f)

    return _tokens_cache


def _resolve_token(value, tokens: dict[str, dict]):
    """Resolve a single value that may be a token reference.

    Token references use dot notation: ``"typography.h1"`` →
    looks up tokens["typography"]["h1"].

    Non-string or non-matching values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    if "." not in value:
        return value
    parts = value.split(".", 1)
    if len(parts) != 2:
        return value
    ns, key = parts
    if ns in tokens and key in tokens[ns]:
        return tokens[ns][key]
    return value


def _resolve_tokens_in_dict(d: dict, tokens: dict[str, dict]) -> dict:
    """Recursively resolve token references in a dict."""
    resolved = {}
    for k, v in d.items():
        if isinstance(v, dict):
            resolved[k] = _resolve_tokens_in_dict(v, tokens)
        elif isinstance(v, str):
            resolved[k] = _resolve_token(v, tokens)
        else:
            resolved[k] = v
    return resolved


# ---------------------------------------------------------------------------
# Theme loader (with inheritance + token resolution)
# ---------------------------------------------------------------------------

_MAX_INHERITANCE_DEPTH = 5


def _load_theme_raw(theme_id: str) -> dict:
    """Load raw theme JSON without resolving inheritance or tokens."""
    path = os.path.join(THEMES_DIR, f"{theme_id}.json")
    if not os.path.isfile(path):
        available = list_theme_ids()
        raise ValueError(
            f"Theme '{theme_id}' not found. Available: {available}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_theme(theme_id: str) -> dict:
    """Load a theme, resolving inheritance chain and design tokens.

    Inheritance: a theme with ``"extends": "base_theme"`` inherits
    all properties from the base, with its own values winning.
    Chains up to 5 levels deep are supported.

    Token resolution: string values like ``"typography.h1"`` are
    replaced with the corresponding token value.
    """
    tokens = _load_tokens()
    chain: list[dict] = []
    visited: set[str] = set()
    current_id: str | None = theme_id

    # Walk the inheritance chain
    while current_id and len(chain) < _MAX_INHERITANCE_DEPTH:
        if current_id in visited:
            log.warning("[theme] circular inheritance detected at '%s'", current_id)
            break
        visited.add(current_id)
        raw = _load_theme_raw(current_id)
        chain.append(raw)
        current_id = raw.get("extends")

    # Merge from base → child (most specific wins)
    chain.reverse()
    merged: dict = {}
    for layer in chain:
        # Remove "extends" from the merged result
        layer_clean = {k: v for k, v in layer.items() if k != "extends"}
        merged = _deep_merge(merged, layer_clean)

    # Resolve token references
    merged = _resolve_tokens_in_dict(merged, tokens)

    return merged


def list_theme_ids() -> list[str]:
    """Return IDs of all available themes."""
    if not os.path.isdir(THEMES_DIR):
        return []
    return sorted(
        f.replace(".json", "")
        for f in os.listdir(THEMES_DIR)
        if f.endswith(".json")
    )


def list_themes() -> list[dict]:
    """Return summary of all available themes."""
    results = []
    for tid in list_theme_ids():
        theme = load_theme(tid)
        results.append({
            "id": theme.get("id", tid),
            "name": theme.get("name", ""),
            "description": theme.get("description", ""),
            "extends": None,  # already resolved
        })
    return results


# ---------------------------------------------------------------------------
# Template / variant loader
# ---------------------------------------------------------------------------

def _find_layout_path(template_id: str, variant: str | None) -> str:
    """Resolve layout file path, supporting both directory and flat layouts.

    Resolution order:
      1. templates/layouts/{template_id}/{variant}.json
      2. templates/layouts/{template_id}/center.json  (default variant)
      3. templates/layouts/{template_id}.json          (legacy flat file)
    """
    # Directory-based (new format)
    dir_path = os.path.join(LAYOUTS_DIR, template_id)
    if os.path.isdir(dir_path):
        if variant:
            path = os.path.join(dir_path, f"{variant}.json")
            if os.path.isfile(path):
                return path
            raise ValueError(
                f"Variant '{variant}' not found for layout '{template_id}'. "
                f"Available: {list_variants(template_id)}"
            )
        # Default: first variant alphabetically, or "center" if it exists
        center = os.path.join(dir_path, "center.json")
        if os.path.isfile(center):
            return center
        variants = list_variants(template_id)
        if variants:
            return os.path.join(dir_path, f"{variants[0]}.json")
        raise ValueError(f"Layout dir '{template_id}' contains no variant files.")

    # Legacy flat file
    flat = os.path.join(LAYOUTS_DIR, f"{template_id}.json")
    if os.path.isfile(flat):
        return flat

    available = list_layout_ids()
    raise ValueError(
        f"Layout '{template_id}' not found. Available: {available}"
    )


def load_template(template_id: str, variant: str | None = None) -> dict:
    """Load a layout template JSON, resolving variant if needed."""
    path = _find_layout_path(template_id, variant)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_variants(template_id: str) -> list[str]:
    """Return available variants for a layout (empty for flat layouts)."""
    dir_path = os.path.join(LAYOUTS_DIR, template_id)
    if not os.path.isdir(dir_path):
        return []
    return sorted(
        f.replace(".json", "")
        for f in os.listdir(dir_path)
        if f.endswith(".json")
    )


def list_layout_ids() -> list[str]:
    """Return IDs of all available layouts (directories + flat files)."""
    if not os.path.isdir(LAYOUTS_DIR):
        return []
    result = []
    for entry in sorted(os.listdir(LAYOUTS_DIR)):
        full = os.path.join(LAYOUTS_DIR, entry)
        if os.path.isdir(full):
            # Only include if it has at least one .json variant
            if any(f.endswith(".json") for f in os.listdir(full)):
                result.append(entry)
        elif entry.endswith(".json"):
            result.append(entry.replace(".json", ""))
    return result


# ---------------------------------------------------------------------------
# Template registry (public API)
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    """Load the central registry file, falling back to directory scan."""
    if os.path.isfile(REGISTRY_PATH):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def list_templates() -> list[dict]:
    """Return the full template registry: layouts + variants + themes.

    Uses ``templates/registry.json`` as the source of truth when
    available.  Falls back to scanning the layouts directory.

    Response::

        [
            {
                "template": "minimal_layout",
                "name": "Minimal Layout",
                "variants": ["center", "split"],
                "default_theme": "industrial_dark",
                "themes": ["industrial_dark", "luxury_gold", ...]
            },
            ...
        ]
    """
    registry = _load_registry()
    all_themes = list_theme_ids()

    if registry:
        result = []
        for layout_id, meta in registry.items():
            result.append({
                "template": layout_id,
                "name": meta.get("name", layout_id),
                "description": meta.get("description", ""),
                "variants": meta.get("variants", []),
                "default_theme": meta.get("default_theme", ""),
                "themes": meta.get("themes", all_themes),
            })
        return result

    # Fallback: scan directories
    result = []
    for layout_id in list_layout_ids():
        variants = list_variants(layout_id)
        try:
            tpl = load_template(layout_id)
        except ValueError:
            continue
        result.append({
            "template": layout_id,
            "name": tpl.get("name", layout_id),
            "description": tpl.get("description", ""),
            "variants": variants,
            "default_theme": tpl.get("default_theme", ""),
            "themes": all_themes,
        })
    return result


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _llm_call(messages: list, model: str = MODEL_CONTENT,
              temperature: float = 0.5) -> str:
    """Call OpenRouter chat completion. Returns assistant content string."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5001",
        "X-Title": "Content Dashboard",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    resp = http_requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"LLM error: {data['error']}")
    return data["choices"][0]["message"]["content"]


def _llm_json(messages: list, model: str = MODEL_CONTENT) -> dict:
    """Call LLM and parse the response as JSON."""
    raw = _llm_call(messages, model=model, temperature=0.3)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start:end + 1])
    raise ValueError(f"Could not parse JSON from LLM response: {cleaned[:200]}")


# ---------------------------------------------------------------------------
# Step 1: Generate structured content
# ---------------------------------------------------------------------------

def _generate_content(prompt: str) -> dict:
    """Ask the LLM to produce structured carousel content."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a social media content strategist. "
                "Generate structured content for an Instagram carousel. "
                "Reply ONLY with a JSON object, no extra text.\n\n"
                "Required JSON format:\n"
                "{\n"
                '  "title": "Short impactful title (max 8 words)",\n'
                '  "subtitle": "Supporting subtitle (max 15 words)",\n'
                '  "bullets": ["Point 1", "Point 2", "Point 3"],\n'
                '  "cta": "Call to action text (max 6 words)",\n'
                '  "body": "Optional body paragraph for the text slide"\n'
                "}"
            ),
        },
        {
            "role": "user",
            "content": f"Create carousel content about: {prompt}",
        },
    ]
    return _llm_json(messages)


# ---------------------------------------------------------------------------
# Step 2: Generate image prompts
# ---------------------------------------------------------------------------

def _generate_image_prompts(prompt: str, num_images: int = 3) -> list[str]:
    """Ask the LLM to produce image generation prompts."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are an art director for social media visuals. "
                "Generate image prompts for AI image generation. "
                "Each prompt should describe a visual that works as a "
                "carousel slide background. "
                "Style: editorial, elegant, no text, no people, no animals. "
                f"Reply ONLY with a JSON object containing an 'image_prompts' "
                f"array of exactly {num_images} strings."
            ),
        },
        {
            "role": "user",
            "content": f"Generate {num_images} background image prompts for a carousel about: {prompt}",
        },
    ]
    data = _llm_json(messages)
    prompts = data.get("image_prompts", [])
    if not prompts:
        prompts = [f"Abstract elegant background texture for {prompt}, editorial style, no text"]
    return prompts[:num_images]


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_instagram_carousel(
    prompt: str,
    user_id: str,
    template_id: str = "minimal_layout",
    variant: str | None = None,
    theme_id: str | None = None,
    num_images: int = 3,
    selected_asset_index: int = 0,
    asset_mapping: dict | None = None,
    overrides: dict | None = None,
) -> dict:
    """Generate a complete Instagram carousel.

    Args:
        prompt: User's topic/description for the carousel.
        user_id: Supabase user ID.
        template_id: Layout template (from templates/layouts/).
        variant: Layout variant (e.g. "center", "split"). None = default.
        theme_id: Theme to apply (from templates/themes/). None = use
                  the layout's ``default_theme``, or fall back to
                  ``industrial_dark``.
        num_images: How many asset images to generate (1-3).
        selected_asset_index: Which generated asset to use as background
                              (ignored if asset_mapping is provided).
        asset_mapping: Explicit mapping of template asset_ids to asset
                       indices, e.g. ``{"background_asset": 1}``.
        overrides: User overrides for fonts/colors/sizes.

    Returns::

        {
            "slides": ["url1", "url2", ...],
            "assets": [{"id": "...", "image_url": "...", ...}, ...],
            "template": "minimal_layout",
            "variant": "center",
            "theme": "industrial_dark",
            "content": {"title": "...", ...}
        }
    """
    t0 = time.time()
    session_id = uuid.uuid4().hex[:12]
    num_images = max(1, min(num_images, 3))
    overrides = overrides or {}

    log.info("[carousel] ═══ START ═══ user=%s template=%s variant=%s theme=%s",
             user_id[:8], template_id, variant, theme_id)
    log.info("[carousel] prompt: %s", prompt[:200])

    # 1) Load layout template
    template = load_template(template_id, variant=variant)
    actual_variant = variant or "center"
    log.info("[carousel] layout loaded: %s", template.get("name", template_id))

    # 2) Load theme (resolve default if not specified)
    if not theme_id:
        theme_id = template.get("default_theme", "") or "industrial_dark"
    try:
        theme = load_theme(theme_id)
    except ValueError:
        log.warning("[carousel] theme '%s' not found, falling back to no theme", theme_id)
        theme = None
    log.info("[carousel] theme: %s", theme.get("name", "none") if theme else "none")

    # 3) Generate structured content
    log.info("[carousel] step 1: generating structured content…")
    content = _generate_content(prompt)
    log.info("[carousel] content: title=%s", content.get("title", "")[:60])

    # 4) Generate image prompts
    log.info("[carousel] step 2: generating %d image prompts…", num_images)
    image_prompts = _generate_image_prompts(prompt, num_images=num_images)
    log.info("[carousel] image prompts: %s", [p[:60] for p in image_prompts])

    # 5) Generate and store assets
    log.info("[carousel] step 3: generating %d assets…", len(image_prompts))
    assets = generate_assets_batch(image_prompts, user_id)
    successful_assets = [a for a in assets if "error" not in a]
    log.info("[carousel] assets generated: %d/%d successful",
             len(successful_assets), len(assets))

    # 6) Build asset_map from mapping or default
    asset_map: dict = {}
    if successful_assets:
        if asset_mapping:
            # Explicit mapping: {"background_asset": 1, "logo": 2}
            for asset_id, asset_idx in asset_mapping.items():
                idx = min(int(asset_idx), len(successful_assets) - 1)
                try:
                    asset_map[asset_id] = load_asset_image(
                        successful_assets[idx]["image_url"]
                    )
                    log.info("[carousel] mapped %s → asset %d", asset_id, idx)
                except Exception as exc:
                    log.warning("[carousel] failed to load asset %d for %s: %s",
                                idx, asset_id, exc)
        else:
            # Default: first successful asset → background_asset
            idx = min(selected_asset_index, len(successful_assets) - 1)
            try:
                asset_map["background_asset"] = load_asset_image(
                    successful_assets[idx]["image_url"]
                )
                log.info("[carousel] mapped background_asset → asset %d", idx)
            except Exception as exc:
                log.warning("[carousel] failed to load asset image: %s", exc)

    # 7) Render slides
    log.info("[carousel] step 5: rendering slides…")
    png_buffers = render_slides(
        template, content, asset_map=asset_map, theme=theme, overrides=overrides,
    )
    log.info("[carousel] rendered %d slides", len(png_buffers))

    # 8) Upload slides to Supabase
    log.info("[carousel] step 6: uploading slides…")
    slide_urls = _db.upload_carousel_images_batch(user_id, session_id, png_buffers)
    log.info("[carousel] uploaded %d slides", len(slide_urls))

    elapsed = time.time() - t0
    log.info("[carousel] ═══ DONE in %.1fs ═══ slides=%d assets=%d",
             elapsed, len(slide_urls), len(successful_assets))

    return {
        "slides": slide_urls,
        "assets": successful_assets,
        "template": template_id,
        "variant": actual_variant,
        "theme": theme_id,
        "content": content,
    }
