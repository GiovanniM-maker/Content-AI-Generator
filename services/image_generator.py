"""Image generation service using OpenRouter (Gemini Flash image model).

Generates a single image from a text prompt via the same OpenRouter API used
by the rest of the app, uploads it to Supabase Storage, and returns a stable
public URL suitable for use in design_spec fields:
  - images.background_image_url  (shared background across all slides)
  - images.slide_images.cover    (cover-specific image)

Usage:
    from services.image_generator import generate_image

    result = generate_image(
        prompt="Abstract dark marble texture with purple veins",
        user_id="...",
        template_id="...",
        target="background",  # or "cover"
    )
    # result = {"url": "https://...supabase.../...", "target": "background"}
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
import traceback
import uuid

import requests as http_requests

log = logging.getLogger(__name__)

# OpenRouter config — same env var and base URL used by the rest of the app
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
IMAGE_MODEL = "google/gemini-2.5-flash-image-preview"

# Timeout for the full generation request (model inference can take 15-40s)
GENERATE_TIMEOUT = 120


def _get_openrouter_key() -> str:
    """Read OPENROUTER_API_KEY from environment at call time."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "[image_gen][config] OPENROUTER_API_KEY environment variable is missing or empty."
        )
    return key


def _generate_image_openrouter(prompt: str) -> bytes:
    """Call OpenRouter image generation and return raw image bytes.

    Uses the chat/completions endpoint with modalities=["image", "text"].
    The model returns the image as a base64 data URL inline in the response.
    """
    api_key = _get_openrouter_key()
    log.info("[image_gen][config] OPENROUTER_API_KEY present (length=%d)", len(api_key))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5001",
        "X-Title": "Content Dashboard",
    }

    payload = {
        "model": IMAGE_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Generate this image. Output ONLY the image, no text explanation.\n\n"
                    f"{prompt}"
                ),
            }
        ],
        "modalities": ["image", "text"],
    }

    log.info("[image_gen][openrouter] request starting → model=%s", IMAGE_MODEL)
    log.info("[image_gen][openrouter] prompt=%s", prompt[:200])

    resp = http_requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=GENERATE_TIMEOUT,
    )

    # Check for HTTP errors
    if resp.status_code != 200:
        error_detail = ""
        try:
            error_data = resp.json()
            if "error" in error_data:
                error_detail = error_data["error"].get("message", str(error_data["error"]))
        except Exception:
            error_detail = resp.text[:300]
        raise RuntimeError(
            f"[image_gen][openrouter] HTTP {resp.status_code}: {error_detail}"
        )

    data = resp.json()
    log.info("[image_gen][openrouter] response received (status=%d)", resp.status_code)

    # Check for API-level errors
    if "error" in data:
        err_msg = data["error"].get("message", str(data["error"]))
        raise RuntimeError(f"[image_gen][openrouter] API error: {err_msg}")

    # Extract image from response
    # OpenRouter returns images as base64 data URLs in the message content
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(
            f"[image_gen][openrouter] no choices in response. Keys: {list(data.keys())}"
        )

    message = choices[0].get("message", {})

    # Strategy 1: Check message.images array (structured format)
    images = message.get("images", [])
    if images:
        img_entry = images[0]
        if isinstance(img_entry, dict):
            url = img_entry.get("image_url", {}).get("url", "") or img_entry.get("url", "")
        else:
            url = str(img_entry)
        if url:
            log.info("[image_gen][openrouter] found image in message.images")
            return _decode_data_url(url)

    # Strategy 2: Check multipart content array
    content = message.get("content", "")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url:
                        log.info("[image_gen][openrouter] found image in content array (image_url)")
                        return _decode_data_url(url)
                elif part.get("type") == "image":
                    # Some models return {"type": "image", "data": "base64..."}
                    b64_data = part.get("data", "")
                    if b64_data:
                        log.info("[image_gen][openrouter] found image in content array (image data)")
                        return base64.b64decode(b64_data)
        # If content is a list, also try to find data URLs in text parts
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                img_bytes = _extract_data_url_from_text(text)
                if img_bytes:
                    return img_bytes

    # Strategy 3: Check string content for embedded data URL
    if isinstance(content, str) and content:
        img_bytes = _extract_data_url_from_text(content)
        if img_bytes:
            return img_bytes

    # Nothing found — log what we got for debugging
    content_preview = str(content)[:300] if content else "(empty)"
    raise RuntimeError(
        f"[image_gen][openrouter] no image found in response. "
        f"Message keys: {list(message.keys())}. "
        f"Content type: {type(content).__name__}. "
        f"Content preview: {content_preview}"
    )


def _decode_data_url(url: str) -> bytes:
    """Decode a data:image/...;base64,... URL to raw bytes."""
    if url.startswith("data:"):
        # Strip the data URL prefix
        match = re.match(r"data:[^;]+;base64,(.+)", url, re.DOTALL)
        if match:
            b64 = match.group(1)
            img_bytes = base64.b64decode(b64)
            log.info("[image_gen][decode] decoded base64 data URL → %d bytes", len(img_bytes))
            if len(img_bytes) < 1000:
                raise RuntimeError(f"Decoded image is suspiciously small ({len(img_bytes)} bytes)")
            return img_bytes
    elif url.startswith("http"):
        # It's a regular URL — download it
        log.info("[image_gen][download] fetching URL=%s", url[:120])
        resp = http_requests.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) < 1000:
            raise RuntimeError(f"Downloaded image is suspiciously small ({len(resp.content)} bytes)")
        log.info("[image_gen][download] received %d bytes", len(resp.content))
        return resp.content

    raise RuntimeError(f"[image_gen][decode] unrecognized image URL format: {url[:100]}")


def _extract_data_url_from_text(text: str) -> bytes | None:
    """Try to extract a base64 data URL from text content."""
    match = re.search(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", text)
    if match:
        log.info("[image_gen][openrouter] found data URL embedded in text content")
        return _decode_data_url(match.group(0))
    return None


def _upload_to_supabase(
    image_bytes: bytes,
    user_id: str,
    template_id: str,
    target: str,
) -> str:
    """Upload generated image to Supabase Storage and return public URL.

    Uses the template-assets bucket with path:
        {user_id}/{template_id}/generated_{target}_{short_hash}.png
    """
    import db

    short_id = uuid.uuid4().hex[:8]
    filename = f"generated_{target}_{short_id}.png"

    log.info("[image_gen][upload] starting → bucket=template-assets, "
             "path=%s/%s/%s, size=%d bytes",
             user_id[:8], template_id[:8], filename, len(image_bytes))

    url = db.upload_template_asset(
        user_id=user_id,
        template_id=template_id,
        filename=filename,
        file_bytes=image_bytes,
        content_type="image/png",
    )

    if not url or not url.startswith("http"):
        raise RuntimeError(f"[image_gen][upload] got invalid URL from Supabase: {url!r}")

    log.info("[image_gen][upload] success → %s", url)
    return url


def generate_image(
    prompt: str,
    user_id: str,
    template_id: str,
    target: str = "background",
) -> dict:
    """Generate a single image and upload it to Supabase Storage.

    Args:
        prompt: Text description of the desired image.
        user_id: Supabase user ID (for storage path).
        template_id: Template ID (for storage path).
        target: Where this image will be used — "background" or "cover".

    Returns:
        {"url": "https://...stable-public-url...", "target": "background"|"cover"}

    Raises:
        RuntimeError: If generation or upload fails.
        TimeoutError: If OpenRouter call exceeds timeout.
        ValueError: If target is invalid.
    """
    if target not in ("background", "cover"):
        raise ValueError(f"Invalid target: {target!r}. Must be 'background' or 'cover'.")

    if not prompt or not prompt.strip():
        raise ValueError("Image prompt cannot be empty")

    log.info("[image_gen] ════════ request received ════════")
    log.info("[image_gen] template=%s, target=%s", template_id, target)
    log.info("[image_gen] prompt=%s", prompt[:200])

    t0 = time.time()

    # Step 1: Generate image via OpenRouter
    try:
        image_bytes = _generate_image_openrouter(prompt.strip())
    except http_requests.exceptions.Timeout:
        log.error("[image_gen][openrouter] TIMEOUT after %.1fs", time.time() - t0)
        raise TimeoutError(f"Image generation timed out after {GENERATE_TIMEOUT}s")
    except RuntimeError:
        raise  # Already has descriptive error message
    except Exception as e:
        log.error("[image_gen][openrouter] unexpected error: %s\n%s", e, traceback.format_exc())
        raise RuntimeError(f"Image generation failed: {e}") from e

    log.info("[image_gen][openrouter] completed in %.1fs, image=%d bytes",
             time.time() - t0, len(image_bytes))

    # Step 2: Upload to Supabase Storage (permanent URL)
    try:
        public_url = _upload_to_supabase(image_bytes, user_id, template_id, target)
    except Exception as e:
        log.error("[image_gen][upload] FAILED: %s\n%s", e, traceback.format_exc())
        raise RuntimeError(f"Failed to upload image to storage: {e}") from e

    elapsed = time.time() - t0
    log.info("[image_gen] ════════ COMPLETE in %.1fs ════════ → %s", elapsed, public_url)

    return {"url": public_url, "target": target}
