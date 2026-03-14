# DEEP TECHNICAL & PRODUCT REVIEW — Content AI Generator

**Reviewer**: Claude (Senior AI Product Architect + Full-Stack Engineer + Systems Reviewer)
**Date**: 2024-03-14
**Codebase snapshot**: `app.py` (3,964 lines), `carousel_renderer.py` (749 lines), `video_generator.py` (443 lines), `db.py` (1,175 lines), `auth.py`, `payments.py`, `security.py`, `templates/index.html` (9,432 lines — the entire SPA)

---

## SECTION 1 — HIGH-LEVEL PRODUCT UNDERSTANDING

### What the app currently does

Content AI Generator is a **multi-platform content repurposing engine** for an Italian-speaking AI/tech consultant audience. It:

1. **Ingests content** from three sources: RSS feeds (90+ curated sources), web search (via Serper API), or manual text/prompt input
2. **Scores and ranks** articles using LLM-based relevance scoring with user preference learning (keyword/source/category tracking)
3. **Generates platform-specific content** for LinkedIn, Instagram (carousel), Twitter/X, Newsletter (Beehiiv-compatible HTML), and Video Script
4. **Renders visual outputs**: Instagram carousels → PNG via Playwright; Newsletters → styled HTML; Video scripts → lip-sync talking-head video via fal.ai (MiniMax TTS + SadTalker)
5. **Manages the content lifecycle**: scheduling, notifications (ntfy.sh + email via Resend), approval tracking, weekly status dashboard
6. **Learns from feedback**: users can submit feedback per platform, which can be used to "enrich" (rewrite) the generation prompts permanently

### Intended product vision

A **one-person content studio** where a professional can:
- Select trending articles → generate content for 5 platforms in one session
- Customize visual templates (carousel slides, newsletter layouts) via a chat-based design interface
- Build a feedback loop that improves outputs over time
- Schedule and track content publishing

### Core value proposition

**"RSS to 5-platform content in minutes, not hours"** — turning a consultant's news reading habit into a content machine. The moat is supposed to be the personalization/template system + the feedback learning loop.

### UX confusion points

1. **"Personalizza" / Templates section conflates two different tasks**: (a) customizing the visual design of outputs, and (b) customizing the writing style/prompts. These are completely different workflows jammed into one concept.

2. **Template chat is an open-ended conversation with an LLM to generate HTML** — users have no mental model for what prompts will produce good results. The system prompt is 150+ lines of instructions, but the user sees a blank chat box.

3. **Newsletter has THREE different rendering paths** (component-based assembler, legacy LLM section parser, full LLM HTML generation) — the user has no visibility into which path is being used or why results differ.

4. **Feedback → prompt enrichment is invisible and irreversible**. The user submits feedback, selects some feedback items, clicks "enrich", and their prompt is permanently rewritten by an LLM. There's no diff view, no undo, no preview of the enriched prompt before it's saved.

5. **The entire frontend is a single 9,432-line HTML file** (`templates/index.html`). This is a monolithic SPA with inline CSS, inline JavaScript, and inline Jinja2 templates — making it extremely hard to maintain, debug, or iterate on UX.

---

## SECTION 2 — CURRENT ARCHITECTURE MAP

### Main modules

| File | Lines | Responsibility |
|------|-------|---------------|
| `app.py` | 3,964 | **Everything**: routes, LLM calls, prompt templates, RSS fetching, scoring, content generation, newsletter assembly, template chat, scheduling, retention, preferences, feedback, notifications, monitoring, background threads |
| `db.py` | 1,175 | Database abstraction (Supabase PostgreSQL via PostgREST) |
| `carousel_renderer.py` | 749 | Playwright-based HTML→PNG rendering for Instagram carousels |
| `video_generator.py` | 443 | TTS + lip-sync video pipeline (fal.ai) |
| `auth.py` | ~300 | Supabase Auth integration (JWT, OAuth, MFA) |
| `payments.py` | ~250 | Stripe integration, plan gating |
| `security.py` | ~200 | CORS, rate limiting, CSP headers, API key encryption, Sentry |
| `templates/index.html` | 9,432 | **Entire frontend SPA** (HTML + CSS + JS inline) |
| `templates/landing.html` | ~1,200 | Public landing page |

### Data flow: RSS → Content Generation

```
User clicks "Fetch Feeds"
  → POST /api/feeds/fetch
    → Background thread spawned
      → feedparser parses each RSS URL (sequential, one by one)
      → New articles collected (deduped by URL, filtered by date)
      → Articles scored in batches of 5 via MODEL_CHEAP
      → Preference bonus applied from selection_prefs table
      → Articles inserted into DB
    → SSE stream /api/feeds/progress reports progress to UI

User selects articles, picks platform(s)
  → POST /api/generate (per platform, per article)
    → Plan gating (platform access + generation limit)
    → Prompt assembled: system_prompt + format_{platform} + article + opinion + feedback
    → Single LLM call (MODEL_SMART, temperature=0.7)
    → Result returned as raw text
    → Weekly status incremented
    → Generation count incremented

For Instagram carousel:
  → POST /api/render-carousel
    → carousel_renderer.py: parse ---SLIDE--- text
    → Playwright launches Chromium, renders each slide HTML → PNG
    → PNG bytes uploaded to Supabase Storage
    → URLs returned to frontend

For Newsletter:
  → POST /api/generate-newsletter (topics → markdown text)
  → POST /api/newsletter/html (markdown text → HTML)
    → Three paths:
      (a) Component-based: deterministic markdown→HTML using template components
      (b) Legacy: LLM parses text into sections, injects into template placeholders
      (c) Default: LLM generates full HTML from scratch
```

### Data flow: Template/Personalize system

```
User creates a template (instagram or newsletter)
  → POST /api/templates (empty template created in DB)

User chats with the template
  → POST /api/templates/{id}/chat
    → System prompt: 150+ lines of HTML/CSS design instructions
    → Current HTML/JSON injected as system context
    → Last 14 chat messages included
    → LLM call (MODEL_FAST, temperature=0.4, expect_json=True)
    → Response parsed: extract { "reply": "...", "html": {...} }
    → For Instagram: html is a JSON with 4 keys (cover, content, list, cta)
    → For Newsletter: html is layout HTML + components (CSS map)
    → Updated template saved to DB
    → Preview cache invalidated

User requests preview
  → POST /api/templates/{id}/preview
    → Instagram: Playwright renders 4 slide types → base64 PNG gallery
    → Newsletter: assemble_newsletter_html() with sample markdown → HTML string
    → Cached in-memory by content hash

User uses template for rendering
  → /api/render-carousel with template_id → uses custom template HTML
  → /api/newsletter/html with template_id → uses template layout + components
```

### Synchronous vs Asynchronous flows

| Flow | Sync/Async |
|------|-----------|
| Content generation (/api/generate) | **Synchronous** — blocks request thread for 5-30s |
| Newsletter generation | **Synchronous** — blocks for 5-30s |
| Newsletter HTML conversion | **Synchronous** — blocks for 3-15s |
| Template chat | **Synchronous** — blocks for 5-30s |
| Template preview (Instagram) | **Synchronous** — Playwright render, blocks for 5-20s |
| Carousel rendering | **Synchronous** — Playwright render, blocks for 10-30s |
| RSS feed fetching | **Asynchronous** — background thread with SSE progress |
| Video generation | **Synchronous** — can block for 60-600s |
| Schedule checking | **Background thread** — polls every 30s |
| Retention cleanup | **Background thread** — runs every 6h |

**Critical observation**: Nearly everything user-facing is synchronous and blocking. A single Playwright render ties up a Flask worker for 10-30 seconds. On a service like Render with limited workers, this means 2-3 concurrent carousel renders can make the entire app unresponsive.

---

## SECTION 3 — FAILURE ANALYSIS

### Why the personalize/template system is unreliable

**Root cause #1: The LLM is asked to generate valid, pixel-perfect HTML/CSS inside a JSON string.**

This is the single biggest architectural mistake. The template chat system prompt (`app.py:3348-3436`) asks the LLM to return:
```json
{
  "reply": "...",
  "html": {
    "cover": "<!DOCTYPE html><html>...(full CSS + HTML)...</html>",
    "content": "<!DOCTYPE html><html>...</html>",
    "list": "<!DOCTYPE html><html>...</html>",
    "cta": "<!DOCTYPE html><html>...</html>"
  }
}
```

This means the LLM must:
- Generate valid JSON
- Where 4 of the values are complete HTML documents
- With proper CSS (including `@import`, gradients, complex layouts)
- With proper escaping of quotes inside JSON strings
- With proper placeholder syntax (`{{COVER_TITLE}}` etc.)
- All in a single response

The JSON parsing failure rate is high because:
- HTML contains quotes that break JSON
- CSS contains braces `{}` that confuse JSON parsers
- Long responses get truncated
- The model sometimes wraps in code fences despite instructions

**Root cause #2: No structured output enforcement.**

The system relies on `_llm_call_validated()` with `expect_json=True`, which tries to extract JSON after the fact. If extraction fails, it retries once with a scolding message. But JSON-with-embedded-HTML is fundamentally hard to validate — the JSON might parse but the HTML might be garbage.

**Root cause #3: No incremental editing — every change regenerates everything.**

The system prompt says "Ogni modifica → rigenera TUTTI e 4 i tipi con il JSON completo". So if the user says "make the title font bigger", the LLM regenerates all 4 slide types from scratch. This is:
- Wasteful (4x the tokens)
- Error-prone (unrelated slides may change)
- Inconsistent (the other slides may drift from previous versions)

**Root cause #4: No validation of the generated HTML.**

There is zero validation that the generated HTML will actually render correctly. No checks for:
- Missing closing tags
- Invalid CSS properties
- Text overflow (content doesn't fit in 1080x1080)
- Missing fonts (Google Fonts @import might fail in Playwright)
- Broken SVG (missing xmlns)
- Missing placeholder substitution

**Root cause #5: The preview render is synchronous and slow.**

Every template chat message that changes HTML triggers a Playwright render to generate the preview. This means:
- The user waits 5-20 seconds per chat iteration
- If Playwright crashes or times out, the user gets an error
- There's no loading state or progress indicator (beyond the client-side spinner)

### Other fragile points

1. **`app.py` is a 4,000-line monolith.** All routes, all business logic, all prompts, all utility functions are in one file. This makes it impossible to test, refactor, or reason about.

2. **Prompts are hardcoded as Python string constants** (`BASE_FORMAT_LINKEDIN`, etc.) — then copied to the DB on first user access. There's no versioning beyond the DB log. Updating a prompt requires code deployment.

3. **RSS fetch is sequential** — each feed is fetched one by one in a single thread. With 90+ feeds, this can take 5-10 minutes.

4. **LLM calls have no circuit breaker or rate limiting.** If OpenRouter is slow or down, every request blocks for the full 240s timeout.

5. **`_fetch_state` is an in-memory dict** — if the worker restarts during a fetch, the state is lost and the SSE stream hangs forever.

6. **Video generation writes to local disk** (`static/video_output/`) on an ephemeral host (Render). Files are lost on deploy.

7. **Background threads are started at module import time** (`_start_background_threads()` at line 3950). With Gunicorn using multiple workers, each worker runs its own schedule checker and retention cleanup — causing duplicate notifications and race conditions on DB updates.

8. **The in-memory preview cache (`_preview_cache`)** is per-worker — so with Gunicorn workers, each worker maintains its own cache, causing inconsistency and wasted memory.

9. **No request timeout enforcement.** Flask doesn't kill long-running handlers. A Playwright render that hangs blocks the worker forever.

10. **The newsletter assembler (`assemble_newsletter_html`)** does regex-based markdown parsing — it's not a real parser. Edge cases like nested bold+italic, multi-line list items, or code blocks will break.

11. **Search result scoring scores each result individually** with a separate LLM call (line 2118). For 10 results, that's 10 sequential API calls — extremely slow.

12. **`_sanitize_user_input`** is a regex-based sanitizer. It will catch simple prompt injection but misses Unicode homoglyphs, zero-width characters, and indirect injection via article content.

---

## SECTION 4 — DATA CONTRACTS

The codebase has **zero formal schemas or type definitions**. Everything is `dict` in, `dict` out. Here are the contracts that should exist:

### 1. Normalized Input Source

```json
{
  "id": "uuid",
  "source_type": "rss" | "web_search" | "custom_text" | "manual_prompt",
  "title": "string",
  "url": "string | null",
  "description": "string",
  "full_text": "string | null",
  "source_name": "string",
  "category": "string",
  "published_at": "ISO8601",
  "language": "it" | "en",
  "score": 1-10,
  "score_reason": "string",
  "preference_boost": 0.0-2.0,
  "metadata": {}
}
```

### 2. Content Strategy Plan

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "sources": ["NormalizedInputSource[]"],
  "platforms": ["linkedin", "instagram"],
  "opinion": "string | null",
  "quantity_per_platform": { "linkedin": 1, "instagram": 2 },
  "variant_angles": { "instagram": ["practical", "strategic"] },
  "custom_instructions": "string | null",
  "created_at": "ISO8601"
}
```

### 3. Per-Platform Content Job

```json
{
  "id": "uuid",
  "strategy_plan_id": "uuid",
  "platform": "linkedin",
  "source_id": "uuid",
  "variant_index": 0,
  "prompt_version": "uuid | int",
  "status": "pending" | "generating" | "completed" | "failed",
  "output": {
    "text": "string",
    "slides": ["string[]"] | null,
    "html": "string | null"
  },
  "model_used": "string",
  "tokens_used": { "input": 0, "output": 0 },
  "cost_estimate": 0.0,
  "created_at": "ISO8601",
  "completed_at": "ISO8601 | null"
}
```

### 4. Feedback Memory / Preference Memory

```json
{
  "user_id": "uuid",
  "feedback_entries": [
    {
      "id": "uuid",
      "platform": "linkedin",
      "scope": "one_off" | "platform_preference" | "brand_preference",
      "feedback_text": "string",
      "applied": false,
      "applied_to_prompt_version": null,
      "created_at": "ISO8601"
    }
  ],
  "brand_preferences": {
    "tone": "direct, practical, no-nonsense",
    "language": "it",
    "avoid": ["buzzwords", "hype"],
    "include": ["personal opinion", "concrete examples"],
    "industry_context": "AI consultant for Italian businesses"
  },
  "platform_preferences": {
    "linkedin": {
      "length": "200-300 words",
      "style_notes": ["no bullet points", "end with question"]
    }
  }
}
```

### 5. Design System / Visual Spec

```json
{
  "id": "uuid",
  "name": "Minimal Industrial",
  "type": "instagram" | "newsletter",
  "colors": {
    "primary": "#1a1a1a",
    "secondary": "#7c5ce7",
    "background": "#0f0c29",
    "text": "#ffffff",
    "text_muted": "rgba(255,255,255,0.7)",
    "accent": "#a29bfe"
  },
  "typography": {
    "heading_font": "Syne",
    "body_font": "Inter",
    "heading_weight": 800,
    "body_weight": 400,
    "heading_size": "68px",
    "body_size": "32px"
  },
  "spacing": {
    "padding": "80px",
    "gap": "24px"
  },
  "decorations": {
    "has_gradient_bg": true,
    "has_accent_line": true,
    "has_brand_footer": true,
    "corner_radius": "0px"
  },
  "images": {
    "logo_url": "https://...",
    "background_url": null
  }
}
```

### 6. Slide Plan

```json
{
  "template_id": "uuid",
  "slides": [
    {
      "type": "cover",
      "layout": "title_centered",
      "placeholders": {
        "COVER_TITLE": { "max_chars": 60, "font_size": "68px" },
        "COVER_SUBTITLE": { "max_chars": 80, "font_size": "24px" }
      }
    },
    {
      "type": "content",
      "layout": "header_body",
      "placeholders": {
        "CONTENT_HEADER": { "max_chars": 40, "font_size": "46px" },
        "CONTENT_BODY": { "max_chars": 200, "font_size": "28px" }
      }
    },
    {
      "type": "list",
      "layout": "header_bullets",
      "placeholders": {
        "LIST_HEADER": { "max_chars": 40 },
        "LIST_ITEMS": { "max_items": 5, "max_chars_per_item": 40 }
      }
    },
    {
      "type": "cta",
      "layout": "centered_button",
      "placeholders": {
        "CTA_TEXT": { "max_chars": 100 },
        "CTA_BUTTON": { "max_chars": 30 }
      }
    }
  ],
  "aspect_ratio": "1:1",
  "dimensions": { "width": 1080, "height": 1080 }
}
```

### 7. Image Generation Job

Currently not implemented. If you add AI image generation:

```json
{
  "id": "uuid",
  "template_id": "uuid",
  "purpose": "logo" | "background" | "slide_decoration" | "product_photo",
  "prompt": "string",
  "style": "minimal" | "photographic" | "illustration",
  "dimensions": { "width": 1080, "height": 1080 },
  "status": "pending" | "generating" | "completed" | "failed",
  "result_url": "string | null",
  "fallback_used": false,
  "provider": "fal.ai" | "replicate",
  "cost": 0.0
}
```

### 8. Renderer Input

```json
{
  "template_id": "uuid",
  "template_type": "instagram" | "newsletter",
  "content": {
    "slides": [
      { "type": "cover", "title": "...", "subtitle": "..." },
      { "type": "content", "header": "...", "body": "..." }
    ]
  },
  "design_system": "DesignSystemSpec",
  "brand": {
    "name": "string",
    "handle": "@string",
    "logo_url": "string | null"
  },
  "aspect_ratio": "1:1",
  "output_format": "png" | "html",
  "quality": "preview" | "final"
}
```

---

## SECTION 5 — RECOMMENDED TARGET ARCHITECTURE

### Opinion: What you should do

**Use a single orchestrator with deterministic renderers and background jobs.**

You do NOT need a multi-agent system. You have one user, one intent at a time, and a linear pipeline. Multi-agent orchestration would add complexity with zero benefit.

### Proposed architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     LAYER 1: INPUT NORMALIZATION            │
│  RSS Fetcher → Article Normalizer                           │
│  Web Search → Article Normalizer                            │
│  Custom Text → Article Normalizer                           │
│  Output: NormalizedInputSource                              │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                     LAYER 2: CONTENT PLANNING               │
│  Input: NormalizedInputSource[] + platform selection         │
│  Determines: platforms, quantities, variant angles           │
│  Output: ContentStrategyPlan → ContentJob[]                 │
│  (This layer is mostly deterministic — no LLM needed)       │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                     LAYER 3: CONTENT GENERATION             │
│  Input: ContentJob + user prompts + feedback context         │
│  LLM call per job (parallelizable!)                         │
│  Output: GeneratedContent                                   │
│  (This is where the LLM does its work)                      │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                     LAYER 4: RENDERING / EXPORT             │
│  Instagram: text → deterministic HTML template → Playwright │
│  Newsletter: markdown → deterministic assembler → HTML      │
│  LinkedIn/Twitter: text passthrough                         │
│  Video: text → TTS → lip-sync (background job)             │
│  Output: Rendered artifacts (PNG URLs, HTML string, etc.)   │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                     LAYER 5: FEEDBACK & LEARNING            │
│  Feedback collected per output                              │
│  Feedback → prompt enrichment (on-demand, with preview)     │
│  Preferences → separate persistent store                    │
│  Output: Updated prompts + preference signals               │
└─────────────────────────────────────────────────────────────┘
```

### Technology recommendations

| Concern | Recommendation |
|---------|---------------|
| **Background jobs** | Use **Redis + RQ** or **Celery** instead of daemon threads. Background threads in Gunicorn workers cause duplicate execution. |
| **Carousel rendering** | Keep Playwright but make it a **background job** that reports completion via polling or WebSocket. |
| **Template design** | Use a **structured design token system** + **deterministic HTML renderer** instead of LLM-generated HTML. The LLM should output a `DesignSystemSpec` JSON, and a deterministic renderer should turn that into HTML. |
| **Newsletter rendering** | Your `assemble_newsletter_html()` is the RIGHT approach. Lean into it harder — make ALL newsletter rendering go through this path. Kill the LLM HTML generation path. |
| **Frontend** | Split `index.html` into a real SPA framework (Vue, React, or even Alpine.js). 9,400 lines of inline JS/HTML is unmaintainable. |
| **API structure** | Split `app.py` into route modules: `routes/auth.py`, `routes/feeds.py`, `routes/generate.py`, `routes/templates.py`, `routes/schedule.py` |

---

## SECTION 6 — TEMPLATE/PERSONALIZE REBUILD PLAN

### The fundamental design change

**Stop asking the LLM to generate HTML.** Instead:

1. The LLM generates a **structured design specification** (JSON)
2. A **deterministic renderer** converts the spec into HTML

### Step-by-step rebuilt flow

#### Step 1: User describes their desired style

User types: "Create minimal-industrial carousel slides for a tech consulting brand"

#### Step 2: LLM generates a DesignSystemSpec

Instead of generating HTML, the LLM returns:
```json
{
  "reply": "Ho creato un design minimal-industrial con sfondo scuro e accenti metallici.",
  "design": {
    "colors": {
      "background": "linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 100%)",
      "primary": "#ffffff",
      "secondary": "rgba(255,255,255,0.6)",
      "accent": "#7c5ce7",
      "accent2": "#a29bfe"
    },
    "typography": {
      "heading_font": "Syne",
      "heading_weight": 800,
      "body_font": "Inter",
      "body_weight": 400
    },
    "layout": {
      "padding": 80,
      "has_accent_line": true,
      "accent_line_width": 64,
      "has_decorative_orbs": true,
      "has_slide_counter": true,
      "brand_position": "bottom"
    }
  }
}
```

#### Step 3: Deterministic renderer generates HTML from the spec

A Python function takes the DesignSystemSpec and generates the 4 slide HTML templates. This function is **pure code** — no LLM involved. It uses the spec values to fill in a parameterized template.

```python
def render_slide_html(spec: DesignSystemSpec, slide_type: str) -> str:
    colors = spec["colors"]
    typo = spec["typography"]
    layout = spec["layout"]

    css = f"""
    body {{
        background: {colors['background']};
        font-family: '{typo['body_font']}', sans-serif;
        color: {colors['primary']};
        padding: {layout['padding']}px;
    }}
    h1 {{ font-family: '{typo['heading_font']}'; font-weight: {typo['heading_weight']}; }}
    """
    # ... deterministic template per slide_type
```

#### Step 4: User iterates via chat

User says "make the accent color red" → LLM updates `design.colors.accent` to `#e94560` → deterministic renderer re-generates HTML → preview updated.

The LLM's job is now much simpler: update a JSON document. Not generate HTML.

#### Step 5: Preview and export

Preview uses the same Playwright render pipeline but with deterministic HTML — so it's consistent every time.

### Fallback strategies

- **If LLM fails to return valid JSON**: Use the previous DesignSystemSpec (no change)
- **If Playwright fails to render**: Return an error with the last successful preview cached
- **If image upload fails**: Keep the previous image URL and retry in background
- **If the user's design spec is too extreme** (e.g., font size 200px): Apply min/max constraints in the renderer, not in the LLM

### Newsletter template design

For newsletters, you've already started this with the component system. Complete it:

1. **Kill the legacy section-placeholder path** (the `{{SECTION_1}}`, `{{SECTION_2}}` pattern)
2. **Kill the "LLM generates full HTML" default path** (lines 2627-2659)
3. **Make the component-based assembler the ONLY path**
4. The LLM's job in template chat should be to update the component styles (CSS strings) and the layout HTML — but the layout HTML is a simple wrapper, not a full page
5. Add a library of preset component style sets (e.g., "Corporate Blue", "Warm Earthy", "Minimal Black") that users can start from

---

## SECTION 7 — FEEDBACK LOOP DESIGN

### Current state

Feedback is stored as free-text strings in the `feedback` table, tagged by platform. The "enrich" endpoint sends feedback + current prompt to the LLM and asks it to rewrite the prompt. The new prompt replaces the old one permanently.

### What's wrong

1. **No separation of feedback types** — "make it shorter" (one-off instruction) is stored the same as "always avoid buzzwords" (permanent preference)
2. **No preview before committing** — the enriched prompt is saved immediately
3. **Prompt bloat** — each enrichment adds instructions without removing any. After 10 enrichments, the prompt becomes a wall of contradictory instructions
4. **No rollback** — prompt versions are logged, but there's no UI to revert

### Proposed feedback memory design

```
FEEDBACK STORAGE (4 tiers):

1. ONE-OFF FEEDBACK (ephemeral)
   - Attached to a specific generation
   - Used as a "rewrite instruction" for regeneration
   - NOT stored permanently
   - NOT used to modify prompts
   - Example: "Make this shorter" → regenerate with this instruction appended

2. PLATFORM PREFERENCES (semi-permanent)
   - Persisted per platform
   - Extracted from explicit feedback like "LinkedIn posts should always end with a question"
   - Stored as structured rules, not free text
   - Injected into prompts at generation time as a "user preferences" section
   - Example: { "linkedin": { "ending": "question", "length": "short", "tone": "provocative" } }

3. BRAND PREFERENCES (permanent)
   - Cross-platform settings
   - Tone of voice, industry context, forbidden words, required elements
   - Set explicitly by the user via a settings page, not inferred from feedback
   - Example: { "tone": "direct", "language": "it", "industry": "AI consulting" }

4. PROMPT TEMPLATES (versioned, editable)
   - The actual prompts remain the source of truth
   - Users can EDIT prompts directly (power user feature)
   - "Enrich from feedback" becomes OPTIONAL, with preview and diff
   - Prompt versions are stored and user can revert
```

### How to avoid prompt bloat and drift

1. **Never modify the base prompt.** Instead, maintain a separate `user_overrides` section that is appended at generation time.
2. **Cap the user_overrides section** at ~500 tokens. If it grows beyond that, summarize it.
3. **Validate prompt coherence** periodically: use the LLM to check if the prompt has contradictory instructions (run this as a background check, not on every generation).
4. **Show prompt size** in the UI — so the user sees when their prompt is getting bloated.

---

## SECTION 8 — SCALABILITY / COST / LATENCY

### Performance bottlenecks

1. **Playwright carousel rendering** — launches a full Chromium browser per render. On Render's free/starter tiers, this is extremely memory-intensive and slow. Each render takes 10-30 seconds and ~300MB RAM.

2. **Sequential RSS fetching** — 90+ feeds fetched one by one. Should be parallelized (ThreadPoolExecutor or asyncio).

3. **Sequential search scoring** — each web search result scored with a separate LLM call. Should batch all results into one call (like article scoring does).

4. **Synchronous LLM calls blocking Flask workers** — with Gunicorn running 2-4 workers, a few concurrent users can exhaust all workers.

5. **`templates/index.html` is 410KB** — sent on every page load with `Cache-Control: no-cache, no-store`. This is ~400KB of uncacheable, uncompressed HTML on every request.

### Cost bottlenecks

1. **MODEL_SMART (Gemini 3.1 Pro Preview)** at $2/M input, $12/M output — used for ALL content generation. Each generation is ~2,000 input tokens + ~1,000 output tokens ≈ $0.016 per generation. At 50 generations/month (pro plan), that's ~$0.80/user/month. Manageable.

2. **Template chat** uses MODEL_FAST (Gemini 2.5 Flash) — much cheaper. But the system prompt is 150+ lines (~1,500 tokens), and the chat history can be 14 messages — so each message costs ~3,000 input tokens. At $0.15/M, that's ~$0.0005 per message. Cheap.

3. **Video generation** is the expensive part — fal.ai charges per inference. MiniMax TTS + SadTalker ≈ $0.10-0.50 per video. But this is gated to Pro+ plans.

4. **Playwright** has no direct cost but consumes significant compute resources on the hosting platform.

### What should be cached

| Data | TTL | Strategy |
|------|-----|----------|
| Rendered carousel previews | Until template changes | In-memory (current) → **move to Supabase Storage** |
| RSS articles | 24 hours | Already done (DB) |
| Newsletter HTML preview | Until template changes | Already done (in-memory) → **move to DB** |
| User prompts | Session-scoped | Already done (DB read per request) → **add request-scoped cache** |
| Preset template previews | Until preset changes | Already done (Supabase Storage, good) |

### What should be parallelized

- RSS fetching: use `ThreadPoolExecutor(max_workers=10)` for parallel feed parsing
- Multi-platform generation: generate all platforms in parallel (currently sequential API calls from frontend)
- Search result scoring: batch all results into one LLM call

### What should be deferred to background jobs

- Carousel PNG rendering → background job, poll for completion
- Video generation → background job (already takes minutes)
- Feedback enrichment → could be synchronous (fast), but show preview first
- Newsletter HTML assembly → fast enough to stay synchronous

---

## SECTION 9 — REFACTOR PRIORITY LIST

### P0 — Must fix immediately

**P0.1: Split `app.py` into modules**
- **Impact**: Without this, every other change is dangerous. 4,000 lines in one file means high merge conflict risk, no test isolation, and no separation of concerns.
- **Effort**: Medium (2-3 days). Create `routes/`, `services/`, move code.
- **Risk if ignored**: Development velocity drops to near-zero. Every change risks breaking unrelated features.

**P0.2: Fix duplicate background threads in Gunicorn**
- **Impact**: Schedule notifications are sent multiple times. Retention cleanup runs per-worker.
- **Effort**: Low (1 day). Use a lock file, Redis lock, or single-worker flag.
- **Risk if ignored**: Users get duplicate notifications. Data might be deleted prematurely.

**P0.3: Make Playwright rendering async / background job**
- **Impact**: Currently blocks Flask workers for 10-30s. 2-3 concurrent renders = app is down.
- **Effort**: Medium (2-3 days). Add Redis + RQ, create render worker.
- **Risk if ignored**: App becomes unusable under light load. Users get timeouts.

### P1 — Should fix soon

**P1.1: Replace LLM-generated HTML in template system with design tokens + deterministic renderer**
- **Impact**: Template personalization becomes reliable. No more JSON parsing failures.
- **Effort**: High (1-2 weeks). Design the spec schema, build the renderer, migrate templates.
- **Risk if ignored**: The personalize feature remains broken and unshippable.

**P1.2: Kill the legacy newsletter rendering paths**
- **Impact**: One code path instead of three. Fewer bugs, simpler mental model.
- **Effort**: Low (1 day). Remove lines 2583-2625 and 2627-2659, make component-based path the default.
- **Risk if ignored**: Users get inconsistent newsletter output depending on hidden conditions.

**P1.3: Split `templates/index.html` into a real frontend**
- **Impact**: Frontend development becomes possible. Currently, any UI change requires editing a 9,400-line file.
- **Effort**: High (2-4 weeks to set up build pipeline + migrate). Could start with Alpine.js components.
- **Risk if ignored**: UI iteration speed is near-zero. Bug fixes in the frontend are nightmares.

**P1.4: Add structured feedback tiers**
- **Impact**: Feedback actually improves outputs instead of bloating prompts.
- **Effort**: Medium (3-5 days). Schema changes, new endpoints, updated UI.
- **Risk if ignored**: Prompt quality degrades over time as users provide more feedback.

**P1.5: Parallelize RSS fetching**
- **Impact**: Feed refresh drops from 5-10 minutes to 30-60 seconds.
- **Effort**: Low (half day). Replace sequential loop with ThreadPoolExecutor.
- **Risk if ignored**: Users wait too long, abandon the feature.

### P2 — Later improvements

**P2.1: Add proper queue system (Redis + RQ or Celery)**
- **Impact**: Reliable background processing, no duplicate execution, retry logic.
- **Effort**: Medium (3-5 days).

**P2.2: Add request-scoped caching for user prompts and subscription info**
- **Impact**: Reduces DB round-trips from ~5-8 per generation to ~2-3.
- **Effort**: Low (1 day).

**P2.3: Add structured output (JSON mode) for LLM calls**
- **Impact**: Reduces JSON parsing failures. OpenRouter supports `response_format: { type: "json_object" }`.
- **Effort**: Low (1 day). Add to `_llm_call()`.

**P2.4: Move video output to Supabase Storage**
- **Impact**: Videos survive deploys on ephemeral hosting.
- **Effort**: Low (half day).

**P2.5: Add proper logging (structured JSON) and observability**
- **Impact**: Debug production issues. Currently, logs go to `pipeline_logs` table and `video.log` file — inconsistent.
- **Effort**: Medium (2-3 days).

**P2.6: Rate limit LLM calls per user**
- **Impact**: Prevent cost runaway if a user scripts the API.
- **Effort**: Low (1 day). Already have rate limiting infra in security.py.

---

## SECTION 10 — EXACT CODE CHANGES TO START WITH

### Change 1: Split app.py into route modules

Create this structure:
```
routes/
  __init__.py      # Flask blueprint registration
  auth.py          # Lines 867-1234 from app.py
  feeds.py         # Lines 1463-1848 from app.py
  generate.py      # Lines 2137-2660 from app.py
  templates.py     # Lines 3242-3905 from app.py
  schedule.py      # Lines 2666-2741 from app.py
  feedback.py      # Lines 2872-2944 from app.py
  monitor.py       # Lines 3119-3220 from app.py
  settings.py      # Lines 1369-1457 from app.py
services/
  llm.py           # _llm_call, _llm_call_validated, _strip_fences, _extract_html
  prompts.py       # BASE_PROMPTS, _get_prompt, _ensure_user_prompts, _enrich_prompt_with_feedback
  scoring.py       # Article scoring, preference bonus calculation
  newsletter.py    # assemble_newsletter_html + markdown parsing
  scheduler.py     # _check_schedules background task
  retention.py     # _retention_cleanup background task
```

### Change 2: Add `response_format` to LLM calls expecting JSON

In `app.py:334-357`, modify `_llm_call()`:

```python
def _llm_call(messages, model=MODEL_CHEAP, temperature=0.3, json_mode=False):
    payload = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    # ... rest unchanged
```

Then use `json_mode=True` in template chat, article scoring, smart brief, and search scoring.

### Change 3: Parallelize RSS fetching

In `app.py:1716`, replace the sequential loop:

```python
# Current (sequential):
for fi in feed_items:
    # ... fetch one by one

# Proposed (parallel):
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_single_feed(fi):
    # ... move the per-feed logic here
    return results

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(fetch_single_feed, fi): fi for fi in feed_items}
    for future in as_completed(futures):
        fi = futures[future]
        try:
            results = future.result()
            new_articles.extend(results)
            progress.append(f"  → {len(results)} articles from {fi['name']}")
        except Exception as e:
            progress.append(f"  ⚠ Error: {e}")
```

### Change 4: Kill legacy newsletter paths

In `app.py:2559-2659`, the `/api/newsletter/html` route has three paths. Remove the legacy LLM path and the default LLM path:

- **Keep**: Lines 2577-2581 (component-based assembler)
- **Remove**: Lines 2583-2625 (legacy placeholder path)
- **Remove**: Lines 2627-2659 (default LLM HTML generation path)
- **Add**: If no template_id provided, use a default built-in layout with the component assembler

### Change 5: Fix background thread duplication

In `app.py:3932-3950`, the background threads start on module import. Fix:

```python
import os

def _start_background_threads():
    global _bg_started
    if _bg_started or not db.is_configured():
        return

    # Only start background threads in the first Gunicorn worker
    # Gunicorn sets GUNICORN_WORKER_ID or we can use a file lock
    worker_id = os.environ.get("GUNICORN_WORKER_ID", "0")
    if worker_id != "0":
        return

    _bg_started = True
    # ... start threads
```

Or better: move to a separate `worker.py` process that runs independently from the web server.

### Change 6: Add `Cache-Control` to `index.html`

In `app.py:853-860`, the SPA is served with `no-cache`. At minimum, add ETag support or version the URL:

```python
@app.route("/app")
def app_dashboard():
    resp = make_response(render_template("index.html"))
    # Allow caching with revalidation instead of no-cache
    import hashlib
    content = resp.get_data()
    etag = hashlib.md5(content).hexdigest()[:16]
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, must-revalidate"
    return resp
```

---

## APPENDIX A — SIMPLIFIED ARCHITECTURE DIAGRAM

```
                    ┌─────────────────┐
                    │   FRONTEND SPA  │
                    │  (index.html)   │
                    └────────┬────────┘
                             │ HTTP/JSON
                    ┌────────▼────────┐
                    │   FLASK API     │
                    │   (app.py)      │
                    ├─────────────────┤
              ┌─────┤ Auth Middleware  ├─────┐
              │     └─────────────────┘     │
    ┌─────────▼──────┐  ┌──────────────▼──────┐
    │  CONTENT ROUTES │  │  TEMPLATE ROUTES    │
    │  /generate      │  │  /templates/chat    │
    │  /generate-news │  │  /templates/preview │
    │  /newsletter    │  │  /render-carousel   │
    └─────────┬──────┘  └──────────┬──────────┘
              │                     │
    ┌─────────▼──────┐  ┌──────────▼──────────┐
    │   LLM SERVICE  │  │  PLAYWRIGHT RENDERER│
    │  (OpenRouter)  │  │  (carousel_renderer)│
    │                │  │                     │
    │  MODEL_SMART   │  │  HTML → PNG bytes   │
    │  MODEL_CHEAP   │  │  (synchronous!)     │
    │  MODEL_FAST    │  │                     │
    └────────────────┘  └─────────────────────┘
              │
    ┌─────────▼──────┐  ┌─────────────────────┐
    │   SUPABASE DB  │  │  EXTERNAL SERVICES  │
    │  (PostgreSQL)  │  │  - Serper (search)  │
    │  - articles    │  │  - fal.ai (video)   │
    │  - sessions    │  │  - ntfy.sh (push)   │
    │  - templates   │  │  - Resend (email)   │
    │  - feedback    │  │  - Stripe (payments)│
    │  - schedules   │  │                     │
    └────────────────┘  └─────────────────────┘
              │
    ┌─────────▼──────┐
    │ SUPABASE STORAGE│
    │  - carousel PNGs│
    │  - template imgs│
    └────────────────┘
```

## APPENDIX B — BIGGEST TECHNICAL DEBTS

1. **`app.py` is a 4,000-line god file** — all business logic, all routes, all prompts in one file
2. **`templates/index.html` is a 9,400-line monolithic SPA** — no build system, no components, no tests
3. **Template system generates HTML via LLM** — unreliable, unpredictable, unvalidated
4. **No background job system** — daemon threads in Flask workers cause duplication and memory leaks
5. **All rendering is synchronous** — Playwright blocks request threads for 10-30 seconds
6. **No formal data contracts** — everything is `dict`, no validation, no type safety
7. **Three different newsletter rendering paths** — confusing, inconsistent output
8. **Video files written to ephemeral local disk** — lost on every deploy
9. **In-memory state (`_fetch_state`, `_preview_cache`)** — not shared across workers, lost on restart
10. **No automated tests** — zero test files found in the repository

## APPENDIX C — BIGGEST PRODUCT/UX MISTAKES

1. **"Personalizza" means two unrelated things** — visual template design AND writing style preferences. Users don't know where to go.
2. **Template chat is an unstructured blank canvas** — users don't know what to ask for. No examples, no presets to start from, no guided flow.
3. **Feedback enrichment is invisible and permanent** — users can't preview changes, can't undo, can't see the diff.
4. **No progress indicators for long operations** — carousel rendering, video generation, and template preview show only a spinner with no ETA or step-by-step progress.
5. **Everything is in Italian** — error messages, system prompts, UI text. This limits the addressable market significantly.
6. **The content generation flow requires 5+ clicks** — fetch feeds → select articles → select platform → add opinion → generate → view result. Each step is a separate UI state.
7. **No draft/preview before generation** — the user clicks "generate" and gets a final output. No ability to preview the prompt or adjust before spending tokens.
8. **Plan gating errors appear as modal alerts** — instead of gracefully showing upgrade prompts inline.

## APPENDIX D — QUICK WINS (High Impact, Low Effort)

1. **Add `response_format: {"type": "json_object"}` to all JSON-expecting LLM calls** — 1 hour of work, eliminates 50%+ of JSON parsing failures.

2. **Parallelize RSS fetching with `ThreadPoolExecutor(max_workers=10)`** — 2 hours of work, 10x faster feed refresh.

3. **Kill the two legacy newsletter rendering paths** — 30 minutes, eliminates confusion and bugs.

4. **Add 5-10 preset design token sets** for the template system — users start from a preset instead of a blank canvas. Even before rebuilding the architecture, presets give users a starting point.

5. **Add ETag caching for `index.html`** — 15 minutes, saves 410KB on every page load for returning users.

6. **Batch search result scoring into one LLM call** — 1 hour, reduces 10 sequential API calls to 1.

7. **Add a "revert prompt" button** in the feedback enrichment UI — 1 hour, uses existing `prompt_logs` data.

8. **Show a diff view** when enriching prompts — 2 hours, builds trust that the system isn't corrupting their prompts.

9. **Add step-by-step progress for video generation** — 2 hours, use SSE like the feed fetcher does.

10. **Move video output to Supabase Storage** — 1 hour, fixes the "files lost on deploy" problem.
