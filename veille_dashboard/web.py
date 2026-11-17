"""Interface web minimaliste (stdlib) : le digest du jour + l'historique."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import llm
from .digest import render_markdown
from .pipeline import load_config, run
from .web_assets import INDEX_HTML

CONFIG_PATH = Path("config.json")
DIGESTS_DIR = Path("data/digests")


def latest_digests(limit: int = 10) -> list[dict[str, Any]]:
    if not DIGESTS_DIR.exists():
        return []
    files = sorted(DIGESTS_DIR.glob("*.json"), reverse=True)[:limit]
    digests = []
    for path in files:
        try:
            digests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return digests


def create_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "veille-dashboard/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: Any) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(200, {**llm.status(), "digests": len(latest_digests(50))})
            elif path == "/api/digests":
                self._json(200, latest_digests(10))
            elif path.startswith("/api/digest/"):
                date = path.rsplit("/", 1)[-1]
                file = DIGESTS_DIR / f"{date}.json"
                if file.exists():
                    self._json(200, json.loads(file.read_text(encoding="utf-8")))
                else:
                    self._json(404, {"error": "digest inconnu"})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/run":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            payload = {}
            if length:
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    payload = {}
            try:
                config = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else {
                    "profile": {"interests": payload.get("interests", [])},
                    "sources": [], "notify": {"channels": ["file"]}}
            except SystemExit as exc:
                self._json(400, {"error": str(exc)})
                return

            if payload.get("interests"):
                config["profile"]["interests"] = payload["interests"]
            result = run(config, use_llm=not payload.get("no_llm", False),
                         dry_run=True)
            self._json(200, {"digest": result["digest"],
                             "markdown": render_markdown(result["digest"]),
                             "collected": result["collected"],
                             "selected": result["selected"]})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8790) -> None:
    server = ThreadingHTTPServer((host, port), create_handler())
    print(f"veille-dashboard → http://{host}:{port}  (Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
