"""Tests veille-dashboard — flux XML locaux, aucun accès réseau."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from veille_dashboard import llm  # noqa: E402
from veille_dashboard.cli import main  # noqa: E402
from veille_dashboard.digest import (age_hours, build_digest, deduplicate,  # noqa: E402
                                     keywords, render_markdown, render_text,
                                     score_items, select_top)
from veille_dashboard.feeds import Item, normalize_date, parse_feed, strip_html  # noqa: E402
from veille_dashboard.notify import notify, write_files  # noqa: E402
from veille_dashboard.pipeline import DEFAULT_PROFILE, load_config, run, save_state  # noqa: E402
from veille_dashboard.web_assets import INDEX_HTML  # noqa: E402


def recent(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


RSS = f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>Nouvelle version de Python</title><link>https://ex.com/py</link>
<description>La version 3.14 apporte des améliorations de performance.</description>
<pubDate>{recent(1)}</pubDate></item>
<item><title>Une faille critique dans une bibliothèque IA</title><link>https://ex.com/sec</link>
<description>Correctif disponible pour tous les utilisateurs.</description>
<pubDate>{recent(3)}</pubDate></item>
<item><title>Vieil article</title><link>https://ex.com/old</link>
<description>Très ancien.</description>
<pubDate>{recent(400)}</pubDate></item>
</channel></rss>"""

ATOM = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Article Atom</title>
    <link rel="alternate" href="https://ex.com/atom"/>
    <summary>Un résumé Atom.</summary>
    <updated>{recent(2)}</updated>
    <category term="python"/>
  </entry>
</feed>"""


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "OLLAMA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    yield


# --------------------------------------------------------------------------- #
# Flux
# --------------------------------------------------------------------------- #
def test_parse_feed_rss():
    items = parse_feed(RSS, source="Test")
    assert len(items) == 3
    assert items[0].title == "Nouvelle version de Python"
    assert items[0].source == "Test"


def test_parse_feed_atom():
    items = parse_feed(ATOM, source="Atom")
    assert items[0].url == "https://ex.com/atom"
    assert items[0].tags == ["python"]


def test_parse_feed_invalide():
    assert parse_feed("pas du xml") == []


def test_strip_html():
    assert strip_html("<p>Bonjour&nbsp;<b>monde</b></p>") == "Bonjour monde"


def test_normalize_date():
    assert normalize_date("Mon, 10 Mar 2026 12:00:00 GMT") == "2026-03-10T12:00:00Z"
    assert normalize_date("2026-03-10") == "2026-03-10T00:00:00Z"
    assert normalize_date("bizarre") == "bizarre"


# --------------------------------------------------------------------------- #
# Sélection
# --------------------------------------------------------------------------- #
def test_age_hours():
    assert 0.5 < age_hours(recent(1)) < 2
    assert age_hours("") is None
    assert age_hours("pas une date") is None


def test_keywords_ignore_mots_vides():
    item = Item(title="Nouvelle version de Python", url="https://ex.com",
                summary="pour les développeurs")
    words = keywords(item)
    assert "python" in words
    assert "de" not in words


def test_score_priorise_les_interets():
    items = parse_feed(RSS, source="Test")
    scored = score_items(items, ["python"])
    assert scored[0].url == "https://ex.com/py"


def test_score_ecarte_les_vieux_articles():
    items = parse_feed(RSS, source="Test")
    scored = score_items(items, ["python"], max_age_hours=72)
    assert all("old" not in item.url for item in scored)


def test_deduplicate_url_et_titres_proches():
    a = Item(title="Python 3.14 est sorti aujourd'hui", url="https://x.com/a?utm=1")
    b = Item(title="Python 3.14 est sorti aujourd'hui", url="https://x.com/b")
    c = Item(title="Python 3.14 est sorti aujourd'hui", url="https://x.com/a")
    assert len(deduplicate([a, b, c])) == 1


def test_select_top_limite():
    items = parse_feed(RSS, source="Test")
    assert len(select_top(items, count=2, interests=["python"])) <= 2


# --------------------------------------------------------------------------- #
# Digest
# --------------------------------------------------------------------------- #
def test_digest_local():
    items = parse_feed(RSS, source="Test")[:2]
    digest = build_digest(items, DEFAULT_PROFILE, use_llm=False)
    assert digest["engine"] == "rules"
    assert len(digest["articles"]) == 2
    assert digest["articles"][0]["why"]


def test_digest_llm_simule(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: {
        "intro": "Trois choses à retenir.",
        "items": [{"index": 1, "summary": "Python 3.14 sort.", "why": "Perf."}]})
    digest = build_digest(parse_feed(RSS)[:1], DEFAULT_PROFILE)
    assert digest["engine"] == "llm"
    assert digest["intro"] == "Trois choses à retenir."
    assert digest["articles"][0]["summary"] == "Python 3.14 sort."


def test_digest_repli_si_llm_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: None)
    assert build_digest(parse_feed(RSS)[:1], DEFAULT_PROFILE)["engine"] == "rules"


def test_render_markdown_et_text():
    digest = build_digest(parse_feed(RSS)[:2], DEFAULT_PROFILE, use_llm=False)
    assert "# Veille du" in render_markdown(digest)
    assert "Veille du" in render_text(digest)


# --------------------------------------------------------------------------- #
# Notification et pipeline
# --------------------------------------------------------------------------- #
def test_write_files(tmp_path: Path):
    digest = build_digest(parse_feed(RSS)[:1], DEFAULT_PROFILE, use_llm=False)
    paths = write_files(digest, out_dir=tmp_path)
    assert paths["markdown"].exists()
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["date"] == digest["date"]


def test_notify_console_file(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    digest = build_digest(parse_feed(RSS)[:1], DEFAULT_PROFILE, use_llm=False)
    outcome = notify(digest, channels=["console", "file"])
    assert outcome["channels"]["console"] is True
    assert (tmp_path / "data" / "digests" / f"{digest['date']}.md").exists()


def test_notify_email_simule():
    digest = build_digest(parse_feed(RSS)[:1], DEFAULT_PROFILE, use_llm=False)
    outcome = notify(digest, channels=["email"], dry_run=True)
    assert outcome["channels"]["email"] == "simulé"


def test_run_avec_fixtures():
    config = {"profile": {**DEFAULT_PROFILE, "top_n": 2},
              "sources": [{"type": "rss", "name": "Test", "url": "https://ex.com/rss"}],
              "notify": {"channels": []}}
    result = run(config, use_llm=False, dry_run=True, fixtures={"https://ex.com/rss": RSS})
    assert result["collected"] == 3
    assert result["selected"] == 2


def test_save_state(tmp_path: Path):
    digest = build_digest(parse_feed(RSS)[:2], DEFAULT_PROFILE, use_llm=False)
    path = save_state(tmp_path / "state.json", digest)
    assert len(json.loads(path.read_text(encoding="utf-8"))["seen"]) == 2


def test_load_config_defaut(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"profile": {"interests": ["rust"]}}), encoding="utf-8")
    config = load_config(path)
    assert config["profile"]["interests"] == ["rust"]
    assert config["sources"]  # sources par défaut


# --------------------------------------------------------------------------- #
# CLI et web
# --------------------------------------------------------------------------- #
def test_cli_init(tmp_path: Path, capsys):
    out = tmp_path / "config.json"
    assert main(["init", "--out", str(out)]) == 0
    assert out.exists()
    assert main(["init", "--out", str(out)]) == 1  # refuse d'écraser


def test_cli_llm(capsys):
    assert main(["llm"]) == 0
    assert "Fournisseur" in capsys.readouterr().out


def test_index_html():
    for marker in ("Veille du jour", "api/run", "Historique"):
        assert marker in INDEX_HTML
