"""
The Frontier Brief — Data Ingestion Module

Collectors for lab/startup RSS feeds, Reddit sentiment, X/Twitter sentiment,
and GitHub trending repositories. Each collector returns a list of dicts with
standardized fields and handles failures via retry + graceful degradation.
"""

import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LOOKBACK_HOURS = 24
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds — exponential backoff
FALLBACK_ENTRY_COUNT = 3   # entries per feed when 24h filter yields nothing
MAX_SUMMARY_CHARS = 1000

REQUEST_HEADERS = {
    "User-Agent": (
        "TheFrontierBrief/1.0 (Automated AI Newsletter; "
        "+https://github.com/frontier-brief)"
    )
}


def _retry(func, *args, **kwargs) -> Any:
    """Retry a callable up to MAX_RETRIES times with exponential backoff."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "Attempt %d/%d for %s failed: %s. Retrying in %ds...",
                    attempt + 1, MAX_RETRIES, func.__name__, exc, delay,
                )
                time.sleep(delay)
    raise last_exc


def _strip_html(html_text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_entry_date(entry: dict) -> datetime | None:
    """Extract a timezone-aware datetime from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    # Try parsing date strings directly
    for field in ("published", "updated"):
        date_str = entry.get(field, "")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(date_str).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _entry_to_article(entry: dict, source_name: str, is_fallback: bool = False) -> dict:
    """Convert a feedparser entry into a standardized article dict."""
    summary_raw = entry.get("summary", "") or entry.get("description", "")
    content_blocks = entry.get("content", [])
    if content_blocks and isinstance(content_blocks, list):
        full_content = content_blocks[0].get("value", "")
        if len(full_content) > len(summary_raw):
            summary_raw = full_content

    summary_clean = _strip_html(summary_raw)[:MAX_SUMMARY_CHARS]

    pub_date = _parse_entry_date(entry)
    pub_str = pub_date.isoformat() if pub_date else "unknown"

    return {
        "title": entry.get("title", "Untitled"),
        "url": entry.get("link", ""),
        "published": pub_str,
        "source_name": source_name,
        "summary": summary_clean,
        "recent_fallback": is_fallback,
    }


# ---------------------------------------------------------------------------
# Lab & Startup News
# ---------------------------------------------------------------------------

def fetch_lab_news(feeds: dict) -> list[dict]:
    """
    Fetch articles from lab/startup RSS feeds or scraped news pages.

    Routing:
    - feed_info["url"]       → RSS/Atom via feedparser
    - feed_info["scrape_url"] → HTML scrape via _scrape_news_page()

    Primary: articles published within the last 24 hours.
    Fallback: if no recent articles found for a feed, take the top 3 most
    recent entries regardless of date so Gemini can evaluate relevance.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    all_articles = []

    for source_name, feed_info in feeds.items():
        scrape_url = feed_info.get("scrape_url", "")
        rss_url = feed_info.get("url", "")

        # --- Scraped HTML path ---
        if scrape_url:
            try:
                articles = _retry(_scrape_news_page, scrape_url, source_name)
            except Exception as exc:
                logger.error("Failed to scrape news page for %s (%s): %s", source_name, scrape_url, exc)
                continue

            recent = [a for a in articles if _within_cutoff(a.get("published", ""), cutoff)]
            if recent:
                all_articles.extend(recent)
                logger.info("Scraped %d recent article(s) from %s", len(recent), source_name)
            else:
                fallback = articles[:FALLBACK_ENTRY_COUNT]
                for a in fallback:
                    a["recent_fallback"] = True
                all_articles.extend(fallback)
                logger.info("No recent articles from %s; used %d fallback entries", source_name, len(fallback))
            continue

        # --- RSS/Atom path ---
        if not rss_url:
            logger.warning("No URL or scrape_url configured for source: %s", source_name)
            continue

        try:
            feed = _retry(_fetch_feed, rss_url)
        except Exception as exc:
            logger.error("Failed to fetch feed for %s (%s): %s", source_name, rss_url, exc)
            continue

        entries = feed.get("entries", [])
        if not entries:
            logger.info("No entries found in feed for %s", source_name)
            continue

        # Primary filter: last 24 hours
        recent = []
        for entry in entries:
            pub_date = _parse_entry_date(entry)
            if pub_date and pub_date >= cutoff:
                recent.append(_entry_to_article(entry, source_name, is_fallback=False))

        if recent:
            all_articles.extend(recent)
            logger.info(
                "Fetched %d recent article(s) from %s", len(recent), source_name
            )
        else:
            # Fallback: take top N most recent entries regardless of date
            fallback = []
            sorted_entries = sorted(
                entries,
                key=lambda e: _parse_entry_date(e) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            for entry in sorted_entries[:FALLBACK_ENTRY_COUNT]:
                fallback.append(_entry_to_article(entry, source_name, is_fallback=True))

            all_articles.extend(fallback)
            logger.info(
                "No recent articles from %s; used %d fallback entries",
                source_name, len(fallback),
            )

    logger.info("Lab/startup news ingestion complete: %d total articles", len(all_articles))
    return all_articles


def _within_cutoff(published_str: str, cutoff: datetime) -> bool:
    """Return True if the published ISO string is after the cutoff datetime."""
    if not published_str or published_str == "unknown":
        return False
    try:
        from datetime import datetime as dt
        pub = dt.fromisoformat(published_str)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return pub >= cutoff
    except (ValueError, TypeError):
        return False


def _scrape_news_page(url: str, source_name: str) -> list[dict]:
    """
    Scrape an HTML news listing page and return article stubs.

    Works for sites that server-render article links (e.g. mistral.ai/news/).
    Extracts /news/* href links and their associated heading text.
    Returns articles sorted newest-first (by position on page, which typically
    matches reverse-chronological order on news listing pages).
    """
    response = requests.get(url, headers={
        **REQUEST_HEADERS,
        # Use a browser UA for JS-heavy sites that block bots
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    }, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    base = url.rstrip("/")
    domain = "/".join(base.split("/")[:3])  # e.g. https://mistral.ai

    seen_hrefs = set()
    articles = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        # Normalise to absolute URL
        if href.startswith("/"):
            href = domain + href
        elif not href.startswith("http"):
            continue

        # Only keep links that look like article paths (contain /news/)
        if "/news/" not in href or href.rstrip("/") == url.rstrip("/"):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # Best-effort title: text of the link or nearest heading ancestor
        title = a_tag.get_text(strip=True)
        if not title:
            parent = a_tag.find_parent(["h1", "h2", "h3", "h4", "article", "div"])
            if parent:
                heading = parent.find(["h1", "h2", "h3", "h4"])
                if heading:
                    title = heading.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        articles.append({
            "title": title,
            "url": href,
            "published": "unknown",  # no date available without fetching each article page
            "source_name": source_name,
            "summary": "",
            "recent_fallback": False,
        })

    return articles


def _fetch_feed(url: str) -> dict:
    """Fetch and parse an RSS/Atom feed with timeout."""
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    return feedparser.parse(response.text)


# ---------------------------------------------------------------------------
# Reddit Sentiment
# ---------------------------------------------------------------------------

REDDIT_REQUEST_DELAY = 6  # seconds between subreddit requests to avoid 429s


def fetch_reddit_sentiment(subreddits: list[str]) -> list[dict]:
    """
    Fetch hot posts from subreddits via RSS feeds.

    Uses .rss endpoints which still work without authentication, unlike the
    .json endpoints that now return 403 for unauthenticated requests.

    A 6-second delay between subreddits is enforced to stay within Reddit's
    undocumented rate limits for unauthenticated RSS access.
    """
    all_posts = []

    for i, sub in enumerate(subreddits):
        # Pause between requests — Reddit aggressively 429s rapid sequential hits
        if i > 0:
            time.sleep(REDDIT_REQUEST_DELAY)

        url = f"https://www.reddit.com/r/{sub}/hot/.rss"
        try:
            feed = _retry(_fetch_feed, url)
        except Exception as exc:
            logger.error("Failed to fetch Reddit RSS for r/%s: %s", sub, exc)
            continue

        entries = feed.get("entries", [])
        count = 0
        for entry in entries[:15]:  # top 15 from feed, take up to 10 after filtering
            if count >= 10:
                break

            content_raw = ""
            content_blocks = entry.get("content", [])
            if content_blocks and isinstance(content_blocks, list):
                content_raw = content_blocks[0].get("value", "")
            if not content_raw:
                content_raw = entry.get("summary", "")

            content_clean = _strip_html(content_raw)[:MAX_SUMMARY_CHARS]

            post = {
                "title": entry.get("title", "Untitled"),
                "url": entry.get("link", ""),
                "author": entry.get("author", "unknown"),
                "subreddit": sub,
                "content": content_clean,
                "published": (
                    _parse_entry_date(entry).isoformat()
                    if _parse_entry_date(entry) else "unknown"
                ),
            }
            all_posts.append(post)
            count += 1

        logger.info("Fetched %d post(s) from r/%s", count, sub)

    logger.info("Reddit ingestion complete: %d total posts", len(all_posts))
    return all_posts


# ---------------------------------------------------------------------------
# Social Sentiment (Bluesky · Mastodon · HN · X/Twitter fallback)
# ---------------------------------------------------------------------------

BLUESKY_SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
MASTODON_INSTANCES = [
    "https://fosstodon.org",       # tech/developer community
    "https://mastodon.social",     # general; large AI presence
]
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_x_sentiment(search_terms: list[str]) -> list[dict]:
    """
    Fetch developer/AI community social posts from multiple free sources.

    Priority:
    1. Bluesky public search API (unauthenticated, 3k req/5min)
    2. Mastodon hashtag timelines (fosstodon.org, mastodon.social — no auth)
    3. Hacker News Algolia search API (unauthenticated, 10k req/hr)
    4. X/Twitter via RSSHub → RSS.app (best-effort, often blocked)

    All four are attempted; results are deduplicated by URL and combined.
    Function is named fetch_x_sentiment for API compatibility with main.py.
    """
    all_posts: list[dict] = []
    seen_urls: set[str] = set()

    def _add(posts: list[dict]) -> None:
        for p in posts:
            url = p.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_posts.append(p)

    # 1. Bluesky
    bsky_posts = _fetch_bluesky(search_terms)
    _add(bsky_posts)

    # 2. Mastodon
    mastodon_posts = _fetch_mastodon(search_terms)
    _add(mastodon_posts)

    # 3. Hacker News
    hn_posts = _fetch_hacker_news(search_terms)
    _add(hn_posts)

    # 4. X/Twitter via bridges (best-effort)
    rss_app_token = os.environ.get("RSS_APP_TOKEN", "")
    for term in search_terms:
        x_posts = _try_rsshub_x_search(term)
        if not x_posts and rss_app_token:
            x_posts = _try_rss_app_x_search(term, rss_app_token)
        _add(x_posts)

    if all_posts:
        logger.info("Social sentiment ingestion complete: %d posts", len(all_posts))
    else:
        logger.warning(
            "Social sentiment ingestion returned no results from any source. "
            "Newsletter will proceed without social data."
        )

    return all_posts


def _fetch_bluesky(search_terms: list[str]) -> list[dict]:
    """
    Fetch AI-relevant posts from Bluesky using the public AppView search API.
    No authentication required. Returns up to 5 posts per search term.
    The public.api.bsky.app endpoint requires Accept: application/json
    and rejects generic bot User-Agent strings.
    """
    bsky_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; FrontierBrief/1.0; +https://github.com/frontier-brief)",
    }
    posts = []
    for term in search_terms[:3]:  # limit terms to avoid rate limit spikes
        try:
            response = requests.get(
                BLUESKY_SEARCH_URL,
                params={"q": term, "limit": 10, "lang": "en"},
                headers=bsky_headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            for post_obj in data.get("posts", [])[:5]:
                record = post_obj.get("record", {})
                author = post_obj.get("author", {})
                handle = author.get("handle", "unknown")
                uri = post_obj.get("uri", "")
                # Convert at:// URI to web URL
                url = ""
                if uri.startswith("at://"):
                    parts = uri.split("/")
                    if len(parts) >= 5:
                        url = f"https://bsky.app/profile/{handle}/post/{parts[-1]}"
                text = record.get("text", "")
                if not text or len(text) < 20:
                    continue
                posts.append({
                    "text": text[:MAX_SUMMARY_CHARS],
                    "author": f"@{handle}",
                    "url": url or f"https://bsky.app/profile/{handle}",
                    "published": record.get("createdAt", "unknown"),
                    "search_term": term,
                    "source": "bluesky",
                    "engagement": (
                        post_obj.get("likeCount", 0) +
                        post_obj.get("repostCount", 0)
                    ),
                })
            logger.debug("Bluesky: fetched posts for term '%s'", term)
        except Exception as exc:
            logger.debug("Bluesky search failed for '%s': %s", term, exc)
    return posts


def _fetch_mastodon(search_terms: list[str]) -> list[dict]:
    """
    Fetch posts from Mastodon hashtag public timelines.
    Uses fosstodon.org (developer-focused) and mastodon.social.
    No authentication required for public hashtag timelines.
    """
    # Map search terms to hashtags by stripping spaces
    tags = list({t.replace(" ", "").lower() for t in search_terms if t})[:3]
    posts = []

    for instance in MASTODON_INSTANCES:
        for tag in tags[:2]:  # 2 tags per instance to stay well under rate limits
            try:
                url = f"{instance}/api/v1/timelines/tag/{requests.utils.quote(tag)}"
                response = requests.get(
                    url,
                    params={"limit": 10},
                    headers=REQUEST_HEADERS,
                    timeout=10,
                )
                response.raise_for_status()
                statuses = response.json()
                for status in statuses[:5]:
                    content_html = status.get("content", "")
                    content_text = _strip_html(content_html)
                    if not content_text or len(content_text) < 20:
                        continue
                    account = status.get("account", {})
                    posts.append({
                        "text": content_text[:MAX_SUMMARY_CHARS],
                        "author": f"@{account.get('acct', 'unknown')}",
                        "url": status.get("url", ""),
                        "published": status.get("created_at", "unknown"),
                        "search_term": tag,
                        "source": f"mastodon/{instance.split('//')[-1]}",
                        "engagement": (
                            status.get("favourites_count", 0) +
                            status.get("reblogs_count", 0)
                        ),
                    })
                logger.debug("Mastodon: fetched %s#%s", instance, tag)
            except Exception as exc:
                logger.debug("Mastodon fetch failed (%s #%s): %s", instance, tag, exc)

    return posts


def _fetch_hacker_news(search_terms: list[str]) -> list[dict]:
    """
    Fetch recent AI-related stories from Hacker News via Algolia search API.
    No authentication required. Rate limit: 10,000 req/hr.
    Returns top stories from the last 24 hours for each search term.
    """
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp())
    posts = []
    seen_ids: set[str] = set()

    for term in search_terms[:3]:
        try:
            response = requests.get(
                HN_ALGOLIA_URL,
                params={
                    "query": term,
                    "tags": "story",
                    "hitsPerPage": 10,
                    "numericFilters": f"created_at_i>{cutoff_ts}",
                },
                headers=REQUEST_HEADERS,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            for hit in data.get("hits", [])[:5]:
                hn_id = hit.get("objectID", "")
                if not hn_id or hn_id in seen_ids:
                    continue
                seen_ids.add(hn_id)
                title = hit.get("title", "")
                if not title:
                    continue
                posts.append({
                    "text": title,
                    "author": hit.get("author", "unknown"),
                    "url": f"https://news.ycombinator.com/item?id={hn_id}",
                    "published": hit.get("created_at", "unknown"),
                    "search_term": term,
                    "source": "hacker_news",
                    "engagement": hit.get("points", 0),
                })
            logger.debug("HN Algolia: fetched stories for term '%s'", term)
        except Exception as exc:
            logger.debug("HN Algolia search failed for '%s': %s", term, exc)

    if posts:
        logger.info("Hacker News: %d stories fetched", len(posts))
    return posts


def _try_rsshub_x_search(term: str) -> list[dict]:
    """Try fetching X search results from a public RSSHub instance."""
    encoded_term = requests.utils.quote(term)
    url = f"https://rsshub.app/x/search/{encoded_term}"
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        posts = []
        for entry in feed.get("entries", [])[:5]:
            posts.append({
                "text": _strip_html(entry.get("summary", "") or entry.get("title", "")),
                "author": entry.get("author", "unknown"),
                "url": entry.get("link", ""),
                "published": (
                    _parse_entry_date(entry).isoformat()
                    if _parse_entry_date(entry) else "unknown"
                ),
                "search_term": term,
                "source": "x_rsshub",
            })
        return posts
    except Exception as exc:
        logger.debug("RSSHub X search failed for '%s': %s", term, exc)
        return []


def _try_rss_app_x_search(term: str, token: str) -> list[dict]:
    """Try fetching X search results from RSS.app with an API token."""
    encoded_term = requests.utils.quote(term)
    url = f"https://rss.app/feeds/v1.1/twitter/search/{encoded_term}"
    headers = {**REQUEST_HEADERS, "Authorization": f"Bearer {token}"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        posts = []
        for entry in feed.get("entries", [])[:5]:
            posts.append({
                "text": _strip_html(entry.get("summary", "") or entry.get("title", "")),
                "author": entry.get("author", "unknown"),
                "url": entry.get("link", ""),
                "published": (
                    _parse_entry_date(entry).isoformat()
                    if _parse_entry_date(entry) else "unknown"
                ),
                "search_term": term,
                "source": "x_rss_app",
            })
        return posts
    except Exception as exc:
        logger.debug("RSS.app X search failed for '%s': %s", term, exc)
        return []


# ---------------------------------------------------------------------------
# GitHub Trending
# ---------------------------------------------------------------------------

def fetch_github_trending(config: dict) -> list[dict]:
    """
    Scrape GitHub's trending page for AI-relevant repositories.

    Parses the server-rendered HTML to extract repo name, description,
    language, star count, and daily star gain. Filters for AI-related repos
    using keyword matching; falls back to top unfiltered repos if too few
    AI-specific results are found.
    """
    url = config.get("url", "https://github.com/trending")
    since = config.get("since", "daily")
    ai_keywords = [kw.lower() for kw in config.get("ai_keywords", ["ai", "llm", "machine learning"])]

    full_url = f"{url}?since={since}"

    try:
        html = _retry(_fetch_page, full_url)
    except Exception as exc:
        logger.error("Failed to fetch GitHub trending page: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    repo_rows = soup.select("article.Box-row")

    if not repo_rows:
        logger.warning("No repository rows found on GitHub trending page — HTML structure may have changed")
        return []

    all_repos = []
    for row in repo_rows:
        repo = _parse_trending_row(row)
        if repo:
            all_repos.append(repo)

    # Filter for AI-relevant repos
    ai_repos = []
    for repo in all_repos:
        searchable = f"{repo['name']} {repo['description']}".lower()
        if any(kw in searchable for kw in ai_keywords):
            ai_repos.append(repo)

    # Use AI-filtered list if we have enough; otherwise fall back to all trending
    if len(ai_repos) >= 3:
        result = ai_repos[:10]
        logger.info("GitHub trending: %d AI-relevant repos found", len(result))
    else:
        result = all_repos[:10]
        logger.info(
            "GitHub trending: only %d AI-relevant repos found; returning top %d overall",
            len(ai_repos), len(result),
        )

    return result


def _fetch_page(url: str) -> str:
    """Fetch a web page and return raw HTML."""
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
    response.raise_for_status()
    return response.text


def _parse_trending_row(row) -> dict | None:
    """Parse a single <article class="Box-row"> from GitHub trending."""
    try:
        # Repo name: <h2><a href="/owner/repo">...</a></h2>
        name_tag = row.select_one("h2 a")
        if not name_tag:
            return None
        repo_path = name_tag.get("href", "").strip("/")
        repo_name = repo_path.replace("/", " / ").strip() if repo_path else "unknown"
        repo_url = f"https://github.com/{repo_path}"

        # Description: <p class="col-9 ...">
        desc_tag = row.select_one("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Language
        lang_tag = row.select_one("[itemprop='programmingLanguage']")
        language = lang_tag.get_text(strip=True) if lang_tag else ""

        # Total stars: look for links containing /stargazers
        stars_total = ""
        star_links = row.select("a[href*='/stargazers']")
        if star_links:
            stars_total = star_links[0].get_text(strip=True).replace(",", "")

        # Stars today: <span class="d-inline-block float-sm-right">N stars today</span>
        stars_today = ""
        spans = row.select("span.d-inline-block")
        for span in spans:
            text = span.get_text(strip=True)
            if "star" in text.lower():
                stars_today = text
                break

        return {
            "name": repo_name,
            "url": repo_url,
            "description": description,
            "language": language,
            "stars_total": stars_total,
            "stars_today": stars_today,
        }
    except Exception as exc:
        logger.debug("Failed to parse trending row: %s", exc)
        return None
