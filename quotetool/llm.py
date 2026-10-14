"""One place to talk to a language model, so the backend can be swapped with one setting.

Backends:
- "ollama": a local model on your own laptop (free; no data leaves the machine).
  Install from https://ollama.com, then run `ollama pull qwen2.5:7b`.
- "openai": any OpenAI-compatible API (Google Gemini, Groq, a university endpoint, LM Studio, ...).
  Set base_url, model and the API key environment variable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests


@dataclass
class LLMConfig:
    backend: str = "ollama"
    model: str = "qwen2.5:7b"
    base_url: str = "http://localhost:11434"
    api_key_env: str = "LLM_API_KEY"  # name of the environment variable holding the key (openai backend)
    temperature: float = 0.0
    timeout: int = 300

    @property
    def name(self) -> str:
        return f"{self.backend}:{self.model}"


class LLMUnavailable(RuntimeError):
    pass


def check(config: LLMConfig) -> tuple[bool, str]:
    """Is the model reachable? Returns (ok, human-readable message)."""
    try:
        if config.backend == "ollama":
            r = requests.get(f"{config.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if config.model not in models and f"{config.model}:latest" not in models:
                return False, f"Ollama is running, but model '{config.model}' is not pulled. Run: ollama pull {config.model}"
            return True, f"Ollama is running with {config.model}"
        if config.backend == "openai":
            if not os.environ.get(config.api_key_env):
                return False, f"Set the environment variable {config.api_key_env} to your API key"
            return True, f"Using {config.model} at {config.base_url}"
        return False, f"Unknown backend '{config.backend}'"
    except requests.RequestException as e:
        return False, f"Cannot reach {config.base_url} ({type(e).__name__}). Is Ollama running? Start it with: ollama serve"


def complete(config: LLMConfig, system: str, user: str, json_schema: dict | None = None) -> str:
    """Send one system + user message, return the model's text reply (JSON text when a schema is given)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        if config.backend == "ollama":
            payload = {
                "model": config.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": config.temperature},
            }
            if json_schema is not None:
                payload["format"] = json_schema  # Ollama constrains the output to this schema
            r = requests.post(f"{config.base_url}/api/chat", json=payload, timeout=config.timeout)
            r.raise_for_status()
            return r.json()["message"]["content"]

        if config.backend == "openai":
            payload = {"model": config.model, "messages": messages, "temperature": config.temperature}
            if json_schema is not None:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {os.environ.get(config.api_key_env, '')}"}
            r = requests.post(f"{config.base_url.rstrip('/')}/chat/completions", json=payload,
                              headers=headers, timeout=config.timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except requests.ConnectionError as e:
        raise LLMUnavailable(f"cannot reach {config.base_url}; is the model server running?") from e
    except requests.RequestException as e:
        raise LLMUnavailable(f"{config.name} failed: {e}") from e
    raise LLMUnavailable(f"Unknown backend '{config.backend}'")
