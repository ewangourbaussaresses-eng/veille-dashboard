# 📡 veille-dashboard

**Vos flux, filtrés et résumés : 5 actualités par jour, pas 500.**

Agrégateur de veille auto-hébergé : il collecte vos flux **RSS/Atom**, les **dépôts
GitHub tendance** et les **subreddits**, déduplique, classe selon vos centres
d'intérêt, résume chaque point (IA optionnelle) et produit un digest quotidien —
affiché dans une interface web minimale, écrit en Markdown/JSON, envoyable par e-mail
ou webhook.

Python standard, **zéro dépendance obligatoire**, tourne en local ou via GitHub Actions.

---

## Fonctionnalités

- collecte RSS 2.0 / Atom, tendances GitHub (API), Reddit (JSON) ;
- **déduplication** par URL et par titres quasi identiques ;
- **classement** : centres d'intérêt + fraîcheur + signaux de la source ;
- résumé par **IA** (Claude, OpenAI, Ollama) ou par extraits (hors ligne) ;
- digest en **Markdown**, **JSON**, **texte** ; historique consultable dans l'interface ;
- notifications : console, fichier, **e-mail SMTP**, **webhook** (`--send` requis) ;
- état `state.json` pour ne pas répéter les liens déjà vus.

## Installation

```bash
git clone <url-du-depot>
cd veille-dashboard
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Python 3.9+.

## Utilisation

```bash
# 1. configuration par défaut
veille-dashboard init --out config.json

# 2. générer le digest du jour
veille-dashboard run --config config.json --state data/state.json

# en markdown, ou en JSON pour un autre outil
veille-dashboard run --format markdown
veille-dashboard run --json

# 3. interface web (digest du jour + historique)
veille-dashboard serve          # http://127.0.0.1:8790
```

### Configurer ses sources

```json
{
  "profile": {
    "name": "Dev",
    "role": "développeur freelance",
    "interests": ["ia", "python", "sécurité"],
    "top_n": 5
  },
  "sources": [
    { "type": "rss",    "name": "Hacker News", "url": "https://news.ycombinator.com/rss" },
    { "type": "github", "language": "python", "days": 7, "limit": 10 },
    { "type": "reddit", "subreddit": "MachineLearning", "limit": 10 }
  ],
  "notify": { "channels": ["console", "file"] }
}
```

### Notifications

```bash
# e-mail (SMTP)
export SMTP_HOST=smtp.exemple.com SMTP_USER=moi@exemple.com \
       SMTP_PASSWORD=... VEILLE_EMAIL_TO=moi@exemple.com
veille-dashboard run --send

# webhook (Slack, Discord, n8n…)
export VEILLE_WEBHOOK="https://hooks.slack.com/services/…"
veille-dashboard run --send
```

Sans `--send`, rien n'est expédié : tout est affiché et écrit en local.

## Brancher une IA

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude (recommandé)
export OPENAI_API_KEY="sk-..."          # ou OpenAI
export OLLAMA_MODEL="llama3.2"          # ou Ollama, 100 % local
```

`veille-dashboard llm` affiche le fournisseur détecté. Sans clé, les résumés sont des
extraits tronqués des flux — le digest reste utilisable.

## Automatiser chaque matin

Un workflow est fourni : [`.github/workflows/veille.yml`](.github/workflows/veille.yml).
Il tourne à 07:00 UTC, écrit `data/digests/AAAA-MM-JJ.md` et commite le résultat.

## Limites (à savoir avant de l'installer)

- Les flux sont lus **sans rendu JavaScript** : les sites qui chargent leur contenu en JS
  ne fournissent souvent pas de RSS exploitable.
- Reddit et GitHub sont interrogés via leurs **API publiques** : sans jeton GitHub, la
  limite de requêtes est basse (l'outil ignore alors la source, sans planter).
- Le classement par règles est simple (mots-clés + fraîcheur) : l'IA améliore nettement
  les résumés, pas la sélection.
- Aucun scraping de sites sans flux : respectez les conditions d'utilisation des sources.

## Tests

```bash
python -m pytest -q     # 24 tests, aucun accès réseau (flux XML en mémoire)
```

## Licence

MIT — voir [LICENSE](LICENSE).
