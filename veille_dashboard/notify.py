"""Notifications : fichier Markdown, sortie console, e-mail SMTP, webhook."""
from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .digest import render_markdown, render_text


def write_files(digest: dict[str, Any], out_dir: str | Path = "data/digests") -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{digest['date']}.md"
    js = out / f"{digest['date']}.json"
    md.write_text(render_markdown(digest), encoding="utf-8")
    js.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": md, "json": js}


def send_email(digest: dict[str, Any], recipient: str | None = None) -> bool:
    """Envoi SMTP si SMTP_HOST, SMTP_USER et SMTP_PASSWORD sont définis."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    to = recipient or os.environ.get("VEILLE_EMAIL_TO")
    if not (host and user and password and to):
        return False

    message = EmailMessage()
    message["Subject"] = f"Veille du {digest['date']}"
    message["From"] = user
    message["To"] = to
    message.set_content(render_text(digest))
    message.add_alternative(render_markdown(digest), subtype="markdown")

    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(message)
    return True


def send_webhook(digest: dict[str, Any], url: str | None = None) -> bool:
    target = url or os.environ.get("VEILLE_WEBHOOK")
    if not target:
        return False
    request = urllib.request.Request(
        target, data=json.dumps(digest, ensure_ascii=False).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "veille-dashboard"})
    try:
        with urllib.request.urlopen(request, timeout=15):
            return True
    except (urllib.error.URLError, OSError):
        return False


def notify(digest: dict[str, Any], channels: list[str] | None = None,
           dry_run: bool = True) -> dict[str, Any]:
    """Envoie le digest. dry_run : rien n'est expédié, tout est affiché."""
    channels = channels or ["console"]
    outcome: dict[str, Any] = {"channels": {}}

    if "console" in channels:
        print(render_text(digest))
        outcome["channels"]["console"] = True

    if "file" in channels:
        paths = write_files(digest)
        outcome["channels"]["file"] = str(paths["markdown"])

    if "email" in channels:
        if dry_run:
            outcome["channels"]["email"] = "simulé"
        else:
            try:
                outcome["channels"]["email"] = send_email(digest)
            except (smtplib.SMTPException, OSError) as exc:
                outcome["channels"]["email"] = f"échec : {exc}"

    if "webhook" in channels:
        if dry_run:
            outcome["channels"]["webhook"] = "simulé"
        else:
            outcome["channels"]["webhook"] = send_webhook(digest)

    return outcome
