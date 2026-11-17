"""CLI veille-dashboard."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, llm
from .digest import render_markdown, render_text
from .pipeline import DEFAULT_PROFILE, DEFAULT_SOURCES, load_config, run, save_state
from .utils import write_json
from .web import serve


def command_init(args: argparse.Namespace) -> int:
    path = Path(args.out)
    if path.exists() and not args.force:
        print(f"⚠ {path} existe déjà (--force pour l'écraser)")
        return 1
    write_json(path, {"profile": DEFAULT_PROFILE, "sources": DEFAULT_SOURCES,
                      "notify": {"channels": ["console", "file"]}})
    print(f"✔ configuration écrite : {path}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not args.no_save and "file" not in (config.get("notify") or {}).get("channels", []):
        config.setdefault("notify", {}).setdefault("channels", []).append("file")
    result = run(config, use_llm=not args.no_llm, dry_run=not args.send)
    digest = result["digest"]

    if args.json:
        print(json.dumps({"collected": result["collected"],
                          "selected": result["selected"], "digest": digest,
                          "notify": result["notify"]}, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(render_markdown(digest))
    elif not args.quiet:
        print(render_text(digest))

    if args.state:
        save_state(args.state, digest)
    return 0


def command_serve(args: argparse.Namespace) -> int:
    serve(host=args.host, port=args.port)
    return 0


def command_llm(args: argparse.Namespace) -> int:
    info = llm.status()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"Fournisseur : {info['provider']} "
          f"({'connecté' if info['available'] else 'non configuré'})")
    if info["model"]:
        print(f"Modèle      : {info['model']}")
    if not info["available"]:
        print("→ Sans clé, les résumés utilisent les extraits des flux.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veille-dashboard",
        description="Agrège vos flux, sélectionne les 5 actualités du jour et les résume.")
    parser.add_argument("--version", action="version", version=f"veille-dashboard {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="créer un config.json par défaut")
    init.add_argument("--out", default="config.json")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    run_cmd = sub.add_parser("run", help="collecter et générer le digest")
    run_cmd.add_argument("--config", default="config.json")
    run_cmd.add_argument("--format", choices=["text", "markdown"], default="text")
    run_cmd.add_argument("--json", action="store_true")
    run_cmd.add_argument("--no-llm", action="store_true", help="résumés par extraits")
    run_cmd.add_argument("--send", action="store_true",
                         help="envoyer réellement (e-mail / webhook) au lieu de simuler")
    run_cmd.add_argument("--state", help="fichier d'état pour ne pas répéter les liens")
    run_cmd.add_argument("--quiet", action="store_true")
    run_cmd.add_argument("--no-save", action="store_true",
                         help="ne pas écrire de fichier dans data/digests")
    run_cmd.set_defaults(func=command_run)

    web = sub.add_parser("serve", help="lancer l'interface web")
    web.add_argument("--port", type=int, default=8790)
    web.add_argument("--host", default="127.0.0.1")
    web.set_defaults(func=command_serve)

    llm_cmd = sub.add_parser("llm", help="état du connecteur IA")
    llm_cmd.add_argument("--json", action="store_true")
    llm_cmd.set_defaults(func=command_llm)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
