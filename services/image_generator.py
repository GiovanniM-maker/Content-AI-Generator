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
import json
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

    # Use structured content array (OpenRouter docs recommend this for multimodal)
    payload = {
        "model": IMAGE_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Generate this image. Output ONLY the image, "
                            "no text explanation.\n\n"
                            f"{prompt}"
                        ),
                    }
                ],
            }
        ],
        "modalities": ["image", "text"],
    }

    log.info("[image_gen][request] model=%s", IMAGE_MODEL)
    log.info("[image_gen][request] prompt=%s", prompt[:200])
    log.info("[image_gen][request] payload keys=%s, modalities=%s",
             list(payload.keys()), payload.get("modalities"))

    resp = http_requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=GENERATE_TIMEOUT,
    )

    log.info("[image_gen][response] HTTP status=%d, content-type=%s",
             resp.status_code, resp.headers.get("Content-Type", "unknown"))

    # Check for HTTP errors
    if resp.status_code != 200:
        error_detail = ""
        try:
            error_data = resp.json()
            log.error("[image_gen][response] ERROR body: %s",
                      json.dumps(error_data, indent=2, default=str)[:2000])
            if "error" in error_data:
                error_detail = error_data["error"].get("message", str(error_data["error"]))
        except Exception:
            error_detail = resp.text[:500]
            log.error("[image_gen][response] ERROR raw: %s", error_detail)
        raise RuntimeError(
            f"[image_gen][openrouter] HTTP {resp.status_code}: {error_detail}"
        )

    data = resp.json()

    # ── LOG RAW RESPONSE STRUCTURE (truncate base64 to keep logs readable) ──
    _log_response_structure(data)

    # Check for API-level errors
    if "error" in data:
        err_msg = data["error"].get("message", str(data["error"]))
        log.error("[image_gen][response] API error: %s", err_msg)
        raise RuntimeError(f"[image_gen][openrouter] API error: {err_msg}")

    # Extract image from response
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(
            f"[image_gen][openrouter] no choices in response. "
            f"Top-level keys: {list(data.keys())}"
        )

    message = choices[0].get("message", {})
    log.info("[image_gen][parse] message keys: %s", list(message.keys()))

    # ── Strategy 1: message.images array (documented OpenRouter format) ──
    images = message.get("images", [])
    if images:
        log.info("[image_gen][parse] found message.images array (%d entries)", len(images))
        img_entry = images[0]
        log.info("[image_gen][parse] images[0] type=%s, keys=%s",
                 type(img_entry).__name__,
                 list(img_entry.keys()) if isinstance(img_entry, dict) else "N/A")
        if isinstance(img_entry, dict):
            url = (
                img_entry.get("image_url", {}).get("url", "")
                or img_entry.get("url", "")
                or img_entry.get("b64_json", "")
            )
        else:
            url = str(img_entry)
        if url:
            log.info("[image_gen][parse] MATCH: message.images → url starts with: %s", url[:60])
            return _decode_image_data(url)

    # ── Strategy 2: content is a list of parts (multipart response) ──
    content = message.get("content", "")
    if isinstance(content, list):
        log.info("[image_gen][parse] content is list (%d parts)", len(content))
        for i, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            ptype = part.get("type", "")
            log.info("[image_gen][parse] content[%d] type=%s, keys=%s",
                     i, ptype, list(part.keys()))

            # Format B1: {"type": "image_url", "image_url": {"url": "data:..."}}
            if ptype == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url:
                    log.info("[image_gen][parse] MATCH: content[%d] image_url → %s", i, url[:60])
                    return _decode_image_data(url)

            # Format B2: {"type": "image", "data": "base64...", "mime_type": "image/png"}
            if ptype == "image":
                b64_data = part.get("data", "")
                if b64_data:
                    log.info("[image_gen][parse] MATCH: content[%d] image data (%d chars)",
                             i, len(b64_data))
                    return base64.b64decode(b64_data)

            # Format B3: Gemini-style inline_data
            inline = part.get("inline_data", {})
            if inline and inline.get("data"):
                log.info("[image_gen][parse] MATCH: content[%d] inline_data (mime=%s)",
                         i, inline.get("mime_type", "unknown"))
                return base64.b64decode(inline["data"])

        # Last resort: scan text parts for embedded data URLs
        for i, part in enumerate(content):
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                img_bytes = _extract_data_url_from_text(text)
                if img_bytes:
                    log.info("[image_gen][parse] MATCH: data URL embedded in content[%d] text", i)
                    return img_bytes

    # ── Strategy 3: content is a plain string with embedded data URL ──
    if isinstance(content, str) and content:
        log.info("[image_gen][parse] content is string (%d chars)", len(content))
        img_bytes = _extract_data_url_from_text(content)
        if img_bytes:
            log.info("[image_gen][parse] MATCH: data URL embedded in string content")
            return img_bytes

    # ── FAILURE: no image found — dump full structure for debugging ──
    content_preview = str(content)[:500] if content else "(empty)"
    log.error(
        "[image_gen][parse] FAILED: no image found!\n"
        "  message keys: %s\n"
        "  content type: %s\n"
        "  content preview: %s",
        list(message.keys()),
        type(content).__name__,
        content_preview,
    )
    raise RuntimeError(
        f"[image_gen][openrouter] Image generation succeeded but no image found in response. "
        f"Message keys: {list(message.keys())}. "
        f"Content type: {type(content).__name__}. "
        f"Content preview: {content_preview}"
    )


def _log_response_structure(data: dict) -> None:
    """Log the response structure with base64 data truncated for readability."""
    try:
        # Deep-copy and truncate any long base64 strings
        def _truncate(obj, depth=0):
            if depth > 6:
                return "..."
            if isinstance(obj, str):
                if len(obj) > 200:
                    return f"{obj[:80]}...[{len(obj)} chars total]...{obj[-40:]}"
                return obj
            if isinstance(obj, dict):
                return {k: _truncate(v, depth + 1) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_truncate(v, depth + 1) for v in obj[:5]]  # max 5 items
            return obj
        safe = _truncate(data)
        log.info("[image_gen][response] RAW STRUCTURE:\n%s",
                 json.dumps(safe, indent=2, default=str))
    except Exception as e:
        log.warning("[image_gen][response] failed to log structure: %s", e)


def _decode_image_data(data: str) -> bytes:
    """Decode image data from a data URL, HTTP URL, or raw base64 string."""
    # Case 1: data:image/...;base64,...
    if data.startswith("data:"):
        match = re.match(r"data:[^;]+;base64,(.+)", data, re.DOTALL)
        if match:
            b64 = match.group(1)
            img_bytes = base64.b64decode(b64)
            log.info("[image_gen][decode] base64 data URL → %d bytes", len(img_bytes))
            if len(img_bytes) < 500:
                raise RuntimeError(
                    f"[image_gen][decode] decoded image suspiciously small ({len(img_bytes)} bytes)"
                )
            return img_bytes
        raise RuntimeError(f"[image_gen][decode] malformed data URL: {data[:100]}")

    # Case 2: HTTP(S) URL — download it
    if data.startswith("http"):
        log.info("[image_gen][download] fetching URL=%s", data[:120])
        resp = http_requests.get(data, timeout=30)
        resp.raise_for_status()
        log.info("[image_gen][download] received %d bytes, content-type=%s",
                 len(resp.content), resp.headers.get("content-type", "unknown"))
        if len(resp.content) < 500:
            raise RuntimeError(
                f"[image_gen][download] image suspiciously small ({len(resp.content)} bytes)"
            )
        return resp.content

    # Case 3: raw base64 string (no data: prefix)
    # Heuristic: if it looks like base64 (long, alphanumeric), try decoding
    if len(data) > 100 and re.match(r'^[A-Za-z0-9+/=\s]+$', data[:200]):
        try:
            img_bytes = base64.b64decode(data)
            log.info("[image_gen][decode] raw base64 string → %d bytes", len(img_bytes))
            if len(img_bytes) < 500:
                raise RuntimeError(
                    f"[image_gen][decode] decoded image suspiciously small ({len(img_bytes)} bytes)"
                )
            return img_bytes
        except Exception as e:
            log.warning("[image_gen][decode] raw base64 decode failed: %s", e)

    raise RuntimeError(
        f"[image_gen][decode] unrecognized image data format "
        f"(len={len(data)}, starts_with={data[:60]!r})"
    )


def _extract_data_url_from_text(text: str) -> bytes | None:
    """Try to extract a base64 data URL from text content."""
    match = re.search(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", text)
    if match:
        log.info("[image_gen][parse] found data URL embedded in text (%d chars match)",
                 len(match.group(0)))
        return _decode_image_data(match.group(0))
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
