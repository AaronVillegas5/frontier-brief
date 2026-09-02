# Architecture — The Frontier Brief

## Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GITHUB ACTIONS CRON                         │
│                     (daily @ 12:00 UTC)                            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   main.py    │
                    │  Entrypoint  │
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
  ┌─────────────────────────────────────────────────┐
  │            STAGE 1: INGESTION                   │
  │           src/ingestion.py                      │
  │                                                 │
  │  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────┐ │
  │  │ Lab/     │ │ Reddit   │ │ X/     │ │GitHub│ │
  │  │ Startup  │ │ RSS      │ │Twitter │ │Trend-│ │
  │  │ RSS      │ │ Feeds    │ │Bridges │ │ ing  │ │
  │  │ Feeds    │ │          │ │        │ │Scrape│ │
  │  └────┬─────┘ └────┬─────┘ └───┬────┘ └──┬───┘ │
  │       │            │           │          │     │
  │       ▼            ▼           ▼          ▼     │
  │   [articles]   [posts]     [tweets]    [repos]  │
  └────────────────────┬────────────────────────────┘
                       │
                       ▼
  ┌─────────────────────────────────────────────────┐
  │            STAGE 2: SYNTHESIS                   │
  │           src/pipeline.py                       │
  │                                                 │
  │  ┌──────────────────────────────────────────┐   │
  │  │ build_payload()                          │   │
  │  │ Assemble JSON, enforce token budget      │   │
  │  └──────────────────┬───────────────────────┘   │
  │                     │                           │
  │                     ▼                           │
  │  ┌──────────────────────────────────────────┐   │
  │  │ synthesize()                             │   │
  │  │ Single call to Gemini 3.1 Flash-Lite     │   │
  │  │ System prompt: skeptical, plain-English  │   │
  │  │ Output: structured JSON (5 sections)     │   │
  │  └──────────────────┬───────────────────────┘   │
  │                     │                           │
  │                     ▼                           │
  │            [validated newsletter JSON]           │
  └────────────────────┬────────────────────────────┘
                       │
                       ▼
  ┌─────────────────────────────────────────────────┐
  │            STAGE 3: DELIVERY                    │
  │           src/delivery.py                       │
  │                                                 │
  │  ┌──────────────────────────────────────────┐   │
  │  │ render_html()                            │   │
  │  │ Inline CSS, responsive, single-column    │   │
  │  └──────────────────┬───────────────────────┘   │
  │                     │                           │
  │                     ▼                           │
  │  ┌──────────────────────────────────────────┐   │
  │  │ send_email()                             │   │
  │  │ Resend API delivery                      │   │
  │  └──────────────────────────────────────────┘   │
  └─────────────────────────────────────────────────┘
```

## Source Catalog

| Source | Method | URL / Endpoint | Rate Limits | Reliability |
|---|---|---|---|---|
| OpenAI Blog | RSS (feedparser) | `openai.com/news/rss.xml` | None | High |
| Anthropic News | RSSHub bridge | `rsshub.app/anthropic/news` | RSSHub limits | Medium — community-maintained |
| Google DeepMind | RSS (feedparser) | `deepmind.google/blog/feed/basic/` | None | High |
| Meta Research | RSS (feedparser) | `research.facebook.com/feed/` | None | High |
| Meta Engineering | RSS (feedparser) | `engineering.fb.com/feed/` | None | High |
| Mistral AI | RSS (feedparser) | `mistral.ai/news/index.xml` | None | High |
| Hugging Face | RSS (feedparser) | `huggingface.co/blog/feed.xml` | None | High |
| Stability AI | RSS (feedparser) | `stability.ai/news/feed` | None | Medium |
| Cohere | RSS (feedparser) | `cohere.com/blog/rss.xml` | None | Medium |
| xAI | RSSHub bridge | `rsshub.app/x/user/xaboratory` | RSSHub limits | Low |
| Together AI | RSS (feedparser) | `together.ai/blog/rss.xml` | None | Medium |
| Reddit (3 subs) | RSS feed (.rss) | `reddit.com/r/{sub}/hot/.rss` | Undocumented, ~60 req/hr | Medium |
| X / Twitter | RSSHub / RSS.app | `rsshub.app/x/search/{term}` | Variable | Low — Nitter dead, bridges fragile |
| GitHub Trending | HTML scraping | `github.com/trending?since=daily` | No auth needed | High |

## Failure Recovery Strategy

The pipeline uses a **retry-then-degrade** pattern at every stage:

### Ingestion Failures
- **Retry**: Each HTTP request retries up to 3 times with exponential backoff (1s → 2s → 4s delays).
- **Degrade**: If a source fails all retries, the collector returns an empty list. The pipeline continues with whatever data was collected.
- **Abort threshold**: If ALL sources fail (total items = 0), the pipeline exits with code 1 and sends no email. There's no point sending an empty newsletter.
- **Lab news fallback**: If a feed has no articles in the last 24 hours (common for labs that post monthly), the top 3 most recent entries are used regardless of age, tagged as `recent_fallback` so the LLM knows they aren't breaking news.

### Synthesis Failures
- **Retry**: The Gemini API call retries once after a 10-second delay.
- **Validation**: The JSON response is validated against the required schema. Missing sections trigger a retry.
- **Hard fail**: If synthesis fails after 2 attempts, the pipeline exits with code 1.

### Delivery Failures
- **Retry**: Email send retries once after a 5-second delay.
- **Hard fail**: If delivery fails after 2 attempts, the pipeline exits with code 1.

### GitHub Actions
- Non-zero exit codes surface as failed workflow runs, visible in the Actions tab.
- Workflow timeout is set to 10 minutes to prevent hanging on stuck network requests.
- All logs are written to stdout and captured automatically by GitHub Actions.

## Design Decisions

### Single Gemini API Call
The newsletter is generated in one call to `gemini-3.1-flash-lite` with a structured JSON schema. This maximizes rate budget efficiency (1 request per day out of a 500 RPD limit) and ensures editorial coherence — the model sees all sources simultaneously, enabling cross-reference and corroboration in a single pass.

### RSS Over APIs
Most lab blogs have RSS feeds that are stable, free, and unauthenticated. Where official RSS isn't available (Anthropic, xAI), community-maintained RSSHub bridges fill the gap. This avoids API key management, rate limit complexity, and paid tier dependencies.

### Reddit RSS Over JSON
Reddit's `.json` endpoints now return 403 for unauthenticated requests. The `.rss` feeds still work without auth and provide enough data (titles, content, authors) for sentiment analysis. The tradeoff is less metadata (no upvote counts), but the post ordering in the RSS feed correlates with Reddit's ranking algorithm.

### Token Budget Management
The raw payload is capped at ~100,000 characters (~25k tokens). When trimming is needed, lower-priority sources (X/Twitter, then GitHub, then Reddit) are truncated first. Lab/startup news is always preserved in full since it's the primary signal source.

### HTML Email Design
Email clients are notoriously inconsistent with CSS rendering. The template uses inline styles, table-based layout, and system fonts — the most broadly compatible approach. No images, no external resources, no JavaScript.

### Resend Over SMTP
Resend provides a simpler integration (single API key vs. host/port/user/password), reliable delivery, and a generous free tier (100 emails/day). The tradeoff is vendor lock-in, but swapping to SMTP would be a ~20-line change in `delivery.py`.
