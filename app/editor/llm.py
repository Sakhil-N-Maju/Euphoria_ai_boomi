"""Minimal client for any OpenAI-compatible chat API (OpenAI, Groq, Gemini's OpenAI endpoint, a local server...)."""
from __future__ import annotations

import json
import re

from .config import env_value, load_config


class LLMError(RuntimeError):
    pass


def api_key() -> str | None:
    return env_value("LLM_API_KEY", "OPENAI_API_KEY")


def base_url() -> str:
    url = env_value("LLM_BASE_URL") or load_config().get("llm", {}).get("base_url") or "https://api.openai.com/v1"
    return url.rstrip("/")


def model_name() -> str:
    return env_value("LLM_MODEL") or load_config().get("llm", {}).get("model", "gpt-4.1-mini")


def configured() -> bool:
    return bool(api_key())


def chat_json(system: str, messages: list[dict], timeout: float | None = None) -> dict:
    """Send a chat and return the reply parsed as a JSON object."""
    return parse_json(_chat(system, messages, timeout, json_mode=True))


def chat_text(system: str, messages: list[dict], timeout: float | None = None) -> str:
    """Send a chat and return the reply as text (markdown). Messages may include images (OpenAI content parts)."""
    return _chat(system, messages, timeout or 240, json_mode=False).strip()


def _chat(system: str, messages: list[dict], timeout: float | None, json_mode: bool) -> str:
    import requests

    key = api_key()
    if not key:
        raise LLMError("No API key. Create app\\.env with a line LLM_API_KEY=your-key (or OPENAI_API_KEY=...).")
    body = {
        "model": model_name(),
        "messages": [{"role": "system", "content": system}, *messages],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    timeout = timeout or float(load_config().get("llm", {}).get("timeout", 120))
    try:
        r = requests.post(f"{base_url()}/chat/completions", json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except requests.RequestException as exc:
        raise LLMError(f"Could not reach the AI service: {exc}") from exc
    if r.status_code != 200:
        raise LLMError(f"AI service error {r.status_code}: {r.text[:400]}")
    try:
        content = r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Unexpected reply from the AI service: {r.text[:400]}") from exc
    return content


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating ```json fences or stray text around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError(f"The AI reply wasn't JSON: {text[:200]}")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"The AI reply wasn't valid JSON: {text[:200]}") from exc
    if not isinstance(data, dict):
        raise LLMError("The AI reply wasn't a JSON object.")
    return data
