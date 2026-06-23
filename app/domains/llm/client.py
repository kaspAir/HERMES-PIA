"""Duenne Anbindung an die Anthropic Messages API (server-seitig, eigener Key).

Hinweis: Bevor echte Projektinhalte an die API gehen, gehoeren sie durch die
Pseudonymisierungsschicht. Fuer Demos mit synthetischen / handbereinigten Daten.
"""
import os

import requests

API_URL = "https://api.anthropic.com/v1/messages"


class LLMClient:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = (model
                      or os.environ.get("HERMESPIA_LLM_MODEL")
                      or os.environ.get("METHODOS_LLM_MODEL")
                      or "claude-sonnet-4-6")

    def complete(self, system, messages, max_tokens=1024):
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY fehlt (.env zu Hause setzen).")
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))
