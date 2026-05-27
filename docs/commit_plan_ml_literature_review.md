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
- [ ] **Commit 4** — `nodes/ml_literature_review.py` core loop
  · gate `tests/unit/agent/ml_literature_review/test_node.py` + real-run output reviewed
  - [ ] **Checkpoint C** — Dynamic search loop behavior
- [ ] **Commit 5** — Protocol `ml_literature_review_to_ml_model_propose.py` (audit-only on `local_full_context`)
  · gate `tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py`
- [ ] **Commit 6** — Workflow integration (`merge_external_agent_outputs`, `should_run_literature_review`)
  · gate `tests/unit/workflows/test_model_exploration_lit_review_wiring.py` + Tier-0 dual-mode
  - [ ] **Checkpoint D** — End-to-end proposer behavior change
- [ ] **Commit 7** — Configs, cache dir README, full connection audit
  · gate full `tests/unit/` + `tests/integration/` green

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
from nodes import ml_literature_review

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
out = ml_literature_review.run(lit_in)

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
      identifier: "2406.04378"      # TIDMAD
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

#### 🔍 Behavioral Checkpoint D — End-to-end proposer behavior change

**Trigger**: run this after the test gate passes. This is the
highest-stakes checkpoint — it decides whether the entire lit-review
addition produces a measurable, traceable improvement in the proposer's
output.

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
- Are the `cite_id` values in Run A's reasoning real — do they match actual
  `cite_id` values from `LiteratureReviewOutput.findings`? Or has the
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
- If Run A has hallucinated `cite_id`s → the proposer is generating
  plausible-sounding references rather than using the actual ones. Fix: add
  an explicit instruction to the proposer to only cite `cite_id` values
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
