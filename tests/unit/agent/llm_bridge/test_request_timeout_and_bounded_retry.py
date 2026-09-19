"""Request timeout policy and the bounded timeout-retry budget.

A real Gate-2 run on 2026-08-17 stalled here: the implementor's
code-generation call against a reasoning model exceeded the bridge's
hardcoded 120 s client timeout TEN consecutive times, the chain never reached
training, and every attempt was billed. An independent probe to the same model
returned in 1.3 s, so the API was healthy — our own client was hanging up, and
then retrying forever.

Two policies, one defect each:

* the per-request timeout was 120 s, one fifth of the OpenAI SDK's own 600 s
  default, with no recorded justification;
* timeouts shared the unbounded `max_retries` budget, so a request that
  legitimately needs longer than the timeout loops forever without progress.

The unbounded budget for 429 is DELIBERATE and must survive: a quota
exhaustion heals when the operator tops up the balance, and a long batch run
resuming by itself is the intended behaviour.
"""

from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from agent.llm_bridge import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_RETRIES,
    LLMBridge,
)


def _bridge(**kw) -> LLMBridge:
    return LLMBridge(provider="openai", model_id="gpt-5.5", api_key="test-key", **kw)


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(request=httpx.Request("POST", "https://example.invalid/v1"))


def _status_error(code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://example.invalid/v1")
    return APIStatusError("boom", response=httpx.Response(code, request=request), body=None)


class TestTheRequestTimeoutIsNotBelowTheVendorDefault:
    def test_the_default_matches_the_sdk_default(self):
        """600 s is not an invented number — it is what the installed SDK
        itself uses. Asserted against the SDK so the two cannot drift apart
        silently, which is how the 120 s value survived unexamined."""
        from openai._constants import DEFAULT_TIMEOUT

        assert DEFAULT_REQUEST_TIMEOUT_SECONDS == DEFAULT_TIMEOUT.read
        assert DEFAULT_REQUEST_TIMEOUT_SECONDS == 600.0

    def test_every_client_the_bridge_builds_uses_it(self):
        """The Gate stalled because ONE hardcoded literal governed all three
        client constructions. A default that some clients ignore is not a
        policy."""
        bridge = _bridge()
        assert bridge.client.timeout == DEFAULT_REQUEST_TIMEOUT_SECONDS
        assert bridge.reflect_client.timeout == DEFAULT_REQUEST_TIMEOUT_SECONDS

    def test_a_caller_can_override_it(self):
        bridge = _bridge(request_timeout=90.0)
        assert bridge.request_timeout == 90.0
        assert bridge.client.timeout == 90.0


class TestTimeoutRetriesAreBounded:
    def test_a_persistent_timeout_raises_instead_of_looping_forever(self, monkeypatch):
        """THE regression. With the old policy this call never returned:
        timeout, back off, timeout, back off, forever, billing each attempt.
        `max_retries=None` (the production default) must NOT make timeouts
        unbounded."""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        bridge = _bridge()
        calls = {"n": 0}

        def always_times_out():
            calls["n"] += 1
            raise _timeout_error()

        with pytest.raises(APITimeoutError):
            bridge._call_with_retry(always_times_out, label="test")
        assert calls["n"] == DEFAULT_TIMEOUT_RETRIES

    def test_the_budget_is_configurable(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda _s: None)
        bridge = _bridge(timeout_retries=2)
        calls = {"n": 0}

        def always_times_out():
            calls["n"] += 1
            raise _timeout_error()

        with pytest.raises(APITimeoutError):
            bridge._call_with_retry(always_times_out, label="test")
        assert calls["n"] == 2

    def test_a_timeout_that_recovers_still_succeeds(self, monkeypatch):
        """Bounded must not mean brittle: a single transient timeout inside
        the budget still resolves normally."""
        monkeypatch.setattr("time.sleep", lambda _s: None)
        bridge = _bridge()
        calls = {"n": 0}

        def times_out_once():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _timeout_error()
            return "ok"

        assert bridge._call_with_retry(times_out_once, label="test") == "ok"
        assert calls["n"] == 2


class TestQuotaRetryStaysUnbounded:
    def test_a_429_does_not_consume_the_timeout_budget(self, monkeypatch):
        """The DELIBERATE behaviour that must survive this change: a quota
        exhaustion heals when the operator tops up the balance, so the chain
        keeps waiting. If 429 shared the bounded timeout budget it would give
        up after 3 attempts and lose the run.
        """
        monkeypatch.setattr("time.sleep", lambda _s: None)
        bridge = _bridge()
        calls = {"n": 0}

        def rate_limited_then_ok():
            calls["n"] += 1
            # More attempts than the timeout budget would ever allow.
            if calls["n"] <= DEFAULT_TIMEOUT_RETRIES + 5:
                raise _status_error(429)
            return "recovered"

        assert bridge._call_with_retry(rate_limited_then_ok, label="test") == "recovered"
        assert calls["n"] == DEFAULT_TIMEOUT_RETRIES + 6

    def test_a_non_retryable_status_still_raises_immediately(self):
        """Auth / bad-request errors do not heal on retry and must not be
        swallowed into either budget."""
        bridge = _bridge()

        def unauthorized():
            raise _status_error(401)

        with pytest.raises(APIStatusError):
            bridge._call_with_retry(unauthorized, label="test")


def test_scoped_deadline_bounds_otherwise_unlimited_rate_limit_retry(monkeypatch):
    """A DA allocation must not wait indefinitely on429 despite unbounded campaign retries."""
    from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline

    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: 0.0)
    bridge = _bridge(max_retries=None)
    calls = []

    def limited():
        calls.append(True)
        raise _status_error(429)

    with execution_deadline(1), pytest.raises(ExecutionDeadlineExceeded, match="retry wait"):
        bridge._call_with_retry(limited, label="test")
    assert len(calls) == 1
