"""
The Frontier Brief — Main Entrypoint

Orchestrates the full pipeline:
  load config + prefs → ingest data → trend detection → synthesize newsletter
  via Gemini → quality self-check → render HTML → save archive → deliver email

Handles errors at each stage with retry logic and graceful degradation.
"""

import logging
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.ingestion import (
    fetch_github_trending,
    fetch_lab_news,
    fetch_reddit_sentiment,
    fetch_x_sentiment,
)
from src.pipeline import (
    build_payload,
    synthesize,
    critique_newsletter,
    apply_critique_flags,
)
from src.delivery import render_html, send_email
from src.trends import load_history, update_history, save_history, detect_heating_topics

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("frontier-brief")


def load_sources() -> dict:
    """Load the sources.yaml configuration file."""
    sources_path = Path(__file__).parent / "sources.yaml"
    if not sources_path.exists():
        logger.error("sources.yaml not found at %s", sources_path)
        sys.exit(1)

    with open(sources_path, "r", encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    logger.info("Loaded sources.yaml with %d lab/startup feeds", len(sources.get("lab_feeds", {})))
    return sources


def load_prefs() -> dict:
    """
    Load personalization preferences from prefs.yaml.
    Returns defaults if the file doesn't exist (backwards compatible).
    """
    prefs_path = Path(__file__).parent / "prefs.yaml"
    if not prefs_path.exists():
        return {}
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs = yaml.safe_load(f) or {}
        logger.info(
            "Loaded prefs.yaml: audience=%s, topic_focus=%d topics",
            prefs.get("audience", "non-technical business owner"),
            len(prefs.get("topic_focus", [])),
        )
        return prefs
    except Exception as exc:
        logger.warning("Could not load prefs.yaml (%s) — using defaults", exc)
        return {}


def save_archive(html: str, date_str: str) -> Path | None:
    """
    Save the rendered newsletter HTML to archive/YYYY-MM-DD.html.
    The archive/ directory is committed to the gh-pages branch by the
    GitHub Actions workflow after each run.
    """
    archive_dir = Path(__file__).parent / "archive"
    archive_dir.mkdir(exist_ok=True)

    # Save dated edition
    edition_path = archive_dir / f"{date_str}.html"
    edition_path.write_text(html, encoding="utf-8")
    logger.info("Archive: saved edition to %s", edition_path)

    return edition_path


def main() -> None:
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("THE FRONTIER BRIEF — Starting daily pipeline")
    logger.info("=" * 60)

    # Load environment variables from .env file (no-op if file doesn't exist)
    load_dotenv()

    # Validate required env vars early
    missing_vars = []
    for var in ("GEMINI_API_KEY", "RESEND_API_KEY", "TO_EMAIL"):
        if not os.environ.get(var):
            missing_vars.append(var)
    if missing_vars:
        logger.critical("Missing required environment variables: %s", ", ".join(missing_vars))
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")

    # Load data source configuration and personalization prefs
    sources = load_sources()
    prefs = load_prefs()

    # Apply excluded sources from prefs to lab_feeds
    excluded = set(prefs.get("excluded_sources", []))
    if excluded:
        lab_feeds = {k: v for k, v in sources.get("lab_feeds", {}).items() if k not in excluded}
        logger.info("Prefs: excluding %d source(s): %s", len(excluded), ", ".join(excluded))
    else:
        lab_feeds = sources.get("lab_feeds", {})

    # -----------------------------------------------------------------------
    # Trend detection — load rolling history before ingestion
    # -----------------------------------------------------------------------
    topic_history = load_history()
    trending_topics = detect_heating_topics(topic_history)
    if trending_topics:
        logger.info("Trending topics (3+ days): %s", ", ".join(trending_topics[:5]))

    # -----------------------------------------------------------------------
    # Stage 1: Ingestion
    # -----------------------------------------------------------------------
    logger.info("-" * 40)
    logger.info("STAGE 1: Data Ingestion")
    logger.info("-" * 40)

    lab_news = fetch_lab_news(lab_feeds)
    reddit_posts = fetch_reddit_sentiment(sources.get("subreddits", []))
    x_posts = fetch_x_sentiment(sources.get("x_search_terms", []))
    github_repos = fetch_github_trending(sources.get("github_trending", {}))

    total_items = len(lab_news) + len(reddit_posts) + len(x_posts) + len(github_repos)
    logger.info(
        "Ingestion summary: %d lab/startup articles, %d Reddit posts, "
        "%d social posts, %d GitHub repos (%d total)",
        len(lab_news), len(reddit_posts), len(x_posts), len(github_repos), total_items,
    )

    if total_items == 0:
        logger.critical(
            "All data sources returned empty results. "
            "Cannot produce a newsletter with no data. Aborting."
        )
        sys.exit(1)

    if total_items < 3:
        logger.warning(
            "Very few data items collected (%d). "
            "The newsletter quality may be limited.", total_items,
        )

    # -----------------------------------------------------------------------
    # Stage 2: Synthesis
    # -----------------------------------------------------------------------
    logger.info("-" * 40)
    logger.info("STAGE 2: Payload Assembly & Gemini Synthesis")
    logger.info("-" * 40)

    payload = build_payload(lab_news, reddit_posts, x_posts, github_repos)

    try:
        newsletter = synthesize(payload, prefs=prefs, trending_topics=trending_topics or None)
    except Exception as exc:
        logger.critical("Newsletter synthesis failed: %s", exc)
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Stage 2b: Quality Self-Check
    # -----------------------------------------------------------------------
    logger.info("Running quality self-check...")
    critique = critique_newsletter(newsletter, api_key)

    if not critique.get("approved", True):
        logger.warning(
            "Quality check score %s/10 — below threshold. Retrying synthesis once...",
            critique.get("overall"),
        )
        time.sleep(15)  # back off before second Gemini call
        try:
            newsletter_retry = synthesize(payload, prefs=prefs, trending_topics=trending_topics or None)
            critique_retry = critique_newsletter(newsletter_retry, api_key)
            if critique_retry.get("overall", 0) >= critique.get("overall", 0):
                logger.info("Retry improved quality score (%s → %s). Using retry.",
                            critique.get("overall"), critique_retry.get("overall"))
                newsletter = newsletter_retry
                critique = critique_retry
            else:
                logger.info("Retry did not improve quality. Using original draft.")
        except Exception as exc:
            logger.warning("Retry synthesis failed (%s) — falling back to original draft", exc)

    # Apply unverified flags from critic to the newsletter text
    newsletter = apply_critique_flags(newsletter, critique)

    date_str = newsletter.get("generated_date", "Unknown Date")

    # -----------------------------------------------------------------------
    # Stage 3: Rendering, Archive & Delivery
    # -----------------------------------------------------------------------
    logger.info("-" * 40)
    logger.info("STAGE 3: HTML Rendering, Archive & Email Delivery")
    logger.info("-" * 40)

    html = render_html(newsletter, tracking_pixel_url=prefs.get("tracking_pixel_url", ""))

    # Save to archive
    save_archive(html, date_str)

    # Retry email delivery once on failure
    try:
        send_email(html, date_str)
    except Exception as exc:
        logger.warning("First email delivery attempt failed: %s. Retrying in 5s...", exc)
        time.sleep(5)
        try:
            send_email(html, date_str)
        except Exception as exc2:
            logger.critical("Email delivery failed after 2 attempts: %s", exc2)
            sys.exit(1)

    # -----------------------------------------------------------------------
    # Stage 4: Post-delivery — update trend history
    # -----------------------------------------------------------------------
    topic_history = update_history(topic_history, newsletter)
    save_history(topic_history)

    # -----------------------------------------------------------------------
    # Done
    # -----------------------------------------------------------------------
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1f seconds", elapsed)
    logger.info("Newsletter delivered for %s", date_str)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
