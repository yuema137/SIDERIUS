"""Per-LLM-call audit row schema.

One ``TokenUsageRow`` is appended to ``{workspace}/token_usage.jsonl`` for every
LLM call routed through ``LLMBridge``. The schema is the contract for the audit
log; downstream tools (`tools/build_token_baseline_report.py`,
`tools/compute_frr.py`, `tools/compute_drr.py`) read this exact shape.

See ``docs/audit_and_optimize_token_usage_and_growth.md`` §1.7 for the design
rationale and §1.4.2 for the ``LLMBridgeContextError`` fail-fast contract.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMBridgeContextError(RuntimeError):
    """Audit-log integrity violation. Process must abort.

    Raised by ``LLMBridge`` when the run-context invariants documented in
    §1.4.1 of the design doc are violated:

    - ``run_id`` mismatch between setter calls or against an existing log file's
      first-row ``run_id``.
    - Backwards iteration advancement on the setter.
    - Audit-log path corruption (unwritable / missing parent).

    Catching this exception inside the bridge or its callers is forbidden — the
    only legitimate handlers are (a) the top-level workflow runner, which
    re-raises after writing a SystemExit-class shutdown record, and (b) tests
    that explicitly assert raise behavior. A static AST check
    (``tests/unit/agent/llm_bridge/test_no_silent_swallow.py``) enforces this.

    The runner translates this exception into ``sys.exit(2)``, distinct from
    the ``exit(1)`` used by the consecutive-failure brake so a downstream
    classifier can distinguish telemetry corruption from training-loop failure.
    """


class TokenCounts(BaseModel):
    """Token counts as reported by the provider's ``response.usage`` object.

    All three fields are ``Optional[int]`` because (a) some providers do not
    return ``usage`` on stream responses, and (b) we degrade gracefully — a
    missing ``usage`` produces a row with ``None`` token counts rather than no
    row at all. The ``chars`` cross-check on ``TokenUsageRow`` lets us still
    compare component sizes when token counts are missing.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: int | None = Field(
        default=None,
        description="Input/prompt tokens reported by the provider. None when "
        "the provider did not return a usage object.",
    )
    completion: int | None = Field(
        default=None,
        description="Output/completion tokens. None when usage was missing.",
    )
    total: int | None = Field(
        default=None,
        description="Total tokens (prompt + completion). May be redundant with "
        "the sum of the two above; preserved as the provider "
        "reports it because some providers count differently for "
        "system / cache / reasoning tokens.",
    )


class TokenUsageChars(BaseModel):
    """Char-level cross-check, computed locally by the bridge.

    These are the raw lengths of the system + user prompts as the bridge sent
    them. Always populated (no provider dependency). When ``TokenCounts`` are
    None, char counts are the only signal we have; when both are present they
    let downstream reports detect tokenizer-vs-byte drift.
    """

    model_config = ConfigDict(extra="forbid")

    system: int = Field(
        ge=0,
        description="len(system_prompt) at call time.",
    )
    user: int = Field(
        ge=0,
        description="len(user_prompt) at call time.",
    )
    total: int = Field(
        ge=0,
        description="system + user. Stored explicitly so downstream "
        "reports don't have to recompute it per row.",
    )


class TokenUsageRow(BaseModel):
    """One row in ``{workspace}/token_usage.jsonl``.

    The bridge appends one of these per LLM call. Iter-flush markers also use
    this schema (with ``label='_iter_flush'`` and zeroed counts) — this keeps
    the log a homogeneous JSONL stream for the linter and report tooling.
    """

    model_config = ConfigDict(extra="forbid")

    ts: str = Field(
        description="UTC ISO-8601 timestamp at call completion, e.g. '2026-05-04T15:32:11.443Z'.",
    )
    run_id: str = Field(
        description="Immutable identifier of the chain run that owns this log "
        "file. Format: '{run_name}-{utc_ts}-{pid}'. The bridge "
        "refuses to write to a file whose first-row run_id differs "
        "from its own — see LLMBridgeContextError.",
    )
    run_name: str = Field(
        description="Human-readable run name (e.g. 'exploit_cnn_v12_0504'). "
        "Duplicated from run_id for convenience in greppy ad-hoc "
        "log queries.",
    )
    iter: int | None = Field(
        default=None,
        description="Iteration index this call belongs to. None only for "
        "out-of-iter setup / teardown rows; marker rows always "
        "have an iter value.",
    )
    label: str = Field(
        description="Stable call-site identifier, e.g. 'proposer.causal_reasoning', "
        "'tuner.planner', 'interpretation.synthesis'. The reserved "
        "label '_iter_flush' marks an iteration boundary; the "
        "reserved label 'unlabeled' indicates a caller forgot to "
        "pass label= and emits a warning.",
    )
    model: str | None = Field(
        default=None,
        description="Provider model id used for the call (e.g. 'gpt-4o-mini'). "
        "Optional only for marker rows.",
    )
    served_model: str | None = Field(
        default=None,
        description="The model the PROVIDER REPORTED SERVING, read from the "
        "response (`response.model`). Distinct from `model` above, which is "
        "the model id the caller CONFIGURED.\n\n"
        "The distinction is the whole point of this field (D-LLM-1 / 66b). "
        "`model` is the configured value echoed back, so it reads the same "
        "whether the provider honoured the request or served something "
        "else — a provenance field that records what you ASKED FOR rather "
        "than what you GOT cannot discriminate those cases, and therefore "
        "can never fail. This one is an OBSERVATION, in the same sense the "
        "config sha256 is: it comes from the response, so it moves when "
        "what was served moves.\n\n"
        "`None` when the provider returned no model field, and on marker "
        "rows. Deliberately NOT validated against `model` — whether a "
        "mismatch should refuse is a separate decision, and recording is "
        "the prerequisite for making it.",
    )
    provider: str | None = Field(
        default=None,
        description="Provider name (e.g. 'openai', 'deepseek', 'gemini'). "
        "Optional only for marker rows.",
    )
    tokens: TokenCounts = Field(
        default_factory=TokenCounts,
        description="Provider-reported token counts. Defaults to all-None when "
        "the provider did not return a usage object.",
    )
    chars: TokenUsageChars = Field(
        description="Local char-level counts. Always populated.",
    )
    components: dict[str, int] = Field(
        default_factory=dict,
        description="Optional pre-merge component breakdown of the prompt. "
        "Populated by the proposer's _audit_proposer_components hook "
        "(see §1.3); empty for non-proposer calls and marker rows. "
        "Nine content keys (system_prompt, candidates_markdown, "
        "interpretation_json, previous_failures, vocab_block, "
        "expert_context_block, agent_cards_block, prior_stage_outputs, "
        "recent_gate_block) plus a 10th catch-all key "
        "`template_and_scaffolding` injected by LLMBridge._record_usage "
        "(§1.5 / Commit 4.2) holding `chars.total - sum(other 9)` so "
        "every char is accounted for. Values are char counts; the "
        "10th key is non-negative by construction.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form caller-supplied context (stage_idx, attempt, "
        "marker='iter_end', etc.). Kept loose so callers can add "
        "context without a schema migration.",
    )
