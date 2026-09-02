"""
The Frontier Brief — Main Entrypoint

Orchestrates the full pipeline: load config → ingest data → synthesize
newsletter via Gemini → render HTML → deliver email. Handles errors at
each stage with retry logic and graceful degradation.
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
from src.pipeline import build_payload, synthesize
from src.delivery import render_html, send_email

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

    # Load data source configuration
    sources = load_sources()

    # -----------------------------------------------------------------------
    # Stage 1: Ingestion
    # -----------------------------------------------------------------------
    logger.info("-" * 40)
    logger.info("STAGE 1: Data Ingestion")
    logger.info("-" * 40)

    lab_news = fetch_lab_news(sources.get("lab_feeds", {}))
    reddit_posts = fetch_reddit_sentiment(sources.get("subreddits", []))
    x_posts = fetch_x_sentiment(sources.get("x_search_terms", []))
    github_repos = fetch_github_trending(sources.get("github_trending", {}))

    # Check if we have enough data to produce a newsletter
    total_items = len(lab_news) + len(reddit_posts) + len(x_posts) + len(github_repos)
    logger.info(
        "Ingestion summary: %d lab/startup articles, %d Reddit posts, "
        "%d X/Twitter posts, %d GitHub repos (%d total)",
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
        newsletter = synthesize(payload)
    except Exception as exc:
        logger.critical("Newsletter synthesis failed: %s", exc)
        sys.exit(1)

    date_str = newsletter.get("generated_date", "Unknown Date")

    # -----------------------------------------------------------------------
    # Stage 3: Rendering & Delivery
    # -----------------------------------------------------------------------
    logger.info("-" * 40)
    logger.info("STAGE 3: HTML Rendering & Email Delivery")
    logger.info("-" * 40)

    html = render_html(newsletter)

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
    # Done
    # -----------------------------------------------------------------------
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1f seconds", elapsed)
    logger.info("Newsletter delivered for %s", date_str)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
