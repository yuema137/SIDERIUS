"""Lazy synchronous facade; optional packages are never imported on the old route."""

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from agent.llm_transport.contracts import Completion, PydanticTransportConfig

if TYPE_CHECKING:
    from agent.llm_transport.background import BackgroundTicket


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

        return _run(lambda: request(self, kwargs))

    def submit_background(self, **kwargs: Any) -> "BackgroundTicket | Completion":
        """Create one background response; a pending response returns a ticket."""
        from agent.llm_transport.runtime import submit_background

        return _run(lambda: submit_background(self, kwargs))

    def await_background(self, ticket: "BackgroundTicket", expires_at: float) -> Completion:
        """Poll an accepted response until a terminal state or ``expires_at`` (monotonic)."""
        from agent.llm_transport.background import await_completion

        return _run(lambda: await_completion(ticket, expires_at))

    def cancel_background(self, ticket: "BackgroundTicket") -> str:
        """Best-effort cancel of an accepted response; returns the outcome."""
        from agent.llm_transport.background import cancel

        return _run(lambda: cancel(ticket))


def _run[T](coroutine: Callable[[], Coroutine[Any, Any, T]]) -> T:
    def run() -> T:
        return asyncio.run(coroutine())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()
    # The public bridge is synchronous, including inside async node callers.
    # A separate loop avoids nested run_until_complete and cross-loop clients.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()
