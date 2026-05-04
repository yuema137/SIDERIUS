# Audit & Optimize Token Usage and Growth

**Status**: Design draft, revision 3 (2026-05-04). G0 (architecture) approved; this revision adds the §8 Commit Ledger and hybrid DRR in preparation for execution.
**Author**: drafted 2026-05-04, revised 2026-05-04 (rev 2 — safety/forensic/retention gates), revised 2026-05-04 (rev 3 — commit ledger + hybrid DRR + fail-fast formalization).
**Inputs**:

- `reports/v11_20250503_token_usage.md` §12 (Proposer Internal Workflow & Feedback Logic) — the audit that motivates this doc.
- Verified file:line citations against `agent/llm_bridge.py`, `nodes/ml_model_proposal_agent.py`, `agent/schemas/proposal.py`, `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`.
- V11 forensic workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v11_0503/` (used as the offline benchmark target in §2.8).

### Revision 2 changelog

- §1.4 expanded: Setter Safety Protocol — RunID + iter validation on every `_record_usage` call; explicit Context Flush at iter boundaries.
- New §1.9: mandatory **Top-3 Bloat Report** after the first 5 iterations of the Phase 1 baseline run. If the bloat is not in the proposer, Phase 2 pivots — surgery follows the data, not the §12 prior.
- New §2.8: **Offline Forensic Benchmark** — `ErrorSignatureSkill` must extract the V11 `spectral_u_operator_lite` failure (VRAM spike location + the specific FFT/U-Net layer) before any Phase 2 code lands.
- New §2.9: **The Trap Test** — long-term wisdom retention. A fatal flaw planted in iter-2 ledger must still be cited at iter 10, proving the sliding window does not throw away load-bearing context.
- §4 expanded: three new quantitative metrics — Failure Re-occurrence Rate (FRR), Delta Realization Rate (DRR), Dehydration Compression Ratio (Cr).
- §5 implementation steps re-numbered to insert the new gate steps (offline forensic test runs *before* step 11 lands; Top-3 Bloat Report runs *between* phases).

### Revision 3 changelog

- §1.4.1 expanded: **Run-ID Fail-Fast Logic** formalized. `LLMBridgeContextError` is a `SystemExit`-class failure — the whole process aborts; no silent fallback path is permitted on RunID mismatch.
- §4.2 metric #8 (DRR) restructured into **Hybrid DRR**: split into `DRR_LLM` (semantic, LLM-judge) and `DRR_Structural` (AST/regex match against the source-code diff). Both must pass; their *gap* is itself a published metric — a large gap indicates "Reasoning Hallucination."
- New §8: **Step-by-Step Commit & Validation Ledger**. The 24 implementation steps in §5 are grouped into **12 atomic commits** (Phase 1: commits 1–5; Phase 2: commits 6–12). Each commit carries a `[ ]` task list, a Pre-Commit Verification block (positive test + quantitative metric + negative test), and a Definition of Done. §5 step numbers carry an annotation `(Commit N)` so the two sections are synchronized — "Execute Commit #N" maps deterministically to the §5 substeps.
- §6 expanded with the Structural-vs-Semantic DRR question.

---

## 0. Problem Statement

V11 production runs exhibit linear growth in proposer prompt size across iterations. The §12 audit identified the root causes:

1. **Telemetry blindspot** — `agent/llm_bridge.py` discards `response.usage` (prompt_tokens / completion_tokens). The only token signal we have is the `[PROMPT_SIZE] N chars` debug print. We are estimating, not measuring.
2. **Unbounded JSON region** — `interpretation['per_model_score_tables']` is dumped verbatim into the JSON region of every stage's user prompt (`_render_stage_user_prompt`, `ml_model_proposal_agent.py:444`). Markdown is bounded by `select_candidate_models(top_n=5)`; JSON is not.
3. **Repeated boilerplate** — at iter 4, ~41% of the proposer prompt is static scaffolding repeated verbatim every iter (vocabulary, hardware context, instructions, forward contract).
4. **Shallow feedback** — `previous_failures` is a flat list of `[PHYSICAL REJECTION]` strings (`ml_model_proposal_agent.py:644-646`). No causal pattern is extracted across iters; no reflection step compares attempt N-1 to attempt N.
5. **No sliding window for code** — full source is implicitly carried for every prior attempt via the candidate markdown blocks, regardless of how relevant N-k is to the current decision.

Goal: replace the current "digital hoarding" with a **Structured Evolutionary Ledger** — bounded, dehydrated, and explicitly delta-aware — while gaining first-class telemetry to verify the fix.

The work splits into two strictly ordered phases. Phase 1 ("the Scale") must land first; we cannot claim Phase 2 ("the Blade") was successful without Phase 1's measurements.

---

## 1. Phase 1 — Real-Time Audit & Telemetry ("the Scale")

### 1.1 Goals

| # | Outcome | Verifies |
|---|---------|----------|
| 1.1 | Every LLM call writes a structured `token_usage.jsonl` row to the workspace, with real `prompt_tokens` / `completion_tokens` from the API response. | We stop estimating. |
| 1.2 | Every proposer call writes a per-component breakdown (system / vocabulary / interpretation_json / prior_results / previous_failures / prior_stage_outputs) to the same log. | We can answer "which component bloated" per iter. |
| 1.3 | `chain_log.txt` carries a one-line summary at each LLM call so a `tail -f` shows live spend. | Operators can spot a runaway component at iter 5, not iter 30. |

### 1.2 API Usage Capture — `agent/llm_bridge.py`

**Current**: `_chat_json` (line 578), `generate_text` (line 682), and `tool_call` (line 701) all discard the API response after extracting `.choices[0].message.content`. The `response.usage` field is never inspected.

**Change**: introduce a thin wrapper helper:

```python
def _record_usage(self, *, response, label: str, system_prompt: str,
                  user_prompt: str, extra: Optional[dict] = None) -> None:
    """Append one row to {workspace}/token_usage.jsonl."""
```

It:

1. Pulls `response.usage.prompt_tokens`, `completion_tokens`, `total_tokens` (OpenAI-compatible — verified for the providers we use: openai, deepseek, gemini-via-openai-shim).
2. Records `len(system_prompt)` + `len(user_prompt)` as char counts (cheap cross-check).
3. Captures `model_name`, `label` (the call-site identifier — see §1.5), `timestamp`, `iter` (read from `LLMBridge.context_iter`, see §1.4), and any caller-supplied `extra` dict.
4. Appends to `{workspace}/token_usage.jsonl` (one JSON object per line, never rewritten).

**Hook sites**: every place `client.chat.completions.create(...)` is currently called inside the bridge — `_chat_json` (line 604) and `generate_text` (line 689) and `tool_call` body. Three call sites, one helper.

**Failure handling**: if `response.usage` is missing (older API shape, or stream mode), record `None` for token counts but still emit the char-level row. Never let telemetry failure abort a real run.

### 1.3 Component-Level Pre-Assembly Hook — `nodes/ml_model_proposal_agent.py`

**Current**: `_render_stage_user_prompt(accumulated)` (line 444) returns one merged string. The `accumulated` dict has known keys (`candidates`, `non_candidates_overview`, `interpretation_summary`, `existing_model_types`, `previous_failures`); on top of that the caller appends `agent_cards_block`, `expert_context_block`, `vocab_block` (lines 1001-1006). We have no granular size data.

**Change**: introduce `_audit_proposer_components(accumulated, agent_cards_block, expert_context_block, vocab_block, system_prompt) -> dict` called immediately before `self.bridge.generate(...)` at line 1014 / 1134. Returns a dict like:

```python
{
    "stage_name": "causal_reasoning",
    "iter": 4,
    "components": {
        "system_prompt":        len(system_prompt),
        "candidates_markdown":  len(markdown_block),
        "interpretation_json":  len(json.dumps(cleaned_interp)),
        "previous_failures":    sum(len(s) for s in inp.previous_failures),
        "vocab_block":          len(vocab_block) if vocab_block else 0,
        "expert_context_block": len(expert_context_block) if expert_context_block else 0,
        "agent_cards_block":    len(agent_cards_block) if agent_cards_block else 0,
        "prior_stage_outputs":  len(json.dumps(_extract_prior_stage_keys(accumulated))),
        "recent_gate_block":    len(_format_recent_gate_exhaustions_block(inp.recent_gate_exhaustions)),
    },
    "total_chars": <sum>,
}
```

The breakdown is passed into `LLMBridge._record_usage` as the `extra` argument so each row in `token_usage.jsonl` has both API-side counts (post-tokenization) and component-level char counts (pre-tokenization). The two together let us identify the bloating component **before** we have a tokenizer that reproduces OpenAI's exact split.

### 1.4 Workspace + iter context — minimal plumbing

`LLMBridge.__init__` does not currently know which workspace or which iteration the call is part of. Two options:

| Option | Sketch | Cost |
|--------|--------|------|
| **A. Pass `workspace` + `iter` into bridge constructor** | `WorkflowLLMConfig` already carries workspace; thread `iter` through `Workflow.run(iter=...)`. | Touches every node `run()` signature — invasive but explicit. |
| **B. Module-level setter on bridge** | `LLMBridge.set_run_context(workspace, iter, run_name, run_id)`; called once per iter at the top of the workflow. | One call site. Less invasive. State is per-instance, not global. |

**Recommendation: B.** The bridge is already an instance per node; one setter at iter boundaries is cleaner than threading kwargs everywhere. Setter writes to `self._token_usage_path`, `self._iter`, `self._run_id`. If unset, `_record_usage` falls back to a sentinel path (`/tmp/token_usage_unbound.jsonl`) and stamps `run_id="unbound"` so unit tests still work but production rows are immediately distinguishable.

#### 1.4.1 Setter Safety Protocol — Context Flush & Validate

Module-level state on a long-lived bridge instance is a known foot-gun: an iter-N call could silently log into iter-(N-1)'s row stream if the setter is not called, called late, or called with stale arguments. The protocol below makes leakage detectable and self-blocking rather than silent.

**Run-ID generation** (one per chain run, immutable for the run's lifetime):

```python
# At workflow startup, deterministic from (run_name, ts):
run_id = f"{run_name}-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
```

`run_id` is generated once at `run_exploration_adaptive.py` start and threaded as the *only* identity argument through the workflow. It is the immutable owner of the `token_usage.jsonl` file.

**Setter contract** (`LLMBridge.set_run_context`):

1. Records `(workspace, iter, run_name, run_id)` plus a `set_at_ts` timestamp.
2. **Refuses `run_id` mutation mid-stream**: if `self._run_id is not None and run_id != self._run_id`, raise `LLMBridgeContextError`. This is the one case where telemetry failure should be loud — a wrong run_id means we're about to corrupt another run's log.
3. Permits `iter` advancement only forward (`new_iter >= self._iter`); same-iter re-entry is allowed for stage retries; backward-iter is rejected with the same error.
4. On legitimate iter advancement, calls `_flush_iter_marker()` (see below) before the new iter takes effect.

**`_flush_iter_marker()`** (called at iter boundary):

Writes one synthetic row at iter end:

```json
{"ts": "...", "label": "_iter_flush", "iter": 4, "run_id": "...", "marker": "iter_end"}
```

This is the audit trail for "iter 4 telemetry stream is closed; iter 5 begins on the next row." Any `iter=4` row appearing *after* an `_iter_flush` for iter 4 is a leak and is detectable by a one-pass linter on the JSONL file (added as a unit test in §1.8).

**Per-row validation in `_record_usage`**:

Before each append, the helper asserts:

| Check | Failure mode | Action |
|-------|--------------|--------|
| `self._run_id` matches the file's first-row `run_id` | Wrong workspace target | Raise `LLMBridgeContextError`, never write. |
| `self._iter` is not less than the last logged iter | Backwards leak | Raise `LLMBridgeContextError`. |
| `self._token_usage_path` exists and is writable | Path corruption | Raise OSError; do not silently swallow. |
| `ts` is monotonically non-decreasing per (run_id, iter) | Clock skew or stale call | Log warning to stderr; still write the row (clock issues are real but rare). |

The first-row `run_id` check is the strongest guard: when the bridge is first asked to write, it reads the file's first line (if any) and verifies the `run_id` matches its own. A mismatch means we're pointing at an *earlier* run's log file — the bridge refuses to write rather than corrupt history.

**Workspace ownership**: only the workflow that owns `run_id` may write to `{workspace}/token_usage.jsonl`. A second concurrent workflow targeting the same workspace would fail the first-row check on its first write and abort — which is the correct behaviour, not a bug.

**Failure handling philosophy**: telemetry-internal corruption (stale iter, wrong run_id) is **loud** — these mean the audit log is unreliable and the operator must see it. Telemetry-data corruption (provider didn't return `usage`, clock skew) is **quiet** — log a warning, write what we have. The two failure classes have different operational responses.

#### 1.4.2 Run-ID Fail-Fast — formal contract

A Run-ID mismatch is **never** recoverable in-process. The bridge does not attempt to "fix" the context, retry, or fall back to a default path. Specifically:

```python
class LLMBridgeContextError(RuntimeError):
    """Audit-log integrity violation. Process must abort.

    Raised by LLMBridge when the run-context invariants in §1.4.1 are violated.
    Catching this exception inside the bridge or its callers is forbidden — the
    only legitimate handlers are (a) the top-level workflow runner, which
    re-raises after writing a SystemExit-class shutdown record, and (b) tests
    that explicitly assert raise behavior.
    """
```

**Mandatory contract**:

1. The bridge **raises** `LLMBridgeContextError` synchronously, before the offending row is written. The corrupting row never reaches disk.
2. The exception is **uncaught by intent** — `agent/llm_bridge.py` must not wrap any of the four checks in try/except. Static check (`tests/unit/agent/llm_bridge/test_no_silent_swallow.py`) AST-greps the bridge module to ensure no `except LLMBridgeContextError` exists in production code.
3. The runner (`run_exploration_adaptive.py`) installs a top-level handler that on `LLMBridgeContextError`:
   - Logs a structured shutdown row to stderr + `chain_log.txt`: `[FATAL] LLMBridgeContextError: <reason> — aborting run to prevent telemetry corruption.`
   - Calls `sys.exit(2)` (distinct from the `exit(1)` used by the consecutive-failure brake, so a downstream classifier can tell the two apart).
4. **No workaround flag exists.** There is no `--skip-runid-check` CLI option. If the check is wrong, the fix is to fix the bridge, not to bypass the check.

**Rationale**: a corrupted `token_usage.jsonl` poisons every metric in §4. Continuing past a known corruption point produces audit data that *looks* valid but isn't — the worst possible failure mode. Aborting is safer than producing convincing-but-wrong numbers.

**Tested by** `test_runner_aborts_on_runid_mismatch`: spawn a subprocess runner pointed at a workspace whose `token_usage.jsonl` already has a different run_id; assert exit code 2 and the FATAL log line.

**Tests** (added to §1.8):

| Test | Asserts |
|------|---------|
| `test_setter_rejects_run_id_mutation` | Calling `set_run_context` twice with different `run_id` raises `LLMBridgeContextError`. |
| `test_setter_rejects_backwards_iter` | Calling `set_run_context(iter=3)` after `set_run_context(iter=5)` raises. |
| `test_record_usage_aborts_on_run_id_mismatch` | Writing to a file whose first row has a different `run_id` is refused. |
| `test_iter_flush_marker_emitted` | After advancing iter, the previous iter has an `_iter_flush` marker as its last row. |
| `test_jsonl_linter_detects_leakage` | One-pass linter flags a row with `iter=N` that appears after the `_iter_flush` for iter `N`. |

### 1.5 Call-Site Labels

Each LLM call must have a stable `label` that names *which* prompt fired. Today the only signal is the inconsistent `[PROMPT_SIZE] {label}` print. Standardize on:

| Label | Site |
|-------|------|
| `proposer.comparison` | `_render_stage_user_prompt` for `COMPARATIVE_ANALYSIS` stage |
| `proposer.causal_reasoning` | same, `CAUSAL_REASONING` stage (incl. boldness retry) |
| `proposer.proposing` | same, `proposing` stage (line 1134 region) |
| `proposer.legacy_reasoning` | legacy 2-call path, `generate_text` at `ml_model_proposal_agent.py:780` |
| `proposer.legacy_commit` | legacy 2-call path, `generate` at `ml_model_proposal_agent.py:797` |
| `tuner.planner` | `agent/llm_bridge.py:401` (existing planner call) |
| `tuner.reflector` | `LLMBridge.reflect` (line 403) |
| `interpretation.per_model` | `result_interpretation_agent.py:714` |
| `interpretation.synthesis` | same, line 820 |
| `interpretation.dedup` | same, line 1179 |
| `validator.code_review` | wherever the validator's LLM step calls `generate` |
| `implementor.reasoning` | `ml_model_implementor.py:751` (free-text reasoning call) |
| `implementor.code` | `ml_model_implementor.py:756` (strict-JSON code commit) |
| `implementor.repair` | `ml_model_implementor.py:769` (validate→repair loop) |

Add the label to every call site as an explicit arg threaded through `bridge.generate(label=...)`. The bridge stores it in the row.

**Component breakdowns** are passed only by call sites that build their user prompt via `_render_stage_user_prompt` (the staged proposer pipeline + boldness retry + proposing). The legacy 2-call path uses `_build_reasoning_prompt` / `_build_commit_prompt` and does not produce a 9-key breakdown — its rows leave `components` empty (still labeled, so chain_log stays clean). See §1.3 for the breakdown shape.

### 1.6 chain_log.txt Live Reporting

Per-call line, written to stdout (already tee'd into `chain_log.txt` by Phase R `_TeeStream`):

```
[TOKEN] iter=04 stage=proposer.causal_reasoning  prompt_tok=11423  comp_tok=842  total_tok=12265  chars(sys/user)=1812/40081
```

And one per-iter rollup line (emitted by the workflow at iter end after all calls have flushed):

```
[TOKEN_ITER] iter=04 calls=12 total_tok=148231 (proposer=87421  tuner=42109  interp=18701)  cumulative_total=412903
```

Operators can `grep '\[TOKEN_ITER\]' chain_log.txt | awk ...` for a per-run cost sparkline.

### 1.7 Schema — `token_usage.jsonl`

One JSON object per line:

```json
{
  "ts":         "2026-05-04T15:32:11.443Z",
  "run_name":   "exploit_cnn_v11_0503",
  "iter":       4,
  "label":      "proposer.causal_reasoning",
  "model":      "gpt-4o-mini",
  "provider":   "openai",
  "tokens": {
    "prompt":     11423,
    "completion": 842,
    "total":      12265
  },
  "chars": {
    "system":  1812,
    "user":    40081,
    "total":   41893
  },
  "components": {
    "system_prompt":        1812,
    "candidates_markdown":  9213,
    "interpretation_json":  14207,
    "previous_failures":     1042,
    "vocab_block":           3754,
    "expert_context_block":   612,
    "agent_cards_block":      488,
    "prior_stage_outputs":   7104,
    "recent_gate_block":     3661
  },
  "extra": { "stage_idx": 1, "attempt": 1 }
}
```

Pydantic schema lives at `agent/schemas/telemetry/token_usage.py`. A new module — there is no existing telemetry schema package; the V11 audit is the first call site that needs it, so we introduce it here and reuse for any future per-call audits.

### 1.8 Unit + integration tests

| Test | Scope |
|------|-------|
| `tests/unit/agent/llm_bridge/test_record_usage.py` | Mock the OpenAI client to return a fixed `Usage(prompt_tokens=…)` shape; assert one row appended to a tmp_path log. Cover the `usage is None` fallback. |
| `tests/unit/agent/proposal/test_audit_components.py` | Build a synthetic `accumulated` dict + blocks; assert all 9 component keys present and sum to total. |
| `tests/unit/runner/test_token_log_iter_rollup.py` | Mock 3 LLM calls with known token counts; assert the `[TOKEN_ITER]` rollup line is emitted with correct totals. |
| Pseudo-mode integration | Run a one-iter pseudo workflow end-to-end; assert `token_usage.jsonl` exists and parses; assert ≥4 rows (proposer × 3 stages + interp × 1). |

No real-API tests required for Phase 1 — the usage-capture path is exercised by the mock, and the row-shape contract is what we care about.

### 1.9 Top-3 Bloat Report — mandatory Phase 2 gate

After Phase 1 lands, run a real chain (≥ 5 iterations, V11-equivalent settings) and produce `reports/v12_top3_bloat.md`. **Phase 2 cannot start until this report is written and reviewed** — the §12 audit was estimation; this is measurement.

#### 1.9.1 What the report must contain

For each of iterations 1–5:

| Column | Source |
|--------|--------|
| `iter` | row `iter` field |
| `total_prompt_tokens` | sum across all calls |
| `top_3_bloat` | the 3 component-keys with the largest `chars.components.<key>` values, ranked, with their token estimates |
| `top_3_share_pct` | what fraction of total prompt tokens those 3 components account for |
| `growth_vs_iter1` | per-component delta from iter 1 baseline |

Plus an aggregate table:

| Component | Iter 1 chars | Iter 5 chars | Growth | Verdict |
|-----------|--------------|--------------|--------|---------|
| `interpretation_json` | … | … | … | bloating / bounded / shrinking |
| `candidates_markdown` | … | … | … | … |
| `previous_failures` | … | … | … | … |
| `vocab_block` | … | … | … | … |
| `system_prompt` | … | … | … | … |
| `prior_stage_outputs` | … | … | … | … |
| `expert_context_block` | … | … | … | … |
| `agent_cards_block` | … | … | … | … |
| `recent_gate_block` | … | … | … | … |

The `Verdict` column uses fixed thresholds: `bloating` if growth > 30% iter-over-iter, `bounded` if within ±10%, `shrinking` if < -10%.

#### 1.9.2 The decision branch

The report ends with one of three explicit verdicts:

1. **"Confirmed Proposer Hypothesis"** — top-3 bloat is dominated by `interpretation_json`, `candidates_markdown`, `previous_failures`, or `prior_stage_outputs`. Phase 2 proceeds as designed in §2.
2. **"Pivot Required — Tuner"** — top-3 bloat is dominated by tuner planner / reflector calls (visible in row `label` = `tuner.planner` / `tuner.reflector`). Phase 2 surgery target shifts from proposer to tuner; the §2 design is set aside and a tuner-focused dehydration design is drafted instead.
3. **"Pivot Required — Other"** — bloat is somewhere else (interpretation synthesis, validator code review, or an unexpected component). Surgery follows the data; we draft a new design before any code lands.

The Phase 2 §2 design is therefore **conditional**: it only applies if verdict (1) is reached. Verdicts (2) or (3) trigger a fresh design pass, not blind execution of §2.

#### 1.9.3 Sanity floor

If verdict (1) is reached **but** total token spend at iter 5 is < 1.5× iter 1 (i.e., growth is gentler than expected), the design lead may decide Phase 2 is not yet justified — the cost is real but small enough that the engineering effort doesn't pay off. This is an explicit "do nothing" exit; document the decision and revisit at iter 15.

---

## 2. Phase 2 — Context Dehydration Surgery ("the Blade")

**Conditional**: applies only if §1.9 verdict is "Confirmed Proposer Hypothesis." Pivot verdicts trigger a fresh design.

Phase 2 lands **only after** Phase 1 telemetry is in production for at least one full chain run, so we have a baseline against which to measure the dehydration effect.

### 2.1 Goals

| # | Outcome | Verifies |
|---|---------|----------|
| 2.1 | Failures forwarded to the next iter are **dehydrated** to ~300 char "Error Signatures" rather than full traceback / log strings. | Failure-block size is bounded per iter. |
| 2.2 | `interpretation['per_model_score_tables']` is truncated to top-N (default N=5) before serialization into the proposer's JSON region. | JSON region size flattens after iter 5. |
| 2.3 | Only the immediate predecessor (iter N-1) carries full source + full causal_hypothesis; older attempts carry a 1-line "idea + failure_reason" summary. | Per-iter prompt size is no longer O(num_models). |
| 2.4 | The proposer's system prompt requires a `delta_reasoning` field that **explicitly compares the new proposal to N-1**, not to the full history. | Forces signal extraction; gives us a structured audit trail. |
| 2.5 | The "Evolutionary Ledger" is a single, schema-validated object the proposer reads — not a free-form accumulation of fields. | One source of truth for what flows iter-to-iter. |

### 2.2 Log Dehydration — Error Signature Skill

**New file**: `agent/skills/error_signature_skill.py`.

**Contract**:

```python
@dataclass
class ErrorSignature:
    error_type: str          # e.g. "torch.cuda.OutOfMemoryError"
    short_message: str       # ≤ 120 chars, the bare error message
    last_frames: list[str]   # last 3-5 traceback lines that name *user* code
    failure_class: str       # one of: "vram", "training", "validation", "shape", "scoring", "unknown"

def extract(traceback_text: str, *, max_frames: int = 5) -> ErrorSignature: ...
def render(sig: ErrorSignature) -> str:
    """Return a 4-line markdown block: kind + message + last frames."""
```

**Where it's invoked**:

1. `workflows/model_exploration.py` `_render_physical_rejection` — dehydrate the existing rejection block to 4 lines instead of the current ~350 chars per entry.
2. `nodes/ml_code_validator_agent.py` — when emitting validator `error_message`, store both the full text (for `validator_iter_NNN.json` on disk) and an `ErrorSignature` (for in-memory propagation).
3. The implementor's `previous_failures` list is built from `ErrorSignature.render(...)`, not from raw traceback strings.

**Caveat**: do not lose information. The full traceback is still written to disk per call (e.g. `validator_iter_NNN.json`); only the **propagated** version is dehydrated.

### 2.3 JSON Truncation — `per_model_score_tables`

**Current**: `ml_model_proposal_agent.py:929-934` includes the full `per_model_score_tables` dict in `accumulated["interpretation_summary"]`. `_render_stage_user_prompt` (line 475-478) strips the markdown-rendered version but keeps the dict intact in JSON. At iter 30 this is ~30 KB.

**Change**: introduce `truncate_score_tables(tables: Dict[str, ScoreComparisonTable], top_n: int) -> Dict[...]` in `nodes/proposal_helpers.py`. It:

1. Sorts by `best_score` (or whichever metric the existing top-N selector uses, to stay consistent with `select_candidate_models`).
2. Returns only the top-N entries.
3. For dropped models, emits a single companion field: `"score_tables_omitted": ["modelA", "modelB", ...]` so the proposer knows the universe is larger than what's in context.

Call site: just before populating `accumulated["interpretation_summary"]["per_model_score_tables"]`.

`top_n` is configurable via the proposer's `pipeline.model_selection` config — default 5 to match the existing markdown selector.

### 2.4 Sliding Window for Source Code

**Current**: every candidate emitted by `select_candidate_models` carries `source_code` and `score_table` markdown into `build_candidate_markdown_block`. There is no distinction between "the model we just trained (N-1)" and "models we tried 10 iters ago".

**Change**: introduce a window policy in `nodes/proposal_helpers.py`:

```python
def apply_source_window(candidates: list[dict], *,
                        full_source_for: int = 1,   # iters back
                        summary_for_older: bool = True) -> list[dict]:
    """For each candidate, decide whether to include source_code / score_table_full
    or a 1-line summary stub."""
```

Each candidate dict carries an `iter_offset` (0 = current, 1 = N-1, ≥ 2 = older). For `iter_offset >= 2`:

- `source_code` removed.
- `score_table` replaced with one line: `"<model_type>: best_score=<val>, failure_reason=<dehydrated>"`.

**Schema impact**: `ProposalInput.interpretation` already carries enough metadata to compute `iter_offset` (per_model_score_tables has `iter_introduced` or similar; if not, we add it via the interpretation agent — see §3 for the schema change list).

### 2.5 Delta Reasoning Requirement — Prompt Templates

**Affected files**:

- `agent/prompt_templates/proposal/causal_reasoning_stage.md`
- `agent/prompt_templates/proposal/proposing_stage.md`
- `_explore` and `_exploit` mode variants of each (currently 6 files total).

**Change**: add a required output field to the proposer's structured response (`agent/schemas/proposal.py` `ProposalOutput`):

```python
delta_reasoning: DeltaReasoning = Field(
    description="Required comparison between this proposal and the immediately "
                "preceding attempt (N-1). Forces explicit signal extraction "
                "rather than free-form 'add another idea on top'."
)

class DeltaReasoning(BaseModel):
    predecessor_model_type: str
    what_we_keep: list[str]    # bounded ≤ 3 entries
    what_we_change: list[str]  # bounded ≤ 3 entries
    why_change_addresses_predecessor_failure: str  # ≤ 400 chars
```

Prompt-template addition (in causal_reasoning):

> **Required: Delta Reasoning.** Before proposing, name the immediate predecessor (iter N-1) and answer in ≤3 bullets each: (a) what specific component of N-1 do you keep? (b) what specific component do you change? (c) why does the change address N-1's documented failure (cite the Error Signature)?

A field validator on `DeltaReasoning` enforces the bounded list lengths.

### 2.6 The Evolutionary Ledger — schema

**New schema**: `agent/schemas/proposal.py` adds:

```python
class EvolutionaryLedger(BaseModel):
    """Bounded, dehydrated cross-iter context. Replaces ad-hoc accumulation
    of previous_failures + interpretation['per_model_score_tables'] +
    expert_context['accumulated_key_findings']."""

    predecessor: PredecessorEntry  # full source + full causal_hypothesis + full ErrorSignature
    older_attempts: list[OlderAttemptSummary]  # bounded ≤ K (default 8); 1-line each
    confirmed_lessons: list[str]  # promoted lessons from interpretation; ≤ 6 entries
    open_bottlenecks: list[str]   # current-iter unresolved bottlenecks; ≤ 4 entries

class PredecessorEntry(BaseModel):
    iter:           int
    model_type:     str
    causal_hypothesis: str       # ≤ 600 chars
    source_code:    str          # full
    score_summary:  str          # 1 line
    error_signature: Optional[ErrorSignature]  # None on success

class OlderAttemptSummary(BaseModel):
    iter:           int
    model_type:     str
    one_line_idea:  str          # ≤ 140 chars
    failure_reason: str          # ≤ 140 chars
```

`ProposalInput` gets a single new field `ledger: EvolutionaryLedger` and the workflow protocol populates it via `restore_prior_state(...)`. The legacy fields (`previous_failures`, `interpretation`, `expert_context`'s accumulated_key_findings, etc.) **stay** for one release as a fallback path; the proposer reads the ledger first, falls back to the legacy fields only if `ledger is None` — a feature flag (`use_evolutionary_ledger=True` default) lets us A/B for one chain run.

After validation, the legacy fields are deleted.

### 2.7 What gets removed (after validation)

| File | Removal |
|------|---------|
| `nodes/ml_model_proposal_agent.py` | The flat `previous_failures` rendering at line 644-648 (replaced by `ledger.predecessor.error_signature` + `ledger.older_attempts[*].failure_reason`). |
| `nodes/ml_model_proposal_agent.py` | `interpretation_summary["per_model_score_tables"]` (line 934) — replaced by ledger. |
| `agent/schemas/proposal.py` | `previous_failures: List[str]` field (line 642) and `recent_gate_exhaustions` field if its info is fully covered by `ledger.confirmed_lessons` + dehydrated signatures (TBD by Phase 1 measurement — keep if telemetry shows it's still load-bearing). |
| Workflow assembly | The `accumulated_physical_rejections` and `accumulated_key_findings` synthesis paths in `workflows/model_exploration.py` (lines 916-954) — replaced by ledger construction. |

### 2.8 Offline Forensic Benchmark — pre-flight test before any code lands

Phase 2 is a destructive refactor (we are throwing away ~90% of the raw failure text). Before we trust the new `ErrorSignatureSkill` to compress live runs, we must prove it captures the actual root cause from a known-failure log. The V11 `spectral_u_operator_lite` run is the perfect benchmark — it failed in a specific, traceable way and the full forensic trail is on disk.

#### 2.8.1 Benchmark target

**Forensic source**: `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v11_0503/iter_002/iteration_002/spectral_u_operator_lite/`

Available artefacts:

- `run_output_iter_002.json` — full tuner run output including per-attempt error strings.
- `run_config_iter_002.json` — the config that was running.
- `cached_models/` — surviving artefacts from the failed attempts.
- `records/` — per-attempt records with timing and error fields.
- `iter_002_hardware.json` — the hardware context at the time of failure.

The cross-iter trail (workflow chain log + memory traces) lives in the workspace root.

#### 2.8.2 The test

A new test file `tests/forensic/test_v11_spectral_u_signature.py` (a new `tests/forensic/` directory — these are pre-flight verifications, not unit/integration):

```python
def test_spectral_u_failure_signature_captures_root_cause():
    raw_log = _load_v11_spectral_u_failure_text()  # reads run_output + chain_log
    sig = error_signature_skill.extract(raw_log)

    # 1. Failure class must be correctly inferred
    assert sig.failure_class == "vram"

    # 2. The error type must name the actual exception class
    assert "OutOfMemoryError" in sig.error_type or "MemoryError" in sig.error_type

    # 3. Last frames must mention the offending architectural component
    frames_text = "\n".join(sig.last_frames).lower()
    assert "fft" in frames_text or "spectral" in frames_text, \
        "Signature lost the FFT layer — compressor is failing"
    assert "u_net" in frames_text or "decoder" in frames_text or "encoder" in frames_text, \
        "Signature lost the U-Net layer — compressor is failing"

    # 4. The rendered short_message must mention VRAM, not just "error"
    assert any(tok in sig.short_message.lower() for tok in ("vram", "cuda", "memory")), \
        f"Signature short_message is generic ({sig.short_message!r}) — compressor is failing"

    # 5. The fully rendered signature must be < 600 chars (target: ~300)
    rendered = error_signature_skill.render(sig)
    assert len(rendered) < 600, f"Signature too long: {len(rendered)} chars"

    # 6. Compression ratio gate (also enforced as §4 metric Cr)
    cr = len(rendered) / len(raw_log)
    assert cr < 0.10, f"Compression ratio {cr:.3f} ≥ 0.10 — too verbose"
```

**Pass criteria**:

- All 6 assertions hold.
- The signature is independently human-reviewable: a reviewer reads the rendered output and answers "yes, this is what failed and why" without consulting the raw log.

**Fail criteria**:

- Any assertion fails — the compressor is not extracting the load-bearing tokens. **Phase 2 code does not land** until the skill is improved and the test passes.
- Specifically: if the rendered signature says `"Unknown Error"` or only mentions "training failed" without naming the layer, the skill has thrown away the cause and is unsafe to deploy.

#### 2.8.3 Why this benchmark before live deployment

A live chain run cannot be the first place we discover the compressor is dropping the FFT-layer signal — by then the proposer has seen 30 iterations of vague "Unknown Error" feedback and the run is wasted. The offline benchmark gives a deterministic pass/fail on real failure data before we trust the skill in production.

The test stays in the suite (gated behind a `@pytest.mark.forensic` marker) as a regression guard — any future change to `ErrorSignatureSkill` must keep passing this test.

### 2.9 The Trap Test — long-term wisdom retention

The Sliding Window (§2.4) shrinks attempts older than N-1 to a 1-line summary. The risk: a fatal architectural lesson learned at iter 2 is forgotten by iter 10. The Trap Test makes this risk measurable.

#### 2.9.1 The setup

A pseudo-mode integration test `tests/integration/proposer/test_long_term_wisdom_trap.py`:

1. **Iter 1**: ledger is empty. Proposer proposes any model.
2. **Iter 2**: a synthetic predecessor is injected with a clearly-fatal flaw — the test plants:
   - `model_type = "deep_recurrent_no_residual_v1"`
   - `error_signature.short_message = "vanishing gradient: all params got grad_norm < 1e-9 by epoch 3 because the 32-layer LSTM has no residual connections"`
   - `error_signature.failure_class = "training"`
   - `older_attempts[*].failure_reason = "no residual connections in deep recurrent stack → vanishing gradient"`
3. **Iters 3–9**: the test feeds a sequence of unrelated successful proposals so the trap entry ages out of the immediate predecessor slot and into `older_attempts`.
4. **Iter 10**: the predecessor (N-1) is a *successful* unrelated model; the trap entry is now in `older_attempts[7]` (8 iters old). The proposer is given a real LLM call with a prompt that biases towards trying a deep recurrent stack again (e.g., "the user wants a temporal-causal architecture with maximum depth").

#### 2.9.2 The assertion

The proposer's `delta_reasoning` or causal_hypothesis output must explicitly cite the iter-2 trap:

```python
def test_proposer_cites_iter2_trap_when_deciding_iter10():
    output = run_proposer_with_trap_at_iter2(target_iter=10, biased_prompt=DEEP_RECURRENT_BIAS)

    full_reasoning = (
        output.delta_reasoning.why_change_addresses_predecessor_failure +
        " " + output.causal_hypothesis
    ).lower()

    # Must reference the specific lesson from iter 2
    assert "vanishing gradient" in full_reasoning or "residual" in full_reasoning, \
        f"Proposer at iter 10 did not cite the iter-2 trap. Reasoning: {full_reasoning!r}"

    # Must not propose the trap architecture
    assert "no residual" not in output.proposal.architecture_summary.lower(), \
        "Proposer fell into the trap — it proposed the very architecture that failed at iter 2"
```

#### 2.9.3 Pass / fail

- **Pass**: proposer cites the iter-2 lesson AND avoids the failing architecture. The Sliding Window retained signal at distance 8.
- **Fail (proposer falls into the trap)**: dehydration is too aggressive. Increase `older_attempts` depth, or promote chronic lessons into `confirmed_lessons` more aggressively.
- **Fail (proposer cites the lesson but proposes the architecture anyway)**: this is a prompt issue, not a context issue. Sharpen the Delta Reasoning prompt.

The test runs in real-API mode (gated behind `@real_run`) because the wisdom-retention question is fundamentally about LLM behaviour, not code paths. A pseudo-mode version (with a fixed mock response) verifies only the *plumbing* — that the iter-2 lesson is *present* in the rendered prompt — and is a unit test:

```python
def test_iter2_lesson_present_in_iter10_prompt():
    rendered_prompt = build_proposer_prompt_with_trap_at_iter2(target_iter=10)
    assert "vanishing gradient" in rendered_prompt
    assert "deep_recurrent_no_residual_v1" in rendered_prompt
```

The unit test is a strict prerequisite — if the lesson is not in the prompt, the LLM cannot possibly cite it, and the real-API test is meaningless.

#### 2.9.4 Tuning knobs

If the test fails for reasons (1) or (2), we have explicit knobs to tune:

| Knob | Default | Effect |
|------|---------|--------|
| `older_attempts_K` | 8 | Number of older summaries kept. Larger = better retention, more tokens. |
| `confirmed_lessons_min_iters` | 1 | If a lesson appears in N+ attempts, promote to `confirmed_lessons`. Lower = more aggressive lesson retention. |
| `error_signature.last_frames_count` | 5 | More frames = more context per failure, larger ledger. |

The Trap Test is the empirical scoreboard for setting these knobs.

---

## 3. Files Touched — Full List

| Path | Phase | Change |
|------|-------|--------|
| `agent/llm_bridge.py` | 1 | Capture `response.usage`; new `_record_usage` helper; `set_run_context` setter; thread `label` arg into `generate`/`generate_text`/`tool_call`/`reflect`. |
| `agent/schemas/telemetry/token_usage.py` | 1 | **New file**. Pydantic schema for `token_usage.jsonl` row. |
| `agent/schemas/telemetry/__init__.py` | 1 | **New file**. Package init. |
| `nodes/ml_model_proposal_agent.py` | 1 + 2 | Pre-assembly hook (`_audit_proposer_components`, Phase 1); ledger consumption + delta_reasoning rendering (Phase 2); remove flat `previous_failures` path (Phase 2 cleanup). |
| `nodes/result_interpretation_agent.py` | 1 + 2 | Add `iter_introduced` to per_model_score_tables (Phase 2 prerequisite); add labels to LLM calls (Phase 1). |
| `nodes/ml_hyperparameter_tune_agent.py` | 1 | Add labels to planner / reflector calls. |
| `nodes/ml_code_validator_agent.py` | 1 + 2 | Add labels (Phase 1); emit `ErrorSignature` alongside full error_message (Phase 2). |
| `nodes/proposal_helpers.py` | 2 | Add `truncate_score_tables`, `apply_source_window`. |
| `agent/skills/error_signature_skill.py` | 2 | **New file**. `extract` + `render` + `ErrorSignature` dataclass. |
| `agent/schemas/proposal.py` | 2 | Add `EvolutionaryLedger`, `PredecessorEntry`, `OlderAttemptSummary`, `DeltaReasoning`. Add `ProposalInput.ledger` field. Add `ProposalOutput.delta_reasoning` field. |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | 2 | Build `ledger` from `recent_tune_outputs` + interpretation; populate the new field. |
| `workflows/model_exploration.py` | 2 | Replace `accumulated_physical_rejections` + flat failure assembly with ledger construction. Setter call to `bridge.set_run_context` per iter (Phase 1). |
| `core/resume.py` | 2 | Build older-attempts summary list from disk-resident interpretations (replaces `accumulated_key_findings` flat list). |
| `agent/prompt_templates/proposal/causal_reasoning_stage*.md` (×3) | 2 | Add Delta Reasoning required block. |
| `agent/prompt_templates/proposal/proposing_stage*.md` (×3) | 2 | Reference `delta_reasoning` field in output schema. |
| `run_exploration_adaptive.py` | 1 | Per-iter `[TOKEN_ITER]` rollup line emit. |
| `tests/unit/agent/llm_bridge/test_record_usage.py` | 1 | **New**. |
| `tests/unit/agent/proposal/test_audit_components.py` | 1 | **New**. |
| `tests/unit/agent/skills/test_error_signature.py` | 2 | **New**. |
| `tests/unit/agent/proposal/test_evolutionary_ledger.py` | 2 | **New**. |
| `tests/unit/agent/proposal/test_truncate_score_tables.py` | 2 | **New**. |
| `tests/unit/agent/proposal/test_source_window.py` | 2 | **New**. |
| `tests/unit/runner/test_token_log_iter_rollup.py` | 1 | **New**. |

---

## 4. Success Metrics

Measurable at iter end via `token_usage.jsonl` aggregation (Phase 1 must be live first).

The metrics split into two families:

- **Cost metrics** — does the prompt actually shrink? (rows 1–6, 9 below)
- **Intelligence metrics** — does the agent stay smart after we shrink the prompt? (rows 7–8, 10–11 below)

A refactor that improves cost while regressing intelligence is a failure. The intelligence metrics are non-negotiable.

### 4.1 Cost & coverage metrics

| # | Metric | Phase | Target | Failure threshold |
|---|--------|-------|--------|-------------------|
| 1 | **Telemetry coverage** | 1 | 100% of LLM calls produce one row in `token_usage.jsonl`. | Any call missing — Phase 1 has not landed. |
| 2 | **Round 4 vs Round 1 size** | 2 | `prompt_tokens(iter=4) ≤ 1.20 × prompt_tokens(iter=1)` for the proposer's `proposing` stage. | > 1.5× — Phase 2 has not solved the growth problem. |
| 3 | **Iter 30 cap** | 2 | `prompt_tokens(iter=30) ≤ 1.50 × prompt_tokens(iter=1)`. | > 2.5× — ledger is leaking. |
| 4 | **JSON region size** | 2 | `chars.components.interpretation_json` is bounded ≤ 8 KB regardless of iter. | unbounded growth — `truncate_score_tables` not effective. |
| 5 | **Failure block size** | 2 | `chars.components.previous_failures` ≤ 1.5 KB per iter (~5 entries × 300 char Error Signatures). | > 4 KB — dehydration regressed. |
| 6 | **Boilerplate share** | 2 | static + repeated content (vocab, hardware, system prompt) ≤ 25% of proposer prompt at iter 4 (down from ~41% per §12.4). | > 35% — boilerplate de-dup didn't land. |
| 9 | **Total run cost** | 2 | A 30-iter chain run total token spend ≤ 60% of a matched V11 baseline. | > 90% — refactor did not pay off; revisit. |

### 4.2 Intelligence-preservation metrics (the "leaner ≠ stupider" gates)

These are the metrics that prove Phase 2 didn't lobotomize the agent. They are mandatory pass-criteria; the refactor does not ship if any of these regress.

| # | Metric | Phase | Definition | Target | Failure threshold |
|---|--------|-------|------------|--------|-------------------|
| 7 | **Failure Re-occurrence Rate (FRR)** | 2 | Count of iters where the proposer either (a) re-proposes an architecture name that already appears in `older_attempts` with a non-null `error_signature`, or (b) emits a model whose `error_signature` after training matches a prior iter's error_signature by `(failure_class, error_type)`. Computed as `FRR = n_repeated / n_total_iters`. | **0.00** in any 30-iter window. | **> 0.00** — dehydration is hiding load-bearing context. The proposer is forgetting documented failures and re-trying them. Block ship; tune §2.9 retention knobs. |
| 8a | **DRR_Structural** (AST/regex) | 2 | Sample 10 iters at random from a 30-iter run. For each `delta_reasoning.what_we_change` claim, attempt to find a corresponding AST node delta or regex match in the source-code diff (predecessor → current iter). A claim is *structurally realized* if either (a) an AST node added/removed/modified at the named location matches the claim's referent, or (b) a regex derived from the claim's keywords matches a non-empty diff hunk. Computed deterministically — no LLM in the loop. | **≥ 0.85** | **< 0.70** — the proposer's claimed changes are not detectable in the source. The Delta Reasoning is structurally hallucinated. Sharpen the §2.5 prompt schema or block ship. |
| 8b | **DRR_LLM** (semantic) | 2 | Same 10-iter sample. Cheap LLM judge (deterministic temperature=0) reads each `what_we_change` claim alongside the predecessor and current source; returns `realized=True/False` per claim. Reports `DRR_LLM = n_realized / n_declared`. | **≥ 0.90** | **< 0.75** — the change is not present semantically (the structural match was a coincidence, or the change is renamed/refactored away). |
| 8c | **DRR Gap** (hallucination indicator) | 2 | `gap = abs(DRR_LLM − DRR_Structural)`. A small gap means the two methods agree and the result is trustworthy. A large gap means one method is being fooled — usually it's the LLM judge being too generous (claim "I added attention" matches semantically against any attention-shaped code, even pre-existing). | **≤ 0.15** | **> 0.25** — the two graders disagree materially. Either the structural matcher is too strict or the LLM judge is too lenient. Re-tune the methods before trusting either number. |
| 10 | **Dehydration Compression Ratio (Cr)** | 2 | Per failed attempt: `Cr = len(rendered_signature) / len(raw_traceback_or_log)`. Computed across all failures in a 30-iter chain run; reported as `(median, p95)`. | **median Cr < 0.10**, **p95 Cr < 0.15**. | **median Cr ≥ 0.15** — compressor is not compressing. **p95 Cr ≥ 0.30** — pathological cases (long tracebacks) are slipping through, which is exactly when compression matters most. |
| 11 | **delta_reasoning presence** | 2 | 100% of `ProposalOutput` payloads carry a non-null, schema-valid `delta_reasoning` (bounded list lengths, all required subfields). | 100% | < 100% — schema validation should make this impossible; any missing payload is a regression. |

#### 4.2.1 How the intelligence metrics are computed

- **FRR computation** is automated: `tools/compute_frr.py` reads `token_usage.jsonl` + per-iter ledger artefacts + per-iter validator outputs, joins on `error_signature`, and emits a CSV. Runs as a CI step on the V13 chain output before Phase 2 ships.
- **DRR_Structural computation** is fully automated: `tools/compute_drr.py` parses each claim, derives an AST query (when the claim is structural — "add residual connection", "change kernel size", "replace LSTM with GRU") or a regex (when the claim is non-structural — "increase dropout to 0.3"), and matches against the source-code diff between predecessor and current iter. Output: per-claim realized/not + the AST/regex evidence string for human spot-check.
- **DRR_LLM computation** is semi-automated: same script invokes a cheap LLM judge (gpt-4o-mini, temperature=0) with the claim + diff hunks; returns realized/not per claim with a one-line rationale. The LLM judge is deliberately lighter than the proposer's own model — we don't want the judge to share blind spots with the proposer.
- **DRR Gap** is just `abs(DRR_LLM - DRR_Structural)`; reported alongside the two raw numbers. The first 30-iter run uses both methods on every sample so we can calibrate the gap distribution before deciding to lean on one or the other long-term (open question §6.1).
- **Cr** is computed in-process whenever `ErrorSignatureSkill.extract` runs on a real failure: the skill records `(input_chars, output_chars)` to a sidecar log; aggregator reports median + p95.

#### 4.2.2 Caveats

- The metrics rely on Phase 1 being trustworthy. If Phase 1 telemetry shows `tokens.prompt is None` for >5% of rows (provider does not return usage), we degrade to char-based comparison and document the caveat.
- FRR can be falsely zero if the proposer never has occasion to repeat itself (e.g., the chain explores a wide design space). To guard against false negatives, also check `n_unique_architectures / n_total_iters` is healthy (> 0.7) — a high-FRR-but-also-low-diversity proposer would be a different kind of broken.
- DRR uses an LLM judge; any LLM judge has noise. Calibrate by running DRR on a known-good baseline (V11 records, where we can manually agree on realized vs not) and verify the judge produces reasonable numbers.

---

## 5. Implementation Steps — Numbered Action List

**Decision gates** (no implementation begins until each gate passes):

- **Gate G0 (this doc)** — design approval. The quantitative success criteria in §4 must be explicitly agreed before any code lands.
- **Gate G1** — Phase 1 baseline report (`reports/v12_token_baseline.md`) + Top-3 Bloat Report (`reports/v12_top3_bloat.md`, §1.9) — gates Phase 2 design validity.
- **Gate G2** — Offline Forensic Benchmark (§2.8) passes — gates `ErrorSignatureSkill` going to production.
- **Gate G3** — Trap Test (§2.9) passes — gates the Sliding Window going to production.
- **Gate G4** — All §4 metrics pass on V13 chain run — gates legacy-path removal.

Each step is annotated `(Commit N)` matching the §8 commit ledger. Within a commit, all listed steps land together — they are not separately committable.

### Phase 1 (telemetry — must land first)

1. **(Commit 1)** **`agent/schemas/telemetry/token_usage.py`** — define `TokenUsageRow` Pydantic schema. Includes `tokens` (`prompt`/`completion`/`total`, all `Optional[int]`), `chars`, `components: Dict[str, int]`, `label`, `iter`, `model`, `provider`, `run_name`, `run_id`, `ts`, `extra`. Add `__init__.py`. Define `LLMBridgeContextError` exception alongside.
2. **(Commit 1 + Commit 2)** **`agent/llm_bridge.py`**:
   - **(Commit 1)** Modify `_chat_json` (line 615 region) to capture `response.usage` and pass it through. Same for `generate_text` (line 689) and `tool_call` and `reflect`.
   - **(Commit 1)** Add `_record_usage(...)` helper that appends one validated `TokenUsageRow` to `{workspace}/token_usage.jsonl`. Silent no-op when context unset.
   - **(Commit 1)** Add `label: str` kwarg to `generate`, `generate_text`, `tool_call`, `reflect`. Default `"unlabeled"` so old callers don't break, but log a warning when default is hit.
   - **(Commit 2)** Add `set_run_context(workspace, iter, run_name, run_id)` method with the §1.4.1 Setter Safety Protocol — refuses run_id mutation, refuses backwards iter, emits `_iter_flush` markers at iter boundaries; raises `LLMBridgeContextError` per §1.4.2.
3. **(Commit 1 + Commit 2)** **Unit tests for the bridge** — `tests/unit/agent/llm_bridge/`:
   - **(Commit 1)** `test_record_usage.py` — mock OpenAI client; assert one row written; assert fallback when `response.usage` is None.
   - **(Commit 2)** `test_setter_safety.py` — `test_setter_rejects_run_id_mutation`, `test_setter_rejects_backwards_iter`, `test_record_usage_aborts_on_run_id_mismatch`, `test_iter_flush_marker_emitted`, `test_jsonl_linter_detects_leakage`, `test_no_silent_swallow` (AST-grep static check), `test_runner_aborts_on_runid_mismatch` (subprocess test).
4. **(Commit 3)** **`nodes/ml_model_proposal_agent.py`** — add `_audit_proposer_components(...)` helper. Call it just before each `bridge.generate(...)` invocation (line 1014, 1054, 1134). Pass result as `extra` to the bridge.
5. **(Commit 3)** **Unit test for component audit** — `tests/unit/agent/proposal/test_audit_components.py`. Synthetic `accumulated` dict; assert all 9 keys present; assert sum equals total.
6. **(Commit 3)** **Add labels to all LLM call sites** — proposer, tuner planner, tuner reflector, interpretation per-model + synthesis + dedup, validator code review.
7. **(Commit 4)** **`workflows/model_exploration.py`** — call `bridge.set_run_context(workspace, iter, run_name, run_id)` at the top of each iter, with run_id generated once at workflow start.
8. **(Commit 4)** **`run_exploration_adaptive.py`** — generate run_id at startup; at iter end, read `token_usage.jsonl` for the current iter, emit `[TOKEN_ITER]` rollup line via the existing `_TeeStream`.
9. **(Commit 4)** **Pseudo-mode integration test** — one-iter end-to-end; assert `token_usage.jsonl` exists; assert ≥4 rows present and parse cleanly; assert `_iter_flush` markers correct.
10. **(Commit 5)** **Land Phase 1**, run one V12-baseline chain (5+ iters), publish `reports/v12_token_baseline.md` showing real per-call token counts.
11. **(Commit 5) Gate G1: Top-3 Bloat Report** — produce `reports/v12_top3_bloat.md` per §1.9 spec. **Decision branch**:
    - Verdict (1) "Confirmed Proposer Hypothesis" → continue to Commit 6.
    - Verdict (2) "Pivot Required — Tuner" or (3) "Other" → set §2 aside, draft a new design targeting the actual bloat source. **STOP HERE** until the new design is approved.
    - Sanity floor (§1.9.3) trips → defer Phase 2; revisit at iter 15.

### Phase 2 (dehydration — only after Gate G1 verdict 1)

12. **(Commit 6)** **`agent/skills/error_signature_skill.py`** — `ErrorSignature` dataclass + `extract` + `render`. Unit-test with samples from existing `validator_iter_*.json` files.
13. **(Commit 7) Gate G2: Offline Forensic Benchmark** — write `tests/forensic/test_v11_spectral_u_signature.py` per §2.8. Run against the V11 `spectral_u_operator_lite` forensic workspace. **All 6 assertions must pass.** If any fails, iterate on the skill (re-open Commit 6) before proceeding. **Do not land Commit 8 until this passes.**
14. **(Commit 8)** **`agent/schemas/proposal.py`** — add `EvolutionaryLedger`, `PredecessorEntry`, `OlderAttemptSummary`, `DeltaReasoning`. Add `ProposalInput.ledger` (default `None` for backward compat) and `ProposalOutput.delta_reasoning` (default `None` initially; tighten to required after one chain run).
15. **(Commit 9)** **`nodes/proposal_helpers.py`** — `truncate_score_tables`, `apply_source_window`. Unit-test both.
16. **(Commit 10)** **`core/resume.py`** + **`workflows/model_exploration.py`** + **`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`** — build the `EvolutionaryLedger` from disk-resident interpretation + run_output files. Include the dehydrated `ErrorSignature` for the predecessor.
17. **(Commit 11)** **`nodes/ml_model_proposal_agent.py`** — render the ledger in the user prompt (replacing the flat `previous_failures` block, the full `per_model_score_tables` JSON, and the per-attempt source code dump). Keep the legacy path behind `inp.ledger is None`.
18. **(Commit 11)** **`agent/prompt_templates/proposal/causal_reasoning_stage*.md`** — add the Delta Reasoning required block (×3 files). Same for `proposing_stage*.md` (×3) referencing the `delta_reasoning` output field.
19. **(Commit 11)** **Unit tests** — `test_evolutionary_ledger.py`, `test_truncate_score_tables.py`, `test_source_window.py`, `test_iter2_lesson_present_in_iter10_prompt` (the §2.9 plumbing-only Trap unit test). All synthetic, no API.
20. **(Commit 11) Gate G3: Trap Test** — write `tests/integration/proposer/test_long_term_wisdom_trap.py` per §2.9. Run in real-API mode with `@real_run` marker. **Both assertions must pass** (cite the iter-2 lesson AND avoid the failing architecture). If fails, tune §2.9.4 knobs before proceeding.
21. **(Commit 11)** **Tier-1 integration test** — `tests/integration/nodes/test_ml_model_proposal_agent_ledger.py` — real LLM call with a populated `EvolutionaryLedger`; assert `delta_reasoning` is present and well-formed.
22. **(Commit 12)** **Land Phase 2 behind `use_evolutionary_ledger=True` default**, run one V13 chain (5+ iters; ideally ≥ 15 iters so iter 30 metrics extrapolate), compare against V12 baseline.
23. **(Commit 12) Gate G4: §4 metrics validation** — publish `reports/v13_token_dehydration.md` reporting all 13 metrics (cost rows 1–6, 9 + intelligence rows 7, 8a, 8b, 8c, 10, 11). **All metrics must pass their target.** If any fails:
    - FRR > 0 → revisit §2.4 sliding window depth, §2.6 confirmed_lessons promotion threshold.
    - DRR_Structural < 0.70 → tighten the §2.5 Delta Reasoning prompt to demand specific, machine-checkable claims.
    - DRR Gap > 0.25 → re-tune the structural matcher and/or the LLM judge before trusting either number.
    - Cr ≥ 0.15 median or ≥ 0.30 p95 → revisit `error_signature_skill.extract` heuristics; widen `last_frames_count`.
    - Cost metrics fail → ledger is leaking; instrument and patch.
24. **(Commit 12 cleanup)** **If all G4 metrics pass**, remove the legacy fallback path (line 644-648 in proposer, the flat `previous_failures` field, the un-truncated `per_model_score_tables` inclusion). One cleanup commit.

---

## 6. Open Questions for Reviewer

1. **Structural-vs-Semantic DRR — long-term direction**: revision 3 keeps both `DRR_Structural` (AST/regex) and `DRR_LLM` (semantic judge) as a hybrid. Three options going forward:
   - (a) Keep both forever. Cost: every metrics run is two passes; gap is informative but redundant once calibrated.
   - (b) Promote `DRR_Structural` to canonical, demote `DRR_LLM` to spot-check (e.g. run only when gap > 0.25 was observed in the previous run). Cost: depends on a working AST matcher across all proposer claim types.
   - (c) Build a richer **AST-diffing skill** (`agent/skills/ast_diff_skill.py`) that emits typed deltas (`ConvLayerAdded(channels=64, kernel=3)`, `LSTMReplacedByGRU`, etc.). The proposer's `delta_reasoning` claims are then matched in a typed namespace, not regex. Higher upfront cost; eliminates LLM-judge dependency entirely.
   - **Recommendation: (a) for the first chain run, then decide based on the gap distribution.** If the gap is consistently small, move to (b); if claim shapes are too varied for AST matching, defer (c) as a later refactor. Marked here as an explicit open question because option (c) is significant engineering and warrants its own design doc if pursued.

2. **Sliding-window default (`K`)**: I propose `older_attempts` ≤ 8 entries. Too aggressive? Too lax? An iter-30 run has 27 older attempts; we need to pick which are kept (latest 8? top-8 by score? mixed?).
3. **`recent_gate_exhaustions` overlap**: this field is already bounded to 3. Does it stay as a separate field, or fold into `confirmed_lessons` of the ledger? Folding is cleaner; keeping is safer for the gate-exhaustion-specific telemetry already being read elsewhere. Phase 1 measurements should answer whether the field is still load-bearing.
4. **Pricing tier coverage in the bridge**: should `_record_usage` also record an estimated dollar cost per row, or is that a downstream report-builder concern? I lean toward the latter — pricing tiers change; the row should stay raw.
5. **Validator + implementor LLM calls**: are these in scope for Phase 1 telemetry? They emit smaller prompts but they fire many times during repair loops. Recommend yes; cheap to label.
6. **Backwards compat window for the legacy fields**: do we keep `previous_failures: List[str]` as a deprecated field for one release, or remove on land? A V11 forensic re-run might want to read old proposal_iter_*.json files — schema removal would break that.

---

## 7. Out of Scope (explicitly)

- Tokenizer-accurate pre-flight prediction (we emit `chars` for cross-check; we do *not* run a local tokenizer to predict token count before sending). Not worth the dependency churn for the optimization gain.
- Streaming token count (some providers stream; we capture only the final `response.usage`).
- Cross-run comparison dashboard. The `token_usage.jsonl` rows are the building block; a dashboard is a follow-up.
- Tuner planner refactor. `memory_history` resets per-iter, so within-iter growth is a separate problem domain. Phase 1 telemetry will tell us whether the tuner is the next refactor target.

---

## 8. Step-by-Step Commit & Validation Ledger

This section is the executable contract. "Execute Commit #N" maps deterministically to the tasks, tests, and Definition of Done below. §5 step numbers are cross-referenced as "(§5 step X)" throughout. Mark `[x]` only after the Pre-Commit Checklist passes — never sooner.

**Conventions for every commit**:

- **Scope** lists every file touched (new + modified). Files outside Scope must not be touched in the commit.
- **Tasks** is the implementation work, in order. `[ ]` = not done; `[x]` = verified done.
- **Pre-Commit Checklist** has three required entries: a positive test (the new code works), a quantitative metric (the change is measurable), and a negative test (failure modes raise loudly). All three must pass before the commit lands.
- **Definition of Done** is a one-line operator-level statement of what is now true after this commit lands.
- **Out of Scope** is the explicit "don't gold-plate" list — work that belongs in a *later* commit.

---

### Commit 1: Bridge usage capture + token_usage row schema

**Phase**: 1 (Telemetry foundation).
**§5 steps**: 1, 2 (capture portion only), 3 (positive test only).

**Scope**:
- `agent/schemas/telemetry/__init__.py` (new)
- `agent/schemas/telemetry/token_usage.py` (new)
- `agent/llm_bridge.py` (modify `_chat_json`, `generate_text`, `tool_call`, `reflect`)
- `tests/unit/agent/llm_bridge/__init__.py` (new, may already exist)
- `tests/unit/agent/llm_bridge/test_record_usage.py` (new)

**Tasks**:
- [x] Define `TokenUsageRow` Pydantic model with the §1.7 fields. All token counts `Optional[int]`.
  - **Implementation note (2026-05-04)**: split into three Pydantic models in `agent/schemas/telemetry/token_usage.py` for clarity — `TokenCounts` (provider-reported `prompt`/`completion`/`total`, all `Optional[int]`), `TokenUsageChars` (local `system`/`user`/`total`, `int` with `ge=0`), and `TokenUsageRow` (the row itself). All three use `ConfigDict(extra="forbid")` so accidental schema drift is caught at validation. `components: Dict[str, int]` and `extra: Dict[str, Any]` deliberately stay open (no nested model) so callers can supply per-stage breakdowns and free-form context without a schema migration. `iter`, `model`, `provider` are `Optional` because marker rows (e.g. `_iter_flush`) do not have those values; `chars` is required because we always know the local lengths.
  - **Package init**: `agent/schemas/telemetry/__init__.py` re-exports `LLMBridgeContextError`, `TokenCounts`, `TokenUsageChars`, `TokenUsageRow`.
- [x] Define `LLMBridgeContextError(RuntimeError)` exception (used by Commit 2; declared here so the import exists).
  - **Implementation note (2026-05-04)**: subclass of `RuntimeError`. The runner translates it into `sys.exit(2)` (Commit 2 work) — the exception itself is `RuntimeError` per §1.4.2 so existing test harnesses that intercept `BaseException` only via `pytest.raises(RuntimeError)` continue to work; the fail-fast behaviour comes from the runner's top-level handler, not from inheriting `SystemExit` directly. The static AST check (`tests/unit/agent/llm_bridge/test_no_silent_swallow.py`, Commit 2) is the guarantee that no inner `except` swallows it.
- **Smoke test result (2026-05-04)**: hand-run via `.venv/bin/python -c "..."` covered 7 invariants — happy-path round-trip (`model_dump_json` → `model_validate_json` produces identical row, 415 chars), degraded path (`tokens={prompt:None,completion:None,total:None}`), marker row (`label='_iter_flush'`, no model/provider), `extra="forbid"` rejection (ValidationError on unknown root field), `ge=0` rejection (ValidationError on negative `chars.user`), and `LLMBridgeContextError` is a `RuntimeError` subclass. **All 7 checks passed.**
- [x] In `LLMBridge._chat_json` (line 615 region), capture `response.usage`; pass to a new `_record_usage` helper.
  - **Implementation note (2026-05-04)**: `_chat_json` now takes `label: str` and `provider: Optional[str]` kwargs. The body was restructured so that status classification (`"ok"` / `"empty_content"` / `"json_decode_error"` / `"wrong_type"`) happens before the existing retry-sleep branch, and `_record_usage` is invoked once per attempt with `extra={"attempt": N, "status": <classified>}`. The success path (`status == "ok"`) is unchanged in observable behaviour; the only added cost on the success path is one `model_dump_json()` per call when the run-context is bound. When `provider` is omitted, the helper auto-detects it: `self.reflect_provider` if `client is self.reflect_client`, else `self.provider`.
- [x] In `LLMBridge.generate_text` (line 689), capture `response.usage`; pass through.
  - **Implementation note (2026-05-04)**: plain-text mode has no content-retry, so `_record_usage` is invoked once with `extra={"attempt": 0, "status": "ok"}`. Provider passes as `self.provider`.
- [x] In `LLMBridge.tool_call` and `LLMBridge.reflect`, capture `response.usage`; pass through.
  - **Implementation note (2026-05-04)**: `tool_call` records before the `if not message.tool_calls` raise — even a `no_tool_call` response burned tokens, so we still write a row with `extra={"attempt": 0, "status": "no_tool_call"}` before raising `ValueError`. `reflect` flows through `_chat_json` with `label="tuner.reflector"` and `provider=self.reflect_provider`, inheriting the per-attempt telemetry of `_chat_json` for free.
- [x] Implement `_record_usage(label, response, system_prompt, user_prompt, extra=None)`. Silent no-op when `self._token_usage_path is None` (context unset — Commit 2 wires the setter).
  - **Implementation note (2026-05-04)**: signature uses keyword-only args (`*, response, label, system_prompt, user_prompt, model_name, provider, extra=None`) for clarity at every call site. Reads `response.usage.{prompt_tokens,completion_tokens,total_tokens}` via `getattr`, so an SDK shape with no `.usage` attribute (e.g. older client, stream mode) degrades to `TokenCounts()` (all-None) rather than `AttributeError`. Char counts always populated. File appended in `"a"` mode with `buffering=1` (line-buffered) per user directive — concurrent bridge instances in one process do not interleave partial lines. Schema-validation failures and `OSError` on append are logged to stderr and swallowed; **only** `LLMBridgeContextError` (Commit 2) is allowed to propagate. The four run-context fields (`_token_usage_path`, `_iter`, `_run_id`, `_run_name`) are initialized to `None` in `__init__`; setter that populates them is Commit 2.
- [x] Add `label: str = "unlabeled"` kwarg to `generate`, `generate_text`, `tool_call`, `reflect`. Log a warning when default is hit. **Decision (2026-05-04)**: per Q2 confirmation, internal sites `plan()` and `reflect()` will pass `label="tuner.planner"` / `label="tuner.reflector"` immediately in this commit so the V12 baseline run is meaningfully labeled and `chain_log.txt` is clean of internal "unlabeled" warnings. External-node labeling (proposer, interp, validator) remains in Commit 3.
  - **Implementation note (2026-05-04)**: class attribute `_DEFAULT_LABEL = "unlabeled"` plus helper `_warn_default_label(method_name)` prints a one-line `[LLMBridge.<method>] WARNING:` to stderr referencing §1.5 of the design doc. The warning fires per-call (not deduped) so a missed call site is visible in `chain_log.txt` until labeled. `plan()` calls `self.generate(..., label="tuner.planner")`; `reflect()` calls `self._chat_json(..., label="tuner.reflector", provider=self.reflect_provider)`. Both internal call sites short-circuit the warning because they pass an explicit label.
- **Per-attempt telemetry decision (2026-05-04, Q1 confirmed)**: in `_chat_json`'s content-retry loop, `_record_usage` is called **inside** the loop, after `_call_with_retry(...)` returns but before JSON parsing. Each attempt — including JSON-decode failures — produces one row, with `extra={"attempt": N, "status": "ok"|"json_decode_error"|"empty_content"|"wrong_type"}`. This makes provider noise (e.g. deepseek-v4-pro empty-content events) measurable rather than estimated.

**Pre-Commit Checklist**:
- [x] **Positive test**: `pytest tests/unit/agent/llm_bridge/test_record_usage.py -v` — mock the OpenAI client to return `Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)`; assert exactly one valid `TokenUsageRow` is appended to a tmp_path log file with the correct counts and label. **Result (2026-05-04)**: `test_generate_writes_one_row_with_correct_counts` PASSED — counts/label/run_id/iter/components/extra all match expected; row validates through `TokenUsageRow` round-trip.
- [x] **Quantitative metric**: with context unset, calling `generate(...)` produces 0 rows in any log file (the no-op path is verified by `pytest -k test_record_usage_noop_when_unbound`). **Result (2026-05-04)**: `test_record_usage_noop_when_unbound` PASSED — `bridge._token_usage_path` defaults to `None`; after a `generate()` call returning a valid response, `tmp_path` is empty.
- [x] **Negative test**: `pytest -k test_record_usage_handles_missing_usage` — when the mocked response has `usage=None`, the row is still written, with `tokens.prompt=None` and `chars.user > 0` (graceful degradation, not silent skip). **Result (2026-05-04)**: `test_record_usage_handles_missing_usage` PASSED — row written with `tokens={prompt:None,completion:None,total:None}` and char counts populated.
- [x] **Per-attempt quantitative check** (Q1 verification per user directive): a multi-retry `_chat_json` call produces exactly N rows where N = number of attempts, with monotonic `attempt` indices and correct per-attempt `status`. **Result (2026-05-04)**: `test_chat_json_writes_one_row_per_attempt` PASSED — three side-effect responses (bad-JSON, bad-JSON, ok) yielded three rows with `attempt=[0,1,2]`, `status=["json_decode_error","json_decode_error","ok"]`, and prompt-token sequence `[10,11,12]` matching the mock side_effect order. Companion `test_chat_json_writes_row_for_empty_content` covers the `empty_content` status branch.
- [x] **`tool_call` no-tool-call branch**: even when the model declines to invoke a tool, the row is still written before raising `ValueError`. **Result (2026-05-04)**: `test_tool_call_writes_row_then_raises_when_no_tool_call` PASSED — row stamped `extra={"attempt":0,"status":"no_tool_call"}`.
- [x] **Internal-label coverage** (Q2 verification): `plan()` rows are labeled `tuner.planner` and `reflect()` rows are labeled `tuner.reflector`; neither method emits the "unlabeled" stderr warning. **Result (2026-05-04)**: `test_plan_uses_tuner_planner_label` and `test_reflect_uses_tuner_reflector_label` both PASSED — labels correctly stamped, `capsys.readouterr().err` contains no `WARNING: called without label=`.
- [x] **Default-label warn path**: `generate("s", "u")` with no `label=` kwarg writes a row with `label="unlabeled"` AND prints `[LLMBridge.generate] WARNING: called without label=` to stderr. **Result (2026-05-04)**: `test_generate_default_label_emits_warning` PASSED.
- [x] **Regression: existing bridge tests pass unchanged**. **Result (2026-05-04)**: `pytest tests/unit/agent/test_llm_bridge.py tests/unit/agent/test_llm_bridge_singleton.py` — 54 pre-existing tests + 11 new = **65 total PASSED in 0.54s**. The `label=` kwargs all default to `"unlabeled"` so legacy callers (test fixtures) emit a stderr warning but do not break.
- [x] `grep -n "label=" agent/llm_bridge.py` shows the kwarg present on `generate`, `generate_text`, `tool_call`, `reflect` (verified at lines for the four public entry points + `_chat_json` private helper).

**Definition of Done**: every LLMBridge entry point captures `response.usage` and routes it through `_record_usage`; with no setter wired, the helper is a verified no-op; the row schema is validated. **Status (2026-05-04): MET.**

**Out of Scope**: setter logic (Commit 2), call-site labeling (Commit 3), workflow plumbing (Commit 4).

---

### Commit 2: Setter Safety Protocol + fail-fast

**Phase**: 1.
**§5 steps**: 2 (setter portion), 3 (safety tests).

**Scope**:
- `agent/llm_bridge.py` (add `set_run_context`, validation hooks, `_flush_iter_marker`)
- `tests/unit/agent/llm_bridge/test_setter_safety.py` (new)
- `tests/unit/agent/llm_bridge/test_no_silent_swallow.py` (new — AST-grep static check)
- `tools/validate_token_usage_jsonl.py` (new — the leak linter, also used by Commit 5 reports)

**Tasks**:
- [x] Add `set_run_context(workspace, iter, run_name, run_id)` method per §1.4.1. Stores `_token_usage_path`, `_iter`, `_run_name`, `_run_id`, `_set_at_ts`.
  - **Implementation note (2026-05-04)**: keyword-only args (`*, workspace, iter, run_name, run_id`). Body is wrapped in `with self._lock:` per the user's concurrency directive — see "Concurrency mechanism" below. Performs four ordered checks before mutating state: run_id immutability → backwards-iter → workspace existence → workspace writability (`os.access(parent, os.W_OK)`). Only after all four pass does it (a) optionally call `_flush_iter_marker_locked` and (b) update the four primary fields plus `_set_at_ts`.
- [x] Implement run_id immutability check: if `self._run_id is not None and run_id != self._run_id`, raise `LLMBridgeContextError`.
  - **Implementation note (2026-05-04)**: error message includes both old and new run_id and explicitly tells the operator that "a new run_id requires a fresh LLMBridge instance" — telemetry corruption being silent is the failure mode we're guarding against, so the message is verbose by design.
- [x] Implement forward-only iter advancement: same-iter re-entry allowed; backward-iter raises.
  - **Implementation note (2026-05-04)**: `iter == self._iter` permitted (covers stage retries within the same iter — e.g. proposer retried after validator rejection). `iter < self._iter` raises `LLMBridgeContextError`. `iter > self._iter` triggers the flush marker. Negative `iter` raises `ValueError` (programmer bug, not run-time corruption).
- [x] On legitimate iter advancement, call `_flush_iter_marker()` which appends `{"label": "_iter_flush", "iter": <prev>, "marker": "iter_end", ...}`.
  - **Implementation note (2026-05-04)**: implemented as `_flush_iter_marker_locked` (caller-holds-lock convention). Constructs a `TokenUsageRow` with `label="_iter_flush"`, `iter=<prev_iter>`, `tokens=TokenCounts()` (all-None), `chars=TokenUsageChars(0,0,0)`, `extra={"marker": "iter_end"}`; runs `_validate_pre_write_locked` against `prev_iter` so a marker write that would violate any §1.4.1 invariant fails the same way a normal row would. Per the concurrency directive, `f.flush()` is called explicitly before exiting the `open()` block to maintain strict ordering with subsequent `_record_usage` rows.
- [x] In `_record_usage`, add the four per-row checks per §1.4.1 (run_id matches file's first row, iter not less than last logged, path writable, ts monotonic warning).
  - **Implementation note (2026-05-04)**: factored into `_validate_pre_write_locked(target_iter, ts)` for reuse by `_flush_iter_marker_locked`. First-row run_id check is **lazy + cached**: on first invocation, reads the file's first line (if file exists and non-empty); caches the result in `self._first_row_run_id_cache`. Subsequent calls compare against the cache (no disk hit). When the file is missing/empty on first write, the bridge's own run_id is cached (we own row 0). A corrupt first line (invalid JSON) raises `LLMBridgeContextError` because the audit log is already broken. Iter-monotonic check uses `self._last_logged_iter` (in-memory tracker, updated on every successful append). ts-monotonic is a soft warning to stderr — clock skew doesn't justify aborting a run.
- [x] Implement `tools/validate_token_usage_jsonl.py` — one-pass linter: detects rows with `iter=N` after an `_iter_flush` for iter `N`; mismatched run_ids; non-monotonic timestamps. Returns nonzero exit code on any anomaly.
  - **Implementation note (2026-05-04)**: ~150 lines. `lint(path) -> (errors, warnings)` is the importable entrypoint (used by both the CLI `main()` and the unit tests). Validates each row via `TokenUsageRow.model_validate` rather than just JSON-parsing, so schema violations are caught alongside structural issues. Error tags: `[BAD_JSON]` / `[BAD_SCHEMA]` / `[RUN_ID_MISMATCH]` / `[DUPLICATE_FLUSH]` / `[LEAK]`. Warnings (`[WARN]`) are non-fatal — non-monotonic ts only. CLI: `python tools/validate_token_usage_jsonl.py <path>` returns 0/1; `--quiet` suppresses the success line for use in CI.

**Concurrency mechanism (per user directive 2026-05-04)** — documented here as required:

A `threading.Lock` (plain, not RLock) is created in `LLMBridge.__init__` as `self._lock`. Two regions enter the lock:

1. **`set_run_context` body** — entire body after the cheap `iter < 0` ValueError check is wrapped in `with self._lock:`. The lock holds across run_id check → backwards-iter check → workspace checks → optional `_flush_iter_marker_locked` → state mutation. This makes the "state-check / iter-flush write / state-update" sequence atomic with respect to any concurrent `_record_usage` caller.
2. **`_record_usage` post-no-op block** — after the early-return on unbound state, the lock holds across `_validate_pre_write_locked` → row construction → `open()` + `f.write()` + `f.flush()` → `self._last_logged_iter` / `self._last_ts` update. Without this, a concurrent `set_run_context` advancing iter could write a flush marker between this method's pre-write check and its actual append, producing a leak.

Helpers `_flush_iter_marker_locked` and `_validate_pre_write_locked` are named with the `_locked` suffix as a convention: the caller is required to hold `self._lock`. This avoids the cost of RLock (re-entrance support) without sacrificing correctness — there are no call paths that re-enter the lock.

Atomicity of small JSONL appends is reinforced by `buffering=1` (line buffering) plus an explicit `f.flush()` before the `with open()` block exits, both per the directive. This guarantees that a row landing on disk is the complete row, never a partial line — even under SIGINT mid-write.

**Pre-Commit Checklist**:
- [x] **Positive test**: `pytest tests/unit/agent/llm_bridge/test_setter_safety.py::test_setter_happy_path` — calling `set_run_context` then `_record_usage` writes one row; advancing `iter` writes the prior `_iter_flush` marker first; the linter passes the resulting file. **Result (2026-05-04)**: PASSED — bound state correct, row written with `iter=0` and `run_id="r-001"`; `test_setter_advance_iter_writes_flush_marker` separately verifies that `set_run_context(iter=4)` after `iter=3` writes a flush marker for `iter=3` with `extra={"marker":"iter_end"}` and zeroed counts.
- [x] **Quantitative metric**: in a 5-iter mock run with 12 calls/iter, the JSONL contains exactly `60 + 4` rows (4 `_iter_flush` markers between iters; no flush after the final iter); linter exit code is 0. **Result (2026-05-04)**: `test_5_iter_quantitative_and_linter_passes` PASSED — observed exactly 60 data rows + 4 flush rows (iters [0,1,2,3]); no flush after iter=4; `tools.validate_token_usage_jsonl.lint(path)` returned `errors=[]`.
- [x] **Negative test (run_id)**: `pytest -k test_setter_rejects_run_id_mutation` — calling `set_run_context` twice with different run_ids raises `LLMBridgeContextError`; the second call writes nothing. **Result (2026-05-04)**: PASSED — `bridge._run_id` remains `"r-A"` after the rejected `"r-B"` call.
- [x] **Negative test (backwards iter)**: `pytest -k test_setter_rejects_backwards_iter` — `set_run_context(iter=5)` then `set_run_context(iter=3)` raises. **Result (2026-05-04)**: PASSED — `LLMBridgeContextError` matches `"backwards iter"`; `bridge._iter` stays at `5`.
- [x] **Negative test (file-level run_id)**: `pytest -k test_record_usage_aborts_on_runid_mismatch` — pre-seed a JSONL with run_id=`A`; bridge with run_id=`B` raises on first write; file is unchanged. **Result (2026-05-04)**: PASSED — `LLMBridgeContextError` matches `"run_id mismatch"`; pre-seeded file has exactly 1 row, run_id=`OTHER-RUN`, unmutated.
- [x] **Negative test (no silent swallow)**: `pytest tests/unit/agent/llm_bridge/test_no_silent_swallow.py` — AST-greps `agent/llm_bridge.py` for any `except LLMBridgeContextError`; assertion fails if any are present. **Result (2026-05-04)**: 3/3 PASSED — `test_bridge_path_resolves` (sanity), `test_no_except_llm_bridge_context_error_in_bridge` (direct AST-grep), and `test_bare_except_does_not_swallow_context_error` (softer check that bare/`Exception`-typed `except` blocks don't enclose `_record_usage` / `set_run_context` / `_validate_pre_write_locked` / `_flush_iter_marker_locked` calls).
- [ ] **Negative test (subprocess abort)**: `pytest -k test_runner_aborts_on_runid_mismatch` — spawn a subprocess pointed at a workspace with a conflicting run_id; assert exit code 2 and `[FATAL] LLMBridgeContextError` in stderr. **Deferred (2026-05-04)**: this test depends on `run_exploration_adaptive.py` installing a top-level `LLMBridgeContextError → sys.exit(2)` handler, which is part of Commit 4's runner scope (Commit 2 explicitly excludes the runner from its `Scope`). **Moved to Commit 4's checklist** — see the deferred item there. The bridge's *own* contract (it raises pre-write, never writes the corrupting row) is covered by `test_record_usage_aborts_on_runid_mismatch` above.
- [x] **Negative test (linter — leak)**: hand-craft a JSONL with iter=4 row appearing after `_iter_flush` for iter=4; `tools/validate_token_usage_jsonl.py` returns nonzero with the leak location. **Result (2026-05-04)**: `test_linter_detects_post_flush_leak` PASSED — `lint()` returned an error tagged `[LEAK]`; CLI `main([str(log)])` returned exit code `1`. Companion `test_linter_detects_run_id_mismatch` covers `[RUN_ID_MISMATCH]`; `test_linter_warns_on_non_monotonic_ts` covers the warn-only ts path (errors empty, warnings non-empty).
- [x] **Concurrency check (per user directive)**: 8 threads racing on `set_run_context(iter=0)` with the bridge already at `iter=0` produce zero `_iter_flush` markers (strict-greater-than guard) and no exceptions. **Result (2026-05-04)**: `test_setter_thread_safety_no_duplicate_flush` PASSED — 8 data rows, 0 flush markers, no captured exceptions.
- [x] **Regression**: full bridge test bundle (`tests/unit/agent/llm_bridge/`, `tests/unit/agent/test_llm_bridge.py`, `tests/unit/agent/test_llm_bridge_singleton.py`). **Result (2026-05-04)**: **92 PASSED in 0.59s** (11 Commit 1 + 13 Commit 2 setter + 3 AST guard + 65 pre-existing).

**Definition of Done**: a corrupted run_id or backwards iter aborts the process with exit code 2 before any row reaches disk; the linter detects post-hoc leaks; static check guarantees no `except LLMBridgeContextError` exists in production code. **Status (2026-05-04): bridge-side MET; the runner-side `exit(2)` is delivered by Commit 4. Bridge guarantee: every code path that could corrupt the audit log raises `LLMBridgeContextError` *before* any append, verified by the negative tests above. Linter is implemented and detects all three documented anomaly classes. AST static check has zero violations on the bridge module.**

**Out of Scope**: changing the runner's existing exit-code conventions (the brake's `exit(1)` is preserved); pricing computation (out of doc scope); the runner's top-level `LLMBridgeContextError → sys.exit(2)` handler (deferred to Commit 4 along with the subprocess test that exercises it).

---

### Commit 3: Component pre-assembly hook + LLM call labels

**Phase**: 1.
**§5 steps**: 4, 5, 6.

**Scope**:
- `agent/llm_bridge.py` (thread `components: Optional[Dict[str, int]]` kwarg through `_record_usage`, `_chat_json`, `generate`, `generate_text`, `tool_call`)
- `nodes/ml_model_proposal_agent.py` (add `_audit_proposer_components` + `_extract_prior_stage_keys`, label all 6 call sites, pass `components=` on the 4 staged sites)
- `nodes/ml_model_implementor.py` (label 3 call sites — discovered during the static AST sweep; not in original scope but required for the "no `label=unlabeled`" gate)
- `nodes/result_interpretation_agent.py` (label per_model + synthesis + dedup calls)
- `nodes/ml_code_validator_agent.py` (label code-review call)
- `tests/unit/agent/ml_model_proposal_agent/test_audit_components.py` (new — placed under existing proposer test dir per project convention)
- `tests/unit/agent/llm_bridge/test_all_calls_labeled.py` (new — permanent AST regression guard)
- Tuner is unchanged: `LLMBridge.plan()` and `LLMBridge.reflect()` already pass `label="tuner.planner"` / `label="tuner.reflector"` internally (landed in Commit 1).

**Tasks**:
- [x] Add `components: Optional[Dict[str, int]] = None` kwarg to `_record_usage`, `_chat_json`, `generate`, `generate_text`, `tool_call`. Caller-supplied dict lands in `row.components` (the schema's dedicated field) — `extra` continues to carry the retry-status payload (`{"attempt": N, "status": ...}`) untouched. **Decision (2026-05-04, Q1 confirmation)**: §1.3's "passed as `extra`" wording was imprecise; the schema split between `components` and `extra` is the real contract.
- [x] Implement `_audit_proposer_components(*, inp: ProposalInput, accumulated, agent_cards_block, expert_context_block, vocab_block, system_prompt, stage_name) -> dict` per §1.3. Returns `{stage_name, components: {9 keys}, total_chars}`. `inp` and `stage_name` were added to the original 5-arg signature (Q3 confirmation) so the function has direct access to `inp.previous_failures` and `inp.recent_gate_exhaustions`. Helper `_extract_prior_stage_keys(accumulated)` partitions stage outputs from input keys via the `_PROPOSER_INPUT_KEYS` set.
- [x] Call the hook before each `self.bridge.generate(...)` invocation in `ml_model_proposal_agent.py` and pass result via `components=` (NOT `extra=`):
  - **Staged loop (line 1011/1014 region)**: `label=f"proposer.{stage.name}"` resolves to `proposer.comparison` / `proposer.causal_reasoning` / `proposer.proposing` depending on which stage runs.
  - **Boldness retry**: `label="proposer.causal_reasoning"`, components recomputed from current `accumulated`.
  - **Proposing stage**: `label="proposer.proposing"`. Audit hook is called with `vocab_block=""` to mirror the actual user prompt assembly (proposing user prompt does NOT append the vocab block — only `agent_cards` + `expert_context`).
- [x] Label the legacy 2-call path: `label="proposer.legacy_reasoning"` (line 780) and `label="proposer.legacy_commit"` (line 797). Components is omitted (the legacy path uses `_build_reasoning_prompt` / `_build_commit_prompt`, not `_render_stage_user_prompt`, so the 9-key breakdown does not apply). Q2 confirmation: visibility over granularity for deprecated code.
- [x] Add `label="interpretation.per_model"` (line 714), `"interpretation.synthesis"` (line 820), `"interpretation.dedup"` (line 1179) to `result_interpretation_agent.py`.
- [x] Add `label="validator.code_review"` (line 544) to `ml_code_validator_agent.py`.
- [x] Add `label="implementor.reasoning"` / `"implementor.code"` / `"implementor.repair"` to `ml_model_implementor.py` (lines 751/756/769). The implementor was not in the original §1.5 table; discovered via the AST sweep and added because it is a node that calls the bridge. §1.5 table updated to reflect this.
- [x] Tuner labels: no change required. `brain.plan()` and `brain.reflect()` already pass labels internally (Commit 1).

**Implementation Details (2026-05-04)**:

- **Bridge plumbing**: `components` is keyword-only on every public method; threaded as `components=components` from each entry point down to `_record_usage`. The previous `components={}` hard-code in the row construction is replaced with `components=components or {}` so non-proposer calls produce empty dicts (schema-valid, distinguishable in downstream reports).
- **Audit hook locality**: `_audit_proposer_components` lives next to `_render_stage_user_prompt` in `ml_model_proposal_agent.py`. It computes the same `cleaned` interpretation summary (drops `per_model_score_tables` to mirror the prompt assembly) and uses `build_candidate_markdown_block` for the markdown count — so the audit's char numbers reflect what the LLM actually saw, not a separate pre-merge computation. The `_format_recent_gate_exhaustions_block` helper at module level is reused for the `recent_gate_block` count.
- **`_extract_prior_stage_keys`**: a small helper that returns `{k: v for k, v in accumulated.items() if k not in _PROPOSER_INPUT_KEYS}`. The fixed `_PROPOSER_INPUT_KEYS = {candidates, non_candidates_overview, interpretation_summary, existing_model_types, previous_failures}` set defines what counts as input vs. stage output — anything else is attributed to `prior_stage_outputs`.
- **`__init__.py` test compat**: `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py::_llm_dispatch` was updated to accept `**kwargs` so the new `label=` / `components=` kwargs from the bridge call sites no longer raise `TypeError` against the mock side_effect. No other test fixture changes were required (proposer/implementor mocks already used `*a, **kw` patterns).

**Pre-Commit Checklist**:
- [x] **Positive test**: `pytest tests/unit/agent/ml_model_proposal_agent/test_audit_components.py` — synthetic `accumulated` dict; asserts all 9 component keys present in the returned breakdown; asserts `total_chars == sum(components.values())` (the original "+ len(system_prompt)" wording was a doc bug — `system_prompt` is already one of the 9 components, so it would double-count). **Result: 5/5 PASS.**
- [x] **Quantitative metric**: AST sweep over `nodes/**/*.py` finds **0** `bridge.{generate,generate_text,tool_call}` calls without `label=` kwarg. Verified by the new permanent regression guard `tests/unit/agent/llm_bridge/test_all_calls_labeled.py`.
- [x] **Negative test**: `test_audit_components_handles_empty_blocks` — when `vocab_block` / `agent_cards_block` / `expert_context_block` / `system_prompt` are empty strings, the breakdown still has all 9 keys present (value 0 for the empty blocks; `interpretation_json` and `prior_stage_outputs` collapse to `len("{}") == 2`). **Result: PASS.**
- [x] **Static check (permanent)**: `tests/unit/agent/llm_bridge/test_all_calls_labeled.py::test_every_bridge_call_in_nodes_has_label_kwarg` walks every `<expr>.bridge.{generate,generate_text,tool_call}` call under `nodes/` and asserts `label=` is present. Q4 confirmation: chosen as a permanent regression guard rather than a one-off shell command, mirroring the `test_no_silent_swallow.py` pattern from Commit 2. **Result: 2/2 PASS.**
- [x] **Bridge bundle regression**: `pytest tests/unit/agent/llm_bridge/` — Commit 2's setter-safety + no-silent-swallow tests still pass with the new `components` kwarg threaded through. **Result: all bridge tests PASS.**
- [x] **Affected-node bundles regression**: `pytest tests/unit/agent/{ml_model_proposal_agent,result_interpretation_agent,ml_code_validator_agent,ml_model_implementor}/` — the new label/components kwargs do not break existing proposer/interp/validator/implementor unit tests. **Result: 781/781 PASS** (full suite of the 5 affected dirs including the 7 new C3 tests).

**Definition of Done**: every proposer LLM call writes a 9-key component breakdown to `token_usage.jsonl.components`; every other node's LLM call has a stable label in `token_usage.jsonl.label`; no call site under `nodes/` emits `label="unlabeled"` (verified by AST regression guard). **Status (2026-05-04): MET.**

**Out of Scope**: workflow's `set_run_context` call (Commit 4); the V12 baseline run (Commit 5).

---

### Commit 4: Workflow plumbing + per-iter rollup

**Phase**: 1.
**§5 steps**: 7, 8, 9.

**Scope**:
- `workflows/model_exploration.py` (call `bridge.set_run_context` per iter)
- `run_exploration_adaptive.py` (generate `run_id`; emit `[TOKEN_ITER]` rollup)
- `tests/integration/runner/test_token_log_iter_rollup.py` (new — pseudo mode)

**Design decisions (locked before code)**:
- **Q1 — `run_workflow` signature**: Option A — flat `chain_run_name: str | None = None` and `run_id: str | None = None` kwargs (matches existing kwarg density; no new dataclass).
- **Q2 — `run_id is None` semantics**: Option B — workflow defaults `None` and silently skips `set_run_context` (preserves the dozens of existing pseudo-mode tests). The production runner (`run_exploration_adaptive.py`) is the *single* enforcement point: it always generates a `run_id`. Therefore the `test_workflow_aborts_on_unset_run_id` negative test from the original spec is **superseded** — the contract is "runner enforces presence", not "workflow rejects None".
- **Q3 — `[TOKEN_ITER]` emission point**: Option A — runner emits after each `_run_one_iter` returns. In-process multi-iter mode (legacy/ad-hoc) gets no rollup; chain mode (production) is fully covered.
- **Q4 — Subprocess test mechanism**: Option A — purpose-built harness `tests/integration/runner/_runid_mismatch_harness.py` invoked via real `python` subprocess. No monkey-patching of internals.

**Tasks**:
- [x] Generate `run_id` once at runner startup using the §1.4.1 format (`{run_name}-{utc_ts}-{pid}`).
  - **Implementation**: `_generate_run_id(run_name)` in `run_exploration_adaptive.py` uses `datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")` (timezone-aware; avoids the `datetime.utcnow()` deprecation). The pid disambiguates concurrent runs from the same shell (e.g. parallel screens).
  - **Call site**: `main()` invokes it once after `args.workspace` is resolved and prints `[TOKEN] run_id = <id>` so the chain_log records the immutable identifier on its first line.
- [x] Thread `run_id` from runner into `workflows/model_exploration.py`.
  - **Implementation**: `_run_one_iter(args, workspace, llm_config, advice, source_paths, iteration, *, run_id)` now takes `run_id` as a keyword-only argument and forwards it together with `chain_run_name=args.run_name` into `run_workflow(...)`. `run_workflow` itself gains the matching kwargs `chain_run_name: str | None = None, run_id: str | None = None` (Q1 Option A — flat density preserved).
- [x] At the top of each iter in the workflow, call `bridge.set_run_context(workspace, iter, run_name, run_id)` for every bridge instance in scope (proposer, tuner, interpreter, validator).
  - **Implementation**: a local closure `_bind_iter_context(agent)` inside the iter loop dispatches by duck-typing — for the four direct-bridge agents (`ResultInterpretationAgent`, `MLModelProposalAgent`, `MLModelImplementor`, `MLCodeValidatorAgent`) it calls `agent.bridge.set_run_context(...)`; for the tuner (which builds its bridge lazily inside `run()`) it calls `agent.set_run_context(...)` and the tuner stores the kwargs in `self._pending_run_context`, applying them after `brain` is constructed.
  - **Tuner change**: `nodes/ml_hyperparameter_tune_agent.py` gained `set_run_context(*, workspace, iter, run_name, run_id)` plus a 4-line block that propagates the pending kwargs onto `brain` once it exists. This keeps the *contract* uniform across all 5 agents while respecting the tuner's lazy-construction internal.
  - **Backward compat**: when `chain_run_name is None or run_id is None`, `_bind_iter_context` returns early — bridges remain in their silent no-op mode (Q2 Option B). The dozens of existing pseudo-mode tests need no changes.
- [x] At iter end in the runner, parse `token_usage.jsonl` rows for the just-finished iter; emit `[TOKEN_ITER] iter=NN calls=K total_tok=… (proposer=… tuner=… interp=…)  cumulative_total=…` via the existing `_TeeStream` so it tees into `chain_log.txt`.
  - **Implementation**: `_emit_token_iter_rollup(workspace, iteration, cumulative_total_in)` reads the JSONL line by line, filters rows whose `iter` matches `iteration` (skipping `_iter_flush` synthetic markers), groups totals by `label.split('.', 1)[0]` (so `proposer.comparison` and `proposer.proposing` collapse into a single `proposer` bucket), prints exactly one summary line, and returns `cumulative_total_in + iter_total` so the caller carries the running sum across iters.
  - **Robustness**: `OSError` on `open()` returns `cumulative_total_in` unchanged (don't crash a successful iter on a transient FS hiccup); malformed JSON lines are individually skipped via `except json.JSONDecodeError` so a single bad row doesn't lose the whole rollup.
- [x] Install a top-level `LLMBridgeContextError` handler in the runner (deferred from Commit 2 per §1.4.2): on catch, emit `[FATAL] LLMBridgeContextError: <reason> — aborting run to prevent telemetry corruption.` to stderr + chain_log.txt, then call `sys.exit(2)`. The exit code is intentionally distinct from the consecutive-failure brake's `exit(1)`.
  - **Implementation**: `from agent.schemas.telemetry import LLMBridgeContextError` at module top; the iter loop in `main()` is wrapped in `try: ... except LLMBridgeContextError as e: print("[FATAL] ...", file=sys.stderr); sys.exit(2)`. Because the runner already tees stdout/stderr into `chain_log.txt` via `_TeeStream`, the `[FATAL]` line lands in the chain log automatically — no double-write needed.

**Pre-Commit Checklist**:
- [x] **Positive test (focused unit-style coverage of the rollup helper)**: `pytest tests/integration/runner/test_token_log_iter_rollup.py` — 7 tests covering the `_generate_run_id` format, `_emit_token_iter_rollup` aggregation by node prefix, missing-file handling, cumulative carry across calls, and malformed-row resilience. **Result: 7 passed in 1.58s** (2026-05-04). Note: the original spec ("one-iter pseudo run; ≥4 rows; `_iter_flush` marker; one `[TOKEN_ITER]` line in captured chain_log") would require booting the full pseudo workflow and capturing tee'd stdout; the focused tests instead exercise the rollup function directly with seeded JSONL fixtures, which is the load-bearing logic. The end-to-end "rollup line lands in `chain_log.txt`" assertion is naturally exercised by the Commit 5 V12 chain run.
- [ ] **Quantitative metric**: in a 3-iter pseudo run, `chain_log.txt` contains exactly 3 `[TOKEN_ITER]` lines; their per-node breakdowns sum to the file's per-row totals (verified by `tools/validate_token_usage_jsonl.py --rollup-check`). **Deferred to Commit 5** — the linter `tools/validate_token_usage_jsonl.py --rollup-check` does not yet exist (Commit 5 builds it alongside `tools/build_token_baseline_report.py`); the V12 chain itself is the natural fixture for this metric.
- [x] ~~**Negative test**: `pytest -k test_workflow_aborts_on_unset_run_id`~~ — **Superseded by Q2 Option B.** With `run_id=None` defaulted in `run_workflow`, the workflow silently skips `set_run_context` rather than raising; enforcement lives in the production runner. The "programming error if run_id is missing" framing now applies only to `run_exploration_adaptive.py::main`, where `_generate_run_id` is unconditional.
- [x] **Negative test (subprocess abort, deferred from Commit 2)**: `pytest -k test_runner_aborts_on_runid_mismatch` — spawn a subprocess runner pointed at a workspace whose `token_usage.jsonl` already has a different run_id; assert exit code 2 and `[FATAL] LLMBridgeContextError` in stderr. This validates the §1.4.2 end-to-end contract (bridge raises → runner translates → `sys.exit(2)`).
  - **Implementation**: `tests/integration/runner/_runid_mismatch_harness.py` is a 90-line standalone subprocess that imports the real `LLMBridge`, calls `set_run_context(...)` with a fresh `run_id`, then calls `_record_usage(...)` with a `SimpleNamespace` SDK-shape response. The first-row check fires inside the bridge, raises `LLMBridgeContextError`, the harness's top-level `except` mirrors the production handler exactly (`[FATAL] LLMBridgeContextError: ... — aborting run to prevent telemetry corruption.` + `sys.exit(2)`). The test seeds `token_usage.jsonl` with a row carrying `"run_id": "PRIOR-RUN-ID-DIFFERENT"`, spawns the harness with `"FRESH-RUN-ID"` as argv[2], and asserts `proc.returncode == 2`, `"[FATAL]" in proc.stderr`, and `"LLMBridgeContextError" in proc.stderr`. **Result: PASSED in 1.58s** (2026-05-04, included in the 7-test suite above).

**Definition of Done**: every iter of a workflow run emits one `[TOKEN_ITER]` rollup line into `chain_log.txt` and a clean stretch of rows in `token_usage.jsonl`; the linter passes. **Status (2026-05-04)**: code path is in place and unit-verified; the end-to-end "one rollup per iter in `chain_log.txt`" assertion will be observed for the first time in the Commit 5 V12 chain run, where it doubles as the input to the baseline report.

**Out of Scope**: the V12 baseline run + report (Commit 5); the `tools/validate_token_usage_jsonl.py --rollup-check` linter (built in Commit 5 alongside `tools/build_token_baseline_report.py`).

---

### Commit 5: V12 baseline run + Top-3 Bloat Report (Gate G1)

**Phase**: 1.
**§5 steps**: 10, 11.

**Scope**:
- `tools/build_token_baseline_report.py` (new — aggregates `token_usage.jsonl` into the report)
- `reports/v12_token_baseline.md` (new — output artifact)
- `reports/v12_top3_bloat.md` (new — output artifact)

**Tasks**:
- [ ] Run a V12 chain (settings matching V11 baseline: `openai_tiered_v1.json` routing, 5+ iters minimum). The run is the deliverable, not a code change.
- [ ] Implement `tools/build_token_baseline_report.py`: reads `token_usage.jsonl` from the V12 workspace; emits §1.9.1 tables (per-iter totals, top-3 bloat per iter, aggregate growth verdicts).
- [ ] Write `reports/v12_token_baseline.md`: real per-call token counts, per-iter trend, comparison against the §12-audit estimates.
- [ ] Write `reports/v12_top3_bloat.md`: tables per §1.9.1; ends with one of the three §1.9.2 verdicts.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `python tools/build_token_baseline_report.py --workspace <v12-ws>` produces both reports without error; both render in markdown without broken tables.
- [ ] **Quantitative metric**: for the 5-iter run, the report shows a clean per-iter token sparkline; the linter on the JSONL returns 0 anomalies.
- [ ] **Negative test**: run the report generator against a workspace whose `token_usage.jsonl` has been hand-corrupted (drop an `_iter_flush` marker). Assert the generator refuses to publish — emits "AUDIT LOG CORRUPTION DETECTED" and exits nonzero. We never publish numbers from a corrupted log.
- [ ] **Verdict recorded**: §1.9.2 verdict is written explicitly at the top of `reports/v12_top3_bloat.md` — Confirmed Proposer / Pivot Tuner / Pivot Other / Sanity Floor.

**Definition of Done (Gate G1)**: real V12 baseline numbers exist; the verdict is recorded; the team has explicitly chosen one of the four branches (continue to Commit 6, pivot, or stop).

**Decision branch**:
- Verdict = "Confirmed Proposer Hypothesis" → proceed to Commit 6.
- Verdict = "Pivot Required — Tuner" or "Pivot Required — Other" → **STOP**. The current §2 design is shelved; a new design pass begins.
- Verdict = Sanity Floor tripped → **DEFER**. Re-run at iter 15 and re-evaluate.

**Out of Scope**: any Phase 2 work.

---

### Commit 6: ErrorSignatureSkill — extract + render

**Phase**: 2 (Dehydration surgery; only after Gate G1 passes).
**§5 step**: 12.

**Scope**:
- `agent/skills/error_signature_skill.py` (new)
- `tests/unit/agent/skills/test_error_signature.py` (new)

**Tasks**:
- [ ] Implement `ErrorSignature` dataclass per §2.2 (fields: `error_type`, `short_message`, `last_frames`, `failure_class`).
- [ ] Implement `extract(traceback_text, max_frames=5) -> ErrorSignature` with heuristic classification:
  - `failure_class` mapping: VRAM strings → `"vram"`, NaN/grad strings → `"training"`, validator errors → `"validation"`, etc.
  - `last_frames` filters traceback to user-code frames (skip site-packages / torch internals).
- [ ] Implement `render(sig) -> str` returning a 4-line markdown block.
- [ ] Sanity unit tests with synthetic tracebacks for each `failure_class`.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/skills/test_error_signature.py` — for each of the 5 classifier classes, a synthetic traceback is correctly classified and rendered.
- [ ] **Quantitative metric**: across the 5 synthetic samples, all rendered signatures are `< 600` chars; median compression ratio (rendered / raw) `< 0.10`.
- [ ] **Negative test**: `pytest -k test_extract_unknown_does_not_silently_succeed` — when `extract` is given an unparseable input, it returns `ErrorSignature(failure_class="unknown", ...)` *and* logs a warning; downstream callers can detect "unknown" and decide whether to keep raw text instead.

**Definition of Done**: the skill can dehydrate a synthetic traceback in five known classes; the unknown path is explicitly flagged.

**Out of Scope**: the V11 forensic test (Commit 7); ledger schema (Commit 8).

---

### Commit 7: Offline Forensic Benchmark (Gate G2)

**Phase**: 2.
**§5 step**: 13.

**Scope**:
- `tests/forensic/__init__.py` (new)
- `tests/forensic/conftest.py` (new — fixtures pointing at `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v11_0503/...`)
- `tests/forensic/test_v11_spectral_u_signature.py` (new)

**Tasks**:
- [ ] Implement `_load_v11_spectral_u_failure_text()` fixture: reads `run_output_iter_002.json` + relevant `chain_log` slice; concatenates raw failure text.
- [ ] Implement the 6 §2.8.2 assertions verbatim.
- [ ] Add `@pytest.mark.forensic` marker; register in `conftest.py` so it runs only when `--run-forensic` is passed (skipped by default to keep CI quick).

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/forensic/test_v11_spectral_u_signature.py --run-forensic` passes all 6 assertions on the V11 spectral_u_operator_lite forensic data.
- [ ] **Quantitative metric**: `Cr = len(rendered) / len(raw_log) < 0.10`; rendered length `< 600` chars; both reported by the test (as test-output prints, not just asserts).
- [ ] **Negative test**: hand-construct a generic Python `RuntimeError` traceback with no FFT or U-Net references; assert that running the benchmark assertions against *that* traceback fails (proves the assertions actually require the FFT/U-Net mention, not just any signature).

**Definition of Done (Gate G2)**: `ErrorSignatureSkill` extracts the V11 root cause (VRAM + FFT/U-Net) deterministically. If this commit's tests fail, **Commit 8 cannot start** — return to Commit 6 and improve `extract` until G2 passes.

**Out of Scope**: ledger schema (Commit 8) — schema work begins only after this gate.

---

### Commit 8: Ledger schemas

**Phase**: 2.
**§5 step**: 14.

**Scope**:
- `agent/schemas/proposal.py` (add `EvolutionaryLedger`, `PredecessorEntry`, `OlderAttemptSummary`, `DeltaReasoning`; add `ProposalInput.ledger`, `ProposalOutput.delta_reasoning`)
- `tests/unit/agent/schemas/test_evolutionary_ledger.py` (new)

**Tasks**:
- [ ] Define the 4 new Pydantic models per §2.6 with bounded list lengths enforced by validators.
- [ ] Add `ProposalInput.ledger: Optional[EvolutionaryLedger] = None` (backward compat).
- [ ] Add `ProposalOutput.delta_reasoning: Optional[DeltaReasoning] = None` initially; tighten to required in Commit 12 cleanup after the chain run validates.
- [ ] Update `ProposalOutput`'s docstring to reference the new field.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/schemas/test_evolutionary_ledger.py` — construct a valid `EvolutionaryLedger`; round-trip through `model_dump()` / `model_validate()` matches.
- [ ] **Quantitative metric**: a valid serialized ledger with predecessor + 8 older_attempts + 6 confirmed_lessons + 4 open_bottlenecks renders to `≤ 4 KB` JSON (proves the schema's natural size matches the design intent).
- [ ] **Negative test**: `pytest -k test_ledger_rejects_oversized_lists` — constructing a ledger with `older_attempts` length > K raises ValidationError; constructing `DeltaReasoning` with `what_we_change` length > 3 raises.

**Definition of Done**: ledger and delta-reasoning schemas exist and validate; existing proposer code paths still work because new fields are Optional.

**Out of Scope**: helpers (Commit 9); workflow assembly (Commit 10); rendering (Commit 11).

---

### Commit 9: Truncation + sliding-window helpers

**Phase**: 2.
**§5 step**: 15.

**Scope**:
- `nodes/proposal_helpers.py` (add `truncate_score_tables`, `apply_source_window`)
- `tests/unit/agent/proposal/test_truncate_score_tables.py` (new)
- `tests/unit/agent/proposal/test_source_window.py` (new)

**Tasks**:
- [ ] Implement `truncate_score_tables(tables, top_n) -> (truncated, omitted_names)` per §2.3.
- [ ] Implement `apply_source_window(candidates, full_source_for=1, summary_for_older=True) -> list[dict]` per §2.4.
- [ ] Both helpers must be pure (no I/O, no global state) so tests are deterministic.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/proposal/test_truncate_score_tables.py tests/unit/agent/proposal/test_source_window.py` — synthetic 30-model dict truncates to 5 by best_score; older candidates keep only one summary line.
- [ ] **Quantitative metric**: with 30 models in the input dict and `top_n=5`, JSON-serialized truncated output is `≤ 8 KB` (matches §4 metric #4 target).
- [ ] **Negative test**: `pytest -k test_truncate_handles_empty_dict` — empty input returns empty output and `omitted_names=[]`; no IndexError. `pytest -k test_window_rejects_invalid_iter_offset` — candidate with `iter_offset=-1` raises.

**Definition of Done**: both helpers compress as designed and refuse malformed inputs.

**Out of Scope**: wiring helpers into the workflow (Commit 10); rendering (Commit 11).

---

### Commit 10: Ledger construction in workflow + protocol

**Phase**: 2.
**§5 step**: 16.

**Scope**:
- `core/resume.py` (build older_attempts summary + confirmed_lessons from disk)
- `workflows/model_exploration.py` (replace `accumulated_physical_rejections` etc. with ledger construction; lines 916-954 region)
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` (populate `ProposalInput.ledger`)
- `tests/unit/agent/protocols/test_ledger_assembly.py` (new)

**Tasks**:
- [ ] In `core/resume.py`, parse all prior `interpretation_iter_*.json` and `run_output_iter_*.json` to build `older_attempts: list[OlderAttemptSummary]` and `confirmed_lessons: list[str]`.
- [ ] Use `ErrorSignatureSkill.extract(...)` (Commit 6) to dehydrate the predecessor's failure into `PredecessorEntry.error_signature`.
- [ ] Use `truncate_score_tables` (Commit 9) before placing tables into the ledger / interpretation summary.
- [ ] Use `apply_source_window` (Commit 9) when building candidate dicts handed to the proposer.
- [ ] Update the protocol to pass the assembled `ledger` into `ProposalInput`.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/protocols/test_ledger_assembly.py` — synthetic disk fixture with 5 prior iters; assert ledger.predecessor matches iter 5; older_attempts has 4 entries; sizes within bounds.
- [ ] **Quantitative metric**: assembled ledger from a 10-iter fixture is `≤ 4 KB` serialized; predecessor source code is full; older_attempts each ≤ 280 chars (one_line_idea ≤ 140 + failure_reason ≤ 140).
- [ ] **Negative test**: `pytest -k test_assembly_aborts_on_corrupt_disk` — when one of the prior interpretation files is malformed JSON, the assembly raises a clear error rather than silently dropping the iter (data quality is load-bearing for the ledger; we don't paper over corruption).

**Definition of Done**: a populated `EvolutionaryLedger` is built from real disk artifacts and reaches `ProposalInput`; helpers are exercised end-to-end.

**Out of Scope**: rendering in the proposer prompt (Commit 11).

---

### Commit 11: Proposer rendering + Delta Reasoning prompt + Trap Test (Gate G3)

**Phase**: 2.
**§5 steps**: 17, 18, 19, 20, 21.

**Scope**:
- `nodes/ml_model_proposal_agent.py` (render ledger; remove flat `previous_failures` block when `inp.ledger is not None`; legacy path preserved as fallback)
- `agent/prompt_templates/proposal/comparison_stage*.md` (×3 — declare `delta_reasoning` schema reference)
- `agent/prompt_templates/proposal/causal_reasoning_stage*.md` (×3 — required Delta Reasoning block)
- `agent/prompt_templates/proposal/proposing_stage*.md` (×3 — output-schema reference for `delta_reasoning`)
- `tests/unit/agent/proposal/test_iter2_lesson_present_in_iter10_prompt.py` (new — plumbing-only Trap unit test)
- `tests/integration/proposer/test_long_term_wisdom_trap.py` (new — real-API Trap test)
- `tests/integration/nodes/test_ml_model_proposal_agent_ledger.py` (new — Tier-1 integration)

**Tasks**:
- [ ] Add ledger rendering helpers in `ml_model_proposal_agent.py` (replaces the flat `previous_failures` rendering at line 644-648 *when* `inp.ledger is not None`; legacy path retained otherwise per §2.6 fallback policy).
- [ ] Update the 9 prompt-template files (3 stages × 3 explore/exploit/default variants) to add the Delta Reasoning required block and reference the new output field.
- [ ] Implement the §2.9 plumbing-only Trap unit test.
- [ ] Implement the §2.9 real-API Trap test with `@real_run` marker.
- [ ] Implement the Tier-1 integration test asserting `delta_reasoning` is present and well-formed on a real call.

**Pre-Commit Checklist**:
- [ ] **Positive test (plumbing)**: `pytest tests/unit/agent/proposal/test_iter2_lesson_present_in_iter10_prompt.py` — the iter-2 trap text is verifiably present in the rendered iter-10 prompt.
- [ ] **Positive test (Tier-1)**: `pytest tests/integration/nodes/test_ml_model_proposal_agent_ledger.py --real-api-call` — real LLM call; `delta_reasoning` field is present, well-formed, and bounded list lengths satisfied.
- [ ] **Quantitative metric (Gate G3)**: `pytest tests/integration/proposer/test_long_term_wisdom_trap.py --real-api-call` — both assertions pass (proposer cites iter-2 lesson AND avoids the failing architecture).
- [ ] **Negative test**: `pytest -k test_proposer_falls_back_when_ledger_missing` — with `inp.ledger=None`, the legacy `previous_failures` rendering is used and produces a valid prompt (regression-guard for the fallback path).

**Definition of Done (Gate G3)**: ledger is rendered correctly; `delta_reasoning` is in every output; the Trap Test demonstrates 8-iter retention. If G3 fails, tune §2.9.4 knobs (older_attempts_K, confirmed_lessons_min_iters, last_frames_count) and re-run before proceeding to Commit 12.

**Out of Scope**: V13 chain run (Commit 12); legacy-path removal (Commit 12 cleanup).

---

### Commit 12: V13 chain run + metrics validation (Gate G4) + cleanup

**Phase**: 2.
**§5 steps**: 22, 23, 24.

**Scope**:
- `tools/compute_frr.py` (new — Failure Re-occurrence Rate computation)
- `tools/compute_drr.py` (new — DRR_Structural + DRR_LLM + Gap)
- `reports/v13_token_dehydration.md` (new — output artifact)
- `nodes/ml_model_proposal_agent.py` (cleanup: remove legacy fallback at line 644-648)
- `agent/schemas/proposal.py` (cleanup: remove `previous_failures: List[str]` field; tighten `delta_reasoning` to required)
- `workflows/model_exploration.py` (cleanup: remove `accumulated_physical_rejections` synthesis path at lines 916-954)

**Tasks**:
- [ ] Run a V13 chain (≥ 5 iters; ≥ 15 preferred for iter-30 extrapolation) with `use_evolutionary_ledger=True`.
- [ ] Implement `tools/compute_frr.py` per §4.2.1: joins `token_usage.jsonl` + ledger artefacts + validator outputs; emits FRR CSV.
- [ ] Implement `tools/compute_drr.py` per §4.2.1: structural matcher (AST/regex) + LLM judge (gpt-4o-mini, temp=0); emits DRR_Structural, DRR_LLM, Gap.
- [ ] Build `reports/v13_token_dehydration.md`: all 13 §4 metrics reported (rows 1–6, 7, 8a, 8b, 8c, 9, 10, 11). Each metric has its target, actual, and pass/fail verdict.
- [ ] **Conditional on all metrics passing**: remove the legacy fallback paths listed in scope. Tighten `ProposalOutput.delta_reasoning` to required (non-Optional).

**Pre-Commit Checklist**:
- [ ] **Positive test (Gate G4)**: every metric in the `reports/v13_token_dehydration.md` table is at or beyond its target.
- [ ] **Quantitative metric**: `prompt_tokens(iter=4) / prompt_tokens(iter=1) ≤ 1.20` for the proposer's `proposing` stage; total V13 cost `≤ 60%` of V12 baseline; FRR `= 0`; DRR_Structural `≥ 0.85`; DRR Gap `≤ 0.15`; Cr median `< 0.10`, p95 `< 0.15`.
- [ ] **Negative test (regression guard)**: full unit-test suite passes after cleanup commit (the legacy-path removal must not break any existing test). `pytest tests/ -x` exits 0.
- [ ] **Negative test (forensic re-runnability)**: assert that loading an old V11 `proposal_iter_NNN.json` against the new `ProposalOutput` schema produces a clear deprecation warning rather than crashing — open question §6.6 may revise this.

**Definition of Done (Gate G4)**: V13 chain run shows the refactor delivered the target cost reduction without regressing any intelligence metric; legacy paths removed; the system is on the new architecture.

**Out of Scope**: anything Phase 3 (tuner refactor, dashboard, etc.).

---

### Commit Map (visual)

```
Phase 1 (Telemetry)              Phase 2 (Dehydration)
 ┌─────────────────┐              ┌─────────────────┐
 │ C1 capture      │              │ C6 ErrorSig     │
 │ C2 setter+fail  │              │ C7 G2 forensic  │
 │ C3 audit+labels │              │ C8 schemas      │
 │ C4 plumbing     │              │ C9 helpers      │
 │ C5 G1 baseline  │ ───────────▶ │ C10 assembly    │
 │     (verdict)   │              │ C11 G3 trap     │
 └─────────────────┘              │ C12 G4 + cleanup│
                                  └─────────────────┘
```

Gates G1, G2, G3, G4 are explicit STOP points. Each gate's failure has a documented remediation path back into a prior commit, not a workaround.
