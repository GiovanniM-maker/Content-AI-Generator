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

import hashlib
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import requests as http_requests

log = logging.getLogger(__name__)

FAL_KEY = os.getenv("FAL_KEY", "")
FAL_MODEL = "fal-ai/flux/schnell"

# Timeouts
GENERATE_TIMEOUT = 120  # seconds — Flux Schnell is fast (~5-15s typical)
DOWNLOAD_TIMEOUT = 30

# Image spec for Instagram slides
IMAGE_SIZE = {"width": 1080, "height": 1080}


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
    import fal_client

    if not FAL_KEY:
        raise RuntimeError("FAL_KEY environment variable is not set")

    os.environ["FAL_KEY"] = FAL_KEY

    result = _run_with_timeout(
        lambda: fal_client.subscribe(
            FAL_MODEL,
            arguments={
                "prompt": prompt,
                "image_size": IMAGE_SIZE,
                "num_inference_steps": num_inference_steps,
                "num_images": 1,
                "enable_safety_checker": True,
            },
        ),
        timeout=GENERATE_TIMEOUT,
        label="Image generation (Flux Schnell)",
    )

    images = result.get("images", [])
    if not images:
        raise RuntimeError("fal.ai returned no images")

    return images[0]["url"]


def _download_image(url: str) -> bytes:
    """Download image bytes from a URL."""
    resp = http_requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    if len(resp.content) < 1000:
        raise RuntimeError(f"Downloaded image is suspiciously small ({len(resp.content)} bytes)")
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

    url = db.upload_template_asset(
        user_id=user_id,
        template_id=template_id,
        filename=filename,
        file_bytes=image_bytes,
        content_type="image/png",
    )

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

    log.info(f"[image_gen] Generating image for template {template_id}, target={target}")
    log.info(f"[image_gen] Prompt: {prompt[:120]}...")

    t0 = time.time()

    # Step 1: Generate image via fal.ai
    try:
        fal_url = _generate_fal_image(prompt.strip())
    except TimeoutError:
        log.error(f"[image_gen] fal.ai timeout after {time.time() - t0:.1f}s")
        raise
    except Exception as e:
        log.error(f"[image_gen] fal.ai generation failed: {e}")
        raise RuntimeError(f"Image generation failed: {e}") from e

    log.info(f"[image_gen] fal.ai returned image in {time.time() - t0:.1f}s")

    # Step 2: Download from temporary fal.ai URL
    try:
        image_bytes = _download_image(fal_url)
    except Exception as e:
        log.error(f"[image_gen] Failed to download from fal.ai: {e}")
        raise RuntimeError(f"Failed to download generated image: {e}") from e

    log.info(f"[image_gen] Downloaded {len(image_bytes)} bytes")

    # Step 3: Upload to Supabase Storage (permanent URL)
    try:
        public_url = _upload_to_supabase(image_bytes, user_id, template_id, target)
    except Exception as e:
        log.error(f"[image_gen] Supabase upload failed: {e}")
        raise RuntimeError(f"Failed to upload image to storage: {e}") from e

    elapsed = time.time() - t0
    log.info(f"[image_gen] Complete in {elapsed:.1f}s → {public_url}")

    return {"url": public_url, "target": target}
