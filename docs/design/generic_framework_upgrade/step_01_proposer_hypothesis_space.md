# Step 01 — 6-P Proposer Hypothesis Space & Prompt Surfaces — detailed design

## Status

**DRAFT — OPERATOR REVIEW PENDING. Design/audit only — NOTHING in this
document authorizes implementation.**

Created 2026-08-12 on branch `docs/generic-framework-step-01-design`,
based on the Step-00 implementation head `71f6b31f`
(`feat/generic-framework-step-00-golden-baseline-harness`) so the
landed Step-00 baselines could be read directly.

**STEP-00 IS AN UNMERGED DESIGN DEPENDENCY (blocking freeze).** This
design cites Step-00 baseline IDs (PB-0/PB-3/PB-4, WF-3, CFG-1/2/3a/3b,
…) that exist on the Step-00 PR branch (PR #198, open, CI pending,
merge pending in another session) but NOT yet on master. Freeze
preconditions (directive rule 9 — none of them performed here):

1. Step-00 PR merged to master.
2. Updated master contains the actual baseline IDs cited in §8/§11.
3. Step-00 Checkpoint E roadmap sync complete.
4. THIS design rebased/re-synchronized onto that master, with every
   cited baseline re-verified present and green there.
5. Any Step-00 closure-audit correction affecting Step 01 incorporated.

Until then no Stage-A claim in this document is FINAL evidence — each
is a claim against the Step-00 branch head `71f6b31f`, re-verifiable at
freeze.

## 0. Relationship to the frozen roadmap and to Step 00

This is the Step-01 detailed design required by the FROZEN roadmap
(`docs/design/siderius_generic_framework_upgrade.md`, operator approved
2026-08-11; O1 proposer-first CONFIRMED — roadmap §15.0(4)). Binding
roadmap contract for Step 01, transcribed from the roadmap:

- **Identity**: step 1 = "6-P Proposer hypothesis-space & prompt
  surfaces" — the PROPOSER slice of §13 pulled forward (§15.0(1);
  single ownership, no duplication with step 04).
- **Final effect (roadmap §15.1 row 6-P)**: "Proposer prompts DERIVE
  from the declared task profile: task facts + contract PROSE
  (shapes/classes/task_type/loss legality) render from existing
  authorities instead of literals; TIDMAD proposals unchanged."
- **Scope limits (roadmap 3rd review F2, binding)**: the
  dataset-constraints block stays regime-A on the `DATASET_CONFIG`
  singleton until step 2; ForwardContract/model-contract SEMANTICS
  stay §5-owned — Step 01 only RENDERS the declaration.
- **A (Stage-A parity surface)**: "rendered proposer prompts (all 3
  stages incl. commit) EXACT-equal for TIDMAD + same kwargs reach
  LLMBridge (§2 nondeterministic surface)."
- **B (Stage-B contrast dimension)**: roadmap fixtures 13.4-A
  (task-description text only) + 13.4-B (declared forward contract,
  PROSE-rendering only) — atomic, one axis per fixture, never both.
- **C (live integration)**: "the PRODUCTION proposer renders from the
  profile in a real chain iteration; contract-reassertion pins
  re-targeted to profile-parameterized form IN THIS PR (its design
  states the semantic change)" — this document states that semantic
  change (§11, row for `test_contract_reassertion.py`).
- **Dependencies**: step 0 only. The constraints-block slice completes
  after step 2 (roadmap matrix Deps column).
- **Commit prompt fact (roadmap §15.0(1), 3rd review finding 1)**: the
  commit prompt is a plain string with ZERO substitution today (passed
  verbatim); extracting it is NEW placeholder/render work — an
  EXTENSION of the live single-template+placeholder mechanism, landed
  WITH its first consumer (the rendered prompt) in the same PR.
- **Authorities already exist**: shapes/classes/task_type from
  `ForwardContract` (live, consumed); loss-legality facts from
  `ml_models/models_format_sandbox.py` `CLASSIFICATION_LOSSES` /
  `REGRESSION_LOSSES` frozensets — today the VALIDATION authority
  only, gaining their FIRST prompt-render consumer in this PR.
  Prompt-side loss legality is re-prosed in ≥5 more places which STAY
  until their own steps. No dependency on §5's future config is
  created; §5 still owns the contract's semantics.
- **Explicit exclusions (6-M, step 4)**: validator/implementor probe
  recipes and generated templates (256/T=64 literals), FU-A-1
  transport (`_PROBE_NUM_CLASSES=256`), custom-loss probe shapes,
  implementor/validator/planner/reflector/lit-review prompts, the
  hybrid-alphabet decision. Segmentation legality
  (`proposal.py` dataset-divisibility check) stays regime-A on the
  singleton until §4 — it does not block 6-P.
- **Checkpoint model**: roadmap §17 (0/A/B/C/D/E) — instantiated in
  §16 below.
- **Compatibility iron law (roadmap §2)**: rendered prompts =
  EXACT string equality for the TIDMAD profile; nondeterministic
  surface = "same kwargs reach LLMBridge" boundary capture.

Step 00 is the direct dependency: it captured the baselines this step
claims parity against. The Step-00 coverage manifest row for step 01
(step-00 design §15.1) maps this step's A-surface to: **PB-0, PB-3,
PB-4 (prompts); WF-3 (label/components kwargs at proposer `generate`
sites); CFG-1/2, CFG-3a/b (task-description channel)**. Two §15.2
deferrals are explicitly assigned to THIS design:

1. **Legacy proposer path reachability (Step-00 UNKNOWN A.1)** —
   resolved in §3.2 below.
2. **Shipped-task-description → proposer JOIN** — "CFG-2 pins the
   shipped string; PB-3 pins the render with a test-owned description;
   the JOIN (proposer actually reading the shipped description) is
   step 01's own A-work" — designed in §8.3 below.

## 1. Final behavioral effect

When Step 01 is complete, the following is TRUE about SIDERIUS
(behavioral outcomes, not mechanics):

1. **The proposer's hypothesis space is declared, not memorized.** The
   task facts that bound what the proposer may propose — input/output
   tensor shapes, class count, task type, and which loss families are
   legal for which output type — reach every proposer prompt surface
   (pipeline comparison/causal/proposing stages AND the legacy
   reasoning/commit surfaces) by RENDERING from their existing
   authorities (`ForwardContract` from the shipped task config; the
   `CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES` frozensets), never from
   prompt-resident literals. Editing `configs/task_config.yaml`
   changes what the proposer is told; editing prompt files cannot
   silently contradict the schema/validator anymore for these facts.
2. **The production proposer actually reads the shipped task
   description.** Today the pipeline path (the standard production
   path) never renders `task_description` anywhere — the LLM proposes
   architectures without ever being told what the task is, beyond
   contract shapes and residual prose. After Step 01, the shipped
   description renders into the production pipeline prompts (the
   JOIN — Step-00 §15.2's assigned A-work), and a changed description
   provably changes the rendered prompt.
3. **TIDMAD proposals unchanged**: under the shipped TIDMAD task
   config, extraction commits render byte-identical prompts (Step-00
   PB-3/PB-4/PB-0 goldens stay green UNMODIFIED); the single
   deliberate render change (the JOIN) is its own commit with an
   explicit, provenance-stamped golden regeneration (§13) — nothing
   changes silently.
4. **A different task renders a different hypothesis space with zero
   SQUID residue in the derived blocks**: the Stage-B fixtures prove
   that swapping ONLY the task-description text (13.4-A) or ONLY the
   declared forward contract (13.4-B) flows through the real
   production render path into the proposer prompts, with the
   TIDMAD-specific prose absent from the profile-derived blocks.
5. **The loss-legality prose can no longer drift from the validator.**
   The prompt statement of legal loss families is DERIVED from the
   same frozensets the validation path enforces
   (`models_format_sandbox.py:368,371,425-433`) — the first
   prompt-render consumer of that authority. A future loss-family
   change updates prompt and validation together or fails the parity
   goldens loudly.

## 2. Non-goals and deferrals

Everything below is EXPLICITLY out of scope. Touching any of it is a
material deviation requiring an operator stop.

| # | Non-goal | Owner |
|---|---|---|
| N1 | Implementor/validator mechanics: probe recipes, probe tensor shapes, `_PROBE_NUM_CLASSES=256` (FU-A-1 transport), generated-plugin templates/`_OUTPUT_CONTRACT_COMMENTS`, implementor self-check, validator LLM prompt, implementor code/loss/repair prompts | 6-M, step 04 |
| N2 | Planner/reflector prompts (incl. the >3-history condensed branch — OD-1's step-07a predecessor), interpretation, cache-consolidator, lit-review prompts (incl. the CFG-3a duplicate task_description collapse) | steps 04/07a/09 |
| N3 | Dataset Profile / DatasetConfig extraction; the known-constraints block stays regime-A on the `DATASET_CONFIG` singleton (`agent/prompts.py:722`, call :1569); segmentation legality (`nodes/ml_model_proposal_agent/proposal.py` divisibility reads) | step 02 |
| N4 | Model/Loss Contract SEMANTICS: output_type alphabet, hybrid disposition, loss-family membership, custom-loss probe recipes — Step 01 RENDERS declarations, never redefines them | step 03 (§5) |
| N5 | Task composition root / regime-B fail-closed binding; no mega TaskConfig; no new YAML file | step 12 |
| N6 | Metric identity: `denoising_score` grammar in causal_reasoning_stage.md:107 stays as-is (MIGRATION PARITY) | step 06 |
| N7 | Transport/schema changes: NO new `ProposalInput`/`ProposalOutput` fields, no protocol changes, no parser allow-list changes (§3.5 shows no new fact needs to survive PAST the prompt render) | n/a — see §6.4 |
| N8 | Hardware/resource facts into task config: the [HARDWARE CONTEXT] runtime block remains the sole budget authority (roadmap §14 resolved row); no VRAM/param literals introduced or "extracted" into config | framework invariant |
| N9 | Forbidden-pattern list extraction: source audit found the forbidden-pattern surface lives ENTIRELY in the validator (`agent/skills/forbidden_pattern_skill.py`, consumed only by `ml_code_validator_agent.py:51,534`; ZERO forbidden-pattern prose in any proposer surface) — despite the roadmap step-1 line naming "forbidden-pattern lists". Recorded as a roadmap-vs-source discrepancy; recommended disposition: 6-M (step 04) owns it with the validator surfaces. OPERATOR DECISION REQUIRED (§19 OD-S1-1) — not silently dropped, not silently absorbed | §19 OD-S1-1 |
| N10 | Prompt WORDING improvements, persona rewrites, dead-code cleanup (e.g. the five ad-hoc test bridges), retry-policy changes, `StubLLMBridge`/pseudo-fidelity work | n/a |
| N11 | The lit-review `task_description` duplicate (`configs/lit_review_config.yaml`) — guarded by CFG-3a, collapses at step 04 | step 04 |
| N12 | Renaming/moving prompt template files for cleanliness | n/a |

## 3. Source audit — current production proposer flow

Audit protocol: four parallel read-only audits (A production
flow/transport, B prompt content/authorities, C proposer test
inventory, G test runtime) + a main-auditor Area-F history audit;
every load-bearing claim below re-verified in source by the main
auditor. All line numbers at head `71f6b31f`.

### 3.1 Production flow map (main-auditor verified)

```text
run_one_iteration.py --llm_config <json>          (chain entry)
  → WorkflowLLMConfig.from_json (:1817-1818) or .uniform (:1826)
  → run_workflow → _get_reasoning_pipeline
      (workflows/model_exploration.py:1904-1910; returns a pipeline
       ONLY when llm_config.propose is a ProposalLLMConfig
       — :202-225: 2 stages comparison + causal_reasoning)
  → protocol local_full_context(...) (:2262-2283)
  → POST-HOC input mutation (:2284-2301): existing_model_types;
      task_description = get_task_description(load_task_config());
      forward_contract = ForwardContract(**cfg["forward_contract"]);
      previous_failures; mindset; hardware_context; vram_budget_gb
  → MLModelProposalAgent.run() (ml_model_proposal_agent.py:1321)
      dispatch :1328-1334: pipeline if any enabled stage else legacy
  → _run_pipeline (:1432): mode resolve → candidate select/enrich →
      shared blocks (:1512-1520: hardware, data-scope, constraints,
      agent-cards, expert-context, vocab, cold-start) →
      template_vars (:1561-1614) →
      per-stage: load_stage_prompt(system) + P-d-ordered user parts
      → bridge.generate/generate_text(label=proposer.<stage>,
        components=audit) (:1683-1698)
      → boldness retry (:1702-1786) + causal-owned validation
        correction loop (:1798-1885)
      → proposing stage ALWAYS last (:1887-1890), structural retries
        (_MAX_PROPOSING_RETRIES) with error re-injection
      → ProposalOutput.model_validate over an EXPLICIT allow-list of
        raw keys (:1990-2016) with validation context
        {loss_registry_names, model_registry_names}
  → candidate_id minted post-parse, both modes (:1342, PR E)
  → persisted proposal_{run}.json (:1345-1352)
  → protocol local_full_spec → MLModelImplementor
```

### 3.2 Legacy-path reachability (resolves Step-00 §15.2 UNKNOWN A.1)

- Dispatch: legacy runs iff `inp.reasoning_pipeline` is None/empty/no
  enabled stage (:1328-1334). The workflow supplies a pipeline iff
  `llm_config.propose` is a `ProposalLLMConfig`
  (model_exploration.py:202-225); the field is typed
  `ProposalLLMConfig | None` (workflows/llm_config.py:236-241).
- `WorkflowLLMConfig.uniform()` (the no-`--llm_config` chain default,
  run_one_iteration.py:1826) ALWAYS builds a `ProposalLLMConfig`
  (llm_config.py:438-443) → pipeline.
- All four shipped operator configs (`llm_configs/*.json`) carry a
  `propose` block with comparison/reasoning/proposing slots →
  pipeline.
- **Verdict**: NO shipped SDSC production launcher or shipped
  `llm_configs/*.json` reaches the legacy path. It IS reachable from
  three non-standard entries (Area-A audit): (i) an operator-authored
  `--llm_config` JSON that omits/nulls `propose` (silent fallback, only
  the "legacy 2-call mode" print at model_exploration.py:1919 differs);
  (ii) `workflows/model_exploration.py` run as `__main__` with neither
  `--llm_config` nor `--provider` (`WorkflowLLMConfig()` default →
  propose=None); (iii) the node's own standalone CLI `main()`
  (`ml_model_proposal_agent.py` tail — builds ProposalInput with no
  pipeline, no task_description). Additionally
  `tests/integration/workflows/test_pr_e_funnel_gate_pseudo.py`
  exercises the legacy path in-repo. The legacy path is therefore
  production-reachable-by-configuration, NOT dead code and NOT the
  standard path. Consequence for Step 01: the legacy surfaces
  (PROPOSAL_REASONING_PROMPT + commit prompt) stay in scope for
  extraction parity (PB-0/PB-4 pin them), but the LIVE integration
  checkpoint (§10) must run through the PIPELINE path.

### 3.3 The commit prompt (main-auditor verified)

`PROPOSAL_COMMIT_PROMPT` = `nodes/ml_model_proposal_agent/
ml_model_proposal_agent.py:322-384`, a plain module-level string with
ZERO placeholders, passed VERBATIM as the system prompt at :1384-1388
(`label="proposer.legacy_commit"`), legacy mode only. Task facts
hardcoded inside it (each restated relative to an existing authority):

| Literal (quote) | Lines | Existing authority |
|---|---|---|
| `"classifier" emits [B, 256, T] per-timestep class logits and admits loss_type ce/focal/focal_cw; "regressor" emits [B, T] the denoised waveform directly and admits loss_type smooth_l1` (output_type field spec) | :330 | ForwardContract (shapes/classes) + `CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES` (`ml_models/models_format_sandbox.py:368,371`) |
| Golden-Paragraph citation prose: `Input: [B, T] int64 (per-timestep ADC class indices)`, `[B, 256, T] float32 (per-timestep logits over 256 denoising classes)`, `[B, T] float32 (the denoised waveform directly)`, `256 denoising bins per time step is contract-fixed, not a hyperparameter` | :332 | ForwardContract fields (input_shape/output_shape/num_classes/descriptions) |
| Hard-constraint block: `The input is fixed: [B, T] int64`; classifier/regressor output+loss legality table | :365-373 | ForwardContract + loss frozensets |
| train_config example values (lr/epochs/batch/optimizer) + `loss_config {"loss_type": "focal", ...}` | :347-358 | example JSON skeleton — proposer-owned prompt content (focal example is TIDMAD-flavored) |
| `[HARDWARE CONTEXT]` references (VRAM constraints relative to "the effective cap") | :336, :374-378 | runtime hardware block (the CORRECT precedent — no literal budgets) |

### 3.4 Pipeline prompt assembly and the template_vars seam

- Substitution mechanism: `load_stage_prompt` = base `.md` +
  `{# EXPLORATION_MODE_BLOCK #}` mode/mindset block + naive
  `str.replace` per `template_vars` key
  (`agent/prompt_templates/proposal/__init__.py:30-78`). Placeholders
  absent from a template are silent no-ops — the extension mechanism
  AND the silent-drop hazard (§5, §15 mutation M-3).
- `template_vars` (:1561-1614): minimum_boldness, n_agent_proposed,
  n_confirmed_links, existing_model_types, known_constraints_block
  (`_format_known_constraints_block(DATASET_CONFIG)`,
  agent/prompts.py:722-760 — regime-A on the singleton until step 2),
  recent_gate_exhaustions_block, recent_trial_validity_block,
  healthgate_evidence_block, **task_description (:1597 — CONSUMER-LESS:
  no proposal template contains `{task_description}`, verified by
  grep over `agent/prompt_templates/proposal/*.md`)**,
  forward_contract (rendered via `render_forward_contract`, consumed
  ONLY by proposing_stage.md:131), available_losses_block,
  available_models_block.
- Placeholders per template (verified): comparison_stage.md →
  {minimum_boldness}, {available_losses_block}; causal_reasoning_
  stage.md → {minimum_boldness}; proposing_stage.md →
  {known_constraints_block} (:109), {forward_contract} (:131), plus
  policy vars. NO stage template renders the task description.
- **Consequence (the JOIN gap, Step-00 §15.2 last row)**: on the
  PRODUCTION pipeline path the shipped `task_description` NEVER
  reaches any rendered prompt — only the forward contract does
  (proposing stage only; comparison/causal see NO task-profile
  content). The legacy path DOES render it ({TASK_BACKGROUND} in
  PROPOSAL_REASONING_PROMPT:282, substituted at :423-435 via
  `_render_task_background` :392-420). The in-module precedent for a
  task-background block therefore already exists.

### 3.5 Parse/validation/transport (area D summary)

- Both construction sites build `ProposalOutput` from an EXPLICIT
  allow-list of `raw.get(...)` keys (legacy :1398-1417, pipeline
  :1990-2016) — a key absent from the allow-list is SILENTLY dropped
  and the schema default applies (the V21 PR A Gate-1R incident is
  documented in-source at :1401-1403). Any NEW task fact that must
  survive into ProposalOutput needs an allow-list entry + schema
  field; Step 01 adds NONE (it changes prompt content only — §6).
- candidate_id: system-minted post-parse for both modes (:1336-1342,
  PR E) — never LLM-supplied; Step 01 must not touch it.
- Retry/revision: pipeline = structural retries on the proposing stage
  with error re-injection (stages 1-2 never re-run) + boldness retry +
  causal-owned correction loop; legacy = no structural retry (raises).
- Persistence: `proposal_{run_name}.json` (:1345-1352); resume restores
  "previous proposal" from it (core/resume.py inventory).

### 3.6 History / prior-PR constraints (Area F)

- **enable_global_task_config.md (SHIPPED, 2026-06)** created the
  exact seam Step 01 extends: `{TASK_BACKGROUND}`/`{FORWARD_CONTRACT}`
  placeholders, T2 implementor + T3 proposer injection; its "out of
  scope" list already deferred the DATASET_CONFIG import — consistent
  with this design's N3.
- **V21 PR A (reachable output contract, MERGED)**: KEEP-256 decision
  with FU-A-1 filed on the validator probe ("wiring it needs a NEW
  transport") — Step 01 must not absorb it (N1); the explicit parser
  allow-lists and the output_type reachability pins are PR-A property
  owners this step must keep green.
- **V21 PR E (candidate funnel, MERGED)**: candidate_id system-minted
  at the single post-parse site (:1342), transported through the real
  protocols, behaviorally inert — untouchable (§3.5); its exact
  key-set pins (test_pr_e_stage_contract_pins.py) forbid casual schema
  additions, reinforcing N7.
- **genericity_contract.md Seam 3 (task pack)**: anticipated exactly
  this content ("task description, forward contract, task-specific
  prompt fragments travelling as one pluggable unit"); the roadmap
  (§0.A) is the seam authority now — DQ-7 records the doc-sync
  question.
- **Stale assumptions corrected by this audit**: (i) the Step-00-era
  UNKNOWN A.1 is resolved (§3.2); (ii) the roadmap's step-1
  "forbidden-pattern lists" phrase does not survive source contact
  (OD-S1-1); (iii) `_render_task_background`'s own docstring claims it
  serves "the proposing-stage .md templates" — false today (its only
  call site is legacy; Area-A) — corrected as part of S1-C's docstring
  hygiene.

## 4. TIDMAD coupling inventory (proposer prompt surfaces)

Complete surface inventory (Area-B audit; load-bearing rows re-verified
by the main auditor). Surfaces: S1 `PROPOSAL_REASONING_PROMPT`
(:275-319, one placeholder {TASK_BACKGROUND} at :282); S2
`PROPOSAL_COMMIT_PROMPT` (:322-384, ZERO placeholders); P1-P9 the nine
stage templates under `agent/prompt_templates/proposal/` (placeholder
map in §3.4 + Area-B table: comparison_stage.md has ONLY the
mode-block hook; causal has {available_losses_block} :37 +
{minimum_boldness} ×2 :140; proposing has 8 distinct placeholders,
with the loss/model registry blocks each substituted TWICE — global
`str.replace`); ~13 programmatic block renderers (cold-start,
data-scope, hardware, constraints, trial-validity, gate-exhaustions,
healthgate-evidence, accumulated-JSON, vocab, legacy user, commit
user, known-constraints, registry/cards/context blocks).

Task-fact rows (F-numbers from the Area-B audit; class per §5 legend):

| # | Fact | Where hardcoded (evidence) | Class | Step-01 action |
|---|---|---|---|---|
| F1/F3 | 256 classes; shapes `[B,T] int64 → [B,256,T] float32` / `[B,T] float32` | commit prompt :330,:332,:365-370; proposing_stage.md:41,:70-71,:74 ("256 amplitude bins") — literals with zero config read; the SAME fact reaches proposing_stage.md:131 correctly via `{forward_contract}` | (e) restatements of a live authority | **EXTRACT-RENDER** from ForwardContract (Stage A, byte-parity) |
| F5 | loss legality per output_type | 7 proposer-owned prose sites: commit :330,:367-370; proposing_stage.md:41,:68-71,:85-86,:92,:168 (+2 indirect: `agent/schemas/proposal.py:974-975,:1247-1248` error text) — NONE imports the frozensets; 6 more sites in OTHER nodes (planner `agent/prompts.py:183-184,:1036-1054,:1072-1073` incl. a model-name-keyed rule of the shape V21 PR A deleted from code; reflector :1272; `check_config_format_skill/wrapper.py:22`; implementor :1574) | (e) proposer sites; other-node sites stay per roadmap | **EXTRACT-RENDER** the 7 proposer prose sites from `CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES` (+"custom" from the Literal alphabet); the schema error-text sites KEEP (validation-side, §5 owns); other nodes' 6 sites DEFER to steps 04/07a |
| F4 | output_type alphabet (proposals: 2-valued Literal, `agent/schemas/proposal.py:970`; runtime 3-valued with hybrid builtin-only; validator excludes hybrid `ml_code_validator_agent.py:318`) | prose restatements inside commit prompt + proposing template | (d)+(a) | RENDER the 2-valued proposal alphabet from the schema Literal (or keep literal where it is JSON-skeleton structure); the hybrid disposition is D2 (§5/step 03) — untouched |
| F8 | task description / SQUID prose | reaches the LEGACY path only ({TASK_BACKGROUND}); PIPELINE: `template_vars["task_description"]` supplied :1597, consumed by NO template | (e) dangling seam | **THE JOIN** (§8.3) |
| F6 | segmentation legality | known-constraints block PARAMETERIZED on the singleton (agent/prompts.py:745-746) — regime-A, stays; schema gate `agent/schemas/proposal.py:1095-1130` reads DATASET_CONFIG | (b) rendered from an authority (the singleton) | KEEP (step 02 swaps the object behind it) |
| F6' | powers-of-2 pedagogy ("16384, 8192, 4096 are INVALID… 16000 nearest") | agent/prompts.py:756-759 — TIDMAD-specific prose inside the otherwise parameterized block; false for other psd lengths | (e) | RECORD, DEFER to step 02 (its truth-value depends on the dataset profile; byte-parity keeps it now) |
| F7 | persona "senior ML architect specialising in deep learning for signal denoising" | S1 :276 (legacy); stage personas in templates | (a)/(e) | KEEP AS-IS (MIGRATION PARITY): outside the roadmap-narrowed 6-P fact scope (shapes/classes/task_type/loss legality); no persona authority exists to render from — inventing one violates §0.8. Recorded §18 deferred question |
| F9 | `denoising_score` grammar | causal_reasoning_stage.md:107 | (e) metric identity | KEEP (MIGRATION PARITY; step 06 owns the metric handle) |
| F10 | "baseline=4000" segments anchor | legacy user prompt :1168-1170 | (e) dataset volume fact, underived (200×20) | KEEP (MIGRATION PARITY; step 02 owns dataset facts) |
| F12/F13/F20 | budget prose: "~100M params" S1:284; "10 GB VRAM" causal_reasoning_stage.md:146; "≤ 80% of the effective cap" :540-541 | contradict the runtime [HARDWARE CONTEXT] block (the roadmap §14 RESOLVED row: derive from the runtime block, no config) | (e) | OD-S1-2 (§19): optional clearly-labeled cleanup commit deleting/re-pointing the two stale numerals (proposer templates have NO later owner — step 04's prompt scope excludes proposer surfaces), with golden regeneration; recommendation INCLUDE |
| F14/F15 | forbidden patterns: skill validator-only (`forbidden_pattern_skill.py`, consumers `ml_code_validator_agent.py:51,:534`); "T ≥ 80,000" never shown to the proposer; proposer's [DISALLOWED PATTERNS] block renders from a DIFFERENT authority (`architectural_pattern_tagger.ARCHITECTURAL_PATTERNS`, :701-709) | skill-local | (a) validator-side | OD-S1-1 (§19): roadmap names "forbidden-pattern lists" in step 1, source says validator-owned → recommend DEFER to 6-M; the tagger↔skill non-sharing is RECORDED as a coupling gap for step 04 |
| F16/F18 | model roster examples + "5.57 SOTA" scores (comparison_stage.md:50-76,:139; causal :121-122); frequency-band file prose (comparison :54-55 — contradicting :308-309/:343's own no-fixed-index rule) | template literals | (e) | KEEP (MIGRATION PARITY): catalogue = V11 (§5+§6 owned, steps 03/04); band semantics = V7 (§4, step 02). Both recorded; the internal contradiction registered as defect-not-blessed |
| F2/F11/F17 | int8/+128 encoding, 20-files/10M, CH1/CH2 | ABSENT from proposer prompts (encoding implied by "ADC class indices"/config's "0-255") | (d) | no action (correctly not exposed); recorded so nobody "extracts" a fact that is not there |
| — | quirks: registry blocks double-substituted (proposing :30/:177, :32/:235); `proposing_stage` loaded WITHOUT `mindset` (:1887-1891, asymmetric with the 3 reasoning-stage sites); `ProposalInput.constraints` never populated in production (absent from the protocol; only scripts inject it); shipped YAML `output_head_note` contains the un-substituted token `[output_shape]` rendered verbatim | verified | (e) | ALL KEPT byte-identical (parity); registered in §17.3 known-quirk list, never blessed |

## 5. Authority and ownership map

Legend (directive §7 format): fact | current source | semantic owner |
Step-01 role | consumer | migration disposition. Classes: (a)
module-local content, (b) rendered-from-authority, (c) runtime state,
(d) framework invariant, (e) accidental hardcode.

| Fact | Current source | Semantic owner | Step-01 role | Final production consumer | Disposition |
|---|---|---|---|---|---|
| task_description | `configs/task_config.yaml:10-14` via `load_task_config` (CFG-1/2 pinned) | §13 task profile (content); loader mechanics framework | JOIN: give it its first PIPELINE render consumer | all 3 pipeline stage prompts (system, via task-background block — §8.3) + existing legacy {TASK_BACKGROUND} | Step 01 consumes; content untouched |
| ForwardContract (shapes, num_classes, task_type, notes) | same YAML :20-35 → `ForwardContract` schema (`agent/schemas/task_config.py:31-120`, extra="forbid") → `render_forward_contract` (workflows/task_config.py:171-214) | SEMANTICS §5 (roadmap F2 limit); declaration+render mechanics exist today | RENDER-ONLY: replace the (e)-class shape/class restatements with renders of the declaration | commit prompt render + proposing template (existing :131 consumer stays) + any new derived block | Step 01 renders; never redefines fields; adds NO fields |
| num_classes=256 | YAML :25; exactly ONE production read today (task_config.py:209 render) | §5 (semantics), §13 (declared value) | render into the shape prose replacing literal 256s | rendered prompts | validator `_PROBE_NUM_CLASSES` stays literal (FU-A-1, 6-M) |
| Loss legality {ce,focal,focal_cw}/{smooth_l1} | `models_format_sandbox.py:368,:371` frozensets + `validate_output_loss_compatibility` :374-435 ("THE production authority", both execution paths consume it) | §5 / models_format_sandbox (validation authority) | FIRST prompt-render consumer (roadmap §15.0(1)): a proposer-owned renderer derives the legality prose from the frozensets | commit prompt + proposing-stage legality table/branch rules | prompt copies in OTHER nodes (6 sites) stay until steps 04/07a; the 5-value Literal alphabet (`models_format_sandbox.py:458`) is the "custom" source |
| output_type proposal alphabet | `agent/schemas/proposal.py:970` Literal["classifier","regressor"] | proposer module policy (validator agrees :318) | render/keep-consistent; no alphabet change | prompts + parse | hybrid disposition = D2 (step 03) |
| segmentation_size legality | `DATASET_CONFIG.psd_segment_length` + `valid_segmentation_sizes()` via `_format_known_constraints_block` (agent/prompts.py:722-760) and the schema gate (proposal.py:1095-1130) | §4 dataset (future); TIDMAD singleton today | UNTOUCHED (regime-A; roadmap F2 limit) | proposing stage :109 | step 02 swaps the authority object |
| Hardware/VRAM budgets | runtime `HardwareContext` (`core/hardware_context.py:51 _SAFETY_FRACTION`, :147-159) → `_render_hardware_context_block` :484-544 | framework/runtime (NEVER task config — roadmap §14 resolved) | keep the precedent; optionally delete the 2 stale numerals (OD-S1-2) | all stage user prompts (block emitted first) | no config field ever |
| prior failures / gate exhaustions / trial validity / healthgate evidence / vocab / expert context / agent cards / mindset / cold-start | typed runtime inputs via protocol + post-hoc fields | runtime state | UNTOUCHED | user prompts | never task config |
| Metric name `denoising_score` | causal template :107 + interpretation keys | §10 (step 06) | UNTOUCHED (MIGRATION PARITY) | — | step 06 handle |
| Dataset volume anchors (4000 segments; 20 files; psd 10M) | legacy prompt :1170 literal; known-constraints render; [DATA SCOPE] block | §4 (step 02) | UNTOUCHED | — | step 02 |
| Model catalogue/roster examples | comparison/causal template literals + registry-driven blocks (`render_available_models`) | §5+§6 (steps 03/04) | UNTOUCHED | — | steps 03/04 |
| Forbidden patterns (T-loop rule) | `forbidden_pattern_skill.py` (validator-consumed only) | 6-M/validator | UNTOUCHED (OD-S1-1) | validator | step 04 |
| Personas | S1:276 + template prose | no authority exists | UNTOUCHED (MIGRATION PARITY) | — | §18 deferred question (needs a declared task block — candidate for step 04/§13 remainder) |

**No new authority is invented anywhere in this table** — every
"render" row points at an authority that exists and is consumed by
production today; every fact without an authority is KEPT literal and
routed to its owning step.

## 6. Target proposer behavior flow (concepts, not frozen APIs)

The mechanism is the SANCTIONED one (roadmap Rev-2 finding 15 / §13.2):
single template + placeholder substitution, extended — never a new
prompt-assembly architecture, never a new YAML, never a mega-config.

### 6.1 Concept map

```text
AUTHORITIES (all pre-existing, none created):
  configs/task_config.yaml ── load_task_config ──► task_description
                                              └──► ForwardContract
  ml_models/models_format_sandbox.CLASSIFICATION_LOSSES /
                                  REGRESSION_LOSSES  (+ the 5-value
                                  loss_type Literal for "custom")
  runtime HardwareContext / DATASET_CONFIG singleton  (unchanged)

NEW PROPOSER-LOCAL RENDERERS (module-local, typed, unit-tested):
  contract-prose renderer: ForwardContract ──► the shape/class prose
      tokens today hardcoded in the commit prompt + proposing template
      (declared input shape, declared output shape, num_classes-derived
      classifier-form token; the two-output-form CATALOGUE prose stays
      module-local framework text — §5 convergence candidate)
  loss-legality renderer: frozensets ──► the per-output_type legality
      prose/table (first prompt-render consumer of the validation
      authority)
  task-background block (pipeline): task_description ──► a labeled
      block in stage system prompts (the JOIN), following the existing
      legacy _render_task_background precedent

TEMPLATES: PROPOSAL_COMMIT_PROMPT becomes a template with placeholders
  rendered AT THE CALL SITE (:1385 area — the first consumer, same
  commit); proposing_stage.md's hardcoded fact lines become
  placeholders fed via template_vars; comparison/causal gain the
  task-background placeholder (JOIN commit only).

UNCHANGED: dispatch, stage order, retry/boldness/correction loops,
  labels, component key sets, parser allow-lists, ProposalOutput
  schema, protocols, candidate_id, persistence, resume.
```

### 6.2 Derivation discipline (ownership guardrails)

1. Render the DECLARATION, never redefine it: renderers read
   ForwardContract fields and frozenset members verbatim; no parsing
   of shape strings, no recomposition beyond inserting `num_classes`
   into the existing classifier-form prose pattern; no new semantic
   rule anywhere.
2. The two-output-form catalogue ("classifier emits per-class logits /
   regressor emits the waveform directly", the regressor `[B, T]`
   form) is §5-owned SEMANTICS with no in-tree declarative authority
   today — it STAYS module-local literal prose, recorded as a §14-style
   convergence candidate for step 03 (do NOT invent an output-form
   registry here).
3. Empty/missing inputs fail VISIBLY in fixtures, not silently:
   renderers keep today's regime-A behavior for legacy callers (empty
   contract → "" per `render_forward_contract`), and the new Stage-B
   tests pin non-empty rendering under both profiles.
4. No new `ProposalInput`/Output field, no protocol change: every
   rendered fact is already transported (task_description +
   forward_contract are post-hoc injected by the workflow today;
   frozensets are imported module-level). A new typed transport would
   only be justified if a fact could not be rendered from an existing
   authoritative input — none qualifies (§3.5).

## 7. PR decomposition decision — ONE PR (frozen AFTER the audit)

**Decision: ONE STEP = ONE PR.** This document is both the step-level
and PR-level design/ledger (operator ONE-PR-ONE-DOC standard; no child
docs). Branch: `feat/generic-framework-step-01-proposer-hypothesis-space`
(created from post-Step-00 master only — §Status freeze preconditions).

Evidence against each child-PR justification criterion (all seven must
hold for a split; none does):

1. *Independent behavioral final effect*: the only candidate split is
   EXTRACTION (byte-identical renders) vs JOIN (render change). An
   extraction-only PR's behavioral effect ("YAML edits now reach the
   commit prompt") is real but is proven by the SAME contrast fixtures
   this PR ships; a JOIN-only PR would re-touch the same templates,
   goldens and tests a week later — shared blast surface, no
   independence.
2. *Master fully usable when merged*: both halves leave master usable —
   criterion neutral, does not force a split.
3. *Own TIDMAD parity evidence*: both halves cite the SAME baselines
   (PB-3/PB-4/PB-0/WF-3/CFG) — no independent parity boundary exists.
4. *Live production consumer*: the extraction's renderers reach
   production only through the same call sites the JOIN touches; a
   split risks exactly the §0.8 consumer-less shape for the
   task-background renderer if the JOIN PR slipped.
5. *Independent validation boundary*: one acceptance-pack family
   (§12) covers everything; the packs do not partition.
6. *No half-enabled sibling state*: an extraction-only merge leaves
   `template_vars["task_description"]` STILL consumer-less on master —
   the audited defect this step is assigned to fix — i.e. the split
   ships a half-enabled state by construction.
7. *Risk/review isolation*: the whole diff is one module + its
   templates + tests; measured inner loop is 3 s; review isolation
   gains nothing.

Commit-level separation (§14) provides the attribution the two-stage
rule wants: extraction commits are individually byte-parity-proven
before the single JOIN commit changes any rendered byte.

## 8. Stage A — TIDMAD extraction parity (exact Step-00 baseline IDs)

Criterion (roadmap §2 row 1 + 6-P matrix row A): rendered proposer
prompts EXACT string equality for the TIDMAD profile, all surfaces;
plus the boundary-capture invariant (labels/components) unchanged.

### 8.1 Baseline map (every claim names a landed Step-00 ID)

| Step-00 baseline (status at 71f6b31f) | What it pins | Stage-A use in Step 01 |
|---|---|---|
| **PB-3** (9 goldens: 3 stage system prompts × explore/exploit + 3 mode-invariant user prompts; + label-sequence pin) — landed, green | the PRODUCTION pipeline render through real `run()` under a pinned environment with a TEST-OWNED ForwardContract/description fixture | extraction commits S1-A/S1-B must keep all 9 byte-identical and the label sequence unchanged; regenerated ONCE in S1-C (JOIN) per §13 |
| **PB-4** (2 goldens: commit system constant + commit user render) — landed, green | the legacy commit surface | S1-A: golden BYTES unchanged; the system-side assert moves constant→render (§11.1) |
| **PB-0** (legacy proposer reasoning golden) — landed (REG), green | the legacy reasoning render incl. {TASK_BACKGROUND} substitution | untouched, stays green through every commit (unless OD-S1-2 approves the budget-literal cleanup, which would regenerate it with provenance) |
| **WF-3** proposer half (component-key-set golden `wf3_proposer_components_key_sets.json` + per-surface label asserts + `components is not None`) — landed, green | label=/components= crossing `generate`/`generate_text` at the proposer sites | "same kwargs reach LLMBridge": key sets and labels unchanged by extraction; JOIN renders into `system_prompt` (an EXISTING component key) so the key-set golden stays valid — any key-set change is a design failure, not a regeneration |
| **CFG-1** (resolved shipped task-config dict), **CFG-2** (2 rendered task strings) — landed, green | the shipped authority content Step 01 renders FROM | untouched (Step 01 never edits YAML/loader); they anchor the JOIN's "shipped description" claim |
| **CFG-3a/3b** (lit-review duplicate + semantics) — landed, green | the duplicate-description channel | untouched guard (N11) |

Dependency honesty: all rows exist and are green on the Step-00 BRANCH
head this design was audited at; none is on master yet. Per §Status,
no row is FINAL evidence until the Step-00 PR merges and this design
re-verifies them on master.

### 8.2 Parity mechanics per extraction commit

- Renderer + template conversion and the golden assert live in the
  SAME commit; the acceptance criterion is the UNMODIFIED golden file
  passing against the NEW render path (not a fresh capture).
- The legacy commit surface gains its render call at the :1385 call
  site in the same commit (seam WITH first consumer).
- A test-side render-vs-constant differential is added in S1-A: once
  placeholders exist, `render(commit_template, TIDMAD) ==
  pb4_legacy_commit_system.txt` AND `commit_template != golden`
  (proves the assert target moved for the right reason — the template
  alone is no longer the LLM-visible surface).
- The §11.1 re-targets land in the same commits as the extraction that
  invalidates their old layer — never a window where a property is
  unowned.

### 8.3 The JOIN (Step-00 §15.2 assigned A-work; commit S1-C)

Claim being closed: "CFG-2 pins the shipped string; PB-3 pins the
render with a test-owned description; the JOIN (proposer actually
reading the shipped description) is step 01's own A-work."

Design: a labeled task-background block containing the (already
transported) `inp.task_description` renders into the pipeline stage
SYSTEM prompts via the existing `template_vars` mechanism — consuming
the audited dead key at :1597 (WIRE, not REMOVE — §0.8; removal is
foreclosed because roadmap fixture 13.4-A requires description-derived
blocks in the proposer render). Placement recommendation (OD-S1-3):
all three stage base templates (comparison + causal today receive ZERO
task framing — the hypothesis-space-defining stages; proposing gains
the description beside its existing contract block). Forward-contract
rendering is NOT expanded to stages 1-2 in this step (records as a
deferred question — a second, separable render change with its own
prompt-budget implications).

Evidence chain for the A-claim: CFG-2 (shipped string) + the S1-C
JOIN test (the SHIPPED description — loaded via `load_task_config()`
from the repo config — appears verbatim in the captured production
pipeline render) + the §10 live-integration assert (workflow-driven).
Golden regeneration: §13 rule 2, exactly once.

## 9. Stage B — atomic contrast design (roadmap 13.4-A / 13.4-B)

One axis per fixture, NEVER both; both fixtures run the REAL
production pipeline path (the PB-3 machinery: real `run()`, canned
boundary bridge, pinned environment), proposer surfaces only.

### 9.1 Fixture 13.4-A — task-description TEXT only

- Input: the in-tree `_ALT_TD` string
  (`tests/unit/agent/test_planner_prompt_task_config.py:32`, "audio
  enhancement for speech synthesis: spectrogram → waveform") as
  `task_description`; the SHIPPED TIDMAD ForwardContract UNCHANGED.
- Asserts: (1) `_ALT_TD` appears in each stage system prompt's
  task-background block; (2) ZERO SQUID residue in the
  description-DERIVED blocks — `"SQUID"`, `"dark-matter"`,
  `"magnetometry"` absent from the task-background block (NOT from
  the whole prompt: contract prose legitimately still says
  "denoising classes" because the CONTRACT is TIDMAD's — axis
  isolation, roadmap §13.3(b) honesty rule); (3) contract-derived
  tokens byte-identical to the TIDMAD variant of the same render.
- Proves: the description channel flows and carries no hidden
  description-derived hardcode.

### 9.2 Fixture 13.4-B — declared ForwardContract only (PROSE rendering only)

- Input: the in-tree regressor-style contrast contract (the
  `test_task_config.py:267-292` non-SQUID-shapes precedent, extended
  to a full fixture with `num_classes=16`-class variant where the
  classifier-form token is exercised); `task_description` = SHIPPED
  TIDMAD string UNCHANGED.
- Asserts: (1) derived contract tokens track the declaration —
  declared input/output shape strings render; `256` absent from every
  contract-DERIVED token; the num_classes-derived classifier-form
  token shows the fixture's value; (2) loss-legality prose UNCHANGED
  (frozensets are not the varied axis); (3) the TIDMAD description
  renders unchanged in the task-background block.
- Proves: shapes/classes/task_type prose derives from the declaration;
  no shadow literal survives.
- Scope honesty (roadmap matrix B cell: "PROSE-rendering only"): this
  fixture proves PROMPT rendering tracks the declaration. It claims
  NOTHING about training/validation executing such a contract — that
  is steps 02/03.

### 9.3 Ladder note

No further rungs: the roadmap B cell for 6-P names exactly 13.4-A +
13.4-B. Loss-family variation is NOT a fixture axis (the frozensets
are production authorities, not per-task profiles yet — step 03);
authority-tracking is proven by mutation M-5 instead (§15).

## 10. Live integration checkpoint (Checkpoint C)

The consumer is the REAL production proposer path — no consumer-less
seam survives the PR:

1. **In-PR (unit tier)**: PB-3-machinery tests drive the REAL
   `MLModelProposalAgent.run()` (production pipeline dispatch, real
   stage loop, real template files, real renderers) — every extraction
   and the JOIN are exercised through the production code path, not
   test-side re-assembly.
2. **In-PR (workflow tier, pseudo)**: one bounded pseudo assertion
   that the WORKFLOW-injected shipped description reaches the captured
   proposer prompt — i.e. through `run_workflow`'s protocol + post-hoc
   injection (model_exploration.py:2284-2301), a RecordingLLMBridge
   capture containing the CFG-2-pinned string. Implemented as a
   minimal extension to an existing pseudo workflow test (pack 4;
   never CI) OR, if an existing dual-mode test already captures the
   proposer prompt (test_vocab_accumulation does), as an added assert
   there — inspect-first at implementation.
3. **Post-merge (chain evidence)**: the roadmap C cell asks for "a
   real chain iteration". Step 01 is a prompt/config extraction whose
   parity is fully deterministic — per roadmap §17 "Bounded real
   Gates … NOT required for prompt/config extractions". Proposed
   instantiation (operator confirms at §19 OD-S1-4): one bounded
   `--is_pseudo_llm` chain iteration (production entry
   `run_one_iteration.py`, StubLLMBridge executes the REAL renders)
   with the rendered proposing-stage system prompt dumped via the
   existing `debug_dump_proposing_prompt_path` hook and checked for
   the shipped description + derived contract tokens; log attached to
   the PR. No real-LLM Gate.

## 11. Test-disposition table

Inventory from the Area-C/E test audit (per-test-body reads, not
AST-scan classification); suite state at head `71f6b31f`: the whole
proposer/protocol/helper surface is GREEN (716 passed / 0 failed /
0 skipped in 5.5 s on the combined targeted run); no xfail/skip
markers anywhere in the proposer unit tree.

Legend — dispositions: **KEEP** (unchanged, still owns its property);
**HARD GATE** (Step-00 golden — must stay green UNMODIFIED through
extraction commits; §13 governs any regeneration); **RETARGET**
(same property, capture layer moves template→rendered; golden BYTES
unchanged where stated); **PROFILE-PARAMETERIZE** (value pin becomes a
profile-derived pin per roadmap §13.3(a)); **EXTEND** (new cases added
beside it). NOTHING IS DELETED in Step 01.

### 11.1 The break set (tests that pin the TEMPLATE literal and go red under byte-identical render extraction)

Audited fact: NO test anywhere asserts that `PROPOSAL_COMMIT_PROMPT`
reaches `bridge.generate` unmodified; the verbatim property is guarded
only by these four template-literal families. Template-layer absence
tests and rendered-TIDMAD equality tests prove different things
(roadmap §13.3) — the rows below never swap one for the other.

| Test | Current intent | Path | Disposition | Reason / replacement owner | Mutation proving the replacement owns the property |
|---|---|---|---|---|---|
| `test_contract_reassertion.py` (5 def / 15 collected; regex-extracts the `mathematical_definition` spec from the CONSTANT; pins 11 tokens + co-occurrence + ≥600-char floor + hard-constraint block tokens + `"forward contract is fixed"` absence) | Golden-Paragraph drift guard on the commit TEMPLATE | legacy | **RETARGET + PROFILE-PARAMETERIZE (the roadmap-mandated semantic change, stated here per matrix row 6-P column C)**: the pins move from the module constant to the RENDERED commit system prompt under (i) the TIDMAD profile — same tokens must appear, now derived (e.g. `[B, 256, T] float32` from ForwardContract, loss families from the frozensets) — and (ii) a contrast profile — the DERIVED tokens must track the profile (e.g. num_classes=16 ⇒ `256 denoising bins` absent, `16 …` present). The structural pins (Golden-Paragraph header, no-concrete-dims clause, length floor, co-occurrence-of-derived-tokens) stay, applied to the render. The absence pin (`forward contract is fixed`) stays on the render | The template no longer carries the tokens literally — asserting the constant would pin nothing; the PROPERTY (the agent is never left without the I/O contract and the fixed-dimension clause) lives on what the LLM sees, which is the render | M-4 (§15): reintroduce a hardcoded `256` in the commit template shadowing the placeholder → contrast-profile pin goes red; M-2: perturb one ForwardContract field → TIDMAD render pin goes red |
| `test_step00_prompt_goldens.py::TestPB4LegacyCommit::test_commit_system_constant` (golden `pb4_legacy_commit_system.txt`) | Step-00 baseline of the commit SYSTEM surface — captured as the raw constant because today constant == render (zero substitution) | legacy | **RETARGET, GOLDEN BYTES UNCHANGED (HARD GATE on content)**: the assert target becomes the RENDERED commit system prompt under the shipped TIDMAD profile; the golden FILE is byte-identical (that is the Stage-A parity claim itself). The sibling `test_commit_user_render` already rendered-layer — KEEP | The golden IS the parity oracle; keeping it aimed at the constant would force the constant to stay literal forever, defeating the step; re-aiming preserves every byte as the acceptance criterion | M-2: change one rendered token (e.g. ForwardContract.output_shape) → red with a unified diff naming the golden; M-1: delete the placeholder consumer (render call) → red (constant ≠ golden once placeholders exist unrendered) |
| `test_prompt_ceiling_policy.py` — 2 of 7 (`test_vram_limit_requirement_retained` :65-68, `test_capacity_constraints_require_justification_language` :72-81 — presence pins on the CONSTANT via `_all_template_texts()`) | VRAM-mandate language never silently dropped | legacy + templates | **KEEP with capture-layer widening**: these two sentences are proposer-owned FRAMEWORK prose (not task facts — §5 map) and STAY LITERAL in the template, so the pins stay green as-is; if the implementation moves any pinned sentence into a rendered block (not planned), the pin follows to the render in the same commit. The 3 absence pins (mandate regexes, `<10 GB VRAM`) and the rendered-layer twin KEEP unchanged — they are anti-hardcode template pins (roadmap §13.3(b)) | The pinned sentences are budget-DISCIPLINE prose deferring to [HARDWARE CONTEXT], not extractable task facts | n/a (no move planned); if moved: same-commit pin move, M-4 guards reintroduction |
| `tests/unit/agent/test_output_contract_end_to_end.py::test_json_skeletons_request_output_type` (`'"output_type"' in PROPOSAL_COMMIT_PROMPT` + in raw proposing_stage.md) | Both JSON skeletons REQUEST output_type (V21 PR A reachability) | both | **KEEP, layer-verified**: the `"output_type"` key is JSON-skeleton STRUCTURE (proposer-owned framework content), planned to stay literal in both templates; pin stays green. If the skeleton line gains placeholders around it, the token itself remains literal | Skeleton structure is not a task fact; PR A's reachability intent is untouched | n/a; the PR-A allow-list source-count pin (`:287-294`) independently guards the parse side |

### 11.2 Step-00 baselines consumed as HARD GATES (green UNMODIFIED through extraction; §13 governs the single JOIN regeneration)

| Baseline | Test | Role in Step 01 |
|---|---|---|
| PB-3 (9 prompt goldens + label-sequence pin) | `test_step00_prompt_goldens.py::TestPB3PipelineProposer` — PRODUCTION pipeline through real `run()` + `BoundaryRecorderBridge`, fully pinned environment, test-owned ForwardContract fixture; user goldens pinned mode-invariant | Stage-A oracle for every pipeline-surface extraction commit: byte-identical before/after. Regenerated ONCE, in the JOIN commit only, per §13 |
| PB-4 (2 goldens) | as §11.1 row 2 | Stage-A oracle for the commit-prompt extraction (content unchanged; capture layer moves) |
| PB-0 (legacy proposer reasoning golden) | `tests/unit/agent/ml_model_proposal_agent` golden family (Step-00 REG) | KEEP byte-identical — legacy reasoning system prompt already renders {TASK_BACKGROUND}; Step 01 does not change its TIDMAD bytes |
| WF-3 proposer half (`wf3_proposer_components_key_sets.json` + per-surface label asserts + `components is not None` at every stage) | `TestWF3ComponentsInventory` | "Same kwargs reach LLMBridge" A-surface: the component KEY SETS and labels must be unchanged by extraction; the JOIN commit updates the key-set golden IFF a new component key is introduced (recorded §13) |
| CFG-1/CFG-2 (resolved dict + 2 rendered-string goldens) | `tests/unit/workflows/test_step00_task_config_baselines.py` | Upstream authority pins — must stay green untouched (Step 01 never edits the shipped YAML or loader) |
| CFG-3a/3b (lit-review duplicate byte-equality + semantics) | same file | Untouched guard that Step 01 does not smuggle in the step-04 duplicate collapse |

### 11.3 KEEP families (behavior contracts unaffected by extraction — spot-listed, all verified green)

- Rendered-layer task-config tests: `test_proposer_task_config.py`
  (17) — the MODEL for this step's new render tests (absence pins:
  custom contract ⇒ zero `TIDMAD`/`SQUID`/`[B, 256, T]` residue in the
  legacy reasoning render; `{forward_contract}` consumed in proposing
  render). **EXTEND** with commit-prompt + pipeline equivalents.
- `test_planner_prompt_task_config.py` — PLANNER surface: absence pins
  stay template-scoped (roadmap §13.3(b)); NOT touched by Step 01
  (planner is step 07a).
- Pipeline behavior: `test_pipeline_runner.py` (63; incl.
  `TestProposerGenericity` anti-hardcode on candidate prompts,
  retry/DI/selection), `test_pipeline_mode_user_prompt.py`,
  `test_boldness_enforcement.py`, `test_causal_stage_validation.py`,
  `test_audit_components.py` — KEEP; they pin retry/order/block
  properties Step 01 must not alter.
- Parse/transport: `test_proposal_schemas.py`, `test_phase_b_schemas
  .py`, `test_output_contract_end_to_end.py` (allow-list source-count
  + schema behavior), `test_pr_e_stage_contract_pins.py` (exact key
  sets), `test_pr_e_candidate_id_transport.py` (16, LEGACY-path mint/
  transport/inertness) — KEEP; Step 01 makes zero schema/transport
  changes, so all stay green by construction (Checkpoint D evidence).
- Protocol mappings: the 3 proposer-edge protocol files (fan-in
  full-context, lit-review channels, propose→impl incl.
  `TestOutputContractTransport`) — KEEP.
- Prompt-block renderers: `test_known_constraints_block.py`,
  `test_hardware_context_block.py`, `test_recent_gate_exhaustions.py`,
  `test_health_evidence_*` , `test_loss_awareness.py`,
  `test_agent_cards.py`, `test_prompt_context_surfacing.py`,
  `test_prior_stage_truncation.py`, `test_description_truncation.py`,
  `test_rejection_acknowledgement_prompt.py`, registry filters,
  `test_preflight_advisory.py`, `test_citation_discipline.py`,
  `test_baseline_config_validators.py`, `test_model_branch_b.py`,
  `test_proposal_helpers.py`, `test_health_prompt_parity.py` (full-
  string legacy golden `reasoning_prompt_structured_evidence.txt` —
  KEEP byte-identical) — all KEEP.
- Integration (never CI): `test_ml_model_proposal_agent.py::test_
  proposal_pipeline_dual_mode` (pipeline, RecordingLLMBridge),
  `test_interp_to_propose.py` dual-mode pair (pipeline, boundary
  capture), `test_pr_e_funnel_gate_pseudo.py` (NOTE: exercises the
  LEGACY proposer — `run_workflow` without `llm_config` ⇒
  `propose=None`; an in-repo consumer of the legacy path, evidence
  for §3.2), persistence/vocab/vram/ordering pseudo tests — KEEP;
  pack-4 members run manually green-before-cite.

### 11.4 Test-migration principle (frozen for this step)

1. Step-00 external-behavior goldens are THE parity oracle; a golden
   is regenerated only per §13 (once, the JOIN commit).
2. No test is kept merely to inspect old source structure: the four
   §11.1 template-literal families are re-targeted to the surface the
   LLM actually receives, never weakened — every pinned token/property
   has a named surviving owner in the RETARGET column.
3. No test is weakened because extraction changed implementation:
   re-target beats delete; DELETE is used zero times in this step.
4. Mutation evidence (§15) proves each replacement owns its property
   before the old capture layer is abandoned.
5. Template anti-hardcode/absence pins remain template-scoped;
   rendered-TIDMAD parity pins remain render-scoped (roadmap §13.3) —
   never interchanged.
6. The full unit suite is the terminal regression gate (pack 5), not
   the inner loop.

## 12. Acceptance packs and runtime budget

All numbers MEASURED at head `71f6b31f` on the lilab box (24 cores,
RTX 5090; unit conftest mocks CUDA discovery so collection is fast;
pytest startup overhead ~1 s/invocation). Every targeted pack is GREEN
at this head. No new test-marker/sharding framework is introduced —
packs are pytest path lists.

| Pack | Contents | Measured | Budget |
|---|---|---|---|
| 1. FAST INNER LOOP | `tests/unit/agent/ml_model_proposal_agent/` (521) + `tests/unit/workflows/test_step00_task_config_baselines.py` (5) + `tests/unit/agent/llm_bridge/test_step00_prompt_goldens.py` + the 3 proposer-edge protocol files (`test_ml_literature_review_to_ml_model_propose.py`, `test_ml_model_propose_to_ml_model_impl.py`, `test_ml_result_interp_to_ml_model_propose.py`) + `tests/unit/agent/schemas/` (295) — 861 tests | **3.0 s wall** (single invocation) | ≤ 2 min (measured 3 s — two orders of margin) |
| 2. STAGE-A PARITY | the Step-00 proposer/config baseline files (`ml_model_proposal_agent/test_step00_prompt_goldens.py`, `llm_bridge/test_step00_prompt_goldens.py`, `workflows/test_step00_task_config_baselines.py` — 16 tests, 1.9 s) + `test_contract_reassertion.py` + `test_proposer_task_config.py` + the full proposer suite (already inside pack 1) | ≈ pack 1 + 2 s | ≤ 2 min |
| 3. STAGE-B CONTRAST | the NEW 13.4-A/13.4-B proposer contrast fixtures (this PR's own tests — land inside `tests/unit/agent/ml_model_proposal_agent/`) | expected O(seconds) (same fixture machinery as PB-3) | ≤ 1 min |
| 4. LIVE INTEGRATION | bounded production-path proposer runs, NO live API: `tests/integration/nodes/test_ml_model_proposal_agent.py::test_proposal_pipeline_dual_mode` (pseudo mode) + `tests/integration/workflows/test_pr_e_persistence_layout_pseudo.py::TestNodePersistence::test_proposer_persists_proposal_json` + `tests/integration/workflows/test_vocab_accumulation.py::test_vocab_discoveries_appear_in_proposal_prompt` (collect-verified present; never in CI per repo policy — run manually with fresh green logs attached to the claim) | bounded, minutes | manual, green-before-cite |
| 5. FINAL FULL SUITE | full `pytest tests/unit/ -m "not real_run"` + ruff check + `ruff format --check` + pyright strict + CI on the exact final head ONLY (~8.3k tests, ~440 s CI precedent) | once, terminal | terminal gate only |

Shared-helper blast radius (measured by import graph):
- `tests/helpers/recording_llm_bridge.py` → 13 direct importer files
  incl. `tests/conftest.py` (`make_bridge_factory`) and 7 integration
  workflows; touching it requires the pin suite
  (`tests/helpers/test_recording_fakes.py`), both tune step00 unit
  files, and the pseudo-mode integration families. **Step 01 does not
  plan to touch it.**
- `tests/helpers/llm_boundary_recorder.py` → exactly the 6
  `test_step00_prompt_goldens.py` files (all unit, seconds).
- `tests/helpers/golden.py` → 14 step00 files +
  `test_scoring_reference_default.py` (all unit, fast). Step 01 only
  ADDS consumers of these helpers; it does not modify them — if a
  modification becomes necessary, that is a blast-radius trigger to
  run the wider helper-importer set (recorded rule).
- Whole `tests/unit/workflows/` (219 tests, 14 s) joins the loop only
  for commits touching `workflows/task_config.py` consumers or the
  workflow injection sites.

## 13. Baseline-golden update policy

Inherits Step-00 §17 verbatim (tests never regenerate; no accept-all;
regeneration only in the same commit as the intentional change, with
message stating the change, the affected surfaces, and why the old
golden is no longer authoritative). Step-01-specific rules:

1. **Step-00 goldens NEVER regenerate silently.** Extraction commits
   (everything except the JOIN) leave every PB-0/PB-3/PB-4/WF-3/CFG
   golden FILE byte-identical — a red golden in those commits is
   production drift by definition (fix the code, never the golden).
2. **Exactly ONE planned regeneration event**: the JOIN commit
   (§14, commit S1-C) changes rendered pipeline prompts by inserting
   the task-description block. In that commit ONLY: the affected PB-3
   goldens (and the WF-3 component-key-set golden IFF a new component
   key is added) are regenerated, with the commit message recording
   (a) the intended behavior change (production pipeline now renders
   the shipped task description), (b) affected surfaces (the named
   golden files + the roadmap 6-P A-surface), (c) why the old goldens
   are no longer authoritative (they pinned the pre-JOIN render, whose
   absence of the description was the audited defect this step
   exists to fix). A before/after unified diff of each regenerated
   golden is attached to the PR.
3. **PB-4 capture-layer move is NOT a regeneration**: the golden bytes
   are unchanged; only the assert target moves from the constant to
   the render (§11.1). The commit message states this explicitly.
4. **CFG-1/2/3a/3b are untouchable in this PR** — Step 01 never edits
   `configs/task_config.yaml`, `configs/lit_review_config.yaml`, or
   the loader; any red there is drift.
5. New Step-01 goldens (contrast-profile renders, commit-prompt
   render fixtures) follow the Step-00 conventions: captured in
   test-only commits with provenance messages; `assert_golden`
   helpers; text-only artifacts; no production source text embedded
   (test-owned frozen fixture classes only).

## 14. Implementation phases (per-commit 8-section checklists)

**NOT AUTHORIZED YET** — implementation starts only after (a) the
§Status freeze preconditions are met (Step-00 merged; this design
re-synced onto master) and (b) operator approval of this design incl.
the §19 decisions. One PR, branch
`feat/generic-framework-step-01-proposer-hypothesis-space`, semantic
commits below (autonomous per the §18.1 standing rules). All boxes
`[ ]` — NOTHING is implemented. Checklists are specific enough to
track but deliberately do not invent code-level detail ahead of the
per-commit inspect-first step; if inspection reveals ambiguity or
larger scope, STOP AND ASK.

### 14.1 Commit S1-A — legacy commit-prompt extraction + renderers (byte-parity)

**Goal.** The commit prompt's task facts (shapes/classes/loss
legality) derive from ForwardContract + the loss frozensets; TIDMAD
render byte-identical; the two new proposer-local renderers exist WITH
their first consumer.

**Scope.** `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`
(PROPOSAL_COMMIT_PROMPT → template + render at the :1385 call site;
new renderer helpers, module-local); tests:
`test_step00_prompt_goldens.py` PB-4 system assert re-target,
`test_contract_reassertion.py` re-target (§11.1),
new renderer unit tests. NON-goals: pipeline templates (S1-B), any
rendered-byte change, schemas, protocols, other nodes.

**Implementation plan.**
- [ ] Inspect the commit prompt + call site + `render_forward_contract`
      + frozensets; fix the exact placeholder set (inspect-first).
- [ ] Loss-legality renderer (frozensets → legality prose tokens) +
      contract-prose renderer (ForwardContract → shape/class tokens),
      typed, docstringed, module-local.
- [ ] Template conversion + render at :1385 (first consumer, same
      commit).
- [ ] PB-4 re-target (golden bytes untouched) + render-vs-constant
      differential (§8.2).
- [ ] `test_contract_reassertion.py` re-target to the render, TIDMAD
      variant (§11.1 row 1; contrast variant lands in S1-D).
- [ ] Renderer unit tests incl. empty-input behavior pins.

**Validation plan.** Pack 1 + pack 2 (§12); ruff/format on touched
files; mutations M-2 partial (commit-prompt token) executed and
recorded.

**Acceptance criteria (observable).** `pb4_legacy_commit_system.txt`
passes UNMODIFIED against the render; `git diff` shows zero template
literal for the extracted tokens (grep evidence recorded); the
differential test proves constant ≠ golden while render == golden;
contract-reassertion re-target red under mutation M-2, green
otherwise.

**Failure/edge cases.** Empty ForwardContract (legacy CLI main(),
test fixtures) → render degrades exactly as `_render_task_background`
does today (regime-A, pinned); regex-extraction in the re-targeted
reassertion test must tolerate the placeholder line shape.

**Verification commands and evidence.** (recorded after execution;
never claim an unrun test passed)

**Commit boundary.** Test-and-production change for the LEGACY commit
surface only; no pipeline template touched; goldens byte-identical.

### 14.2 Commit S1-B — pipeline template extraction (byte-parity)

**Goal.** proposing_stage.md's hardcoded fact lines (:41, :70-71,
:74, :85-92, :168 loss/shape tokens) derive via template_vars from
the same renderers; TIDMAD render byte-identical (all 9 PB-3 goldens
unmodified).

**Scope.** `agent/prompt_templates/proposal/proposing_stage.md` (+
`_run_pipeline` template_vars additions); tests: new rendered-layer
pins mirroring `test_proposer_task_config.py`'s shape. NON-goals: the
task-description placeholder (S1-C); comparison/causal templates
(no extractable fact rows — §4); wording changes; the
double-substitution quirk (kept byte-identical).

**Implementation plan.**
- [ ] Inspect proposing_stage.md line-by-line against the §4 fact
      rows; fix the placeholder set; verify no prose mention of a new
      placeholder name exists elsewhere in the template (the :177/:235
      double-render hazard — choose collision-free names).
- [ ] template_vars entries from the S1-A renderers.
- [ ] Byte-parity check of all 9 PB-3 goldens.
- [ ] Rendered-layer pins: TIDMAD tokens present; template file no
      longer contains the extracted literals (template-layer absence
      pin, new).

**Validation plan.** Pack 1 + 2; mutation M-5 (one-sided template
edit) executed and recorded.

**Acceptance criteria.** All 9 PB-3 goldens + label-sequence pin +
WF-3 key-set golden pass UNMODIFIED; grep shows the extracted
literals absent from the template; new absence pin red if a literal
is reintroduced (M-4 pre-check).

**Failure/edge cases.** Placeholder-name collision with prose (global
str.replace) — checked by inspection + a collision guard assert in
the new tests; a missing template_vars key ships the literal
placeholder to the LLM (silent no-op) — covered by the rendered pins.

**Verification commands and evidence.** (after execution)

**Commit boundary.** proposing_stage.md + template_vars + tests;
rendered TIDMAD bytes unchanged.

### 14.3 Commit S1-C — the JOIN (single deliberate render change)

**Goal.** The production pipeline renders the shipped task
description (task-background block in stage system prompts),
consuming the dead template_vars key; §13 rule-2 golden regeneration.

**Scope.** Stage base templates (per OD-S1-3 placement) +
`_run_pipeline` (no new key needed — :1597 exists); PB-3 golden
regeneration (provenance per §13); JOIN tests (§8.3, §10.2);
WF-3 key-set golden verified UNCHANGED. NON-goals: forward-contract
expansion to stages 1-2; wording beyond the minimal labeled block;
legacy surfaces (already render the description).

**Implementation plan.**
- [ ] Inspect stage templates + the WF-3 component audit to confirm
      the block lands inside the `system_prompt` component.
- [ ] Add the labeled task-background block + placeholder per
      OD-S1-3.
- [ ] Regenerate affected PB-3 goldens in THIS commit with the §13
      rule-2 message + attached diffs.
- [ ] JOIN test: shipped description (via `load_task_config()`)
      appears verbatim in the captured production render.
- [ ] Workflow-tier pseudo assert (§10.2) — inspect-first whether to
      extend an existing dual-mode test or add a bounded one.

**Validation plan.** Pack 1 + 2 + the touched integration test (pack
4, manual, log recorded); mutations M-1 and M-6 executed and
recorded.

**Acceptance criteria.** The regenerated goldens contain the shipped
description exactly once per stage system prompt; WF-3 key sets
unchanged; M-1 (remove the placeholder) turns the JOIN test red;
M-6 (drop the workflow post-hoc injection) turns the workflow-tier
assert red.

**Failure/edge cases.** Empty description (node CLI main()) → block
collapses to "" (legacy precedent), pinned by a test; prompt-size
growth is bounded (description is ~4 lines; `test_prompt_ceiling`
budget tests must stay green).

**Verification commands and evidence.** (after execution)

**Commit boundary.** The ONLY commit that changes rendered TIDMAD
bytes; everything needed to review that change (templates, goldens,
diffs, tests) is inside it.

### 14.4 Commit S1-D — Stage-B contrast fixtures + mutation battery closeout

**Goal.** 13.4-A and 13.4-B land (§9); the §15 battery is fully
executed and recorded; contract-reassertion contrast variant lands.

**Scope.** New tests + fixtures only (test-only commit). NON-goals:
any production diff.

**Implementation plan.**
- [ ] 13.4-A fixture + asserts (§9.1).
- [ ] 13.4-B fixture + asserts (§9.2), incl. the num_classes contrast
      variant of the re-targeted contract-reassertion pins.
- [ ] Execute remaining mutations (M-3, M-4, M-7) with
      mutation-proof hygiene (cache clear, count==1, baseline re-run);
      record the dossier in this document.

**Validation plan.** Packs 1-3; full battery dossier.

**Acceptance criteria.** Each fixture varies exactly one axis
(reviewed against §9's atomicity notes); every §15 mutation has a
recorded RED and a restored GREEN; zero surviving behavior-changing
mutations.

**Failure/edge cases.** A contrast fixture accidentally varying two
axes (e.g. alt description that also implies different shapes) — the
§9 fixtures pin the OTHER axis explicitly to the TIDMAD value.

**Verification commands and evidence.** (after execution)

**Commit boundary.** Test-only.

### 14.5 Commit S1-E (OPTIONAL — exists only if OD-S1-2 approves) — stale budget-literal cleanup

**Goal.** Delete/re-point the two stale budget numerals ("~100M"
S1:284; "10 GB" causal_reasoning_stage.md:146) to the [HARDWARE
CONTEXT] deferral pattern (roadmap §14 resolved row).
**Scope.** Two prose lines + PB-0/PB-3 golden regeneration
(§13-compliant) + the 2 pinned `test_prompt_ceiling_policy` sentences
if touched. **Implementation plan.** [ ] per inspection.
**Validation.** Packs 1-2. **Acceptance.** No numeral budget literal
in proposer surfaces (extending the existing `<10 GB VRAM` absence
pin); goldens regenerated with provenance. **Failure cases.** none
beyond golden hygiene. **Evidence.** (after execution).
**Boundary.** Isolated, clearly-labeled, skippable.

### 14.6 Commit S1-F — docs closeout + PR readiness

**Goal.** This ledger fully reconciled ([x] with evidence); node doc
sync (`nodes/ml_model_proposal_agent/ml_model_proposal_agent.md` —
prompt-surface documentation current per the pre-merge doc-sync rule);
final full-suite + static gates at the executable head (pack 5),
clean tree; PR READY FOR OPERATOR REVIEW (never merge).
**Scope.** docs + any final test bookkeeping. **Plan.** [ ] ledger
reconciliation; [ ] node .md quote-verified against merged-state
flags/defaults; [ ] pack-5 run from a clean tree, verdict from the
log. **Acceptance.** CI green on the exact head; every §14 box [x]
with evidence or explicitly deferred with reason; §16 checkpoint
table filled. **Boundary.** docs-only.

## 15. Validation and mutation plan

Executed as recorded evidence during implementation (mutation applied
locally, red observed, reverted, green re-verified; mutation-proof
hygiene rules apply). Battery (directive-mandated cases instantiated):

| # | Mutation | Expected RED |
|---|---|---|
| M-1 | delete a NEW placeholder consumer: remove `{task_description}` from one stage template (post-JOIN) | JOIN test + the regenerated PB-3 golden for that stage |
| M-2 | change one TIDMAD rendered token: perturb one ForwardContract-derived token in the renderer (e.g. drop the dtype suffix) | PB-4-retargeted golden (S1-A) / PB-3 goldens (S1-B) with unified diff naming the surface |
| M-3 | parser/transport-loss analog: make the loss-legality renderer read an empty iterable (authority disconnected pre-render) | re-targeted contract-reassertion legality pins + rendered legality golden |
| M-4 | reintroduce a hardcoded task fact: paste a literal `256`-token line into the template beside the placeholder | 13.4-B contrast fixture (literal survives the contrast profile) + template-layer absence pin (S1-B) |
| M-5 | one-sided template/profile update: edit a derived-block line in the template without regenerating goldens | PB-3/PB-4 parity golden |
| M-6 | transport loss at the workflow boundary: comment out `propose_input.task_description = …` (model_exploration.py:2290) | workflow-tier JOIN assert (§10.2) |
| M-7 | alternate-task SQUID-residue check: run 13.4-A and grep the description-derived block for SQUID tokens | 13.4-A itself (this is its steady-state assertion, executed as a mutation-class check once with a deliberately SQUID-contaminated renderer to prove the assert can fire) |

Negative controls: (NC-1) changing a `label=` string reds WF-3 label
asserts, NOT the prompt goldens (separation stays real); (NC-2) an
unrelated template_vars value change (e.g. minimum_boldness fixture
value) does not red the contract goldens; (NC-3) the extraction
commits re-run PB-3/PB-4 twice with byte-identical verdicts.

## 16. Checkpoints instantiated (roadmap §17)

| Checkpoint | Instantiation | Status |
|---|---|---|
| 0 BASELINE AVAILABLE | PB-0/PB-3/PB-4, WF-3, CFG-1/2/3a/3b landed and green — TRUE on the Step-00 branch head; blocked on merge for master (§Status) | PENDING MERGE |
| A EXTRACTION PARITY | §8: every extraction commit leaves all named goldens byte-identical; JOIN is the sole §13-governed regeneration; boundary kwargs (labels/components) unchanged | design |
| B GENERIC CONTRAST | §9: exactly the two roadmap-declared rungs 13.4-A + 13.4-B, one axis each | design |
| C LIVE INTEGRATION | §10: real production pipeline path in-PR (unit + pseudo workflow tier) + the bounded pseudo chain iteration (OD-S1-4); the :1597 seam is WIRED — no consumer-less seam survives | design |
| D REGRESSION | §12 pack 5 at the final head from a clean tree + §15 battery dossier + CI green on the exact head | design |
| E ROADMAP SYNC | roadmap §15.1 row 6-P updated in the same PR or an immediately-merged docs follow-up BEFORE the step-02 PR opens; folder README row + this doc's Status updated | design |

## 17. Failure cases and diagnostics

1. **A Step-00 golden red during an extraction commit** → production
   drift (the render is not byte-equal): fix the renderer/template,
   NEVER the golden. Diff helper names the surface.
2. **A Step-00 golden red during S1-C** → expected for exactly the
   regenerated set; any OTHER golden red = scope leak, stop.
3. **WF-3 component-key-set diff** → the JOIN leaked a new component
   key or a label changed: design violation (§8.1 WF-3 row), fix the
   code.
4. **Contrast fixture red with TIDMAD tokens present** → a shadow
   literal survived (M-4 shape): grep the template for the token,
   remove, re-run.
5. **Placeholder text visible in a rendered golden** (`{...}` bytes) →
   a template_vars key went missing (silent no-op hazard §3.4):
   the rendered pins catch it; fix the vars dict.
6. **`test_prompt_ceiling` budget red after the JOIN** → prompt
   growth exceeded the stage budget: shrink the block label, not the
   budget test.
7. **Known-quirk register (never blessed, §4 last row)**: registry
   double-substitution; proposing-stage missing `mindset`; dead
   `ProposalInput.constraints`; `[output_shape]` pseudo-placeholder in
   the shipped YAML; dead `_MAX_REASONING_RETRIES`; legacy commit call
   passes no `components=`; per-stage LLM routing kwargs absorbed and
   unused; silent legacy fallback on a propose-less llm_config
   (Area-A silent-drop list, 18 entries, kept in the audit record).
   Step 01 changes NONE of them; each is routed: prompt-mechanics
   quirks → step 04; config/binding quirks → steps 02/10/12.

## 18. Standing rules, risks, limitations, deferred questions

### 18.1 Standing implementation rules (Step-00 §18 precedent, carried forward)

- Semantic commits are AUTONOMOUS once implementation is authorized;
  STOP only for: material design/scope deviation; validation exceeding
  the approved envelope; an unresolved operator policy question; PR
  READY FOR OPERATOR REVIEW; merge approval (never merge).
- Per commit: inspect source before editing → update this live ledger
  continuously → inspect diff + staged list before committing → record
  tests/decisions/deviations here → commit autonomously.
- Minimum-sufficient test cadence: targeted new tests + directly
  affected suites + mutation checks + ruff/format on touched files per
  commit; the FULL unit suite + ruff + `ruff format --check` + pyright
  strict + CI ONCE at the final executable head, from a clean tree,
  verdict from the log file (never a wrapper exit code).
- No real-training Gates in this PR (prompt/config extraction; roadmap
  §17 exemption). If one becomes necessary — material deviation, stop.
- Acceptance criteria are observable conditions; "tests pass" alone is
  never a criterion; a boundary claim's evidence is its recorded
  mutation red.
- All Python through `.venv/bin/python`. English only.

### 18.2 Risks and limitations

1. **Golden regeneration concentration risk**: S1-C regenerates up to
   9 PB-3 goldens at once — mitigated by §13 rule 2 (attached diffs,
   one commit, one reason) and by S1-A/S1-B proving parity FIRST so
   the JOIN diff contains ONLY the description block.
2. **Placeholder/prose collision** (global `str.replace`): the
   :177/:235 double-render precedent shows prose mentions get
   expanded — new placeholder names are collision-checked (S1-B plan).
3. **Derivation-creep risk**: renderers could quietly grow semantic
   rules (e.g. parsing shape strings). Guarded by §6.2 rule 1 and
   review trigger: any conditional logic beyond verbatim-field
   insertion + membership listing is a scope question.
4. **Step-00 dependency risk**: if the Step-00 PR changes under review
   (goldens renamed/moved), §8.1's map must be re-verified at the
   freeze re-sync — recorded as the §Status precondition.
5. **Legacy-surface divergence**: after Step 01 the legacy and
   pipeline paths still differ (commit prompt has no hardware block;
   known-constraints only in pipeline; description in both). Step 01
   narrows only the fact-derivation gap; the structural asymmetries
   are recorded, owned by steps 04/10.
6. **Prompt-content change risk (JOIN)**: adding the description to
   stages 1-2 changes what the LLM attends to; scientifically this is
   the STEP'S PURPOSE (the hypothesis space should know the task),
   but any behavioral drift in real campaigns is attributable to the
   single JOIN commit.

### 18.3 Deferred questions (recorded, not decided here)

| Q | Content | Suggested owner |
|---|---|---|
| DQ-1 | Persona/task-domain prose ("specialising in … signal denoising") — needs a declared task block; no authority exists | step 04 (§13 remainder) with the cross-node persona sweep |
| DQ-2 | Forward-contract rendering into stages 1-2 (today stage-3 only) | revisit at step 04 or on evidence from campaign logs |
| DQ-3 | Two-output-form catalogue prose as a §5 declaration | step 03 convergence candidate (§6.2 rule 2) |
| DQ-4 | The 6 other-node loss-legality prose sites (planner ×4 incl. the model-name-keyed rule, reflector, check_config_format wrapper) | steps 07a/04 — recorded here so the count is not lost |
| DQ-5 | Legacy-mode structural gaps (no known-constraints block, no components=, no hardware block on commit call) | step 04/10 |
| DQ-6 | `[output_shape]` pseudo-placeholder in shipped YAML `output_head_note` (rendered verbatim to the LLM); fixing it breaks CFG-2 → needs its own §13-compliant regeneration | operator config edit post-Step-01, or step 02 |
| DQ-7 | genericity_contract.md Seam-3 section update (the roadmap is the seam authority now; the contract doc still says "update this section first") | with this PR's docs commit or D11 |

## 19. Operator decisions required

| ID | Question | Options | Recommendation |
|---|---|---|---|
| OD-S1-1 | **Forbidden-pattern lists**: the frozen roadmap's step-1 line names them, but the source audit shows the surface is validator-owned end-to-end (`forbidden_pattern_skill.py`; consumers `ml_code_validator_agent.py:51,:534`; ZERO proposer prose; the proposer's [DISALLOWED PATTERNS] block already renders from `ARCHITECTURAL_PATTERNS` — a live, correct seam) | (a) DEFER to 6-M step 04 with the validator surfaces (roadmap line recorded as pre-audit assumption); (b) extract the skill's list to config now with the validator as consumer (crosses into 6-M scope) | **(a) DEFER** — extracting a validator-consumed list is 6-M work by the roadmap's own 6-P/6-M split; doing it here would broaden 6-P exactly the way the directive forbids |
| OD-S1-2 | **Stale budget literals** ("~100M" PROPOSAL_REASONING_PROMPT:284; "10 GB" causal_reasoning_stage.md:146): roadmap §14 already RESOLVED the semantics (derive from [HARDWARE CONTEXT]; delete stale literals) but proposer templates have NO later owner (step 04's prompt scope excludes proposer surfaces) | (a) include optional commit S1-E (isolated, golden-regenerating, clearly labeled); (b) defer and accept an ownership gap | **(a) INCLUDE S1-E** — otherwise the two literals become permanently unowned; the commit is isolated and skippable |
| OD-S1-3 | **JOIN placement**: which stage system prompts render the task-background block | (a) all three stages (comparison/causal currently task-blind — they choose the architecture family); (b) proposing stage only (minimal byte change) | **(a) all three** — the step's final effect is about the HYPOTHESIS SPACE, which is formed in stages 1-2; (b) would satisfy the letter of the JOIN while leaving the deciding stages task-blind |
| OD-S1-4 | **Checkpoint-C chain evidence form** (roadmap C cell says "a real chain iteration"; §17 exempts prompt extractions from real Gates) | (a) bounded `--is_pseudo_llm` production-entry iteration with prompt dump, log attached (no API cost); (b) one real-LLM bounded iteration; (c) unit+pseudo-workflow evidence only | **(a)** — exercises the production entry + real renders at zero API cost; (b) adds LLM nondeterminism and cost without adding parity evidence |
| OD-S1-5 | **Design freeze** after Step-00 merge + re-sync: confirm the §8.1 baseline map against master and authorize implementation | — | freeze only after the §Status preconditions are all TRUE |

## 20. Governance persistence (for later propagation)

Recorded here because shared files (`docs/design/generic_framework_upgrade/README.md`,
roadmap §15.1) must NOT be modified while the Step-00 branch is still
moving:

- **Step-design kickoff protocol (canonical, used by this design;
  propagate to the folder README after Step 00 merges)**: frozen
  roadmap review → prerequisite design/evidence review → preliminary
  PR-decomposition hypothesis (private, provisional) → focused full
  codebase audit for the step → source-grounded final one-PR vs
  multi-PR decision → parent/child detailed design → adversarial
  review → operator review. PR decomposition is never frozen before
  the source audit.
- **Parent/child design-tree convention (operator standard, binding)**:
  ONE PR = ONE DOC. A step comprising several PRs gets a PARENT doc
  (final effect, aggregate compatibility contract, child dependency
  DAG, aggregate checkpoints, step-level completion, child status)
  plus `step_01_proposer_hypothesis_space/pr_01a_<functional-unit>.md`
  children, each owning one independently mergeable behavioral
  outcome. If one PR suffices, the parent doc IS the PR doc. Never
  split by file count, LOC, prompt count or context length. No child
  docs for semantic commits inside one coherent PR.
- **Per-commit detailedness standard (operator, binding)**: every
  planned commit carries the 8-section checklist — Goal / Scope /
  Implementation plan with `[ ]` items / Validation plan / Acceptance
  criteria (observable conditions, never "tests pass") / Failure and
  edge cases / Verification commands and evidence (recorded after
  execution; never claim an unrun test passed) / Commit boundary.
- The roadmap's §15.1 matrix remains the single step-status authority;
  the folder README is an index only.
