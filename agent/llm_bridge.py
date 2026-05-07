# agent/llm_bridge.py
#
# Unified LLM transport layer for SIDERIUS.
#
# This module provides two layers of functionality:
#
# 1. GENERIC TRANSPORT (provider-agnostic, used by all nodes):
#    - generate(system_prompt, user_prompt) -> dict   (JSON mode)
#    - generate_text(system_prompt, user_prompt) -> str (plain text)
#    - tool_call(system_prompt, user_prompt, tools) -> ToolCallResult
#    - list_models() -> list of model IDs
#    All providers (OpenAI, Gemini, any OpenAI-compatible endpoint) are
#    accessed through a single openai.OpenAI client routed via base_url.
#    Nodes call these methods directly with their own prompts.
#
# 2. DOMAIN-SPECIFIC WRAPPERS (only used by the tuning agent):
#    - plan()    -> assembles a prompt from memory_history + expert_advice +
#                   config_manual using generators from agent.prompts, then
#                   calls generate().
#    - reflect() -> assembles a prompt from experiment results using generators
#                   from agent.prompts, then calls generate().
#    These are specific to ml_hyperparameter_tune_agent. The other 4 nodes
#    (interpretation, proposal, implementor, validator) bypass plan()/reflect()
#    entirely and call generate()/generate_text() with their own prompts.
#
# NOTE: plan() and reflect() are candidates for moving into the tuning agent
# itself, which would make LLMBridge a pure transport layer. See Open Question
# 1 in docs/refactor_llm_bridge.md.

import os
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict, Optional
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import ValidationError

from agent.prompts import (
    PLANNER_PROMPT,
    REFLECTOR_PROMPT,
    get_planner_user_prompt,
    get_reflector_user_prompt
)
from agent.schemas.telemetry import (
    LLMBridgeContextError,
    TokenCounts,
    TokenUsageChars,
    TokenUsageRow,
)


# Fallback markdown injected at the {SCORE_COMPARISON_TABLE} token when no
# per-file table is available. Italicised Markdown so the LLM reads them as
# meta-notes, not table rows. See docs/aggregated_score_table_awareness.md §9.
_PLANNER_SCORE_TABLE_FALLBACK = (
    "_(No prior round yet — this is round 1. A comparison table will appear "
    "once your first experiment completes.)_"
)
_REFLECTOR_SCORE_TABLE_FALLBACK = (
    "_(This experiment produced no score_table — either the scorer failed or "
    "file_vector/denoising_score was missing.)_"
)


# ---------------------------------------------------------------------------
# Tool-call result — flattens the OpenAI SDK's nested response structure
# so callers remain SDK-agnostic.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolCallResult:
    """
    Structured result from an LLM tool-call request.

    Attributes:
        name:      The tool (skill) name the LLM chose to invoke.
        arguments: Parsed dict of the arguments the LLM provided.
                   Ready to pass to ``input_schema.model_validate(arguments)``.
        call_id:   The tool_call ID from the API (needed if you want to send
                   a tool-result message back in a multi-turn conversation).
    """

    name: str
    arguments: Dict[str, Any]
    call_id: str

# ---------------------------------------------------------------------------
# Known providers — convenience defaults, not a restriction.
# Any OpenAI-compatible endpoint can be used via base_url/api_key overrides.
# ---------------------------------------------------------------------------
_KNOWN_PROVIDERS: Dict[str, Dict[str, Optional[str]]] = {
    "openai": {
        "base_url": None,           # SDK default
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.1-flash-lite-preview",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-pro",
    },
    # Claude via Bedrock/Vertex requires non-standard auth (AWS SigV4 / Google
    # OAuth).  Placeholder entry — wire up when a compatible endpoint is available.
    # "claude": {
    #     "base_url": "https://...",
    #     "api_key_env": "ANTHROPIC_API_KEY",
    #     "default_model": "claude-sonnet-4-20250514",
    # },
}


# ---------------------------------------------------------------------------
# Stub-mode model name synthesiser (Commit 4.4 Stage 2).
#
# Single source of truth for the cross-stub `model_name` slug. The
# StubLLMBridge derives proposer.proposing / implementor.code / tuner.planner
# model_name fields from this helper so all three label outputs agree on
# the slug — which becomes the plugin filename
# (`agent_generated/models/{model_name}.py`) and the training target.
#
# Format: ``stub_arch_{iter:03d}_{slot}``. Deterministic, collision-free
# across iters and slots, and lands within Python's identifier rules so
# `importlib` accepts it as a module name without escaping.
# ---------------------------------------------------------------------------
def _synth_stub_model_name(iter_idx: int, slot: str) -> str:
    """Return the canonical stub-mode plugin slug for ``(iter_idx, slot)``.

    Args:
        iter_idx: Iteration index (≥ 0). Zero-padded to 3 digits.
        slot:     Per-iter sub-id distinguishing models proposed within
                  the same iter (e.g. ``"a"``, ``"b"``).

    Returns:
        Slug of shape ``stub_arch_{iter:03d}_{slot}``.
    """
    return f"stub_arch_{iter_idx:03d}_{slot}"


class LLMBridge:
    """
    Universal API gateway for all LLM calls in SIDERIUS.

    **Architectural invariant**: this class is the ONLY place in the
    `agent/`, `nodes/`, and `workflows/` codebase that constructs an
    `OpenAI()` client. Every agent must route its LLM calls through an
    `LLMBridge` instance. This is enforced by
    ``tests/unit/agent/test_llm_bridge_singleton.py``, which fails if
    any other file under those directories instantiates ``OpenAI()``
    directly.

    Why this matters: the retry policy, timeouts, provider routing,
    planner/reflector model split, and any future cross-cutting
    concerns (rate limiting, observability, fallbacks) all live in
    one place. Bypassing the bridge silently opts an agent out of
    every one of those guarantees — and the bug usually only surfaces
    in production under load.

    If you genuinely need a one-off client (e.g. a test or a
    diagnostic script), put it under ``tests/`` or ``scripts/``,
    where the singleton check does not run.
    """

    def __init__(
        self,
        provider: str = "gemini",
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        reflect_provider: Optional[str] = None,
        reflect_model_id: Optional[str] = None,
        max_retries: Optional[int] = None,
    ):
        """
        Unified LLM bridge — every provider is accessed through ``openai.OpenAI``.

        For known providers (``"openai"``, ``"gemini"``), ``base_url`` and
        ``api_key`` are resolved automatically from environment variables.
        Any OpenAI-compatible endpoint can be used by passing ``base_url``
        and ``api_key`` explicitly.

        Args:
            provider: Provider label (used for logging / identification).
            model_id: Model identifier (e.g. ``"gpt-4o"``, ``"gemini-3-flash"``).
                      Falls back to the provider's default when ``None``.
            base_url: Override the API base URL.  Required for providers not in
                      the known-providers map.
            api_key:  Override the API key.  When ``None``, looked up from the
                      environment variable associated with the provider.
            reflect_provider:
                      Optional separate provider for the reflector method
                      (``reflect()``). When set, the bridge instantiates a
                      second OpenAI client pointed at this provider's
                      base_url and uses its API key. When unset (default),
                      ``reflect()`` uses the same provider/client as
                      ``generate()``. Designed to let the reflector use a
                      different vendor entirely (e.g. main planner on
                      gemini, reflector on openai).
            reflect_model_id:
                      Optional separate model ID for the reflector method
                      (``reflect()``). When set, ``reflect()`` uses this model
                      while ``plan()`` and other methods continue to use
                      ``model_id``. Designed to let cheaper/faster models
                      handle the templated reflection step while keeping the
                      main reasoning model for planning. When unset (default),
                      both planner and reflector use ``model_id``.

                      ``reflect_provider`` and ``reflect_model_id`` are
                      independent — you can set either or both, or neither.
                      Common patterns:
                        - Both unset: planner and reflector use the same
                          provider+model (legacy behavior).
                        - Only ``reflect_model_id`` set: same provider, two
                          different models (e.g. gemini-3.1-pro for planner,
                          gemini-2.5-flash for reflector).
                        - Both set: cross-provider routing (e.g. gemini for
                          planner, openai for reflector).
            max_retries:
                      Maximum number of retry attempts for transient API
                      errors (429, 5xx, connection, timeout). ``None``
                      (default) means retry indefinitely — the process
                      owner (Slurm wall time, Ctrl-C) is the natural
                      timeout. Set to a positive integer for interactive
                      use where infinite retry would be annoying (e.g. 6
                      for the legacy ~77s window, 20 for ~15 minutes).
                      Backoff doubles from 2.5s up to a 60s cap.
        """
        load_dotenv()
        self.provider = provider.lower()
        self.max_retries = max_retries

        known = _KNOWN_PROVIDERS.get(self.provider)

        # Resolve api_key: explicit arg > env var > None
        if api_key is None and known:
            api_key = os.getenv(known["api_key_env"])
        self.api_key = api_key

        # Resolve base_url: explicit arg > known default > None (SDK default)
        if base_url is None and known:
            base_url = known["base_url"]

        # Resolve model: explicit arg > known default (unknown providers must supply model_id)
        if model_id is None and known:
            model_id = known["default_model"]
        self.model_name = model_id
        # Reflect model defaults to the main model when unset, so existing
        # callers see no behavior change.
        self.reflect_model_name = reflect_model_id or self.model_name

        # Retry policy: SDK retries are disabled (max_retries=0) and
        # replaced with our own loop in _chat_json that uses a longer
        # backoff schedule (2.5s, 5s, 10s, 20s, 40s — total ~77s).
        # The default SDK schedule (capped at ~8s, ~25s total) gave up
        # too fast on the E9 SDSC iter 47950268 503 (Google "high
        # demand" / per-key QPM saturation under parallel runs).
        self.client = OpenAI(
            api_key=self.api_key,
            max_retries=0,
            timeout=120.0,
            **({"base_url": base_url} if base_url else {}),
        )

        # --- Reflect client setup (Phase A.2: cross-provider support) ---
        # When reflect_provider is None or matches the main provider, the
        # reflect client is the same object as the main client (no duplicate
        # connections, no extra resource cost). When it differs, we
        # instantiate a second OpenAI client with the reflect provider's
        # credentials.
        normalized_reflect_provider = (
            reflect_provider.lower() if reflect_provider else self.provider
        )
        self.reflect_provider = normalized_reflect_provider

        if normalized_reflect_provider == self.provider:
            # Same provider — reuse the main client. Saves a connection
            # and ensures both calls hit the same authenticated endpoint.
            self.reflect_client = self.client
        else:
            # Different provider — resolve its credentials from
            # _KNOWN_PROVIDERS and instantiate a second OpenAI client.
            reflect_known = _KNOWN_PROVIDERS.get(normalized_reflect_provider)
            if reflect_known is None:
                raise ValueError(
                    f"Unknown reflect_provider {normalized_reflect_provider!r}. "
                    f"Known providers: {list(_KNOWN_PROVIDERS.keys())}. "
                    f"For ad-hoc providers, instantiate the second client "
                    f"manually and assign it to LLMBridge.reflect_client "
                    f"after construction."
                )
            reflect_api_key = os.getenv(reflect_known["api_key_env"])
            reflect_base_url = reflect_known["base_url"]
            self.reflect_client = OpenAI(
                api_key=reflect_api_key,
                max_retries=0,
                timeout=120.0,
                base_url=reflect_base_url,
            )

        # --- Run-context state (Commit 1: scaffolding; Commit 2: setter) ---
        # The four primary fields stay None until set_run_context() is called
        # by the workflow runner (Commit 4). While None, _record_usage is a
        # silent no-op — the bridge captures response.usage but does not write
        # a row anywhere. This lets unit tests that patch the OpenAI client
        # run without touching disk, and ensures that production runs which
        # never get a setter call do not start writing half-formed rows.
        self._token_usage_path: Optional[Path] = None
        self._iter: Optional[int] = None
        self._run_id: Optional[str] = None
        self._run_name: Optional[str] = None

        # --- Setter Safety Protocol state (Commit 2) ---
        # _lock serializes set_run_context with _record_usage so that the
        # state-check / iter-flush write / state-update sequence is atomic.
        # Any code path that mutates run-context state OR appends a row must
        # be inside `with self._lock:`. Helpers suffixed `_locked` assume the
        # caller already holds the lock. This is a plain Lock (not RLock) —
        # we never re-enter from inside a locked block.
        self._lock = threading.Lock()
        # Set when set_run_context() is called; copied into rows' extra if
        # callers ask for it. Plain ISO-8601 string for cheap diffing.
        self._set_at_ts: Optional[str] = None
        # Lazy cache of the file's first-row run_id (read once on first write).
        # If the file does not exist or is empty when we first try to write,
        # this is set to our own run_id (we own the file from row 0).
        self._first_row_run_id_cache: Optional[str] = None
        # Tracks the highest iter value successfully appended (rows + markers).
        # Used to detect backwards-iter leaks per §1.4.1.
        self._last_logged_iter: Optional[int] = None
        # Tracks the most recent ts string written; used for the soft
        # monotonic-timestamp warning (clock-skew detection — not a raise).
        self._last_ts: Optional[str] = None

    # ------------------------------------------------------------------
    # Setter Safety Protocol (§1.4.1 / §1.4.2 of the design doc)
    # ------------------------------------------------------------------
    # set_run_context is the *only* way to bind run-context state on the
    # bridge. It is called by the workflow runner once per iter (Commit 4
    # wires it). The body is wrapped in self._lock so that the
    # state-check / iter-flush / state-update sequence is atomic with
    # respect to concurrent _record_usage callers — without the lock,
    # an in-flight _record_usage could write a row using stale iter
    # *after* a flush marker was emitted, leaking into a flushed iter.
    #
    # Two invariants are enforced loudly (LLMBridgeContextError):
    #   - run_id immutability: once set, the bridge refuses any setter
    #     call with a different run_id. This is the strongest guard
    #     against pointing a bridge instance at another run's log.
    #   - forward-only iter: same-iter re-entry is allowed (stage retries
    #     within the same iter), but going backwards is rejected.
    #
    # On legitimate iter advancement (new_iter > current self._iter),
    # _flush_iter_marker_locked appends one synthetic row with
    # label='_iter_flush' for the *previous* iter, then state is updated.
    # ------------------------------------------------------------------
    def set_run_context(self, *, workspace: Path, iter: int,
                        run_name: str, run_id: str) -> None:
        """Bind run-context state used by ``_record_usage``.

        Args:
            workspace:  Directory that owns ``token_usage.jsonl``. The file
                        path is ``workspace / "token_usage.jsonl"``. Must be
                        an existing, writable directory; checked once here.
            iter:       Iteration index for subsequent calls. Must be
                        non-negative; must be ``>=`` any prior value bound
                        on this bridge.
            run_name:   Human-readable run name (e.g. ``"explore_v12_0504"``).
            run_id:     Immutable run identifier (format
                        ``{run_name}-{utc_ts}-{pid}``). Once bound on this
                        bridge, calling the setter with a different
                        ``run_id`` raises :class:`LLMBridgeContextError`.

        Raises:
            LLMBridgeContextError: on run_id mutation or backwards iter.
            OSError: if ``workspace`` does not exist or is not writable.
            ValueError: if ``iter`` is negative.
        """
        if iter < 0:
            raise ValueError(f"iter must be non-negative, got {iter}")
        workspace = Path(workspace)

        with self._lock:
            # --- run_id immutability check (§1.4.1 row 1) ---
            if self._run_id is not None and run_id != self._run_id:
                raise LLMBridgeContextError(
                    f"run_id mutation forbidden: bridge bound to "
                    f"{self._run_id!r}, refused new {run_id!r}. "
                    f"A new run_id requires a fresh LLMBridge instance."
                )
            # --- forward-only iter check (§1.4.1 row 3 of contract) ---
            if self._iter is not None and iter < self._iter:
                raise LLMBridgeContextError(
                    f"backwards iter rejected: bridge at iter={self._iter}, "
                    f"refused setter call with iter={iter}. "
                    f"Same-iter re-entry is allowed; backwards is not."
                )
            # --- workspace writability check (loud OSError per §1.4.1) ---
            if not workspace.exists():
                raise OSError(
                    f"workspace does not exist: {workspace}. "
                    f"Refusing to bind token-usage path to a missing dir."
                )
            if not os.access(workspace, os.W_OK):
                raise OSError(
                    f"workspace not writable: {workspace}. "
                    f"Cannot append token_usage.jsonl."
                )
            # --- legitimate iter advancement: flush prior iter first ---
            #
            # Strict-greater-than per the user's concurrency directive
            # ("State-Change Guard: ensure that _iter_flush only fires if
            # the new iter is strictly greater than the current self._iter,
            # to prevent redundant flush markers if multiple components
            # call the setter for the same iteration").
            if self._iter is not None and iter > self._iter:
                self._flush_iter_marker_locked(prev_iter=self._iter)

            # --- update state (last step inside the lock) ---
            self._token_usage_path = workspace / "token_usage.jsonl"
            self._iter = iter
            self._run_name = run_name
            self._run_id = run_id
            self._set_at_ts = (
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )

    def _flush_iter_marker_locked(self, *, prev_iter: int) -> None:
        """Append one synthetic row marking the close of ``prev_iter``.

        Caller must hold ``self._lock``. The marker uses
        ``label='_iter_flush'``, zeroed token/char counts, and
        ``extra={'marker': 'iter_end'}`` per §1.4.1 of the design doc.

        Pre-write checks (run_id, path, ts) are run via
        ``_validate_pre_write_locked`` so a marker write that would
        corrupt the log fails the same way a normal row would.
        """
        # Defensive: if the path is unset (shouldn't happen — set_run_context
        # only calls this on iter advancement, and iter advancement implies
        # a prior bind), silently no-op.
        if self._token_usage_path is None:
            return
        ts = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        # Run pre-write invariant checks (loud on violation).
        self._validate_pre_write_locked(target_iter=prev_iter, ts=ts)
        try:
            row = TokenUsageRow(
                ts=ts,
                run_id=self._run_id or "unbound",
                run_name=self._run_name or "unbound",
                iter=prev_iter,
                label="_iter_flush",
                model=None,
                provider=None,
                tokens=TokenCounts(),
                chars=TokenUsageChars(system=0, user=0, total=0),
                components={},
                extra={"marker": "iter_end"},
            )
        except ValidationError as ve:
            print(
                f"[LLMBridge._flush_iter_marker] schema validation failed "
                f"for iter={prev_iter}: {ve}",
                file=sys.stderr, flush=True,
            )
            return
        # Append (line-buffered). Transient OSError swallowed; structural
        # writability was already verified by _validate_pre_write_locked.
        try:
            with open(self._token_usage_path, "a", buffering=1) as f:
                f.write(row.model_dump_json() + "\n")
                f.flush()  # Per concurrency directive: explicit flush in lock
        except OSError as oe:
            print(
                f"[LLMBridge._flush_iter_marker] append failed for "
                f"{self._token_usage_path}: {oe}",
                file=sys.stderr, flush=True,
            )
            return
        # Track that this iter has been flushed (for monotonic check).
        self._last_logged_iter = prev_iter
        self._last_ts = ts

    # ------------------------------------------------------------------
    # Public marker emit (Commit 6.1 — Stability Filter audit support)
    # ------------------------------------------------------------------
    # Callers that deliberately *skip* a labelled LLM call (e.g. the
    # interpretation agent's Stability Filter, which reuses a cached
    # per_model entry instead of re-querying the LLM) emit a synthetic
    # row through this method so the skip is countable in
    # token_usage.jsonl. Without this, build_token_baseline_report.py
    # cannot quantify the savings — the skip would be invisible to the
    # audit. Mirrors _flush_iter_marker_locked's row shape (zeroed
    # tokens/chars, marker-style extra) but with caller-provided label
    # and extra. See docs/audit_and_optimize_token_usage_and_growth.md
    # Commit 6.1 (T4 wiring + audit-log test).
    # ------------------------------------------------------------------
    def emit_marker(self, *, label: str,
                    extra: Optional[Dict[str, Any]] = None) -> None:
        """Append a synthetic marker row without an LLM call.

        Args:
            label: Stable call-site identifier, e.g.
                ``"interpretation.per_model_skipped"``. Must be non-empty.
            extra: Free-form caller context, e.g.
                ``{"reason": "stable", "model_type": "punet"}``.

        Silent no-op when run context is unset (mirrors ``_record_usage``).
        Pre-write invariants (run_id, path, ts) are validated the same
        way as a real LLM row — a marker that would corrupt the log
        fails as loudly as a real row would.

        Raises:
            ValueError: empty ``label``.
            LLMBridgeContextError: pre-write invariant violation
                (run_id mutation, backwards iter). Propagates per §1.4.2.
        """
        if not label:
            raise ValueError("emit_marker requires a non-empty label")
        if self._token_usage_path is None:
            return  # context unset — silent no-op

        ts = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

        with self._lock:
            self._validate_pre_write_locked(target_iter=self._iter, ts=ts)
            try:
                row = TokenUsageRow(
                    ts=ts,
                    run_id=self._run_id or "unbound",
                    run_name=self._run_name or "unbound",
                    iter=self._iter,
                    label=label,
                    model=None,
                    provider=None,
                    tokens=TokenCounts(),
                    chars=TokenUsageChars(system=0, user=0, total=0),
                    components={},
                    extra=dict(extra) if extra else {},
                )
            except ValidationError as ve:
                print(
                    f"[LLMBridge.emit_marker] schema validation failed "
                    f"for label={label!r}: {ve}",
                    file=sys.stderr, flush=True,
                )
                return
            try:
                with open(self._token_usage_path, "a", buffering=1) as f:
                    f.write(row.model_dump_json() + "\n")
                    f.flush()
            except OSError as oe:
                print(
                    f"[LLMBridge.emit_marker] append failed for "
                    f"{self._token_usage_path}: {oe}",
                    file=sys.stderr, flush=True,
                )
                return
            # Track for monotonic checks (mirrors _flush_iter_marker_locked).
            if self._iter is not None and (
                self._last_logged_iter is None
                or self._iter > self._last_logged_iter
            ):
                self._last_logged_iter = self._iter
            self._last_ts = ts

    def _validate_pre_write_locked(self, *, target_iter: Optional[int],
                                   ts: str) -> None:
        """Run the four §1.4.1 pre-write invariant checks. Caller holds lock.

        Raises:
            LLMBridgeContextError: on run_id or backwards-iter violation
                (rows 1-2 of the §1.4.1 table).
            OSError: on path corruption (row 3). Logs a stderr warning on
                non-monotonic ts (row 4) but does *not* raise — clock skew
                is real but rare and shouldn't tank a run.
        """
        # --- Row 3: path writable ---
        path = self._token_usage_path
        if path is None:
            # Caller bug: pre-write should never run with unset path.
            raise OSError("_validate_pre_write_locked called with no path")
        parent = path.parent
        if not parent.exists():
            raise OSError(
                f"token_usage.jsonl parent dir vanished: {parent}"
            )
        if not os.access(parent, os.W_OK):
            raise OSError(
                f"token_usage.jsonl parent dir no longer writable: {parent}"
            )

        # --- Row 1: first-row run_id matches (lazy, cached) ---
        if self._first_row_run_id_cache is None:
            if path.exists() and path.stat().st_size > 0:
                with open(path, "r") as f:
                    first_line = f.readline().strip()
                if first_line:
                    try:
                        first_row = json.loads(first_line)
                    except json.JSONDecodeError:
                        raise LLMBridgeContextError(
                            f"first line of {path} is not valid JSON; "
                            f"audit log already corrupted, refusing to write."
                        )
                    file_run_id = first_row.get("run_id")
                    if file_run_id != self._run_id:
                        raise LLMBridgeContextError(
                            f"run_id mismatch: file owner={file_run_id!r}, "
                            f"bridge={self._run_id!r}. Audit-log integrity "
                            f"violation — refusing write to {path}."
                        )
                    self._first_row_run_id_cache = file_run_id
                else:
                    # File exists but empty — we own it.
                    self._first_row_run_id_cache = self._run_id
            else:
                # File missing — we will create it; we own row 0.
                self._first_row_run_id_cache = self._run_id
        else:
            # Cache hit — verify the bridge's run_id hasn't drifted.
            if self._first_row_run_id_cache != self._run_id:
                raise LLMBridgeContextError(
                    f"run_id mismatch (cached): file owner="
                    f"{self._first_row_run_id_cache!r}, "
                    f"bridge={self._run_id!r}."
                )

        # --- Row 2: iter not less than last logged ---
        if (target_iter is not None and self._last_logged_iter is not None
                and target_iter < self._last_logged_iter):
            raise LLMBridgeContextError(
                f"backwards iter leak: trying to write iter={target_iter} "
                f"but last logged iter={self._last_logged_iter}. "
                f"Audit log would be non-monotonic — aborting."
            )

        # --- Row 4: ts monotonic (warn-only) ---
        if self._last_ts is not None and ts < self._last_ts:
            print(
                f"[LLMBridge] WARNING: non-monotonic timestamp "
                f"({ts} < last {self._last_ts}). Clock skew? Row still written.",
                file=sys.stderr, flush=True,
            )

    def list_models(self) -> List[str]:
        """
        List model IDs available from the current provider.

        Calls the ``GET /models`` endpoint exposed by OpenAI-compatible APIs.
        Returns a sorted list of model ID strings.
        """
        response = self.client.models.list()
        return sorted(m.id for m in response)

    def plan(self,
             memory_history: List[Dict],
             expert_advice: str = "None",
             force_model: str = "auto",
             config_manual: Optional[Dict] = None,
             model_description: Optional[str] = None,
             exploration_checklist: str = "",
             plugin_source_excerpt: str = "",
             current_round: Optional[int] = None,
             max_rounds: Optional[int] = None,
             trial_allowed: bool = True,
             force_formal_round: bool = True,
             plan_overrides: Optional[Dict] = None,
             max_epochs: Optional[int] = None,
             # --- Phase K (K.6) — [ACTIVE RESOURCE BUDGETS] block inputs ---
             trial_vram_budget_gb: Optional[float] = None,
             formal_vram_budget_gb: Optional[float] = None,
             trial_time_budget_minutes: Optional[float] = None,
             formal_time_budget_minutes: Optional[float] = None,
             last_vram_estimate_gb: Optional[float] = None,
             last_time_estimate_minutes: Optional[float] = None,
             last_batch_size: Optional[int] = None,
             last_mode: Optional[str] = None,
             score_table_md: Optional[str] = None) -> Dict:
        """
        Uses the Planner logic to observe Research Memory and decide next steps.
        Incorporates physical constraints from config_manual and architecture
        knowledge from model_description to prevent hallucinations.

        Args:
            config_manual:    JSON schema of the model's config fields.
            model_description: Markdown description of the architecture and its physics.
            plugin_source_excerpt: Pre-formatted block (e.g. from
                              ``format_plugin_source_excerpt_block``) showing the
                              raw Pydantic config class source so the LLM can
                              see ``@model_validator`` / ``@field_validator``
                              bodies that ``config_manual`` (JSON schema) cannot
                              represent. Empty string disables the section.
                              Phase D.1 — see docs/improving_validation_awareness.md.
            current_round:    Current round number (1-based). Forwarded to prompt.
            max_rounds:       Total rounds in this run. Forwarded to prompt.
            trial_allowed:    Whether the LLM may choose trial mode. Forwarded to prompt.
            force_formal_round:
                              When True (default), the final round is presented
                              to the LLM as MANDATORY formal mode. When False,
                              the final round is presented as OPTIONAL formal
                              and the planner may pick trial mode (testing /
                              debugging only).
            plan_overrides:   Operator-frozen plan fields. When set, the prompt
                              renders a SYSTEM-FIXED PARAMETERS block so the LLM
                              knows which knobs it does not control.
            max_epochs:       Hard cap on epochs. Forwarded to the FIXED block.
            trial_vram_budget_gb,
            formal_vram_budget_gb,
            trial_time_budget_minutes,
            formal_time_budget_minutes:
                Operator-supplied per-mode resource budgets. Forwarded into the
                [ACTIVE RESOURCE BUDGETS] planner-prompt block (Phase K, §10.3
                / §10.11). None on any field renders "(no budget — gate
                disabled)" on that axis.
            last_vram_estimate_gb,
            last_time_estimate_minutes,
            last_batch_size,
            last_mode:
                Resource snapshot from the most recent prior attempt's record,
                surfaced into the same [ACTIVE RESOURCE BUDGETS] block so the
                LLM has a concrete number to react to. None means "no prior
                data" (round 1 before any pre-flight has run).
            score_table_md:
                Pre-rendered markdown from the best-so-far record's
                ``score_table.rendered_markdown``. Substituted into the
                ``{SCORE_COMPARISON_TABLE}`` placeholder in ``PLANNER_PROMPT``
                (see docs/aggregated_score_table_awareness.md §9.1). ``None``
                on iteration 1 (no prior records) renders the "no prior round
                yet" fallback.
        """
        system_prompt = PLANNER_PROMPT.replace(
            "{SCORE_COMPARISON_TABLE}",
            score_table_md or _PLANNER_SCORE_TABLE_FALLBACK,
        )

        # --- 2. Inject model description + config manual ---
        manual_context = ""
        if model_description:
            manual_context += f"\n\n[MODEL ARCHITECTURE DESCRIPTION]:\n{model_description}"
        if config_manual:
            manual_context += f"\n\n[STRICT PHYSICAL CONSTRAINTS / CONFIG MANUAL]:\n{json.dumps(config_manual, indent=2)}"

        # Pass the new arguments to the prompt generator
        user_prompt = get_planner_user_prompt(
            memory_history=memory_history,
            expert_advice=expert_advice,
            force_model=force_model,
            current_round=current_round,
            max_rounds=max_rounds,
            trial_allowed=trial_allowed,
            force_formal_round=force_formal_round,
            plan_overrides=plan_overrides,
            max_epochs=max_epochs,
            trial_vram_budget_gb=trial_vram_budget_gb,
            formal_vram_budget_gb=formal_vram_budget_gb,
            trial_time_budget_minutes=trial_time_budget_minutes,
            formal_time_budget_minutes=formal_time_budget_minutes,
            last_vram_estimate_gb=last_vram_estimate_gb,
            last_time_estimate_minutes=last_time_estimate_minutes,
            last_batch_size=last_batch_size,
            last_mode=last_mode,
        )

        # Assemble final prompt: user prompt + plugin source + checklist + description + manual.
        # ``plugin_source_excerpt`` is rendered before the exploration checklist so the
        # raw ``@model_validator`` bodies are adjacent to the field-by-field tried-value
        # list — the planner reasons about both at the same moment.
        final_user_prompt = user_prompt
        if plugin_source_excerpt:
            final_user_prompt += f"\n\n{plugin_source_excerpt}"
        if exploration_checklist:
            final_user_prompt += f"\n\n{exploration_checklist}"
        final_user_prompt += manual_context

        print(f"    [PROMPT_SIZE] planner: {len(final_user_prompt)} chars")
        # Internal call site: label is fixed (§1.5), wired in Commit 1 so
        # the V12 baseline run is meaningfully labeled and chain_log is
        # clean of "unlabeled" warnings from inside the bridge itself.
        return self.generate(system_prompt, final_user_prompt,
                             label="tuner.planner")

    def reflect(self, exp_id: str, hypothesis: str, actual_results: Dict,
                reflection_context: Optional[Dict] = None) -> Dict:
        """
        Uses the Reflector logic to transform results into new Memory entries.
        reflection_context provides baseline/best score comparisons so the
        reflector can judge results correctly.

        Routes through ``self.reflect_client`` and ``self.reflect_model_name``,
        both of which default to the main client/model when ``reflect_provider``
        and ``reflect_model_id`` were not passed to ``__init__``. When set
        independently, the reflector can use a different provider AND/OR a
        different model than the planner — it is a templated structured-
        extraction task, not a reasoning task, and does not need a frontier
        model.

        The ``{SCORE_COMPARISON_TABLE}`` token in ``REFLECTOR_PROMPT`` is
        substituted with ``reflection_context["score_comparison_table"]`` when
        present (threaded by the tuner per sub-commit B), otherwise a fallback
        notice. See docs/aggregated_score_table_awareness.md §9.4.
        """
        score_table_md = (
            reflection_context.get("score_comparison_table")
            if reflection_context else None
        )
        system_prompt = REFLECTOR_PROMPT.replace(
            "{SCORE_COMPARISON_TABLE}",
            score_table_md or _REFLECTOR_SCORE_TABLE_FALLBACK,
        )
        user_prompt = get_reflector_user_prompt(exp_id, hypothesis, actual_results, reflection_context)

        # Internal call site: label is fixed (§1.5). Provider is the
        # reflect provider (may differ from self.provider when cross-
        # provider routing is configured).
        return self._chat_json(self.reflect_client, self.reflect_model_name,
                               system_prompt, user_prompt,
                               label="tuner.reflector",
                               provider=self.reflect_provider)

    # Retry policy for ALL OpenAI API calls. SDK-level retry is disabled
    # (max_retries=0 in the client constructors), so this helper is the
    # single source of truth for how we handle transient API failures.
    #
    # Backoff: doubles from 2.5s up to a 60s cap, then stays at 60s.
    # Schedule: 2.5, 5, 10, 20, 40, 60, 60, 60, ...
    #
    # When max_retries is None (default): retry indefinitely — the process
    # owner (Slurm wall time, Ctrl-C) is the natural timeout. This is the
    # right default for batch jobs where burning a round on a transient 503
    # is far more expensive than waiting a few extra minutes.
    #
    # When max_retries is an integer: stop after that many total attempts
    # (e.g. max_retries=6 gives 1 initial + 5 retries, similar to the old
    # fixed schedule). Use this for interactive/lilab sessions.
    #
    # Catches 429 (rate limit), 5xx (server errors incl. Google 503 "high
    # demand"), and connection / timeout errors. Other 4xx errors (auth,
    # bad request, model not found) are raised immediately — they will
    # not heal on retry.
    _RETRY_INITIAL_WAIT = 2.5
    _RETRY_MAX_WAIT = 60.0

    # Content-level retry policy for _chat_json. Distinct from the HTTP-level
    # _call_with_retry budget above. Triggers when the API returns a successful
    # HTTP response whose body is empty, non-JSON, or decodes to a non-dict/list
    # — the failure mode observed with deepseek-v4-pro on long structured
    # prompts (HTTP 200 + empty content). Bounded so a genuinely malformed
    # contract still surfaces promptly.
    _CONTENT_RETRY_BUDGET = 3
    _CONTENT_RETRY_INITIAL_WAIT = 2.0
    _CONTENT_RETRY_MAX_WAIT = 16.0

    @staticmethod
    def _parse_retry_delay(exc) -> Optional[float]:
        """Extract retryDelay seconds from a Google API 429 error body, if present.

        Google embeds a RetryInfo detail with a delay string like "28890s".
        Returns None if the field is absent or unparseable.
        """
        try:
            details = exc.body.get("error", {}).get("details", [])
            for d in details:
                if d.get("@type", "").endswith("RetryInfo"):
                    delay_str = d.get("retryDelay", "")
                    if delay_str.endswith("s"):
                        return float(delay_str[:-1])
        except Exception:
            pass
        return None

    def _call_with_retry(self, fn, label: str = "api_call"):
        """Call an OpenAI API function with the bridge's retry policy."""
        from openai import APIStatusError, APIConnectionError, APITimeoutError
        last_exc = None
        attempt = 0
        wait = self._RETRY_INITIAL_WAIT
        while True:
            try:
                return fn()
            except (APIConnectionError, APITimeoutError) as e:
                last_exc = e
            except APIStatusError as e:
                if e.status_code != 429 and not (500 <= e.status_code < 600):
                    raise
                last_exc = e
                # Honor the API-suggested retry delay for hard quota errors
                # (e.g. daily RPD reset). Overrides the exponential backoff
                # for this attempt only; next attempt resumes normal schedule.
                if e.status_code == 429:
                    suggested = self._parse_retry_delay(e)
                    if suggested is not None:
                        wait = suggested
            attempt += 1
            # Check if we've exhausted our retry budget
            if self.max_retries is not None and attempt >= self.max_retries:
                print(f"[LLMBridge.{label}] All {attempt} "
                      f"attempts failed; raising.", flush=True)
                raise last_exc
            print(f"[LLMBridge.{label}] Attempt {attempt} failed "
                  f"({type(last_exc).__name__}: {last_exc}); "
                  f"retrying in {wait}s...", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, self._RETRY_MAX_WAIT)

    @staticmethod
    def _sanitize_json_text(text: str) -> str:
        """Best-effort cleanup of LLM-generated JSON text before parsing.

        Handles common LLM output quirks in a model-agnostic way:

        1. Markdown fence stripping — some models wrap the JSON in ```json...```
           despite being asked for raw JSON.
        2. Invalid escape sequences — JSON only permits \\", \\\\, \\/, \\b, \\f,
           \\n, \\r, \\t, \\uXXXX after a backslash. Any other \\X is illegal.
           LLMs sometimes escape characters that don't need escaping (e.g. \\`
           for backtick, \\' for apostrophe, \\( in math notation).

           We fix this iteratively using the JSON parser's own error position:
           each JSONDecodeError with "escape" in its message reports the exact
           character position of the offending \\X. We drop the backslash at
           pos-1 and keep the character at pos, then re-parse. Repeat until the
           JSON is valid or a non-escape error is encountered.

           This approach is model-agnostic — it doesn't assume which character
           follows the backslash, and handles multiple bad escapes in one pass.
        """
        import json as _json

        # 1. Strip markdown fences
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # 2. Fix invalid escape sequences using parser error-position feedback.
        # The JSON parser reports the backslash position inconsistently across
        # versions (sometimes e.pos is the backslash, sometimes the char after it).
        # We probe both positions bidirectionally, so this works regardless.
        _MAX_FIXES = 100  # guard against pathological input
        for _ in range(_MAX_FIXES):
            try:
                _json.loads(text)
                break  # valid JSON — stop
            except _json.JSONDecodeError as e:
                if "escape" not in e.msg.lower():
                    break  # different error class; let caller handle it
                pos = e.pos
                # Probe both pos-1 and pos for the offending backslash.
                if pos > 0 and text[pos - 1] == "\\":
                    idx = pos - 1  # backslash is before the reported position
                elif pos < len(text) and text[pos] == "\\":
                    idx = pos      # backslash is at the reported position
                else:
                    break  # no backslash found near the error site; give up
                text = text[:idx] + text[idx + 1:]  # drop the backslash

        return text

    # ------------------------------------------------------------------
    # Telemetry — per-LLM-call audit row (Phase 1, Commit 1)
    # ------------------------------------------------------------------
    # See docs/audit_and_optimize_token_usage_and_growth.md §1.2 / §1.7.
    # _record_usage is the single point where we serialize one
    # TokenUsageRow per API call. The row schema lives in
    # agent/schemas/telemetry/token_usage.py.
    #
    # Behaviour summary:
    #   - Silent no-op when self._token_usage_path is None (context
    #     unset; Commit 2 wires set_run_context()).
    #   - Per-attempt: every successful API response produces one row,
    #     including content-retry attempts where the JSON later fails
    #     to parse (Q1 confirmed 2026-05-04). The caller passes
    #     extra={"attempt": N, "status": "ok"|"json_decode_error"|...}
    #     to make the retry-cost visible.
    #   - Graceful degradation when response.usage is missing: token
    #     counts written as None; char counts always populated.
    #
    # The row is appended in "a" mode with line buffering (buffering=1)
    # so concurrent bridge instances inside the same process do not
    # interleave partial lines. Cross-process safety is not yet
    # required — only the workflow runner writes here.
    # ------------------------------------------------------------------
    def _record_usage(self, *, response: Any, label: str,
                      system_prompt: str, user_prompt: str,
                      model_name: str, provider: str,
                      components: Optional[Dict[str, int]] = None,
                      extra: Optional[Dict[str, Any]] = None) -> None:
        """Append one ``TokenUsageRow`` to ``{workspace}/token_usage.jsonl``.

        Silent no-op when ``self._token_usage_path is None`` (run context
        unset). Telemetry must never abort a real run — any unexpected
        error in this helper is logged to stderr and swallowed, *except*
        for ``LLMBridgeContextError`` which propagates per §1.4.2.

        Args:
            response:       The raw OpenAI SDK response object. ``response.usage``
                            is read if present; missing/None is fine.
            label:          Stable call-site identifier (see §1.5). Defaults
                            to ``"unlabeled"`` at the public-method level.
            system_prompt:  The system prompt as sent to the API.
            user_prompt:    The user prompt as sent to the API.
            model_name:     Provider model id used for this call.
            provider:       Provider name (``"openai"``, ``"gemini"``, etc.).
            components:     Pre-merge char-count breakdown of the user prompt,
                            produced by the proposer's
                            ``_audit_proposer_components`` hook (§1.3). ``None``
                            for non-proposer calls and the legacy 2-call path —
                            stored as an empty dict in that case.
            extra:          Free-form caller context, e.g.
                            ``{"attempt": 0, "status": "ok"}``.
        """
        if self._token_usage_path is None:
            # Context not set — silent no-op until set_run_context is called.
            return

        # --- Pull provider-reported token counts (graceful if missing) ---
        usage = getattr(response, "usage", None)
        if usage is None:
            tokens = TokenCounts()  # all None
        else:
            tokens = TokenCounts(
                prompt=getattr(usage, "prompt_tokens", None),
                completion=getattr(usage, "completion_tokens", None),
                total=getattr(usage, "total_tokens", None),
            )

        # --- Compute local char counts (always available) ---
        sys_chars = len(system_prompt) if system_prompt else 0
        usr_chars = len(user_prompt) if user_prompt else 0
        chars = TokenUsageChars(
            system=sys_chars,
            user=usr_chars,
            total=sys_chars + usr_chars,
        )

        # --- Close the component-coverage gap (§1.5 Phase 1.5 / Commit 4.2;
        #     audit-hook content key count grown by Commit 4.3.3) ---
        # The proposer's `_audit_proposer_components` hook reports N named
        # content payloads (currently 10 — see that hook's docstring; was 9
        # pre-Commit-4.3.3) but not the user-prompt template wrapper text
        # (section headers like "## Interpretation Summary", key-value preludes
        # like "Models analysed: [...]", stage-specific instructions) that
        # `_build_*_prompt` injects around them. Gate T1 (2026-05-04) measured
        # the wrapper gap at ~7.5–8.3 K chars per proposer call (~22 % of each
        # user prompt under the 9-key audit). To make the audit lossless, we
        # inject a catch-all key
        # `template_and_scaffolding = chars.total - sum(content components)`.
        # The formula is generic in N, so growing the hook's content-key set
        # (e.g. Commit 4.3.3 added `non_candidates_overview`) just shrinks the
        # catch-all without touching this code. Only applied to rows that carry
        # a non-empty components dict (i.e. proposer rows): keeps the
        # schema-empty default for non-proposer rows untouched. `max(0, ...)`
        # guards against a future audit-hook bug that overcounts; we'd rather
        # log zero than a negative.
        if components:
            content_sum = sum(components.values())
            components = {
                **components,
                "template_and_scaffolding": max(0, chars.total - content_sum),
            }

        ts = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

        # --- Lock-protected validate + append + state update.
        # The §1.4.1 pre-write checks must observe the same run-context
        # that the row is built from, and the state-update (last_logged_iter
        # / last_ts) must follow the append without interleaving with a
        # concurrent set_run_context call. The lock provides that guarantee.
        with self._lock:
            # Pre-write invariants (loud on violation; LLMBridgeContextError
            # propagates per §1.4.2 — never wrap this in try/except).
            self._validate_pre_write_locked(target_iter=self._iter, ts=ts)

            # Build + validate the row (schema errors are programming bugs;
            # log + skip rather than abort the run).
            try:
                row = TokenUsageRow(
                    ts=ts,
                    run_id=self._run_id or "unbound",
                    run_name=self._run_name or "unbound",
                    iter=self._iter,
                    label=label,
                    model=model_name,
                    provider=provider,
                    tokens=tokens,
                    chars=chars,
                    components=components or {},
                    extra=extra or {},
                )
            except ValidationError as ve:
                print(
                    f"[LLMBridge._record_usage] schema validation failed for "
                    f"label={label!r}: {ve}",
                    file=sys.stderr, flush=True,
                )
                return

            # Append + explicit flush (per concurrency directive).
            # Transient OSError on append (e.g. ENOSPC mid-write) is
            # logged + swallowed — structural writability was verified
            # in _validate_pre_write_locked above, so any error here is
            # a transient I/O issue and shouldn't tank the run.
            try:
                with open(self._token_usage_path, "a", buffering=1) as f:
                    f.write(row.model_dump_json() + "\n")
                    f.flush()
            except OSError as oe:
                print(
                    f"[LLMBridge._record_usage] append failed for "
                    f"{self._token_usage_path}: {oe}",
                    file=sys.stderr, flush=True,
                )
                return

            # Update tracking state (success path only).
            if self._iter is not None:
                self._last_logged_iter = self._iter
            self._last_ts = ts

    def _chat_json(self, client: OpenAI, model_name: str,
                   system_prompt: str, user_prompt: str,
                   *, label: str = "unlabeled",
                   provider: Optional[str] = None,
                   components: Optional[Dict[str, int]] = None) -> Dict:
        """
        Internal helper: send a system+user prompt through a specific client
        to a specific model, and return the parsed JSON response.

        Used by ``generate()`` (which always uses ``self.client`` and
        ``self.model_name``) and by ``reflect()`` (which uses
        ``self.reflect_client`` and ``self.reflect_model_name`` so callers
        can route the reflector to a cheaper/faster/different-quota model on
        the same OR a different provider than the main planner).

        The client and model are passed as explicit arguments so the helper
        is fully decoupled from any per-method state — easy to mock and easy
        to extend with future per-method routing.
        """
        # Content-level retry loop. HTTP-level transients (429/5xx/connection/
        # timeout) are handled inside _call_with_retry. This outer loop handles
        # the orthogonal failure mode where the API returns HTTP 200 but the
        # body is empty / non-JSON / wrong top-level type — observed with
        # deepseek-v4-pro on long structured prompts. Bounded so genuinely
        # malformed contracts surface promptly.
        #
        # Per-attempt telemetry (Phase 1, Commit 1): every attempt that
        # successfully returns from _call_with_retry produces one row in
        # token_usage.jsonl, regardless of whether the JSON parses. The row
        # carries extra={"attempt": N, "status": "ok"|"json_decode_error"|
        # "empty_content"|"wrong_type"} so content-retry cost is visible.
        # Provider defaults to self.provider for the main client, falls back
        # to self.reflect_provider when the reflect client is in use.
        if provider is None:
            provider = (
                self.reflect_provider if client is self.reflect_client
                else self.provider
            )
        last_text = ""
        last_err_label = ""
        wait = self._CONTENT_RETRY_INITIAL_WAIT
        for attempt in range(self._CONTENT_RETRY_BUDGET + 1):
            response = self._call_with_retry(
                lambda: client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                ),
                label="_chat_json",
            )
            raw = response.choices[0].message.content or ""
            text = self._sanitize_json_text(raw.strip())
            last_text = text

            # Determine attempt status before recording so each row carries
            # an honest status field. Decode is repeated below in the
            # success branch — the first decode here is consulted only for
            # status classification; the second is the source of truth for
            # the returned object.
            decoded = None
            end_idx = None
            attempt_status: str
            if not text:
                attempt_status = "empty_content"
                last_err_label = "empty_content"
            else:
                try:
                    decoded, end_idx = json.JSONDecoder().raw_decode(text)
                except json.JSONDecodeError as e:
                    attempt_status = "json_decode_error"
                    last_err_label = f"json_decode_error: {e.msg}"
                    decoded = None
                else:
                    if not isinstance(decoded, (dict, list)):
                        attempt_status = "wrong_type"
                        last_err_label = (
                            f"wrong_type: decoded to {type(decoded).__name__}"
                        )
                        decoded = None
                    else:
                        attempt_status = "ok"

            # Record one row per attempt, including content-retry failures.
            # No-op when run context is unset (Commit 2 wires the setter).
            self._record_usage(
                response=response,
                label=label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_name=model_name,
                provider=provider,
                components=components,
                extra={"attempt": attempt, "status": attempt_status},
            )

            if attempt_status == "ok":
                trailing = text[end_idx:].strip()
                if trailing:
                    print(
                        f"[LLMBridge._chat_json] Discarded {len(trailing)} chars of "
                        f"trailing data after valid JSON (model={model_name}).",
                        flush=True,
                    )
                return decoded

            # Content-level failure — retry if budget remains.
            if attempt < self._CONTENT_RETRY_BUDGET:
                print(
                    f"[LLMBridge._chat_json] Content-level retry "
                    f"{attempt + 1}/{self._CONTENT_RETRY_BUDGET} (model={model_name}, "
                    f"err={last_err_label}, body_preview={last_text[:80]!r}); "
                    f"sleeping {wait}s.",
                    flush=True,
                )
                time.sleep(wait)
                wait = min(wait * 2, self._CONTENT_RETRY_MAX_WAIT)

        # Budget exhausted — raise the same ValueError shape callers expect.
        print(
            f"[LLMBridge._chat_json] Failed to parse JSON from model={model_name} "
            f"after {self._CONTENT_RETRY_BUDGET + 1} attempts (last_err={last_err_label}): "
            f"{last_text[:200]}",
            flush=True,
        )
        raise ValueError(
            f"Model response was not valid JSON after "
            f"{self._CONTENT_RETRY_BUDGET + 1} attempts. Return ONLY a raw JSON object. "
            f"Last response started with: {last_text[:200]}"
        )

    # Sentinel used by the public-method `label` kwargs. Calls that pass
    # the default "unlabeled" emit a one-line warning to stderr so a
    # missed label site is visible without aborting the run. Production
    # call sites are labeled in Commit 3 (proposer, interp, validator);
    # internal sites (plan / reflect) are labeled in this commit.
    _DEFAULT_LABEL = "unlabeled"

    def _warn_default_label(self, method_name: str) -> None:
        """Print a one-line stderr warning when label= falls to the default."""
        print(
            f"[LLMBridge.{method_name}] WARNING: called without label= kwarg "
            f"(label fell back to {self._DEFAULT_LABEL!r}). Pass an explicit "
            f"label per docs/audit_and_optimize_token_usage_and_growth.md §1.5.",
            file=sys.stderr, flush=True,
        )

    def generate(self, system_prompt: str, user_prompt: str,
                 *, label: str = _DEFAULT_LABEL,
                 components: Optional[Dict[str, int]] = None) -> Dict:
        """
        Call the main LLM (``self.client`` + ``self.model_name``) with a
        system prompt and a user prompt, return a JSON dict.

        Uses ``response_format={"type": "json_object"}`` via the unified
        OpenAI-compatible ``chat.completions.create`` endpoint for all providers.

        Args:
            system_prompt: System role content.
            user_prompt:   User role content.
            label:         Stable call-site identifier (see §1.5). Defaults
                           to ``"unlabeled"`` to keep legacy callers working;
                           a one-line warning is emitted to stderr until
                           every site is labeled (Commit 3).
            components:    Pre-merge char-count breakdown for proposer call
                           sites (see §1.3 / ``_audit_proposer_components``).
                           ``None`` for non-proposer calls — stored as an
                           empty dict on the row.
        """
        if label == self._DEFAULT_LABEL:
            self._warn_default_label("generate")
        return self._chat_json(self.client, self.model_name,
                               system_prompt, user_prompt,
                               label=label, provider=self.provider,
                               components=components)

    def generate_text(self, system_prompt: str, user_prompt: str,
                      *, label: str = _DEFAULT_LABEL,
                      components: Optional[Dict[str, int]] = None) -> str:
        """
        Call the LLM with a system prompt and user prompt, return plain text.

        Used for free-form reasoning steps where JSON mode would constrain
        output quality. ``label`` is captured into the per-call telemetry row.
        ``components`` carries the optional pre-merge char-count breakdown
        from ``_audit_proposer_components`` (proposer text-mode stages only).
        """
        if label == self._DEFAULT_LABEL:
            self._warn_default_label("generate_text")
        response = self._call_with_retry(
            lambda: self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            label="generate_text",
        )
        # Telemetry: one row per successful API response. Plain-text mode
        # has no content-retry, so attempt is always 0 and status "ok".
        self._record_usage(
            response=response,
            label=label,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_name=self.model_name,
            provider=self.provider,
            components=components,
            extra={"attempt": 0, "status": "ok"},
        )
        return response.choices[0].message.content.strip()

    def tool_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
        *,
        label: str = _DEFAULT_LABEL,
        components: Optional[Dict[str, int]] = None,
    ) -> ToolCallResult:
        """
        Ask the LLM to select a tool and provide arguments.

        Uses the OpenAI ``tools`` parameter so the model is structurally
        constrained to emit a valid tool call — no free-form JSON parsing.

        Args:
            system_prompt: System-level instruction for the LLM.
            user_prompt:   The user message describing the goal or context.
            tools:         List of OpenAI-format tool definitions.  Typically
                           built via ``SkillSpec.to_openai_tool()``.
            label:         Stable call-site identifier (see §1.5).

        Returns:
            A ``ToolCallResult`` with the chosen tool name, parsed arguments
            dict, and the API's call ID.

        Raises:
            ValueError: If the model response does not contain a tool call
                        (e.g. the model replied with plain text instead).
        """
        if label == self._DEFAULT_LABEL:
            self._warn_default_label("tool_call")
        response = self._call_with_retry(
            lambda: self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=tools,
                tool_choice="auto",
            ),
            label="tool_call",
        )

        message = response.choices[0].message

        # Telemetry: record the row regardless of whether a tool_call came
        # back. The API charged for the tokens either way; the response
        # shape is the caller's contract concern.
        tool_status = "ok" if message.tool_calls else "no_tool_call"
        self._record_usage(
            response=response,
            label=label,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_name=self.model_name,
            provider=self.provider,
            components=components,
            extra={"attempt": 0, "status": tool_status},
        )

        if not message.tool_calls:
            raise ValueError(
                f"[LLMBridge.tool_call] Model did not return a tool call. "
                f"Response: {message.content!r}"
            )

        tc = message.tool_calls[0]
        return ToolCallResult(
            name=tc.function.name,
            arguments=json.loads(tc.function.arguments),
            call_id=tc.id,
        )


# ---------------------------------------------------------------------------
# StubLLMBridge — stateless generative stub (Commit 4.4 Stage 2 / PR-B B2)
#
# Drop-in LLMBridge replacement for 0-cost chain smokes. Returns deterministic,
# schema-valid synthetic responses for every production label without any
# HTTP call. Selected via Stage 3 CLI flags (`--is_pseudo_llm`); dormant in
# production until then.
#
# Design contract (see docs/audit_and_optimize_token_usage_and_growth.md
# §8 Commit 4.4):
#   * Inherits `set_run_context`, `emit_marker`, `_validate_pre_write_locked`,
#     and the run-context state machine — the test harness watches
#     `token_usage.jsonl` flush + skip markers exactly as for the real bridge.
#   * Overrides `_record_usage` to a no-op so synthetic calls never pollute
#     production telemetry with zero-token rows (defensive — synthesise paths
#     do not call `_record_usage` either, but the override is the contract).
#   * Skips `OpenAI()` construction in `__init__` so the stub works with no
#     API key and no network.
#   * Overrides `_chat_json` (catches `generate` + `reflect` JSON paths),
#     `generate_text`, and `tool_call`.
#   * Each label dispatches through `_SYNTH_HANDLERS_JSON` /
#     `_SYNTH_HANDLERS_TEXT`. Unknown labels raise `NotImplementedError`
#     instead of silently returning something — drift is loud.
#
# B2a covers 5 labels (tuner.{planner,reflector} +
# interpretation.{per_model, synthesis, dedup}); B2b adds the remaining 8
# (proposer + implementor + validator).
# ---------------------------------------------------------------------------
class StubLLMBridge(LLMBridge):
    """Generative stub LLMBridge for 0-cost chain smokes.

    Returns deterministic, schema-valid synthetic responses for every label
    without HTTP calls. Selected by the Stage 3 chain-runner factory when
    ``--is_pseudo_llm`` is passed; dormant otherwise.

    Public surface mirrors :class:`LLMBridge` so downstream nodes do not
    need to know which bridge is wired:
      * ``set_run_context`` / ``emit_marker`` are inherited as-is (the
        run-context state machine and skip-marker emission are shared
        behaviour the smoke harness depends on).
      * ``generate`` / ``plan`` / ``reflect`` are inherited; they call into
        ``_chat_json`` which is overridden.
      * ``generate_text`` / ``tool_call`` / ``_chat_json`` are overridden.
      * ``_record_usage`` is overridden to a no-op so synthetic calls never
        write zero-token rows to ``token_usage.jsonl``.

    Cross-stub coupling: ``_synth_stub_model_name(iter, slot)`` is the
    single source of truth for the plugin slug — ``tuner.planner`` (here)
    and ``proposer.proposing`` / ``implementor.code`` (B2b) all derive
    their model_name from it so the chain's training step finds the same
    plugin file.
    """

    # --- Dispatch tables (label -> method-name) --------------------------
    # Keyed by string method names rather than method objects so the dict
    # can sit in the class body without forward-referencing each method.
    _SYNTH_HANDLERS_JSON: Dict[str, str] = {
        "tuner.planner":              "_synth_tuner_planner",
        "tuner.reflector":            "_synth_tuner_reflector",
        "interpretation.per_model":   "_synth_interpretation_per_model",
        "interpretation.synthesis":   "_synth_interpretation_synthesis",
        "interpretation.dedup":       "_synth_interpretation_dedup",
        # B2b: proposer.legacy_commit / proposer.causal_reasoning /
        #      proposer.proposing / implementor.code / implementor.repair /
        #      validator.code_review
    }
    _SYNTH_HANDLERS_TEXT: Dict[str, str] = {
        # B2b: proposer.legacy_reasoning / implementor.reasoning
    }

    def __init__(self, *, max_retries: Optional[int] = 0):
        """Initialise stub bridge state without any OpenAI client.

        Deliberately does NOT call ``super().__init__()``: the parent
        constructor instantiates ``OpenAI()`` clients which need an API
        key and (for the gemini default) hit the network during list_models
        probes. The stub bridge has neither; it sets only the state that
        the inherited ``set_run_context`` / ``emit_marker`` /
        ``_validate_pre_write_locked`` paths require.

        Args:
            max_retries: Honoured for API-shape parity only — no HTTP calls
                         are made, so the value is unused. Defaults to ``0``
                         (clearer than ``None`` for "no retries needed").
        """
        load_dotenv()
        self.provider: str = "stub"
        self.model_name: Optional[str] = "stub_model"
        self.api_key: Optional[str] = None
        self.max_retries: Optional[int] = max_retries

        # Reflect-side mirror — same provider/model so cross-provider
        # routing is a no-op in stub mode.
        self.reflect_provider: str = "stub"
        self.reflect_model_name: Optional[str] = "stub_model"

        # No OpenAI clients. Both attributes exist so any inherited code
        # that grabs `self.client` / `self.reflect_client` fails fast
        # (NoneType attribute access) instead of silently masking a bug.
        self.client = None
        self.reflect_client = None

        # --- Run-context state (mirrors LLMBridge.__init__) ---
        self._token_usage_path: Optional[Path] = None
        self._iter: Optional[int] = None
        self._run_id: Optional[str] = None
        self._run_name: Optional[str] = None

        # --- Setter Safety Protocol state (mirrors LLMBridge.__init__) ---
        self._lock = threading.Lock()
        self._set_at_ts: Optional[str] = None
        self._first_row_run_id_cache: Optional[str] = None
        self._last_logged_iter: Optional[int] = None
        self._last_ts: Optional[str] = None

    # ------------------------------------------------------------------
    # Telemetry: synthetic calls never write per-call rows.
    # ------------------------------------------------------------------
    def _record_usage(self, **_kwargs) -> None:
        """No-op: synthetic responses must not appear in token_usage.jsonl.

        The synth paths below never call ``_record_usage`` directly, so
        this override is defence-in-depth — it guarantees that any future
        code path on ``StubLLMBridge`` (or any inherited helper that
        reaches the writer) cannot leak zero-token rows into a real run's
        audit log. ``emit_marker`` is intentionally left inherited so the
        Stability-Filter-skipped markers continue to flow.
        """
        return

    # ------------------------------------------------------------------
    # Dispatch helpers — one per response type.
    # ------------------------------------------------------------------
    def _synthesise_json(self, label: str) -> Dict:
        """Return a JSON-mode synthetic response for ``label``."""
        handler_name = self._SYNTH_HANDLERS_JSON.get(label)
        if handler_name is None:
            raise NotImplementedError(
                f"StubLLMBridge: no JSON synthesiser registered for "
                f"label={label!r}. Known JSON labels: "
                f"{sorted(self._SYNTH_HANDLERS_JSON)}."
            )
        return getattr(self, handler_name)()

    def _synthesise_text(self, label: str) -> str:
        """Return a text-mode synthetic response for ``label``."""
        handler_name = self._SYNTH_HANDLERS_TEXT.get(label)
        if handler_name is None:
            raise NotImplementedError(
                f"StubLLMBridge: no text synthesiser registered for "
                f"label={label!r}. Known text labels: "
                f"{sorted(self._SYNTH_HANDLERS_TEXT)}."
            )
        return getattr(self, handler_name)()

    # ------------------------------------------------------------------
    # Entry-point overrides.
    # ------------------------------------------------------------------
    def _chat_json(self, client: Any, model_name: str,
                   system_prompt: str, user_prompt: str,
                   *, label: str = LLMBridge._DEFAULT_LABEL,
                   provider: Optional[str] = None,
                   components: Optional[Dict[str, int]] = None) -> Dict:
        """Bypass HTTP; dispatch to the JSON synthesiser registered for ``label``.

        Catches every JSON-mode call: ``generate`` (inherited, calls
        ``self._chat_json``), ``plan`` (inherited, calls ``self.generate``),
        and ``reflect`` (inherited, calls ``self._chat_json`` directly with
        the reflect client/model). The ``client`` / ``model_name`` /
        ``provider`` / ``components`` args are accepted for signature
        parity but ignored — synthesis is purely label-driven.
        """
        if label == self._DEFAULT_LABEL:
            self._warn_default_label("_chat_json")
        return self._synthesise_json(label)

    def generate_text(self, system_prompt: str, user_prompt: str,
                      *, label: str = LLMBridge._DEFAULT_LABEL,
                      components: Optional[Dict[str, int]] = None) -> str:
        """Bypass HTTP; dispatch to the text synthesiser registered for ``label``."""
        if label == self._DEFAULT_LABEL:
            self._warn_default_label("generate_text")
        return self._synthesise_text(label)

    def tool_call(self, system_prompt: str, user_prompt: str,
                  tools: List[Dict[str, Any]],
                  *, label: str = LLMBridge._DEFAULT_LABEL,
                  components: Optional[Dict[str, int]] = None) -> ToolCallResult:
        """Loud refusal — no production label currently routes through ``tool_call``.

        ``validator.code_review`` was suspected to use ``tool_call`` but
        actually calls ``generate`` (verified at
        ``nodes/ml_code_validator_agent.py:544``). If a future label adds
        a tool-call site, register it on a new ``_SYNTH_HANDLERS_TOOL``
        dispatch table rather than silently returning a sentinel.
        """
        raise NotImplementedError(
            f"StubLLMBridge.tool_call() has no synthesiser for label={label!r}. "
            f"No production label routes through tool_call() today. If a new "
            f"site is added, extend StubLLMBridge with a tool-call dispatch "
            f"table; do not silently return a sentinel ToolCallResult."
        )

    # ==================================================================
    # B2a synthesisers: tuner (2) + interpretation (3)
    # ==================================================================

    def _synth_tuner_planner(self) -> Dict:
        """Return an ``ExperimentPlan``-validatable dict with stub hyperparameters.

        Uses ``_synth_stub_model_name(iter, "a")`` for ``model_type`` so the
        slug matches what proposer.proposing / implementor.code will return
        in B2b — the chain's training step then finds
        ``agent_generated/models/{slug}.py`` where the implementor wrote it.

        Keys use the LLM-facing aliases (``model_config`` / ``train_config`` /
        ``loss_config``) — Pydantic's ``populate_by_name=True`` accepts both
        these and the Python field names (``model_cfg`` etc.).
        """
        iter_idx = self._iter if self._iter is not None else 0
        return {
            "model_type":             _synth_stub_model_name(iter_idx, "a"),
            "hypothesis":             "Stub planner: no-op verdict; the "
                                      "chain proceeds with default trial mode.",
            "reasoning":              "Stub mode — no real planning; "
                                      "minimal viable hyperparameters returned.",
            "model_config":           {},
            "train_config":           {"epochs": 1, "batch_size": 1, "lr": 1e-3},
            "loss_config":            {"loss_type": "ce"},
            "is_trial":               True,
            "trial_strategy":         "snapshot",
            "trial_portion":          0.02,
            "target_files":           [],
            "train_portion":          0.1,
            "eval_strategy":          "snapshot",
            "eval_portion":           0.02,
            "train_validation_align": True,
        }

    def _synth_tuner_reflector(self) -> Dict:
        """Return the four reflector keys consumed by the tuner agent.

        See ``nodes/ml_hyperparameter_tune_agent.py`` ``reflection.get(...)``
        callsites and ``agent/prompts.py`` REFLECTOR_PROMPT output schema.
        """
        return {
            "conclusion":    "Stub reflector: neutral verdict — chain continues.",
            "key_factor":    "(none — stub mode)",
            "discovery":     "(none — stub mode)",
            "memory_update": "Continue with default plan; stub mode in effect.",
        }

    def _synth_interpretation_per_model(self) -> Dict:
        """Return all 8 fields specified by ``PER_MODEL_SYSTEM_PROMPT``.

        Every key is required so the Knowledge Accumulator's downstream
        merge/compress paths (``model_knowledge_cache``,
        ``compress_model_summary``) find non-empty values. See
        ``nodes/result_interpretation_agent.py`` PER_MODEL_SYSTEM_PROMPT
        for the full contract.
        """
        return {
            "key_findings":         ["Stub: no real findings."],
            "bottlenecks":          ["Stub: no real bottlenecks."],
            "best_config_analysis": "Stub: no analysis performed.",
            "score_trend":          "Stub: no trend computed.",
            "per_file_analysis":    "Stub: no per-file analysis.",
            "data_sensitivity":     "Stub: no data-sensitivity analysis.",
            "efficiency_assessment":"Stub: no efficiency analysis.",
            "strategy_assessment":  "Stub: no strategy analysis.",
        }

    def _synth_interpretation_synthesis(self) -> Dict:
        """Return all 5 fields specified by ``SYNTHESIS_SYSTEM_PROMPT``.

        The synthesis callsite reads only ``key_findings`` / ``bottlenecks`` /
        ``take_home_message``, but the prompt asks for 5 fields; we provide
        the full set so a future consumer that reads the extra two fields
        finds non-empty values.
        """
        return {
            "key_findings":          ["Stub: no real cross-model findings."],
            "bottlenecks":           ["Stub: no real cross-model bottlenecks."],
            "per_file_comparison":   "Stub: no per-file comparison.",
            "efficiency_comparison": "Stub: no efficiency comparison.",
            "take_home_message":     "Stub mode — no real synthesis performed.",
        }

    def _synth_interpretation_dedup(self) -> Dict:
        """Return ``is_duplicate=False`` so the dedup pass keeps every term.

        See ``DEDUP_SYSTEM_PROMPT`` and the callsite at
        ``nodes/result_interpretation_agent.py:1311`` which reads
        ``is_duplicate`` / ``duplicate_of`` / ``rationale``.
        """
        return {
            "is_duplicate": False,
            "duplicate_of": None,
            "rationale":    "Stub: not a duplicate (default verdict).",
        }
