"""One function to get JSON back from an AI model: OpenAI or Claude.

Which one is used:
  AI_PROVIDER=openai     -> needs OPENAI_API_KEY   (model: OPENAI_MODEL, default below)
  AI_PROVIDER=anthropic  -> needs ANTHROPIC_API_KEY (model: claude-opus-5-5)
If AI_PROVIDER is blank, whichever key is set is used (OpenAI first).
"""

import json
import os

import httpx

from .config import MODEL as CLAUDE_MODEL

OPENAI_DEFAULT_MODEL = "gpt-5"


class AIError(RuntimeError):
    pass


def provider() -> str:
    chosen = os.environ.get("AI_PROVIDER", "").strip().lower()
    if chosen in ("openai", "anthropic"):
        return chosen
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return ""


def available() -> bool:
    p = provider()
    return bool(p and os.environ.get("OPENAI_API_KEY" if p == "openai" else "ANTHROPIC_API_KEY"))


def complete_json(system: str, user: str, schema: dict, schema_name: str = "result") -> dict:
    p = provider()
    if p == "openai":
        return _openai(system, user, schema, schema_name)
    if p == "anthropic":
        return _anthropic(system, user, schema)
    raise AIError("No AI key set. Put OPENAI_API_KEY (or ANTHROPIC_API_KEY) in the .env file.")


def _openai(system: str, user: str, schema: dict, schema_name: str) -> dict:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise AIError("OPENAI_API_KEY is not set")
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": os.environ.get("OPENAI_MODEL") or OPENAI_DEFAULT_MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema_name, "strict": True,
                                                "schema": schema}},
        },
        timeout=180,
    )
    if r.status_code >= 400:
        raise AIError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    choice = r.json()["choices"][0]
    message = choice["message"]
    if message.get("refusal"):
        raise AIError(f"OpenAI declined: {message['refusal']}")
    if choice.get("finish_reason") == "length":
        raise AIError("OpenAI response was cut off")
    return json.loads(message["content"])


def _anthropic(system: str, user: str, schema: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError(f"Claude connection error: {e}") from e
    if response.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    if response.stop_reason == "max_tokens":
        raise AIError("Claude response was cut off")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
