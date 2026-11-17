"""Lecture des flux : RSS/Atom, API GitHub (tendances), Reddit JSON — stdlib uniquement."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

USER_AGENT = "veille-dashboard/1.0 (+https://github.com/)"
TIMEOUT = 15

ATOM = "{http://www.w3.org/2005/Atom}"
RSS1 = "{http://purl.org/rss/1.0/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


@dataclass
class Item:
    title: str
    url: str
    source: str = ""
    summary: str = ""
    published: str = ""
    tags: list[str] = field(default_factory=list)
    score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "source": self.source,
                "summary": self.summary, "published": self.published,
                "tags": self.tags, "score": round(self.score, 3)}

    def key(self) -> str:
        return re.sub(r"[?#].*$", "", self.url).rstrip("/").lower()


def fetch(url: str, timeout: int = TIMEOUT, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def strip_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", text).strip()


def _text(element: ET.Element, tag: str) -> str:
    found = element.find(tag)
    if found is None:
        return ""
    return (found.text or "").strip()


def _link(element: ET.Element) -> str:
    link = element.find("link")
    if link is None:
        for candidate in element.findall(ATOM + "link"):
            if candidate.get("rel") in (None, "alternate"):
                return candidate.get("href", "")
        return ""
    return (link.text or link.get("href") or "").strip()


def parse_feed(xml_text: str, source: str = "") -> list[Item]:
    """Analyse un flux RSS 2.0, RSS 1.0 ou Atom."""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return []

    items: list[Item] = []
    entries = (root.findall(".//item") or root.findall(".//" + ATOM + "entry")
               or root.findall(".//" + RSS1 + "item"))
    for entry in entries[:60]:
        title = _text(entry, "title") or _text(entry, ATOM + "title")
        link = _link(entry)
        if not title or not link:
            continue
        raw_summary = (_text(entry, "description") or _text(entry, ATOM + "summary")
                       or _text(entry, CONTENT + "encoded")
                       or _text(entry, ATOM + "content"))
        published = (_text(entry, "pubDate") or _text(entry, ATOM + "updated")
                     or _text(entry, ATOM + "published") or _text(entry, "date"))
        tags = [c.get("term", "") for c in entry.findall(ATOM + "category")]
        tags += [c.text or "" for c in entry.findall("category")]
        items.append(Item(title=strip_html(title), url=link, source=source,
                          summary=strip_html(raw_summary)[:600],
                          published=normalize_date(published),
                          tags=[t for t in tags if t][:5]))
    return items


def normalize_date(text: str) -> str:
    """ISO 8601 quand c'est possible, sinon la chaîne d'origine."""
    if not text:
        return ""
    text = text.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text.replace("GMT", "+0000"), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return text


def fetch_rss(url: str, source: str = "") -> list[Item]:
    return parse_feed(fetch(url), source=source or url)


def fetch_github_trending(language: str = "", days: int = 7, limit: int = 15) -> list[Item]:
    """Dépôts créés récemment avec le plus d'étoiles, via l'API de recherche GitHub."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = f"created:>{since:%Y-%m-%d}"
    if language:
        query += f" language:{language}"
    url = (f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}"
           f"&sort=stars&order=desc&per_page={min(limit, 30)}")
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        data = json.loads(fetch(url, headers=headers))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []
    items = []
    for repo in data.get("items", [])[:limit]:
        items.append(Item(
            title=repo.get("full_name", ""),
            url=repo.get("html_url", ""),
            source="GitHub tendances",
            summary=(repo.get("description") or "")[:400],
            published=repo.get("created_at", ""),
            tags=[repo.get("language") or "n/a"],
            score=float(repo.get("stargazers_count", 0)) / 1000))
    return items


def fetch_reddit(subreddit: str, limit: int = 15) -> list[Item]:
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={limit}"
    try:
        data = json.loads(fetch(url, headers={"User-Agent": USER_AGENT}))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []
    items = []
    for child in data.get("data", {}).get("children", [])[:limit]:
        post = child.get("data", {})
        items.append(Item(
            title=post.get("title", ""),
            url="https://www.reddit.com" + post.get("permalink", ""),
            source=f"r/{subreddit}",
            summary=(post.get("selftext") or "")[:400],
            published=datetime.fromtimestamp(post.get("created_utc", 0), timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            score=float(post.get("score", 0)) / 100))
    return items


def collect(sources: list[dict[str, Any]], offline_fixtures: dict[str, str] | None = None
            ) -> list[Item]:
    """Récupère tous les flux d'une configuration ; ignore silencieusement les pannes."""
    fixtures = offline_fixtures or {}
    items: list[Item] = []
    for source in sources:
        kind = source.get("type", "rss")
        name = source.get("name") or source.get("url") or source.get("subreddit", "")
        try:
            if kind == "rss":
                url = source["url"]
                if url in fixtures:
                    items += parse_feed(fixtures[url], source=name)
                else:
                    items += fetch_rss(url, source=name)
            elif kind == "github":
                items += fetch_github_trending(language=source.get("language", ""),
                                               days=int(source.get("days", 7)),
                                               limit=int(source.get("limit", 10)))
            elif kind == "reddit":
                items += fetch_reddit(source["subreddit"], int(source.get("limit", 10)))
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            continue
    return items
