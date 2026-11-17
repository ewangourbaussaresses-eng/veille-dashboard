"""Boîte à outils partagée : LLM (Claude / OpenAI / Ollama) avec repli hors ligne.

Chaque projet de dev-toolbox est autonome, mais tous utilisent ce même module :
copiez `llm.py` dans votre projet si vous n'en gardez qu'un seul.

Fournisseurs, par ordre de priorité (variable LLM_PROVIDER = auto | claude | openai | ollama | off) :
    ANTHROPIC_API_KEY   -> Claude (https://api.anthropic.com)
    OPENAI_API_KEY      -> OpenAI (https://api.openai.com)
    OLLAMA_HOST         -> Ollama local (http://localhost:11434, 100 % hors ligne)
Sans clé : le mode `off` est actif et chaque outil utilise sa logique locale.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OLLAMA_MODEL = "llama3.2"
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def _env(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or None


def ollama_host() -> str:
    return _env("OLLAMA_HOST") or "http://localhost:11434"


def active_provider() -> str:
    forced = (_env("LLM_PROVIDER") or "auto").lower()
    if forced in ("off", "none", "aucun", "false", "0"):
        return "off"
    if forced in ("claude", "openai", "ollama"):
        return forced if _configured(forced) else "off"
    for candidate in ("claude", "openai", "ollama"):
        if _configured(candidate):
            return candidate
    return "off"


def _configured(provider: str) -> bool:
    if provider == "claude":
        return bool(_env("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(_env("OPENAI_API_KEY"))
    if provider == "ollama":
        if _env("OLLAMA_MODEL"):
            return True
        # Ollama est « configuré » si le serveur local répond
        try:
            with urllib.request.urlopen(f"{ollama_host()}/api/tags", timeout=1):
                return True
        except Exception:  # noqa: BLE001
            return False
    return False


def is_available() -> bool:
    return active_provider() != "off"


def status() -> dict[str, Any]:
    provider = active_provider()
    models = {"claude": _env("ANTHROPIC_MODEL") or DEFAULT_CLAUDE_MODEL,
              "openai": _env("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
              "ollama": _env("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL}
    return {"provider": provider, "available": provider != "off",
            "model": models.get(provider),
            "claude_key": bool(_env("ANTHROPIC_API_KEY")),
            "openai_key": bool(_env("OPENAI_API_KEY")),
            "ollama_host": ollama_host() if provider == "ollama" else None}


def _post(url: str, payload: dict, headers: dict[str, str], timeout: int) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(f"HTTP {exc.code} : {exc.read().decode('utf-8', 'replace')[:300]}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"réseau : {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise LLMError("réponse illisible") from exc


def call_claude(prompt: str, system: str = "", max_tokens: int = 1024,
                temperature: float = 0.3, timeout: int = 60) -> LLMResponse:
    key = _env("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY absente")
    model = _env("ANTHROPIC_MODEL") or DEFAULT_CLAUDE_MODEL
    payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                               "temperature": temperature,
                               "messages": [{"role": "user", "content": prompt}]}
    if system:
        payload["system"] = system
    data = _post(ANTHROPIC_URL, payload,
                 {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}, timeout)
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text").strip()
    if not text:
        raise LLMError("réponse vide")
    usage = data.get("usage") or {}
    return LLMResponse(text, "claude", model, usage.get("input_tokens", 0),
                       usage.get("output_tokens", 0))


def call_openai(prompt: str, system: str = "", max_tokens: int = 1024,
                temperature: float = 0.3, timeout: int = 60) -> LLMResponse:
    key = _env("OPENAI_API_KEY")
    if not key:
        raise LLMError("OPENAI_API_KEY absente")
    model = _env("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    data = _post(OPENAI_URL, {"model": model, "messages": messages,
                              "max_tokens": max_tokens, "temperature": temperature},
                 {"Authorization": f"Bearer {key}"}, timeout)
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise LLMError("réponse inattendue") from exc
    usage = data.get("usage") or {}
    return LLMResponse(text, "openai", model, usage.get("prompt_tokens", 0),
                       usage.get("completion_tokens", 0))


def call_ollama(prompt: str, system: str = "", max_tokens: int = 1024,
                temperature: float = 0.3, timeout: int = 180) -> LLMResponse:
    model = _env("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
    payload = {"model": model, "stream": False,
               "options": {"temperature": temperature, "num_predict": max_tokens},
               "messages": ([{"role": "system", "content": system}] if system else []) +
                           [{"role": "user", "content": prompt}]}
    data = _post(f"{ollama_host()}/api/chat", payload, {}, timeout)
    text = (data.get("message") or {}).get("content", "").strip()
    if not text:
        raise LLMError("réponse vide d'Ollama")
    return LLMResponse(text, "ollama", model,
                       data.get("prompt_eval_count", 0), data.get("eval_count", 0))


def complete(prompt: str, system: str = "", **kwargs: Any) -> LLMResponse:
    provider = active_provider()
    if provider == "claude":
        return call_claude(prompt, system, **kwargs)
    if provider == "openai":
        return call_openai(prompt, system, **kwargs)
    if provider == "ollama":
        return call_ollama(prompt, system, **kwargs)
    raise LLMError("aucun fournisseur LLM configuré")


def complete_or_none(prompt: str, system: str = "", **kwargs: Any) -> LLMResponse | None:
    try:
        return complete(prompt, system=system, **kwargs)
    except LLMError:
        return None


def extract_json(text: str) -> Any:
    """Extrait le premier JSON valide d'une réponse (tolère ```json et texte autour)."""
    text = text.strip()
    candidates = [(text.find("["), text.rfind("]")), (text.find("{"), text.rfind("}"))]
    candidates.sort(key=lambda c: c[0] if c[0] != -1 else 10 ** 9)
    for start, end in candidates:
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("aucun JSON exploitable")


def ask_json(prompt: str, system: str = "", **kwargs: Any) -> Any:
    """Appelle le LLM et renvoie directement la donnée JSON, ou None si indisponible."""
    response = complete_or_none(prompt, system=system, **kwargs)
    if response is None:
        return None
    try:
        return extract_json(response.text)
    except LLMError:
        return None
