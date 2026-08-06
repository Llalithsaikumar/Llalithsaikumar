#!/usr/bin/env python3
"""
Regenerates the dynamic parts of the profile README:

  * Selected Work  -> cards built from GitHub's *pinned* repositories.
                      Unpin a repo and it disappears on the next run.
  * assets/stats.svg / assets/langs.svg
                   -> self-hosted replacements for github-readme-stats,
                      whose public instance is rate-limited and often 500s.

Run by .github/workflows/profile.yml. Needs GITHUB_TOKEN in the env.
"""

import json
import os
import re
import urllib.request
from collections import defaultdict
from html import escape

TOKEN = os.environ["GITHUB_TOKEN"]
LOGIN = os.environ.get("PROFILE_LOGIN", "Llalithsaikumar")
ROOT = os.environ.get("GITHUB_WORKSPACE", ".")

ACCENT = "#6E56CF"
MUTED = "#7D8590"
LINE = "#8892A0"

QUERY = """
query($login: String!) {
  user(login: $login) {
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes {
        ... on Repository {
          name
          nameWithOwner
          description
          url
          stargazerCount
          forkCount
          isPrivate
          primaryLanguage { name color }
        }
      }
    }
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      restrictedContributionsCount
    }
    pullRequests(states: MERGED) { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def graphql(query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-readme-builder",
        },
    )
    with urllib.request.urlopen(req) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


# ---------------------------------------------------------------- shields

SHIELD = "https://img.shields.io/badge/{label}-{color}?style=flat-square"
# Simple Icons slugs differ from GitHub's language names in a few cases.
LOGO_SLUG = {
    "C#": "csharp", "C++": "cplusplus", "Jupyter Notebook": "jupyter",
    "Shell": "gnubash", "Vue": "vuedotjs", "Node": "nodedotjs",
    "SCSS": "sass", "Objective-C": "apple", "Dockerfile": "docker",
}


def readable_on(hex_color):
    """Pick black or white text for a background. Language colors like
    JavaScript's #f1e05a are far too light for white text."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "white"
    # relative luminance, sRGB coefficients
    return "black" if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 150 else "white"


def shield(label, color, logo=None):
    fg = readable_on(color)
    label = label.replace("-", "--").replace("_", "__").replace(" ", "%20")
    url = SHIELD.format(label=label, color=color.lstrip("#"))
    if logo:
        url += f"&logo={logo}&logoColor={fg}"
    return url


# ------------------------------------------------------------ pinned cards

def build_pinned(nodes):
    cards = [n for n in nodes if n and not n.get("isPrivate")]
    if not cards:
        return "<p><i>No pinned repositories.</i></p>"

    def cell(repo):
        lang = repo.get("primaryLanguage") or {}
        name = lang.get("name")
        color = (lang.get("color") or ACCENT).lstrip("#")
        slug = LOGO_SLUG.get(name, name.lower().replace(" ", "").replace(".", "dot")) if name else None

        badges = []
        if name:
            badges.append(
                f'<img src="{shield(name, color, slug)}" alt="{escape(name)}" />'
            )
        badges.append(
            f'<img src="https://img.shields.io/github/stars/{repo["nameWithOwner"]}'
            f'?style=flat-square&color={ACCENT.lstrip("#")}&labelColor=4A5568&logo=github&logoColor=white" alt="stars" />'
        )
        if repo["forkCount"]:
            badges.append(
                f'<img src="https://img.shields.io/github/forks/{repo["nameWithOwner"]}'
                f'?style=flat-square&color=4A5568&labelColor=4A5568" alt="forks" />'
            )

        desc = (repo.get("description") or "").strip() or "&nbsp;"
        title = repo["nameWithOwner"] if "/" in repo["nameWithOwner"] and \
            not repo["nameWithOwner"].startswith(LOGIN + "/") else repo["name"]

        return (
            f'<td width="50%" valign="top">\n'
            f'  <h4><a href="{repo["url"]}">{escape(title)}</a></h4>\n'
            f'  <p>{escape(desc)}</p>\n'
            f'  <p>{" ".join(badges)}</p>\n'
            f'</td>'
        )

    rows = []
    for i in range(0, len(cards), 2):
        pair = cards[i:i + 2]
        cells = "\n".join(cell(r) for r in pair)
        if len(pair) == 1:
            cells += '\n<td width="50%"></td>'
        rows.append(f"<tr>\n{cells}\n</tr>")

    return "<table>\n" + "\n".join(rows) + "\n</table>"


# --------------------------------------------------------------- svg cards

FONT = "'Segoe UI',Ubuntu,'Helvetica Neue',Helvetica,sans-serif"


def txt(x, y, s, size, weight, fill):
    """Presentation attributes, not CSS classes. A <style> block inside an SVG
    is honoured by browsers but ignored by several other renderers; inline
    attributes render identically everywhere."""
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}">{s}</text>')


def svg_header(w, h):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" fill="none" role="img">'
    )


def build_stats_svg(data, path):
    u = data["user"]
    c = u["contributionsCollection"]
    commits = c["totalCommitContributions"] + c["restrictedContributionsCount"]
    stars = sum(r["stargazerCount"] for r in u["repositories"]["nodes"])
    items = [
        (f'{stars}', "Total stars"),
        (f'{commits}', "Commits this year"),
        (f'{u["pullRequests"]["totalCount"]}', "Merged PRs"),
        (f'{u["repositories"]["totalCount"]}', "Repositories"),
        (f'{u["followers"]["totalCount"]}', "Followers"),
    ]
    w, h = 450, 165
    out = [svg_header(w, h)]
    out.append(f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="10" '
               f'fill="none" stroke="{LINE}" stroke-opacity="0.45"/>')
    out.append(txt(24, 34, "GitHub Statistics", 13, 600, ACCENT))
    out.append(f'<line x1="24" y1="46" x2="{w-24}" y2="46" stroke="{LINE}" stroke-opacity="0.3"/>')

    col_w = (w - 48) / 3
    for i, (num, label) in enumerate(items):
        col, row = i % 3, i // 3
        x = 24 + col * col_w
        y = 82 + row * 46
        out.append(txt(f"{x:.0f}", y, num, 22, 700, ACCENT))
        out.append(txt(f"{x:.0f}", y + 16, label, 11, 400, MUTED))
    out.append("</svg>")
    write(path, "".join(out))


def build_langs_svg(data, path):
    totals = defaultdict(int)
    colors = {}
    for repo in data["user"]["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            n = edge["node"]["name"]
            totals[n] += edge["size"]
            colors[n] = edge["node"]["color"] or ACCENT

    top = sorted(totals.items(), key=lambda kv: -kv[1])[:6]
    grand = sum(v for _, v in top) or 1

    w, h = 450, 165
    bar_x, bar_w, bar_y, bar_h = 24, w - 48, 62, 10
    out = [svg_header(w, h)]
    out.append(f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="10" '
               f'fill="none" stroke="{LINE}" stroke-opacity="0.45"/>')
    out.append(txt(24, 34, "Most Used Languages", 13, 600, ACCENT))
    out.append(f'<line x1="24" y1="46" x2="{w-24}" y2="46" stroke="{LINE}" stroke-opacity="0.3"/>')
    # Plain rects, no clipPath: clip-path support is inconsistent across SVG
    # renderers, and a segmented bar does not need it.
    cursor = bar_x
    for i, (name, size) in enumerate(top):
        seg = bar_w * size / grand
        if i == len(top) - 1:            # absorb rounding drift into the last
            seg = bar_x + bar_w - cursor
        out.append(f'<rect x="{cursor:.2f}" y="{bar_y}" width="{seg:.2f}" '
                   f'height="{bar_h}" fill="{colors[name]}"/>')
        cursor += seg

    col_w = (w - 48) / 2
    for i, (name, size) in enumerate(top):
        col, row = i % 2, i // 2
        x = 24 + col * col_w
        y = 104 + row * 20
        pct = 100 * size / grand
        out.append(f'<circle cx="{x+5}" cy="{y-4}" r="5" fill="{colors[name]}"/>')
        out.append(txt(f"{x+18:.0f}", y,
                       f"{escape(name)} &#160;{pct:.1f}%", 11, 400, MUTED))
    out.append("</svg>")
    write(path, "".join(out))


# ------------------------------------------------------------------ output

def write(path, content):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"wrote {path}")


def splice(readme_path, marker, block):
    with open(readme_path, encoding="utf-8") as f:
        text = f.read()
    pattern = re.compile(
        rf"(<!-- {marker}:START -->)(.*?)(<!-- {marker}:END -->)", re.S
    )
    if not pattern.search(text):
        raise SystemExit(f"marker {marker} not found in README")
    new = pattern.sub(lambda m: f"{m.group(1)}\n\n{block}\n\n{m.group(3)}", text)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"spliced {marker}")


def main():
    data = graphql(QUERY, {"login": LOGIN})
    readme = os.path.join(ROOT, "README.md")
    splice(readme, "PINNED", build_pinned(data["user"]["pinnedItems"]["nodes"]))
    build_stats_svg(data, "assets/stats.svg")
    build_langs_svg(data, "assets/langs.svg")


if __name__ == "__main__":
    main()
