# Architecture — The Frontier Brief

Deterministic, serverless daily AI newsletter pipeline with autonomous quality verification and zero operating costs.

---

## Pipeline Flow

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               GITHUB ACTIONS CRON                                      │
│                               (daily @ 09:00 UTC)                                      │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
                                    ┌──────────────┐
                                    │   main.py    │
                                    │  Entrypoint  │
                                    └──────┬───────┘
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: INGESTION (src/ingestion.py)                                                  │
│                                                                                        │
│ ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│ │ Lab/Startup RSS  │  │ Reddit RSS       │  │ Mastodon/HN/X    │  │ GitHub Trending  │ │
│ │ (8 Feeds + BS4)  │  │ (3 Subreddits)   │  │ (Tags & Algolia) │  │ (Scraped Repos)  │ │
│ └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘ │
│          │                     │                     │                     │           │
│          ▼                     ▼                     ▼                     ▼           │
│     [articles]              [posts]               [takes]               [repos]        │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: SYNTHESIS & QUALITY CONTROL (src/pipeline.py)                                │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ build_payload()                                                                  │  │
│  │ Assemble raw data, enforce < 100k char budget, inject trends & prefs.yaml        │  │
│  └───────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                             │
│                                          ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ synthesize() — Gemini 3.1 Flash-Lite                                             │  │
│  │ System Prompt: editorial principles, "why it matters", plain-English translation  │  │
│  │ Output: strict JSON Schema enforcement (5 sections, zero Markdown breaks)         │  │
│  └───────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                             │
│                                          ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ critique_newsletter() — Autonomous Critic Pass                                   │  │
│  │ Evaluates accuracy, hype ratio, and source diversity. Retries synthesis if < 7/10│  │
│  │ apply_critique_flags() tags unverified single-source claims with disclaimers      │  │
│  └───────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                             │
│                                          ▼                                             │
│                             [validated newsletter JSON]                                │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: RENDERING & DELIVERY (src/delivery.py)                                        │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ render_html()                                                                    │  │
│  │ Deterministic inline CSS, responsive 600px table layout, sentiment color badges   │  │
│  └───────────────────┬──────────────────────────────────────────┬───────────────────┘  │
│                      │                                          │                      │
│                      ▼                                          ▼                      │
│  ┌────────────────────────────────────────┐  ┌──────────────────────────────────────┐  │
│  │ send_email()                           │  │ save_archive() & GitHub Pages Deploy │  │
│  │ Resend API delivery to recipient       │  │ Writes YYYY-MM-DD.html, rebuilds     │  │
│  │ Includes anonymous 1x1 telemetry pixel │  │ index.html, pushes to gh-pages branch│  │
│  └────────────────────────────────────────┘  └──────────────────────────────────────┘  │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: STATE MANAGEMENT (src/trends.py)                                              │
│                                                                                        │
│ Commits updated 7-day topic_history.json to main branch for rolling trend detection    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Source Catalog

| Source | Method | Endpoint / Mechanism | Rate Limits / Pacing | Reliability |
|---|---|---|---|---|
| OpenAI Blog | RSS (feedparser) | `openai.com/news/rss.xml` | None | High |
| Anthropic News | RSSHub / RSS | `rsshub.app/anthropic/news` | Public bridge limits | Medium |
| Google DeepMind | RSS (feedparser) | `deepmind.google/blog/feed/basic/` | None | High |
| Meta AI Research | RSS (feedparser) | `research.facebook.com/feed/` | None | High |
| Meta Engineering | RSS (feedparser) | `engineering.fb.com/feed/` | None | High |
| Mistral AI | HTML Parser (BS4) | `mistral.ai/news/` scrape fallback | None | High |
| Hugging Face | RSS (feedparser) | `huggingface.co/blog/feed.xml` | None | High |
| Stability AI | RSS (feedparser) | `stability.ai/news/feed` | None | Medium |
| Cohere | RSS (feedparser) | `cohere.com/blog/rss.xml` | None | Medium |
| Together AI | RSS (feedparser) | `together.ai/blog/rss.xml` | None | Medium |
| Reddit (3 subs) | RSS feed (.rss) | `reddit.com/r/{sub}/hot/.rss` | 6s pacing delay between calls | High (bypasses 403 API) |
| Mastodon AI/LLM | REST JSON API | `mastodon.social/api/v1/timelines/tag/{tag}` | Unauthenticated rate budget | High |
| Hacker News | REST JSON API | `hn.algolia.com/api/v1/search_by_date` | 10,000 req/hr | Very High |
| GitHub Trending | HTML scraping | `github.com/trending?since=daily` | No auth required | High |

---

## Failure Recovery Strategy

The pipeline operates on a **retry-then-degrade** pattern across every stage:

### 1. Ingestion Failures
- **Exponential Backoff:** All HTTP calls retry up to 3 times with exponential backoff (1s → 2s → 4s delays).
- **Graceful Degradation:** If a feed exhausts retries, the collector logs a warning and returns an empty list. The pipeline continues with remaining sources.
- **Reddit Rate Pacing:** Unauthenticated Reddit requests enforce a mandatory 6-second sleep between subreddit calls to avoid HTTP 429 rate limits.
- **24-Hour Fallback:** If a lab feed has no new posts within the last 24 hours (common for monthly releases), the top 3 most recent entries are ingested with a `recent_fallback: true` tag for background context.
- **Hard Abort:** If all sources return zero items, the pipeline exits with code 1 rather than producing an empty email.

### 2. Synthesis Failures & Schema Validation
- **Structured JSON Output:** Synthesis uses Gemini's `response_schema` parameter to enforce `NEWSLETTER_SCHEMA` at the model token generation layer.
- **Runtime Validation:** After parsing, `_validate_newsletter()` verifies all 5 sections and nested fields exist.
- **Automatic Retry:** If formatting is invalid or the API encounters a transient failure, synthesis retries after a 10-second backoff delay.
- **Token Budget Protection:** `build_payload()` caps context at 100,000 characters (~25k tokens), trimming lowest-priority sources first (social → GitHub → Reddit → lab news).

### 3. Autonomous Quality Self-Check
- **Second Pass Critic:** `critique_newsletter()` uses a lightweight Gemini call (`temperature=0.1`) to score accuracy (1-10), hype ratio (1-10), and source diversity (1-10).
- **Automatic Re-Synthesis:** If the overall score is below 7/10, the system triggers a single re-synthesis pass with the original context.
- **Single-Source Flagging:** Stories corroborated by only one source are automatically labeled with `[Note: Unverified — single source]` in the final copy.
- **Fail-Open Verification:** If the critic call encounters a rate limit or network error, it safely passes through the draft so delivery is never blocked by the verification layer.

### 4. Delivery & Web Archiving
- **Delivery Retries:** Email sending via Resend retries once after a 5-second backoff.
- **Orphan Branch Isolation:** The GitHub Actions workflow pushes static editions and generated `index.html` to an isolated `gh-pages` branch, keeping the `main` branch pure code.
- **Dynamic Fallbacks:** `render_html()` dynamically constructs the GitHub Pages archive and dashboard links using `GITHUB_REPOSITORY_OWNER`, preventing broken hash anchor links.

---

## Design Decisions & Tradeoffs

### 1. Single LLM Call with Schema Enforcement vs. Multi-Agent Chain
* **Tradeoff:** A multi-agent system (Researcher → Drafter → Critic → Formatter) consumes 4–6 API calls, risking Gemini's 15 requests-per-minute free-tier cap.
* **Decision:** Consolidate ingestion synthesis into a single inference call with strict JSON Schema output, using roughly 10,000 tokens (~4% of daily quota). A single lightweight secondary call is reserved exclusively for the quality critic.

### 2. Python HTML Rendering vs. LLM Direct HTML Generation
* **Tradeoff:** Asking an LLM to generate raw HTML often produces malformed tags, broken styling, or markdown leaks.
* **Decision:** The LLM generates structured data only. Python's `render_html()` deterministically formats the 600px table layout, sentiment badge colors, star ratings, and inline CSS. The presentation layout cannot break.

### 3. Git as State Store vs. Hosted Database
* **Tradeoff:** Provisioning and maintaining an external cloud database (Supabase, Postgres) introduces infrastructure maintenance and credential overhead.
* **Decision:** A rolling 7-day topic window is committed directly to `data/topic_history.json` on the `main` branch by the workflow. Git acts as the zero-cost state store.

### 4. Open Developer Networks vs. Paid Twitter API
* **Tradeoff:** The official X/Twitter API costs $100/month, and free RSS bridges are heavily blocked.
* **Decision:** Ingest developer sentiment from Mastodon's hashtag timeline (`#AI`, `#LLM`) and Hacker News via the Algolia API. This provides over 30 authentic community perspectives per run at zero cost.

### 5. Serverless Cloudflare Edge Proxy for Dashboard
* **Tradeoff:** A static GitHub Pages frontend cannot securely store a GitHub OAuth Client Secret.
* **Decision:** Deploy a lightweight Cloudflare Worker (`worker/index.js`) as a serverless edge proxy. The worker securely handles the token exchange, allowing users to authenticate and update `prefs.yaml` via GitHub REST API without hosting any servers.

### 6. Anonymous Telemetry
* **Tradeoff:** Traditional email tracking exposes subscriber IP addresses and email identities.
* **Decision:** Open rates are recorded via a 1x1 tracking pixel using a SHA-256 hash of the repository actor (`hashlib.sha256(raw_actor).hexdigest()[:12]`). Fork owners can opt out completely via `allow_telemetry: false` in `prefs.yaml`.
