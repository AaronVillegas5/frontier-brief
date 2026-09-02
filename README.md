# The Frontier Brief

A fully automated daily AI newsletter that pulls the latest from major AI labs and startups, captures community sentiment from Reddit and X/Twitter, highlights trending GitHub repos, and explains why it all matters — written for non-technical readers.

Runs on GitHub Actions. Costs nothing. Ships by email every day at noon UTC.

---

## Quick Start (5 Minutes)

### 1. Fork the Repository

Click the **Fork** button at the top right of this GitHub page. This creates your own copy of the project.

### 2. Get Your API Keys

You need two free API keys:

**Gemini API Key** (Google AI — free tier):
1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **Create API Key**
4. Copy the key — you'll need it in step 3

**Resend API Key** (email delivery — free tier):
1. Go to [Resend](https://resend.com) and create a free account
2. Go to **API Keys** in the sidebar
3. Click **Create API Key**, give it a name like "frontier-brief"
4. Copy the key — you'll need it in step 3

> **Note**: On Resend's free tier, emails can only be sent from `onboarding@resend.dev` and can only be delivered to the email address you used to create your Resend account.

### 3. Configure GitHub Secrets

In your forked repository:

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add each of these:

| Secret Name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key from step 2 |
| `RESEND_API_KEY` | Your Resend API key from step 2 |
| `FROM_EMAIL` | `onboarding@resend.dev` (use this exact value for free tier) |
| `TO_EMAIL` | The email you registered with on Resend |

### 4. Test It

1. Go to the **Actions** tab in your repository
2. Click **The Frontier Brief — Daily Newsletter** in the left sidebar
3. Click the **Run workflow** button → **Run workflow**
4. Wait 2-3 minutes for the pipeline to complete
5. Check your email — you should have today's edition

### 5. You're Done

The newsletter will now run automatically every day at 12:00 PM UTC. No further action needed.

---

## How It Works

Every day, the pipeline:

1. **Collects data** from 10+ AI lab and startup RSS feeds, 3 Reddit communities, X/Twitter search bridges, and GitHub's trending page
2. **Sends everything** to Google's Gemini AI in a single API call with instructions to corroborate facts, cut through hype, and write for a non-technical audience
3. **Renders** the AI's analysis into a clean HTML email
4. **Delivers** the email via Resend

The whole process takes about 1-2 minutes and costs nothing on free API tiers.

---

## Newsletter Sections

| Section | What It Covers |
|---|---|
| **The Big Story** | The single most important AI development today, with context on why it matters |
| **Frontier Watch** | Quick hits from labs and startups — new models, products, research |
| **The Street Says** | What Reddit and X are actually saying — hype, skepticism, drama |
| **Repo of the Day** | One trending GitHub project worth knowing about |
| **Two Steps Ahead** | Forward-looking analysis — what today's news suggests about tomorrow |

---

## Customizing Sources

Edit `sources.yaml` to add or remove data sources:

```yaml
lab_feeds:
  My New Source:
    url: "https://example.com/feed.xml"
```

Push the change to your fork and it takes effect on the next run.

---

## Project Structure

```
frontier-brief/
├── main.py                              # Pipeline entrypoint
├── sources.yaml                         # Data source configuration
├── requirements.txt                     # Python dependencies
├── .env.example                         # Environment variable template
├── ARCHITECTURE.md                      # Technical architecture document
├── src/
│   ├── ingestion.py                     # Data collectors (RSS, Reddit, X, GitHub)
│   ├── pipeline.py                      # Payload assembly + Gemini synthesis
│   └── delivery.py                      # HTML rendering + Resend email delivery
└── .github/workflows/
    └── daily_brief.yml                  # GitHub Actions daily schedule
```

---

## Running Locally

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/frontier-brief.git
cd frontier-brief

# Create a virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up your environment
cp .env.example .env
# Edit .env with your API keys

# Run the pipeline
python main.py
```

---

## Troubleshooting

**Pipeline fails with "Missing required environment variables"**
→ Double-check that all four secrets are set in Settings → Secrets → Actions. The names must match exactly: `GEMINI_API_KEY`, `RESEND_API_KEY`, `FROM_EMAIL`, `TO_EMAIL`.

**Email never arrives**
→ On Resend's free tier, `TO_EMAIL` must be the same email you registered with. Check your spam folder. Verify your Resend API key is active at [resend.com/api-keys](https://resend.com/api-keys).

**"All data sources returned empty results"**
→ This usually means temporary network issues or rate limiting. Wait an hour and trigger the workflow manually. If it persists, some RSS feed URLs in `sources.yaml` may have changed — check the logs in the Actions tab for specific error messages.

**Gemini synthesis fails**
→ Verify your Gemini API key at [aistudio.google.com](https://aistudio.google.com). The free tier allows 500 requests per day — if you've been testing heavily, you may have hit the limit.

---

## Rate Limits & Costs

| Service | Free Tier Limit | This Project Uses |
|---|---|---|
| Gemini API | 15 RPM, 500 RPD | 1 request per day |
| Resend | 100 emails/day, 3,000/month | 1 email per day |
| Reddit RSS | ~60 requests/hour (estimated) | 3 requests per run |
| GitHub | No auth required for trending page | 1 request per run |

Everything fits comfortably within free tiers.

---

## License

MIT
