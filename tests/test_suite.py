"""
The Frontier Brief — Unit & Integration Tests

Run with: python -m pytest tests/ -v
Or:        python tests/test_suite.py
"""

import json
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Ensure project root is on the path
sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# delivery.py tests
# ---------------------------------------------------------------------------

class TestDeliveryHelpers(unittest.TestCase):

    def test_is_url_valid_https(self):
        from src.delivery import _is_url
        self.assertTrue(_is_url("https://example.com"))
        self.assertTrue(_is_url("https://deepmind.google/blog/some-article/"))

    def test_is_url_valid_http(self):
        from src.delivery import _is_url
        self.assertTrue(_is_url("http://example.com"))

    def test_is_url_rejects_names(self):
        from src.delivery import _is_url
        self.assertFalse(_is_url("Google DeepMind"))
        self.assertFalse(_is_url("GitHub Trending"))
        self.assertFalse(_is_url("Anthropic Engineering"))
        self.assertFalse(_is_url(""))
        self.assertFalse(_is_url(None))

    def test_format_stars_adds_emoji(self):
        from src.delivery import _format_stars
        self.assertEqual(_format_stars("121,191"), "⭐ 121,191 stars")
        self.assertEqual(_format_stars("5k"), "⭐ 5k stars")

    def test_format_stars_empty(self):
        from src.delivery import _format_stars
        self.assertEqual(_format_stars(""), "")
        self.assertEqual(_format_stars(None), "")

    def test_format_stars_no_double_emoji(self):
        from src.delivery import _format_stars
        result = _format_stars("⭐ 1,000 stars")
        self.assertEqual(result, "⭐ 1,000 stars")

    def test_linkify_subreddit_basic(self):
        from src.delivery import _linkify_subreddit
        result = _linkify_subreddit("r/MachineLearning")
        self.assertIn("https://www.reddit.com/r/MachineLearning", result)
        self.assertIn("<a href=", result)

    def test_linkify_subreddit_in_sentence(self):
        from src.delivery import _linkify_subreddit
        result = _linkify_subreddit("Reddit (r/LocalLLaMA)")
        self.assertIn("https://www.reddit.com/r/LocalLLaMA", result)

    def test_linkify_subreddit_no_match(self):
        from src.delivery import _linkify_subreddit
        result = _linkify_subreddit("Some plain text with no subreddit")
        self.assertNotIn("<a href=", result)
        self.assertIn("Some plain text", result)

    def test_linkify_subreddit_escapes_html(self):
        from src.delivery import _linkify_subreddit
        result = _linkify_subreddit("Test <script>alert(1)</script>")
        self.assertNotIn("<script>", result)

    def test_render_html_returns_string(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        html = render_html(stub)
        self.assertIsInstance(html, str)
        self.assertGreater(len(html), 1000)

    def test_render_html_headline_hyperlinked_single_source(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        stub["the_big_story"]["sources"] = ["https://example.com/article"]
        html = render_html(stub)
        self.assertIn('href="https://example.com/article"', html)

    def test_render_html_no_hyperlink_without_source(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        stub["the_big_story"]["sources"] = []
        html = render_html(stub)
        # headline should not be wrapped in an anchor
        self.assertNotIn("Test Headline</a>", html)

    def test_render_html_filters_non_url_sources(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        stub["the_big_story"]["sources"] = ["Google DeepMind", "GitHub Trending"]
        html = render_html(stub)
        # No [1] source links should appear since all sources are invalid
        self.assertNotIn("Sources:", html)

    def test_render_html_star_emoji_present(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        html = render_html(stub)
        self.assertIn("⭐", html)

    def test_render_html_subreddit_linked(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        stub["the_street_says"]["hot_takes"][0]["source"] = "r/MachineLearning"
        html = render_html(stub)
        self.assertIn("reddit.com/r/MachineLearning", html)

    def test_render_html_sentiment_color_applied(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        stub["the_street_says"]["hot_takes"][0]["sentiment_color"] = "#d4edda"
        html = render_html(stub)
        self.assertIn("#d4edda", html)

    def test_render_html_ignores_invalid_sentiment_color(self):
        from src.delivery import render_html
        stub = _stub_newsletter()
        stub["the_street_says"]["hot_takes"][0]["sentiment_color"] = "javascript:alert(1)"
        html = render_html(stub)
        self.assertNotIn("javascript:", html)


# ---------------------------------------------------------------------------
# ingestion.py tests
# ---------------------------------------------------------------------------

class TestIngestionHelpers(unittest.TestCase):

    def test_strip_html_removes_tags(self):
        from src.ingestion import _strip_html
        self.assertEqual(_strip_html("<p>Hello <b>world</b></p>"), "Hello world")

    def test_strip_html_collapses_whitespace(self):
        from src.ingestion import _strip_html
        self.assertEqual(_strip_html("<p>  foo   bar  </p>"), "foo bar")

    def test_strip_html_empty(self):
        from src.ingestion import _strip_html
        self.assertEqual(_strip_html(""), "")
        self.assertEqual(_strip_html(None), "")

    def test_parse_entry_date_from_published_parsed(self):
        from src.ingestion import _parse_entry_date
        entry = {"published_parsed": (2026, 9, 2, 12, 0, 0, 0, 0, 0)}
        result = _parse_entry_date(entry)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 9)
        self.assertEqual(result.day, 2)

    def test_parse_entry_date_none_when_missing(self):
        from src.ingestion import _parse_entry_date
        self.assertIsNone(_parse_entry_date({}))

    def test_within_cutoff_true_for_recent(self):
        from src.ingestion import _within_cutoff
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertTrue(_within_cutoff(recent, cutoff))

    def test_within_cutoff_false_for_old(self):
        from src.ingestion import _within_cutoff
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        self.assertFalse(_within_cutoff(old, cutoff))

    def test_within_cutoff_false_for_unknown(self):
        from src.ingestion import _within_cutoff
        cutoff = datetime.now(timezone.utc)
        self.assertFalse(_within_cutoff("unknown", cutoff))
        self.assertFalse(_within_cutoff("", cutoff))

    def test_retry_succeeds_on_first_try(self):
        from src.ingestion import _retry
        mock_fn = MagicMock(return_value="ok")
        result = _retry(mock_fn, "arg1")
        self.assertEqual(result, "ok")
        mock_fn.assert_called_once_with("arg1")

    def test_retry_retries_on_failure(self):
        from src.ingestion import _retry
        call_count = {"n": 0}

        def flaky_fn():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ValueError("transient failure")
            return "ok"

        with patch("src.ingestion.time.sleep"):
            result = _retry(flaky_fn)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count["n"], 3)

    def test_retry_raises_after_max_attempts(self):
        from src.ingestion import _retry

        def always_fails():
            raise ValueError("always fails")

        with patch("src.ingestion.time.sleep"):
            with self.assertRaises(ValueError):
                _retry(always_fails)


    def test_entry_to_article_basic(self):
        from src.ingestion import _entry_to_article
        entry = {
            "title": "Test Article",
            "link": "https://example.com",
            "summary": "<p>Some content</p>",
            "published_parsed": (2026, 9, 2, 12, 0, 0, 0, 0, 0),
        }
        result = _entry_to_article(entry, "Test Source")
        self.assertEqual(result["title"], "Test Article")
        self.assertEqual(result["url"], "https://example.com")
        self.assertEqual(result["source_name"], "Test Source")
        self.assertEqual(result["summary"], "Some content")
        self.assertFalse(result["recent_fallback"])

    def test_entry_to_article_fallback_flag(self):
        from src.ingestion import _entry_to_article
        entry = {"title": "Old", "link": "https://example.com"}
        result = _entry_to_article(entry, "Source", is_fallback=True)
        self.assertTrue(result["recent_fallback"])


# ---------------------------------------------------------------------------
# pipeline.py tests
# ---------------------------------------------------------------------------

class TestPipelinePayload(unittest.TestCase):

    def test_build_payload_within_limit(self):
        from src.pipeline import build_payload
        lab = [{"title": f"Article {i}", "url": f"https://example.com/{i}"} for i in range(5)]
        reddit = [{"title": f"Post {i}"} for i in range(5)]
        github = [{"name": f"repo{i}"} for i in range(3)]
        x = []
        payload = build_payload(lab, reddit, x, github)
        self.assertIsInstance(payload, str)
        parsed = json.loads(payload)
        self.assertIn("lab_and_startup_news", parsed)
        self.assertIn("reddit_sentiment", parsed)

    def test_build_payload_trims_when_over_limit(self):
        from src.pipeline import build_payload, MAX_PAYLOAD_CHARS
        # Create a payload guaranteed to exceed limit
        big_item = {"content": "x" * 10_000}
        lab = [big_item.copy() for _ in range(20)]
        reddit = [big_item.copy() for _ in range(20)]
        github = [big_item.copy() for _ in range(20)]
        x = [big_item.copy() for _ in range(20)]
        payload = build_payload(lab, reddit, x, github)
        self.assertLessEqual(len(payload), MAX_PAYLOAD_CHARS + 100)  # +100 tolerance for hard truncation

    def test_validate_newsletter_passes_valid(self):
        from src.pipeline import _validate_newsletter
        _validate_newsletter(_stub_newsletter())  # should not raise

    def test_validate_newsletter_fails_missing_section(self):
        from src.pipeline import _validate_newsletter
        stub = _stub_newsletter()
        del stub["two_steps_ahead"]
        with self.assertRaises(ValueError):
            _validate_newsletter(stub)

    def test_validate_newsletter_fails_empty_headline(self):
        from src.pipeline import _validate_newsletter
        stub = _stub_newsletter()
        stub["the_big_story"]["headline"] = ""
        with self.assertRaises(ValueError):
            _validate_newsletter(stub)

    def test_validate_newsletter_fails_empty_frontier_watch(self):
        from src.pipeline import _validate_newsletter
        stub = _stub_newsletter()
        stub["frontier_watch"] = []
        with self.assertRaises(ValueError):
            _validate_newsletter(stub)


# ---------------------------------------------------------------------------
# Integration: Live network tests (marked — skip in CI without flag)
# ---------------------------------------------------------------------------

class TestLiveIngestion(unittest.TestCase):
    """
    Live network tests. Skipped by default. Run with:
        python tests/test_suite.py --live
    """

    @classmethod
    def setUpClass(cls):
        cls.run_live = "--live" in sys.argv

    def _skip_if_not_live(self):
        if not self.run_live:
            self.skipTest("Skipping live test (run with --live flag)")

    def test_github_trending_returns_repos(self):
        self._skip_if_not_live()
        from src.ingestion import fetch_github_trending
        config = {
            "url": "https://github.com/trending",
            "since": "daily",
            "ai_keywords": ["ai", "llm", "machine learning"],
        }
        repos = fetch_github_trending(config)
        self.assertGreater(len(repos), 0)
        self.assertIn("name", repos[0])
        self.assertIn("url", repos[0])
        self.assertTrue(repos[0]["url"].startswith("https://github.com/"))

    def test_reddit_returns_posts(self):
        self._skip_if_not_live()
        from src.ingestion import fetch_reddit_sentiment
        posts = fetch_reddit_sentiment(["MachineLearning"])
        self.assertGreater(len(posts), 0)
        self.assertIn("title", posts[0])

    def test_lab_news_returns_articles(self):
        self._skip_if_not_live()
        from src.ingestion import fetch_lab_news
        feeds = {"OpenAI": {"url": "https://openai.com/news/rss.xml"}}
        articles = fetch_lab_news(feeds)
        self.assertGreater(len(articles), 0)
        self.assertIn("title", articles[0])
        self.assertIn("source_name", articles[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_newsletter() -> dict:
    """Return a minimal valid newsletter dict for render testing."""
    return {
        "the_big_story": {
            "headline": "Test Headline",
            "body": "First paragraph.\n\nSecond paragraph.",
            "why_it_matters": "Because it does.",
            "sources": ["https://example.com/article"],
        },
        "frontier_watch": [
            {
                "headline": "Watch Item",
                "summary": "A brief summary.",
                "why_it_matters": "It matters.",
                "source_url": "https://example.com/source",
            }
        ],
        "the_street_says": {
            "summary": "Overall sentiment is mixed.",
            "hot_takes": [
                {
                    "source": "r/MachineLearning",
                    "take": "A community hot take.",
                    "sentiment": "skeptical",
                    "sentiment_color": "#fff3cd",
                }
            ],
        },
        "repo_of_the_day": {
            "name": "owner / repo",
            "url": "https://github.com/owner/repo",
            "description": "A cool repository.",
            "why_it_matters": "It matters for developers.",
            "stars": "5,432",
        },
        "two_steps_ahead": {
            "body": "Looking forward, things will change.\n\nMore change incoming."
        },
        "generated_date": "2026-09-02",
    }


if __name__ == "__main__":
    # Strip --live from argv before passing to unittest
    argv = [a for a in sys.argv if a != "--live"]
    unittest.main(argv=argv, verbosity=2)
