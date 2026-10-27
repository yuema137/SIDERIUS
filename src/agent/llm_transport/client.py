"""Lazy synchronous facade; optional packages are never imported on the old route."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.llm_transport.contracts import Completion, PydanticTransportConfig


class PydanticClient:
    """One direct request per call. SDK clients live and close on that request's loop."""

    def __init__(
        self,
        *,
        config: PydanticTransportConfig,
        provider: str,
        api_key: str,
        base_url: str,
        timeout: float,
        max_output_tokens: int | None,
    ) -> None:
        try:
            import pydantic_ai.direct  # noqa: F401
        except ImportError as exc:
            raise ImportError("Install siderius[pydantic-ai] to use this LLM transport") from exc
        self.config = config
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens

    def create(self, **kwargs: Any) -> Completion:
        from agent.llm_transport.runtime import request

        def run() -> Completion:
            return asyncio.run(request(self, kwargs))

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()
        # The public bridge is synchronous, including inside async node callers.
        # A separate loop avoids nested run_until_complete and cross-loop clients.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(run).result()
