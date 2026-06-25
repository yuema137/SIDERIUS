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
- [x] **Commit P** — Proposer awareness for external findings — *(retroactive — fixes structural gaps the Q1–Q7 audit surfaced after Commit 5; see new §11 of `external_agents_for_proposer.md`)* · committed across `c0c0ea4` (P-design), `0c280ba` (P-a), `a629e4a` (P-b), `69e7234` (P-c), `aeb4d9f` (P-d), `6348ece` (P-e); Checkpoint P signed off 2026-06-05
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
- [x] **Commit 6.5a** — Search-quality prompt fixes (Fixes 1+2+5; post-audit 2026-06-12)
  · gate `tests/unit/agent/prompt_templates/test_literature_review_prompts.py` (5 prompt-content tests) + `tests/unit/agent/schemas/test_literature_review_schemas.py` (1 test on `ConfidenceRubric.render_for_searcher()` single-source-of-truth)
- [x] **Commit 6.5b** — Search-quality code/schema/YAML fixes (Fixes 3+4+6; post-audit 2026-06-12)
  · gate `tests/unit/agent/schemas/test_literature_review_schemas.py` (2 schema tests: `SearchDecisionRecord` + `LiteratureReviewInput.task_description`) + `tests/unit/agent/ml_literature_review/test_node.py` (5 node tests: Fix 3 no-op feedback + Fix 4 decision log + Fix 6 task threading) + `tests/unit/workflows/test_model_exploration_lit_review_wiring.py` (2 workflow tests: empty-task warning + non-empty no-warning)
  - [x] **6.5b-1** — Schemas + provenance + task_description field (Fix 4 schemas + Fix 6 field) · committed `faaeed7`
  - [x] **6.5b-2** — Fix 3: no-op escalation feedback · committed `e0e5f55`
  - [x] **6.5b-3** — Fix 4 node wiring: SearchDecisionRecord + provenance + tuple return · committed `cc92443`
  - [x] **6.5b-4** — Fix 5 remainder: dimension_counts + DIMENSION_LABELS + coverage rendering · committed `d3bfbd4`
  - [x] **6.5b-5** — Fix 6: task_description plumbing YAML→workflow→node · committed `e61e1cf`
  - [x] **Checkpoint S** — Search-quality re-run (5× same seed) · signed off 2026-06-13
- [x] **Commit F** — `task_description` cleanup (remove `SIDERIUS_TASK` constant); depends on Commit 6.5b · committed (SHA 5979896)
  · gate `tests/unit/agent/prompt_templates/test_literature_review_prompts.py` + full `tests/unit/` sweep (catches stray `SIDERIUS_TASK` imports)
- [ ] **Commit 7** — Configs, cache dir README, full connection audit
  · gate full `tests/unit/` + `tests/integration/` green
- [ ] **§10 End-to-end validation suite** — permanent acceptance gate
  (spec: `external_agents_for_proposer.md` §10); cross-cutting, not a single
  commit. Run log: `docs/validation_suite_runs.md`.
  - [x] **First FULL run** — completed across the 2026-06-09 + 2026-06-10 chain; FAILED under the original ≥4 floor, PASSED under the amended ≥2 floor. See `docs/validation_suite_runs.md` 2026-06-09 + 2026-06-10 entries. Floor amendment landed in `5e312ab` (§10.5 floor 4→2 + new §10.5.a stable-attractor calibration); the assertion broadness + V1/V0 example pattern-leak fixes that closed the chain landed in `9f731fe` (Noise2Noise example replacement) + `d652a3b` (equation-vs-shape discriminator).
  - [x] **Prerequisite re-run** — before Checkpoint D / Commit 6 (must pass on
        the post-P proposer) · signed off 2026-06-22, see `docs/validation_suite_runs.md` 2026-06-22 entry. PASS: 3 findings (Mamba 0.75 / DeepDenoiser 0.85 / FreLE 0.90), all structural assertions green, equation placement rule holds. Closes the §10 prerequisite for Checkpoint D.

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
- [x] **Audit step (no code change)**: open
      `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:43-222`
      and confirm `local_full_context` accepts `mindset: str | None` and
      `agent_cards: list[AgentCard] | None` kwargs and maps them into
      `ProposalInput`. Pre-conversation analysis confirmed this; verify
      once more before declaring the audit closed.
- [x] Write `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`
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
- [x] Tests:
  - [x] `local_all_channels` maps all four channels correctly with a fully
        populated `LiteratureReviewOutput`.
  - [x] `local_all_channels` passes through `new_vocab_candidates=[]` and
        `suggested_mindset=None` without error (v1 wired-empty channels).
  - [x] `local_all_channels` wraps a single `agent_card` into a list of one
        (the field on `ProposalInput` is `agent_cards: list[AgentCard]`).
  - [x] `local_all_channels` does NOT emit any `reference_library` or
        `reference_library_md` kwarg (regression guard against the
        cancelled design).
  - [x] `database_all_channels` raises `NotImplementedError`.

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

### Implementation log (sub-step progress within Commit 6)

| Sub-step | Status | Notes |
|---|---|---|
| Pre-flight A — `workflows/` added to `pyrightconfig.json` + 11 errors / 8 warnings fixed | ✅ done | `pyrightconfig.json` adds `workflows` to the `include` list; pre-existing pyright issues in `workflows/llm_config.py` + `workflows/model_exploration.py` cleaned to **0/0** without any `# type: ignore`. Two pre-existing `# type: ignore[arg-type]` lines at `llm_config.py:341,350` (in `.uniform()`) intentionally left alone — fixing them would propagate Literal types to external callers and is out of scope for Commit 6. |
| Pre-flight B — Fix `dynamic_search.initial_verbosity` dormant-field bug (Step 1 of 2026-06-11 implementation order) | ✅ done | Committed `6c493ee` (2026-06-11). `_run_search_loop` reads `cfg.initial_verbosity` and passes it to `_do_search`; `_do_search` accepts the new kwarg and forwards to `_retrieved_from_search_result`; `_retrieved_from_search_result` uses it on the `PaperSource(verbosity=...)` construction. Default-value path is bit-identical (50/50 existing tests pass unchanged). Interpretation chosen (minimal — interpretation `a` per the design review): set the operator's REQUESTED verbosity on `RetrievedPaper.source.verbosity` but leave `verbosity_achieved` at 0; the S2 search itself stays metadata-only and actual deep-reads continue via the LLM's escalation decisions. Verification: ruff + pyright (file + whole-repo) clean; 50/50 lit-review unit tests pass. |
| 6a — Read insertion point | ✅ done | Insertion point: between `interpretation = _interp_agent.run(...)` at `model_exploration.py:1080-1083` and `proposal = None` at line 1086. The cross-iter failure seeding (1086-1137) runs after lit-review so the proposer's `previous_failures` history is unaffected. |
| 6b Part 1 — `LitReviewLLMConfig` nested config on `WorkflowLLMConfig` (Step 2 of 2026-06-11 implementation order) | ✅ done | Committed `592ec6a` (2026-06-11). New `LitReviewLLMConfig(main, search)` class added; `WorkflowLLMConfig.lit_review: LitReviewLLMConfig \| None` slot added; `.get("lit_review")` flattens to the 4-field shape `{llm_provider, llm_model_id, search_llm_provider, search_llm_model_id}` when configured, and falls back to a translated 2-field dict from `interpret` when not. `.uniform()` populates lit_review with both sub-slots = `base_cfg`. Schema-level defaults: `deepseek` / `deepseek-v4-pro` for both sub-slots (matches Step 3's JSON defaults). Verification: ruff + pyright (file + whole-repo) clean; 10/10 smoke tests pass — including a backward-compat check that all 4 existing `llm_configs/*.json` still parse against the new schema. |
| 6b Part 2 — `should_run_literature_review` + `merge_external_agent_outputs` | ✅ done | Committed `65bc50e` (2026-06-12). `should_run_literature_review(interp_output, *, enabled)` returns `enabled` verbatim in v1; `interp_output` reserved for future content-based gating (marked unused via `del`). `merge_external_agent_outputs(outputs)` handles N=0 (4-channel empty default), N=1 with `LiteratureReviewOutput` delegating to the Commit-5 protocol `local_all_channels`, and N≥2 generic concat-then-last-non-None-mindset for future agents. Verification: ruff + pyright (file + whole-repo) clean; 5/5 smoke tests pass (enabled True/False + N=0/N=1/N=2 merge cases). |
| 6b Part 3 — Update existing `llm_configs/*.json` (Step 3 of 2026-06-11 implementation order) | ✅ done | Committed `8764e46` (2026-06-11). All 4 configs got the same `lit_review` block (both sub-slots = `deepseek`/`deepseek-v4-pro`), uniformly across both the OpenAI-routed (`openai_tiered_*.json`, `certify_minimal.json`) and the deepseek-routed (`deepseek_tiered_pro.json`) configs — lit-review-specific routing isolated from main-pipeline routing. Verification: JSON parse + `WorkflowLLMConfig.model_validate` + `.get('lit_review')` returns the expected 4-field dict on all 4 files. +40/-0 lines total. |
| 6c — Two `run_workflow` signature additions: `lit_review_enabled: bool = False` + `lit_review_config_path: str = "configs/lit_review_config.yaml"` | ✅ done (folded) | Committed as part of `59cc76e` (2026-06-12, sub-step 6e). Both params landed atop `run_workflow`'s signature between `run_id` and the pseudo-mode factories group, with a doc-comment explaining the resolution chain and the operator-configurable path semantics. |
| 6d — Flesh out `configs/lit_review_config.yaml` (Step 4 of 2026-06-11 implementation order) | ✅ done | Committed `546ce72` (2026-06-11). Replaced the 4b-final stub with the full operator-visible knob set per Design Decision 3 — every knob explicit (6 top-level keys: `enabled`, `root_papers`, `dynamic_search`, `findings_verbosity`, `synthesis`, `confidence_rubric`), all values match schema defaults verbatim so the file is a self-documenting tunable surface. Verification: `yaml.safe_load` parses cleanly; per-block `DynamicSearchConfig.model_validate` / `SynthesisConfig.model_validate` / `ConfidenceRubric.model_validate` / `PaperSource.model_validate` all pass. +88/-7 lines. |
| 6e — Wire per-iteration insertion point | ✅ done | Committed `59cc76e` (2026-06-12). New `_build_lit_review_input` helper; `run_workflow` opens + parses YAML at `lit_review_config_path` internally (relative paths resolved against `SIDERIUS_ROOT`); conditional `MLLiteratureReviewAgent.run` once per iter; `merge_external_agent_outputs` produces `external_channels` which extends `expert_context` + `vocab_seed` and supplies `agent_cards` + `mindset` to every per-attempt `local_full_context` call. Also landed the two signature additions deferred from 6c. Bit-identical behaviour when `lit_review_enabled=False` — protocol's existing `list(x or [])` and `if mindset is not None` guards collapse empty channels to "no contributor block". Verification: ruff + pyright (file + whole-repo) clean; 3/3 smoke tests pass (symbols importable, signature defaults correct, `_build_lit_review_input` round-trips every operator-visible knob from the canonical YAML). |
| 6f — `sdsc_submission_scripts/run_one_iteration.py` CLI flags + path threading | ✅ done | Committed `596b206` (2026-06-12). Two CLI flags landed at the end of `build_parser` per Design Decision 1: (1) `argparse.BooleanOptionalAction` for `--ml_lit_review_enabled`/`--no-ml_lit_review_enabled` (default `None` = "fall through to YAML"); (2) `--ml_lit_review_config <path>` (default `"configs/lit_review_config.yaml"`). Resolution logic in `main()` peeks at the YAML's `enabled` key only when neither CLI flag was passed; fail-safe behaviour (FileNotFoundError / yaml.YAMLError → False) prevents a misconfigured YAML from silently enabling the gate. Resolved boolean + raw path threaded into `run_workflow` right before the pseudo-mode factories. Verification: ruff clean; 6/6 smoke tests pass — including the regression check that argparse REJECTS the pre-rename name `--lit_review_enabled` (proves the `ml_` prefix is enforced, not just documented). |
| 6g — `reference_data/root_papers_cache/README.md` | ✅ done | Committed `4019849` (2026-06-12). README documents the cache contract (one JSON per `RetrievedPaper`, filename via `_sanitize_paper_id`, paper_id is the cache key, manual deletion to invalidate) + the `DEFAULT_ROOT_CACHE_DIR` node contract. `.gitignore` tightened to `reference_data/root_papers_cache/*` + an explicit `!README.md` negation so only the README is tracked — JSON cache files stay gitignored per Risk 5. Verification: `git check-ignore -v` matches the negation rule on README and the wildcard rule on a phantom `*.json`; `git add --dry-run` accepts the README and rejects the phantom. |
| 6h — Tests | ✅ done | Landed across two commits — Files 1-4 (helper unit tests + LitReviewLLMConfig + JSON regression + initial_verbosity regression + CLI flag naming) in `35c1f21` (2026-06-12, 24 tests + 1 modified across 4 files); File 5 (workflow-level dual-mode integration — operator-YAML passthrough, absence-tolerance, channels-reach-proposer smoke) in `82bbf94` (2026-06-12, 2 tests). Total: **26 new tests** + 1 modified. All tests pass under ruff + pytest (2/2 on the new dual-mode file in 1.10s; 135/135 on the 4 unit-test files combined). |

### Design decisions log (2026-06-11)

Three decisions confirmed after the schema audit:

1. **CLI flag naming convention** — every external-agent CLI gate uses an `--ml_*` (or future `--phys_*` etc.) prefix. Lit-review's flags are `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` (not the earlier-drafted `--lit_review_enabled`). Establishes a forward-compatible pattern for when a second external agent lands.
2. **Lit-review config path is operator-configurable** — `run_workflow` receives `lit_review_config_path: str = "configs/lit_review_config.yaml"`; the runner exposes `--ml_lit_review_config <path>` so different experiments can use different configs without editing the default file. The workflow opens + parses the YAML internally (the runner does not pre-parse).
3. **LLM routing architecture** — the lit-review node has two bridges (main + search-decision). The original 6b Part 1 sketched a single `NodeLLMConfig` lit_review slot; that's replaced with a nested `LitReviewLLMConfig(main: NodeLLMConfig, search: NodeLLMConfig)`. Operators set LLM routing in `WorkflowLLMConfig` (not the lit-review YAML) — matches the existing precedent of tuner planner/reflector + proposer comparison/reasoning/proposing nested configs.

**Pre-flight verification** (after pyright cleanup landed):
- `.venv/bin/python -m ruff check workflows/` → All checks passed
- `.venv/bin/python -m ruff format --check workflows/` → 2 files already formatted
- `.venv/bin/python -m pyright workflows/` → 0 errors, 0 warnings, 0 informations
- `.venv/bin/python -m pyright` (whole-repo CI gate) → 0 errors, 0 warnings, 0 informations

### Pre-flight B — Fix `dynamic_search.initial_verbosity` dormant-field bug

**Trigger**: schema audit on 2026-06-11 (response to Design Decision 3
investigation). `DynamicSearchConfig.initial_verbosity` is defined on
the schema with default `0` and a docstring describing it as the
starting verbosity floor for newly retrieved search results — but the
node never reads it. `_retrieved_from_search_result` at
`nodes/ml_literature_review/ml_literature_review.py:494` hardcodes
`PaperSource(..., verbosity=0)` on every search hit, so any non-default
value an operator sets in the YAML would be silently ignored.

**Fix**: thread `inp.dynamic_search.initial_verbosity` from `run()` →
`_run_search_loop` → `_do_search` → `_retrieved_from_search_result`,
replacing the hardcoded `verbosity=0`. The default behaviour stays
identical (the schema default is `0`), so this is a non-breaking change.

**Why pre-flight, not 6d**: it's a node-level bug, orthogonal to the
workflow integration. Lands before any Commit 6 sub-step so 6d can ship
a YAML that promises a working knob.

**Files**:
- Edit: `nodes/ml_literature_review/ml_literature_review.py` —
  `_retrieved_from_search_result` accepts and uses
  `initial_verbosity`; `_do_search` accepts and threads it;
  `_run_search_loop` reads `cfg.initial_verbosity` and passes it down.

**Test gate**:
- Existing tests in `tests/unit/agent/ml_literature_review/` keep
  passing (the default-value path is unchanged).
- One new regression test: with `initial_verbosity=2`, a mocked search
  hit produces a `RetrievedPaper.source.verbosity == 2`. Covered as
  part of 6h.

**Files**:
- Edit: `workflows/model_exploration.py`
- Edit: `configs/lit_review_config.yaml` (stub created in 4b-final; Commit 6 fills
  in the full runtime config with root_papers, dynamic_search, and synthesis blocks)
- New: `reference_data/root_papers_cache/README.md`
- New: `tests/unit/workflows/test_model_exploration_lit_review_wiring.py`
- Edit (possibly): existing Tier-0 dual-mode workflow test to cover the new
  insertion point (depending on test design — confirm before editing).

**Checklist**:
- [x] Read `workflows/model_exploration.py` end-to-end and **show the user
      the insertion point** (post-interpretation, pre-proposal loop) with
      surrounding line numbers before patching. **Insertion point**: between
      line 1083 (interpretation print) and line 1086 (`proposal = None`),
      before the cross-iter failure seeding at 1086-1137.
- [x] Add `merge_external_agent_outputs(outputs: list[ExternalAgentOutput]) -> dict[str, Any]`
      as a module-level function in `workflows/model_exploration.py` (or a
      sibling helper file if that's the convention; check the file's
      existing helper placement). **Module-level placement** chosen — one
      call site, one external agent in v1. **Done — committed `65bc50e`
      (2026-06-12).** Behaviour:
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
- [x] Add `should_run_literature_review(interp_output: InterpretationOutput, *, enabled: bool) -> bool`:
      reads the resolved `enabled` flag (CLI → YAML → default `False`,
      see Two-layer gate below). For v1 the gate is just `return enabled`
      — `interp_output` is reserved for future content-based gating
      (e.g. "skip lit-review when interpretation confidence > 0.9").
      Docstring includes the cost-tradeoff note from spec §6.
      **Done — committed `65bc50e` (2026-06-12).** Docstring also
      names the locked CLI flags `--ml_lit_review_enabled` /
      `--no-ml_lit_review_enabled` per Design Decision 1.

  **Two-layer enable/disable gate** (Risk 4 resolution, P-design 2026-06-09;
  CLI flag naming locked to the `--ml_*` prefix and the config path made
  operator-configurable per Design Decisions 1 + 2, 2026-06-11):
  - **YAML layer** (default file `configs/lit_review_config.yaml`, but
    the path is parameterised — see "Configurable config path" below):
    top-level `enabled: bool` defaulting to `true`. Operators edit the
    YAML to disable lit-review for an entire experiment chain.
  - **CLI layer** (`run_one_iteration.py` / `run_chain.sh`): exactly
    **two** flags for lit-review — no more.
    1. **`--ml_lit_review_enabled` / `--no-ml_lit_review_enabled`** via
       `argparse.BooleanOptionalAction`. Overrides the YAML default for
       a single run without editing the config file. The `ml_` prefix
       (Design Decision 1, 2026-06-11) establishes a naming convention
       for future external agents — e.g. `--ml_physics_agent_enabled` /
       `--no-ml_physics_agent_enabled` when the physics agent lands.
       Earlier drafts of this doc used `--lit_review_enabled` without
       the prefix; that name is **not** what ships and the tests
       enforce a parser error on the pre-rename name (see Tests block
       below).
    2. **`--ml_lit_review_config`** (Design Decision 2, 2026-06-11)
       with default `"configs/lit_review_config.yaml"`. Threaded
       straight through to `run_workflow(lit_review_config_path=...)`
       so the workflow opens + parses the YAML at the operator-supplied
       path. Lets different experiments use different lit-review
       configs without editing the default file.
  - **Resolution priority**: CLI flag (when explicitly set) >
    YAML `enabled` > default `False`. The workflow resolves this in one
    place before calling `should_run_literature_review`, then passes
    the resolved boolean as a kwarg. *(Default changed from the earlier
    draft's `True` to `False` so the production default is off until
    operators opt in.)*
  - **Scope (Design Decision 1, 2026-06-11)**: the CLI surface for
    lit-review contains **exactly** these two flags — the enable/disable
    toggle and the config path. **No other lit-review parameter is
    exposed at the CLI.** `root_papers`, `dynamic_search`, `synthesis`,
    `confidence_rubric`, etc. all stay in the YAML — config-file-only.
    LLM routing (`llm_provider` / `llm_model_id` /
    `search_llm_provider` / `search_llm_model_id`) lives separately in
    `WorkflowLLMConfig.lit_review` (Design Decision 3, 2026-06-11 —
    see "LLM routing architecture" below) and is **not** in the
    lit-review YAML either.

  **LLM routing architecture** (Design Decision 3, 2026-06-11):
  Lit-review makes three LLM calls (compression, search-decision,
  synthesis). The original 6b Part 1 sketched a single
  `lit_review: NodeLLMConfig | None` slot on `WorkflowLLMConfig`
  driving all three calls through one bridge. That's replaced with
  a nested `LitReviewLLMConfig` carrying two sub-slots — `main`
  (compression + synthesis) and `search` (search-decision). The node
  already reads four fields off `LiteratureReviewInput` for this split:
  `llm_provider` + `llm_model_id` build the main bridge unconditionally
  (`nodes/ml_literature_review/ml_literature_review.py:267`); the
  optional `search_llm_provider` + `search_llm_model_id` build a
  separate search-bridge when either is set, falling back per-field to
  the main bridge otherwise (`:271-277`). `WorkflowLLMConfig.get("lit_review")`
  flattens its two sub-slots into the matching 4-field shape so the
  workflow can splat into `LiteratureReviewInput`. The earlier draft's
  plan to expose `search_llm_provider` / `search_llm_model_id` in the
  lit-review YAML is cancelled — all LLM routing lives in
  `WorkflowLLMConfig` (mirrors the tuner planner/reflector + proposer
  comparison/reasoning/proposing nested-config precedent).
- [x] Load the lit-review YAML at workflow startup via the new
      `lit_review_config_path: str = "configs/lit_review_config.yaml"`
      kwarg on `run_workflow` (Design Decision 2, 2026-06-11). The path
      is resolved relative to project root via the same mechanism the
      workflow already uses for other configs (grep for `yaml.safe_load`
      to confirm). **The workflow opens + parses the YAML internally —
      it does NOT receive a pre-parsed dict from the caller**, so the
      runner stays focused on argument passing and the workflow owns
      the config schema's interpretation. Open + parse the file only
      when `lit_review_enabled=True` (an unused path never hits the
      filesystem). Convert the parsed dict into the non-LLM fields of
      `LiteratureReviewInput`; the four LLM-routing fields come from
      `llm_config.get("lit_review")` (Design Decision 3, 2026-06-11),
      `experiment_history` comes from the per-iter `InterpretationOutput`,
      `storage` + `run_name` come from the workflow's run-scoped state.
      **Done — committed `59cc76e` (2026-06-12).** Relative paths
      resolve to `SIDERIUS_ROOT` via `os.path.isabs` check;
      `_build_lit_review_input` uses `LiteratureReviewInput.model_validate`
      to drive Pydantic's nested-schema validation in one shot.
- [x] At the per-iteration insertion point: **Done — committed
      `59cc76e` (2026-06-12).** Implementation matches the pseudo-code
      example below; the proposal-loop's `local_full_context` call now
      receives `expert_context = expert_context_for_propose +
      external_channels["expert_context"]`, `vocab_seed = vocab_seed +
      external_channels["vocab_seed"]`, `agent_cards =
      external_channels["agent_cards"]`, `mindset =
      external_channels["mindset"]` — bit-identical to pre-Commit-6
      behaviour when `lit_review_enabled=False`.
  ```python
  # ----- In run_one_iteration.py — resolved ONCE per chain process,
  # then passed as two separate kwargs into run_workflow.
  # ml_lit_review_enabled is None when neither --ml_lit_review_enabled
  # nor --no-ml_lit_review_enabled was passed (BooleanOptionalAction
  # signals "fall through to YAML" with None). When non-None, the CLI
  # overrides the YAML.
  if args.ml_lit_review_enabled is not None:
      ml_lit_review_enabled = args.ml_lit_review_enabled
  else:
      with open(args.ml_lit_review_config) as f:
          ml_lit_review_enabled = yaml.safe_load(f).get("enabled", False)

  run_workflow(
      ...,
      lit_review_enabled=ml_lit_review_enabled,
      lit_review_config_path=args.ml_lit_review_config,  # default "configs/lit_review_config.yaml"
  )

  # ----- In run_workflow — opens + parses the YAML internally, only
  # when actually used (lit_review_enabled=True). An unused path never
  # hits the filesystem.
  interp_output = result_interpretation_agent.run(...)
  if should_run_literature_review(interp_output, enabled=lit_review_enabled):
      with open(lit_review_config_path) as f:
          lit_review_config = yaml.safe_load(f)
      lit_input = _build_lit_review_input(
          lit_review_config,
          interp_output,
          llm_kwargs=llm_config.get("lit_review"),  # 4-field flatten from LitReviewLLMConfig
          ...,
      )
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
- [x] **Step 3 — Update existing `llm_configs/*.json`** to add a
      `lit_review` block matching the new `LitReviewLLMConfig` shape.
      Four files affected:
      - `llm_configs/certify_minimal.json`
      - `llm_configs/deepseek_tiered_pro.json`
      - `llm_configs/openai_tiered_pro.json`
      - `llm_configs/openai_tiered_v1.json`

      The new `lit_review` block adds two sub-slots `main` + `search`,
      both as full `NodeLLMConfig` objects. Default routing per
      operator instruction (2026-06-11): both sub-slots set to
      `deepseek` / `deepseek-v4-pro` (the cheap-but-strong synthesis
      model the §10 Phase-2 work converged on; the search-decision
      step is the cheap templated call, deepseek is a fine match for
      both).

      Example block (uniform across all 4 files):
  ```json
  "lit_review": {
    "main": {
      "provider": "deepseek",
      "model_id": "deepseek-v4-pro"
    },
    "search": {
      "provider": "deepseek",
      "model_id": "deepseek-v4-pro"
    }
  }
  ```

      Without this update, an operator loading any of the 4 existing
      configs against the new `WorkflowLLMConfig` schema would still
      validate (the `lit_review` slot is `LitReviewLLMConfig | None`
      with default `None`) — but `.get("lit_review")` would fall back
      to `interpret`, producing a 2-field flatten that the lit-review
      node would treat as "no search-bridge override" and route the
      search-decision call through the main bridge. That's a correct
      fallback, not a bug — but the explicit `lit_review` block is
      the operator-visible source of truth Design Decision 3 calls for.

      **Status (2026-06-11)**: ✅ Done — committed `8764e46`. All 4
      configs updated with the same `lit_review` block; backward-compat
      verified by JSON parse + `WorkflowLLMConfig.model_validate` +
      `.get('lit_review')` → 4-field `{llm_provider, llm_model_id,
      search_llm_provider, search_llm_model_id}` dict on every file.
- [x] Flesh out `configs/lit_review_config.yaml` — **the default
      lit-review config**, at the default path (operators wanting a
      non-default config copy this and point at it via
      `--ml_lit_review_config /path/to/other.yaml`, per Design Decision
      2, 2026-06-11). A stub exists from Commit 4b-final containing
      only the `synthesis.transfer_tolerance` block; the stub's note
      "Commit 7 will flesh out" is **outdated** — Commit 6 does this,
      Commit 7 just adds the cache README + audit.

      **Status (2026-06-11)**: ✅ Done — committed `546ce72`. Replaced
      the stub with the full 6-key operator-visible knob set
      (`enabled`, `root_papers`, `dynamic_search`, `findings_verbosity`,
      `synthesis`, `confidence_rubric`); every value matches the
      schema default verbatim per the source-of-truth principle.
      Verification: yaml.safe_load + per-block Pydantic validation
      all pass.

      Per Design Decision 3 (2026-06-11), **every operator-visible
      knob is written explicitly even when it matches the schema
      default** — operators see all available knobs in one place
      without reading the schema source. The only fields omitted are
      (a) workflow-filled internal fields (`experiment_history` /
      `storage` / `run_name`) and (b) LLM routing fields (which live
      in `WorkflowLLMConfig.lit_review` per Design Decision 3 — NOT
      in this file).

      Replace the stub with:
  ```yaml
  # Top-level enable/disable flag — Risk 4 two-layer gate. Operators
  # may also override at the CLI via --no-ml_lit_review_enabled /
  # --ml_lit_review_enabled without editing this file. The CLI flag's
  # `ml_` prefix establishes a naming convention for future external
  # agents (Design Decision 1, 2026-06-11).
  enabled: true

  # ---------------------------------------------------------------------------
  # Root papers — curated foundational papers always resolved at agent start.
  # Per-paper extracts cached on disk under reference_data/root_papers_cache/.
  # ---------------------------------------------------------------------------
  root_papers:
    - source_type: arxiv
      identifier: "2406.04378"          # TIDMAD primary paper
      verbosity: 1                      # 0=metadata only / 1=PaperExtract / 2=full text

  # ---------------------------------------------------------------------------
  # Dynamic S2 search loop — runs after root-paper resolution, finds related
  # papers, lets the LLM escalate selected hits to deeper verbosity.
  # ---------------------------------------------------------------------------
  dynamic_search:
    enabled: true                       # master switch for the search loop
    max_rounds: 3                       # hard cap on search iterations
    initial_verbosity: 0                # starting verbosity for new search results (wired through after Pre-flight B fix)
    escalation_allowed: true            # whether the LLM may upgrade specific papers mid-loop
    results_per_query: 10               # S2 hits per query (>10 mostly adds noise)
    max_escalations_per_round: 2        # cap on deep-reads per round; 0 disables escalation entirely

  # ---------------------------------------------------------------------------
  # Output detail — 1 = three-part Implication/Mechanism/Adaptation format
  # (proposer-facing); 0 = single paragraph (backward-compat).
  # ---------------------------------------------------------------------------
  findings_verbosity: 1

  # ---------------------------------------------------------------------------
  # Synthesis — controls cross-domain transfer permissiveness for findings.
  # ---------------------------------------------------------------------------
  synthesis:
    transfer_tolerance: moderate        # strict / moderate / liberal

  # ---------------------------------------------------------------------------
  # Confidence rubric — single source of truth for what a finding's
  # confidence number means. Injected into the synthesis prompt; the
  # lit-review node clamps abstract-only-cited findings at
  # ``abstract_only_ceiling``.
  #
  # Note: overriding bands here affects the SYNTHESIS PROMPT only. The
  # lit-review node's emitted ``AgentCard.trust_guidance`` is built from
  # the SCHEMA DEFAULTS at module-load time (see
  # nodes/ml_literature_review/ml_literature_review.py:83-86) and does
  # not see a per-run override. Known limitation, not blocking — the
  # synthesis behaviour (what the LLM is told and what gets emitted)
  # follows the override; only the proposer-facing trust legend stays
  # on defaults.
  # ---------------------------------------------------------------------------
  confidence_rubric:
    omit_below: 0.40
    abstract_only_ceiling: 0.79
    bands:
      - lower: 0.80
        upper: 1.00
        criteria: "deep-read (verbosity >= 1 extract) AND on-domain (1D / broadband signal denoising) AND directly addresses a current bottleneck"
      - lower: 0.60
        upper: 0.79
        criteria: "deep-read with a clear mechanism transfer, OR an on-domain abstract with a strong specific signal"
      - lower: 0.40
        upper: 0.59
        criteria: "abstract-only evidence, OR cross-domain with a plausible (unvalidated) transfer rationale"
  ```

  **Knobs NOT in this file** (and why):
  - `llm_provider` / `llm_model_id` / `search_llm_provider` /
    `search_llm_model_id` — LLM routing lives in `WorkflowLLMConfig.lit_review`
    (Design Decision 3, 2026-06-11). The workflow flattens that nested
    config into the 4 fields the lit-review node reads.
  - `experiment_history` — workflow fills per-iter from `InterpretationOutput`.
  - `storage` / `run_name` — workflow fills with chain-scoped state.
- [x] Create `reference_data/root_papers_cache/README.md` explaining: format
      (one JSON file per paper, named `{paper_id}.json`, content is a
      serialized `RetrievedPaper`), invalidation (delete the file manually
      to force re-fetch + re-compression), and the contract with the
      lit-review node (`DEFAULT_ROOT_CACHE_DIR` constant at
      `nodes/ml_literature_review.py:61` points here by default).
      **Done — committed `4019849` (2026-06-12).** Also tightened
      `.gitignore` from a whole-dir ignore to `*` + `!README.md` so
      only the README escapes the ignore — keeps the "JSONs only,
      README is documentation" intent visible to future operators.

  **Risk 5 resolution (P-design 2026-06-09)**: only the README is
  committed in Commit 6 — NOT the cache files themselves. Production
  runs populate the cache via the S2 + extraction path on first run;
  subsequent runs hit the cache. Operators wanting bit-for-bit
  reproducibility can manually copy the Phase-1 pilot cache files from
  `reference_data/lit_review_pilot_cache/` (the gitignored pilot cache
  the Phase-1 / Phase-2 / §10 FULL tests use) into
  `reference_data/root_papers_cache/`. We may revisit committing the
  files if reproducibility issues from S2 variability become a problem.
- [x] Tests (`tests/unit/workflows/test_model_exploration_lit_review_wiring.py`)
      — **complete** as of `82bbf94` (File 5). Helpers + `_build_lit_review_input`
      land as unit tests in `35c1f21`; the 3 workflow-level tests
      (config_path passthrough, absence-tolerance, wiring smoke) live as
      dual-mode integration tests in
      `tests/integration/workflows/test_lit_review_wiring_dual_mode.py`
      (commit `82bbf94`) — splitting the test surface into the
      lighter-weight unit file and the heavier dual-mode file matches
      the test-classification rule (unit = mocked helpers; integration =
      workflow-level wiring with all 5 node agents patched).
  - [x] `merge_external_agent_outputs([single_output])` returns the four
        channels mapped correctly.
  - [x] `merge_external_agent_outputs([])` returns the empty default
        (`findings=[], new_vocab_candidates=[], agent_cards=[], mindset=None`).
  - [x] `merge_external_agent_outputs([a, b])` — concat-then-last-wins for
        mindset; concatenation for the list channels.
  - [x] `should_run_literature_review(...)` respects the `enabled` kwarg
        in both directions (True → True, False → False).
  - [x] **`lit_review_config_path` passthrough** (Design Decision 2,
        2026-06-11): with a tmp YAML at a non-default path, invoke
        `run_workflow(lit_review_config_path=tmp_path, lit_review_enabled=True, ...)`
        and assert the workflow opens + parses *that* file, not the
        default at `configs/lit_review_config.yaml`. Asserts both
        (a) the YAML at `tmp_path` is read, and (b) the resulting
        `LiteratureReviewInput.root_papers` matches the tmp file's
        contents. **Done — landed in
        `tests/integration/workflows/test_lit_review_wiring_dual_mode.py::test_lit_review_enabled_threads_operator_yaml_channels_to_proposer`
        (commit `82bbf94`, 2026-06-12)**. Sentinel arxiv id "9999.99999"
        in the tmp YAML is asserted on the captured
        `LiteratureReviewInput.root_papers[0].identifier`.
  - [x] **`lit_review_config_path` is NOT touched when
        `lit_review_enabled=False`**: with `lit_review_config_path`
        pointed at a path that does not exist, the workflow runs
        without raising — confirms the path is opened only when
        actually used. **Done — landed in
        `test_lit_review_wiring_dual_mode.py::test_lit_review_disabled_tolerates_missing_yaml_path`
        (commit `82bbf94`)**.
  - [x] Wiring smoke test: with `MLLiteratureReviewAgent.run` mocked to
        return a canned `LiteratureReviewOutput`, invoke the per-iter
        section and assert the `ProposalInput` arriving at the proposer
        has the expected `agent_cards` and `expert_context` entries.
        **Done — landed in
        `test_lit_review_wiring_dual_mode.py::test_lit_review_enabled_threads_operator_yaml_channels_to_proposer`
        (commit `82bbf94`)**, with assertions on
        `prop_input.agent_cards[0].agent_name == "ml_literature_review"`
        and the lit-review finding's `source_ref`.

- [x] Tests for `LitReviewLLMConfig` (`tests/unit/workflows/test_llm_config.py`
      — extend existing file; Design Decision 3, 2026-06-11) — **Done,
      committed `35c1f21` (2026-06-12)**, 7 new tests + 1 modified
      (test_default_all_slots_none now asserts cfg.lit_review is None).
      All 4 sub-bullets pass:
  - [x] `WorkflowLLMConfig.get("lit_review")` returns a 4-field dict
        when the slot is configured: `{llm_provider, llm_model_id,
        search_llm_provider, search_llm_model_id}`.
  - [x] `WorkflowLLMConfig.get("lit_review")` falls back to
        `.get("interpret")` semantics when `lit_review is None` (back-compat).
        Implementation note: the fallback translates key names
        (`provider` → `llm_provider`, `model_id` → `llm_model_id`);
        the test asserts the translated shape, not the verbatim
        `.get("interpret")` dict.
  - [x] `WorkflowLLMConfig.uniform("openai", "gpt-4o-mini")` populates
        both `lit_review.main` and `lit_review.search` with the same
        `NodeLLMConfig`.
  - [x] All 4 existing `llm_configs/*.json` files parse successfully
        against the updated schema (regression — guards against the
        Step 3 update being incomplete).

- [x] Tests for `sdsc_submission_scripts/run_one_iteration.py` CLI flag
      naming + threading (Design Decision 1, 2026-06-11) — **Done,
      committed `35c1f21` (2026-06-12)**, 6 new tests in
      `TestLitReviewCLI` (one extra test splits the True/False
      `--ml_lit_review_enabled` cases for clarity). All 4 sub-bullets
      pass:
  - [x] `argparse` accepts `--ml_lit_review_enabled` (→ `True`) and
        `--no-ml_lit_review_enabled` (→ `False`); when neither flag is
        passed, the namespace value is `None` (the BooleanOptionalAction
        sentinel for "fall through to YAML").
  - [x] `argparse` rejects the **pre-rename name** `--lit_review_enabled`
        with a parser error — confirms the `ml_` prefix is enforced,
        not just documented. Use `pytest.raises(SystemExit)` on
        `parse_args`.
  - [x] `--ml_lit_review_config /path/to/other.yaml` is threaded through
        unchanged to `run_workflow(lit_review_config_path=...)` (mock
        `run_workflow` and assert the kwarg value). *(Implementation
        note: argparse-level only — the test asserts
        `args.ml_lit_review_config == "/path/to/other.yaml"`; the
        threading-through-to-`run_workflow` part is exercised
        end-to-end in File 5.)*
  - [x] Default `--ml_lit_review_config` value is
        `"configs/lit_review_config.yaml"` when the flag is omitted.

- [x] **`initial_verbosity` regression test** (Pre-flight B,
      2026-06-11) in `tests/unit/agent/ml_literature_review/`: with
      `DynamicSearchConfig(initial_verbosity=2)`, a mocked S2 search
      hit produces a `RetrievedPaper.source.verbosity == 2`. Default
      (`initial_verbosity=0`) path keeps existing behaviour — guard
      against silent regression. **Done, committed `35c1f21`
      (2026-06-12)**, 2 tests in `TestInitialVerbosity` (the explicit
      `initial_verbosity=2` test + a default-zero regression that
      guards against accidental knob-flip from the Pre-flight B fix).
- [x] **Extend an existing dual-mode test to cover the lit-review insertion
      point** (Risk 6 resolution, P-design 2026-06-09 — do NOT just rely
      on the wiring smoke test). Candidates from
      `tests/integration/workflows/`: `test_k9_invented_model_dual_mode.py`
      or `test_n_recent_gate_exhaustions_dual_mode.py`. The extension
      mocks `MLLiteratureReviewAgent.run` to return a canned
      `LiteratureReviewOutput` and asserts the per-iteration
      `ProposalInput` carries the expected `agent_cards` + `expert_context`.
      Catches workflow-level wiring regressions for free on every
      dual-mode CI run. **Done — committed `82bbf94` (2026-06-12).**
      Deviation from the spec: rather than extending one of the
      existing files (both of which test `agent.run()` directly,
      not `run_workflow`), a NEW dedicated file
      `tests/integration/workflows/test_lit_review_wiring_dual_mode.py`
      was created — same dual-mode `pytestmark`, same mocking pattern,
      cleaner separation of concerns (the existing files focus on
      tuner-state and gate-exhaustion propagation; this one focuses
      on lit-review insertion). 2 tests cover both the enabled and
      disabled paths.

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

Add ~$0.10–0.40 per iteration when the proposer picks Branch C
(generate new custom loss) — this triggers the implementor's 2-call
loss-generation LLM chain plus potential repair attempts. See
`docs/design/enable_loss_inventory.md` § Gate 3 for a combined
cost estimate ($2.50–6.50) covering both model and loss generation.

**How to run**: invoke two chain iterations back-to-back using the same
seed and advice file, with lit-review toggled via the YAML config:

```bash
# Run A: lit-review ON (set enabled: true in configs/lit_review_config.yaml)
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_d_runA_$(date +%s) \
    --run_name checkpoint_d_runA \
    --num_iterations 1 --max_rounds 2 --max_proposal_attempts 3 \
    --max_epochs 1 --trial_portion 0.02 --trial_time_budget_minutes 5 \
    --trial_vram_budget_gb 10 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --seed_paths 

# Run B: lit-review OFF (set enabled: false in configs/lit_review_config.yaml)
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_d_runB_$(date +%s) \
    --run_name checkpoint_d_runB \
    --num_iterations 1 --max_rounds 2 --max_proposal_attempts 3 \
    --max_epochs 1 --trial_portion 0.02 --trial_time_budget_minutes 5 \
    --trial_vram_budget_gb 10 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --seed_paths 
```

Note: `--ml_lit_review_enabled` / `--no-ml_lit_review_enabled` CLI flags
exist in `run_one_iteration.py` but are NOT forwarded by
`_chain_common.sh` (bash-wrapper gap, tracked as follow-up). Use the
YAML `enabled:` key as the toggle instead.

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
- **Loss surface (added by loss-inventory feature)**: Does Run A's
  `ProposalOutput.custom_loss_spec` reference a specific technique from
  a lit-review finding? Check `custom_loss_spec.description` and
  `mathematical_definition` for `source_ref` values that appear verbatim
  in `LiteratureReviewOutput.findings[*].source_ref`. A finding that
  influences the loss design is equally valid evidence of lit-review
  influence as one that influences the architecture.
- Loss-inventory Gate 3 (`docs/design/enable_loss_inventory.md`
  § Gate 3) covers this surface in detail, including a mechanical
  hallucinated-source_ref check and a post-gate human audit checklist
  (Concern 1 + Concern 2). If Gate 3 has already been run and signed
  off before Checkpoint D, its artifacts may partially answer this
  bullet without re-running.

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

## Commit 6.5 — Search-quality fixes (post-audit, 2026-06-12)

**Trigger**: two read-only investigations on 2026-06-12 — (a) the code audit
of `agent/prompt_templates/literature_review/search_decision_system.md` +
`nodes/ml_literature_review/ml_literature_review.py:_run_search_loop` +
`agent/schemas/literature_review.py` against the canonical-trace artifact
(`docs/dynamic_search_pilot.md`); and (b) a direct S2 API check running 11
queries (3 LLM-generated + 8 manually crafted) against live Semantic Scholar.
Together they surfaced six search-quality gaps that compound across
Checkpoint D's A/B comparison runs.

### Audit findings (shared across 6.5a + 6.5b)

1. **No confidence-band framing in the search-decision prompt.** The LLM
   has no instruction tying escalation (v=0 → v=1) to confidence bands.
   `ConfidenceRubric._default_confidence_bands()` defines v=0 capping at
   0.40-0.59, v=1 enabling 0.60-0.79, and v=1 + on-domain + bottleneck
   enabling 0.80+ — but the search-decision LLM has never been told this.
   **Evidence**: canonical trace produced 3 findings at v=0 with
   confidences 0.45 / 0.50 / 0.45 — entirely in the abstract-only band
   ceiling (§5 of `docs/dynamic_search_pilot.md`).
2. **Binary `Mandatory assessment` block** (lines 93-106 of
   `search_decision_system.md`). The block asks "does *any* paper qualify?"
   and tells the LLM "ESCALATE *that* paper" (singular pronoun + qualifier).
   After round 1's escalate of SNRAware (no-op, already a v=1 root), the
   LLM had no instruction to re-evaluate the menu for newcomers — TADA
   (`arxiv:2501.04967`) and FreLE (`arxiv:2510.25800`) became findings at
   v=0 despite arriving in later rounds and being on-bottleneck.
3. **No-op escalations are silent.** `MLLiteratureReviewAgent._escalate`
   accepts calls on papers already at v≥requested without telling the
   LLM. From the LLM's perspective in rounds 2-4 of the canonical trace,
   its round-1 escalate "succeeded"; nothing nudged it to pick a different
   paper. **Evidence**: `_escalate` returns nothing observable; the loop
   at line 458 of the node increments `escalations_this_round`
   regardless of whether the call did real work.
4. **Per-round decisions are not persisted.** The only output artifact
   (`LiteratureReviewOutput.{retrieved_papers, search_rounds_used,
   findings}`) carries no `reasoning`, no per-paper provenance, and no
   per-decision audit trail. The `reasoning` field IS emitted by the LLM
   per the Output contract, but is captured only via
   `logger.info(..., json.dumps(decision)[:500])` at line 426 of the node
   — truncated to 500 chars, INFO-level only.
5. **Query coverage is single-dimensional in real runs.** Direct S2 API
   check (2026-06-12, 11 queries × top-5 results = 55 results) showed the
   LLM's 3 canonical-trace queries (`"SNR maximization loss denoising"`,
   `"sample reweighting loss time series denoising"`, `"spectral loss
   denoising time series"`) all anchored on bottleneck 2 (loss-metric
   mismatch). **Zero LLM queries** targeted bottleneck 1 (file-17 /
   hard-segment recovery) or bottleneck 3 (tiny-data robustness). Zero
   LLM queries included on-domain anchors (`"1D"`, `"broadband"`,
   `"SQUID"`). Manually crafted queries returned **3 papers more directly
   on-domain than the canonical findings** — `arxiv:2001.04460`
   (differentiable perceptual audio loss, 2020), `arxiv:2403.04350` (GW
   self-supervised denoising, 2024), and a cluster of 1D broadband
   denoising autoencoder papers — none seen by the LLM. The gap is ~80%
   query-quality, ~20% S2 coverage.
6. **No `task_description` threading.** All three lit-review render
   functions accept `task_description: str = SIDERIUS_TASK` but the node
   never passes one. Every run uses the SIDERIUS-specific default text
   regardless of `LiteratureReviewInput`. There is no
   `LiteratureReviewInput.task_description` schema field; no YAML key;
   no node call-site plumbing. The synthesis prompt's `{TASK_DESCRIPTION}`
   placeholder + the search prompt's are both already wired in the .md
   files and the render functions — but only the constant flows through.

### Goal

Close these six gaps so (a) the search-decision LLM is informed enough
to escalate strategically AND cover all three bottleneck dimensions,
(b) the no-op feedback channel exists, (c) Checkpoint D's A/B
comparison runs produce diagnosable + comparable artifacts that survive
past the INFO log, and (d) the task description is operator-controlled
rather than hardcoded.

### Commit-split rationale (resolved 2026-06-12, was Open Q3)

Commit 6.5 splits into two atomic commits to minimise blast radius:

- **6.5a** = prompt-only changes (Fixes 1, 2, 5). Smaller surface; fast
  test cycle; can be reverted independently if Checkpoint S reveals a
  prompt-side regression.
- **6.5b** = code + schema + YAML changes (Fixes 3, 4, 6). Adds the
  observability and feedback channels the search prompt needs.

**Checkpoint S runs after 6.5b lands** — it needs Fix 4's
`search_decisions` field to compute coverage metrics and Fix 6's task
injection to validate query anchoring. Both 6.5a and 6.5b must be on
disk for Checkpoint S to be meaningful.

---

### Commit 6.5a — Prompt-only fixes (Fixes 1, 2, 5)

**Files**:
- Edit: `agent/prompt_templates/literature_review/search_decision_system.md`
  — goal-statement rewrite (Fix 5), Mandatory-assessment rewrite (Fix 2),
  new confidence-band section + new query-generation-dimensions section
  (Fixes 1 + 5).
- Edit: `agent/prompt_templates/literature_review/__init__.py`
  — `render_search_decision_prompt` only: wire the new
  `{CONFIDENCE_RUBRIC_FOR_SEARCH}` placeholder; extend the
  `prior_search_results` block to render coverage distribution (Fix 5).
- Edit: `agent/schemas/literature_review.py`
  — small addition only: the new `ConfidenceRubric.render_for_searcher()`
  method. **No field additions** — `SearchDecisionRecord` +
  `LiteratureReviewOutput.search_decisions` +
  `RetrievedPaper.discovered_in_round` + `discovered_via_query` +
  `LiteratureReviewInput.task_description` all land in 6.5b.
- Edit: `tests/unit/agent/prompt_templates/test_literature_review_prompts.py`
  — Fixes 1, 2, 5 prompt-content tests.
- Edit: `tests/unit/agent/schemas/test_literature_review_schemas.py`
  — `ConfidenceRubric.render_for_searcher()` single-source-of-truth test.

#### Checklist — Fix 1: Confidence-band framing in `search_decision_system.md`

- [x] Add `ConfidenceRubric.render_for_searcher() -> str` method to
      `agent/schemas/literature_review.py`. Renders the three default
      bands keyed to the verbosity → confidence-band → escalation-value
      framing (distinct from `.render()` for synthesis omission and
      `.render_for_consumer()` for AgentCard trust legend). · landed
      (pre-commit, files on disk 2026-06-12)
- [x] Add a new section to `search_decision_system.md` (positioned above
      "## When to escalate vs. search vs. stop", former line 108, now
      line 177 after Edits B/C/D shifted line numbers) titled
      **"## Why escalation matters for finding confidence"** carrying:
  - The rendered `{CONFIDENCE_RUBRIC_FOR_SEARCH}` placeholder (single
    source of truth — bands come from `ConfidenceRubric`, not hardcoded
    in the .md).
  - The strategic framing: *"A paper cited from its abstract alone (v=0)
    caps the finding's confidence at the 0.40-0.59 band. Escalating to
    v=1 lets the synthesis LLM cite the same paper at confidence ≥0.60
    — strategically valuable when the paper is on-domain AND addresses
    one of the listed bottlenecks. The proposer reads each finding's
    confidence and weights its trust accordingly; a 0.65 finding lands
    more influence than a 0.45 one. Escalating an on-domain
    on-bottleneck paper is worth one round because it unlocks a
    higher-confidence finding that the proposer weights more heavily."*
- [x] Wire the `{CONFIDENCE_RUBRIC_FOR_SEARCH}` placeholder in
      `render_search_decision_prompt` via the same `.replace(...)`
      pattern the existing `{TASK_DESCRIPTION}` placeholder uses.
      Implementation also adds a `confidence_rubric: ConfidenceRubric |
      None = None` kwarg mirroring `render_synthesis_prompt`, so a
      custom rubric flows through the whole agent (synthesis +
      consumer + searcher) from a single source.

#### Checklist — Fix 2: Enumerative `Mandatory assessment` block

- [x] Rewrite the Mandatory-assessment block of
      `search_decision_system.md` (was lines 93-106 pre-edit; now lines
      127-150 post-edit) from binary to enumerative. The new block:
  - Tell the LLM to mentally rank **ALL retrieved papers** (not just one)
    against the current bottlenecks.
  - Tell the LLM to **list qualifying paper_ids in its `reasoning`
    field**.
  - Tell the LLM to **escalate the highest-ranked paper that has not
    been deep-read yet** (verbosity_achieved < 1).
  - Only choose SEARCH when the qualifying list is empty.
  - Acknowledge that the escalation budget allows multiple escalations
    between searches (referencing `max_escalations_per_round`).

#### Checklist — Fix 5: Goal rewrite + query generation guidance + coverage diversity

- [x] Rewrite lines 1-4 (the goal statement) of
      `search_decision_system.md`. New text (slightly expanded from the
      spec — adds "You output ONE JSON object" closing for clarity):
  ```
  You are the search strategist for an automated ML denoising research
  agent. Each round you decide the single most valuable next action to
  build a literature picture that helps the proposer design a better
  architecture. Bottlenecks are the highest priority, but adjacent
  techniques, novel training strategies, and domain-specific tricks are
  ALL in scope — a paper that addresses a bottleneck obliquely (e.g.
  perceptual loss for audio when our bottleneck is loss-metric mismatch
  on 1D signals) can be just as valuable as a direct hit.
  ```
- [x] Add a new section **"## Query generation — four dimensions to
      cover"** below the "## Translating the experiment state into a
      query" section. Lists 4 dimensions:
  1. **Bottlenecks** (highest priority) — every bottleneck in the list
     should be touched by at least one query across the run.
  2. **Take-home message direction** — the operator's literal directive
     (top of the user prompt). If it says "target file 17 recovery", at
     least one query must target hard-segment recovery.
  3. **Architectural gaps in `key_findings`** — gaps the experiment has
     not yet covered (e.g. if findings show all explored models are
     spectral, search for non-spectral alternatives).
  4. **Adjacent techniques not covered by `explored model_types`** —
     audio/speech/biomedical denoising mechanisms, augmentation
     strategies, regularisation tricks; cross-domain mechanism transfer
     is welcome.
- [x] Add a coverage diversity rule to the Output contract: *"In your
      `reasoning` field for a `search` action, label which dimension the
      query targets — one of `bottleneck`, `take_home`,
      `architectural_gap`, `adjacent_technique`. Across the run, you
      MUST cover ≥ 2 distinct dimensions."*
- [x] Extend `prior_search_results` rendering in
      `render_search_decision_prompt` to show **coverage distribution**:
      e.g. *"Coverage so far: bottleneck=2, take_home=0,
      architectural_gap=0, adjacent_technique=0."*

  **Landed 2026-06-12 in 6.5b-4 sub-commit (SHA d3bfbd4).**
  Implementation across two files:
  * `agent/prompt_templates/literature_review/__init__.py`:
    - New `DIMENSION_LABELS: tuple[str, ...]` constant (single source
      of truth for the 4 dimension vocabulary).
    - `render_search_decision_prompt` gained
      `dimension_counts: dict[str, int] | None = None` kwarg.
    - Coverage line rendered INSIDE the `## Queries already tried this
      run` block, AFTER the per-query lines and BEFORE the 0-hit
      broaden nudge. Format: `Coverage so far: bottleneck=N,
      take_home=N, architectural_gap=N, adjacent_technique=N.` (no
      interpretive suffix — LLM reads the counts and decides). Omitted
      when `dimension_counts` is None/empty, or when
      `prior_search_results` is None.
  * `nodes/ml_literature_review/ml_literature_review.py`:
    - `DIMENSION_LABELS` added to the existing import.
    - New module-level helper `_parse_dimension(reasoning: str) -> str
      | None`: case-insensitive substring scan returning the
      LEFTMOST-mention label; None when no label appears (diagnostic
      signal that the LLM didn't follow the labelling rule).
    - `_run_search_loop` initializes `dimension_counts: dict[str, int]`
      with all 4 labels at 0; after each successful search action,
      parses the dimension label from `decision.get("reasoning")` and
      increments. Threaded through to `render_search_decision_prompt`
      every round.
    - Pyright-required refactor: `_append_decision` was moved OUT of
      the while loop (was inside per 6.5b-3) and now takes
      `dec: dict[str, Any]` + `current_rounds: int` as explicit args.
      The in-loop closure-with-default-args pattern triggered a
      `reportGeneralTypeIssues` self-reference error from pyright
      after adding the dimension_counts mutation in the same loop
      body; the function-scope helper resolves it cleanly while
      preserving the DRY benefit and eliminating any B023 lint risk.
      All 7 call sites updated to pass `decision, rounds` explicitly.
      Audit-trail output is byte-identical to 6.5b-3.

  Implementation deviation from the spec sample: NO interpretive
  suffix (the spec wrote *"...you have not yet addressed the take_home
  priority; consider it next round."*). Bare counts let the LLM
  reason about coverage based on the system prompt's four-dimensions
  section; adding a directive suffix would duplicate that guidance.

  Source-of-counts deviation: spec said "needs the
  `search_decisions[].reasoning` capture from Fix 4 to compute the
  counts." Implementation reads from `decision.get("reasoning")`
  directly in `_run_search_loop` at decision time — same string,
  accessed earlier in the data flow. The `search_decisions` audit
  trail still captures the reasoning for post-hoc inspection.

  **Test gate run — 6.5b-4 (pre-commit, 2026-06-12)**: 163 passed in
  1.19s (160 baseline + 3 net-new). `ruff check` + `ruff format
  --check` + `pyright` all green on the 2 production files.

  Tests delivered:
  - `tests/unit/agent/ml_literature_review/test_node.py::TestParseDimension::test_parse_dimension_first_label_heuristic`
    — case-insensitive leftmost-match for all 4 labels; None for
    no-match and empty.
  - `tests/unit/agent/prompt_templates/test_literature_review_prompts.py::TestSearchDecisionPrompt::test_dimension_coverage_line_renders_inside_prior_block`
    — coverage line renders with all 4 labels in correct ordering
    (queries → coverage → broaden nudge).
  - `...::test_dimension_coverage_omitted_when_no_counts_or_no_prior`
    — None / empty dict / None prior_search_results all skip the line.
- [x] **Trusted dimension labels** (resolved 2026-06-12, was Open Q1):
      labels in the `reasoning` field are TRUSTED — the node counts
      what the LLM self-reports, no parser-enforced contract. A missing
      label is itself a diagnostic signal that Fix 5 is incomplete
      (visible in the captured `search_decisions[].reasoning` for
      post-hoc inspection). No node-side validation of the label
      vocabulary.

#### Test gate — 6.5a

```
.venv/bin/python -m pytest \
  tests/unit/agent/prompt_templates/test_literature_review_prompts.py \
  tests/unit/agent/schemas/test_literature_review_schemas.py -q
.venv/bin/python -m ruff check \
  agent/prompt_templates/literature_review/ \
  agent/schemas/literature_review.py
.venv/bin/python -m ruff format --check \
  agent/prompt_templates/literature_review/ \
  agent/schemas/literature_review.py
.venv/bin/python -m pyright \
  agent/prompt_templates/literature_review/__init__.py \
  agent/schemas/literature_review.py
```

Test floor — **6 new tests** + 0 modifications:

- **Fix 1**: 2 tests. (a) Rendered search-decision system prompt
  contains the three band criteria + the "escalating an on-domain
  on-bottleneck paper unlocks a higher-confidence finding" sentence
  (`tests/unit/agent/prompt_templates/...`). (b) Regression:
  `ConfidenceRubric.render_for_searcher()`, `.render()`, and
  `.render_for_consumer()` all render the same band bounds for the
  default rubric (single source of truth)
  (`tests/unit/agent/schemas/...`).
- **Fix 2**: 2 prompt-content tests. (a) The rewritten block contains
  "rank", "list every paper that qualifies", "highest-ranked".
  (b) Anti-regression: the binary phrasing "does any retrieved paper
  directly address" is no longer present.
- **Fix 5**: 2 prompt-content tests. (a) Rewritten goal statement
  contains "adjacent techniques" + "in scope"; the four-dimension list
  is present. (b) `render_search_decision_prompt` test: with mocked
  `prior_search_results` carrying 3 labelled queries (counts:
  bottleneck=2, adjacent_technique=1, take_home=0,
  architectural_gap=0), the rendered block contains the coverage
  distribution line citing all four dimensions with those counts.

**Test gate run — 2026-06-12 (pre-commit)**: 152 passed in 0.84s
(147 baseline + 5 net-new = 152; test 5 below is an in-place rewrite of
the Commit 6 `test_mandatory_escalation_assessment_block_present` and
so doesn't add a row). `ruff check` + `ruff format --check` + `pyright`
all green on the 3 production files.

Test-floor mapping (3 schema + 2 prompt + 1 rewrite delivered vs. the
spec's 2+2+2 along Fix-1/2/5 lines — same total volume, structural
regrouping):

- Fix 1 covered by: schema-side `test_render_for_searcher_has_all_default_bands`
  + `test_render_for_searcher_has_search_leadin_not_producer_or_consumer`
  + `test_render_for_searcher_with_custom_rubric` (single-source-of-
  truth across the three render methods); prompt-side
  `test_confidence_rubric_for_search_placeholder_filled` (the
  `{CONFIDENCE_RUBRIC_FOR_SEARCH}` placeholder is filled, the
  "Why escalation matters for finding confidence" section header is
  present, all three default-band bounds appear, the strategic-framing
  sentence "Escalating an on-domain on-bottleneck paper... unlocks a
  higher-confidence finding" is verified as an explicit substring
  match — spec Fix 1 (a) — and a custom rubric flows through via the
  new `confidence_rubric` kwarg).
- Fix 2 covered by: rewritten in-place
  `test_mandatory_escalation_assessment_block_present` — asserts the
  new enumerative-ranking language ("scan ALL papers retrieved",
  "list (by paper_id) EVERY paper that qualifies",
  "verbosity_achieved < 1", "Only choose SEARCH when NO retrieved
  paper qualifies", "defaulting to" + "SEARCH is not acceptable").
  Spec's Fix 2 (b) anti-regression ("does any retrieved paper directly
  address" must be absent) is covered by construction — the .md has
  exactly one assessment block and it was rewritten to contain the
  new phrasing.
- Fix 5 covered by: prompt-side
  `test_four_dimensions_section_and_label_rule_present` — the new
  "## Query generation — four dimensions to cover" section header is
  present, all four dimension names appear, the "label which dimension
  the query targets" + "cover ≥ 2 distinct dimensions" Output-contract
  rule appears. Spec's Fix 5 (b) coverage-distribution rendering test
  is deferred along with the feature itself to 6.5b (Fix 4 dependency).

---

### Commit 6.5b — Code + schema + YAML fixes (Fixes 3, 4, 6)

**Files**:
- Edit: `agent/prompt_templates/literature_review/__init__.py`
  — `render_search_decision_prompt` extended with
  `prior_escalation_results` kwarg + the no-op-feedback sub-block
  (Fix 3).
- Edit: `agent/schemas/literature_review.py`
  — new `SearchDecisionRecord` class (Fix 4); new `search_decisions`
  field on `LiteratureReviewOutput` (Fix 4); new `discovered_in_round`
  + `discovered_via_query` fields on `RetrievedPaper` (Fix 4); new
  `task_description: str = ""` field on `LiteratureReviewInput` (Fix 6).
- Edit: `nodes/ml_literature_review/ml_literature_review.py`
  — `_run_search_loop` records decisions; `_escalate` returns/signals
  no-op status; per-paper provenance written when papers arrive via
  `_do_search` + `_retrieved_from_search_result`;
  `MLLiteratureReviewAgent.run` populates `search_decisions`; all three
  render-function call sites pass `inp.task_description`
  (Fixes 3 + 4 + 6).
- Edit: `workflows/model_exploration.py`
  — `_build_lit_review_input` reads `task_description` from YAML; logs
  an INFO warning when empty (Fix 6).
- Edit: `configs/lit_review_config.yaml`
  — new `task_description:` top-level key with multi-line comment +
  SIDERIUS-default example (Fix 6).
- Edit: `tests/unit/agent/schemas/test_literature_review_schemas.py`
  — Fix 4 + Fix 6 schema tests.
- Edit: `tests/unit/agent/ml_literature_review/test_node.py`
  — Fixes 3, 4, 6 node tests.
- Edit: `tests/unit/workflows/test_model_exploration_lit_review_wiring.py`
  — Fix 6 workflow-level tests (warn on empty, no warn on non-empty).

#### Checklist — Fix 3: No-op escalation feedback

- [x] Modify `MLLiteratureReviewAgent._escalate` to return a status
      indicating no-op vs real work. The no-op check fires when
      `target.verbosity_achieved >= requested_verbosity` BEFORE running
      the skill call.

  **Landed 2026-06-12 in 6.5b-2 sub-commit (SHA e0e5f55).**
  Implementation: the pre-call check
  (`if target.verbosity_achieved >= target_verbosity: return "noop"`)
  fires at the top of `_escalate` per spec — skips the resolve skill
  when the LLM mis-asks for an already-achieved verbosity, saving one
  API call. A post-call defense-in-depth check is also present
  (catches empty `full_text` responses + the verbosity-didn't-rise
  case after a compress failure) — covers degenerate skill responses
  the pre-call check can't anticipate. Return type is
  `Literal["ok", "noop", "error"]`; `target.error` is set on the
  `"error"` path. Budget charge applies on every outcome
  (Decision 2, 2026-06-12).
- [x] Modify `_run_search_loop` to track no-op escalations in a local
      `prior_escalation_results: list[tuple[str, bool, str]]` —
      `(paper_id, was_noop, reasoning)` — passed into
      `render_search_decision_prompt` as a new kwarg.

  **Landed 2026-06-12 in 6.5b-2 sub-commit (SHA e0e5f55).**
  Implementation deviation: tuple slot 2 is `str` (one of
  `"ok"` / `"noop"` / `"error"`), not `bool was_noop`. Preserves the
  3-state signal end-to-end so the LLM distinguishes errors from
  no-ops (a hard fetch failure should not be re-tried any more than a
  no-op, but the LLM's reasoning about WHY differs). Approved
  in-conversation 2026-06-12.
- [x] Extend `render_search_decision_prompt` to accept
      `prior_escalation_results` and render a sub-block in the user
      prompt (parallel to the existing `## Queries already tried this
      run` block):
  ```
  ## Escalations already attempted this run
  - "arxiv:2503.18162" → no-op (was already v=1); pick a different paper next time
  - "arxiv:2501.04967" → deep-read produced extract (now v=1)
  ```

  **Landed 2026-06-12 in 6.5b-2 sub-commit (SHA e0e5f55).**
  Implementation deviation: the rendered format is richer than the
  spec sample. Each row carries the status's user-facing label
  (`"success — paper now deep-read"` / `"no-change — paper was already
  at the requested verbosity OR fetch returned no new content"` /
  `"error — resolve call failed; do not retry this paper"`) plus the
  LLM's original reasoning excerpt (truncated to 200 chars with `…`
  ellipsis). The richer format is what the new test
  `test_prior_escalation_results_renders_three_statuses` locks in.
- [x] Add a system-prompt nudge alongside the existing
      broaden-on-0-hit nudge: *"An escalation that returned 'no-op'
      means the paper was already at the requested verbosity —
      escalating it again wastes a round; pick a different on-bottleneck
      paper."*

  **Landed 2026-06-12 in 6.5b-2 sub-commit (SHA e0e5f55).**
  Implementation deviation: the nudge lives in the **user prompt**
  (appended to the escalation-history block when non-empty), not in
  the system prompt. Wording is *"Do NOT re-escalate a paper whose
  last status was 'no-change' or 'error' — pick a different paper,
  search for a new one, or stop."* Trade-off chosen: context-aware
  (appears only when there's escalation history) vs. always-present
  in system prompt. Context-aware avoids noise on first round when
  there are no prior escalations.

#### Test gate run — 6.5b-2 (pre-commit, 2026-06-12)

157 passed in 1.03s (153 baseline + 4 net-new). `ruff check` +
`ruff format --check` + `pyright` all green on the 2 production files
(`agent/prompt_templates/literature_review/__init__.py`,
`nodes/ml_literature_review/ml_literature_review.py`).

Tests delivered:
- `tests/unit/agent/prompt_templates/test_literature_review_prompts.py::TestSearchDecisionPrompt::test_prior_escalation_results_renders_three_statuses`
  — 3 statuses render their specific labels + paper_ids + do-not-retry
  nudge + 200-char reasoning truncation with ellipsis.
- `...::test_prior_escalation_results_omitted_when_none_or_empty`
  — None and `[]` both omit the entire block.
- `tests/unit/agent/ml_literature_review/test_node.py::TestEscalation::test_escalate_returns_ok_when_verbosity_raised`
  — happy path returns `"ok"` and raises `verbosity_achieved`.
- `...::test_escalate_returns_noop_on_empty_full_text_and_error_on_failure`
  — two sub-cases: empty full_text → `"noop"` (no mutation); resolve
  fail → `"error"` (target.error set).

#### Checklist — Fix 4: Persistent search decision log

- [x] Add `SearchDecisionRecord` Pydantic class in
      `agent/schemas/literature_review.py`:
  ```python
  class SearchDecisionRecord(BaseModel):
      round_index: int = Field(
          ge=1,
          description="1-indexed round the decision belongs to. Search "
          "actions consume this round; escalate / done actions occur "
          "within it.",
      )
      action: str = Field(
          description="Action the LLM returned. Expected: 'search' | "
          "'escalate' | 'done', but typed as ``str`` (not ``Literal``) so "
          "anomalous responses surface in the audit trail instead of "
          "raising ValidationError and crashing the loop "
          "(Decision 4, 2026-06-12).",
      )
      query: str | None = Field(default=None,
          description="The S2 query string, set when action='search'.")
      paper_id: str | None = Field(default=None,
          description="The escalation target's paper_id, set when action='escalate'.")
      verbosity: int | None = Field(default=None,
          description="Requested verbosity tier for the escalation "
          "(typically 1 or 2).")
      reasoning: str = Field(default="",
          description="The LLM's free-text justification, captured "
          "verbatim. The dynamic-search rule requires the LLM to label "
          "which of {bottleneck, take_home, architectural_gap, "
          "adjacent_technique} the query targets; the node trusts the "
          "label (no parser-enforced contract).")
      outcome: str = Field(
          description="Post-execution result. Canonical values: 'ok' / "
          "'noop' / 'error' (escalate); 'n_hits=N' (search); "
          "'budget_exceeded' / 'target_not_found' / 'unknown_action' "
          "(degenerate); 'done' (stop).")
  ```

  **Landed 2026-06-12 in 6.5b-1 schema sub-commit (SHA faaeed7).**
  **Implementation deviations from the spec draft above** (all resolved
  in this conversation):
  * `round_idx` → `round_index` (more readable; Decision 3 reaffirmed
    1-indexing means search-only, so `ge=1` rejects 0/negative).
  * `action: Literal[...]` → `action: str` — Decision 4 (type-permissive
    so anomalous LLM responses surface in the audit trail instead of
    crashing the loop with `ValidationError`).
  * The three outcome flags (`hits: int | None`, `noop: bool`,
    `cap_hit: bool`) are collapsed into a single `outcome: str` field
    with canonical values listed above. Rationale: one string field
    extends to new outcome categories (e.g. `"empty_query"`,
    `"target_not_found"`) without schema changes; the typed-triple
    would have needed a parallel bool added per category.
  * New `verbosity: int | None` field — captures the LLM's requested
    escalation tier (1 or 2) so the audit log is self-describing
    without re-reading the live log.
  * `reasoning` made optional (`default=""`) — a malformed LLM
    response that omits `reasoning` still records.
- [x] Add `search_decisions: list[SearchDecisionRecord] =
      Field(default_factory=list)` to `LiteratureReviewOutput`.
      Backward-compat: existing serialised outputs default to `[]`; no
      migration needed. **Landed 2026-06-12 in 6.5b-1 schema sub-commit
      (SHA faaeed7).** Field description landed slightly expanded:
      *"Audit trail of LLM decisions inside the dynamic-search loop —
      one record per LLM call. Empty when the search loop did not run
      (dynamic_search.enabled=False) or the LLM call raised before any
      decision was logged. See SearchDecisionRecord."*
- [x] Add provenance fields to `RetrievedPaper`:
  ```python
  discovered_in_round: int | None = Field(
      default=None,
      ge=0,
      description="0 = root paper (pre-loop); 1..max_rounds = the search "
      "round that surfaced this paper. None for legacy/cached entries.",
  )
  discovered_via_query: str | None = Field(
      default=None,
      description="The S2 query string that returned this paper. None for "
      "root papers and for legacy/cached entries.",
  )
  ```

  **Landed 2026-06-12 in 6.5b-1 schema sub-commit (SHA faaeed7).**
  Implementation deviation: `ge=0` constraint added on
  `discovered_in_round` to reject negative values explicitly (the
  semantics — 0 for roots, 1+ for search hits — make negatives
  meaningless). Field descriptions also expanded to spell out the
  "Pydantic default fires when key is absent → backward-compat with
  pre-6.5b cached JSON" claim, which is what the new schema-side test
  `test_provenance_fields_default_and_legacy_cache_backward_compat`
  proves end-to-end via `RetrievedPaper.model_validate_json`.
- [x] Modify `_run_search_loop` to build a `SearchDecisionRecord` after
      every LLM call (search, escalate-success, escalate-noop,
      escalate-cap-hit, done) into a local `decisions` list.

  **Landed 2026-06-12 in 6.5b-3 sub-commit (SHA cc92443).**
  Implementation: closure-style helper `_append_decision(action_str,
  outcome)` defined inside the while loop, captures `decision` and
  `rounds` via default-arg locking per `feedback_ruff_fix_patterns`
  (`_rounds=rounds, _decision=decision`). Called from 7 outcome sites
  covering every action path:
    * `done` → `outcome="done"` (terminal)
    * `search` empty query → `outcome="empty_query"` (terminal)
    * `search` success → `outcome=f"n_hits={n_hits}"`
    * `escalate` budget-exceeded → `outcome="budget_exceeded"`
    * `escalate` executed → `outcome=status` ("ok" / "noop" / "error" from Fix 3)
    * `escalate` target-not-found → `outcome="target_not_found"`
    * catch-all `escalate-while-disabled` → `outcome="escalation_disabled"`
    * catch-all truly-unknown action → `outcome="unknown_action"`

  Method return type changed `int → tuple[int, list[SearchDecisionRecord]]`.
  Round-index semantic: `round_index = rounds + 1` (1-indexed; decision
  belongs to next-to-execute round). The escalate-while-disabled split
  is a small enhancement over the original spec — the audit trail now
  distinguishes a config mismatch from a true LLM hallucination
  (approved in-conversation 2026-06-12).
- [x] Pass `round_idx` + current query string down into `_do_search` +
      `_retrieved_from_search_result` so new papers carry provenance.

  **Landed 2026-06-12 in 6.5b-3 sub-commit (SHA cc92443).**
  Implementation: `_do_search` gained `round_index: int` keyword-only
  parameter; threads it + the `query` string down to
  `_retrieved_from_search_result` (which also gained both as
  keyword-only). Each new `RetrievedPaper` constructed with
  `discovered_in_round=round_index` + `discovered_via_query=query`.
  Internal naming `round_idx` was renamed to `round_index` for
  consistency with `SearchDecisionRecord.round_index` (single
  vocabulary across the codebase).

  Implementation extends beyond the spec: `_build_retrieved_from_resolve`
  is ALSO patched to explicitly set `discovered_in_round=0` +
  `discovered_via_query=None` on root papers. Per Decision 3 from the
  2026-06-12 design conversation: root papers get 0 (not None) to
  match "search hits = 1+" symmetrically. This is 4.D in this commit's
  internal numbering — landed alongside 4.E because both touch
  `RetrievedPaper` construction.
- [x] Populate `LiteratureReviewOutput.search_decisions` from the
      accumulated records in `MLLiteratureReviewAgent.run`.

  **Landed 2026-06-12 in 6.5b-3 sub-commit (SHA cc92443).**
  Implementation: `run()` unpacks `_run_search_loop`'s new tuple
  return — `rounds_used, search_decisions = self._run_search_loop(...)` —
  then passes `search_decisions` to the `LiteratureReviewOutput`
  construction. When `dynamic_search.enabled=False` the loop never
  runs and `search_decisions` defaults to `[]` (initialized at the
  top of `run()` so the type hint flows even on the disabled path).

#### Test gate run — 6.5b-3 (pre-commit, 2026-06-12)

57 passed in 1.08s (54 baseline + 3 net-new). `ruff check` +
`ruff format --check` + `pyright` all green on the single production
file (`nodes/ml_literature_review/ml_literature_review.py`).

Tests delivered (all in new `TestSearchDecisionLog` class in
`tests/unit/agent/ml_literature_review/test_node.py`):
- `test_search_decisions_records_all_action_types` — exercises a
  search → escalate → done sequence; asserts every record's `action`,
  `outcome`, `round_index`, per-action fields (`query` for search,
  `paper_id` + `verbosity` for escalate), and `reasoning` excerpt.
  Locks in the 1-indexed `round_index = rounds + 1` semantic.
- `test_search_hit_provenance_tags_round_index_and_query` —
  `discovered_in_round=1` and `discovered_via_query=<the query>` reach
  the new `RetrievedPaper` end-to-end through `_do_search` +
  `_retrieved_from_search_result`.
- `test_root_paper_provenance_tagged_zero` — root paper resolved at
  agent start carries `discovered_in_round=0` and
  `discovered_via_query=None`.

#### Checklist — Fix 6: `task_description` config field + node threading

- [x] Add `task_description: str = ""` to `LiteratureReviewInput` in
      `agent/schemas/literature_review.py`. `Field` description must
      strongly recommend operators fill it in: *"Concrete downstream
      task description shown to all three lit-review LLM calls
      (compression, search-decision, synthesis). Drives search-query
      anchor words and synthesis relevance framing. Default empty
      string means 'task block omitted from prompts'; operators SHOULD
      set this via configs/lit_review_config.yaml's `task_description:`
      key so the LLM has a concrete domain to anchor its queries on."*

  **Landed 2026-06-12 in 6.5b-1 schema sub-commit (SHA faaeed7).**
  Landed wording reframes the recommendation around the Commit F
  bridge explicitly: *"...When empty, the node falls back to
  ``SIDERIUS_TASK`` (the lit-review module's default constant) — this
  is a temporary bridge; Commit F flips the default to the empty
  string and removes ``SIDERIUS_TASK`` entirely. Workflow logs a
  warning when this field is empty."* Operationally identical (the
  Field's default value is still `""` and the recommendation to set
  it in YAML is still present); the wording change makes the
  Commit-F dependency more discoverable from the field docstring
  itself.
- [x] Add `task_description:` to `configs/lit_review_config.yaml` with
      a multi-line comment + a SIDERIUS-default example. Place it
      immediately under `enabled:` so operators see it first when
      editing. Example block:
  ```yaml
  # Concrete downstream task this lit-review run is supporting. Injected
  # into all three lit-review LLM calls (compression, search-decision,
  # synthesis) via the {TASK_DESCRIPTION} placeholder. Drives the search
  # LLM's query anchor words (e.g. "1D", "broadband", "SQUID") and the
  # synthesis LLM's relevance framing.
  #
  # Strongly recommended — an empty value omits the task block from
  # prompts and forces the LLM to guess the domain from key_findings +
  # bottlenecks alone (the canonical-trace failure mode).
  task_description: |
    Full-spectrum 1-D time-series denoising of SQUID dark-matter detector
    data: map a noisy [B, T] integer signal to a clean [B, 256, T]
    reconstruction, trained across the whole frequency spectrum at once
    (not split into per-band models).
  ```

  **Landed 2026-06-12 in 6.5b-5 sub-commit (SHA e61e1cf).**
  Implementation landed with slightly different framing in the YAML
  comment block — references "the SIDERIUS_TASK default constant"
  explicitly and notes the workflow prints a Warning at YAML-load time.
  Default value lower-cased to match the prompt-module SIDERIUS_TASK
  constant verbatim.
- [x] Modify `_build_lit_review_input` (in
      `workflows/model_exploration.py`) to read
      `config.get("task_description", "")` from the YAML dict and pass
      it into the `LiteratureReviewInput` constructor.

  **Landed 2026-06-12 in 6.5b-5 sub-commit (SHA e61e1cf).**
  Implementation: `str(config.get("task_description", "") or "").strip()`
  collapses missing key, None value, empty string, and whitespace-only
  — all into "" before the `if not task_description:` warning check.
  Then included in the `model_validate` dict so the validated input
  carries it through to the node.
- [x] **Log an INFO-level warning in `_build_lit_review_input`** (in
      `workflows/model_exploration.py`) when `task_description == ""`
      — wording: *"`task_description` is empty in lit_review_config.yaml;
      lit-review LLM calls will receive no task-domain anchor and may
      produce off-domain queries. Strongly recommended: set
      `task_description:` in the YAML."* (Resolved 2026-06-12, was
      Open Q2.) The warning fires at YAML-load time, NOT at render time
      — render-time warnings would fire 3+ times per run and clutter
      logs.

  **Landed 2026-06-12 in 6.5b-5 sub-commit (SHA e61e1cf).**
  Implementation deviation: uses `print("Warning: ...")` rather than
  `logger.info(...)`. Reason: `workflows/model_exploration.py` has no
  logger setup — file convention is `print("Warning: ...")` for
  operator-visible warnings (matches existing pattern at line 136 for
  vocab seed load failure). Operator approval received in-conversation
  2026-06-12 (Fix 6.C revision). Wording landed slightly expanded:
  *"Warning: lit_review config has no `task_description` — the
  lit-review agent will fall back to the SIDERIUS_TASK default constant.
  Set `task_description:` in configs/lit_review_config.yaml to
  specialize the agent's search/synthesis behavior for your problem."*
- [x] Modify `MLLiteratureReviewAgent` call sites in
      `nodes/ml_literature_review/ml_literature_review.py` to pass
      `inp.task_description` to all three render functions
      (`render_paper_extract_prompt`, `render_search_decision_prompt`,
      `render_synthesis_prompt`).

  **Landed 2026-06-12 in 6.5b-5 sub-commit (SHA e61e1cf).**
  Implementation: `run()` computes `self._task_description =
  inp.task_description or SIDERIUS_TASK` once after bridge setup, then
  all three render call sites pass `task_description=self._task_description`.
  Storing on `self` (rather than threading `inp.task_description`
  through `_compress`'s signature) keeps `_compress` callable from
  `_escalate` without a parameter chain.

  Pre-existing test fix: `test_escalate_returns_ok_when_verbosity_raised`
  (from 6.5b-2) bypassed `agent.run()` and called `_escalate` directly,
  which now indirectly requires `self._task_description`. The test was
  updated to set `agent._task_description = "test task"` manually
  alongside the existing `agent.bridge = bridge` setup.
- [x] **No `.md` file changes** — all three prompts already have the
      `{TASK_DESCRIPTION}` placeholder (confirmed 2026-06-12); this fix
      only wires the data source from the YAML through to the
      placeholder substitution. Confirmed during 6.5b-5 implementation:
      no `.md` files were touched.
- [x] **Commit-F dependency**: this fix REPLACES the `SIDERIUS_TASK`
      default usage in node call sites but leaves the constant defined
      in `__init__.py`. Commit F follows up by deleting the constant +
      changing the render defaults from `SIDERIUS_TASK` to `""`. Order
      matters — Commit F must NOT land before Commit 6.5b.
      Dependency now unblocked — 6.5b-5 is the last sub-commit of
      6.5b, so Commit F can land next once the operator approves.

#### Test gate run — 6.5b-5 (pre-commit, 2026-06-12)

198 passed in 4.08s (195 baseline + 3 net-new). `ruff check` + `ruff
format --check` + `pyright` all green on the 2 production files
(`nodes/ml_literature_review/ml_literature_review.py`,
`workflows/model_exploration.py`).

Tests delivered:
- `tests/unit/workflows/test_model_exploration_lit_review_wiring.py::TestBuildLitReviewInput::test_warns_on_empty_task_description`
  — 3 sub-cases (missing key / empty string / whitespace-only) all
  trigger the warning via capsys.
- `...::test_no_warning_when_task_description_set` — non-empty value
  → no warning + flows to `inp.task_description`.
- `tests/unit/agent/ml_literature_review/test_node.py::TestTaskDescriptionPlumbing::test_task_description_reaches_all_three_render_calls`
  — custom value reaches all 3 LLM-facing system prompts (paper_extract
  / search_decision / synthesis) captured by FakeBridge.

Bonus: pre-existing `test_escalate_returns_ok_when_verbosity_raised`
(from 6.5b-2) updated with one-line setup expansion to set
`agent._task_description` since it bypasses `agent.run()`.

#### Test gate — 6.5b

```
.venv/bin/python -m pytest \
  tests/unit/agent/schemas/test_literature_review_schemas.py \
  tests/unit/agent/ml_literature_review/test_node.py \
  tests/unit/workflows/test_model_exploration_lit_review_wiring.py -q
.venv/bin/python -m ruff check \
  agent/prompt_templates/literature_review/ \
  agent/schemas/literature_review.py \
  nodes/ml_literature_review/ml_literature_review.py \
  workflows/model_exploration.py \
  configs/lit_review_config.yaml
.venv/bin/python -m ruff format --check \
  agent/prompt_templates/literature_review/ \
  agent/schemas/literature_review.py \
  nodes/ml_literature_review/ml_literature_review.py \
  workflows/model_exploration.py
.venv/bin/python -m pyright \
  agent/prompt_templates/literature_review/__init__.py \
  agent/schemas/literature_review.py \
  nodes/ml_literature_review/ml_literature_review.py \
  workflows/model_exploration.py
```

Test floor — **9 new tests** + 0 modifications:

- **Fix 3** (2 tests, `tests/unit/agent/ml_literature_review/test_node.py`):
  (a) `FakeBridge` returns escalate→search; the first escalate targets
  an already-v=1 paper; assert the second round's user prompt contains
  the rendered no-op feedback line + the broaden-on-noop nudge.
  (b) Assert `LiteratureReviewOutput.search_decisions[0].noop is True`.
- **Fix 4** (3 tests): (a) Schema
  (`tests/unit/agent/schemas/test_literature_review_schemas.py`):
  `SearchDecisionRecord` validates with each of search-with-hits,
  escalate-success, escalate-noop, escalate-cap-hit, done shapes.
  (b) Node: a canned full loop produces a `search_decisions` list
  matching the canned LLM responses 1-for-1. (c) Node: every
  `retrieved_papers[i]` from a search-loop addition carries
  `discovered_in_round` = the round it was added in and
  `discovered_via_query` = the query that surfaced it; root papers
  carry `discovered_in_round=0` and `discovered_via_query=None`.
- **Fix 6** (4 tests): (a) Schema: `LiteratureReviewInput` accepts
  `task_description=""` (default) AND a non-empty string. (b) Node:
  with a non-empty `task_description` on the input, all three render
  functions receive it (verifiable via FakeBridge prompt captures).
  (c) Workflow
  (`tests/unit/workflows/test_model_exploration_lit_review_wiring.py`):
  `_build_lit_review_input` logs an INFO warning when YAML omits
  `task_description:` (captured via caplog). (d) Workflow:
  `_build_lit_review_input` does NOT warn when YAML provides a
  non-empty `task_description:`.

#### 🔍 Behavioral Checkpoint S — Search-quality re-run (5× same seed)

**Trigger**: after BOTH 6.5a and 6.5b land + their respective test
gates are green. Checkpoint S validates the combined effect of all six
fixes — it cannot run after 6.5a alone (no `search_decisions` to
inspect) and would not be conclusive after 6.5b alone (no
prompt-level behavioral changes).

**How to run**: re-run `MLLiteratureReviewAgent` **5 times** on the same
`InterpretationOutput` seed used in the canonical trace
(`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v12_0504/iter_014/iteration_014/interpretation_iter_014.json`).
Same configuration as the canonical trace: `deepseek-v4-pro` for all
three sub-calls, `findings_verbosity=1`,
`synthesis_config.transfer_tolerance="moderate"`, `max_rounds=3`,
`escalation_allowed=True`, `max_escalations_per_round=2`. Set
`task_description:` in the YAML to the SIDERIUS-default text (per the
Fix 6 example). Capture each run's `LiteratureReviewOutput` to disk
under `reference_data/lit_review_pilot_cache/post_6_5_audit_runs/run_{N}.json`.

**Pass criteria (all must hold)**:

| # | Criterion | Pre-fix baseline (canonical trace) |
|---|---|---|
| 1 | **≥ 4 of 5 runs produce ≥ 1 non-no-op escalation** | 0/1 runs (SNRAware escalate was a no-op) |
| 2 | **≥ 3 of 5 runs produce ≥ 1 finding cited at v=1** | 0/1 runs (all 3 findings at v=0) |
| 3 | **≥ 2 of 5 runs produce a finding with confidence ≥ 0.60** | 0/1 runs (confidences 0.45 / 0.50 / 0.45) |
| 4 | **All 5 runs cover ≥ 2 distinct dimensions** (verifiable from `search_decisions[].reasoning`) | 1/1 covered 1 dimension only (all queries on loss-metric mismatch) |
| 5 | **`search_decisions` populated in all 5 runs** with complete per-round records | N/A pre-fix (field didn't exist) |

**Diagnostics to inspect** (per-run):

- Round-1 decision: enumerative ranking in `reasoning` (Fix 2 working)
  — should cite ≥ 2 paper_ids when the menu has more than one
  candidate.
- Any subsequent round received a no-op feedback line in its rendered
  user prompt (Fix 3 working) — verifiable from a captured prompt
  snapshot per run.
- Coverage distribution rendered in `prior_search_results` block
  (Fix 5 working) — verifiable from a captured prompt snapshot.
- For each finding, walk the chain:
  `finding.source_ref → retrieved_papers[ref].verbosity_achieved →
  discovered_in_round → search_decisions[round]`. Broken chains
  indicate Fix 4 incomplete.

**What this decides**: whether Checkpoint D can run on Commit 6.5's
surface. If any pass criterion fails, the failure mode is logged into
the artifact and Commit 6.5 stays open until a follow-up fix iteration
closes it. **Checkpoint D is gated until Checkpoint S passes.**

**Artifact**: `docs/search_quality_validation.md` containing the 5
runs' aggregated metrics table, per-run round-by-round decision
walkthroughs (condensed to the diagnostic essentials), captured prompt
snapshots proving Fixes 3 + 5 fired, and the human verdict.

### Resolved open questions (2026-06-12)

- **Q1** (Fix 5 dimension labels): **trusted** — node counts what the
  LLM self-reports; no parser-enforced label contract; missing labels
  are diagnostic signals visible in `search_decisions[].reasoning`.
- **Q2** (Fix 6 default behavior): **log an INFO warning in
  `_build_lit_review_input`** when `task_description == ""`; do NOT
  warn at render time (would fire 3+ times per run).
- **Q3** (Commit split): **split into 6.5a (prompt-only) + 6.5b (code +
  schema + YAML)**; Checkpoint S runs after 6.5b lands (needs Fix 4's
  `search_decisions` field + Fix 6's task injection).

---

## Commit F — `task_description` cleanup (remove SIDERIUS_TASK constant)

**Trigger**: follow-up to Commit 6.5b Fix 6. Once
`LiteratureReviewInput.task_description` exists + the node passes
`inp.task_description` to all three render functions + the YAML carries
the operator-set value, the `SIDERIUS_TASK` constant + its use as
render-function default becomes dead code.

**Goal**: remove the hardcoded `SIDERIUS_TASK` constant from
`agent/prompt_templates/literature_review/__init__.py` and unify all
three lit-review prompts (compression, search-decision, synthesis) to
read their task description exclusively from
`LiteratureReviewInput.task_description`. After Commit F, the only
place the SIDERIUS-specific task text lives is the
`configs/lit_review_config.yaml` (the canonical operator default,
landed in Commit 6.5b Fix 6).

**Strict ordering**: Commit F MUST land after Commit 6.5b. If Commit F
landed first, the render defaults would silently switch from the
SIDERIUS-specific text to `""`, leaving prompts with empty task blocks
until the YAML and node call-sites caught up — exactly the
canonical-trace failure mode the audit flagged.

**Files**:
- Edit: `agent/prompt_templates/literature_review/__init__.py`
  — remove `SIDERIUS_TASK` constant + the 2-line prose comment above
  it; change the `task_description: str = SIDERIUS_TASK` default to
  `task_description: str = ""` on all three render functions
  (`render_paper_extract_prompt`, `render_search_decision_prompt`,
  `render_synthesis_prompt`); update docstrings to reflect the new
  default + point operators at `LiteratureReviewInput.task_description`.
- `agent/prompt_templates/literature_review/paper_extract_system.md`,
  `search_decision_system.md`, `synthesis_system.md` — **no change**.
  All three already carry the `{TASK_DESCRIPTION}` placeholder; the
  empty-string substitution just replaces the placeholder with an
  empty line under the heading. Confirmed by grep (1 placeholder each,
  2026-06-12).
- Edit: `tests/unit/agent/prompt_templates/test_literature_review_prompts.py`
  — update any test that previously expected the SIDERIUS-specific
  default text. Add one new test for the empty-default behavior + one
  for the non-empty round-trip.

**Checklist**:
- [x] Remove `SIDERIUS_TASK` constant + its 2-line prose comment from
      `agent/prompt_templates/literature_review/__init__.py`.
- [x] Update `render_paper_extract_prompt` signature: change
      `task_description: str = SIDERIUS_TASK` → `task_description: str = ""`.
- [x] Update `render_search_decision_prompt` signature: same change.
- [x] Update `render_synthesis_prompt` signature: same change.
- [x] Confirm the three .md files still have `{TASK_DESCRIPTION}`
      placeholders — no .md edits required (re-verify with grep).
- [x] Confirm `nodes/ml_literature_review/ml_literature_review.py` call
      sites still pass `inp.task_description` (landed in 6.5b Fix 6 —
      Commit F just confirms the wiring is correct after the defaults
      flip).
- [x] Update any existing prompt-content unit tests that hardcoded the
      `SIDERIUS_TASK` text. Most assertions are structural and should
      keep passing; the few that quoted the SIDERIUS text need to be
      re-pointed at operator-supplied test fixtures.

**Landed 2026-06-12 in Commit F (SHA 5979896).** Implementation per
spec with these notes:
- Also touched `agent/schemas/literature_review.py` —
  `LiteratureReviewInput.task_description` field description rewritten
  to remove the "Commit F flips the default to '' and removes
  SIDERIUS_TASK" bridge wording (the description now describes the
  post-Commit-F reality directly).
- Also touched `workflows/model_exploration.py` —
  `_build_lit_review_input` warning text rewritten. New wording:
  *"Warning: lit_review config has no `task_description` — lit-review
  LLM calls will receive no task-domain anchor and may produce
  off-domain queries. Strongly recommended: set `task_description:`
  in configs/lit_review_config.yaml ..."*
- Also touched `tests/unit/workflows/test_model_exploration_lit_review_wiring.py`
  — assertion text updated from `"SIDERIUS_TASK default constant"` to
  `"no task-domain anchor"` to match the new warning wording.
- Test deviation from the spec's "2 new + ≤ 3 modified" floor:
  delivered 3 modified, 0 new. Rationale: the existing
  `TestTaskInjection::test_default_empty_task_placeholder_gone`
  (renamed from `test_default_task_injected_and_placeholder_gone`)
  and `::test_custom_task_overrides_default` cover both empty-default
  and custom-task surfaces for `render_paper_extract_prompt`. The
  other 2 render functions (`render_search_decision_prompt` and
  `render_synthesis_prompt`) are implicitly tested at their empty
  defaults via the existing `TestSearchDecisionPrompt._render()` and
  `TestSynthesisPrompt._render()` helpers (both use kwargs that now
  resolve to `""`).
- One residual `SIDERIUS_TASK` mention remains in
  `workflows/model_exploration.py:545` — but it's a comment explaining
  "post-Commit-F there is no SIDERIUS_TASK fallback", which is the
  intended documentation of the cleanup, not a code reference.

**Test gate run — Commit F (pre-commit, 2026-06-12)**: 303 passed in
4.11s (sweep of `tests/unit/agent/prompt_templates/` +
`tests/unit/workflows/` + `tests/unit/agent/ml_literature_review/test_node.py`).
`ruff check` + `ruff format --check` + `pyright` all green on the 4
production files. Sanity grep: `grep -rn "SIDERIUS_TASK" --include="*.py" .`
returns exactly 1 hit (`workflows/model_exploration.py:545`, the
comment), down from 18+ hits pre-Commit-F.

**Test gate**:
```
.venv/bin/python -m pytest \
  tests/unit/agent/prompt_templates/test_literature_review_prompts.py \
  tests/unit/agent/ml_literature_review/test_node.py -q
.venv/bin/python -m ruff check \
  agent/prompt_templates/literature_review/__init__.py \
  nodes/ml_literature_review/ml_literature_review.py
.venv/bin/python -m ruff format --check \
  agent/prompt_templates/literature_review/__init__.py
.venv/bin/python -m pyright \
  agent/prompt_templates/literature_review/__init__.py
.venv/bin/python -m pytest tests/unit/ -q   # full unit sweep — no other module imports SIDERIUS_TASK
```

Test floor — **2 new tests** + ≤ 3 modified:

- **New test 1**: `render_paper_extract_prompt(raw_text="foo")` (no
  `task_description`) produces a rendered prompt where the
  `{TASK_DESCRIPTION}` placeholder has been replaced with `""` (the
  heading `## The task...` is still present, the body under it is
  empty). Same structural assertion for `render_search_decision_prompt`
  and `render_synthesis_prompt` at their empty defaults.
- **New test 2**: a non-empty `task_description="custom task X"` passed
  to each of the three render functions appears verbatim in the
  rendered system prompt body.
- **Modified test(s)**: any existing prompt-content test that hardcoded
  `"full-spectrum 1-D time-series denoising of SQUID..."` is updated to
  either (a) pass an explicit `task_description` and assert on it, or
  (b) assert on structural placeholder presence rather than the
  SIDERIUS-specific text. Expected count: ≤ 3 tests touched.

**Sanity check (cross-repo grep)**:
- `grep -rn "SIDERIUS_TASK" --include="*.py"` after the edit must
  return zero hits — no other module should import the constant.
- `grep -rn "SIDERIUS_TASK" --include="*.md"` must return zero hits —
  no docs reference the constant either.

### Resolved open questions (2026-06-12)

- **Commit F Q1** (warn at render time?): **no** — the warning is
  already covered by Commit 6.5b Fix 6's `_build_lit_review_input`
  INFO warning (Q2 of 6.5). A render-time warning would fire 3+ times
  per run and clutter logs.

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
