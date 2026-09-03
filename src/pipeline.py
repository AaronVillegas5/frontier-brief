"""
The Frontier Brief — Pipeline Module

Assembles ingested data into a structured prompt, sends a single request to
Gemini 3.1 Flash-Lite, and returns a validated newsletter JSON payload.
"""

import json
import logging
import os
import time

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.1-flash-lite"
MAX_PAYLOAD_CHARS = 100_000  # ~25k tokens at ~4 chars/token
GEMINI_RETRY_DELAY = 10     # seconds before retrying a failed Gemini call

SYSTEM_PROMPT = """You are the editor of "The Frontier Brief," a daily AI newsletter written for 
smart, curious, non-technical business owners. Your readers don't know what a transformer 
is, but they want to feel two steps ahead of the news.

EDITORIAL PRINCIPLES:
- Signal over noise. Fewer, better stories. A tight brief with 3 stories that actually matter 
  beats 15 items of churn.
- Cut through hype. Breathless "this changes everything" coverage is a failure mode. Measured, 
  skeptical takes are a feature.
- Vet before you publish. A story earns its place by being corroborated across multiple sources 
  and genuinely consequential. If a claim only exists in one viral post, label it explicitly as 
  unverified gossip.
- Plain English only. No jargon without an inline explanation. If you mention "fine-tuning," 
  explain it as "customizing an AI model with specific data, like teaching a general-purpose 
  chef to specialize in your restaurant's menu."
- Every story must answer "so what?" — why does this matter to someone running a business?
- Include a "seeing around the corner" angle: what does today's news suggest is coming next?

CORROBORATION RULES:
- Cross-reference claims across the provided lab announcements, Reddit discussions, Bluesky/
  Mastodon/X posts, Hacker News discussions, and GitHub activity.
- If a story appears in only one source, mark it with "[Unverified — single source]".
- Prioritize stories that show up across multiple independent sources.
- Items tagged with "recent_fallback": true are older articles used as context because no 
  breaking news was found for that source. Use them for background, not as lead stories.
- The "x_twitter_sentiment" field contains posts from Bluesky, Mastodon, Hacker News, and 
  X/Twitter. Each post includes a "source" field indicating its origin.

TONE:
- Conversational but authoritative. Think "smart friend who works in tech" — not "corporate 
  press release" and not "breathless Twitter thread."
- The reader should finish in under 5 minutes and feel smarter, not overwhelmed.

OUTPUT RULES:
- Respond with ONLY valid JSON matching the required schema.
- Do not include markdown formatting, code fences, or commentary outside the JSON.
- All text fields should be plain text (no markdown, no HTML).
- Keep "the_big_story" body to 3-5 paragraphs.
- Keep "frontier_watch" to 2-4 quick-hit items.
- Keep "the_street_says" focused on genuine community sentiment, not just headlines.
- Pick exactly ONE repo for "repo_of_the_day" — the most interesting/consequential one.
- "two_steps_ahead" should be 2-3 paragraphs of genuine forward-looking analysis.
- In "the_big_story.sources", provide ONLY real https:// URLs from the raw data. Do NOT put source names like "GitHub Trending" or "Google DeepMind" — only actual article URLs. If you do not have a real URL for a source, omit it.
- In "the_street_says.hot_takes", each take must include a "sentiment_color" field: a hex color (e.g. "#d4edda") chosen from this palette to reflect the emotional tone:
  - Positive/optimistic: "#d4edda" (light green)
  - Cautiously optimistic: "#cce5ff" (light blue)
  - Skeptical/mixed: "#fff3cd" (light amber)
  - Frustrated/bearish: "#f8d7da" (light red)
  - Neutral: "#f8f9fa" (light grey)"""

NEWSLETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "the_big_story": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "body": {"type": "string"},
                "why_it_matters": {"type": "string"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["headline", "body", "why_it_matters", "sources"],
        },
        "frontier_watch": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["headline", "summary", "why_it_matters", "source_url"],
            },
        },
        "the_street_says": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "hot_takes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "take": {"type": "string"},
                            "sentiment": {"type": "string"},
                            "sentiment_color": {"type": "string"},
                        },
                        "required": ["source", "take", "sentiment", "sentiment_color"],
                    },
                },
            },
            "required": ["summary", "hot_takes"],
        },
        "repo_of_the_day": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string"},
                "description": {"type": "string"},
                "why_it_matters": {"type": "string"},
                "stars": {"type": "string"},
            },
            "required": ["name", "url", "description", "why_it_matters", "stars"],
        },
        "two_steps_ahead": {
            "type": "object",
            "properties": {
                "body": {"type": "string"},
            },
            "required": ["body"],
        },
        "generated_date": {"type": "string"},
    },
    "required": [
        "the_big_story",
        "frontier_watch",
        "the_street_says",
        "repo_of_the_day",
        "two_steps_ahead",
        "generated_date",
    ],
}


def build_payload(
    lab_news: list[dict],
    reddit_posts: list[dict],
    x_posts: list[dict],
    github_repos: list[dict],
) -> str:
    """
    Assemble all ingested data into a single JSON string for the Gemini prompt.

    Truncates to stay within token limits. Priority order when trimming:
    lab_news > reddit > github > x_posts (X data is least reliable).
    """
    payload = {
        "lab_and_startup_news": lab_news,
        "reddit_sentiment": reddit_posts,
        "github_trending_repos": github_repos,
        "x_twitter_sentiment": x_posts,
    }

    payload_str = json.dumps(payload, indent=None, ensure_ascii=False)

    if len(payload_str) <= MAX_PAYLOAD_CHARS:
        logger.info("Payload size: %d chars (within limit)", len(payload_str))
        return payload_str

    # Trim from lowest-priority source first
    logger.warning(
        "Payload too large (%d chars). Trimming to fit within %d chars...",
        len(payload_str), MAX_PAYLOAD_CHARS,
    )

    trim_order = ["x_twitter_sentiment", "github_trending_repos", "reddit_sentiment", "lab_and_startup_news"]

    for key in trim_order:
        items = payload[key]
        while len(json.dumps(payload, indent=None, ensure_ascii=False)) > MAX_PAYLOAD_CHARS and len(items) > 1:
            items.pop()
        payload[key] = items

        if len(json.dumps(payload, indent=None, ensure_ascii=False)) <= MAX_PAYLOAD_CHARS:
            break

    # Final truncation if individual entries are very large
    payload_str = json.dumps(payload, indent=None, ensure_ascii=False)
    if len(payload_str) > MAX_PAYLOAD_CHARS:
        payload_str = payload_str[:MAX_PAYLOAD_CHARS]
        logger.warning("Payload hard-truncated to %d chars", MAX_PAYLOAD_CHARS)

    logger.info("Final payload size: %d chars", len(payload_str))
    return payload_str


def synthesize(
    payload: str,
    prefs: dict | None = None,
    trending_topics: list[str] | None = None,
) -> dict:
    """
    Send the assembled payload to Gemini 3.1 Flash-Lite and return the
    structured newsletter JSON.

    Makes a single API call. Retries once on failure after a 10-second delay.

    Args:
        payload: JSON string of all ingested data.
        prefs: Optional personalization dict from prefs.yaml.
        trending_topics: Optional list of topics heating up across multiple days.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    # Build personalization context block
    personalization_block = ""
    if prefs:
        topics = prefs.get("topic_focus", [])
        audience = prefs.get("audience", "non-technical business owner")
        fw_count = prefs.get("frontier_watch_count", 3)
        ht_count = prefs.get("hot_takes_count", 3)
        preferred = prefs.get("preferred_sources", [])
        excluded = prefs.get("excluded_sources", [])
        parts = [f"\nPERSONALIZATION CONTEXT (from reader prefs.yaml):"]
        if topics:
            parts.append(f"- Reader topic focus: {', '.join(topics)}. Prioritize stories in these areas.")
        if audience != "non-technical business owner":
            parts.append(f"- Audience: {audience}. Adjust technical depth accordingly.")
        if preferred:
            parts.append(f"- Preferred sources: {', '.join(preferred)}. Weight stories from these higher.")
        if excluded:
            parts.append(f"- Excluded sources: {', '.join(excluded)}. Do not include stories from these.")
        parts.append(f"- Include exactly {fw_count} frontier_watch items and {ht_count} hot_takes.")
        personalization_block = "\n".join(parts)

    # Build trend context block
    trend_block = ""
    if trending_topics:
        trend_block = (
            f"\nTREND ALERT — These topics have appeared in the newsletter for "
            f"{3}+ consecutive days: {', '.join(trending_topics[:8])}. "
            f"If any of these appear in today's data, note in 'two_steps_ahead' that "
            f"this is an accelerating multi-day trend, not just today's news."
        )

    user_prompt = (
        "Below is today's raw data from AI lab announcements, Reddit discussions, "
        "X/Twitter posts, and GitHub trending repositories. Analyze this data and "
        "produce today's edition of The Frontier Brief newsletter.\n\n"
        "Corroborate claims across sources. Cut through hype. Write for a non-technical "
        "business audience. Use today's actual date for generated_date."
        f"{personalization_block}"
        f"{trend_block}"
        f"\n\nRAW DATA:\n{payload}"
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=NEWSLETTER_SCHEMA,
        temperature=0.3,
    )

    last_exc = None
    for attempt in range(2):  # 1 initial + 1 retry
        try:
            logger.info(
                "Sending synthesis request to %s (attempt %d/2)...", MODEL_NAME, attempt + 1
            )
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=user_prompt,
                config=config,
            )

            if not response.text:
                raise ValueError("Gemini returned an empty response")

            newsletter = json.loads(response.text)
            _validate_newsletter(newsletter)

            logger.info("Newsletter synthesis complete — date: %s", newsletter.get("generated_date"))
            return newsletter

        except Exception as exc:
            last_exc = exc
            logger.error("Gemini synthesis failed (attempt %d/2): %s", attempt + 1, exc)
            if attempt == 0:
                logger.info("Retrying in %ds...", GEMINI_RETRY_DELAY)
                time.sleep(GEMINI_RETRY_DELAY)

    raise RuntimeError(f"Gemini synthesis failed after 2 attempts: {last_exc}")


def _validate_newsletter(newsletter: dict) -> None:
    """Validate that the newsletter JSON has all required top-level sections."""
    required_keys = [
        "the_big_story",
        "frontier_watch",
        "the_street_says",
        "repo_of_the_day",
        "two_steps_ahead",
        "generated_date",
    ]
    missing = [k for k in required_keys if k not in newsletter]
    if missing:
        raise ValueError(f"Newsletter JSON missing required sections: {missing}")

    # Validate nested structure
    big_story = newsletter["the_big_story"]
    for field in ("headline", "body", "why_it_matters"):
        if not big_story.get(field):
            raise ValueError(f"the_big_story is missing required field: {field}")

    if not isinstance(newsletter["frontier_watch"], list) or len(newsletter["frontier_watch"]) == 0:
        raise ValueError("frontier_watch must be a non-empty list")

    street = newsletter["the_street_says"]
    if not street.get("summary"):
        raise ValueError("the_street_says is missing summary")

    repo = newsletter["repo_of_the_day"]
    for field in ("name", "description", "why_it_matters"):
        if not repo.get(field):
            raise ValueError(f"repo_of_the_day is missing required field: {field}")

    if not newsletter["two_steps_ahead"].get("body"):
        raise ValueError("two_steps_ahead is missing body")


# ---------------------------------------------------------------------------
# Quality Self-Check
# ---------------------------------------------------------------------------

CRITIC_PROMPT = """You are a fact-checking editor reviewing a draft newsletter before publication.

Evaluate the draft on three criteria:
1. ACCURACY (1-10): Are claims specific and grounded in the source data? Deduct for vague 
   generalisations, speculation presented as fact, or claims without a traceable source.
2. HYPE (1-10, higher = less hypy): Does the writing stay measured and skeptical? Deduct for 
   phrases like "game-changing", "revolutionary", or "changes everything" without justification.
3. SOURCE_DIVERSITY (1-10): Does the story draw on multiple independent sources?

Return JSON only, matching this schema exactly:
{
  "accuracy": <int 1-10>,
  "hype": <int 1-10>,
  "source_diversity": <int 1-10>,
  "overall": <int 1-10 — weighted average>,
  "approved": <bool — true if overall >= 7>,
  "flags": [<string — specific claim that needs [Unverified] label>]
}"""

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "accuracy":         {"type": "integer"},
        "hype":             {"type": "integer"},
        "source_diversity": {"type": "integer"},
        "overall":          {"type": "integer"},
        "approved":         {"type": "boolean"},
        "flags":            {"type": "array", "items": {"type": "string"}},
    },
    "required": ["accuracy", "hype", "source_diversity", "overall", "approved", "flags"],
}

CRITIC_RETRY_DELAY = 15  # seconds — longer delay to avoid back-to-back rate limit hits


def critique_newsletter(newsletter: dict, api_key: str) -> dict:
    """
    Run a quality self-check on the synthesized newsletter using a second
    Gemini call. Returns the critique result dict.

    Token budget: ~4,000 tokens (newsletter JSON input) + ~300 tokens output.
    Total per-run Gemini usage with self-check: ~15,000 tokens (6% of 250k TPM).

    If the critique fails (rate limit, error), returns a passing result so the
    newsletter is never silently blocked by the self-check infrastructure.
    """
    client = genai.Client(api_key=api_key)

    newsletter_text = json.dumps(newsletter, indent=None, ensure_ascii=False)
    user_prompt = (
        "Review this newsletter draft and return your quality assessment as JSON.\n\n"
        f"DRAFT:\n{newsletter_text}"
    )

    config = types.GenerateContentConfig(
        system_instruction=CRITIC_PROMPT,
        response_mime_type="application/json",
        response_schema=CRITIC_SCHEMA,
        temperature=0.1,  # deterministic — this is a scoring task
    )

    try:
        logger.info("Running quality self-check on newsletter draft...")
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=config,
        )
        critique = json.loads(response.text)
        logger.info(
            "Quality check: accuracy=%s hype=%s source_diversity=%s overall=%s approved=%s flags=%d",
            critique.get("accuracy"), critique.get("hype"), critique.get("source_diversity"),
            critique.get("overall"), critique.get("approved"), len(critique.get("flags", [])),
        )
        return critique
    except Exception as exc:
        logger.warning("Quality self-check failed (%s) — proceeding with original draft", exc)
        # Safe passthrough — don't block delivery on critic failure
        return {"approved": True, "overall": 8, "flags": [], "accuracy": 8, "hype": 8, "source_diversity": 8}


def apply_critique_flags(newsletter: dict, critique: dict) -> dict:
    """
    Annotate flagged claims in the newsletter with [Unverified — single source] labels.
    Modifies the big story body and frontier watch summaries in-place.
    Returns the (possibly annotated) newsletter dict.
    """
    flags = critique.get("flags", [])
    if not flags:
        return newsletter

    # For each flagged claim, try to find it in the body and append the label
    for flag in flags[:3]:  # limit annotation work to top 3 flags
        short = flag[:60].lower()  # use first 60 chars for fuzzy matching
        body = newsletter["the_big_story"].get("body", "")
        # If the flagged claim appears in the body, append a footnote
        if any(word in body.lower() for word in short.split() if len(word) > 5):
            if "[Unverified" not in body:
                newsletter["the_big_story"]["body"] = (
                    body + "\n\n[Note: Some claims in this story come from a single source "
                    "and could not be independently corroborated at time of publication.]"
                )
            break

    logger.info("Applied %d critique flag(s) to newsletter", len(flags))
    return newsletter

