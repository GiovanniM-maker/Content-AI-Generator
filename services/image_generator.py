"""Image generation service using fal.ai Flux Schnell.

Generates a single image from a text prompt, uploads it to Supabase Storage,
and returns a stable public URL suitable for use in design_spec fields:
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

import logging
import os
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import requests as http_requests

log = logging.getLogger(__name__)

FAL_MODEL = "fal-ai/flux/schnell"

# Timeouts
GENERATE_TIMEOUT = 120  # seconds — Flux Schnell is fast (~5-15s typical)
DOWNLOAD_TIMEOUT = 30

# Image spec for Instagram slides
IMAGE_SIZE = {"width": 1080, "height": 1080}


def _get_fal_key() -> str:
    """Read FAL_KEY from environment at call time (not import time).

    This allows the key to be set after the module is imported,
    which is common with .env loading or secrets injection.
    """
    key = os.getenv("FAL_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "[image_gen][config] FAL_KEY environment variable is missing or empty. "
            "Set it to your fal.ai API key (https://fal.ai/dashboard/keys)."
        )
    return key


def _run_with_timeout(fn, timeout: int, label: str = "operation"):
    """Run a callable with a timeout."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            raise TimeoutError(f"{label} exceeded timeout of {timeout}s")


def _generate_fal_image(prompt: str, num_inference_steps: int = 4) -> str:
    """Call fal.ai Flux Schnell to generate an image.

    Returns the temporary fal.ai URL of the generated image.
    Raises on failure.
    """
    try:
        import fal_client
    except ImportError:
        raise RuntimeError(
            "[image_gen][config] fal-client package is not installed. "
            "Run: pip install fal-client==0.5.9"
        )

    fal_key = _get_fal_key()
    os.environ["FAL_KEY"] = fal_key
    log.info("[image_gen][config] FAL_KEY present (length=%d)", len(fal_key))

    payload = {
        "prompt": prompt,
        "image_size": IMAGE_SIZE,
        "num_inference_steps": num_inference_steps,
        "num_images": 1,
        "enable_safety_checker": True,
    }
    log.info("[image_gen][fal] request starting → model=%s, image_size=%s, steps=%d",
             FAL_MODEL, IMAGE_SIZE, num_inference_steps)

    result = _run_with_timeout(
        lambda: fal_client.subscribe(
            FAL_MODEL,
            arguments=payload,
        ),
        timeout=GENERATE_TIMEOUT,
        label="Image generation (Flux Schnell)",
    )

    log.info("[image_gen][fal] response received, keys=%s", list(result.keys()) if isinstance(result, dict) else type(result).__name__)

    if not isinstance(result, dict):
        raise RuntimeError(f"[image_gen][fal] unexpected response type: {type(result).__name__}")

    images = result.get("images", [])
    if not images:
        raise RuntimeError(
            f"[image_gen][fal] no images in response. "
            f"Keys: {list(result.keys())}. "
            f"Has 'images': {'images' in result}. "
            f"Content sample: {str(result)[:200]}"
        )

    url = images[0].get("url", "") if isinstance(images[0], dict) else str(images[0])
    if not url:
        raise RuntimeError(f"[image_gen][fal] first image has no URL. Image entry: {images[0]}")

    log.info("[image_gen][fal] image URL received: %s", url[:100])
    return url


def _download_image(url: str) -> bytes:
    """Download image bytes from a URL."""
    log.info("[image_gen][download] fetching URL=%s", url[:120])
    resp = http_requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    size = len(resp.content)
    log.info("[image_gen][download] received %d bytes, content-type=%s",
             size, resp.headers.get("content-type", "unknown"))
    if size < 1000:
        raise RuntimeError(f"Downloaded image is suspiciously small ({size} bytes)")
    return resp.content


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
        TimeoutError: If fal.ai call exceeds timeout.
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

    # Step 1: Generate image via fal.ai
    try:
        fal_url = _generate_fal_image(prompt.strip())
    except TimeoutError:
        log.error("[image_gen][fal] TIMEOUT after %.1fs", time.time() - t0)
        raise
    except RuntimeError:
        raise  # Already has good error message from _generate_fal_image
    except Exception as e:
        log.error("[image_gen][fal] unexpected error: %s\n%s", e, traceback.format_exc())
        raise RuntimeError(f"Image generation failed: {e}") from e

    log.info("[image_gen][fal] completed in %.1fs", time.time() - t0)

    # Step 2: Download from temporary fal.ai URL
    try:
        image_bytes = _download_image(fal_url)
    except Exception as e:
        log.error("[image_gen][download] FAILED: %s\n%s", e, traceback.format_exc())
        raise RuntimeError(f"Failed to download generated image: {e}") from e

    # Step 3: Upload to Supabase Storage (permanent URL)
    try:
        public_url = _upload_to_supabase(image_bytes, user_id, template_id, target)
    except Exception as e:
        log.error("[image_gen][upload] FAILED: %s\n%s", e, traceback.format_exc())
        raise RuntimeError(f"Failed to upload image to storage: {e}") from e

    elapsed = time.time() - t0
    log.info("[image_gen] ════════ COMPLETE in %.1fs ════════ → %s", elapsed, public_url)

    return {"url": public_url, "target": target}
