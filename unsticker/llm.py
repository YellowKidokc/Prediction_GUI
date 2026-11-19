"""Model tiers for the Unsticker ladder. All calls use the OpenAI-compatible
chat/completions shape, so any provider (Jev, DeepSeek, OpenRouter) plugs in by
config. Keys are read from the environment only and never written anywhere.

Env per tier (override any of them):
  OPENROUTER_API_KEY, JEV_MODEL            (Jev = cheap OpenRouter model)
  DEEPSEEK_API_KEY, DEEPSEEK_MODEL         (direct DeepSeek API)
  TOP_WRITER_MODEL (Opus 5.5), TOP_APPROVER_MODEL (Fable 5.2), both via OpenRouter
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Model:
    name: str
    base_url: str
    model: str
    key_env: str

    fallback: "Model | None" = None

    def with_fallback(self, other: "Model") -> "Model":
        self.fallback = other
        return self

    @property
    def ready(self) -> bool:
        own = bool(self.base_url and self.model and os.environ.get(self.key_env))
        return own or bool(self.fallback and self.fallback.ready)

    def chat(self, system: str, user: str, **kw) -> str:
        try:
            return self._chat(system, user, **kw)
        except Exception as exc:
            if not (self.fallback and self.fallback.ready):
                raise
            try:
                return self.fallback.chat(system, user, **kw)
            except Exception as exc2:
                raise RuntimeError(f"{redact(exc)} | fallback: {redact(exc2)}") from None

    def _chat(self, system: str, user: str, *, temperature: float = 0.2,
              max_tokens: int = 4000, timeout: int = 180) -> str:
        if not (self.base_url and self.model and os.environ.get(self.key_env)):
            raise RuntimeError(f"model tier {self.name} not configured")
        body = json.dumps({
            "model": self.model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode()
        key = os.environ[self.key_env].strip()
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        last = ""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
                return data["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}: {exc.read()[:300]!r}"
                if exc.code in (400, 401, 403, 404):
                    break
            except Exception as exc:  # never let a key-bearing message escape
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{self.name} call failed: {redact(last)}")


KEY_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{6})[A-Za-z0-9_\-]+|(Bearer\s+)\S+")


def redact(text: str) -> str:
    return KEY_RE.sub(lambda m: (m.group(1) + "…") if m.group(1) else m.group(2) + "…", str(text))


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k, d)


def tiers() -> dict[str, Model]:
    router = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    deepseek = Model("deepseek", _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                     _env("DEEPSEEK_MODEL", "deepseek-chat"), "DEEPSEEK_API_KEY")
    return {
        # Jev = the cheap OpenRouter call. Set JEV_MODEL to the exact model you want.
        "jev": Model("jev", router, _env("JEV_MODEL", "~deepseek/deepseek-flash-latest"),
                     "OPENROUTER_API_KEY"),
        # direct DeepSeek first; if it fails (e.g. out of balance), same model family via OpenRouter
        "deepseek": deepseek.with_fallback(
            Model("deepseek(openrouter)", router, _env("DEEPSEEK_ROUTER_MODEL", "deepseek/deepseek-v4-pro"),
                  "OPENROUTER_API_KEY")),
        "top_writer": Model("opus", router, _env("TOP_WRITER_MODEL", "anthropic/claude-opus-5.5"),
                            "OPENROUTER_API_KEY"),
        "top_approver": Model("fable", router, _env("TOP_APPROVER_MODEL", "anthropic/claude-fable-5.2"),
                              "OPENROUTER_API_KEY"),
    }


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ``` fences)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def yes_no(text: str) -> str:
    """Force a reply onto YES / NO / UNKNOWN."""
    head = text.strip().upper()[:40]
    if head.startswith("YES"):
        return "YES"
    if head.startswith("NO"):
        return "NO"
    return "UNKNOWN"
