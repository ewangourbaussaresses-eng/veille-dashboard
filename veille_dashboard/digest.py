"""Sélection des actualités du jour et résumé personnalisé (IA ou règles)."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from . import llm
from .feeds import Item

SYSTEM = (
    "Tu es un analyste de veille technologique. Tu résumes des actualités en français, "
    "sans hype, sans superlatif, en indiquant pourquoi chaque point compte. Tu n'inventes "
    "aucun fait absent des titres fournis. Tu réponds UNIQUEMENT en JSON."
)

STOPWORDS = set("""
le la les un une des du de d au aux et ou mais donc or ni car que qui quoi dont où ce
cet cette ces son sa ses leur leurs il elle ils elles on nous vous je tu se est sont
être avoir a ont dans pour par sur avec sans sous entre chez vers plus moins très trop
peu tout tous toute toutes autre autres même aussi comme si non oui the and for with
that this from your you our their are was were will can has have not but all new how
why what when who
""".split())


def keywords(item: Item) -> set[str]:
    text = f"{item.title} {item.summary}".lower()
    words = re.findall(r"[a-zà-ÿ0-9][a-zà-ÿ0-9\-]{2,}", text)
    return {w for w in words if w not in STOPWORDS}


def age_hours(published: str) -> float | None:
    if not published:
        return None
    try:
        parsed = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 3600)


def score_items(items: list[Item], interests: list[str], max_age_hours: int = 72) -> list[Item]:
    """Pertinence = centres d'intérêt + fraîcheur + signaux de la source."""
    interests_lower = [i.lower() for i in interests]
    scored: list[Item] = []
    for item in items:
        words = keywords(item)
        relevance = sum(2.0 for interest in interests_lower
                        if interest in words or interest in item.title.lower())
        hours = age_hours(item.published)
        freshness = 0.0 if hours is None else max(0.0, 2.0 * math.exp(-hours / 48))
        if hours is not None and hours > max_age_hours:
            continue
        item.score = relevance + freshness + item.score
        if relevance == 0 and item.score < 1.0:
            continue
        scored.append(item)
    return sorted(scored, key=lambda i: -i.score)


def deduplicate(items: list[Item]) -> list[Item]:
    """Écarte les doublons d'URL et les titres quasi identiques."""
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    result: list[Item] = []
    for item in items:
        url_key = item.key()
        title_key = re.sub(r"[^a-zà-ÿ0-9 ]", "", item.title.lower())
        if url_key in seen_urls:
            continue
        if any(_similar(title_key, other) for other in seen_titles):
            continue
        seen_urls.add(url_key)
        seen_titles.append(title_key)
        result.append(item)
    return result


def _similar(a: str, b: str) -> bool:
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) > 0.6


def select_top(items: list[Item], count: int = 5, interests: list[str] | None = None
               ) -> list[Item]:
    unique = deduplicate(items)
    if interests:
        unique = score_items(unique, interests)
    else:
        unique = sorted(unique, key=lambda i: -i.score)
    return unique[:count]


def digest_with_llm(items: list[Item], profile: dict[str, Any]) -> dict[str, Any] | None:
    if not items:
        return None
    listing = "\n".join(
        f"{index}. {item.title} — {item.source} — {item.summary[:220]}"
        for index, item in enumerate(items, 1))
    prompt = f"""Voici les actualités retenues aujourd'hui pour un profil « {profile.get('role', 'développeur')} »
intéressé par : {', '.join(profile.get('interests', []))}.

{listing}

Pour CHAQUE actualité, écris un résumé de 2 phrases maximum expliquant ce qui se passe
et pourquoi ça compte pour ce profil. Puis une phrase d'introduction pour l'ensemble.

Réponds uniquement avec ce JSON :
{{"intro": "une phrase",
  "items": [{{"index": 1, "summary": "2 phrases", "why": "pourquoi ça compte"}}]}}"""
    data = llm.ask_json(prompt, system=SYSTEM, max_tokens=1400, temperature=0.4)
    return data if isinstance(data, dict) else None


def digest_locally(items: list[Item], profile: dict[str, Any]) -> dict[str, Any]:
    interests = [i.lower() for i in profile.get("interests", [])]
    entries = []
    for index, item in enumerate(items, 1):
        summary = item.summary or item.title
        if len(summary) > 240:
            summary = summary[:237].rsplit(" ", 1)[0] + "…"
        hit = next((i for i in interests if i in item.title.lower()
                    or i in item.summary.lower()), None)
        why = (f"Concerne directement votre veille « {hit} »." if hit
               else "À suivre dans votre domaine.")
        entries.append({"index": index, "summary": summary, "why": why})
    return {"intro": f"{len(items)} actualité(s) retenue(s) pour aujourd'hui.",
            "items": entries}


def build_digest(items: list[Item], profile: dict[str, Any],
                 use_llm: bool = True) -> dict[str, Any]:
    digest = None
    engine = "rules"
    if use_llm and llm.is_available():
        digest = digest_with_llm(items, profile)
        if digest:
            engine = "llm"
    if digest is None:
        digest = digest_locally(items, profile)

    summaries = {entry.get("index"): entry for entry in digest.get("items", [])
                 if isinstance(entry, dict)}
    articles = []
    for index, item in enumerate(items, 1):
        entry = summaries.get(index, {})
        articles.append({
            "title": item.title, "url": item.url, "source": item.source,
            "published": item.published,
            "summary": entry.get("summary") or item.summary[:240],
            "why": entry.get("why", ""),
            "score": round(item.score, 2),
        })
    return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "intro": digest.get("intro", ""), "articles": articles,
            "engine": engine, "profile": profile.get("name", "")}


def render_markdown(digest: dict[str, Any]) -> str:
    lines = [f"# Veille du {digest['date']}", ""]
    if digest.get("intro"):
        lines += [digest["intro"], ""]
    for index, article in enumerate(digest["articles"], 1):
        lines += [f"## {index}. {article['title']}", ""]
        if article.get("summary"):
            lines += [article["summary"], ""]
        if article.get("why"):
            lines += [f"> {article['why']}", ""]
        meta = article.get("source", "")
        if article.get("published"):
            meta += f" · {article['published'][:10]}"
        lines += [f"{meta} — [lire]({article['url']})", ""]
    return "\n".join(lines)


def render_text(digest: dict[str, Any]) -> str:
    lines = [f"Veille du {digest['date']}", "=" * 40, ""]
    if digest.get("intro"):
        lines += [digest["intro"], ""]
    for index, article in enumerate(digest["articles"], 1):
        lines.append(f"{index}. {article['title']}")
        if article.get("summary"):
            lines.append(f"   {article['summary']}")
        lines.append(f"   {article.get('source', '')} — {article['url']}")
        lines.append("")
    return "\n".join(lines)
