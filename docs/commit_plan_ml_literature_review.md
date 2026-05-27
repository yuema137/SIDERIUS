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

| # | Commit | State | Test gate |
|---|---|---|---|
| 1 | Schema (`literature_review.py` + `external_agents.py`) | `[x]` | `tests/unit/agent/schemas/test_literature_review_schemas.py` |
| 2 | Paper resolver skill + TIDMAD pilot | `[ ]` | `tests/unit/agent/skills/test_paper_resolver_skill.py` + committed `docs/paper_resolver_pilot.md` |
| 3 | Finalize `PaperExtract` + compression prompt | `[ ]` | `tests/unit/agent/prompt_templates/test_literature_review_prompts.py` + real-run extract reviewed |
| 4 | `nodes/ml_literature_review.py` core loop | `[ ]` | `tests/unit/agent/ml_literature_review/test_node.py` + real-run output reviewed |
| 5 | Protocol `ml_literature_review_to_ml_model_propose.py` (audit-only on `local_full_context`) | `[ ]` | `tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py` |
| 6 | Workflow integration (`merge_external_agent_outputs`, `should_run_literature_review`) | `[ ]` | `tests/unit/workflows/test_model_exploration_lit_review_wiring.py` + Tier-0 dual-mode |
| 7 | Configs, cache dir README, full connection audit | `[ ]` | full `tests/unit/` + `tests/integration/` green |

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
- `render_agent_cards` and `render_expert_context` with dedup-by-`cite_id` and
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
        `year`, `core_idea`, `architecture_summary`, `key_results`,
        `relevance_to_squid`. All `str`. Finalize after pilot.
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
- [ ] Write `skill_config.json` matching the
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
- [ ] Write `wrapper.py` exporting
      `run_skill(sandbox, **kwargs) -> dict`. `sandbox` is accepted and
      ignored (consistent with universal skill convention per Q3).
- [ ] Resolve-mode branch (`mode == "resolve"`):
  - [ ] `source_type in {"arxiv","doi","openreview"}` → S2 lookup via
        `GET /graph/v1/paper/{id_prefix}:{identifier}` (e.g.
        `ARXIV:2302.09309`, `DOI:...`, `URL:...`). Parse `openAccessPdf`
        and `externalIds`.
  - [ ] PDF download: prefer `openAccessPdf.url`; fall back to
        `https://arxiv.org/pdf/{arxiv_id}.pdf` when `externalIds.ArXiv`
        present. Stream to a temp file (do not buffer in memory).
  - [ ] Local file branch (`source_type == "local"`): resolve repo-relative
        path against project root, read `.pdf` via `pdfplumber`, read
        `.txt` / `.md` directly.
- [ ] Search-mode branch (`mode == "search"`):
  - [ ] Build query against `GET /graph/v1/paper/search?query=...&limit=...&offset=...`
        with optional filters mapped to the S2 query params.
  - [ ] Unwrap `response["data"]` and run each paper object through the
        same per-paper mapping helper used by resolve-mode. Result is a
        `list[RetrievedPaper]`-shaped payload.
  - [ ] Search defaults to `verbosity=0` (metadata only — no PDF fetch
        per result, which would be a fan-out cost trap). PDF fetch only
        happens when the lit-review node later requests a specific paper
        at higher verbosity via a follow-up `resolve` call.
  - [ ] Honour `limit` (default 10, cap at 50 — documented in wrapper).
- [ ] Shared per-paper mapping helper (private): `_paper_object_to_dict(obj) -> dict`
      returns the fields needed by `RetrievedPaper.s2_metadata` plus an
      `openAccessPdf` and `externalIds` pass-through. Used by both modes.
- [ ] Per-run in-memory cache: module-level
      `_S2_CACHE: dict[tuple, dict]` keyed by the full request shape
      (mode + identifier + filters). A second call with the same shape
      returns the cached S2 response. Documented as **not** thread-safe.
- [ ] Error contract: every exit path returns
      `{"status": "ok" | "partial" | "error", "data": ..., "message": ...}`.
      Never raise. `partial` covers e.g. resolve succeeded for S2 metadata
      but PDF download failed.
- [ ] Run the **resolve-mode pilot** manually:
      ```python
      from agent.skills.paper_resolver_skill.wrapper import run_skill
      result = run_skill(
          None, mode="resolve",
          source_type="arxiv", identifier="2302.09309", verbosity=1,
      )
      ```
      Capture: token-count estimate, openAccessPdf-vs-arxiv-fallback path
      taken, structural integrity of equations/sections, signal-to-noise.
- [ ] Run the **search-mode pilot** manually (sanity, 3-line check —
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
- [ ] Write `docs/paper_resolver_pilot.md` recording both pilots' outputs,
      plus a 200-line excerpt of the TIDMAD extracted text so Commit 3
      can reference it without re-running. **Show the user before
      finalising the file.**
- [ ] Write `tests/unit/agent/skills/test_paper_resolver_skill.py`:
  - [ ] resolve / arxiv — mocked S2 response, mocked PDF download, asserts
        `openAccessPdf` path is taken.
  - [ ] resolve / arxiv — S2 returns no `openAccessPdf`, asserts arXiv
        fallback URL is used.
  - [ ] resolve / arxiv — both paths fail → `verbosity_achieved=0`, S2
        metadata only, status="partial", no exception.
  - [ ] resolve / doi — mocked S2 returns metadata, no PDF,
        verbosity_achieved=0.
  - [ ] resolve / openreview — mocked S2 returns metadata + openAccessPdf,
        verbosity_achieved=2 (full text path).
  - [ ] resolve / local `.pdf` — `pdfplumber` is mocked to return canned text.
  - [ ] resolve / local `.md` — direct file read, no pdfplumber.
  - [ ] resolve / local — absolute path rejected (the `PaperSource` validator
        catches it at construction; this test confirms the wrapper also
        defends in-depth).
  - [ ] **search — happy path**: mocked S2 returns an envelope with 3
        `data` items; wrapper unwraps and returns 3 mapped paper objects.
  - [ ] **search — empty result**: mocked S2 returns `{"total": 0,
        "offset": 0, "data": []}` → wrapper returns `status="ok"`,
        empty list, no exception.
  - [ ] **search — filter passthrough**: `year=2023`, `min_citation_count=10`
        appear in the request URL.
  - [ ] cache hit — two calls with the same arguments (resolve or search)
        → `requests.get` called once.
  - [ ] error case — `requests.get` raises → wrapper returns
        `{"status":"error","message":...}`, does not propagate.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/skills/test_paper_resolver_skill.py -q
.venv/bin/python -m ruff check agent/skills/paper_resolver_skill/ tests/unit/agent/skills/test_paper_resolver_skill.py
.venv/bin/python -m pyright agent/skills/paper_resolver_skill/wrapper.py
```
Plus: `docs/paper_resolver_pilot.md` exists with **both** resolve-mode and
search-mode outputs, reviewed by user.

**Open questions / decisions needed**:
- HTTP library — confirm `requests` is the project default by grepping
  before writing. If `httpx` is the convention, switch.
- S2 rate limits — does the agent need to thread an API key from the env?
  Lean: yes (`S2_API_KEY` if set; degrade silently to unauthenticated
  shared pool if not). Confirm behaviour during the pilot. Both modes
  share the same per-key quota — no mode-specific rate-limit code needed.
- PDF extraction library — `pdfplumber` is the spec default; confirm it's
  already in `pyproject.toml`. If not, this commit adds it.

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
- [ ] Read `docs/paper_resolver_pilot.md` end-to-end before changing
      `PaperExtract`.
- [ ] **Stop and ask** if any of these is true after reading the pilot:
  - PDF text is too noisy for reliable equation capture (no `key_equations`
    field).
  - Section structure isn't preserved (`architecture_summary` won't work as
    a free-text field; may need sub-fields).
  - Paper-specific oddity (`relevance_to_squid` may need to be neutralised to
    `relevance_to_domain` for generality).
- [ ] Finalize `PaperExtract` fields based on the pilot. Default candidate
      list (subject to pilot review): `title`, `authors`, `year`,
      `core_idea` (≤80 words), `architecture_summary` (≤150 words),
      `key_results` (≤120 words), `relevance_to_squid` (≤100 words).
      Decide via pilot whether to add `key_equations: str` (LaTeX) and
      `architecture_diagram_md: str`. Document the per-field word budget
      in the docstring.
- [ ] Remove the provisional `TODO` comment.
- [ ] Write `render_paper_extract_prompt(raw_text)`:
  - System prompt: role = "research-paper summariser for an ML denoising
    agent"; output **must** be valid JSON matching `PaperExtract`; word
    budgets per field; missing fields → `""` not `null`.
  - User prompt: includes the raw paper text (truncated to a documented
    max-char cap that fits the model's context window — confirm the cap by
    reading `agent/llm_bridge.py`'s context handling, do not guess).
- [ ] Unit test: feed a hand-crafted valid JSON string through
      `bridge.generate(...)` (mocked) and assert `PaperExtract` parses it.
- [ ] Unit test: feed a malformed JSON string through mocked
      `bridge.generate(...)` and assert the node falls back to
      `verbosity_achieved=0` with `extract=None`. (Note: this test will be
      reused by Commit 4; this commit asserts the validation half only.)
- [ ] Unit test: prompt-rendering function produces deterministic output
      for a fixed input (snapshot-style — diff against an inline expected
      string).
- [ ] **Real-run test** (`@real_run`): call
      `bridge.generate(*render_paper_extract_prompt(tidmad_text))` with the
      TIDMAD paper text from the pilot. Validate the returned JSON parses
      into `PaperExtract`. **Show the user the actual extract output before
      closing the commit.**

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/schemas/test_literature_review_schemas.py tests/unit/agent/prompt_templates/test_literature_review_prompts.py -q
.venv/bin/python -m pytest tests/unit/agent/prompt_templates/test_literature_review_prompts.py -m real_run -q   # opt-in, real LLM call
.venv/bin/python -m ruff check agent/schemas/literature_review.py agent/prompt_templates/literature_review/
.venv/bin/python -m pyright agent/schemas/literature_review.py agent/prompt_templates/literature_review/__init__.py
```
Plus: real-run `PaperExtract` JSON shown to user and approved.

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

**Checklist**:
- [ ] Read `nodes/ml_hyperparameter_tune_agent.py` (specifically the `_run_skill`
      helper at L497-507 and the LLMBridge instantiation block) and match the
      conventions exactly:
  - Skill import via `importlib.import_module(f"agent.skills.{folder}.wrapper")`.
  - LLMBridge access as singleton (no new instance — `LLMBridge.get_instance()` or
      whatever the actual accessor is — confirm by reading).
  - JSON parsing pattern for `bridge.generate(...)` responses.
- [ ] Implement the node as `def run(input: LiteratureReviewInput) -> LiteratureReviewOutput`
      module-level function (match the simpler nodes in the project; if the
      project convention is a class with `.run()`, follow that — confirm
      before writing).
- [ ] Root-paper resolution:
  - [ ] For each `root_papers[i]`, compute cache path
        `reference_data/root_papers_cache/{paper_id}.json`.
  - [ ] Cache hit → load `RetrievedPaper` from JSON. Cache miss → call
        `paper_resolver_skill.run_skill(None, ...)`, build `RetrievedPaper`,
        write cache.
  - [ ] For verbosity=1 root papers without an extract on cache miss: call
        LLMBridge compression prompt (Commit 3) on the full text, then write
        the extract back to cache with `verbosity_achieved=1`.
- [ ] Dynamic search loop:
  - [ ] At round 0: LLM is asked "given the experiment_history and the
        root-paper extracts, what should we search S2 for?" (JSON output:
        `{"query": str, "verbosity": int} | {"done": true}`).
        Mark with `# TODO(reflector-split): this decision step is the
        natural future reflector-model candidate (cheap, templated).`
  - [ ] Each round: call `paper_resolver_skill.run_skill(None, mode="search",
        query=..., limit=..., verbosity=0)` to get candidate papers as S2
        metadata. If the LLM then requests verbosity escalation on a
        specific paper, call `mode="resolve"` for that paper. Append to
        `retrieved_papers`.
  - [ ] LLM is asked "another query, escalate verbosity on paper X, or done?"
        Same TODO marker.
  - [ ] Terminate when LLM says `{"done": true}` OR when
        `search_rounds_used >= input.dynamic_search.max_rounds`. The
        max-rounds branch is the hard safety net.
- [ ] Final synthesis call: LLM is given the full `retrieved_papers` list +
      `experiment_history` and produces the four `ExternalAgentOutput`
      channels (JSON). For v1, `new_vocab_candidates` and `suggested_mindset`
      are documented in the prompt as "leave empty / null unless you have
      strong cross-paper convergent evidence."
- [ ] Build and return `LiteratureReviewOutput` with all fields populated;
      `started_at`/`finished_at` ISO 8601 UTC.
- [ ] Write `nodes/ml_literature_review.py` storage: dump the
      `LiteratureReviewOutput` to
      `{storage.local.workspace}/ml_literature_review_{run_name}.json` per
      the inter-node communication invariant in `CLAUDE.md`.
- [ ] Unit tests (`tests/unit/agent/ml_literature_review/test_node.py`):
  - [ ] Full run with mocked LLMBridge (returns canned JSON for each call)
        and mocked `paper_resolver_skill.run_skill` (returns canned
        `RetrievedPaper` dicts). Asserts `LiteratureReviewOutput` validates
        and has the expected `agent_card`, `findings`, `retrieved_papers`.
  - [ ] Dynamic loop terminates at `max_rounds` even when mocked LLM never
        emits `{"done": true}` — assert `search_rounds_used == max_rounds`.
  - [ ] Root paper cache hit — file pre-written at the expected path; assert
        `paper_resolver_skill.run_skill` is NOT called for that paper.
  - [ ] Root paper cache miss — file absent; assert
        `paper_resolver_skill.run_skill` IS called and a JSON cache file is
        written at the expected path with the resolver's result.
  - [ ] LLM compression fallback: mocked compression call returns malformed
        JSON → resulting `RetrievedPaper.verbosity_achieved == 0`,
        `extract is None`, but the node does not raise.
  - [ ] Storage dump test: `LiteratureReviewOutput` JSON file written at the
        documented path; round-trips through `model_validate_json`.
- [ ] Integration test (`tests/integration/nodes/test_ml_literature_review.py`,
      `@real_run`): one root paper (TIDMAD), `max_rounds=2`, real S2 + real
      LLMBridge. Asserts `LiteratureReviewOutput` validates and has at least
      one `ExpertContextItem` in `findings`. **Show the user the full output
      before closing the commit.**

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/ml_literature_review/ -q
.venv/bin/python -m pytest tests/integration/nodes/test_ml_literature_review.py -m real_run -q   # opt-in
.venv/bin/python -m ruff check nodes/ml_literature_review.py tests/unit/agent/ml_literature_review/ tests/integration/nodes/test_ml_literature_review.py
.venv/bin/python -m pyright nodes/ml_literature_review.py
```
Plus: integration test output reviewed by user.

**Open questions / decisions needed**:
- **Node entry shape.** Class-with-`.run()` or module-level `run()`? Check
  `nodes/ml_hyperparameter_tune_agent.py` and match. If unclear, ask.
- **Per-round verbosity escalation policy.** The LLM is allowed to ask for
  a specific paper to be re-fetched at higher verbosity. Should the node
  cap how many escalations per round, or trust the LLM + `max_rounds`?
  Lean: trust + `max_rounds`. Document the choice.

---

## Commit 5 — Protocol file (audit-only)

**Goal**: Land the per-edge protocol mapping `LiteratureReviewOutput` →
`ProposalInput` channel updates, and **document the audit finding** that
`local_full_context` in the upstream protocol already threads `mindset` and
`agent_cards` end-to-end (no patch needed).

**Files**:
- New: `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`
- New: `tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py`

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
    — returns a dict with the four kwargs that `local_full_context` expects
    from external agents: `expert_context=output.findings`,
    `vocab_seed=output.new_vocab_candidates`, `agent_cards=[output.agent_card]`,
    `mindset=output.suggested_mindset`. Returns a dict (not a typed object)
    because it gets spread into `local_full_context(**update_dict, ...)`.
  - `database_all_channels(...) -> dict[str, Any]` placeholder that raises
    `NotImplementedError`.
- [ ] Tests:
  - [ ] `local_all_channels` maps all four channels correctly with a fully
        populated `LiteratureReviewOutput`.
  - [ ] `local_all_channels` passes through `new_vocab_candidates=[]` and
        `suggested_mindset=None` without error (v1 wired-empty channels).
  - [ ] `local_all_channels` wraps a single `agent_card` into a list of one
        (the field on `ProposalInput` is `agent_cards: list[AgentCard]`).
  - [ ] `database_all_channels` raises `NotImplementedError`.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py -q
.venv/bin/python -m ruff check agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py
.venv/bin/python -m pyright agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py
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

## Commit 6 — Workflow integration

**Goal**: Wire the lit-review call into `workflows/model_exploration.py`
between interpretation and proposal, with `merge_external_agent_outputs` as
the (currently single-input) aggregator and `should_run_literature_review`
as the always-true trigger.

**Files**:
- Edit: `workflows/model_exploration.py`
- New: `configs/lit_review_config.yaml`
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
  - `findings`: concatenate across outputs.
  - `new_vocab_candidates`: concatenate.
  - `agent_cards`: one card per output, accumulated.
  - `suggested_mindset`: last non-None wins (documented as a v1 rule; flagged
    for revisit when the second agent populates this — see §9 Q2 of the
    architecture doc).
  - Returns the four-kwarg dict directly consumable by `local_full_context`.
- [ ] Add `should_run_literature_review(interp_output: InterpretationOutput) -> bool`:
      always returns `True` for v1. Docstring includes the cost-tradeoff
      note from spec §6.
- [ ] Load `configs/lit_review_config.yaml` at workflow startup (path resolved
      relative to project root via the same mechanism the workflow already
      uses for other configs — grep for `yaml.safe_load` to confirm). Convert
      the parsed dict into `LiteratureReviewInput` minus the
      `experiment_history` field (filled in per-iter from interp output).
- [ ] At the per-iteration insertion point:
  ```
  interp_output = result_interpretation_agent.run(...)
  if should_run_literature_review(interp_output):
      lit_input = build_lit_review_input(lit_review_config, interp_output, ...)
      lit_output = ml_literature_review.run(lit_input)
      external_outputs = [lit_output]
  else:
      external_outputs = []
  external_channels = merge_external_agent_outputs(external_outputs)
  for attempt in range(1, max_proposal_attempts+1):
      proposal_input = local_full_context(
          interp_output, ..., **external_channels,
      )
      ...
  ```
- [ ] Create `configs/lit_review_config.yaml`:
  ```yaml
  root_papers:
    - source_type: arxiv
      identifier: "2302.09309"      # TIDMAD
      verbosity: 1
  dynamic_search:
    enabled: true
    max_rounds: 3
    initial_verbosity: 0
    escalation_allowed: true
  ```
- [ ] Create `reference_data/root_papers_cache/README.md` explaining: format
      (one JSON file per paper, named `{paper_id}.json`, content is a
      serialized `RetrievedPaper`), invalidation (delete the file manually
      to force re-fetch + re-compression), and why this cache is committed
      (per-agent committed cache per architecture doc §8 *Cache and
      reproducibility*).
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
- [ ] Tier-0 dual-mode integration test (existing workflow test, if any) is
      re-run to confirm nothing broke. If there is no existing dual-mode
      test for this insertion point, the wiring smoke test above stands as
      the gate.

**Test gate**:
```
.venv/bin/python -m pytest tests/unit/workflows/test_model_exploration_lit_review_wiring.py -q
.venv/bin/python -m pytest tests/unit/workflows/ -q   # full workflow unit dir to catch wiring regressions
.venv/bin/python -m ruff check workflows/model_exploration.py configs/lit_review_config.yaml tests/unit/workflows/test_model_exploration_lit_review_wiring.py
.venv/bin/python -m pyright workflows/model_exploration.py
```

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
