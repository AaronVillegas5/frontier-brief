# The Frontier Brief

A fully automated daily AI newsletter that pulls the latest from major AI labs and startups, captures community sentiment from Reddit and open developer networks, highlights trending GitHub repositories, and explains why it all matters — written for non-technical leaders and operators.

👉 **[Live Web Archive](https://aaronvillegas5.github.io/frontier-brief/)** &middot; **[Web Preferences Dashboard](https://aaronvillegas5.github.io/frontier-brief/dashboard.html)** 👈

Runs on GitHub Actions. Costs $0.00 to operate. Ships by email every morning at 09:00 UTC.

---

## Key Features & Stretch Goals

* **13 Ingestion Feeds:** Scrapes OpenAI, DeepMind, Anthropic, Meta, Hugging Face, Mistral (HTML parser), Reddit RSS (r/MachineLearning, r/LocalLLaMA, r/singularity), Mastodon, Hacker News (Algolia API), and GitHub Trending.
* **Strict JSON Synthesis:** Gemini 3.1 Flash-Lite constrained by a strict JSON schema—never produces broken markdown or invalid HTML.
* **Autonomous LLM Critic:** Self-evaluates drafts for accuracy, clarity, and hype ratio. Triggers automatic re-synthesis if quality falls below threshold, and flags single-source claims with `[Note: Unverified]`.
* **Personalization Engine (`prefs.yaml`):** Readers can configure topic focus, audience tone (e.g. non-technical vs. developer), and source exclusions without changing code.
* **Serverless Web Dashboard:** A responsive single-page web app hosted on GitHub Pages that allows non-technical users to configure preferences via GitHub OAuth and an edge Cloudflare Worker proxy.
* **7-Day Trend Detection:** Tracks multi-day recurring topics across a rolling 7-day window committed directly to Git. Highlights "heating topics" in synthesis.
* **Privacy-Preserving Analytics:** All outbound links include UTM campaign tracking. Open rates are supported via a 1x1 tracking pixel using SHA-256 hashed user identifiers for complete anonymity, with an opt-out toggle in preferences.
* **Permanent Web Archive:** Automatically generates and indexes responsive HTML editions on the `gh-pages` branch on every run.
* **54 Automated Unit Tests:** Comprehensive test suite covering ingestion, backoff retry logic, schema validation, trend detection, and UTM parsing.

---

## Quick Start (5 Minutes)

### 1. Fork the Repository
Click **Fork** at the top right of this repository to create your personal copy.

### 2. Get Free API Keys
* **Gemini API Key:** Create a free key at [Google AI Studio](https://aistudio.google.com/apikey).
* **Resend API Key:** Create a free account at [Resend](https://resend.com) and generate an API key.

> **Note:** On Resend's free tier, emails are sent from `onboarding@resend.dev` and delivered to your registered Resend account email.

### 3. Configure GitHub Secrets
In your forked repository, go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret Name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key from Google AI Studio |
| `RESEND_API_KEY` | Your Resend API key from Resend |
| `FROM_EMAIL` | `onboarding@resend.dev` |
| `TO_EMAIL` | Your recipient email registered on Resend |

### 4. Run & Verify
1. Go to the **Actions** tab in your repository.
2. Select **The Frontier Brief — Daily Newsletter** in the left sidebar.
3. Click **Run workflow** → **Run workflow**.
4. The pipeline will finish in ~75 seconds. Check your inbox and your GitHub Pages archive.

---

## Project Structure

```
frontier-brief/
├── main.py                              # Pipeline entrypoint & stage orchestrator
├── sources.yaml                         # Data sources (RSS feeds, subreddits, social terms)
├── prefs.yaml                           # User personalization config (topics, tone, telemetry)
├── requirements.txt                     # Production Python dependencies
├── .env.example                         # Environment variable template for local dev
├── ARCHITECTURE.md                      # Detailed technical architecture document
├── dashboard/                           # Client-side web preferences dashboard
│   ├── dashboard.html                   # Responsive configuration UI
│   └── app.js                           # GitHub OAuth & REST API client logic
├── worker/                              # Serverless OAuth proxy (Cloudflare Workers)
│   ├── index.js                         # Code-exchange proxy isolating CLIENT_SECRET
│   └── wrangler.toml                    # Cloudflare deployment config
├── scripts/                             # Utility & CI automation scripts
│   └── build_index.py                   # Generates gh-pages archive index.html
├── src/                                 # Core application modules
│   ├── ingestion.py                     # Data collectors (RSS, Reddit, Mastodon, HN, GitHub)
│   ├── pipeline.py                      # Gemini synthesis, JSON schema, & LLM Critic
│   ├── trends.py                        # Rolling 7-day trend detection engine
│   └── delivery.py                      # Inline HTML email renderer & Resend delivery
├── tests/
│   └── test_suite.py                    # 54 automated unit tests
├── data/
│   └── topic_history.json               # Rolling multi-day trend history state
└── .github/workflows/
    └── daily_brief.yml                  # GitHub Actions cron (09:00 UTC) & dispatch workflow
```

---

## Running Locally

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/frontier-brief.git
cd frontier-brief

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Fill in GEMINI_API_KEY, RESEND_API_KEY, and TO_EMAIL in .env

# Run the test suite (54 tests)
python tests/test_suite.py

# Run the end-to-end pipeline
python main.py
```

---

## Rate Limits & Resource Usage

| Service | Free Tier Allocation | Frontier Brief Usage |
|---|---|---|
| **GitHub Actions** | 2,000 min / month | ~38 min / month (1.2 min / day) |
| **Gemini 3.1 Flash-Lite** | 15 RPM, 500 RPD | 1–2 requests / day (~15k tokens) |
| **Resend** | 100 emails / day | 1 email / day |
| **Reddit RSS** | ~60 req / hr | 3 req / day (6s delay between calls) |
| **HN / Algolia** | 10,000 req / hr | 3 req / day |
| **Cloudflare Workers** | 100,000 req / day | On-demand for dashboard saves only |

---

## License

MIT License
