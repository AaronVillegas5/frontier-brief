"""
The Frontier Brief — Trend Detection Module

Tracks which topics appear in the newsletter across multiple days by
maintaining a rolling 7-day history in data/topic_history.json.
This file is committed back to the repo after each run, making git
the state store — no database required.
"""

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

HISTORY_FILE = Path(__file__).parent.parent / "data" / "topic_history.json"
HISTORY_DAYS = 7          # rolling window
TREND_THRESHOLD = 3       # days a topic must appear to be flagged as "heating up"
MAX_TOPICS_PER_DAY = 20   # cap stored topics to keep file small

# Common words to exclude from topic extraction
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "this", "that", "these", "those", "it", "its", "their", "they", "we",
    "our", "your", "new", "said", "says", "also", "more", "can", "now",
    "how", "what", "when", "where", "who", "why", "not", "no", "all",
    "as", "so", "if", "than", "then", "just", "like", "use", "using",
    "day", "today", "time", "year", "one", "two", "three", "first", "next",
}


def load_history() -> dict:
    """
    Load the rolling topic history from disk.
    Returns an empty dict if the file doesn't exist yet (first run).
    Schema: {date_str: [topic, topic, ...], ...}
    """
    if not HISTORY_FILE.exists():
        logger.debug("No topic history file found — starting fresh")
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        logger.debug("Loaded topic history: %d days of data", len(history))
        return history
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load topic history (%s) — starting fresh", exc)
        return {}


def save_history(history: dict) -> None:
    """
    Write the updated history dict to disk.
    Creates the data/ directory if it doesn't exist.
    """
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logger.debug("Saved topic history to %s", HISTORY_FILE)
    except OSError as exc:
        logger.warning("Could not save topic history: %s", exc)


def extract_topics(newsletter: dict) -> list[str]:
    """
    Extract key topic words from today's newsletter headlines and summary text.

    Pulls from: big story headline, frontier watch headlines, repo name/desc.
    Returns a deduplicated list of meaningful multi-word phrases and key nouns.
    """
    text_sources = []

    # Big story
    big = newsletter.get("the_big_story", {})
    text_sources.append(big.get("headline", ""))
    text_sources.append(big.get("why_it_matters", ""))

    # Frontier watch headlines
    for item in newsletter.get("frontier_watch", []):
        text_sources.append(item.get("headline", ""))

    # Repo of the day
    repo = newsletter.get("repo_of_the_day", {})
    text_sources.append(repo.get("description", ""))

    # Two steps ahead (first sentence only — tends to name the theme)
    two_steps = newsletter.get("two_steps_ahead", {}).get("body", "")
    first_sentence = two_steps.split(".")[0] if "." in two_steps else two_steps[:150]
    text_sources.append(first_sentence)

    combined = " ".join(text_sources).lower()

    # Extract 2-word phrases (bigrams) that contain meaningful terms
    words = re.findall(r"\b[a-z][a-z\-]{2,}\b", combined)
    meaningful = [w for w in words if w not in STOPWORDS and len(w) > 3]

    # Count and return top topics
    counts = Counter(meaningful)
    top_words = [word for word, _ in counts.most_common(MAX_TOPICS_PER_DAY)]

    # Also extract known AI-domain bigrams
    bigrams = []
    for i in range(len(words) - 1):
        if words[i] not in STOPWORDS and words[i + 1] not in STOPWORDS:
            bigram = f"{words[i]} {words[i + 1]}"
            bigrams.append(bigram)
    bigram_counts = Counter(bigrams)
    top_bigrams = [b for b, c in bigram_counts.most_common(10) if c >= 2]

    return list(dict.fromkeys(top_words[:15] + top_bigrams[:5]))


def update_history(history: dict, newsletter: dict) -> dict:
    """
    Add today's topics to the history and prune entries older than HISTORY_DAYS.
    Returns the updated history dict.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    topics = extract_topics(newsletter)
    history[today] = topics
    logger.info("Trend detection: recorded %d topics for %s", len(topics), today)

    # Prune old entries
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    history = {date: topics for date, topics in history.items() if date >= cutoff}

    return history


def detect_heating_topics(history: dict) -> list[str]:
    """
    Return topics that have appeared in TREND_THRESHOLD or more days
    within the rolling history window.

    These are injected into the synthesis prompt to flag accelerating trends.
    """
    if len(history) < TREND_THRESHOLD:
        return []  # not enough history yet

    topic_day_counts: Counter = Counter()
    for daily_topics in history.values():
        # Count each topic once per day (not total mentions)
        for topic in set(daily_topics):
            topic_day_counts[topic] += 1

    heating = [
        topic for topic, count in topic_day_counts.items()
        if count >= TREND_THRESHOLD
    ]

    if heating:
        logger.info(
            "Trend detection: %d heating topics found: %s",
            len(heating), ", ".join(heating[:5])
        )
    else:
        logger.debug("Trend detection: no topics at threshold (%d days)", TREND_THRESHOLD)

    return heating
