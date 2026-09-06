"""
The Frontier Brief — Web Archive Index Generator

Generates index.html for the GitHub Pages web archive by scanning for
dated edition files (20*.html) in the current directory and rendering
a responsive archive listing sorted chronologically (newest first).
"""

from pathlib import Path


def generate_index(output_dir: Path = Path(".")) -> Path:
    files = sorted(output_dir.glob("20*.html"), reverse=True)
    links = "\n".join(
        f'      <li><a href="{f.name}">The Frontier Brief &mdash; {f.stem}</a></li>'
        for f in files
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>The Frontier Brief &mdash; Archive</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 600px;
      margin: 40px auto;
      padding: 0 20px;
      color: #1a1a2e;
    }}
    h1 {{
      font-size: 22px;
      border-bottom: 2px solid #1a1a2e;
      padding-bottom: 10px;
    }}
    ul {{
      list-style: none;
      padding: 0;
    }}
    li {{
      padding: 8px 0;
      border-bottom: 1px solid #eee;
    }}
    a {{
      color: #4a90d9;
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    .subtitle {{
      color: #888;
      font-size: 13px;
      margin-top: -10px;
    }}
  </style>
</head>
<body>
  <h1>The Frontier Brief</h1>
  <p class="subtitle">Signal, not noise. Daily AI newsletter &mdash; past editions.</p>
  <ul>
{links}
  </ul>
</body>
</html>"""
    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"Generated index.html with {len(files)} editions at {index_path}")
    return index_path


if __name__ == "__main__":
    generate_index()
