"""
The Frontier Brief — Delivery Module

Renders the structured newsletter JSON into a clean HTML email and delivers
it via the Resend API.
"""

import logging
import os
import re
from html import escape

import resend

logger = logging.getLogger(__name__)

# Divider reused between every section — 2px dark line
SECTION_DIVIDER = (
    '<tr><td style="padding: 0 30px;">'
    '<hr style="border: none; border-top: 2px solid #1a1a2e; margin: 0; opacity: 0.15;">'
    '</td></tr>'
)

# Section label font size (the ■ THE BIG STORY line)
SECTION_LABEL_STYLE = (
    "margin: 0 0 10px 0; font-size: 16px; font-weight: 800; "
    "text-transform: uppercase; letter-spacing: 1.5px;"
)


def _is_url(s: str) -> bool:
    """Return True if the string looks like a real http/https URL."""
    return bool(s) and re.match(r"^https?://", s.strip())


def _add_utm(url: str, date_str: str = "") -> str:
    """
    Append UTM tracking parameters to an outbound URL.

    This makes the newsletter analytics-ready — readers or evaluators with
    Google Analytics on their sites will see frontier-brief as a traffic source.
    Skips URLs that already have query params or are anchor links.
    """
    if not _is_url(url):
        return url
    campaign = date_str or "newsletter"
    sep = "&" if "?" in url else "?"
    return (
        f"{url}{sep}utm_source=frontier-brief"
        f"&utm_medium=email&utm_campaign={campaign}"
    )


def _linkify_subreddit(source: str) -> str:
    """
    Convert 'r/SubredditName' patterns in source strings to HTML hyperlinks.
    Leaves other text untouched. Returns safe HTML.
    """
    def replace(m):
        sub = m.group(1)
        return (
            f'<a href="https://www.reddit.com/r/{escape(sub)}" '
            f'style="color: #4a90d9; text-decoration: none;">r/{escape(sub)}</a>'
        )
    # Escape the whole string first, then un-escape our controlled substitution
    escaped = escape(source)
    return re.sub(r"r/([A-Za-z0-9_]+)", replace, escaped)


def _format_stars(stars: str) -> str:
    """Prefix star count with a star emoji if not already present."""
    if not stars:
        return ""
    s = stars.strip()
    if s and not s.startswith("⭐"):
        return f"⭐ {s} stars"
    return s


def render_html(newsletter: dict, tracking_pixel_url: str = "") -> str:
    """
    Render the newsletter dict into a clean, responsive HTML email.

    Uses inline CSS only (email clients strip <link> and <style> in <head>).
    Single-column, max-width 600px layout with system font stack.
    """
    date_str = escape(newsletter.get("generated_date", ""))
    big_story = newsletter["the_big_story"]
    frontier_watch = newsletter["frontier_watch"]
    street_says = newsletter["the_street_says"]
    repo = newsletter["repo_of_the_day"]
    two_steps = newsletter["two_steps_ahead"]

    # -----------------------------------------------------------------------
    # Frontier Watch items
    # -----------------------------------------------------------------------
    frontier_items_html = ""
    for item in frontier_watch:
        raw_url = item.get("source_url", "")
        source_link = ""
        if _is_url(raw_url):
            utm_url = _add_utm(raw_url.strip(), date_str)
            source_link = (
                f' <a href="{escape(utm_url)}" '
                f'style="color: #4a90d9; text-decoration: none; font-size: 13px;">'
                f'[source]</a>'
            )
        frontier_items_html += f"""
        <tr>
          <td style="padding: 12px 0; border-bottom: 1px solid #e0e0e0;">
            <strong style="color: #1a1a2e; font-size: 15px;">{escape(item.get("headline", ""))}</strong>{source_link}
            <p style="margin: 6px 0 4px 0; color: #333; font-size: 14px; line-height: 1.5;">
              {escape(item.get("summary", ""))}
            </p>
            <p style="margin: 2px 0 0 0; color: #666; font-size: 13px; font-style: italic;">
              Why it matters: {escape(item.get("why_it_matters", ""))}
            </p>
          </td>
        </tr>"""

    # -----------------------------------------------------------------------
    # Hot takes — sentiment_color from Gemini used as background tint
    # -----------------------------------------------------------------------
    hot_takes_html = ""
    for take in street_says.get("hot_takes", []):
        sentiment = take.get("sentiment", "").lower()
        # Gemini-supplied hex for background tint; fall back to neutral
        raw_bg = take.get("sentiment_color", "")
        bg_color = raw_bg if re.match(r"^#[0-9a-fA-F]{3,6}$", raw_bg) else "#f8f9fa"

        # Badge color matches the sentiment label
        badge_colors = {
            "bullish":             "#2d8a4e",
            "excited":             "#2d8a4e",
            "cautiously optimistic": "#4a7fcb",
            "bearish":             "#c0392b",
            "frustrated":          "#c0392b",
            "skeptical":           "#e67e22",
            "worried":             "#e67e22",
            "mixed":               "#7f8c8d",
        }
        badge_color = badge_colors.get(sentiment, "#7f8c8d")

        source_html = _linkify_subreddit(take.get("source", ""))

        hot_takes_html += f"""
        <tr>
          <td style="padding: 10px 0; border-bottom: 1px solid #e0e0e0;">
            <div style="background: {bg_color}; border-radius: 6px; padding: 10px 12px;">
              <span style="display: inline-block; background: {badge_color}; color: white;
                padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: bold;
                text-transform: uppercase; letter-spacing: 0.5px;">{escape(sentiment)}</span>
              <span style="color: #555; font-size: 12px; margin-left: 6px;">
                {source_html}
              </span>
              <p style="margin: 6px 0 0 0; color: #333; font-size: 14px; line-height: 1.5;">
                {escape(take.get("take", ""))}
              </p>
            </div>
          </td>
        </tr>"""

    # -----------------------------------------------------------------------
    # Big Story source links — filter out any non-URL values Gemini may return
    # -----------------------------------------------------------------------
    source_links_html = ""
    valid_sources = [s.strip() for s in big_story.get("sources", []) if _is_url(s)]
    if valid_sources:
        links = [
            f'<a href="{escape(_add_utm(url, date_str))}" style="color: #4a90d9; text-decoration: none;">[{i}]</a>'
            for i, url in enumerate(valid_sources, 1)
        ]
        source_links_html = (
            f'<p style="margin: 10px 0 0 0; font-size: 13px; color: #888;">'
            f'Sources: {" ".join(links)}</p>'
        )

    # -----------------------------------------------------------------------
    # Big Story headline — hyperlinked if there is exactly one valid source
    # -----------------------------------------------------------------------
    raw_headline = escape(big_story.get("headline", ""))
    if len(valid_sources) == 1:
        headline_html = (
            f'<a href="{escape(valid_sources[0])}" '
            f'style="color: #1a1a2e; text-decoration: none;">{raw_headline}</a>'
        )
    else:
        headline_html = raw_headline

    # Body paragraphs
    body_paragraphs = escape(big_story.get("body", "")).replace(
        "\n\n",
        '</p><p style="margin: 10px 0; color: #333; font-size: 15px; line-height: 1.6;">'
    )

    # Two Steps Ahead body paragraphs
    two_steps_body = escape(two_steps.get("body", "")).replace(
        "\n\n",
        '</p><p style="margin: 10px 0; color: #333; font-size: 15px; line-height: 1.6;">'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The Frontier Brief — {date_str}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f5f5f5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">

  <!-- Wrapper -->
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
    style="background-color: #f5f5f5;">
    <tr>
      <td align="center" style="padding: 20px 10px;">

        <!-- Main Container -->
        <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
          style="max-width: 600px; width: 100%; background-color: #ffffff; border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.10);">

          <!-- Header -->
          <tr>
            <td style="padding: 30px 30px 20px 30px; text-align: center;
              border-bottom: 3px solid #1a1a2e;">
              <h1 style="margin: 0; font-size: 26px; font-weight: 700; color: #1a1a2e;
                letter-spacing: -0.5px;">
                THE FRONTIER BRIEF
              </h1>
              <p style="margin: 6px 0 0 0; font-size: 13px; color: #888; letter-spacing: 1px;
                text-transform: uppercase;">
                {date_str} &middot; Signal, Not Noise
              </p>
            </td>
          </tr>

          <!-- The Big Story -->
          <tr>
            <td style="padding: 25px 30px 20px 30px;">
              <p style="{SECTION_LABEL_STYLE} color: #e74c3c;">
                &#9632; The Big Story
              </p>
              <h2 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #1a1a2e;
                line-height: 1.3;">
                {headline_html}
              </h2>
              <p style="margin: 10px 0; color: #333; font-size: 15px; line-height: 1.6;">
                {body_paragraphs}
              </p>
              <div style="background: #f8f9fa; border-left: 3px solid #1a1a2e; padding: 12px 16px;
                margin: 16px 0; border-radius: 0 4px 4px 0;">
                <p style="margin: 0; font-size: 14px; color: #333; line-height: 1.5;">
                  <strong>Why it matters:</strong> {escape(big_story.get("why_it_matters", ""))}
                </p>
              </div>
              {source_links_html}
            </td>
          </tr>

          {SECTION_DIVIDER}

          <!-- Frontier Watch -->
          <tr>
            <td style="padding: 20px 30px;">
              <p style="{SECTION_LABEL_STYLE} color: #2d8a4e;">
                &#9632; Frontier Watch
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                {frontier_items_html}
              </table>
            </td>
          </tr>

          {SECTION_DIVIDER}

          <!-- The Street Says -->
          <tr>
            <td style="padding: 20px 30px;">
              <p style="{SECTION_LABEL_STYLE} color: #e67e22;">
                &#9632; The Street Says
              </p>
              <p style="margin: 0 0 12px 0; color: #333; font-size: 14px; line-height: 1.5;">
                {escape(street_says.get("summary", ""))}
              </p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                {hot_takes_html}
              </table>
            </td>
          </tr>

          {SECTION_DIVIDER}

          <!-- Repo of the Day -->
          <tr>
            <td style="padding: 20px 30px;">
              <p style="{SECTION_LABEL_STYLE} color: #8e44ad;">
                &#9632; Repo of the Day
              </p>
              <div style="background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 6px;
                padding: 16px;">
                <h3 style="margin: 0 0 4px 0; font-size: 17px; color: #1a1a2e;">
                  <a href="{escape(repo.get("url", ""))}"
                    style="color: #4a90d9; text-decoration: none;">
                    {escape(repo.get("name", ""))}
                  </a>
                </h3>
                <p style="margin: 0 0 8px 0; font-size: 12px; color: #888;">
                  {_format_stars(repo.get("stars", ""))}
                </p>
                <p style="margin: 0 0 8px 0; color: #333; font-size: 14px; line-height: 1.5;">
                  {escape(repo.get("description", ""))}
                </p>
                <p style="margin: 0; color: #555; font-size: 14px; line-height: 1.5; font-style: italic;">
                  Why it matters: {escape(repo.get("why_it_matters", ""))}
                </p>
              </div>
            </td>
          </tr>

          {SECTION_DIVIDER}

          <!-- Two Steps Ahead -->
          <tr>
            <td style="padding: 20px 30px;">
              <p style="{SECTION_LABEL_STYLE} color: #000080;">
                &#9632; Two Steps Ahead
              </p>
              <p style="margin: 0; color: #333; font-size: 15px; line-height: 1.6;">
                {two_steps_body}
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 20px 30px; text-align: center; border-top: 3px solid #1a1a2e;">
              <p style="margin: 0 0 10px 0; font-size: 13px;">
                <a href="https://AaronVillegas5.github.io/frontier-brief/" style="color: #4a90d9; text-decoration: none;">
                  View Web Archive
                </a>
              </p>
              <p style="margin: 0; font-size: 12px; color: #aaa;">
                The Frontier Brief &middot; {date_str}<br>
                Signal, not noise. Curated and synthesized by AI, vetted for substance.
              </p>
            </td>
          </tr>

        </table>
        <!-- End Main Container -->

      </td>
    </tr>
  </table>
  <!-- End Wrapper -->
"""
    if tracking_pixel_url:
        sep = "&" if "?" in tracking_pixel_url else "?"
        pixel_url = f"{tracking_pixel_url}{sep}campaign={date_str}"
        html += f'\n  <img src="{escape(pixel_url)}" width="1" height="1" alt="" style="display:none;" />'

    html += "\n</body>\n</html>"
    logger.info("HTML email rendered (%d bytes)", len(html))
    return html


def send_email(html: str, date_str: str) -> None:
    """
    Send the newsletter HTML email via Resend.

    Required env vars: RESEND_API_KEY, FROM_EMAIL, TO_EMAIL.
    Free-tier Resend accounts can only send from onboarding@resend.dev
    and deliver to the registered account email.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("FROM_EMAIL") or "onboarding@resend.dev"
    to_email = os.environ.get("TO_EMAIL")

    if not api_key:
        raise RuntimeError("RESEND_API_KEY environment variable is not set")
    if not to_email:
        raise RuntimeError("TO_EMAIL environment variable is not set")

    resend.api_key = api_key

    params: resend.Emails.SendParams = {
        "from": f"The Frontier Brief <{from_email}>",
        "to": [to_email],
        "subject": f"The Frontier Brief — {date_str}",
        "html": html,
    }

    logger.info("Sending newsletter email to %s...", to_email)

    try:
        response = resend.Emails.send(params)
        email_id = response.get("id", "unknown")
        logger.info("Email sent successfully (Resend ID: %s)", email_id)
    except Exception as exc:
        logger.error("Email delivery failed: %s", exc)
        raise
