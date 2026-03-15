"""New carousel generation pipeline — template + content + assets.

Orchestrates the full flow:
  1. LLM generates structured content (title, subtitle, bullets, cta)
  2. LLM generates 2-3 image prompts from the user prompt
  3. Image model generates assets
  4. Assets are stored in Supabase
  5. Renderer composes slides using template + content + selected asset
  6. Slides exported as PNG and uploaded to Supabase

Usage::

    from services.carousel_pipeline import generate_instagram_carousel

    result = generate_instagram_carousel(
        prompt="5 strategie per aumentare le vendite online",
        user_id="abc123",
        template_id="minimal_industrial",
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

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "templates", "layouts"
)


# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------

def load_template(template_id: str) -> dict:
    """Load a template JSON from templates/layouts/{template_id}.json."""
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.json")
    if not os.path.isfile(path):
        available = [
            f.replace(".json", "")
            for f in os.listdir(TEMPLATES_DIR)
            if f.endswith(".json")
        ]
        raise ValueError(
            f"Template '{template_id}' not found. "
            f"Available: {available}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_templates() -> list[dict]:
    """Return a summary of all available templates."""
    templates = []
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(TEMPLATES_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        templates.append({
            "id": data.get("id", fname.replace(".json", "")),
            "name": data.get("name", ""),
            "description": data.get("description", ""),
        })
    return templates


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
    # Strip markdown fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # Find JSON object
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
        # Fallback: single generic prompt
        prompts = [f"Abstract elegant background texture for {prompt}, editorial style, no text"]
    return prompts[:num_images]


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_instagram_carousel(
    prompt: str,
    user_id: str,
    template_id: str = "minimal_industrial",
    num_images: int = 3,
    selected_asset_index: int = 0,
    overrides: dict | None = None,
) -> dict:
    """Generate a complete Instagram carousel.

    Args:
        prompt: User's topic/description for the carousel.
        user_id: Supabase user ID.
        template_id: Which template to use (from templates/layouts/).
        num_images: How many asset images to generate (2-3).
        selected_asset_index: Which generated asset to use as background.
        overrides: Optional user overrides for fonts/colors/sizes.
                   Keys follow ``{element_type}_{property}`` naming::

                       {
                           "title_font": "Montserrat",
                           "title_color": "#FFD700",
                           "subtitle_size": 40,
                           "accent_color": "#ff0000",
                       }

    Returns::

        {
            "slides": ["url1", "url2", "url3", "url4"],
            "assets": [
                {"id": "...", "image_url": "...", "prompt": "..."},
                ...
            ],
            "template": "minimal_industrial",
            "content": {"title": "...", ...}
        }
    """
    t0 = time.time()
    session_id = uuid.uuid4().hex[:12]
    num_images = max(1, min(num_images, 3))
    overrides = overrides or {}

    log.info("[carousel] ═══ START ═══ user=%s template=%s", user_id[:8], template_id)
    log.info("[carousel] prompt: %s", prompt[:200])

    # 1) Load template
    template = load_template(template_id)
    log.info("[carousel] template loaded: %s", template["name"])

    # 2) Generate structured content
    log.info("[carousel] step 1: generating structured content…")
    content = _generate_content(prompt)
    log.info("[carousel] content: title=%s", content.get("title", "")[:60])

    # 3) Generate image prompts
    log.info("[carousel] step 2: generating %d image prompts…", num_images)
    image_prompts = _generate_image_prompts(prompt, num_images=num_images)
    log.info("[carousel] image prompts: %s", [p[:60] for p in image_prompts])

    # 4) Generate and store assets
    log.info("[carousel] step 3: generating %d assets…", len(image_prompts))
    assets = generate_assets_batch(image_prompts, user_id)
    successful_assets = [a for a in assets if "error" not in a]
    log.info("[carousel] assets generated: %d/%d successful",
             len(successful_assets), len(assets))

    # 5) Build asset_map — maps template asset_ids to PIL Images
    asset_map: dict = {}
    if successful_assets:
        idx = min(selected_asset_index, len(successful_assets) - 1)
        try:
            asset_map["background_asset"] = load_asset_image(
                successful_assets[idx]["image_url"]
            )
            log.info("[carousel] mapped background_asset → asset %d", idx)
        except Exception as exc:
            log.warning("[carousel] failed to load asset image: %s", exc)

    # 6) Render slides
    log.info("[carousel] step 5: rendering slides…")
    png_buffers = render_slides(
        template, content, asset_map=asset_map, overrides=overrides,
    )
    log.info("[carousel] rendered %d slides", len(png_buffers))

    # 7) Upload slides to Supabase
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
        "content": content,
    }
