"""Pipeline complet : collecte → sélection → résumé → notification."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .digest import build_digest, select_top
from .feeds import Item, collect
from .notify import notify
from .utils import get_logger, read_json, write_json

log = get_logger("veille")

DEFAULT_PROFILE = {
    "name": "Développeur",
    "role": "développeur / indépendant",
    "interests": ["ia", "python", "open source", "sécurité"],
    "top_n": 5,
}

DEFAULT_SOURCES = [
    {"type": "rss", "name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
    {"type": "rss", "name": "Le Monde Informatique",
     "url": "https://www.lemondeinformatique.fr/flux-rss/thematique/toutes-les-actualites/rss.xml"},
    {"type": "github", "language": "python", "days": 7, "limit": 10},
]


def load_config(path: str | Path) -> dict[str, Any]:
    data = read_json(path, default=None)
    if not isinstance(data, dict):
        raise SystemExit(f"✖ configuration illisible : {path}")
    profile = {**DEFAULT_PROFILE, **(data.get("profile") or {})}
    return {"profile": profile, "sources": data.get("sources") or DEFAULT_SOURCES,
            "notify": data.get("notify") or {"channels": ["console", "file"]}}


def run(config: dict[str, Any], use_llm: bool = True, dry_run: bool = True,
        fixtures: dict[str, str] | None = None) -> dict[str, Any]:
    profile = config["profile"]
    items = collect(config["sources"], offline_fixtures=fixtures)
    log.info("%d élément(s) collecté(s)", len(items))
    top = select_top(items, count=int(profile.get("top_n", 5)),
                     interests=profile.get("interests"))
    log.info("%d retenu(s) après sélection", len(top))

    digest = build_digest(top, profile, use_llm=use_llm)
    channels = (config.get("notify") or {}).get("channels", ["console"])
    outcome = notify(digest, channels=channels, dry_run=dry_run)
    # le fichier est toujours écrit : c'est la source de l'historique web
    if "file" not in channels and not dry_run:
        from .notify import write_files
        write_files(digest)
    return {"digest": digest, "collected": len(items), "selected": len(top),
            "notify": outcome}


def save_state(path: str | Path, digest: dict[str, Any]) -> Path:
    state = read_json(path, default={"seen": []}) or {"seen": []}
    seen = state.get("seen", [])
    for article in digest.get("articles", []):
        if article["url"] not in seen:
            seen.append(article["url"])
    return write_json(path, {"seen": seen[-500:], "last_run": digest["date"]})


def already_seen(path: str | Path, items: list[Item]) -> list[Item]:
    state = read_json(path, default={"seen": []}) or {"seen": []}
    seen = set(state.get("seen", []))
    return [item for item in items if item.url not in seen]


def dumps_digest(digest: dict[str, Any]) -> str:
    return json.dumps(digest, ensure_ascii=False, indent=2)
