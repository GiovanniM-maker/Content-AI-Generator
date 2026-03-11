# Content AI Generator -- Complete Functional Specification

**Version:** 1.0
**Date:** 2026-03-11
**Scope:** Full application behavior, architecture, user journey, features, data flow, security, and known issues.

---

## 1. Architecture

### 1.1 Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | Single-page application (SPA) embedded in a single HTML file (`templates/index.html`, ~5712 lines). Dark-themed, glassmorphism CSS. All JavaScript is inline. |
| **Backend** | Python Flask (`app.py`, ~1900 lines). Serves the SPA and exposes a REST API under `/api/`. |
| **Database** | Supabase (PostgreSQL + Row Level Security). Accessed via `supabase-py` client using the `service_role` key. |
| **Authentication** | Supabase Auth (email/password). JWTs stored in `localStorage` on the client. Server validates JWTs on every `/api/` request. |
| **LLM (AI Models)** | OpenRouter API. Two models are used: Google Gemini 2.0 Flash (`google/gemini-2.0-flash-001`) for article scoring, and Anthropic Claude Sonnet 4.5 (`anthropic/claude-sonnet-4-5`) for content generation. |
| **Web Search** | Serper API (Google Search wrapper) for the "Web Search" source mode. |
| **Push Notifications** | ntfy.sh (self-hosted or public topic-based push notifications). |
| **Payments** | Stripe (Checkout Sessions, Customer Portal, Webhooks). |
| **Image Rendering** | `carousel_renderer` module (separate Python module, renders Instagram carousel slide images server-side). |
| **Security** | AES-256 encryption for user API keys via a `security` module. Sentry for error tracking. Rate limiting via `flask-limiter`. CORS and security headers. |
| **Hosting** | Render (canonical URL: `content-ai-generator-1.onrender.com`). |

### 1.2 File Structure

| File | Purpose |
|---|---|
| `app.py` | Flask application: all routes, business logic, LLM calls, RSS fetching, scheduling, prompt management. |
| `db.py` | Database abstraction layer: all Supabase CRUD operations, organized by table/entity. |
| `schema.sql` | Database schema: 13 tables, indexes, RLS policies, triggers, helper functions. |
| `templates/index.html` | Complete frontend: CSS (~1700 lines), HTML body (~700 lines), JavaScript (~3300 lines). |

### 1.3 Supporting Modules (Imported but not in codebase)

- `auth` -- Authentication helper (signup, login, token validation)
- `payments` -- Stripe integration (checkout, portal, webhooks, subscription management)
- `security` -- AES-256 encryption/decryption for API keys, security headers
- `carousel_renderer` -- Server-side image generation for Instagram carousel slides

### 1.4 Request Flow

```
Browser (SPA)
  |
  |-- localStorage: cd_auth (access_token, refresh_token, user)
  |-- fetch() wrapper auto-injects Authorization: Bearer <token>
  |
  v
Flask (/api/* routes)
  |
  |-- _before_request_auth(): extracts JWT, validates via Supabase, sets g.user_id
  |
  v
db.py (Supabase client using service_role key)
  |
  v
Supabase (PostgreSQL with RLS)
```

---

## 2. User Journey (Step by Step)

### 2.1 First Visit (Unauthenticated)

1. User navigates to `/app` (or `/`).
2. The auth overlay is displayed, showing a **landing page** with:
   - Hero section with value proposition (in Italian).
   - "How it works" section (3 steps: Select, Generate, Publish).
   - Features grid.
   - Pricing section with monthly/annual toggle (Free, Pro, Business).
   - FAQ accordion.
   - Footer with Terms of Service and Privacy Policy links.
3. A floating card overlays the landing page with login/register forms.
4. User can toggle between "Accedi" (Login) and "Registrati" (Register).

### 2.2 Registration Flow

1. User enters name, email, password, clicks "Registrati".
2. Client `POST /auth/signup` with `{email, password, full_name}`.
3. Server creates user via Supabase Auth.
4. Database trigger `handle_new_user()` fires and auto-creates:
   - `profiles` row (id, email, full_name).
   - `subscriptions` row (plan='free', status='active').
   - `feeds_config` row (empty categories).
   - `selection_prefs` row (default empty counters).
5. If email confirmation is required, user sees a confirmation message.
6. If auto-login is enabled, tokens are stored and user proceeds to the dashboard.

### 2.3 Login Flow

1. User enters email and password, clicks "Accedi".
2. Client `POST /auth/login`.
3. On success, `access_token`, `refresh_token`, and `user` object are stored in `localStorage` under key `cd_auth`.
4. `onAuthSuccess()` is called which:
   - Hides the auth overlay.
   - Updates the topbar user pill (first name + avatar initial).
   - Loads the weekly status banner.
   - Starts notification polling (every 60 seconds).
   - Checks onboarding status (launches guided tour if first time).

### 2.4 Onboarding Tour

On first login (if `localStorage.onboarding_completed` is not set), a 5-step interactive tour launches:

1. **Source modes** -- Explains RSS, Web Search, Custom Text.
2. **Opinion field** -- Explains how personal opinion is integrated into generated content.
3. **Platform selector** -- Shows LinkedIn, Instagram, Twitter, Newsletter, Video Script.
4. **Generate button** -- Explains the generation process (~60 seconds).
5. **Library tab** -- Explains history, settings, and monitoring.

Each step highlights the relevant UI element with a spotlight effect and a tooltip.

### 2.5 Authenticated Dashboard

The main dashboard has three top-level tabs:

1. **Crea** (Create) -- Content source selection, generation, and results.
2. **Pianifica** (Plan) -- Calendar and list views of scheduled content.
3. **Libreria** (Library) -- History, Settings, and Monitor sub-sections.

A **weekly status banner** appears at the top showing per-platform counts of generated, approved, scheduled, and published content for the current week.

A **usage counter** in the topbar shows remaining generations (e.g., "7/10 gen" for free plan, "unlimited" for business).

A **notification bell** in the topbar shows unread notification count with a dropdown panel.

### 2.6 Content Creation Flow

#### Step 1: Choose Source

The user selects one of three source modes:

**Web Search (default):**
1. User enters a search query and clicks "Cerca".
2. Client `POST /api/search` sends the query.
3. Server calls Serper API, returns up to 10 results.
4. Results are immediately sent to `POST /api/search/score` for AI scoring.
5. Server uses Gemini Flash to score each result on a 1-10 scale.
6. Scored results are displayed as selectable cards showing title, snippet, source, score, and score reason.
7. User selects 1-3 results (click to toggle selection).

**RSS Feeds:**
1. User clicks "Aggiorna Feed" to fetch latest articles.
2. Client `POST /api/feeds/fetch` triggers a background thread.
3. Progress is streamed via Server-Sent Events (`GET /api/feeds/progress`).
4. For each configured feed: fetch via `feedparser`, insert articles into DB.
5. Each batch of articles is scored by Gemini Flash.
6. Scored articles appear in a categorized list, filterable by minimum score.
7. Articles show title, source, relevance score (with boost badge if applicable), and summary.
8. User selects 1-3 articles.

**Custom Text:**
1. User types or pastes text into a textarea (with character counter).
2. Clicks "Genera da testo" to proceed directly to generation.
3. A pseudo-article object is created from the text.

#### Step 2: Add Opinion and Select Platforms

1. User writes an optional opinion in the "La tua opinione" textarea.
2. User selects target platforms by clicking platform buttons:
   - LinkedIn (free plan)
   - Instagram (pro plan)
   - Twitter/X (pro plan)
   - Newsletter (free plan)
   - Video Script (pro plan)
3. Locked platforms show a lock badge and display a toast when clicked.

#### Step 3: Generate Content

1. User clicks the generate button.
2. The results section scrolls into view with a progress bar showing:
   - Status text (e.g., "LinkedIn #1 completato").
   - Progress percentage.
   - ETA based on elapsed time per call (~8 seconds average).
3. Generation requests fire in parallel for LinkedIn, Instagram, Twitter, and Video Script.
4. Newsletter generation fires sequentially after all others complete (it needs all topics).
5. Each `POST /api/generate` call includes: article data, user opinion, format type, optional feedback.
6. Server loads the user's customized prompt (or base prompt), injects the article and opinion, calls Claude Sonnet 4.5 via OpenRouter.
7. A session is auto-saved to the database with all content, carousel images, and platform selections.
8. Selection preferences are tracked via `POST /api/track-selections`.

#### Step 4: Review and Refine

For each generated content piece, the user can:

- **Edit** the text directly in a textarea (auto-saves after 1 second of inactivity).
- **Copy** to clipboard.
- **Integrate Opinion** -- Re-generates the content with a specific opinion for that piece.
- **Feedback & Regenerate** -- Provide textual feedback and regenerate. The feedback is sent as an additional parameter to the generation endpoint. Feedback is also stored in the `feedback` table for later prompt enrichment.
- **Approve** -- Mark content as approved (toggleable). Tracked in weekly status.
- **Schedule** -- Pick a date/time and schedule for later.

Instagram carousels additionally show:
- Rendered slide images (via server-side carousel renderer).
- Slide navigation (prev/next arrows, dots).
- Download button (downloads all slides as PNG files).
- Re-render button (regenerates images with new styling).

Newsletter additionally shows:
- HTML Preview button (opens a modal with iframe preview).
- Toggle between rendered preview and raw HTML source code.
- Copy HTML and Copy Plain Text buttons.

#### Step 5: Bulk Scheduling

At the bottom of the results, a "Bulk Schedule" section lets the user:
1. Pick a date/time.
2. Click "Programma tutti gli approvati" to schedule all approved content at once.
3. `POST /api/schedule/bulk` creates schedule entries for each approved item.

---

## 3. Features (Detailed)

### 3.1 Authentication

**UI:** Login and register forms in a floating card on the auth overlay. Enter key submits the active form.

**API Routes:**
- `POST /auth/signup` -- Creates user, returns tokens or confirmation message.
- `POST /auth/login` -- Validates credentials, returns `access_token`, `refresh_token`, `user`.
- `POST /auth/refresh` -- Refreshes an expired access token using the refresh token.
- `POST /auth/logout` -- Server-side logout.
- `GET /auth/me` -- Returns current user info.

**Client Behavior:**
- `fetch()` is monkey-patched to auto-inject `Authorization: Bearer <token>` header on all `/api/` requests.
- On 401 response, the client attempts token refresh. If refresh fails, it clears auth data and shows the login overlay.
- `?landing` URL parameter forces the landing page view even when authenticated.

**DB Tables:** `profiles`, `subscriptions`.

### 3.2 Payment & Subscription System

**Plans:**
| Plan | Monthly Price | Generations | Platforms |
|---|---|---|---|
| Free | 0 | 10 lifetime | LinkedIn, Newsletter |
| Pro | Configurable | 50/month | All 5 platforms |
| Business | Configurable | Unlimited | All 5 platforms |

**UI:**
- Pricing section in the landing page with monthly/annual toggle.
- Pricing modal accessible from within the app via `openPricing()`.
- Usage bar in the topbar showing remaining/used generations.
- Locked platform badges on unavailable platforms.
- Auto-opens pricing modal when a plan limit error is received from the API.

**API Routes:**
- `GET /api/plans` -- Returns plan definitions and current user plan.
- `POST /api/checkout` -- Creates a Stripe Checkout session, returns redirect URL.
- `POST /api/billing/portal` -- Creates a Stripe Customer Portal session.
- `GET /api/subscription` -- Returns subscription details, usage info, and plan details.
- `POST /stripe/webhook` -- Handles Stripe webhook events for subscription lifecycle.

**Click Behavior:**
- "Upgrade a Pro/Business" button calls `startCheckout(plan)`, which redirects to Stripe Checkout.
- On successful payment, URL param `?payment=success` triggers a success banner and usage reload.
- "Gestisci abbonamento" opens Stripe Customer Portal in a new tab.

**DB Tables:** `subscriptions`, `profiles` (stores `stripe_customer_id`).

### 3.3 Content Sources

#### 3.3.1 Web Search

**UI:** Search input + "Cerca" button. Results area with selectable cards. Selection bar with count and generate button.

**API Routes:**
- `POST /api/search` -- Sends query to Serper API, returns raw results.
- `POST /api/search/score` -- Scores results using Gemini Flash LLM.

**Click Behavior:**
1. User types query, clicks "Cerca" (or Enter).
2. `webSearch()` calls `/api/search`, then `/api/search/score`.
3. `renderSearchResults()` displays scored results.
4. Clicking a result toggles selection (max 3).
5. `updateWebSearchBar()` enables/disables the generate button.

**DB Tables:** `articles` (scored results are inserted with `source_mode='web_search'`).

#### 3.3.2 RSS Feeds

**UI:** "Aggiorna Feed" button. Log area showing progress. Article list grouped by category with score filter.

**API Routes:**
- `POST /api/feeds/fetch` -- Triggers background RSS fetch thread.
- `GET /api/feeds/progress` -- SSE endpoint streaming progress messages.
- `GET /api/articles?min_score=N` -- Returns scored articles filtered by minimum score.

**Click Behavior:**
1. Click "Aggiorna Feed" triggers `fetchFeeds()`.
2. Progress messages stream in real-time.
3. On completion, a link to view articles appears.
4. Articles are displayed via `loadTopics()` with category grouping.
5. Click an article card to toggle selection (max 3).
6. Selection bar shows count and "Genera" button.

**RSS Processing (Server):**
1. For each feed URL in user's `feeds_config`, `feedparser` fetches and parses.
2. New articles (not already in DB) are inserted in batches of 50.
3. Each batch is scored by Gemini Flash (JSON output with score, summary, category, score_reason).
4. Scores are updated in the database.

**DB Tables:** `articles`, `feeds_config`.

#### 3.3.3 Custom Text

**UI:** Textarea with character counter. "Genera da testo" button.

**Click Behavior:**
1. User types text.
2. `generateFromCustomText()` creates a pseudo-article object with `source_mode='custom_text'`.
3. Proceeds directly to generation.

**DB Tables:** None directly (content flows through sessions).

### 3.4 Smart Brief (AI Suggestions)

**UI:** Collapsible panel in the Crea tab, visible only when the user has made 3+ article selections. Shows confidence percentage, top keywords, and AI-generated content suggestions.

**API Route:** `GET /api/smart-brief` -- Returns suggestions based on selection history.

**Server Logic:**
1. Loads user's `selection_prefs` (source counts, category counts, keyword counts).
2. Calculates confidence score based on total selections.
3. Calls Gemini Flash to generate 3-5 content suggestions with titles, hooks, platform recommendations, and urgency levels.

**Click Behavior:**
- Clicking the header toggles the body.
- Clicking a suggestion switches to Custom Text mode and pre-fills the textarea.

**DB Tables:** `selection_prefs`.

### 3.5 Content Generation

**UI:** Progress bar with status text, percentage, and ETA. Results displayed as content cards per platform.

**API Routes:**
- `POST /api/generate` -- Generates content for a single platform+article combination.
- `POST /api/generate-newsletter` -- Generates a newsletter from multiple topics.
- `POST /api/newsletter/html` -- Converts newsletter markdown to styled HTML.

**Generation Flow (Server):**
1. Load user prompt for the requested format (or use base prompt).
2. Build system prompt: `BASE_SYSTEM_PROMPT` + format-specific prompt.
3. Build user message with article data, opinion, and optional feedback.
4. If feedback is provided, store it in `feedback` table.
5. Call OpenRouter with Claude Sonnet 4.5.
6. Return generated content.
7. Log the generation in `pipeline_logs`.
8. Increment `weekly_status` counter for the platform.
9. Check generation limits based on plan.

**Prompts (All in Italian):**
- `BASE_SYSTEM_PROMPT` -- Defines the AI persona as an Italian content strategist.
- `format_linkedin` -- LinkedIn post with hook, body, CTA, hashtags.
- `format_instagram` -- Instagram carousel with `---SLIDE---` and `---CAPTION---` separators.
- `format_twitter` -- Tweet or thread with `---TWEET---` separators.
- `format_newsletter` -- Weekly newsletter in markdown format.
- `format_video_script` -- Video script for Reels/TikTok/Shorts with `---SECTION---` separators.

**DB Tables:** `sessions`, `feedback`, `pipeline_logs`, `weekly_status`, `user_prompts`.

### 3.6 Carousel Rendering

**UI:** Image viewer within Instagram content cards. Navigation arrows, dots, slide counter. Download and re-render buttons.

**API Route:** `POST /api/render-carousel` -- Renders carousel slides as images.

**Client Behavior:**
1. After generation, `renderAllCarouselImages()` sends each carousel text to the server.
2. Server uses `carousel_renderer` module to generate PNG images.
3. Images are displayed in a viewer with navigation.
4. Download triggers sequential blob downloads of all slides.
5. Re-render regenerates images and updates the viewer.

**DB Tables:** `sessions` (carousel_images stored as JSONB).

### 3.7 Feedback & Regeneration

**UI:** Collapsible feedback row per content piece with textarea and "Rigenera" button.

**Click Behavior:**
1. Click "Feedback" to expand the feedback row.
2. Type feedback describing desired changes.
3. Click "Rigenera" to regenerate with feedback context.
4. Feedback is stored for later prompt enrichment.

**API Routes:**
- `POST /api/generate` (with `feedback` parameter) -- Regenerates content incorporating feedback.
- `POST /api/feedback` -- Stores feedback entry.
- `GET /api/feedback` -- Returns all feedback grouped by format type.
- `DELETE /api/feedback/<format>/<id>` -- Deletes a specific feedback entry.

**DB Tables:** `feedback`.

### 3.8 Prompt Customization & Enrichment

**UI:** Monitor tab > Prompts section shows a versioned changelog with LCS-based diffs. Feedback Memory section shows collected feedback with checkboxes for enrichment.

**API Routes:**
- `GET /api/monitor/prompts` -- Returns prompt version history.
- `POST /api/prompts/enrich` -- Takes selected feedback IDs and enriches the corresponding prompt.

**Enrichment Flow (Server):**
1. Load current prompt for the specified format.
2. Load selected feedback entries.
3. Call Claude Sonnet 4.5 to generate an improved prompt incorporating the feedback.
4. Save new prompt version with trigger='enrichment'.
5. Log new version in `prompt_logs`.
6. Mark feedback entries as enriched (set `enriched_at`).

**Prompt Initialization:**
On first use, `init_user_prompts()` copies base prompts to the user's `user_prompts` table, creating personalized copies.

**DB Tables:** `user_prompts`, `prompt_logs`, `feedback`.

### 3.9 Scheduling & Calendar

**UI:**
- **Calendar View:** Weekly grid (Mon-Sun, 06:00-23:00) with colored event blocks by platform. Week navigation arrows. Click event to open detail modal.
- **List View:** Chronological list of scheduled items with platform badge, title, date, status badge, and action buttons.

**API Routes:**
- `POST /api/schedule` -- Creates a single schedule entry.
- `POST /api/schedule/bulk` -- Creates multiple schedule entries at once.
- `GET /api/schedule` -- Returns all scheduled items for the user.
- `DELETE /api/schedule/<id>` -- Removes a schedule entry.
- `POST /api/schedule/<id>/publish` -- Marks an entry as published.
- `GET /api/schedule/<id>/content` -- Returns the full content for a scheduled item (loads from the linked session).

**Calendar Detail Modal:**
- Shows platform, date, status, and full content in a textarea.
- Delete button (hidden if already published).
- Close on overlay click or Escape key.

**Background Schedule Checker:**
A daemon thread runs every 30 seconds on the server:
1. Queries all `pending` schedule entries where `scheduled_at <= now()`.
2. For each due item, sends a push notification via ntfy.sh to the user's configured topic.
3. Updates status to `notified`.
4. Creates an in-app notification.
5. Increments the `scheduled` counter in weekly status.

**Statuses:** `pending` -> `notified` -> `published`.

**DB Tables:** `schedules`, `sessions` (content retrieval), `notifications`, `weekly_status`.

### 3.10 Session Management

**UI:** History section in the Library tab. Sessions displayed as expandable cards with inline content previews. Search and filter capabilities.

**API Routes:**
- `GET /api/sessions` -- Returns all sessions for the user, ordered by creation date desc.
- `POST /api/sessions` -- Creates a new session.
- `PUT /api/sessions/<id>` -- Updates session content and carousel images.
- `DELETE /api/sessions/<id>` -- Deletes a session.

**Client Behavior:**
- Sessions auto-save when content is edited (debounced 1 second after last keystroke).
- Click session card to expand inline preview showing content snippets per platform with copy buttons.
- "Dettaglio completo" opens a full session detail view with all content in read-only textareas.
- "Rigenera" pre-fills the Crea tab with the session's original settings (source mode, opinion, platforms).
- "Elimina" shows a confirmation dialog before deleting.

**Filters:**
- Text search (searches title and content).
- Platform filter chips (all, linkedin, instagram, twitter, video_script, newsletter).
- Status filter chips (all, draft, approved, scheduled).

**DB Tables:** `sessions`.

### 3.11 Notifications

**UI:** Bell icon in topbar with red badge showing unread count. Click opens a dropdown panel with notification list. "Segna tutte come lette" button.

**API Routes:**
- `GET /api/notifications` -- Returns notifications with unread count.
- `POST /api/notifications/read` -- Marks a single notification as read.
- `POST /api/notifications/read-all` -- Marks all notifications as read.

**Client Behavior:**
- Polling every 60 seconds via `setInterval`.
- Click a notification item to mark it as read.
- Time displayed as relative ("ora", "5 min fa", "2 ore fa", "3 giorni fa").

**Push Notifications (ntfy.sh):**
- `POST /api/ntfy/test` -- Sends a test notification to the user's configured ntfy topic.
- Schedule checker sends push notifications when content is due.

**DB Tables:** `notifications`, `profiles` (stores `ntfy_topic`).

### 3.12 Weekly Status Tracking

**UI:** Banner at top of main content area showing per-platform counts for the current week.

**API Route:** `GET /api/weekly-status` -- Returns current week's metrics by platform.

**Counters tracked:**
- `generated` -- Incremented when content is generated.
- `approved` -- Incremented when content is approved.
- `scheduled` -- Incremented when a schedule notification fires.
- `published` -- Incremented when content is marked as published.

**Server:** Uses PostgreSQL function `increment_weekly_status()` for atomic counter updates with `week_key` format (e.g., "2026-W11").

**DB Tables:** `weekly_status`.

### 3.13 Monitor Dashboard

**UI:** Four sub-tabs within the Library > Monitor section.

#### 3.13.1 Health Summary
Six cards showing: Total Articles, Total Sessions, Errors (24h), Warnings (24h), Total Feedback, Prompt Versions.

**API Route:** `GET /api/monitor/health`

#### 3.13.2 Prompt Changelog
Grouped by prompt name, each group expandable. Shows version history in reverse chronological order. Each version displays:
- Version number and trigger tag (Initial, Feedback, Enriched).
- Line-by-line diff using LCS algorithm (added lines in green, removed in red, unchanged in gray).
- Toggle between diff view and full content view.
- Statistics: added, removed, unchanged line counts.

**API Route:** `GET /api/monitor/prompts`

#### 3.13.3 Pipeline Logs
Filterable log entries (all, info, warning, error, feedback). Shows level badge, message text, and timestamp. Limited to 100 entries.

**API Route:** `GET /api/monitor/pipeline`

#### 3.13.4 Feed Health
Per-feed cards showing hostname, last seen date, and status badge (OK, warning, error, unknown).

Data source: Derived from pipeline logs within `GET /api/monitor/health`.

#### 3.13.5 Feedback Memory
Per-format sections (LinkedIn, Instagram, etc.) showing individual feedback entries with:
- Checkbox for selecting entries for prompt enrichment.
- Feedback text and timestamp.
- Enrichment badge if the feedback was already used.
- Delete button per entry.
- "Arricchisci prompt" button that triggers prompt enrichment with selected feedback.

**API Route:** `GET /api/feedback`, `POST /api/prompts/enrich`

#### 3.13.6 Selection Preferences
Bar charts showing:
- Top Sources (by selection count).
- Top Categories (by selection count).
- Top Keywords (by frequency).

**API Route:** `GET /api/monitor/preferences`

### 3.14 Settings

**UI:** Within Library > Settings section.

**Components:**
1. **ntfy Test:** Button to send a test push notification.
2. **RSS Feed Management:** Category-organized feed list. Each category shows its feeds with name, URL, and remove button. Add feed form per category. Add/remove category buttons.

**API Routes:**
- `GET /api/feeds/config` -- Returns the user's feed configuration.
- `POST /api/feeds/config` -- Saves the full feed configuration.
- `POST /api/feeds/config/add` -- Adds a feed to a category.
- `POST /api/feeds/config/remove` -- Removes a feed from a category.
- `POST /api/feeds/config/add-category` -- Creates a new category.
- `POST /api/feeds/config/remove-category` -- Removes a category and all its feeds.

**API Key Management (Server-side):**
- `GET /api/settings/keys` -- Returns whether keys are configured (not the keys themselves).
- `POST /api/settings/keys` -- Saves encrypted API keys (OpenRouter, Serper, fal.ai).

**DB Tables:** `feeds_config`, `profiles` (encrypted key fields).

### 3.15 Selection Preferences (Learning Engine)

**Purpose:** Tracks user article selection patterns to provide Smart Brief suggestions and boost scoring.

**API Routes:**
- `POST /api/track-selections` -- Records selected articles, updating source, category, and keyword counts.
- `GET /api/smart-brief` -- Uses accumulated preferences to generate AI suggestions.

**Boost Mechanism:**
When scoring articles via RSS, the server applies boost multipliers based on selection history:
- Source match: `source_count / total_selections * boost_factor`
- Category match: `category_count / total_selections * boost_factor`
- Keyword match: Based on keyword frequency in title/description.

**DB Tables:** `selection_prefs`.

---

## 4. Data Flow

### 4.1 Article Ingestion (RSS)

```
User clicks "Aggiorna Feed"
  |
  v
POST /api/feeds/fetch (starts background thread)
  |
  v
For each feed URL in feeds_config:
  feedparser.parse(url)
    |
    v
  Insert new articles into articles table (batches of 50)
    |
    v
  POST to OpenRouter (Gemini Flash) for scoring
    |
    v
  Update articles with scores, summaries, categories
    |
    v
  Send progress via SSE (/api/feeds/progress)
```

### 4.2 Article Ingestion (Web Search)

```
User enters query, clicks "Cerca"
  |
  v
POST /api/search
  |
  v
Serper API call (Google Search)
  |
  v
Return results to client
  |
  v
Client sends to POST /api/search/score
  |
  v
OpenRouter (Gemini Flash) scores each result
  |
  v
Insert scored articles into articles table
  |
  v
Return scored articles to client
```

### 4.3 Content Generation

```
User selects articles + platforms, clicks Generate
  |
  v
Track selections: POST /api/track-selections
  (updates selection_prefs)
  |
  v
For each platform (parallel):
  POST /api/generate
    |
    v
  Server:
    1. Load user prompt (user_prompts) or base prompt
    2. Build prompt: system_prompt + format_prompt + article + opinion
    3. Check generation limits (subscriptions)
    4. Call OpenRouter (Claude Sonnet 4.5)
    5. Store feedback if provided (feedback table)
    6. Increment weekly_status (generated counter)
    7. Log to pipeline_logs
    8. Return content
  |
  v
Newsletter (sequential, after others):
  POST /api/generate-newsletter
    |
    v
  Same flow but combines all topics into one prompt
  |
  v
Auto-save session: POST /api/sessions
  |
  v
Render carousel images: POST /api/render-carousel
  |
  v
Display results with edit/copy/approve/schedule actions
```

### 4.4 Prompt Enrichment

```
User selects feedback entries in Monitor > Feedback Memory
  |
  v
POST /api/prompts/enrich
  {format_type, feedback_ids}
  |
  v
Server:
  1. Load current prompt for format_type
  2. Load selected feedback entries
  3. Call OpenRouter (Claude Sonnet 4.5) with enrichment prompt
  4. Save new prompt version (user_prompts + prompt_logs)
  5. Mark feedback as enriched (feedback.enriched_at)
  6. Log to pipeline_logs
  |
  v
Client refreshes Monitor to show new prompt version in changelog
```

### 4.5 Schedule Notification

```
Background thread (every 30 seconds):
  |
  v
Query: SELECT * FROM schedules WHERE status='pending' AND scheduled_at <= NOW()
  |
  v
For each due item:
  1. Load user profile for ntfy_topic
  2. POST to ntfy.sh with notification
  3. Update schedule status to 'notified'
  4. Create in-app notification
  5. Increment weekly_status (scheduled counter)
  6. Log to pipeline_logs
```

---

## 5. Database Schema Summary

### 5.1 Tables (13 total)

| Table | Purpose | Key Columns |
|---|---|---|
| `profiles` | User profiles extending auth.users | id (FK), email, plan, stripe_customer_id, encrypted API keys, ntfy_topic |
| `subscriptions` | Stripe subscription tracking | user_id, stripe_subscription_id, plan, status, period dates |
| `articles` | Scored RSS/search articles | user_id, url, title, score, summary, category, source_mode |
| `sessions` | Content generation sessions | user_id, article (JSONB), topics (JSONB), content (JSONB), carousel_images (JSONB), platforms (JSONB) |
| `schedules` | Content publishing schedule | user_id, platform, title, content_key, session_id, scheduled_at, status |
| `feedback` | User feedback on generated content | user_id, format_type, feedback, enriched_at |
| `feeds_config` | RSS feed categories per user | user_id, categories (JSONB) |
| `pipeline_logs` | Operational log entries | user_id, level, message, extra (JSONB) |
| `prompt_logs` | Prompt version history | user_id, prompt_name, version, content, trigger |
| `selection_prefs` | Learning engine data | user_id, source_counts, category_counts, keyword_counts, total_selections |
| `weekly_status` | Per-week content metrics | user_id, week_key, platform, generated, approved, scheduled, published |
| `user_prompts` | Per-user active prompts | user_id, prompt_name, content, is_base |
| `notifications` | In-app notifications | user_id, type, title, body, read |

### 5.2 Key Relationships

- All tables reference `auth.users(id)` via `user_id` (CASCADE delete).
- `schedules.session_id` references `sessions.id` (soft reference, not FK).
- `profiles.id` directly references `auth.users(id)`.

### 5.3 Indexes (15 total)

Optimized for common queries: articles by user+score, sessions by user+date, schedules by user+status, feedback by user+format, pipeline logs by user+date, notifications by user+read status, etc.

---

## 6. Security

### 6.1 Authentication & Authorization

- **JWT-based:** Every `/api/` request requires a valid Bearer token.
- **Server-side validation:** `_before_request_auth()` middleware extracts and validates JWT via Supabase before processing any API request.
- **Row Level Security:** All 13 tables have RLS enabled. Policies ensure users can only access their own data using `auth.uid() = user_id`.
- **Service Role Key:** The backend uses `service_role` key to bypass RLS for administrative operations (e.g., schedule checker daemon).
- **Token Refresh:** Client automatically attempts token refresh on 401 responses before showing login.

### 6.2 API Key Encryption

- User API keys (OpenRouter, Serper, fal.ai) are encrypted with AES-256 before storage.
- The `security` module handles encryption/decryption.
- Keys are stored in `profiles` table fields: `openrouter_api_key_enc`, `serper_api_key_enc`, `fal_key_enc`.
- The `GET /api/settings/keys` endpoint only returns whether keys are configured, never the actual key values.

### 6.3 Input Sanitization

- Client-side: `esc()` and `_escHtml()` functions escape HTML entities before rendering.
- Server-side: All user input is used as parameters in API calls, not directly in SQL (Supabase client handles parameterization).

### 6.4 Infrastructure Security

- **Sentry:** Error tracking and monitoring.
- **CORS:** Configured via Flask-CORS.
- **Rate Limiting:** Via `flask-limiter` (specific limits not visible in code).
- **Security Headers:** Applied via the `security` module.
- **HTTPS:** Enforced by Render hosting platform.

### 6.5 Payment Security

- Stripe handles all payment processing. No card data touches the application server.
- Webhook signature verification ensures webhook authenticity.
- Subscriptions are server-managed; users have read-only access to their subscription data.

---

## 7. Current Known Issues and Limitations

### 7.1 Architecture Concerns

1. **Monolithic Frontend:** The entire SPA (~5712 lines) is in a single HTML file. This makes maintenance, testing, and code splitting impossible. No module system, no bundler, no framework.

2. **No Frontend Framework:** All DOM manipulation is imperative. State management is through global variables (`selectedArticles`, `currentSession`, `currentContent`, etc.). This is fragile and hard to reason about.

3. **Inline JavaScript:** All ~3300 lines of JavaScript are inline in the HTML file. No minification, no tree-shaking, no source maps.

4. **Background Thread for Scheduling:** Using a Python `threading.Timer` for the schedule checker is fragile. If the server restarts or the thread crashes, notifications stop. A proper task queue (Celery, Redis Queue) or a cron-based approach would be more reliable.

5. **SSE for RSS Progress:** Server-Sent Events are used for RSS fetch progress. This ties up a server thread per connected client during the fetch operation.

### 7.2 Data Integrity

6. **Soft Reference for Sessions in Schedules:** `schedules.session_id` is not a foreign key. If a session is deleted, schedule entries referencing it become orphaned and their content retrieval fails silently.

7. **No Pagination on Articles or Sessions:** `GET /api/articles` and `GET /api/sessions` return all records. This will cause performance issues as data grows.

8. **Client-side Article Encoding:** Articles are serialized to JSON, URI-encoded, then base64-encoded and embedded in `onclick` handlers. This is brittle and creates XSS risk if encoding is improperly handled.

### 7.3 UX Issues

9. **Max 3 Article Selection:** Hardcoded limit of 3 articles per generation. Not configurable per plan or by user preference.

10. **No Offline Support:** No service worker, no caching strategy. The app requires constant connectivity.

11. **Italian-only UI:** All prompts, UI text, toast messages, and error messages are in Italian. No internationalization support.

12. **No Undo for Approve/Schedule:** Approving content is toggleable, but once scheduled, the only option is to delete the schedule entry.

### 7.4 Security Gaps

13. **localStorage for Tokens:** JWT tokens in `localStorage` are vulnerable to XSS attacks. `httpOnly` cookies would be more secure.

14. **Global fetch Monkey-patch:** The `fetch` override applies globally, including to third-party scripts if any are loaded.

15. **No CSRF Protection:** While the app uses Bearer tokens (which provide implicit CSRF protection), there is no explicit CSRF token mechanism.

### 7.5 Performance

16. **No Content Caching:** Every tab switch triggers fresh API calls (e.g., `loadHistory()`, `loadSchedule()`, `loadMonitor()`). No client-side caching or conditional fetching.

17. **Parallel Generation Requests:** All platform generations fire simultaneously. For a user generating 3 articles across 5 platforms, this creates ~16 concurrent API calls to OpenRouter, which could cause rate limiting.

18. **No Image Optimization:** Carousel images are served as PNGs without optimization or lazy loading.

### 7.6 Missing Features

19. **No Content Export:** No built-in way to export all generated content (e.g., as CSV, PDF, or structured document).

20. **No Collaborative Features:** Single-user only. No team/workspace support.

21. **No Direct Publishing:** The app only notifies users to publish. There is no direct integration with LinkedIn, Instagram, Twitter APIs, or email services for automated publishing.

22. **No A/B Testing:** No mechanism to compare different content variations for the same article.

23. **No Analytics:** No tracking of content performance after publication (engagement, clicks, etc.).

---

## 8. API Route Summary

### Public Routes (No Auth)
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Landing page |
| GET | `/app` | Dashboard SPA |
| POST | `/auth/signup` | User registration |
| POST | `/auth/login` | User login |
| POST | `/auth/refresh` | Token refresh |
| POST | `/auth/logout` | Logout |
| POST | `/stripe/webhook` | Stripe webhook handler |
| GET | `/healthz` | Health check |

### Authenticated Routes (Require JWT)
| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/me` | Current user info |
| GET | `/api/plans` | Plan definitions |
| POST | `/api/checkout` | Create Stripe checkout |
| POST | `/api/billing/portal` | Open Stripe portal |
| GET | `/api/subscription` | Subscription & usage info |
| GET/POST | `/api/settings/keys` | API key management |
| GET/PUT | `/api/settings/profile` | Profile management |
| GET/POST | `/api/feeds/config` | Feed configuration |
| POST | `/api/feeds/config/add` | Add feed to category |
| POST | `/api/feeds/config/remove` | Remove feed from category |
| POST | `/api/feeds/config/add-category` | Create feed category |
| POST | `/api/feeds/config/remove-category` | Delete feed category |
| POST | `/api/feeds/fetch` | Trigger RSS fetch |
| GET | `/api/feeds/progress` | SSE progress stream |
| GET | `/api/articles` | Get scored articles |
| POST | `/api/search` | Web search via Serper |
| POST | `/api/search/score` | Score search results |
| POST | `/api/generate` | Generate content (single) |
| POST | `/api/generate-newsletter` | Generate newsletter |
| POST | `/api/newsletter/html` | Convert newsletter to HTML |
| GET/POST | `/api/schedule` | List/create schedules |
| POST | `/api/schedule/bulk` | Bulk schedule creation |
| DELETE | `/api/schedule/<id>` | Delete schedule |
| POST | `/api/schedule/<id>/publish` | Mark as published |
| GET | `/api/schedule/<id>/content` | Get schedule content |
| GET/POST | `/api/sessions` | List/create sessions |
| PUT | `/api/sessions/<id>` | Update session |
| DELETE | `/api/sessions/<id>` | Delete session |
| GET/POST | `/api/feedback` | List/create feedback |
| DELETE | `/api/feedback/<format>/<id>` | Delete feedback |
| POST | `/api/prompts/enrich` | Enrich prompts with feedback |
| GET | `/api/notifications` | List notifications |
| POST | `/api/notifications/read` | Mark notification read |
| POST | `/api/notifications/read-all` | Mark all read |
| POST | `/api/track-selections` | Track article selections |
| GET | `/api/smart-brief` | Get AI suggestions |
| POST | `/api/render-carousel` | Render carousel images |
| GET | `/api/weekly-status` | Weekly metrics |
| POST | `/api/approve` | Approve content |
| POST | `/api/ntfy/test` | Test push notification |
| GET | `/api/monitor/prompts` | Prompt version history |
| GET | `/api/monitor/pipeline` | Pipeline logs |
| GET | `/api/monitor/preferences` | Selection preferences |
| GET | `/api/monitor/health` | System health metrics |

---

*End of Functional Specification*
