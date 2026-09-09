"""
Comparison Script — Old Pipeline vs Graph-Enhanced Pipeline

Runs ingestion once, then calls synthesize() twice:
1. Without bridge_topics (old behavior)
2. With bridge_topics from the co-occurrence graph (new behavior)

Sends both as separate emails so you can compare side by side.
"""

import logging
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Ensure project root is on the path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.ingestion import (
    fetch_github_trending,
    fetch_lab_news,
    fetch_reddit_sentiment,
    fetch_x_sentiment,
)
from src.pipeline import build_payload, synthesize
from src.delivery import render_html, send_email
from src.trends import build_topic_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("comparison")


def main():
    load_dotenv(project_root / ".env")

    for var in ("GEMINI_API_KEY", "RESEND_API_KEY", "TO_EMAIL"):
        if not os.environ.get(var):
            logger.critical("Missing required env var: %s", var)
            sys.exit(1)

    # Load sources
    sources_path = project_root / "sources.yaml"
    with open(sources_path, "r", encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    lab_feeds = sources.get("lab_feeds", {})

    # -----------------------------------------------------------------------
    # Stage 1: Ingest data ONCE (shared by both pipelines)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("COMPARISON RUN — Ingesting data (shared)")
    logger.info("=" * 60)

    lab_news = fetch_lab_news(lab_feeds)
    reddit_posts = fetch_reddit_sentiment(sources.get("subreddits", []))
    x_posts = fetch_x_sentiment(sources.get("x_search_terms", []))
    github_repos = fetch_github_trending(sources.get("github_trending", {}))

    total = len(lab_news) + len(reddit_posts) + len(x_posts) + len(github_repos)
    logger.info("Ingestion complete: %d total items", total)

    if total == 0:
        logger.critical("No data ingested. Cannot proceed.")
        sys.exit(1)

    payload = build_payload(lab_news, reddit_posts, x_posts, github_repos)

    # -----------------------------------------------------------------------
    # Stage 1b: Build the topic graph
    # -----------------------------------------------------------------------
    bridge_topics = build_topic_graph(lab_news, reddit_posts, github_repos)
    logger.info("Bridge topics: %s", bridge_topics or "(none)")

    # -----------------------------------------------------------------------
    # Email A: OLD pipeline (no bridge topics)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("SYNTHESIZING EMAIL A — Old Pipeline (no graph)")
    logger.info("=" * 60)

    newsletter_old = synthesize(payload, bridge_topics=None)
    date_str = newsletter_old.get("generated_date", "unknown")

    repo_owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "aaronvillegas5").lower()
    newsletter_old["archive_url"] = f"https://{repo_owner}.github.io/frontier-brief/{date_str}.html"

    html_old = render_html(newsletter_old)

    # Override subject line to distinguish
    to_email = os.environ.get("TO_EMAIL", "")
    from_email = os.environ.get("FROM_EMAIL") or "onboarding@resend.dev"
    resend_key = os.environ.get("RESEND_API_KEY", "")

    import resend
    resend.api_key = resend_key
    resend.Emails.send({
        "from": f"The Frontier Brief <{from_email}>",
        "to": [to_email],
        "subject": f"[OLD - No Graph] The Frontier Brief - {date_str}",
        "html": html_old,
    })
    logger.info("Email A sent (OLD pipeline)")

    # Back off before second Gemini call
    logger.info("Waiting 15s before second synthesis...")
    time.sleep(15)

    # -----------------------------------------------------------------------
    # Email B: NEW pipeline (with bridge topics)
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("SYNTHESIZING EMAIL B - Graph-Enhanced Pipeline")
    logger.info("=" * 60)

    newsletter_new = synthesize(payload, bridge_topics=bridge_topics or None)
    date_str_new = newsletter_new.get("generated_date", "unknown")

    newsletter_new["archive_url"] = f"https://{repo_owner}.github.io/frontier-brief/{date_str_new}.html"

    html_new = render_html(newsletter_new)

    resend.Emails.send({
        "from": f"The Frontier Brief <{from_email}>",
        "to": [to_email],
        "subject": f"[NEW - Graph Enhanced] The Frontier Brief - {date_str_new}",
        "html": html_new,
    })
    logger.info("Email B sent (NEW graph-enhanced pipeline)")


    logger.info("=" * 60)
    logger.info("COMPARISON COMPLETE - Check your inbox for both emails")
    logger.info("=" * 60)



if __name__ == "__main__":
    main()
