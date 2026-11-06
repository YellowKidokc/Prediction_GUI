"""DeepSeek access. Two backends, same call:

  DEEPSEEK_BACKEND=ollama (default)  local Ollama, model DEEPSEEK_MODEL (default deepseek-r1:8b)
  DEEPSEEK_BACKEND=api               api.deepseek.com, key in DEEPSEEK_API_KEY, model deepseek-chat

Any failure raises LLMUnavailable; callers fall back to rules, never crash.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request


class LLMUnavailable(RuntimeError):
    pass


def _post(url: str, body: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailable(f"{url}: {exc}") from exc


def ollama_model() -> str:
    """Exact name if installed; else the first installed tag of the same family
    (deepseek-r1:8b -> deepseek-r1:latest). Ollama matches names exactly."""
    want = os.environ.get("DEEPSEEK_MODEL", "deepseek-r1:8b")
    try:
        url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags"
        with urllib.request.urlopen(url, timeout=5) as r:
            names = [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except Exception:  # noqa: BLE001
        return want
    if want in names or f"{want}:latest" in names:
        return want
    family = want.split(":")[0]
    return next((n for n in names if n.split(":")[0] == family), want)


def backend() -> str:
    return os.environ.get("DEEPSEEK_BACKEND", "ollama").lower()


def chat(system: str, user: str, timeout: int = 180) -> str:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if backend() == "api":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise LLMUnavailable("DEEPSEEK_API_KEY not set")
        body = _post(os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com") + "/chat/completions",
                     {"model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"), "messages": msgs,
                      "temperature": 0.2}, {"Authorization": f"Bearer {key}"}, timeout)
        text = body["choices"][0]["message"]["content"]
    else:
        body = _post(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat",
                     {"model": ollama_model(), "messages": msgs,
                      "stream": False, "options": {"temperature": 0.2}}, {}, timeout)
        text = body["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # r1 reasoning trace


def chat_json(system: str, user: str, timeout: int = 180) -> dict:
    text = chat(system + "\nReply with ONE JSON object and nothing else.", user, timeout)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise LLMUnavailable(f"no JSON in reply: {text[:200]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"bad JSON: {exc}") from exc
