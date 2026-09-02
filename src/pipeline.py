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
- Cross-reference claims across the provided lab announcements, Reddit discussions, X posts, 
  and GitHub activity.
- If a story appears in only one source, mark it with "[Unverified — single source]".
- Prioritize stories that show up across multiple independent sources.
- Items tagged with "recent_fallback": true are older articles used as context because no 
  breaking news was found for that source. Use them for background, not as lead stories.

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


def synthesize(payload: str) -> dict:
    """
    Send the assembled payload to Gemini 3.1 Flash-Lite and return the
    structured newsletter JSON.

    Makes a single API call. Retries once on failure after a 10-second delay.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    user_prompt = (
        "Below is today's raw data from AI lab announcements, Reddit discussions, "
        "X/Twitter posts, and GitHub trending repositories. Analyze this data and "
        "produce today's edition of The Frontier Brief newsletter.\n\n"
        "Corroborate claims across sources. Cut through hype. Write for a non-technical "
        "business audience. Use today's actual date for generated_date.\n\n"
        f"RAW DATA:\n{payload}"
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
