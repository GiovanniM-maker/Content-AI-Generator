#!/usr/bin/env python3
"""
Pre-render all preset template previews and upload to Supabase Storage.
Updates thumbnail_url in preset_templates table so the frontend loads
images instantly (no Playwright render on every page visit).

Run once after deploy / after seeding presets:
  python3 cache_previews.py

Requires Playwright browsers installed:
  playwright install chromium
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

import db
from carousel_renderer import render_template_preview


def main():
    print("=== Pre-rendering preset template previews ===\n")

    # Ensure the Storage bucket exists
    db.ensure_template_previews_bucket()
    print("[OK] template-previews bucket ready\n")

    # Get all IG presets (NL presets don't need rendering — they're HTML iframes)
    presets = db.get_preset_templates(template_type="instagram")
    print(f"Found {len(presets)} Instagram presets to render\n")

    success = 0
    failed = 0

    for preset in presets:
        pid = preset["id"]
        html = preset.get("html_content", "")
        ratio = preset.get("aspect_ratio", "1:1")
        name = preset.get("name", "?")

        if not html.strip():
            print(f"  SKIP  {name} (empty HTML)")
            continue

        print(f"  Rendering '{name}' ({ratio}) ...")
        try:
            result = render_template_preview(
                template_html=html,
                aspect_ratio=ratio,
            )

            urls = {}
            for slide_type, png_bytes in result.items():
                url = db.upload_template_preview_image(pid, slide_type, png_bytes)
                urls[slide_type] = url
                size_kb = len(png_bytes) / 1024
                print(f"    {slide_type}: uploaded ({size_kb:.1f} KB)")

            # Persist URLs in preset_templates.thumbnail_url
            db.update_preset_thumbnail_url(pid, json.dumps(urls))
            print(f"    \u2713 thumbnail_url updated with {len(urls)} URLs")
            success += 1

        except Exception as e:
            print(f"    \u2717 Error: {e}")
            failed += 1

    print(f"\n=== Done: {success} cached, {failed} failed ===")


if __name__ == "__main__":
    main()
