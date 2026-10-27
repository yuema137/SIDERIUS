"""Capture raw accounting evidence before SDK normalization supplies defaults."""

import json
from contextlib import suppress
from typing import Any

import httpx2


class AccountingCapture:
    """A request-local receipt, including SDK-internal streaming fallbacks."""

    def __init__(self) -> None:
        self.raw: dict[str, Any] = {}

    def absorb(self, body: object) -> None:
        if not isinstance(body, dict):
            return
        if isinstance(body.get("model"), str):
            self.raw["model"] = body["model"]
        if isinstance(body.get("usage"), dict):
            self.raw.setdefault("usage", {}).update(body["usage"])

    async def __call__(self, response: httpx2.Response) -> None:
        if not response.is_success:
            return
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            await response.aread()
            # The model adapter owns malformed-response refusal.
            with suppress(ValueError):
                self.absorb(response.json())
        elif "text/event-stream" in content_type:
            # The bridge's API is one-shot. Keep SDK-internal streams readable
            # while retaining provider evidence rather than default zero usage.
            await response.aread()
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(event, dict):
                    self.absorb(event.get("message"))  # Anthropic message_start
                    self.absorb(event.get("response"))  # Responses completed
                    self.absorb(event)  # Anthropic cumulative message_delta
