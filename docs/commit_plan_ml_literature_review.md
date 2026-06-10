# Commit Plan — `ml_literature_review`

**Status**: living document. Every checklist item is `[ ]` (pending) or `[x]`
(done) and updated in lockstep with the code as work proceeds.

---

## Document relationships

External agents are governed by three documents, each at a different layer:

- **Vision** — [`external_agents_architecture.md`](external_agents_architecture.md):
  invariants every external agent must respect (channel hierarchy, `AgentCard`
  trust calibration, when a manager layer is justified). Slow-moving.
- **Spec** — [`external_agents_for_proposer.md`](external_agents_for_proposer.md):
  the design of the first agent, `ml_literature_review` — schemas, verbosity
  levels, workflow integration. Evolves as implementation reveals reality.
- **Execution** — [`commit_plan_ml_literature_review.md`](commit_plan_ml_literature_review.md):
  the live `[ ]`/`[x]` checklist for rolling out `ml_literature_review`,
  commit by commit. Updates in lockstep with the code.

**You are here**: the **Execution** layer (live rollout checklist).

**Direction of truth**: when reality contradicts a doc, fix the highest
layer first (Vision → Spec → Plan), never the reverse.

---

## Status board

The board mixes **code commits** (the seven `[ ]`/`[x]` checklists below) with
**behavioral checkpoints** (human review gates indented under their owning
commit). A commit is not "done" until both its automated test gate is green
**and** any attached checkpoint has been reviewed and signed off.

- [x] **Commit 1** — Schema (`literature_review.py` + `external_agents.py`)
  · gate `tests/unit/agent/schemas/test_literature_review_schemas.py` · committed `c8fe641`
- [x] **Commit 2** — Paper resolver skill + TIDMAD pilot
  · gate `tests/unit/agent/skills/test_paper_resolver_skill.py` + `docs/paper_resolver_pilot.md` · committed 2a `a2bd97d` (skill+tests+deps) + 2b `5796cea` (docs+ID-fix); field-name lock `a659b47`
  - [x] **Checkpoint A** — Raw paper resolution output · signed off 2026-05-26
- [x] **Commit 3** — Finalize `PaperExtract` + compression prompt
  · gate 42 passed (schema + prompt suites) + real-run extract reviewed · artifact `docs/paper_extract_pilot.md` · committed `879e90e`
  - [x] **Checkpoint B** — Single paper LLM compression quality · signed off 2026-05-26 (hard requirement passes on both papers; one targeted prompt revision applied)
- [x] **Commit 2c** — Two-tier full-text + formula extraction (arXiv source → pdfplumber+LLM) — *(retroactive — amends Commit 2's skill; see §5a of `external_agents_for_proposer.md`)* · committed across `4da895d` (2c-a), `1ebb034` (2c-b), `963b628` (2c-cleanup), `5133662` + `81a63c6` (2c-c); Checkpoints E + F signed off 2026-05-31
  · gate `tests/unit/agent/skills/test_paper_resolver_skill.py` (tier cascade) + `@real_run` Tier-1 on TIDMAD · extraction-pilot artifact
  - [x] **2c-a** — `PaperExtract` +3 fields + extraction-tier-aware compression prompt · committed `4da895d`
  - [x] **2c-b** — Tier-1 arXiv source extraction wired end-to-end (parser + wrapper cascade + node propagation + 41 unit tests) · committed `1ebb034`
  - [x] **2c-cleanup** — drop the `marker_pdf` tier entirely from schema/prompts/skill_config/docs (two-tier cascade locked: arXiv source → pdfplumber+LLM) · committed `963b628`
  - [x] **2c-c** — `render_review_report` + §10 corpus pilot run + Checkpoints E/F *(was 2c-d before Tier-2 was cancelled)* · committed `5133662` (render_review_report) + `81a63c6` (§10 Phase-1 pilot + Checkpoints E/F sign-off)
  - [x] **Checkpoint E** — Tier-1 formula extraction quality (raw .tex output) · signed off 2026-05-31 (§10 Phase-1 pilot artifact reviewed; equations correct + clean for all 6 .tex papers, pseudocode preserved for TADA + FreLE, others have no algorithm blocks)
  - [x] **Checkpoint F** — LLM compression quality for `key_equations_md` / `pseudocode_md` · signed off 2026-05-31 (compression passes across all 7 papers: architecture_details actionable, key_results carry regime qualifiers, relevance_to_task honest, zero hallucinations)
- [x] **Commit 2d** — equation-/pseudocode-aware synthesis prompt — *(retroactive — extends Commit 2c; see §5b of `external_agents_for_proposer.md`)* · committed across `e9efddf` (synthesis prompt + per-paper block + locked Mechanism-vs-Adaptation placement rule), `7a5c093` (Phase-2 pilot script), `c51c231` (pilot artifact-first fix), `ce67cd2` (two-layer cite-id-mismatch fix: prompt labeled-id line + node-side `_validate_content_paper_id` hook), `7d466b2` (Phase-2 pilot floor + LaTeX-regex tuning); Checkpoint G signed off 2026-06-02
  · scope: feed `key_equations_md` / `pseudocode_md` / `extraction_method` into `render_synthesis_prompt`'s per-paper block; update `synthesis_system.md` so the synthesis LLM quotes Tier-1 equations verbatim and flags Tier-2 quotes as paraphrased — directly inside `ExpertContextItem.content`. **Zero schema changes** — `LiteratureReviewOutput` keeps its four `ExternalAgentOutput` channels, `ProposalInput` is untouched, `proposal.py` imports nothing from `literature_review.py`. The `reference_library` design earlier drafts proposed (typed output channel of `PaperReference` entries) is cancelled — equations travel inline inside finding `content`. `reference_library` lives only as transient node-scratch state during the `synth()` call; it is never serialised, never on output, never crosses any boundary.
  · gate `tests/unit/agent/prompt_templates/test_literature_review_prompts.py` + `tests/unit/agent/ml_literature_review/`
  - [x] **Checkpoint G** — Final synthesis output quality (equation-aware findings) · signed off 2026-06-02 (§10 Phase-2 pilot artifact reviewed; 3 findings emitted, all citing the paper they describe — zero TADA/FreLE-style cite-id-vs-content mismatches; equations quoted verbatim from Tier-1 sources inside Mechanism; Adaptation clean of LaTeX on all three findings; equation fidelity spot-checked against source `key_equations_md`; confidence calibration honest (0.90 / 0.85 / 0.70 ordering matches the on-domain → cross-domain gradient); each Adaptation describes a concrete implementation step)
- [x] **Commit 4** — `nodes/ml_literature_review.py` core loop
  · **4a** `820c548`; **4b-code** `c7860d7`; **4b-docs** `2ec1ae5`; **4b-final** `91461a2` (findings_verbosity + transfer_tolerance + node source-type routing + integration test → DeepSeek + Checkpoint C)
  - [x] **Checkpoint C** — Dynamic search loop behavior · signed off 2026-05-28 (artifact `docs/dynamic_search_pilot.md`)
- [x] **Commit 5** — Protocol `ml_literature_review_to_ml_model_propose.py` (audit-only on `local_full_context`; **4-kwarg shape**: `expert_context` / `vocab_seed` / `agent_cards` / `mindset`. No `reference_library` plumbing — that channel was cancelled in the 2d revision; equations travel inline inside finding `content`.) · committed `db55537`
  · gate `tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py`
- [ ] **Commit P** — Proposer awareness for external findings — *(retroactive — fixes structural gaps the Q1–Q7 audit surfaced after Commit 5; see new §11 of `external_agents_for_proposer.md`)*
  · scope: make the proposer actually read external-agent findings in production (pipeline) mode. Generic by construction — no agent-specific names in schemas or prompts. Resolves four problems found in audit: Rule 1 blocks literature, pipeline drops `constraints`/`hardware_context`/`vram_budget_gb`/`expert_advice`, literature renders at the bottom of the user prompt, no synthesis instruction.
  · gate `tests/unit/agent/ml_model_proposal_agent/` + `tests/unit/agent/schemas/` + prompt-template snapshot tests
  - [x] **P-design** — Doc-only scope contract: new `## Commit P` section in this file + new §11 in `external_agents_for_proposer.md`. No code touched. · committed `c0c0ea4`
  - [x] **P-a** — `cite_id` → `source_ref` rename across 36 files (also `DiscoveryMemo.citation_sources` → `source_refs`, `InheritedComponent.citation_source` → `source_ref`). Pure mechanical rename, zero behavior change. · committed `0c280ba`
  - [x] **P-b** — Schema additions: `AgentCard.trust_level: Literal["hard_limit", "strong_prior", "soft_prior"]`; `InheritedComponent.source_type: Literal["experiment", "external_agent", "human"]` + `source_id: str` (hard-remove `from_model_type` AND `source_ref` — both dead, no production callers); `render_agent_cards` surfaces `Trust Level` first; lit-review's emitted `AgentCard` declares `trust_level="soft_prior"`; `workflows/model_exploration.py` reference-code loop reads `source_id` when `source_type=="experiment"`. Test floor follows `feedback_dont_test_static_analysis` — pytest covers runtime-only behavior (validator regex, conditional branches, dict-input Literal rejection, render order); pyright/ruff/Pydantic-declaration trivia is NOT re-tested. · committed `a629e4a`
  - [x] **P-c** — Prompt rewrites: generic multi-source Rule 1 in `causal_reasoning_stage.md`; parallel weakening of "no generic ML knowledge" in `comparison_stage.md` Rule 4; new MANDATORY synthesis section in `causal_reasoning_stage.md`; remove hardcoded literature/physics/human trust hierarchy from both stage prompts; rewrite Contract Hierarchy in all six `*_explore.md`/`*_exploit.md` files to point at the synthesis rules instead of the dead "Advice JSON". · committed `69e7234`
  - [x] **P-d** — Pipeline-mode dead-field fixes + position-bias fix: render `_render_hardware_context_block` and a new `_render_constraints_block` at the TOP of every stage's user prompt; move `agent_cards_block` and `expert_context_block` from the bottom to the top (above the candidate markdown); hard-remove `ProposalInput.expert_advice`; `human_advice` workaround keeps existing behavior but the wrapped `ExpertContextItem` now carries a synthesized `human` `AgentCard` with `trust_level="strong_prior"` so its synthesis weight is correct. · committed `aeb4d9f`
  - [x] **P-e** — Doc + status-board updates: update vision doc §4 (`AgentCard.trust_level` is now structured; `trust_guidance` prose stays for humans); close vision doc §9 question 1 *(partial — same-trust_level adjudication deferred until a second external agent is added)*; soft-edge doc gains an `Exceptions` section noting `ProposalInput` is the deliberate exception; tick the P-b/P-c/P-d boxes (P-e is the lockstep tick commit); update `nodes/ml_literature_review.md` Parameter Reference to mention the emitted `AgentCard.trust_level` constant. · committed `6348ece`
  - [x] **Checkpoint P** — Proposer pipeline-mode prompt audit (offline) · signed off 2026-06-05 (all 9 sub-criteria PASS; 10/10 automated pre-checks PASS; visual sub-criteria S1–S5 verified in the captured prompts; artifact `docs/proposer_prompt_audit.md` carries the per-criterion verdict table + 3 captured (system, user) prompt pairs covering comparison → causal_reasoning → proposing in pipeline mode). Driver: `scripts/render_proposer_prompts_for_audit.py` (zero LLM calls, runs in ~1 second). **Gates Commit 6 from starting — now unblocked.**
- [ ] **Commit 6** — Workflow integration (`merge_external_agent_outputs`, `should_run_literature_review`)
  · gate `tests/unit/workflows/test_model_exploration_lit_review_wiring.py` + Tier-0 dual-mode
  - [ ] **Checkpoint D** — End-to-end proposer behavior change
- [ ] **Commit 7** — Configs, cache dir README, full connection audit
  · gate full `tests/unit/` + `tests/integration/` green
- [ ] **§10 End-to-end validation suite** — permanent acceptance gate
  (spec: `external_agents_for_proposer.md` §10); cross-cutting, not a single
  commit. Run log: `docs/validation_suite_runs.md`.
  - [ ] **First FULL run** — after Commit P closes (Commit-2 family complete +
        proposer-awareness landed; suite validates the *post-P* proposer
        behavior, not the broken pre-P one)
  - [ ] **Prerequisite re-run** — before Checkpoint D / Commit 6 (must pass on
        the post-P proposer)

---

## Behavioral checkpoints

The automated test gates above answer *"does the code run correctly?"* — they
verify schema validation, mock-driven control flow, and type safety. The
**behavioral checkpoints** answer a different question: *"is the system doing
something useful?"* A system can have 100% green tests and still produce
literature summaries that no proposer would read, or have zero traceable
influence on the architectures the proposer suggests.

Each checkpoint is a human review gate attached to a specific commit. It
specifies the exact command to run, the artifact it should produce, what to
inspect in that artifact, and what design decision depends on the answer.
**No commit with an attached checkpoint is considered done until both the
test gate is green and the checkpoint review is signed off.** The checkpoint
artifacts (`docs/paper_resolver_pilot.md`, `docs/paper_extract_pilot.md`,
`docs/dynamic_search_pilot.md`, `docs/e2e_behavior_pilot.md`) are
version-controlled so future revisions of the system have a reference for
what "working" looked like at each stage.

**§10 End-to-end validation suite** (spec:
`external_agents_for_proposer.md` §10) is a *separate kind of artifact* —
distinct from the one-time checkpoints above, it is a *permanent* acceptance
gate that re-runs across commits on a locked 7-paper corpus. The one-time
checkpoints (A–F, D) gate a single commit's behavior; §10 gates the entire
system's regression behavior over time. Its first FULL run is right after
Commit 2d closes (Commit-2 family complete → suite fully runnable per §10.4),
and it is a prerequisite for Checkpoint D / Commit 6. Each suite run records
dated results in `docs/validation_suite_runs.md`.

---

## Confirmed design decisions (locked, do not relitigate)

These came out of the pre-plan Q&A and are now invariants for the rest of the
plan:

1. **`LiteratureReviewInput.experiment_history` is `InterpretationOutput`** (passed
   whole). The historical-architectures gap is acknowledged; the future fix, if
   needed, is a `chain_history` field at the *workflow* layer — not a reshape
   of this input schema.
2. **Single LLM model for v1.** No reflector split. The dynamic-search inner
   loop's "done? upgrade? next query?" decision is the natural future reflector
   candidate — marked in code with a `TODO(reflector-split)` comment so it's
   greppable.
3. **Resolver skill keeps `run_skill(sandbox, **kwargs)`.** Sandbox is `None`
   from the lit-review node and ignored inside. Preserves universal skill
   convention; future generic skill loaders don't need a special case.
4. **`configs/lit_review_config.yaml` is committed directly.** Repo-relative
   paths required for `source: local` entries. No `.example.yaml` split for
   v1; if per-machine override is needed later, we add it then.
5. **Pilot artifact is committed.** `docs/paper_resolver_pilot.md` lands as
   part of Commit 2; future readers see why `PaperExtract` fields ended up
   the way they did.
6. **Commit 5 is audit-only.** `local_full_context` at
   `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:43-64`
   already accepts `mindset` and `agent_cards` and threads them into
   `ProposalInput`. The commit message records the audit finding; no code
   patch.

---

## Pre-landed work (do not re-do)

These are already in main and form the receiving end for lit-review:

- `AgentCard`, `ProposalInput.agent_cards`, `ProposalInput.mindset`,
  `VocabEntry.origin`, `ExpertContextItem.kind == "literature"` —
  `agent/schemas/proposal.py`.
- `local_full_context` end-to-end threading of `mindset` and `agent_cards` —
  `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`.
- `render_agent_cards` and `render_expert_context` with dedup-by-`source_ref` and
  confidence-descending sort — `agent/prompt_templates/proposal/__init__.py`.
- Phase F tests covering the agent-card path through the proposer —
  `tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py`.

If any of the above stops being true mid-plan, **stop and report** rather than
silently re-implementing.

---

## Cross-cutting requirements (apply to every commit)

- **Python interpreter**: every command uses
  `.venv/bin/python` per `CLAUDE.md`. Never `python3` (system py is 3.8).
- **Test scope**: run only the test files relevant to the commit's change.
  The full suite runs once, in Commit 7's gate.
- **LLM access**: every LLM call goes through `LLMBridge` (the
  singleton-enforcing test at `tests/unit/agent/test_llm_bridge_singleton.py`
  will fail any direct `OpenAI()` / `Anthropic()` import). Use
  `bridge.generate(...)` for JSON, `bridge.generate_text(...)` for plain
  text. No new public methods on LLMBridge in this work.
- **JSON parsing from LLM**: match the pattern used in
  `nodes/ml_hyperparameter_tune_agent.py` exactly — do not introduce a new
  convention without asking.
- **Lint / type check**: after every commit's edits, run
  `.venv/bin/python -m ruff check <changed files>` and
  `.venv/bin/python -m pyright <changed files>`. Never disable a rule to make
  CI green — fix the underlying code.
- **Commits**: ask before each commit. Show the test command and wait for
  approval. Test with a real run *before* committing.
- **Pilot / real-run outputs**: outputs of Commit 2's pilot and Commit 3 / 4's
  real-run tests are **design checkpoints**, not just test gates. Show them
  before the commit closes.

---

## Commit 1 — Schema

**Goal**: Define the typed surface for the lit-review node and the universal
`ExternalAgentOutput` base, with pure-data tests proving Pydantic validation
works on every schema. No node, no skill, no LLM yet — just the contract.

**Files**:
- New: `agent/schemas/external_agents.py` — universal base `ExternalAgentOutput`
  (lives in a shared module so future agents import it without refactoring;
  see [§6 of the architecture doc](external_agents_architecture.md#6-the-insertable-not-refactorable-property)).
- New: `agent/schemas/literature_review.py` — `PaperSource`,
  `DynamicSearchConfig`, `PaperExtract` (provisional), `RetrievedPaper`,
  `LiteratureReviewInput`, `LiteratureReviewOutput(ExternalAgentOutput)`.
- New: `tests/unit/agent/schemas/test_literature_review_schemas.py`.

**Checklist**:
- [x] Create `agent/schemas/external_agents.py` with `ExternalAgentOutput(BaseModel)`:
      `agent_card: AgentCard`, `findings: list[ExpertContextItem]`,
      `new_vocab_candidates: list[VocabEntry] = []`,
      `suggested_mindset: str | None = None`. Imports `AgentCard`,
      `ExpertContextItem`, `VocabEntry` from `agent.schemas.proposal`.
- [x] Create `agent/schemas/literature_review.py`:
  - [x] `PaperSource(BaseModel)`: `source_type: Literal["arxiv","doi","openreview","local"]`,
        `identifier: str`, `verbosity: Literal[0,1,2] = 1`. Validator: for
        `source_type == "local"`, `identifier` must be a repo-relative path
        (no leading `/`, no `..`).
  - [x] `DynamicSearchConfig(BaseModel)`: `enabled: bool = True`,
        `max_rounds: int = 3` (ge=1), `initial_verbosity: Literal[0,1,2] = 0`,
        `escalation_allowed: bool = True`.
  - [x] `PaperExtract(BaseModel)` — **provisional** fields with TODO comment
        pointing at Commit 3. Start from spec §5 list: `title`, `authors`,
        `year`, `core_idea`, `architecture_details`, `key_results`,
        `relevance_to_task`. All `str`. Finalize after pilot.
  - [x] `RetrievedPaper(BaseModel)`: `paper_id: str`, `source: PaperSource`,
        `s2_metadata: dict[str, Any] | None`, `extract: PaperExtract | None`,
        `full_text: str | None`, `verbosity_achieved: Literal[0,1,2]`,
        `error: str | None = None`.
  - [x] `LiteratureReviewInput(BaseModel)`: `experiment_history: InterpretationOutput`
        (imported from `agent.schemas.interpretation`), `root_papers: list[PaperSource]`,
        `dynamic_search: DynamicSearchConfig`, `storage: StorageConfig`,
        `run_name: str`, `llm_provider: str`, `llm_model_id: str`.
  - [x] `LiteratureReviewOutput(ExternalAgentOutput)`: adds
        `retrieved_papers: list[RetrievedPaper]` (audit trail),
        `search_rounds_used: int`, `run_name: str`, `started_at: str`,
        `finished_at: str`. Inherits the four channel fields.
- [x] Create `tests/unit/agent/schemas/test_literature_review_schemas.py`:
  - [x] Happy-path instantiation for each schema (one test per schema).
  - [x] `PaperSource` validator rejects absolute path when `source_type=="local"`.
  - [x] `PaperSource` validator rejects `..` in local path.
  - [x] `DynamicSearchConfig` rejects `max_rounds=0`.
  - [x] `LiteratureReviewOutput` accepts empty `new_vocab_candidates` and
        `suggested_mindset=None` (v1 wired-empty channels).
  - [x] `RetrievedPaper` with `verbosity_achieved=0` and `extract=None` validates
        (cache miss + S2 fallback path).

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/schemas/test_literature_review_schemas.py -q
.venv/bin/python -m ruff check agent/schemas/external_agents.py agent/schemas/literature_review.py tests/unit/agent/schemas/test_literature_review_schemas.py
.venv/bin/python -m pyright agent/schemas/external_agents.py agent/schemas/literature_review.py
```

**Open questions / decisions needed**:
- `LiteratureReviewInput.run_name` — does v1 share the workflow's `run_name`
  or get its own derived name (`f"{run_name}_litreview"`)? Lean: share, no
  derivation, document the choice in the docstring.
- `RetrievedPaper.paper_id` format — is it `f"{source_type}:{identifier}"` or
  just the raw identifier? Lean: prefixed (collision-safe across sources).

---

## Commit 2 — Paper resolver skill (resolve + search) + TIDMAD pilot

**Goal**: Ship the deterministic paper-fetching skill — **both** S2 lookup
by ID *and* S2 keyword search, plus PDF download and local file read — and
verify against the TIDMAD paper that the extracted text is usable for
`PaperExtract`-style compression.

**Design note (decided pre-implementation, see S2 API research)**: the
skill has **two modes**, `resolve` and `search`, controlled by a `mode`
parameter in `skill_config.json`. They share all post-processing
(`openAccessPdf` extraction, `externalIds` normalisation, PDF download,
auth/rate-limit/retry plumbing). Per-paper response objects are the same
shape between `/paper/{id}` and `/paper/search` — the `search` mode just
unwraps `response["data"]` before reusing the same paper-mapping function.
Splitting into two skill folders would duplicate ~all logic for a five-line
URL switch. **Do not split.**

**Files**:
- New: `agent/skills/paper_resolver_skill/skill_config.json`
- New: `agent/skills/paper_resolver_skill/wrapper.py`
- New: `agent/skills/paper_resolver_skill/__init__.py` (empty marker)
- New: `tests/unit/agent/skills/test_paper_resolver_skill.py`
- New: `docs/paper_resolver_pilot.md` (the pilot artifact)

**Checklist**:
- [x] Write `skill_config.json` matching the
      `denoising_score_skill/skill_config.json` template. Top-level
      `parameters.properties`:
  - `mode`: `Literal["resolve", "search"]` — required.
  - **Resolve-mode**: `source_type` (`Literal["arxiv","doi","openreview","local"]`),
        `identifier: str`, `verbosity: Literal[0,1,2]`.
  - **Search-mode**: `query: str` (required), `limit: int = 10`,
        `offset: int = 0`, optional filters (`year`, `fields_of_study`,
        `publication_types`, `min_citation_count`),
        `verbosity: Literal[0,1,2] = 0` (search defaults to metadata-only).
  - `required`: `["mode"]` plus mode-dependent constraints (documented in
        the wrapper's docstring; Pydantic-style validation lives at the
        node-input boundary, not in `skill_config.json`).
- [x] Write `wrapper.py` exporting
      `run_skill(sandbox, **kwargs) -> dict`. `sandbox` is accepted and
      ignored (consistent with universal skill convention per Q3).
- [x] Resolve-mode branch (`mode == "resolve"`):
  - [x] `source_type in {"arxiv","doi","openreview"}` → S2 lookup via
        `GET /graph/v1/paper/{id_prefix}:{identifier}` (e.g.
        `ARXIV:2406.04378`, `DOI:...`, `URL:...`). Parse `openAccessPdf`
        and `externalIds`.
  - [x] PDF download: prefer `openAccessPdf.url`; fall back to
        `https://arxiv.org/pdf/{arxiv_id}.pdf` when `externalIds.ArXiv`
        present. **v1 deviation**: the PDF is buffered in memory
        (`resp.content`), not streamed to a temp file — acceptable for papers
        <10MB; revisit if a larger paper appears.
  - [x] Local file branch (`source_type == "local"`): resolve repo-relative
        path against project root, read `.pdf` via `pdfplumber`, read
        `.txt` / `.md` directly.
- [x] Search-mode branch (`mode == "search"`):
  - [x] Build query against `GET /graph/v1/paper/search?query=...&limit=...&offset=...`
        with optional filters mapped to the S2 query params.
  - [x] Unwrap `response["data"]` and run each paper object through the
        same per-paper mapping helper used by resolve-mode. Result is a
        `list[RetrievedPaper]`-shaped payload.
  - [x] Search defaults to `verbosity=0` (metadata only — no PDF fetch
        per result, which would be a fan-out cost trap). PDF fetch only
        happens when the lit-review node later requests a specific paper
        at higher verbosity via a follow-up `resolve` call.
  - [x] Honour `limit` (default 10, cap at 50 — documented in wrapper).
- [x] Shared per-paper mapping helper (private): `_paper_object_to_dict(obj) -> dict`
      returns the fields needed by `RetrievedPaper.s2_metadata` plus an
      `openAccessPdf` and `externalIds` pass-through. Used by both modes.
- [x] Per-run in-memory cache: module-level
      `_S2_CACHE: dict[tuple, dict]` keyed by the full request shape
      (mode + identifier + filters). A second call with the same shape
      returns the cached S2 response. Documented as **not** thread-safe.
- [x] Rate limiting (S2 1 req/s): `_s2_get` paces sends via `_throttle_s2`
      (module-level last-send timestamp; sleeps only the remaining fraction
      of `S2_MIN_REQUEST_INTERVAL_S=1.1`) **and** retries up to
      `S2_MAX_RETRIES=3` on 429/5xx, honouring `Retry-After` else exponential
      backoff (`S2_RETRY_BACKOFF_BASE_S`). Scoped to S2 calls only — PDF
      downloads (arxiv/publisher) are not S2-throttled. Never raises; not
      thread-safe (same contract as the cache).
- [x] URL-encoding fix: `_s2_lookup_id` percent-encodes the lookup id
      (`safe=":/"`) so an OpenReview forum URL's `?id=...` reaches S2 inside the
      path instead of being parsed as a query string. arXiv/DOI on-the-wire form
      unchanged. (Bug found during the pilot; see `docs/paper_resolver_pilot.md`.)
- [x] Empty-extraction fix: `_extract_pdf_text` treats whitespace-only output
      (image-only/scanned PDFs) the same as a hard failure — returns
      `(None, msg)` + `logger.warning`, so callers fall back to
      `verbosity_achieved=0` instead of silently succeeding with `""`.
- [x] Error contract: every exit path returns
      `{"status": "ok" | "partial" | "error", "data": ..., "message": ...}`.
      Never raise. `partial` covers e.g. resolve succeeded for S2 metadata
      but PDF download failed.
- [x] Run the **resolve-mode pilot** manually:
      ```python
      from agent.skills.paper_resolver_skill.wrapper import run_skill
      result = run_skill(
          None, mode="resolve",
          source_type="arxiv", identifier="2406.04378", verbosity=1,
      )
      ```
      Capture: token-count estimate, openAccessPdf-vs-arxiv-fallback path
      taken, structural integrity of equations/sections, signal-to-noise.
- [x] Run the **search-mode pilot** manually (sanity, 3-line check —
      not the design-driving pilot):
      ```python
      result = run_skill(
          None, mode="search",
          query="superconducting quantum interference device denoising",
          limit=5, verbosity=0,
      )
      ```
      Capture: result count, whether top results are topically relevant,
      whether `openAccessPdf` populated on any of them. Just enough to
      prove the endpoint works — Commit 4's dynamic-search loop will
      exercise it in earnest.
- [x] Write `docs/paper_resolver_pilot.md` recording both pilots' outputs,
      plus a 200-line excerpt of the TIDMAD extracted text so Commit 3
      can reference it without re-running. **Show the user before
      finalising the file.**
- [x] Write `tests/unit/agent/skills/test_paper_resolver_skill.py`:
  - [x] resolve / arxiv — mocked S2 response, mocked PDF download, asserts
        `openAccessPdf` path is taken.
  - [x] resolve / arxiv — S2 returns no `openAccessPdf`, asserts arXiv
        fallback URL is used.
  - [x] resolve / arxiv — both paths fail → `verbosity_achieved=0`, S2
        metadata only, status="partial", no exception.
  - [x] resolve / doi — mocked S2 returns metadata, no PDF,
        verbosity_achieved=0.
  - [x] resolve / openreview — mocked S2 returns metadata + openAccessPdf,
        verbosity_achieved=2 (full text path).
  - [x] resolve / local `.pdf` — `pdfplumber` is mocked to return canned text.
  - [x] resolve / local `.md` — direct file read, no pdfplumber.
  - [x] resolve / local — absolute path rejected (the `PaperSource` validator
        catches it at construction; this test confirms the wrapper also
        defends in-depth).
  - [x] **search — happy path**: mocked S2 returns an envelope with 3
        `data` items; wrapper unwraps and returns 3 mapped paper objects.
  - [x] **search — empty result**: mocked S2 returns `{"total": 0,
        "offset": 0, "data": []}` → wrapper returns `status="ok"`,
        empty list, no exception.
  - [x] **search — filter passthrough**: `year=2023`, `min_citation_count=10`
        appear in the request URL.
  - [x] cache hit — two calls with the same arguments (resolve or search)
        → `requests.get` called once.
  - [x] error case — `requests.get` raises → wrapper returns
        `{"status":"error","message":...}`, does not propagate.
  - [x] rate limit — `_throttle_s2` sleeps only the remaining interval when
        called within `S2_MIN_REQUEST_INTERVAL_S`; no sleep once enough time
        has elapsed.
  - [x] rate limit — a 429 then 200 is retried to success; a persistent 429
        exhausts `S2_MAX_RETRIES` then returns `status="error"` (no raise);
        a non-retryable status (404) returns immediately; `Retry-After` is
        honoured when present.
  - [x] url encoding — `_s2_lookup_id` percent-encodes `?`/`=` in an OpenReview
        URL; arXiv/DOI ids are byte-identical after encoding.
  - [x] empty extraction — `_extract_pdf_text` returns `(None, msg)` when every
        page extracts to empty text.
- [x] **Real-API source-type validation** — opt-in `@real_run` integration tests
      in `tests/integration/skills/test_paper_resolver_skill.py` (the unit file
      only covers mocked HTTP/PDF):
  - [x] resolve / arxiv — live S2 + real pdfplumber on TIDMAD `2406.04378`.
  - [x] resolve / doi — live S2 on `10.48550/arXiv.2406.04378`; resolves to the
        same paper (ArXiv-id cross-check).
  - [x] resolve / openreview — `xfail`: S2 does not index OpenReview URLs and
        there is no fallback yet (spec §9).
  - [x] resolve / local `.txt` — offline real read of
        `reference_data/tidmad_signal_frequencies.txt` (unmarked, no key).

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/skills/test_paper_resolver_skill.py -q
.venv/bin/python -m ruff check agent/skills/paper_resolver_skill/ tests/unit/agent/skills/test_paper_resolver_skill.py tests/integration/skills/test_paper_resolver_skill.py
.venv/bin/python -m pyright agent/skills/paper_resolver_skill/wrapper.py
.venv/bin/python -m pytest tests/integration/skills/test_paper_resolver_skill.py -m real_run -q   # opt-in: live S2 (3 tests, skip w/o network); local .txt runs offline in the full integration sweep
```
Plus: `docs/paper_resolver_pilot.md` exists with **both** resolve-mode and
search-mode outputs, reviewed by user.

#### 🔍 Behavioral Checkpoint A — Raw paper resolution output

**Trigger**: run this after the test gate passes and `pdfplumber` is
installed in the venv. This is the gate that decides what fields
`PaperExtract` (Commit 3) ends up carrying.

**How to run**: with the wrapper green, run it manually against the TIDMAD
paper, capturing both verbosity tiers:

```python
from agent.skills.paper_resolver_skill.wrapper import run_skill

# Full text (verbosity=2) — what compression sees in worst case.
v2 = run_skill(
    None, mode="resolve", source_type="arxiv",
    identifier="2406.04378", verbosity=2,
)
full_text = v2["data"]["full_text"]
print(full_text[:3000])  # first 3000 chars
print("---")
print(f"Total length: {len(full_text)} chars, "
      f"≈{len(full_text) // 4} tokens")

# Verbosity=1 — what the LLM compression prompt will receive.
v1 = run_skill(
    None, mode="resolve", source_type="arxiv",
    identifier="2406.04378", verbosity=1,
)
print(v1["status"], v1["message"])
```

**What to inspect**:
- Is the extracted text readable, or is it garbled (common with multi-column
  PDF layouts)?
- Are mathematical equations preserved as LaTeX, rendered as Unicode, or
  lost entirely?
- Is section structure identifiable (Introduction / Methods / Results /
  References)?
- What fraction of the text is noise: author affiliations, page
  headers/footers, reference list, figure captions with no context?
- For a SQUID signal-processing paper specifically: which sections contain
  information that would actually help a model proposer (architecture
  choices, preprocessing decisions, training tricks, ablations)?
- Roughly how many tokens is the full text? Estimate as `len(full_text) / 4`.

**What this decides**: the `PaperExtract` field design in Commit 3.
Specifically:
- If equations are preserved as readable LaTeX → add a `key_equations: str`
  field to `PaperExtract`.
- If equations are garbled → do not add a structured equation field;
  instruct the LLM to describe equations in prose instead.
- If section structure is clean → the LLM compression prompt can reference
  section names explicitly.
- If noise ratio is high → the compression prompt must explicitly instruct
  the LLM to ignore references, affiliations, and figure captions.

**Sign-off requirement**: a human must read the output and answer each
bullet above in `docs/paper_resolver_pilot.md`. If the text quality is so
poor that useful information cannot be extracted (e.g. fully garbled
multi-column layout), we need to evaluate alternative extraction libraries
(e.g. `pymupdf`, `pypdf2`) before proceeding to Commit 3. **Do not proceed
until the extraction quality question is settled.**

**Artifact to commit**: `docs/paper_resolver_pilot.md` containing the
inspection answers, a representative excerpt of the extracted text (first
500 chars of the methods section if identifiable), and a recommendation on
equation handling. Same file also captures the search-mode sanity check
(per the search-pilot bullet above) — single file, two pilots.

**Open questions / decisions needed** — RESOLVED:
- HTTP library → `requests` (project default; the only HTTP lib the wrapper
  imports). ✅
- S2 rate limits / API key → `S2_API_KEY` env var (silent-degrade to the
  unauthenticated pool if absent), plus a 1 req/s `_throttle_s2` pace and a
  429/5xx `Retry-After`-aware retry. ✅
- PDF extraction library → `pdfplumber 0.11.9` (added to `pyproject.toml`,
  installed via `uv sync`). ✅

**Verification (Checkpoint A — signed off 2026-05-26)**:
- Unit gate: `pytest tests/unit/agent/skills/test_paper_resolver_skill.py -q`
  → **35 passed**; ruff + pyright clean.
- Real-API source-type validation:
  `pytest tests/integration/skills/test_paper_resolver_skill.py`
  → **3 passed, 1 xfailed** (arxiv ✅, doi ✅, openreview xfail [S2 coverage],
  local ✅).
- Live pilot vs TIDMAD `2406.04378`: resolve v2 = 73,644 chars ≈ 18.4k tokens
  (via `arxiv_fallback` — S2 `openAccessPdf.url` was empty), resolve v1, and a
  search sanity check. Captured in `docs/paper_resolver_pilot.md`.
- **Decision locked (F3): no `key_equations` field; equations described in
  prose.** Extraction degrades math (`∑`→`(cid:88)`, subscripts flattened).
- **Domain caveat (F4): TIDMAD model rankings are frequency-split; SIDERIUS is
  full-spectrum.** The compression prompt must inject this qualifier — a hard
  requirement at Checkpoint B.
- ID correction: `2302.09309` (CVPR *StyleAdv*, wrong) → `2406.04378` (TIDMAD,
  per the legacy repo README) across docs/code/tests.
- Bugs found + fixed: URL-encoding truncation (openreview `?id=`) and
  empty-extraction silent-success.

---

## Commit 2c — Two-tier full-text + formula extraction

**Goal**: Implement the two-tier extraction strategy
(`docs/external_agents_for_proposer.md` §5a) in `paper_resolver_skill`; add
`key_equations_md`, `pseudocode_md`, and `extraction_method` to `PaperExtract`;
run a pilot validating extraction quality on real papers. Logically this sits
between Commit 2 (shipped the skill + pdfplumber path) and Commit 3 (locked the
`PaperExtract` field set) — it extends the skill and **amends** both Commit 3's
field-set lock and pilot finding **F3** ("no `key_equations`; prose only"): F3's
rationale (pdfplumber degrades math) holds only for the Tier-2 path; Tier 1
carries equations verbatim. NOTE: introduced after Commits 3 and 4 already
shipped, so it also requires re-validating the Commit-3 compression prompt
against the new fields (Checkpoint F + the equation-aware prompt variant).

**Why two tiers, not three.** An early plan slotted in a GPU-based PDF→Markdown
tier (`marker-pdf`) between arXiv source and pdfplumber. We dropped it: the lab
GPU (5090) does not have `marker-pdf` installed, and the marginal quality gain
over `pdfplumber + LLM` is small for math-heavy papers (both paths ultimately
depend on the compression LLM to reconstruct LaTeX). The framework stays
extensible — a Tier-1.5 GPU converter can be slotted in later without touching
the existing wire-up — but the locked design here is two-tier only.

**Sub-commit ladder**: split into logical units committed sequentially — 2c-a
(schema + prompt), 2c-b (Tier-1 wire-up), 2c-cleanup (drop `marker_pdf` from
schema/prompts/docs after the Tier-2 cancellation decision), 2c-c (pilot +
render_review_report + Checkpoints E/F; renumbered from the original 2c-d after
the cancellation).

**Checklist**:

#### 2c-a — schema + prompt *(committed `4da895d`)*
- [x] Add `key_equations_md`, `pseudocode_md`, `extraction_method` to
      `PaperExtract`; update the "locked field set" docstring note accordingly.
- [x] `render_paper_extract_prompt` becomes `extraction_method`-aware
      (equation-aware for Tier 1–2; "reconstruct from degraded text, mark
      unreliable" for Tier 3). Per-tier instruction blocks injected via the
      `{EXTRACTION_INSTRUCTIONS}` placeholder.

#### 2c-b — Tier-1 arXiv source wire-up *(committed `1ebb034`)*
- [x] Tier 1: arXiv source downloader (`https://arxiv.org/src/{id}` → `.tar.gz`)
      + `.tex` parser for `equation`/`align`/`algorithm`/`figure` → clean Markdown.
      Implemented in `agent/skills/paper_resolver_skill/arxiv_source.py` via
      pylatexenc 2.x AST walk with verbatim slicing.
- [x] Tier 2 (formerly Tier-3): existing `pdfplumber` text path retained as the
      fallback. No change to the path itself; the cascade now arrives there only
      after Tier-1 returns None.
- [x] `extraction_method` wired end-to-end through both tiers: set in the skill
      payload, returned in the response envelope, read by the node and stamped
      on `PaperExtract` after LLM validation (so the LLM cannot mint or override
      the trust signal).
- [x] Unit tests for the **Tier-1 / Tier-2 cascade**: 21 parser tests + 10
      wrapper cascade tests + 10 node propagation tests (mocked HTTP throughout;
      no real network, no real LLM).

#### 2c-cleanup — drop `marker_pdf` from schema/prompts/docs
*(post-2c-b decision: cancel the planned Tier-2 marker hook entirely; the
cascade is two-tier only — see "Why two tiers, not three" above)*
- [ ] `agent/schemas/literature_review.py`: remove `"marker_pdf"` from the
      `extraction_method` Literal; update the field docstring to describe a
      two-tier scale (`arxiv_source` > `pdfplumber_llm` > `abstract_only`).
- [ ] `agent/prompt_templates/literature_review/__init__.py`: remove
      `_PAPER_EXTRACT_INSTRUCTIONS_MARKER` constant and its entry in the
      `_PAPER_EXTRACT_INSTRUCTIONS` dict; tighten `render_paper_extract_prompt`'s
      `extraction_method` parameter Literal to drop `"marker_pdf"`.
- [ ] `agent/prompt_templates/literature_review/paper_extract_system.md`:
      no edit needed if `marker_pdf` is not mentioned in the static template —
      verify and confirm.
- [ ] `agent/skills/paper_resolver_skill/skill_config.json`: update the
      top-level description to list two tiers (drop `marker_pdf`) and update
      the `verbosity` description correspondingly.
- [ ] `agent/skills/paper_resolver_skill/wrapper.py`: drop any reference to
      `marker_pdf` in payload dicts / log lines (none exist today — verify
      and confirm).
- [ ] `nodes/ml_literature_review.py`: tighten the `_compress` and call-site
      Literals to drop `"marker_pdf"`.
- [ ] Tests: remove the `marker_pdf` parametrize case from
      `test_node.py::TestExtractionMethodPropagation::test_method_from_skill_lands_on_extract`
      and from the `test_prompt_carries_tier_specific_instructions` parametrize.
- [ ] Run the full gate (pytest + ruff + ruff format --check + pyright) on the
      affected suites; confirm green.

#### 2c-c — pilot + render_review_report + Checkpoints E/F
*(renumbered from the original 2c-d after Tier-2 was cancelled)*
- [ ] **`render_review_report`** — pure, deterministic Markdown renderer for a
      lit-review run's artifacts (Phase 1 `RetrievedPaper` extracts and, when
      present, Phase 2 findings). Reusable in production runs, not just §10.
      Location: `agent/prompt_templates/literature_review/__init__.py`
      (alongside the compression / synthesis renderers). **Pure function — no
      LLM, no I/O; the caller writes the rendered string to a file.** Unit
      tests assert deterministic output + per-section presence for a fixture
      `LiteratureReviewOutput` / `RetrievedPaper` list (with and without
      findings). *(Note: earlier drafts also planned a Phase-2
      `reference_library` section — cancelled per the 2d revision; the
      renderer is single-channel.)*
- [ ] Pilot on the **§10 corpus** (7 papers, §10.2): six Tier-1 papers
      (#1–#6 Mamba / PatchTST / GW / DeepDenoiser / TADA / FreLE) and SNRAware
      (#7) via the Tier-2 (`pdfplumber + LLM`) fallback. Capture per-paper
      `verbosity_achieved`, `extraction_method`, and full `PaperExtract`
      (incl. `key_equations_md` / `pseudocode_md`). The pilot script calls
      `render_review_report` and writes a single human-review Markdown file
      covering all 7 papers — that file is the artifact Checkpoints E + F
      sign off on.
- [ ] Re-validate LLM compression with new fields: after Checkpoint E is
      signed off, run the compression prompt on the §10 corpus and verify:
      (a) `key_equations_md` is populated with correct LaTeX for the six
          Tier-1 papers (cross-check against raw `.tex`); for SNRAware
          (PDF-only) Tier-2 produces a usable best-effort extract;
      (b) `pseudocode_md` is populated with the algorithm structure preserved;
      (c) `extraction_method` is correctly passed through the response envelope
          to the node and reflected in the final `PaperExtract` (`arxiv_source`
          for #1–#6; `pdfplumber_llm` for #7).
      The pilot's `render_review_report` output (above) contains the full
      `PaperExtract` for all seven papers — that's the artifact for the
      Checkpoint-F review. This is the **§10 Phase 1 partial run**.

**Test gate**:
- Unit: `tests/unit/agent/skills/test_paper_resolver_skill.py` — per-tier +
  cascade, all HTTP mocked.
- Integration (`@real_run`): Tier-1 on TIDMAD with a **real** arXiv source
  download; assert `key_equations_md` is non-empty and contains `$$`.
- **§10 partial run** (before closing 2c): run §10 Phase 1 (Steps 1a/1b incl.
  `key_equations_md` / `extraction_method`) on the 7-paper corpus — this *is*
  Checkpoints E+F at corpus scale. Record results in
  `docs/validation_suite_runs.md`.

#### 🔍 Behavioral Checkpoint E — Tier-1 formula extraction quality

Run Tier-1 extraction on the **six §10 corpus papers with `.tex` source**
(§10.2 #1–#6: Mamba `arxiv:2312.00752`, PatchTST `arxiv:2211.14730`,
GW denoising `arxiv:2511.20731`, DeepDenoiser `arxiv:1811.02695`,
TADA `arxiv:2501.04967`, FreLE `arxiv:2510.25800`); print each paper's
extracted `key_equations_md` and `pseudocode_md`; **show the results before
proceeding.** Verify per paper:
- (a) each paper's key equations extract correctly (cross-check against the
  raw `.tex` source);
- (b) each paper's pseudocode / algorithm blocks (where present) preserve
  structure;
- (c) the Markdown is clean enough to feed directly to the LLM compression
  prompt.

This checkpoint **gates Tier-1 quality** on these six papers — equations,
pseudocode, and figure captions must come through cleanly enough for the
compression LLM to fill `key_equations_md` / `pseudocode_md` verbatim. If
Tier-1 turns out to be insufficient on a paper, that paper degrades to the
Tier-2 (`pdfplumber + LLM`) path instead — same fallback SNRAware uses below.
(Inserting a future GPU-based converter as a Tier-1.5 is left open by the
two-tier design, but is out of scope for Commit 2c.) Note: SNRAware
(`arxiv:2503.18162`, §10 #7) is PDF-only (no `.tex` source) and exercises the
Tier-2 fallback path in Checkpoint F, not Tier-1 here. Do not proceed on the
new fields until signed off.

#### 🔍 Behavioral Checkpoint F — LLM compression quality for new fields

After Checkpoint E is signed off, run the compression prompt on the **full §10
corpus** (six Tier-1 papers from §10.2 #1–#6 + SNRAware (#7) via Tier-2
(`pdfplumber + LLM`)) and verify the equation-aware prompt variant correctly
populates the new fields:
- (a) `key_equations_md` holds correct LaTeX for the six Tier-1 papers
  (cross-check against raw `.tex`); for SNRAware (PDF-only), Tier-2 produces
  a usable best-effort extract;
- (b) `pseudocode_md` holds the algorithm structure, preserved;
- (c) `extraction_method` is correctly set per paper (`arxiv_source` for the
  Tier-1 inputs; `pdfplumber_llm` for SNRAware) and propagated through the
  response envelope to the node and reflected in the final `PaperExtract`.
Show the full `PaperExtract` JSON for all seven papers before closing
Commit 2c. This is a targeted re-run of Checkpoint B for the new fields at
corpus scale (= the §10 Phase 1 partial run).

---

## Commit 2d — equation-/pseudocode-aware synthesis prompt

**Goal**: Teach the synthesis prompt to use 2c's new `PaperExtract` fields
(`key_equations_md`, `pseudocode_md`, `extraction_method`) so the synthesis
LLM quotes equations and algorithm fragments **directly inside
`ExpertContextItem.content`** — primarily in the **Mechanism** section,
occasionally in **Adaptation**. The equation reaches the proposer as a
literal part of the finding's content string; the proposer reads one
channel (`expert_context`) and the math travels with the citation.

### Hard invariants (locked)

- `LiteratureReviewOutput` is **unchanged**. No `reference_library` field.
  No new field of any kind. The four `ExternalAgentOutput` channels
  (`findings`, `new_vocab_candidates`, `suggested_mindset`, `agent_card`)
  stay exactly as they are, plus the existing audit-trail fields
  (`retrieved_papers`, `search_rounds_used`, `run_name`, timestamps).
- `ProposalInput` is **unchanged**. No `reference_library` field, no
  `reference_library_md` field, no new field of any kind.
- `agent/schemas/proposal.py` imports **nothing** from
  `agent/schemas/literature_review.py`. `PaperReference` does not exist
  and will not be added. `PaperExtract` stays in
  `agent/schemas/literature_review.py` and is not exported anywhere new.
- `reference_library`, if it exists at all in 2d, is **transient
  node-internal scratch state** — a `source_ref → PaperExtract` lookup the
  node may build during `synth()` to populate the synthesis prompt's
  per-paper block. Not on the output schema, never serialised, never
  written to disk, never spread into a protocol kwarg.
- The only producer-side change is the synthesis prompt (the system `.md`
  + the `render_synthesis_prompt` per-paper formatter + the node-side
  assembly site that builds the per-paper dict). The proposer side is
  untouched.
- **Word budgets stay as-is.** `findings_verbosity=1`'s per-section caps
  (Implication ≤40w, Mechanism ≤80w, Adaptation ≤50w) are not modified
  in this commit. Modify only if real §10 Phase-2 runs show the caps
  squeeze out equation quotes — not pre-emptively.

### Files

- Edit: `agent/prompt_templates/literature_review/__init__.py`
  (`render_synthesis_prompt` — extend the per-paper block to include
  `key_equations_md`, `pseudocode_md`, and `extraction_method` from each
  cited paper's `PaperExtract`)
- Edit: `agent/prompt_templates/literature_review/synthesis_system.md`
  (instructions to the LLM: quote Tier-1 equations verbatim inside the
  Mechanism section; flag Tier-2 quotes as paraphrased / approximate;
  preserve fenced pseudocode blocks where the algorithm itself is the
  mechanism)
- Edit: `nodes/ml_literature_review.py` (build the transient
  `source_ref → PaperExtract` scratch lookup at synthesis time; pass the
  extra fields through to `render_synthesis_prompt`. **No schema change,
  no change to `LiteratureReviewOutput(...)` construction.**)
- Edit: `tests/unit/agent/prompt_templates/test_literature_review_prompts.py`
  (assert the rendered prompt contains the new fields and the new
  per-tier instructions)

**Explicitly NOT changed** in 2d (to make the invariants concrete):
`agent/schemas/proposal.py`, `agent/schemas/literature_review.py`,
`agent/schemas/external_agents.py`, `agent/prompt_templates/proposal/__init__.py`,
`ml_model_proposal_agent.py`. Touching any of these would violate the
zero-schema-change invariant.

### Checklist

- [ ] Verify the existing `papers: list[dict]` parameter on
      `render_synthesis_prompt` and confirm where in the node the dict is
      assembled today. Add `key_equations_md`, `pseudocode_md`, and
      `extraction_method` to each per-paper dict at the assembly site.
- [ ] Extend `render_synthesis_prompt`'s per-paper block formatter to
      emit the new fields when non-empty. Tier-2 papers get an
      `extraction_method: pdfplumber_llm (best-effort)` marker; Tier-1
      papers get `extraction_method: arxiv_source (ground-truth LaTeX)`;
      `abstract_only` papers naturally have nothing to emit.
- [ ] Update `synthesis_system.md`:
  - Mechanism section instructions: when the cited paper has a non-empty
    `key_equations_md` AND `extraction_method` is `arxiv_source`, quote
    the relevant equation verbatim inside the Mechanism block (Markdown
    LaTeX preserved). When `extraction_method` is `pdfplumber_llm`, the
    equation may be quoted as a paraphrase — must be flagged
    ("approximate equation, reconstructed from a degraded PDF") rather
    than presented as ground truth.
  - Pseudocode rule: if the algorithm IS the mechanism (e.g. TADA's
    Scale-Targeting), reproduce the relevant 3–8 lines of pseudocode
    inside the Mechanism block as a fenced code block. Otherwise just
    name the algorithm and cite.
  - Abstract-only citations: no equation quotes, no pseudocode.
- [ ] Unit tests:
  - `render_synthesis_prompt` injects `key_equations_md` into the
    per-paper block when the paper has it.
  - `render_synthesis_prompt` injects `extraction_method` per paper.
  - The Tier-1 / Tier-2 / abstract-only instruction blocks all reach the
    rendered system prompt.
  - Existing synthesis-prompt tests still pass unchanged (no regression
    in confidence rubric / omission rules / content format wiring).
- **No schema test changes** — `LiteratureReviewOutput` and
  `ProposalInput` are untouched.

### Test gate

```
.venv/bin/python -m pytest \
  tests/unit/agent/prompt_templates/test_literature_review_prompts.py \
  tests/unit/agent/ml_literature_review/ -q
.venv/bin/python -m ruff check \
  agent/prompt_templates/literature_review/__init__.py \
  nodes/ml_literature_review.py
.venv/bin/python -m ruff format --check \
  agent/prompt_templates/literature_review/__init__.py \
  nodes/ml_literature_review.py
.venv/bin/python -m pyright \
  agent/prompt_templates/literature_review/__init__.py \
  nodes/ml_literature_review.py
```

### §10 trigger

Before closing 2d: run §10 Phase 2 on the §10.2 corpus end-to-end. The
new acceptance bullets (see §10.4 Phase 2 and §10.5 in
`external_agents_for_proposer.md`) require findings citing Tier-1 papers
to quote equations verbatim inside `content` (typically Mechanism) and
findings citing Tier-2 papers to flag the equation as paraphrased. This
is the **first FULL §10 run** — the suite is now fully runnable per the
§10.4 callout. Promotion of the artifact into
`docs/validation_suite_runs.md` happens in a separate sign-off commit
after operator review.

#### 🔍 Behavioral Checkpoint G — Final synthesis output quality

Run §10 Phase 2 on the corpus with 2d shipped. **Show the rendered
`ExpertContextItem` content for every finding before proceeding.** Verify:

- (a) For each finding citing a Tier-1 paper (#1–#6 plus any v=1
  search-found Tier-1 paper) that has a non-empty `key_equations_md`:
  the finding's `content` quotes at least one equation verbatim,
  typically inside **Mechanism**. The LaTeX matches the source (no
  hallucination, no silent edits).
- (b) For each finding citing a Tier-1 paper with non-empty
  `pseudocode_md` *where the algorithm IS the mechanism*: the finding's
  `content` reproduces the relevant 3–8 lines as a fenced code block.
- (c) For each finding citing a Tier-2 (`pdfplumber_llm`) paper —
  including SNRAware (#7) — equations are quoted as paraphrased /
  approximate (explicit flag like "approximate equation, reconstructed
  from a degraded PDF"), not as ground truth.
- (d) For each finding citing an `abstract_only` paper: no equation
  quotes. The Mechanism describes the method in prose only.
- (e) **Implementability bar.** For at least the majority of v=1-cited
  findings, a proposer reading only the `ExpertContextItem` (not the
  source paper, not the `PaperExtract`) knows *how to implement* the
  method — names specific layer types / equation form / training regime,
  not just *that a method exists*.
- (f) **Measurable improvement over pre-2d findings.** Compared to the
  2c-c.2 §10 Phase-1 artifact (`docs/validation_suite_runs.md` post-
  promotion of 2c-c.2's artifact, when available), the 2d findings carry
  noticeably more concrete equation / pseudocode content for the same
  cited papers.

This checkpoint **gates whether equations are arriving inside finding
`content` at usable fidelity**, which is the entire point of Commit 2d.
The earlier-planned `reference_library`-population check (cancelled) is
explicitly replaced by Checkpoint G. Do not close Commit 2d until signed
off.

### Resolved open questions (post-2c-c.2 revision)

- No schema changes on either side: `LiteratureReviewOutput` keeps its
  four channels; `ProposalInput` is untouched. Confirmed.
- Equations reach the proposer inside `ExpertContextItem.content`, not
  via a parallel channel. Confirmed.
- `reference_library` is node-internal scratch state only, scoped to
  `synth()`. Not output, not serialised, not on disk. Confirmed.
- Word budgets unchanged for now; revisit only if real Phase-2 runs show
  they squeeze out equation quotes. Confirmed.
- `PaperReference` schema does not exist. `render_reference_library`
  function does not exist. Both were cancelled in the 2d revision and
  must not be reintroduced.

---

## Commit 3 — Finalize `PaperExtract` + LLM compression prompt

**Goal**: Replace the provisional `PaperExtract` with the field set the pilot
proved is reliably extractable, and write the LLMBridge compression prompt
that produces it. This commit is **gated on the Commit 2 pilot being
reviewed**.

**Files**:
- Edit: `agent/schemas/literature_review.py` (finalize `PaperExtract`).
- New: `agent/prompt_templates/literature_review/__init__.py` — exports
  `render_paper_extract_prompt(raw_text: str) -> tuple[str, str]`
  (system, user) matching the existing `agent/prompt_templates/proposal/__init__.py`
  pattern.
- Edit: `tests/unit/agent/schemas/test_literature_review_schemas.py` (cover
  any new fields).
- New: `tests/unit/agent/prompt_templates/test_literature_review_prompts.py`.

**Checklist**:
- [x] **Field-name reconciliation (pre-Commit-3, done)** — locked canonical
      `PaperExtract` fields: `title, authors, year, core_idea,
      architecture_details, key_results, relevance_to_task`. Renamed
      `architecture_summary`→`architecture_details` and
      `relevance_to_squid`→`relevance_to_task` across code + the four docs;
      dropped `key_methods` and `limitations` (the latter conflicts with
      `AgentCard.limitations`); `key_findings` is reserved for
      `InterpretationOutput`/`CacheEntry` and must not be reused on
      `PaperExtract`. Gate: `test_literature_review_schemas.py` 25 passed,
      ruff + pyright clean. Committed `a659b47`.
- [x] Read `docs/paper_resolver_pilot.md` end-to-end before changing
      `PaperExtract`.
- [x] **Stop and ask** — conditions evaluated against the pilot; none forced a
      hard stop, all resolved:
  - PDF text too noisy for equations → confirmed (F3): **no `key_equations`
    field**; math captured in prose.
  - Section structure preserved (pilot §2) → `architecture_details` works as a
    single free-text field; no sub-fields needed.
  - Domain-name generality — already RESOLVED pre-Commit-3: `relevance_to_squid`
    → task-agnostic `relevance_to_task`; prompt injects the concrete task.
- [x] Finalize `PaperExtract` fields: locked 7-field set `title`, `authors`,
      `year`, `core_idea` (≤80), `architecture_details` (≤150),
      `key_results` (≤120), `relevance_to_task` (≤100). **No `key_equations`
      / `architecture_diagram_md`** (F3). Word budgets documented in the
      class docstring + per-field `Field(description=...)`.
- [x] Remove the provisional notes (class docstring + `architecture_details`)
      and update the module-level schema docstring.
- [x] Write `render_paper_extract_prompt(raw_text, task_description=SIDERIUS_TASK)`
      in `agent/prompt_templates/literature_review/__init__.py`:
  - System prompt (`paper_extract_system.md`, `{TASK_DESCRIPTION}` placeholder):
    role, 7-key JSON contract, `""` not `null`, per-field budgets, anti-noise
    rules (`(cid:NN)`/margin stamp/affiliations/TOC/despacing), math-in-prose,
    anti-hallucination, and the **generic paper-conditional** frequency-split
    rule (verbatim; not TIDMAD-specific — see decisions below).
  - User prompt: raw text truncated to `MAX_RAW_TEXT_CHARS=120_000` chars
    (~30k tok) with a `[...TRUNCATED...]` marker.
- [x] Unit test: valid dict from mocked `bridge.generate(...)` parses into
      `PaperExtract` (all 7 fields round-trip).
- [x] Unit test: malformed payload (wrong-typed field / non-dict) raises
      `ValidationError` — the validation half (Commit 4 adds the node-level
      `verbosity_achieved=0` / `extract=None` fallback).
- [x] Unit test: `render_paper_extract_prompt` deterministic + content
      asserts (7 keys, freq-split rule, anti-noise, task injection,
      truncation behavior).
- [x] **Real-run test** (`@real_run`): `tests/integration/prompt_templates/test_paper_extract_compression.py`
      resolves TIDMAD live (verbosity=2), compresses via real `LLMBridge`,
      validates into `PaperExtract`. **1 passed**; both extracts shown to the
      user and signed off (Checkpoint B). Artifact: `docs/paper_extract_pilot.md`.

**Implementation notes / decisions (Commit 3):**
- Code-fact corrections (checked, not guessed): (1) `bridge.generate()` returns
  a **parsed dict**, not a string → use `PaperExtract.model_validate(...)`, not
  `model_validate_json`. (2) `llm_bridge.py` imposes **no length cap** — the
  truncation guard lives in `render_paper_extract_prompt`. (3) **No
  `LLMBridge.get_instance()`** — construct `LLMBridge(provider=..., model_id=...)`
  directly. The Checkpoint B snippet below reflects (1)/(3).
- Decision 1 — frequency-split rule phrased **generically/paper-conditional**
  (not TIDMAD-specific): the same prompt also compresses non-TIDMAD search
  papers, where a TIDMAD-named claim would be a hallucination. Generic phrasing
  fires correctly for TIDMAD (which does describe frequency-split) and stays
  silent for papers that don't.
- Decision 2 — truncation cap = **120,000 chars** (~30k tok), `[...TRUNCATED...]`
  marker.
- Decision 3 — real-run test under `tests/integration/` (project convention),
  not the unit folder.
- Decision 4 — task injected via optional `task_description=SIDERIUS_TASK` param.
- **Unit gate result (2026-05-26):** `41 passed` (schema + prompt suites),
  ruff `All checks passed`, pyright `0 errors`.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/schemas/test_literature_review_schemas.py tests/unit/agent/prompt_templates/test_literature_review_prompts.py -q
.venv/bin/python -m pytest tests/integration/prompt_templates/test_paper_extract_compression.py -m real_run -q -s   # opt-in, real S2+LLM call
.venv/bin/python -m ruff check agent/schemas/literature_review.py agent/prompt_templates/literature_review/
.venv/bin/python -m pyright agent/schemas/literature_review.py agent/prompt_templates/literature_review/__init__.py
```
Plus: real-run `PaperExtract` JSON shown to user and approved.

#### 🔍 Behavioral Checkpoint B — Single paper LLM compression quality

**Trigger**: run this after the test gate passes, using the finalised
`PaperExtract` schema and the real LLMBridge.

**How to run**: compress the TIDMAD paper text (from Checkpoint A's
artifact) into a `PaperExtract` and print the result, then repeat on one
additional paper returned by an S2 keyword search:

```python
from agent.prompt_templates.literature_review import render_paper_extract_prompt
from agent.llm_bridge import LLMBridge  # confirm accessor at implementation time
from agent.schemas.literature_review import PaperExtract
import json

bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")  # no get_instance()

# Paper 1: TIDMAD (known root paper)
sys_prompt, user_prompt = render_paper_extract_prompt(tidmad_full_text)
raw = bridge.generate(sys_prompt, user_prompt)  # returns a parsed dict
extract_tidmad = PaperExtract.model_validate(raw)  # NOT model_validate_json
print(json.dumps(extract_tidmad.model_dump(), indent=2))

# Paper 2: top hit from a dynamic search to test generalisation.
search = run_skill(None, mode="search",
                   query="SQUID denoising neural network", limit=5)
other_paper_id = search["data"]["results"][0]["externalIds"].get("ArXiv")
# ... resolve at verbosity=2, then repeat the compression
```

**What to inspect**:
- Does `architecture_details` capture the core technical contribution, or
  does it describe the problem setup instead?
- Does the architecture description contain enough information for a model
  proposer to understand the rough structure (layer types, connectivity
  pattern, key design choices)?
- Does `relevance_to_task` make a specific argument for why this paper is
  relevant to TIDMAD denoising, or is it a generic "this paper is about
  signal processing"?
- Are there hallucinations — claims that cannot be found in the source text?
- Does `architecture_details` correctly qualify all model comparisons with
  "under frequency-split training", and explicitly identify WaveNet as the only
  full-spectrum baseline? If the extract presents FCNet/PUNet/Transformer
  rankings **without** this qualifier, it is a **failed compression** — revise
  the prompt before Checkpoint B can be signed off.
- Are the field lengths appropriate? Too short means information loss; too
  long means the compression is not doing its job. Check each field against
  its documented word budget.
- Is anything important missing that no field captures? This is the signal
  for whether the field list needs to be extended.

**What this decides**: whether the `PaperExtract` schema and compression
prompt are ready for use inside the full node. Specifically:
- If `architecture_details` is consistently vague → tighten the prompt to
  ask explicitly for layer types, input/output shapes, and key
  hyperparameters.
- If `relevance_to_task` is generic → add a task-description injection into
  the compression prompt so the LLM knows what "relevant" means for this
  specific problem.
- If a consistently important category of information (e.g. training
  procedure, data preprocessing) is missing from all fields → add a new
  field before proceeding.
- If hallucinations appear → add an explicit anti-hallucination instruction
  to the prompt and re-run.

**Sign-off requirement**: a human must read both extracts (TIDMAD + one
dynamic search result) and judge whether the output is specific enough to
influence architectural proposals. "Good enough" means: a model proposer
reading **only** the `PaperExtract` (not the original paper) would learn
something concrete and actionable. If not good enough after one prompt
revision, escalate to the user before trying a second revision. **Do not
proceed to Commit 4 until this is signed off.**

- **Hard requirement (domain correctness)**: the frequency-split qualifier check
  above is mandatory. A compression that omits it **cannot proceed to Commit 4**
  regardless of other quality criteria.

**Artifact to commit**: `docs/paper_extract_pilot.md` containing the full
JSON output of both `PaperExtract` instances, the human judgment on each
inspection bullet, and any prompt changes made as a result.

**Outcome (2026-05-26): SIGNED OFF.** Both papers compressed via real
`gpt-4o-mini`: TIDMAD (root) + `arxiv:2308.11644` (dynamic-search hit). Hard
requirement passes on both — the generic frequency-split rule fires for TIDMAD
(qualifying the 6.43 FC-Net score with "under frequency-split training" and
naming WaveNet as the full-spectrum baseline) and stays silent on the vibration
paper (no hallucinated regime). One targeted prompt revision was applied
(regime-on-every-number + per-model mechanism for benchmark papers); see
`docs/paper_extract_pilot.md` §4 for the before/after.

**Open questions / decisions needed**:
- Pilot-dependent (see checklist above): equations field? diagram field?
  domain-generic vs SQUID-specific phrasing?
- Should the compression prompt be the same for all source types, or
  source-aware (e.g. for `source_type=="local"` the user may have written
  domain-specific notes that need different handling)? Lean: same prompt,
  text-content-agnostic. Revisit if pilot disagrees.

---

## Commit 4 — `nodes/ml_literature_review.py` core loop

**Goal**: Ship the lit-review node end-to-end: root-paper resolution
(cache-first), dynamic search loop with terminator, final LLM synthesis →
`LiteratureReviewOutput`.

**Files**:
- New: `nodes/ml_literature_review.py`
- New: `tests/unit/agent/ml_literature_review/__init__.py` (empty)
- New: `tests/unit/agent/ml_literature_review/test_node.py`
- New: `tests/integration/nodes/test_ml_literature_review.py` (Tier-1, `@real_run`)

**Sub-commit split** (decided 2026-05-27): **4a** = node + 2 new prompts + all
unit tests (mocked); **4b** = Tier-1 `@real_run` integration test + Checkpoint C
trace + `docs/dynamic_search_pilot.md`. Mirrors Commit 2/3 staging.

**Checklist** (4a unless marked 4b):
- [x] Read existing nodes and match conventions — confirmed by reading
      `result_interpretation_agent.py` / `ml_model_proposal_agent.py` /
      `ml_hyperparameter_tune_agent.py`. **Two plan assumptions corrected:**
  - Node entry is a **class with `.run()`** (all 5 nodes), not a module-level
    `run()`. Class: `MLLiteratureReviewAgent`. (Checkpoint C snippet below
    updated to class form.)
  - **No `LLMBridge.get_instance()`** — the bridge is built lazily in `run()`
    from `inp.llm_provider`/`inp.llm_model_id` via an injectable
    `bridge_factory` (the tuner's pattern). `generate()` returns a parsed dict
    → `model_validate`. Skill via direct `from …paper_resolver_skill.wrapper
    import run_skill` (single skill → no `importlib` dispatch needed).
- [x] Implement the node as `MLLiteratureReviewAgent.run(inp) -> LiteratureReviewOutput`.
- [x] Root-paper resolution:
  - [x] Cache path `{root_cache_dir}/{sanitized paper_id}.json`
        (`paper_id = "{source_type}:{identifier}"`, non-`[A-Za-z0-9._-]`→`_`;
        `root_cache_dir` is an injectable ctor arg, default
        `reference_data/root_papers_cache`, now gitignored).
  - [x] Cache hit → load `RetrievedPaper`; miss → `run_skill(None, ...)`, build
        `RetrievedPaper`, write cache (skip caching hard errors).
  - [x] verbosity≥1 → compression prompt on full text → `extract`; compression
        failure degrades to metadata-only (`verbosity_achieved=0`).
- [x] Dynamic search loop (new prompt `render_search_decision_prompt`):
  - [x] Each round the LLM emits `{"action": "search"|"escalate"|"done", ...}`
        grounded in `experiment_history` (key_findings + bottlenecks primary;
        explored `model_types` + full-spectrum preference injected). TODO marker
        added at the decision call site.
  - [x] `search` → `run_skill(mode="search", limit=8, verbosity=0)` (metadata);
        `escalate` (per-paper, when `escalation_allowed`) → `run_skill(resolve)`
        + compress that paper. Each non-`done` decision consumes one round.
  - [x] Terminate on `{"done"}` OR `rounds == max_rounds` (hard safety net).
- [x] Final synthesis (new prompt `render_synthesis_prompt`): LLM emits
      `{"findings": [...]}`; node wraps each into `ExpertContextItem`
      (source/kind set by node). `new_vocab_candidates=[]`,
      `suggested_mindset=None` for v1.
- [x] **Synthesis prompt quality** — revise the 4a `render_synthesis_prompt` +
      `_synthesize` to meet this *before committing 4a*. Collection-level prompt
      (reasons across all retrieved papers together, not per-paper). System
      prompt requirements:
  - (a) Present `experiment_history.bottlenecks` + `key_findings` as the PRIMARY
        input — every `ExpertContextItem` grounded in a specific current
        bottleneck/finding, not a generic paper description.
  - (b) Each item states the implication for a current bottleneck. "This paper
        proposes X" is unacceptable; "Given bottleneck Y, finding Z suggests
        trying W" is the target format.
  - (c) Each item carries `confidence` (0.0–1.0). `ExpertContextItem` has no
        rationale field, so the one-line justification for the score is appended
        to `content`.
  - (d) A paper with no actionable relevance to the current bottlenecks gets NO
        item — omission beats a weak/generic item; an empty `findings` list is
        valid output.
  - (e) Every item's `source_ref` must exactly match the `paper_id` of a retrieved
        `RetrievedPaper`; `_synthesize` soft-drops unmatched ids (log + omit
        that item, keep the rest) — see open questions.
  - (f) `new_vocab_candidates` / `suggested_mindset` stay empty for v1 (per
        external_agents §2). The ≥3-paper cross-convergence rule is the
        criterion for a FUTURE version, not v1.
- [x] Build/return `LiteratureReviewOutput`; ISO-8601 UTC `started_at`/`finished_at`.
- [x] Storage dump to `{workspace}/ml_literature_review_{run_name}.json`.
- [x] Unit tests (`tests/unit/agent/ml_literature_review/test_node.py`): full
      run; loop terminates at `max_rounds`; cache hit (resolver not called);
      cache miss (resolver called + cache written); compression fallback
      (`verbosity_achieved==0`, `extract is None`, no raise); storage round-trip;
      **plus** an escalation-path test (search hit → deep-read → extract).
- [x] Synthesis unit tests (added in the 4a revision):
  - [x] mocked synthesis returns a valid `list[ExpertContextItem]` with
        `confidence` scores — all items validate against the schema.
  - [x] papers with no actionable relevance → zero `findings` items (empty list
        valid, must not raise).
  - [x] a `source_ref` not matching any retrieved `paper_id` is soft-dropped —
        assert the bad item is omitted and the well-cited items remain.
  - [x] `render_synthesis_prompt` deterministic content asserts — system prompt
        contains the bottleneck-grounding instruction, the omission-over-weak-item
        rule, the source_ref-matching instruction, and the task-description injection.
**4a gate result (2026-05-27):** 58 unit passed (node + prompt + schema suites),
ruff check + `ruff format --check` clean, pyright 0 errors. Committed `820c548`.

**4b sub-commit ladder** (per `feedback_split_planned_commit_into_git_commits`):
- [x] **4b-code** (`c7860d7`, 2026-05-27): node abstract-only confidence clamp;
      escalation-assessment block in `search_decision_system.md`; `ConfidenceRubric`
      + `render_for_consumer` + propagation to `AgentCard.trust_guidance` (proposal
      `trust_guidance` `max_length` 400→800); Fix A (jargon translation) + Fix B
      (full-spectrum guard) + Fix C (short keyword phrase + zero-hit feedback);
      year override from S2 metadata; `search_llm_provider`/`search_llm_model_id`
      routing; `abstract_only_ceiling=0.79`. 117 unit pass; ruff + format + pyright clean.
- [x] **4b-docs** (`2ec1ae5`, 2026-05-27): §5a (three-tier extraction strategy) +
      §5b (`reference_library` channel) in `external_agents_for_proposer.md`;
      pull-channel paragraph in `external_agents_architecture.md`; Commit 2c + 2d
      sections + status-board reorder in this doc; `nodes/ml_literature_review_README.md`
      stub (first instance of the node-README convention).
      **Supersession (post-2c-c.2):** §5a's three-tier design was cancelled
      in `963b628` (two-tier locked). §5b's `reference_library` channel was
      cancelled entirely in the 2d revision — equations now travel inline
      inside `ExpertContextItem.content`; no separate channel. Both §5a and
      §5b were rewritten in place; `external_agents_architecture.md`'s
      "Mathematical content in reference_library" section was rewritten as
      "Mathematical content travels inline inside findings"; the 2d section
      was rewritten to reflect the new scope (synthesis-prompt update only,
      zero schema changes).
- [x] **4b-final** (`91461a2`, 2026-05-28):
  - [x] **findings_verbosity + three-part content format** (impl 2026-05-27).
        Added `findings_verbosity: Literal[0, 1] = 1` to `LiteratureReviewInput`;
        replaced example + content-format section in `synthesis_system.md` with a
        `{CONTENT_FORMAT_BLOCK}` placeholder; `render_synthesis_prompt` injects
        V1 (three-part Markdown — **Implication:** ≤40 words / **Mechanism:**
        ≤80 words / **Adaptation:** ≤50 words + closing `(rationale: …)`) or V0
        (existing single-paragraph) per the input field. V1/V0 block constants
        live in `agent/prompt_templates/literature_review/__init__.py`
        (`_SYNTHESIS_CONTENT_FORMAT_V1` / `_V0`) so the .md template stays
        neutral. Tests: schema default=1, v=0 accepted, v=2 rejected; rendered
        prompt has the three headings + word budgets at v=1, the existing
        single-paragraph rules at v=0, placeholder gone from both; raw .md
        carries the placeholder only. Gate: **123 unit pass**, ruff + `ruff
        format --check` clean, pyright 0 errors. Awaiting Checkpoint-style
        DeepSeek validation (next bullet) before commit.
  - [x] **Targeted DeepSeek synthesis validation** with `findings_verbosity=1`
        on the Step 6b paper set (22 papers reused from `/tmp/step6b_output.json`;
        `/tmp/synth_v1_validate.py`; ran 2026-05-28T02:34Z). Result: **6 findings,
        all bottleneck-grounded, no frequency-split recs (Fix B holds), all
        confidence in [0.40, 0.79]** (no v0 paper exceeded the clamp ceiling).
        Format compliance: **5/6 with all three labels** (`**Implication:**` /
        `**Mechanism:**` / `**Adaptation:**`); **6/6 with the closing
        `(rationale: ...)`**. One finding (source_ref `doi:10.1109/ICCC68654...`)
        wrote **`**Adaption:**`** (typo) instead of `**Adaptation:**`. Resolved
        2026-05-27 via node-side soft normalization: added
        `_normalize_finding_content_headings` (+ `_FINDING_HEADING_ALIASES` map,
        documented for future variant additions) in `nodes/ml_literature_review.py`,
        applied in `_synthesize` before each `ExpertContextItem` is built. Unit
        test asserts `**Adaption:**` → `**Adaptation:**` and canonical content
        unchanged. **124 unit pass; gate clean.**
  - [x] **Integration test** (`tests/integration/nodes/test_ml_literature_review.py`,
        `@real_run`) — switched to `deepseek` + `skipif DEEPSEEK_API_KEY` (2026-05-28);
        runs with shipped defaults (findings_verbosity=1, transfer_tolerance=moderate);
        one root (TIDMAD), `max_rounds=2`, real S2 + LLMBridge; asserts
        `LiteratureReviewOutput` validates + ≥1 `ExpertContextItem`. Lint-clean +
        collects (not executed here — real-API/network).
  - [x] **Node source-type routing** (unit; 2026-05-28) — added `TestSourceTypeRouting`
        confirming doi / local / openreview root papers route through
        `_resolve_root_paper` → cache → compress with filesystem-safe cache filenames
        (arxiv already covered). (Real-API source-type validation lives at the skill
        level from Commit 2's `@real_run` tests.)
  - [x] **Canonical trace run** (2026-05-28T03Z; `/tmp/canonical_trace.py`,
        `/tmp/canonical_trace_output.json`; ran with `max_rounds=3` per user
        direction, not the originally-planned 2): TIDMAD + SNRAware seeded at
        v1, all-DeepSeek, escalation on, `findings_verbosity=1`. Result:
        **2 findings** (seismic-GAN @0.42, Raman peak-preserving @0.48), both
        with perfect 3/3 format compliance + rationale, all cite_ids match,
        Fix B holds, confidence in [0.40, 0.48]. **Mandatory-escalation block
        fired** (2 ESCALATE decisions logged with reasoning) but neither
        produced a new v1 — Raman PDF unavailable (resolve=partial), SNRAware
        already-v1 (no-op). **Neither v1 root cited in findings**: SNRAware's
        compression `relevance_to_task` explicitly said *"No direct
        applicability to SQUID dark-matter detector signal denoising"* (MRI 2D
        vs 1D SQUID); TIDMAD is the benchmark/dataset paper (no new mechanism).
        Both omissions are correct per the synthesis omission discipline.
        **Clamp's deep-read branch remains unit-test-validated only** — the
        only on-bottleneck v1 candidate (Raman, doi:10.3390/s21144623) was
        identified by the LLM's escalation reasoning but couldn't be deep-read
        because the resolver had no PDF for that DOI; this is precisely the
        failure mode Commit 2c (originally three-tier extraction with a
        Tier-2 marker hook for DOI-only PDFs) was designed to fix.
        **Supersession (post-2c-b):** the marker hook was cancelled (see
        §523 "Why two tiers, not three"). The two-tier cascade fixes this
        failure mode only when the paper has an arXiv ID; DOI-only papers
        like the Raman example remain pdfplumber-extracted (Tier-2) or
        abstract-only.
  - [x] **SynthesisConfig.transfer_tolerance** (impl 2026-05-28). Added
        `SynthesisConfig` (`transfer_tolerance: Literal["strict","moderate","liberal"]
        = "moderate"`; `min_confidence` deliberately NOT duplicated — omit
        threshold stays in `ConfidenceRubric.omit_below`) + `synthesis_config`
        field on `LiteratureReviewInput`. `synthesis_system.md`'s hardcoded
        omission paragraph replaced with a `{OMISSION_RULE}` placeholder;
        `render_synthesis_prompt(synthesis_config=...)` injects strict/moderate/
        liberal blocks from `_SYNTHESIS_OMISSION_RULES` in `__init__.py`; the
        Hard-rules "omission beats a weak item" line softened to defer to the
        tolerance block. Created `configs/lit_review_config.yaml` STUB
        (`synthesis.transfer_tolerance: moderate`; nothing loads it yet —
        Commit 7). Tests: SynthesisConfig default/accept/reject, each tolerance
        block injected, default=moderate, `.md` placeholder-only. **Rationale:**
        strict tolerance omitted cross-domain-but-transferable papers (e.g.
        SNRAware); moderate emits a finding with an explicit Adaptation transfer
        caveat. Gate: **133 unit pass**, ruff + `ruff format --check` clean,
        pyright 0 errors. **Canonical trace being re-run with moderate tolerance
        (supersedes the strict run above).**
  - [x] **Write `docs/dynamic_search_pilot.md`** (saved 2026-05-28, 307 lines).
        Canonical artifact = the **moderate-tolerance full-loop trace** (3
        grounded findings: Raman peak-loss @0.45, TADA adversarial-AE @0.50,
        FreLE freq-loss @0.45 — two cross-domain-with-caveat, demonstrating
        moderate). SNRAware escalated-first but not cited this sample (search-
        vs-synthesis variance, documented §2/§7); §5.1 shows the SNRAware
        v1-finding-with-caveat @0.65 from the isolated moderate comparison.
        Sections: seed summary, loop trace, Checkpoint-C per-bullet verdicts
        (all pass), Fix history 0–12, findings quality, PaperExtract 5×3 track
        check (GW highlight), known limitations (incl. search-vs-synthesis
        variance + transfer-tolerance framing), config summary, sign-off.
        Verified clean (each section once; marker sentence intact).
  - [x] **Checkpoint C sign-off** — signed off 2026-05-28; artifact `docs/dynamic_search_pilot.md`.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/ml_literature_review/ -q
.venv/bin/python -m pytest tests/integration/nodes/test_ml_literature_review.py -m real_run -q   # opt-in
.venv/bin/python -m ruff check nodes/ml_literature_review.py tests/unit/agent/ml_literature_review/ tests/integration/nodes/test_ml_literature_review.py
.venv/bin/python -m pyright nodes/ml_literature_review.py
```
Plus: integration test output reviewed by user.

#### 🔍 Behavioral Checkpoint C — Dynamic search loop behavior

**Trigger**: run this after the test gate passes, using a real
`InterpretationOutput` from the workspace and a real LLM/S2 round trip.

**How to run**: pick the most recent `result_interpretation_*.json` in the
workspace as the experiment-history seed and run the node with
`max_rounds=3`, emitting the full per-round decision trace to stdout. If
the node does not already log every LLM decision, add temporary debug
logging before running the checkpoint (and remove it before the commit
closes).

```python
import json
from pathlib import Path
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    LiteratureReviewInput, DynamicSearchConfig, PaperSource,
)
from nodes.ml_literature_review import MLLiteratureReviewAgent

# Seed: most recent interpretation output from the workspace.
interp_path = sorted(Path("./workspace").glob("result_interpretation_*.json"))[-1]
interp = InterpretationOutput.model_validate_json(interp_path.read_text())

lit_in = LiteratureReviewInput(
    experiment_history=interp,
    root_papers=[PaperSource(source_type="arxiv",
                             identifier="2406.04378", verbosity=1)],
    dynamic_search=DynamicSearchConfig(
        enabled=True, max_rounds=3,
        initial_verbosity=0, escalation_allowed=True,
    ),
    storage=...,  # real workspace
    run_name="checkpoint_c",
    llm_provider="openai", llm_model_id="gpt-4o-mini",
)
out = MLLiteratureReviewAgent().run(lit_in)

# Per the node's contract, every round's decision MUST be printed:
#   - the query string generated for this round
#   - the titles of the papers the S2 search returned
#   - which papers (if any) were upgraded from verbosity=0 to verbosity=1
#   - the termination decision ({"done": true} or {"query": "..."}) + the
#     reasoning string the LLM produced alongside it
```

**What to inspect**:
- Are the search queries specific and grounded in the experiment history?
  A good query looks like *"gated Fourier neural operator 1D signal
  denoising"* or *"low-SNR time-series denoising spectral convolution"*. A
  bad query looks like *"SQUID signal processing neural network"* (too
  generic) or *"TIDMAD denoising"* (will only return papers we already have).
- Does the LLM's query generation visibly use the `key_findings` and
  `bottlenecks` from the `InterpretationOutput`? If the current bottleneck
  is "overfitting in the high-frequency band," does the query reflect that?
- Are the papers selected for verbosity=1 upgrade genuinely more relevant
  than the ones left at verbosity=0? Read the abstracts of both groups and
  judge.
- Does the termination decision make sense, or does the loop stop too early
  (after one round of weak results) or run unnecessarily long?
- Do the retrieved papers overlap significantly with models already in
  `MODEL_REGISTRY` (punet, wavenet, gated_fno, transformer, rnn)? High
  overlap means queries are too generic and rediscovering what we already
  have. Zero overlap across all rounds may mean queries are too narrow.
- Do the `ExpertContextItem` entries in `findings` reference specific
  bottlenecks from the `InterpretationOutput`, or are they generic paper
  summaries that could have been written without reading the experiment
  history? **This is the most important quality signal for the synthesis
  call** — items not grounded in the current experimental context will be
  rationally ignored by the proposer.

**What this decides**: the dynamic search system prompt. Specifically:
- If queries are too generic → add an explicit instruction to the prompt:
  *"your query must reflect a specific architectural gap or failure mode
  identified in the experiment history, not just the general task domain."*
- If the LLM ignores `key_findings` → restructure the prompt to present
  `key_findings` and `bottlenecks` as the primary input, with task
  description as secondary context.
- If termination is too early → add a minimum-rounds requirement or
  rephrase the termination condition.
- If verbosity=1 selection is poor → add an explicit *"justify your upgrade
  decision by citing the specific finding in the abstract that makes this
  paper worth deep-reading"* instruction.
- If `findings` items are not grounded in current bottlenecks → the synthesis
  prompt must more forcefully front-load `bottlenecks` + `key_findings` and
  explicitly forbid generic paper summaries. Revise the prompt and re-run the
  checkpoint before proceeding to Commit 5.

**Sign-off requirement**: a human must read the full loop trace and judge
whether the search behavior is purposeful. "Good enough" means: the queries
are visibly grounded in the specific experimental context, and the papers
retrieved are ones a human ML researcher would actually want to read given
the same experimental history. If the queries are generic across all three
rounds, the system prompt needs revision before proceeding to Commit 5.
**Show the user the full trace before marking this checkpoint done.**

**Artifact to commit**: `docs/dynamic_search_pilot.md` containing the full
loop trace, a 3-5 line human summary of the `InterpretationOutput` used as
input (not the full JSON), and the human judgment on each inspection bullet.

**Checkpoint C — iteration log (2026-05-27; real DeepSeek + OpenAI runs).**
Seed for all runs: real `InterpretationOutput` from
`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v12_0504/iter_014`
(80 experiments, 12 spectral/wavelet architectures; bottlenecks = file-17
under-recovery, optimization-to-metric mismatch, tiny-data robustness). Status:
**Checkpoint C signed off 2026-05-28** — search-robustness fix (Fix C) +
escalation-assessment block (Fix 9) + transfer_tolerance (Fix 12) landed; clean
canonical trace captured in `docs/dynamic_search_pilot.md`.

1. **First run (all gpt-4o-mini): two real failures.** (i) Search queries were
   polluted with project-internal jargon ("file 17", "Impact_Score") → 0-hit /
   junk queries. (ii) Synthesis *recommended frequency-split* (FC-Net) — the F4
   anti-pattern.
2. **Fix A (search prompt: translate internal jargon → general ML terms).** Two
   revisions; reduced but did not fully eliminate the "file"/"late-file" leak on
   gpt-4o-mini (model instruction-following limit). Documented as a residual.
3. **Fix B (synthesis full-spectrum guard).** Added a hard rule: never recommend
   frequency-split / per-band techniques; treat such results as cautionary.
   Worked — subsequent runs correctly cautioned against FC-Net's frequency-split
   score instead of recommending it.
4. **5-paper / 3-track PaperExtract quality check (gpt-4o-mini): PASS.**
   `architecture_details` specific, `key_results` regime-qualified,
   `relevance_to_task` appropriately graded, no hallucinations across main (2),
   application (1), denoising (2) tracks.
5. **Model routing exploration → all-DeepSeek.**
   - search-decision on **deepseek-v4-pro**: clean, consistent, well-targeted
     queries (fixed the gpt-4o-mini jargon-leak variance).
   - compression re-validated on deepseek (same 5 papers): **no empty-content
     failures**, MORE detailed + MORE accurate than gpt-4o-mini — notably caught
     DMF-Net's frequency-split regime that gpt-4o-mini missed.
   - all-DeepSeek attempt: synthesis returned **empty `{"findings": []}`**
     (DeepSeek over-applies the omission rule). Confirmed via raw capture (not a
     bug / source_ref / shape issue — genuinely conservative).
   - **Intervention 1** (verbosity-0/abstract clarification) fixed emptiness, but
     introduced a magic number (`0.5-0.65`) in the prompt.
6. **ConfidenceRubric refactor** (per "Scoring and rubric design invariants",
   `external_agents_architecture.md`). Unified `ConfidenceRubric` Pydantic model
   (3 bands + `omit_below`), injected via `{CONFIDENCE_RUBRIC}`, configurable via
   `LiteratureReviewInput.confidence_rubric`; **zero numbers in the `.md`**.
   Subsumes Intervention 1's magic numbers (abstract-only = the 0.40-0.59 band).
   Word budgets deferred (open question, `external_agents_for_proposer.md` §9).
7. **Year override.** Node overwrites LLM-extracted `year` with `s2_metadata`'s
   value (DeepSeek often leaves year blank) — `_override_year_from_metadata` + test.
8. **Search-variance finding (the current blocker).** Even on DeepSeek the loop
   is high-variance: clean, well-targeted queries sometimes return 0 S2 hits.
   **Direct S2-API check (2026-05-27)** of the three 0-hit queries: raw S2 returns
   `total=0`, **identical to the skill** → not a skill bug; the queries are long
   prose-like phrases too narrow for S2's keyword index (working queries are short
   keyword phrases).
9. **Fix C (APPROVED, pending implementation).** (a) search-prompt guideline:
   short keyword phrase (~3-6 keywords, not a sentence) + good/bad examples;
   (b) zero-hit feedback: pass prior `(query, hit_count)` into each round and
   nudge the LLM to broaden after a 0-hit. Then re-validate + sign off.

**Model decision (current):** `deepseek-v4-pro` for all three LLM steps
(search-decision, compression, synthesis); `ConfidenceRubric` default;
`search_llm_*` split fields kept as dormant capability (all-DeepSeek = main model
deepseek, `search_llm_*` unset).

**Open questions / decisions needed**:
- **Node entry shape.** RESOLVED — class `MLLiteratureReviewAgent` with
  `.run()` (matches all 5 nodes); the bridge is built lazily in `run()` from the
  input via an injectable `bridge_factory`.
- **Synthesis `source_ref` mismatch.** RESOLVED — soft drop (log + omit the item,
  keep the rest); a single hallucinated id must not discard a useful list.
- **`results_per_query`.** RESOLVED — add as a `DynamicSearchConfig` field
  (default 10) with the relevance-drop reasoning in its docstring (S2 relevance
  drops sharply past position ~10; ~10 abstracts ≈ 2k tokens is a manageable
  decision surface). Replaces the 4a node constant `SEARCH_LIMIT=8`.
- **Per-round verbosity escalation cap.** RESOLVED — added
  `DynamicSearchConfig.max_escalations_per_round` (default 2); the loop resets
  the counter on each search round and logs+drops escalation requests beyond
  the cap. Searches consume the round budget; escalations do not.

---

## Commit 5 — Protocol file (audit-only)

**Goal**: Land the per-edge protocol mapping `LiteratureReviewOutput` →
`ProposalInput` channel updates, and **document the audit finding** that
`local_full_context` in the upstream protocol already threads `mindset` and
`agent_cards` end-to-end (no patch needed).

**Files**:
- New: `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`
- New: `tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py`
- **No edit** to `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` —
  the 4-kwarg shape already in place (`expert_context` / `vocab_seed` /
  `agent_cards` / `mindset`) is sufficient. The earlier-planned
  `reference_library` parameter was dropped along with the
  `reference_library` channel cancellation in the 2d revision.

**Checklist**:
- [ ] **Audit step (no code change)**: open
      `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:43-222`
      and confirm `local_full_context` accepts `mindset: str | None` and
      `agent_cards: list[AgentCard] | None` kwargs and maps them into
      `ProposalInput`. Pre-conversation analysis confirmed this; verify
      once more before declaring the audit closed.
- [ ] Write `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`
      matching the conventions in `ml_result_interp_to_ml_model_propose.py`:
  - Module docstring listing implemented vs planned protocols.
  - `local_all_channels(output: LiteratureReviewOutput) -> dict[str, Any]`
    — returns a dict with the **four** kwargs that `local_full_context` expects
    from external agents: `expert_context=output.findings`,
    `vocab_seed=output.new_vocab_candidates`, `agent_cards=[output.agent_card]`,
    `mindset=output.suggested_mindset`. Returns a dict (not a typed object)
    because it gets spread into `local_full_context(**update_dict, ...)`.
    **No `reference_library` / `reference_library_md` kwarg** — that channel
    was cancelled in the 2d revision. Equations reach the proposer inside
    `ExpertContextItem.content`, which already travels through `expert_context`.
  - `database_all_channels(...) -> dict[str, Any]` placeholder that raises
    `NotImplementedError`.
- [ ] Tests:
  - [ ] `local_all_channels` maps all four channels correctly with a fully
        populated `LiteratureReviewOutput`.
  - [ ] `local_all_channels` passes through `new_vocab_candidates=[]` and
        `suggested_mindset=None` without error (v1 wired-empty channels).
  - [ ] `local_all_channels` wraps a single `agent_card` into a list of one
        (the field on `ProposalInput` is `agent_cards: list[AgentCard]`).
  - [ ] `local_all_channels` does NOT emit any `reference_library` or
        `reference_library_md` kwarg (regression guard against the
        cancelled design).
  - [ ] `database_all_channels` raises `NotImplementedError`.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py -q
.venv/bin/python -m ruff check agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py
.venv/bin/python -m pyright agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py
```

**Commit message must include the audit finding**: state that
`local_full_context` already threads `mindset` and `agent_cards` (cite the
line numbers), so no patch to the existing protocol was required.

**Open questions / decisions needed**:
- Function name — `local_all_channels` vs `local_full_context` (mirroring the
  upstream protocol). Lean: `local_all_channels` because the data scope is
  literally the four channels, not the full context. Open to override if the
  convention is to mirror the upstream name.

---

## Commit P — Proposer awareness for external findings

**Status**: retroactive. The Q1–Q7 audit conducted after Commit 5 landed found
four structural problems that prevent the proposer from acting on external
findings in production (pipeline) mode. All four must be fixed before
Checkpoint D fires, otherwise Checkpoint D will fail in known ways and we
will be back here anyway.

**Trigger**: failed structural audit on `_run_pipeline`
(`nodes/ml_model_proposal_agent.py`). See
`docs/external_agents_for_proposer.md` §11 for the audit findings.

**Generic by construction**. None of the changes hardcode agent names
(`ml_literature_review`, `physics`, `human`). All differentiation is by
structural roles (`trust_level`, `source_type`) any future agent can adopt.

**Files**:
- `agent/schemas/proposal.py` — `ExpertContextItem.source_ref` (rename),
  `DiscoveryMemo.source_refs` (rename), `InheritedComponent.source_type` +
  `source_id` (additions; remove `from_model_type`),
  `AgentCard.trust_level` (addition), `ProposalInput.expert_advice` (REMOVE).
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` —
  `human_advice` wrap injects a synthesized `human` `AgentCard`.
- `agent/prompt_templates/proposal/__init__.py` — `render_agent_cards`
  surfaces `Trust Level`; `render_expert_context` uses `source_ref`.
- `agent/prompt_templates/proposal/causal_reasoning_stage.md` — Rule 1
  rewrite; new MANDATORY synthesis section; remove hardcoded trust hierarchy.
- `agent/prompt_templates/proposal/comparison_stage.md` — weaken Rule 4;
  remove hardcoded trust hierarchy.
- `agent/prompt_templates/proposal/*_explore.md` /
  `agent/prompt_templates/proposal/*_exploit.md` (6 files) — rewrite Contract
  Hierarchy to point at synthesis rules in the base prompt.
- `nodes/ml_model_proposal_agent.py` — call `_render_hardware_context_block`
  and a new `_render_constraints_block` from `_run_pipeline`; reorder block
  appends (cards + context BEFORE candidate markdown, hardware + constraints
  ABOVE that).
- `nodes/ml_literature_review.py` — emitted `AgentCard` declares
  `trust_level="soft_prior"`.
- Every test / doc / cache that referenced the pre-rename `cite_id` /
  `citation_sources` / `citation_source` (36 files — see P-a blast
  radius below).

### Sub-commit ladder

The ladder is **design-doc-first**: this section (and §11 of the spec doc)
is committed BEFORE any code change. Each subsequent code commit reads from
this section as its scope contract.

#### P-design *(this commit — doc-only)*

Scope: this section + new §11 of `docs/external_agents_for_proposer.md` +
vision-doc §4 amendment placeholder (the actual vision-doc edit is in P-e).
No code touched. Establishes the design contract in tree so code commits
can be reviewed against it.

#### P-a — `cite_id` → `source_ref` rename
Pure mechanical rename across 36 files (319 occurrences; the initial
estimate of 28 / 247 in P-design was based on a `cite_id`-only grep and
undercounted `citation_sources` / `citation_source` hits and 8 small
files: 6 advice JSONs in `advice/workflow/`, 1 pseudo-data JSON, and
`agent/llm_bridge.py`). Includes
`DiscoveryMemo.citation_sources` → `source_refs` and
`InheritedComponent.citation_source` → `source_ref`. Zero behavior change
at LLM level — same data, different key name.

Gate: full unit suite green (`tests/unit/`);
`git grep -lE "cite_id|citation_source"` returns only
`docs/audit/unit_tests_rubric_audit.md` (the standing exclusion) and this
commit-plan doc itself (where the pre-rename names appear as explanatory
text describing the rename).

#### P-b — Schema additions
`AgentCard.trust_level: Literal["hard_limit", "strong_prior", "soft_prior"]`.
`InheritedComponent.source_type: Literal["experiment", "external_agent", "human"]`
+ `source_id: str`. Hard-remove `InheritedComponent.from_model_type` (breaking
change; tests must update; no production callers since SIDERIUS has no
external API consumers). `render_agent_cards` outputs `Trust Level: <level>`
on every card. Lit-review's emitted card declares `trust_level="soft_prior"`.

Gate: new schema unit tests; existing tests updated to populate new required
fields.

#### P-c — Prompt rewrites
Rewrite `causal_reasoning_stage.md` Rule 1 to be source-attributable rather
than ModelComparison-only. Weaken `comparison_stage.md` Rule 4 to allow
literature signals to influence the comparison, with provenance recorded
explicitly. Insert new MANDATORY "Multi-source synthesis" section in
`causal_reasoning_stage.md` between the existing MANDATORY block (ends line
69) and the `## What you produce` section (starts line 70). Remove hardcoded
literature/physics/human trust hierarchy from both stage prompts (lines
21-26 of `causal_reasoning_stage.md` and 23-28 of `comparison_stage.md`).
Replace with one generic line referencing `Trust Level` on cards. Rewrite
Contract Hierarchy in all six `*_explore.md`/`*_exploit.md` files to point
at the synthesis rules instead of the now-dead "Advice JSON".

Gate: prompt-template snapshot tests; `_check_citation_discipline` regression
test still passes with renamed field.

#### P-d — Pipeline-mode dead-field fixes + position-bias fix
Add `_render_constraints_block(constraints, existing_model_types)` helper.
Call both `_render_hardware_context_block` and `_render_constraints_block`
from `_run_pipeline`. Reorder per-stage user-prompt assembly so the order is:

1. `[HARDWARE CONTEXT]` block
2. `## Constraints` block
3. `## External Contributors` (`agent_cards_block`)
4. `## Expert Context` (`expert_context_block`)
5. Candidate markdown + `## Accumulated context` JSON
6. Vocab block (reasoning stages only)

Hard-remove `ProposalInput.expert_advice` (the field, all its render calls,
all its references in tests/docs). The `human_advice` wrap in
`ml_result_interp_to_ml_model_propose.py:131-141` additionally injects a
synthesized `human` `AgentCard` so the wrapped `ExpertContextItem` carries
proper trust framing under the new structural rules.

Gate: existing proposal-agent unit tests pass after fixture updates; new
test asserting that the assembled user prompt in pipeline mode contains
`[HARDWARE CONTEXT]` and `## Constraints` strings when corresponding inputs
are present.

#### P-e — Doc + status-board updates
Vision doc `external_agents_architecture.md` §4 update for structured
`trust_level`. Close §9 open question 1. Commit-plan status board ticks for
P-a/P-b/P-c/P-d. Node README `nodes/ml_literature_review.md` Parameter
Reference adds an entry for the emitted `AgentCard.trust_level`.

Gate: doc-only, no test gate; lockstep tick of status board with the four
preceding sub-commits.

### Test gate (whole-Commit-P)

```
.venv/bin/python -m pytest tests/unit/ -q
.venv/bin/python -m ruff check <every file P-a/P-b/P-c/P-d touched>
.venv/bin/python -m ruff format --check <every file P-a/P-b/P-c/P-d touched>
.venv/bin/python -m pyright <every code file P-a/P-b/P-c/P-d touched>
```

Plus **Checkpoint P** below.

#### 🔍 Behavioral Checkpoint P — Proposer pipeline-mode prompt audit (offline)

Render the assembled user prompt + system prompt for each stage in pipeline
mode using a synthetic `ProposalInput` that contains:

- one literature `ExpertContextItem` with a non-`experiment` `source_ref`
  and an `AgentCard(trust_level="soft_prior")`
- one non-empty `constraints` list
- one `HardwareContext` manifest (GPU available)
- one `human_advice` string

Inspect the rendered prompts by eye and verify:

- (P.1) `[HARDWARE CONTEXT]` block renders at the top of every stage's user
  prompt.
- (P.2) `## Constraints` block renders right below `[HARDWARE CONTEXT]`.
- (P.3) `## External Contributors` block renders next, with `Trust Level:
  soft_prior` visible on the lit-review card and `Trust Level: strong_prior`
  visible on the synthesized `human` card.
- (P.4) `## Expert Context` block renders next, with the literature finding
  carrying its `source_ref` and the wrapped human directive carrying
  `source_ref=human:human_advice` (post-rename).
- (P.5) Candidate markdown + accumulated JSON renders below all of the
  above.
- (P.6) `causal_reasoning_stage.md` system prompt contains the new
  MANDATORY synthesis section and the rewritten Rule 1; no hardcoded
  "Literature agents / Physics agents / Human directives" text remains in
  the system prompt.
- (P.7) No `expert_advice` field appears anywhere in the rendered prompts;
  no `cite_id` field name appears (all renamed to `source_ref`).

**Sign-off requirement**: a human reads the rendered prompts and confirms
all seven sub-criteria PASS. Artifact: `docs/proposer_prompt_audit.md`.

**Cost**: zero LLM calls. The audit is purely textual on the rendered
strings. Cheap and fast; gates Commit 6 from starting.

**Why this checkpoint precedes Checkpoint D**: Checkpoint D requires real
LLM runs and is expensive. Checkpoint P is free and catches structural
problems Checkpoint D would otherwise re-discover. Failing Checkpoint P
means re-iterate the prompts before spending on Checkpoint D.

---

## Commit 6 — Workflow integration

**Goal**: Wire the lit-review call into `workflows/model_exploration.py`
between interpretation and proposal, with `merge_external_agent_outputs` as
the (currently single-input) aggregator and `should_run_literature_review`
as the always-true trigger.

**Files**:
- Edit: `workflows/model_exploration.py`
- Edit: `configs/lit_review_config.yaml` (stub created in 4b-final; Commit 6 fills
  in the full runtime config with root_papers, dynamic_search, and synthesis blocks)
- New: `reference_data/root_papers_cache/README.md`
- New: `tests/unit/workflows/test_model_exploration_lit_review_wiring.py`
- Edit (possibly): existing Tier-0 dual-mode workflow test to cover the new
  insertion point (depending on test design — confirm before editing).

**Checklist**:
- [ ] Read `workflows/model_exploration.py` end-to-end and **show the user
      the insertion point** (post-interpretation, pre-proposal loop) with
      surrounding line numbers before patching.
- [ ] Add `merge_external_agent_outputs(outputs: list[ExternalAgentOutput]) -> dict[str, Any]`
      as a module-level function in `workflows/model_exploration.py` (or a
      sibling helper file if that's the convention; check the file's
      existing helper placement). Behaviour:
  - **N=1 case**: equivalent to calling the per-agent protocol's
    `local_all_channels(outputs[0])` directly — the Commit 5 protocol at
    `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`
    already produces the 4-kwarg shape this merge returns. The merge
    function should `from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import local_all_channels`
    and delegate for N=1; the merge logic only fires for N>=2. Avoids
    duplicating the per-agent → 4-kwarg mapping.
  - **N>=2 case** (no v1 caller; future-facing):
    - `findings`: concatenate across outputs. Findings already carry their
      cited paper's equations / pseudocode inline inside `content` (per the
      2d revision); the merge does not need any equation-specific handling.
    - `new_vocab_candidates`: concatenate.
    - `agent_cards`: one card per output, accumulated.
    - `suggested_mindset`: last non-None wins (documented as a v1 rule; flagged
      for revisit when the second agent populates this — see §9 Q2 of the
      architecture doc).
  - **N=0 case**: returns the empty default
    (`expert_context=[], vocab_seed=[], agent_cards=[], mindset=None`).
    The proposer's downstream caller handles empty as "internal-only run".
  - Returns the **four-kwarg** dict directly consumable by `local_full_context`.
    The earlier-planned 5th `reference_library` kwarg was cancelled in the
    2d revision — equations now travel inline inside finding `content`, so
    the merge has nothing extra to concatenate beyond the four channels.
- [ ] Add `should_run_literature_review(interp_output: InterpretationOutput, *, enabled: bool) -> bool`:
      reads the resolved `enabled` flag (CLI → YAML → default True). For v1
      the gate is just `return enabled` — `interp_output` is reserved for
      future content-based gating (e.g. "skip lit-review when interpretation
      confidence > 0.9"). Docstring includes the cost-tradeoff note from
      spec §6.

  **Two-layer enable/disable gate** (Risk 4 resolution, P-design 2026-06-09):
  - **YAML layer** (`configs/lit_review_config.yaml`): top-level
    `enabled: bool` defaulting to `True`. Operators edit the YAML to
    disable lit-review for an entire experiment chain.
  - **CLI layer** (`run_one_iteration.py` / `run_chain.sh`): add a
    `--lit_review_enabled` / `--no-lit_review_enabled` pair via
    `argparse.BooleanOptionalAction`. Overrides the YAML default for a
    single run without editing the config file.
  - **Resolution priority**: CLI flag (when explicitly set) >
    YAML `enabled` > default `True`. The workflow resolves this in one
    place before calling `should_run_literature_review`, then passes the
    resolved boolean as a kwarg.
  - **Scope**: the CLI flag controls **enable/disable only**, not the
    lit-review parameters. `root_papers`, `dynamic_search`, `synthesis`,
    `confidence_rubric`, etc. all stay in the YAML — config-file-only.
    This keeps the CLI surface manageable; operators wanting parameter
    tweaks edit the YAML.
- [ ] Load `configs/lit_review_config.yaml` at workflow startup (path resolved
      relative to project root via the same mechanism the workflow already
      uses for other configs — grep for `yaml.safe_load` to confirm). Convert
      the parsed dict into `LiteratureReviewInput` minus the
      `experiment_history` field (filled in per-iter from interp output).
- [ ] At the per-iteration insertion point:
  ```
  interp_output = result_interpretation_agent.run(...)
  lit_review_enabled = _resolve_lit_review_enabled(cli_args, lit_review_config)
  if should_run_literature_review(interp_output, enabled=lit_review_enabled):
      lit_input = build_lit_review_input(lit_review_config, interp_output, ...)
      lit_output = ml_literature_review.run(lit_input)
      external_outputs = [lit_output]
  else:
      external_outputs = []
  external_channels = merge_external_agent_outputs(external_outputs)
  for attempt in range(1, max_proposal_attempts+1):
      proposal_input = local_full_context(
          interp_output,
          attempt_storage,
          human_advice=human_advice_propose,  # P-d wrap path stays alive
          **external_channels,                # P-c/P-d channels: expert_context, vocab_seed, agent_cards, mindset
          # ...other existing run-level kwargs (is_trial / trial_strategy /
          # trial_time_budget_minutes / hardware_context / vram_budget_gb / etc.)
      )
      ...
  ```
  **Important: `human_advice=human_advice_propose` stays as a kwarg
  alongside `**external_channels`.** The P-d wrap path (in
  `ml_result_interp_to_ml_model_propose.local_full_context`) handles the
  `human_advice` value by wrapping it into an `ExpertContextItem` and
  injecting a synthesized `human` `AgentCard` with
  `trust_level="strong_prior"`. Dropping `human_advice` here would lose
  the only path human directives reach the proposer.
- [ ] Flesh out `configs/lit_review_config.yaml` (a stub exists from
      Commit 4b-final containing only the `synthesis.transfer_tolerance`
      block; the stub's note "Commit 7 will flesh out" is **outdated** —
      Commit 6 does this, Commit 7 just adds the cache README + audit).
      Replace the stub with:
  ```yaml
  # Top-level enable/disable flag — Risk 4 two-layer gate. Operators may
  # also override at the CLI via --no-lit_review_enabled / --lit_review_enabled
  # without editing this file.
  enabled: true

  root_papers:
    - source_type: arxiv
      identifier: "2406.04378"      # TIDMAD
      verbosity: 1
  dynamic_search:
    enabled: true
    max_rounds: 3
    initial_verbosity: 0
    escalation_allowed: true
  synthesis:
    transfer_tolerance: moderate    # preserved from the 4b-final stub
  ```
- [ ] Create `reference_data/root_papers_cache/README.md` explaining: format
      (one JSON file per paper, named `{paper_id}.json`, content is a
      serialized `RetrievedPaper`), invalidation (delete the file manually
      to force re-fetch + re-compression), and the contract with the
      lit-review node (`DEFAULT_ROOT_CACHE_DIR` constant at
      `nodes/ml_literature_review.py:61` points here by default).

  **Risk 5 resolution (P-design 2026-06-09)**: only the README is
  committed in Commit 6 — NOT the cache files themselves. Production
  runs populate the cache via the S2 + extraction path on first run;
  subsequent runs hit the cache. Operators wanting bit-for-bit
  reproducibility can manually copy the Phase-1 pilot cache files from
  `reference_data/lit_review_pilot_cache/` (the gitignored pilot cache
  the Phase-1 / Phase-2 / §10 FULL tests use) into
  `reference_data/root_papers_cache/`. We may revisit committing the
  files if reproducibility issues from S2 variability become a problem.
- [ ] Tests (`tests/unit/workflows/test_model_exploration_lit_review_wiring.py`):
  - [ ] `merge_external_agent_outputs([single_output])` returns the four
        channels mapped correctly.
  - [ ] `merge_external_agent_outputs([])` returns the empty default
        (`findings=[], new_vocab_candidates=[], agent_cards=[], mindset=None`).
  - [ ] `merge_external_agent_outputs([a, b])` — concat-then-last-wins for
        mindset; concatenation for the list channels.
  - [ ] `should_run_literature_review(...)` returns `True` for an arbitrary
        `InterpretationOutput`.
  - [ ] Wiring smoke test: with `ml_literature_review.run` mocked to return
        a canned `LiteratureReviewOutput`, invoke the per-iter section and
        assert the `ProposalInput` arriving at the proposer has the expected
        `agent_cards` and `expert_context` entries.
- [ ] **Extend an existing dual-mode test to cover the lit-review insertion
      point** (Risk 6 resolution, P-design 2026-06-09 — do NOT just rely
      on the wiring smoke test). Candidates from
      `tests/integration/workflows/`: `test_k9_invented_model_dual_mode.py`
      or `test_n_recent_gate_exhaustions_dual_mode.py`. The extension
      mocks `MLLiteratureReviewAgent.run` to return a canned
      `LiteratureReviewOutput` and asserts the per-iteration
      `ProposalInput` carries the expected `agent_cards` + `expert_context`.
      Catches workflow-level wiring regressions for free on every
      dual-mode CI run.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/workflows/test_model_exploration_lit_review_wiring.py -q
.venv/bin/python -m pytest tests/unit/workflows/ -q   # full workflow unit dir to catch wiring regressions
.venv/bin/python -m ruff check workflows/model_exploration.py configs/lit_review_config.yaml tests/unit/workflows/test_model_exploration_lit_review_wiring.py
.venv/bin/python -m pyright workflows/model_exploration.py
```

**§10 prerequisite** (before Checkpoint D): full §10 suite must pass — §10.6
makes it a prerequisite for Checkpoint D. Re-run the full suite if any prompt
/ `ConfidenceRubric` / `transfer_tolerance` default has changed since the
Commit-2d full run. Record in `docs/validation_suite_runs.md`.

#### 🔍 Behavioral Checkpoint D — End-to-end proposer behavior change

**Trigger**: run this after the test gate passes. This is the
highest-stakes checkpoint — it decides whether the entire lit-review
addition produces a measurable, traceable improvement in the proposer's
output.

**Cost callout (Risk 7, P-design 2026-06-09)**: Checkpoint D runs **two
complete workflow iterations** (Run A lit-review ON, Run B OFF) on the
same starting state. Each iteration touches the proposer LLM + the
lit-review pipeline + downstream tuner gates. **Realistic per-iteration
cost: $1-6 each → $2-12 total for the A/B**, plus the §10 FULL
prerequisite re-run ($1-6) if any prompt / `ConfidenceRubric` /
`transfer_tolerance` default has changed since the most recent §10 FULL
sign-off. Operator should be aware before scheduling.

**How to run**: run two complete workflow iterations back-to-back using the
same starting state (same model, same experiment history, same seed):

```python
# Run A: lit review ON.
proposal_A = run_one_iteration(
    base_state, should_run_literature_review_override=True,
)

# Run B: lit review BYPASSED (patch the gate to return False).
proposal_B = run_one_iteration(
    base_state, should_run_literature_review_override=False,
)

print("== Run A (lit review on) ==")
print(proposal_A.model_dump_json(indent=2))
print("== Run B (lit review off) ==")
print(proposal_B.model_dump_json(indent=2))
```

Print the full `ProposalOutput` from both runs — specifically the proposed
architecture description and the reasoning trace.

**What to inspect**:
- Does Run A's proposal reference any specific technique, paper finding, or
  architectural concept that came from the `ExpertContextItem` list? Look
  for concrete traces: a specific method name, a training trick, a design
  rationale that could only have come from the literature.
- Does Run B produce a qualitatively different proposal, or is it
  essentially the same with the literature references stripped out?
- Are the `source_ref` values in Run A's reasoning real — do they match actual
  `source_ref` values from `LiteratureReviewOutput.findings`? Or has the
  proposer hallucinated citations?
- Does the proposal in Run A feel more grounded and specific, or does the
  literature just add decorative references to an otherwise unchanged
  proposal?
- Check the `expert_context` block that was passed to the proposer: are the
  `ExpertContextItem` entries specific enough to be actionable, or are they
  generic enough that a proposer would rationally ignore them?

**What this decides**: whether the end-to-end system is working. This is
the highest-stakes checkpoint. Possible failure modes and responses:
- If Run A and Run B proposals are nearly identical → the
  `ExpertContextItem` content is too abstract, or the proposer's system
  prompt does not give literature findings enough weight. Fix: either
  tighten the `ExpertContextItem` generation prompt in
  `ml_literature_review`, or add an explicit instruction in the proposer's
  system prompt to engage with literature findings before proposing.
- If Run A has hallucinated `source_ref`s → the proposer is generating
  plausible-sounding references rather than using the actual ones. Fix: add
  an explicit instruction to the proposer to only cite `source_ref` values
  that appear in the provided `expert_context` block.
- If Run A's proposal is more specific but the specificity comes from the
  `AgentCard` trust framing rather than the actual findings → the findings
  themselves are too weak. Return to Checkpoint B and tighten the
  compression prompt.
- If Run A is clearly better and the improvement is traceable to specific
  `ExpertContextItem` entries → the system is working.

**Sign-off requirement**: a human must read both proposals side by side and
make a judgment: does the literature review produce a meaningful, traceable
improvement in proposal quality? "Good enough" does *not* mean Run A is
always better — it means the influence of the literature is visible and
grounded in real retrieved content. If the system fails this checkpoint,
**do not merge the workflow integration into the main branch** until the
root cause is identified and fixed. **Show the user both proposals before
marking this checkpoint done.**

**Artifact to commit**: `docs/e2e_behavior_pilot.md` containing: the
`LiteratureReviewOutput` summary (agent card + top 3 findings), the Run A
proposal summary, the Run B proposal summary, a side-by-side diff of the
key differences, and the human judgment on whether the improvement is real
and traceable.

**Open questions / decisions needed**:
- Helper placement: `merge_external_agent_outputs` and
  `should_run_literature_review` — module-level in `model_exploration.py`,
  or a new `workflows/external_agents_helpers.py` file? Lean: module-level
  for v1 (one call site, one external agent). Refactor when the second
  agent lands.
- `build_lit_review_input` lives where? Probably a small helper near the
  config load. Open: should it be its own function or inline? Lean: small
  named function — easier to unit-test the config-merge logic.
- Tier-0 dual-mode coverage: does any existing dual-mode test exercise the
  interpretation → proposal handoff? If yes, extend it; if no, the wiring
  smoke test in this commit is the only gate at this layer.

---

## Commit 7 — Configs, cache directory, full connection audit

**Goal**: Final polish — confirm the cache README is complete, run the
end-to-end connection audit per spec §8 step 8, and make sure no existing
test broke anywhere in the repo.

**Files**:
- Possibly edit: `configs/lit_review_config.yaml` (final tuning of defaults).
- Possibly edit: `reference_data/root_papers_cache/README.md` (final wording).
- Edit: `docs/external_agents_for_proposer.md` §9 to mark resolved open
  questions.
- Edit: `docs/commit_plan_ml_literature_review.md` (this file) — mark all
  boxes `[x]` and note the commit hash in the status board.

**Checklist**:
- [ ] **Connection audit** — write the audit results as a markdown table
      directly in the commit message (and a copy in §9 of the spec doc):
  - Every field on `ProposalInput` that lit-review touches: where it comes
    from (which `LiteratureReviewOutput` field, via which protocol function,
    via which workflow merge entry).
  - Every field on `LiteratureReviewInput`: how the workflow populates it.
  - Any silent defaults or missing keys → fix before this commit closes.
- [ ] Run the full unit suite — first failure is a blocker:
      ```
      .venv/bin/python -m pytest tests/unit/ -q
      ```
- [ ] Run the full integration suite (pseudo-mode default for dual-mode tests
      — no real API needed):
      ```
      .venv/bin/python -m pytest tests/integration/ -q
      ```
- [ ] Run ruff and pyright on the **entire set of files added or edited
      across commits 1-7** (not the whole repo):
      ```
      .venv/bin/python -m ruff check agent/schemas/external_agents.py agent/schemas/literature_review.py agent/skills/paper_resolver_skill/ agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py agent/prompt_templates/literature_review/ nodes/ml_literature_review.py workflows/model_exploration.py tests/unit/agent/schemas/test_literature_review_schemas.py tests/unit/agent/skills/test_paper_resolver_skill.py tests/unit/agent/prompt_templates/test_literature_review_prompts.py tests/unit/agent/ml_literature_review/ tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py tests/unit/workflows/test_model_exploration_lit_review_wiring.py tests/integration/nodes/test_ml_literature_review.py
      .venv/bin/python -m pyright agent/schemas/external_agents.py agent/schemas/literature_review.py agent/skills/paper_resolver_skill/wrapper.py agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py agent/prompt_templates/literature_review/__init__.py nodes/ml_literature_review.py workflows/model_exploration.py
      ```
- [ ] Update `docs/external_agents_for_proposer.md` §9: mark questions
      resolved by this implementation (config naming, sandbox arg convention,
      reflector split deferral, etc.). Leave the genuinely open ones
      (manager layer threshold, cross-iteration agent memory) untouched —
      they're for `external_agents_architecture.md` to track.
- [ ] Update this file's status board: all `[ ]` → `[x]`, add commit hashes.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/ -q
.venv/bin/python -m pytest tests/integration/ -q
.venv/bin/python -m ruff check <changed files, listed above>
.venv/bin/python -m pyright <changed files, listed above>
```
All four commands must exit 0. Connection audit table appears in the commit
message.

**Open questions / decisions needed**:
- None at this stage by design — anything still open after Commit 7 has been
  promoted to `external_agents_architecture.md` §9 as a long-term concern.

---

## How to use this document while executing

1. Before starting a commit, re-read the **Goal** and **Checklist** and tick
   off `[ ]` → `[x]` for items already done (rare but possible if a fix
   landed out of band).
2. As each checklist item completes, flip `[ ]` → `[x]` **in the same edit
   that lands the code**. Never let plan and code drift.
3. Hit the **Test gate** before declaring the commit done. The gate command
   is the exact `pytest` / `ruff` / `pyright` invocation — if it doesn't
   pass, the commit is not done.
4. **Show the user** any pilot / real-run artifact called out in the
   commit's checklist before asking to commit. These are design checkpoints,
   not formalities.
5. If anything in the codebase contradicts a checklist item — **stop and
   ask**. The plan reflects the codebase as of writing; if it shifts,
   update the plan first, then the code.
