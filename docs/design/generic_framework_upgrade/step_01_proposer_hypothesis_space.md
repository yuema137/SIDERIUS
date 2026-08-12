# Step 01 — 6-P Proposer Hypothesis Space & Prompt Surfaces — detailed design

## Status

**PARENT DESIGN — FROZEN / OPERATOR APPROVED (2026-08-12).**
OD-S1-1..8 all decided (§19). **PR 01a implementation AUTHORIZED**
by the operator on 2026-08-12; PR 01b remains blocked on PR 01a's
merge. This parent stays the status authority; the child designs are
the live implementation ledgers.

Children (one PR = one doc):
- [`pr_01a_contract_derived_prompt_extraction.md`](./step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md)
  — exact-parity extraction; **IN IMPLEMENTATION** (see below).
- [`pr_01b_task_description_join.md`](./step_01_proposer_hypothesis_space/pr_01b_task_description_join.md)
  — the intentional JOIN; **blocked on PR 01a merge; NOT STARTED**.

**Implementation progress (mechanical, 2026-08-12).** Branch
`feat/generic-framework-step-01a-contract-derived-prompt-extraction`,
Landed: `S1-A0` (`4a11e4e8`), `S1-A` (`a3a97014`), `S1-B`
(`aa1127d7`), `S1-D` (the §4.4 contrast rungs B-i / B-ii / FX-2 /
FX-5, their second-surface half, and the mutation closeout). All four
implementation commits are complete; PR closeout (full suite, static
gates, PR, exact-head CI) is the only remaining work. Checkpoint A not
yet closed. The child doc is the live ledger and holds all evidence,
mutations and findings — this Status is only the pointer.

Two implementation questions the earlier draft left open are now
FROZEN from source in PR 01a's design: the standalone node CLI loads
the shipped config through the canonical `load_task_config()` (it is a
documented architectural surface, `docs/architecture.md:164,:273`, and
extraction would otherwise break it), and the loss authority is
imported directly at module level from `ml_models/
models_format_sandbox.py:368,371` (that module imports only `typing`
and `pydantic` — no circularity, no side effects, and Step 01 is its
first production consumer).

Created 2026-08-12 on branch `docs/generic-framework-step-01-design`,
based on the Step-00 implementation head `71f6b31f`
(`feat/generic-framework-step-00-golden-baseline-harness`) so the
landed Step-00 baselines could be read directly.

**STEP-00 DEPENDENCY: RESOLVED 2026-08-12.** Step 00 merged (PR #198 →
`e80da078`; post-merge sync `47fdf6e5`, Checkpoint E complete) and this
branch was synchronized onto that master by merge (not rebase — the
repo hook correctly blocks history rewriting). All five freeze
preconditions are now satisfied:

1. [x] Step-00 PR merged to master.
2. [x] Master contains every baseline ID cited in §8/§11 — verified
   artifact-by-artifact with `git ls-tree master` (§8.1).
3. [x] Step-00 Checkpoint E roadmap sync complete (`47fdf6e5`).
4. [x] THIS design synchronized onto that master; cited baselines
   re-verified present AND green here (proposer package + CFG
   task-config baselines: 526 passed, 2.3 s).
5. [x] Step-00 closure-audit corrections incorporated — the one that
   touches Step 01 is WF-3's components half (now a landed golden,
   `wf3_proposer_components_key_sets.json`), cited in §8.1.

**Session-limit recovery (2026-08-12).** The first design agent was
terminated mid-task by a session limit. Nothing was lost: the worktree,
the committed draft (`fd9bfea6`) and the in-flight review correction
were all recovered; the correction was committed as `ac5581b4` (review
finding F1 — corrected per-template placeholder inventory), and the
durable transcript was mined for further findings (none beyond F1 —
the other F-numbers found there were quotations of the STEP-00 design,
verified as such, not Step-01 findings).

**Adversarial review COMPLETE and reconciled (2026-08-12, §19A).** A
fresh read-only reviewer attacked the draft against the roadmap, the
merged Step-00 design and the source; 12 findings were CONFIRMED (each
re-verified in source by the main auditor) and are corrected in place —
decisively: the F1/F3 extraction row was split per-site because the
shape prose is NOT uniformly renderable (§4.1, OD-S1-7); a
frozenset-iteration renderer would have made the goldens flaky across
processes (§6.2 rule 5, measured); the landed PB-3 fixture leaves
`num_classes=0`, so a prerequisite fixture-completion commit S1-A0 is
now first (§8.1a); an empty ForwardContract would have silently
stripped the I/O contract on a reachable path (§6.2 rule 6); PB-0 was
misidentified and the legacy reasoning SYSTEM prompt has no oracle
(§8.1, §13 R3); 13.4-B was split into two same-axis rungs (§9.2); and
the JOIN's departure from the A-cell's exact-equality text is now an
explicit operator grant (**OD-S1-8**) instead of a design-side
reinterpretation. The document is therefore **READY FOR OPERATOR
REVIEW**; the remaining blockers are the §19 decisions, not further
audit.

**Flexible data input (operator requirement, 2026-08-12)** is designed
in the new §6A: capability matrix, strict Step-1-compatible
terminology, Mode A/Mode B authoring model, the presets-are-not-an-
authority principle, and the fail-closed decision (**Outcome B**,
source-proven). §9.4 maps the F1-F5 contrast ladder onto what this step
can honestly land.

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
   legal for which output type — are RENDERED from their existing
   authorities **at every proposer surface that semantically states or
   consumes that fact** (not: every fact injected into every stage —
   operator wording correction 2026-08-12; the per-site map is §4.1) (`ForwardContract` from the shipped task config; the
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
3. **TIDMAD proposals unchanged by the EXTRACTION**: under the
   shipped TIDMAD task config, every extraction commit renders
   byte-identical prompts (the Step-00 goldens stay green UNMODIFIED).
   Exactly three regeneration events exist, each declared in advance
   (§13 R1/R2/R3): a test-only fixture completion, the JOIN, and the
   optional literal cleanup. The JOIN deliberately makes TIDMAD
   proposals BETTER-INFORMED (the LLM is finally told the task) —
   that is the step's purpose, it is contained in one commit, and it
   requires the explicit operator grant OD-S1-8. Nothing changes
   silently.
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

6. **The proposer's generic templates stop assuming a data shape.**
   After extraction, no generic proposer template independently asserts
   rank, axis names or TIDMAD semantics **in its contract-derived
   blocks**: there, `[B, 256, T]` / `[B, T]` / "256 amplitude bins"
   appear only as text DERIVED from the declared contract. Three
   literal survivors remain by explicit decision, each with a named
   later owner — the shipped description's own prose, the
   two-output-form catalogue (§4.1 tier iii, step 03), and the
   renderer's `per-timestep` descriptor (§4 row F21) — enumerated in
   §9.5 (2nd-review R2-1). A profile declaring a rank-4 neutral-axis contract renders
   prompts carrying that declaration with zero TIDMAD shape residue
   (§9.4 FX-2/FX-5). This makes the proposer **Step-1-compatible** with
   arbitrary declared shapes in the strict sense defined in §6A.2 —
   and explicitly NOT end-to-end capable of executing such a task,
   which remains steps 02/03/04+ work.

## 2. Non-goals and deferrals

Everything below is EXPLICITLY out of scope. Touching any of it is a
material deviation requiring an operator stop.

| # | Non-goal | Owner |
|---|---|---|
| N1 | Implementor/validator mechanics: probe recipes, probe tensor shapes, `_PROBE_NUM_CLASSES=256` (FU-A-1 transport), generated-plugin templates/`_OUTPUT_CONTRACT_COMMENTS`, implementor self-check, validator LLM prompt, implementor code/loss/repair prompts | 6-M, step 04 |
| N2 | Planner/reflector prompts (incl. the >3-history condensed branch — OD-1's step-07a predecessor), interpretation, cache-consolidator, lit-review prompts (incl. the CFG-3a duplicate task_description collapse) | steps 04/07a/09 |
| N3 | Dataset Profile / DatasetConfig extraction; the known-constraints block stays regime-A on the `DATASET_CONFIG` singleton (renderer `agent/prompts.py:722-760`; call site `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1569` — citation corrected, finding F13); segmentation legality (`agent/schemas/proposal.py:1095-1130` divisibility gate) | step 02 |
| N4 | Model/Loss Contract SEMANTICS: output_type alphabet, hybrid disposition, loss-family membership, custom-loss probe recipes — Step 01 RENDERS declarations, never redefines them | step 03 (§5) |
| N5 | Task composition root / regime-B fail-closed binding; no mega TaskConfig; no new YAML file | step 12 |
| N6 | Metric identity: `denoising_score` grammar in causal_reasoning_stage.md:107 stays as-is (MIGRATION PARITY) | step 06 |
| N7 | Transport/schema changes: NO new `ProposalInput`/`ProposalOutput` fields, no protocol changes, no parser allow-list changes (§3.5 shows no new fact needs to survive PAST the prompt render) | n/a — see §6.4 |
| N8 | Hardware/resource facts into task config: the [HARDWARE CONTEXT] runtime block remains the sole budget authority (roadmap §14 resolved row); no VRAM/param literals introduced or "extracted" into config | framework invariant |
| N9 | Forbidden-pattern list extraction: source audit found the forbidden-pattern surface lives ENTIRELY in the validator (`agent/skills/forbidden_pattern_skill.py`, consumed only by `ml_code_validator_agent.py:51,534`; ZERO forbidden-pattern prose in any proposer surface) — despite the roadmap step-1 line naming "forbidden-pattern lists". Recorded as a roadmap-vs-source discrepancy; recommended disposition: 6-M (step 04) owns it with the validator surfaces. OPERATOR DECISION REQUIRED (§19 OD-S1-1) — not silently dropped, not silently absorbed | §19 OD-S1-1 |
| N10 | Prompt WORDING improvements, persona rewrites, dead-code cleanup (e.g. the five ad-hoc test bridges), retry-policy changes, `StubLLMBridge`/pseudo-fidelity work. **Single declared carve-out (finding F12): commit S1-E**, IF and only if OD-S1-2 approves it — deleting the two stale budget numerals is a wording change by the letter of this non-goal, but it is the roadmap §14-resolved disposition for a surface with no later owner. It is isolated, capture-then-edit (§13 R3), and skippable; nothing else in this PR edits prompt wording | n/a |
| N11 | The lit-review `task_description` duplicate (`configs/lit_review_config.yaml`) — guarded by CFG-3a, collapses at step 04 | step 04 |
| N12 | Renaming/moving prompt template files for cleanliness | n/a |
| N13 | **Inventing a structured tensor/axis schema, a preset vocabulary, or preset↔shape consistency VALIDATION** — §6A.1 proves there is nothing structured to validate today and §6A.5 freezes Outcome B; building it here would seize Dataset/Model-I/O semantic ownership | steps 02/03 (binding dependency recorded in §6A.5) |

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
- Placeholders per template (corrected by adversarial review F1):
  comparison_stage.md → ONLY the `{# EXPLORATION_MODE_BLOCK #}` hook
  (:143); comparison_stage_explore.md → {n_agent_proposed};
  comparison_stage_exploit.md → {n_agent_proposed} +
  {n_confirmed_links}; causal_reasoning_stage.md →
  {available_losses_block} (:37) + {minimum_boldness} ×2 (:140);
  proposing_stage.md → {available_losses_block} (:30, again :177),
  {available_models_block} (:32, again :235),
  {recent_gate_exhaustions_block} (:103),
  {recent_trial_validity_block} (:105), {healthgate_evidence_block}
  (:107), {known_constraints_block} (:109), {existing_model_types}
  (:124,:212,:244), {forward_contract} (:131); the three
  causal/proposing mode files carry none. NO stage template renders
  the task description.
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
| F1/F3 | 256 classes; shapes `[B,T] int64 → [B,256,T] float32` / `[B,T] float32` | commit prompt :330,:332,:365-370; proposing_stage.md:41,:70-71,:74 ("256 amplitude bins") — literals with zero config read; the SAME fact reaches proposing_stage.md:131 correctly via `{forward_contract}` | (e) restatements of a live authority | **SPLIT PER SITE** — see §4.1 (adversarial finding F4: these sites are NOT uniformly renderable; the un-split row would have forced either a banned conditional rule or a self-contradictory regressor prompt) |
| F5 | loss legality per output_type | 7 proposer-owned prose sites: commit :330,:367-370; proposing_stage.md:41,:68-71,:85-86,:92,:168 (+2 indirect: `agent/schemas/proposal.py:972-976` — a Field DESCRIPTION, not error text — and `:1247-1248`, the actual validation error text; citation corrected, finding F13) — NONE imports the frozensets; 6 more sites in OTHER nodes (planner `agent/prompts.py:183-184,:1036-1054,:1072-1073` incl. a model-name-keyed rule of the shape V21 PR A deleted from code; reflector :1272; `check_config_format_skill/wrapper.py:22`; implementor :1574) | (e) proposer sites; other-node sites stay per roadmap | **EXTRACT-RENDER** the 7 proposer prose sites from `CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES` (+"custom" from the Literal alphabet); the schema error-text sites KEEP (validation-side, §5 owns); other nodes' 6 sites DEFER to steps 04/07a |
| F4 | output_type alphabet (proposals: 2-valued Literal, `agent/schemas/proposal.py:970`; runtime 3-valued with hybrid builtin-only; validator excludes hybrid `ml_code_validator_agent.py:318`) | prose restatements inside commit prompt + proposing template | (d)+(a) | RENDER the 2-valued proposal alphabet from the schema Literal (or keep literal where it is JSON-skeleton structure); the hybrid disposition is D2 (§5/step 03) — untouched |
| F8 | task description / SQUID prose | reaches the LEGACY path only ({TASK_BACKGROUND}); PIPELINE: `template_vars["task_description"]` supplied :1597, consumed by NO template | (e) dangling seam | **THE JOIN** (§8.3) |
| F6 | segmentation legality | known-constraints block PARAMETERIZED on the singleton (agent/prompts.py:745-746) — regime-A, stays; schema gate `agent/schemas/proposal.py:1095-1130` reads DATASET_CONFIG | (b) rendered from an authority (the singleton) | KEEP (step 02 swaps the object behind it) |
| F6' | powers-of-2 pedagogy ("16384, 8192, 4096 are INVALID… 16000 nearest") | agent/prompts.py:756-759 — TIDMAD-specific prose inside the otherwise parameterized block; false for other psd lengths | (e) | RECORD, DEFER to step 02 (its truth-value depends on the dataset profile; byte-parity keeps it now) |
| F7 | persona "senior ML architect specialising in deep learning for signal denoising" | S1 :276 (legacy); stage personas in templates | (a)/(e) | KEEP AS-IS (MIGRATION PARITY): outside the roadmap-narrowed 6-P fact scope (shapes/classes/task_type/loss legality); no persona authority exists to render from — inventing one violates §0.8. Recorded §18 deferred question |
| F9 | `denoising_score` grammar | causal_reasoning_stage.md:107 | (e) metric identity | KEEP (MIGRATION PARITY; step 06 owns the metric handle) |
| F10 | "baseline=4000" segments anchor | legacy user prompt :1168-1170 | (e) dataset volume fact, underived (200×20) | KEEP (MIGRATION PARITY; step 02 owns dataset facts) |
| F12/F13/F20 | budget prose: "~100M params" S1:284; "10 GB VRAM" causal_reasoning_stage.md:**145** (citation corrected, finding F13); "≤ 80% of the effective cap" :540-541 | contradict the runtime [HARDWARE CONTEXT] block (the roadmap §14 RESOLVED row: derive from the runtime block, no config) | (e) | OD-S1-2 (§19): optional clearly-labeled cleanup commit deleting/re-pointing the two stale numerals (proposer templates have NO later owner — step 04's prompt scope excludes proposer surfaces), with golden regeneration; recommendation INCLUDE |
| F14/F15 | forbidden patterns: skill validator-only (`forbidden_pattern_skill.py`, consumers `ml_code_validator_agent.py:51,:534`); "T ≥ 80,000" never shown to the proposer; proposer's [DISALLOWED PATTERNS] block renders from a DIFFERENT authority (`architectural_pattern_tagger.ARCHITECTURAL_PATTERNS`, :701-709) | skill-local | (a) validator-side | OD-S1-1 (§19): roadmap names "forbidden-pattern lists" in step 1, source says validator-owned → recommend DEFER to 6-M; the tagger↔skill non-sharing is RECORDED as a coupling gap for step 04 |
| F16/F18 | model roster examples + "5.57 SOTA" scores (comparison_stage.md:50-76,:139; causal :121-122); frequency-band file prose (comparison :54-55 — contradicting the no-fixed-index rules at `ml_model_proposal_agent.py:308-309` (reasoning prompt) and `:343` (commit prompt) — a CROSS-SURFACE contradiction, not an internal one; citation corrected, finding F13) | template literals | (e) | KEEP (MIGRATION PARITY): catalogue = V11 (§5+§6 owned, steps 03/04); band semantics = V7 (§4, step 02). Both recorded; the internal contradiction registered as defect-not-blessed |
| **F21** (2nd-review R2-2) | `render_forward_contract`'s task-type descriptor `Task type: {task_type} (per-timestep {num_classes}-class).` — a TEMPORAL-axis assertion emitted by PRODUCTION CODE from a STRUCTURED field, not by prompt prose | `workflows/task_config.py:206-212`; shipped bytes pinned by CFG-2 golden `cfg2_forward_contract_block.txt` ("Task type: classification (per-timestep 256-class)."); reaches proposing_stage.md:131 and (post-JOIN) the commit surface | (e) authority-rendered, but the AUTHORITY ITSELF hardcodes a rank assumption | **KEEP byte-identical** in Step 01 (regime-A parity; any change regenerates CFG-2, which Step 01 does not own) + **whitelist it in §9.5** so FX-2/FX-5 do not fail on it + **route to step 02/03**: a rank-4 spatial contract with `num_classes>0` would render "per-timestep 16-class", which is wrong for that task. Recorded as a defect-not-blessed |
| F2/F11/F17 | int8/+128 encoding, 20-files/10M, CH1/CH2 | ABSENT from proposer prompts (encoding implied by "ADC class indices"/config's "0-255") | (d) | no action (correctly not exposed); recorded so nobody "extracts" a fact that is not there |
| — | quirks: registry blocks double-substituted (proposing :30/:177, :32/:235); `proposing_stage` loaded WITHOUT `mindset` (:1887-1891, asymmetric with the 3 reasoning-stage sites); `ProposalInput.constraints` never populated in production (absent from the protocol; only scripts inject it); shipped YAML `output_head_note` contains the un-substituted token `[output_shape]` rendered verbatim | verified | (e) | ALL KEPT byte-identical (parity); registered in §17.3 known-quirk list, never blessed |

### 4.1 F1/F3 per-site renderability (adversarial finding F4 — decisive)

The shipped `ForwardContract` declares ONE output form
(`output_shape: "[B, 256, T] float32"`, `num_classes: 256`,
`task_type: "classification"`); there is NO declared regressor form
anywhere in-tree. The prompt sites state the fact in ≥4 incompatible
surface forms. Splitting them:

| Tier | Sites | Why | Step-01 action |
|---|---|---|---|
| **(i) Verbatim-renderable** — the literal equals a ForwardContract field byte-for-byte | commit :332's `[B, T] int64 (per-timestep ADC class indices)` and `[B, 256, T] float32 (per-timestep logits over 256 denoising classes)`; commit :365's `The input is fixed: [B, T] int64`; proposing_stage.md:131 (ALREADY rendered) | pure field insertion; satisfies §6.2 rule 1 without any transformation | **EXTRACT-RENDER** (S1-A/S1-B) |
| **(ii) Needs a DECLARED formatting rule** — same fact, different surface form (dtype dropped, backticks, "float" vs "float32") | commit :330 (`[B, 256, T] per-timestep class logits`); proposing_stage.md:41, :70-71 (`` `[B, 256, T]` float ``) | rendering these from `output_shape` requires a dtype-stripping/formatting transformation — a rule, not an insertion | **DEFERRED out of Step 01** unless OD-S1-7 approves the single explicit formatting rule below; default = KEEP LITERAL with a template-layer note pointing at §5's future contract |
| **(iii) No authority — KEEP LITERAL** | the REGRESSOR branch text everywhere (commit :330/:369, proposing_stage.md:41/:71); "256 amplitude bins" (:74) and "256 denoising bins" (commit :332's third citation) — invented nouns with no declared counterpart | no declared regressor form exists; inventing one is §0.8 speculative abstraction and §5-owned semantics | **KEEP** (MIGRATION PARITY), recorded as a step-03 convergence candidate (DQ-3) |

Consequence for §1: the step's final effect stands (the
hypothesis-space facts DERIVE where an authority exists), but the
honest scope is **tier (i) + loss legality + the JOIN**, not "all 256
literals disappear". The remaining literals are named, classified and
routed — never silently left as unexamined hardcodes.

Optional single formatting rule (OD-S1-7, recommended REJECT for this
step): "a `<shape-without-dtype>` token derives from `output_shape` by
dropping the trailing dtype word". It is one rule, testable, and would
move tier (ii) into scope; it is nonetheless a semantic decision about
the contract's surface forms, which §5 owns.

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
5. **Deterministic render ORDER is part of the contract (adversarial
   finding F4b — verified by the main auditor: three fresh processes
   produced `['ce','focal','focal_cw']`, `['focal','ce','focal_cw']`,
   `['focal','focal_cw','ce']`).** A renderer must NEVER iterate a
   frozenset directly — that would make every prompt golden flaky
   across processes, defeating the §2 exact-equality criterion. Rules:
   legality lists render via `sorted()` over the frozensets; the
   built-in loss ALPHABET list (proposing_stage.md:85-86, :168 — the
   `focal, focal_cw, ce, smooth_l1` order) renders from
   `LossConfig.loss_type`'s `Literal.__args__` declaration order
   (`ml_models/models_format_sandbox.py:458`), a DIFFERENT authority
   with its own intentional order. Both orderings are pinned by a
   unit test, and mutation M-8 (shuffle the source order) must turn
   the goldens red.
   Byte-parity consequence: `sorted()` gives `ce, focal, focal_cw`,
   which MATCHES commit :330/:367 and proposing_stage.md:70 as
   written — so those sites extract at byte parity. Any site whose
   literal order differs from both authorities is tier-(ii)/(iii) by
   §4.1 and stays literal.
6. **Empty/absent contract must FAIL VISIBLY, not silently degrade
   (adversarial finding F9 — verified).** The node's standalone CLI
   (`ml_model_proposal_agent.py:2163-2170`) builds `ProposalInput`
   with NO `task_description` and NO `forward_contract`, then runs the
   LEGACY path — so after extraction, a naive "empty contract → empty
   render" (today's `_render_task_background` regime-A behavior,
   :409) would send a commit prompt with the I/O contract REMOVED on a
   production-reachable path (§3.2 entry iii). That is a behavioral
   regression, not parity. Required: the commit-prompt render is
   FAIL-CLOSED on an empty contract (raise with a message naming the
   missing declaration), pinned by a test AND by an extension of the
   re-targeted contract-reassertion suite; the CLI's own construction
   is then either fixed to load the task config or left to raise
   loudly (decide at implementation inspect-first, record the choice).
   The legacy REASONING prompt's existing empty-collapse behavior is
   NOT changed (that surface has always degraded; changing it is out
   of scope).

## 6A. Flexible data input — rank-agnostic boundary (operator requirement, 2026-08-12)

Added after the first draft, on operator direction. The framework
target is NOT an enumeration of 1D/2D/3D/spatiotemporal; those are
instances. The target boundary is:

> A task may expose one or more named tensors of arbitrary rank, with
> declared dtype, ordered axes, axis semantics and dimension
> constraints. Framework prompt consumers do not branch on 1D/2D/3D or
> hardcoded axis names.

This section states, from source, exactly how much of that Step 01 can
honour — and refuses to claim the rest.

### 6A.1 Capability matrix — what the CURRENT surfaces can express

Source facts (main-auditor verified at this head):

- `ForwardContract` (`agent/schemas/task_config.py:31-99`) has exactly
  nine fields: `input_shape`, `input_description`, `output_shape`,
  `output_description` (all `str`), `num_classes` (`int`, ge=0),
  `embedding_note`, `output_head_note`, `task_type` (free-form `str`,
  its own docstring says "consumers should treat unknown values as
  opaque labels"), `task_note`. `extra="forbid"`.
- `ProposalInput.forward_contract` (`agent/schemas/proposal.py:678`)
  is that same type — the proposer receives no other contract object.
- `render_forward_contract` (`workflows/task_config.py:191-205`)
  emits two fixed lines (`input:` / `output:`) plus the optional notes.
- **No code anywhere parses a shape string.** A repository-wide search
  for `.split(`/`.strip(`/`.replace(`/`.startswith(`/`re.*` applied to
  `input_shape`/`output_shape` across `agent/`, `nodes/`, `workflows/`,
  `execute_tools/`, `ml_models/`, `core/` returns ZERO hits. The
  strings are transported and rendered verbatim.
- `num_classes` is the ONLY structured field, and it is an output-class
  count, not an axis length; the validator's own comment says it "is
  consumed only for prompt rendering"
  (`ml_code_validator_agent.py:327`).
- **No Dataset Contract or Model I/O Contract module exists yet** —
  `agent/schemas/` contains nothing matching dataset/contract/tensor.

| Capability | Classification | Evidence |
|---|---|---|
| arbitrary tensor rank | **REPRESENTABLE AS PROSE ONLY** | shape is a free `str`; nothing parses it |
| ordered axes | PROSE ONLY | no axis list exists in any schema |
| semantic axis roles (temporal/spatial/channel/batch) | PROSE ONLY | no role vocabulary anywhere in source |
| fixed dimensions | PROSE ONLY | `num_classes` is the sole structured number and is not an axis length |
| symbolic dimensions (`B`, `T`) | PROSE ONLY | they are characters inside the string |
| dynamic dimensions | PROSE ONLY | same |
| multiple NAMED input tensors | **REQUIRES STEP-02 DATASET CONTRACT / STEP-03 MODEL I/O CONTRACT** | single unnamed `input_shape` field; no name/multiplicity concept |
| multiple NAMED output tensors | REQUIRES STEP-02/03 CONTRACT | single unnamed `output_shape` |
| cross-tensor dimension relationships | PROSE ONLY (expressible only as free text in `task_note`) | no relational structure |
| dtype | PROSE ONLY | embedded inside the shape string |
| batch/sample semantics | PROSE ONLY | `B` is prose convention, not declared |

**Consequence (corrected by 2nd-review R2-2).** The transport is
rank-agnostic in the only sense it can be: it never inspects rank,
because it never parses. Rank assumptions therefore live almost
entirely in **prompt PROSE** — the §4 coupling inventory — with ONE
exception that must not be glossed: `render_forward_contract`
(`workflows/task_config.py:206-212`) itself emits
`(per-timestep {num_classes}-class)`, a temporal-axis assertion
generated by production code from a structured field, and it branches
on `if fc.num_classes:`. That is §4 row F21: kept byte-identical here
(CFG-2 owns its bytes), whitelisted in §9.5, and routed to step 02/03
as the first thing a real tensor contract must fix. Everything else is
(F1/F3 `[B, 256, T]`/`[B, T]` restatements at `PROPOSAL_COMMIT_PROMPT`
:330,:332,:365-370 and `proposing_stage.md`:41,:70-71,:74; F4
output_type alphabet; F5 loss legality). Step 01's extraction of those
literals into rendered declarations IS the rank-agnostic work available
at this step.

### 6A.2 Strict capability terminology (frozen)

**Step-1-compatible.** A task is Step-1-compatible when its hypothesis
space can be communicated to the current Proposer through an explicit
task description and a normalized model-facing data/forward-contract
description, while preserving the current `ProposalOutput` schema and
the unchanged downstream handoff. Concretely, after Step 01: supplying a profile whose contract prose
declares a rank-4 tensor with neutral axis names produces proposer
prompts whose **Step-01-owned contract-derived blocks** carry that
declaration with no contradicting TIDMAD shape residue. It does NOT
mean the whole prompt is free of TIDMAD shape text — §9.5 enumerates
three legitimate survivors (the shipped description's own prose, the
two-output-form catalogue, the renderer's `per-timestep` descriptor),
each with a named later owner.

**Name precision (operator correction 2026-08-12).** Read
"Step-1-compatible" strictly as **Step-1 PROMPT-CONTRACT
compatibility**: compatibility at the task-description and
declared-contract surfaces only. After Step 01 the proposer still
carries other TIDMAD-era priors OUTSIDE this slice — persona/domain
prose (F7), the model catalogue and its SOTA scores (F16/F18), the
metric grammar (F9), dataset anchors (F10/F6'), the two-output-form
catalogue (§4.1 tier iii) and the grandfathered `per-timestep`
renderer (F21). None of them is removed here; each is recorded with
its owning step. Step 01 therefore makes the proposer neither
task-agnostic nor end-to-end compatible.

**Not yet end-to-end compatible.** Such a task is still NOT executable:
data loading, batching/collation, probe tensors, generated-plugin
execution, artifact writing, scoring and HealthGates all remain bound
to TIDMAD until steps 02/03/04+. Step 01 must never be described as
arbitrary-task end-to-end support. The §12 acceptance packs assert
prompt-level properties only.

### 6A.3 Mode A / Mode B — the target authoring model (recorded, NOT built here)

**Mode A — explicit tensor contract (canonical).** The user names each
tensor and declares dtype, ordered axes, axis semantics, fixed/symbolic/
dynamic dimensions, batch/sample role and cross-tensor relationships.
Explicit specification is the canonical semantic representation; exact
fields and syntax belong to the contract-owning step (02/03), not here
(§6.2 rule: Step 01 renders declarations, never defines them).

**Mode B — semantic preset (convenience).** Provisional families,
recorded as design input for the contract owner, deliberately NOT
frozen as API values by this step:

| Family | Defining requirement (axis-ROLE based, never rank-number based) |
|---|---|
| `generic_tensor` | no rank-specific assumption; user supplies axes/dims; universal escape hatch |
| `time_series` | ≥1 axis declared temporal; MAY carry one or more channel/feature axes (a multi-channel series is a valid instance — "time series" must never mean scalar `[B,T]`); no `[B,T]`/`[B,C,T]` ordering assumption |
| `spatial_grid` | ≥1 axis declared spatial; images and volumes are instances of ONE family — core logic must not branch "2D image" vs "3D volume" |
| `spatiotemporal` | ≥1 temporal AND ≥1 spatial axis; no fixed rank or ordering |

### 6A.4 Presets are convenience, not a second authority (FROZEN PRINCIPLE)

> A semantic preset is authoring convenience that resolves into,
> constrains or validates an explicit normalized tensor contract. It is
> never an independent competing source of truth.

The required shape is:

```text
user authoring form (Mode A or Mode B)
    -> resolution / consistency validation      [owner: step 02/03]
    -> ONE normalized rank-agnostic contract
    -> proposer rendering                        [owner: step 01]
```

Forbidden anywhere in the framework — including in anything Step 01
lands:

```python
if data_is_1d: ...
elif data_is_2d: ...
elif data_is_spatiotemporal: ...
```

**Step 01's binding obligation under this principle:** the proposer
consumes the ONE resolved declaration and must not branch on a preset
label, a rank, or an axis name. **One pre-existing branch is
grandfathered, not blessed** (2nd-review R2-2): `if fc.num_classes:`
in `render_forward_contract:209`. Step 01 may not add branches and may
not remove that one (CFG-2 pins its output); §4 row F21 assigns its
removal to the contract owner. This is enforceable today and is
asserted by N-RANK (§15) — no Step-01 renderer may read `task_type` or
any shape text to select a code path; `task_type` is rendered as an
opaque label, exactly as its schema docstring already requires.

### 6A.5 Fail-closed on preset/shape inconsistency — **OUTCOME B (frozen, source-proven)**

The rule the framework must eventually enforce: when a preset and
explicit tensor information are both present and inconsistent (e.g.
`time_series` with no temporal axis; `spatial_grid` with no spatial
axis; a declared `output.H == input.H` relation contradicted by the
contracts; a dense preset over a ragged structure), the run must fail
with an explicit typed/configuration error **before any LLM request is
constructed**. Silently rewriting the shape, silently dropping the
preset, silently defaulting to TIDMAD, inferring semantics from model
names or filenames, or letting contradictory prose reach the Proposer
are all forbidden.

**Decision: OUTCOME B — the validation belongs to Step 02/03; Step 01
renders an already-resolved declaration.** Grounds:

1. There is nothing to validate against. Consistency checking requires
   structured axes/roles/dims; §6A.1 shows the entire contract is prose
   and that no component parses it. A check written now could only
   regex free text.
2. Building the structure here would take semantic ownership of the
   Dataset (step 02) and Model I/O (step 03) contracts — forbidden by
   the roadmap's 6-P/6-M split and by this design's §2/§6.2.
3. Outcome C is unavailable: a child PR needs an *already-authoritative*
   surface with a live consumer. Source shows no authority (no contract
   module), no parser, no consumer. Splitting would create exactly the
   consumer-less seam the roadmap forbids.

**Recorded as a BINDING DEPENDENCY on the contract-owning step** (02 or
03, whichever introduces the structured tensor contract):

- the consistency axis is NOT only preset↔tensor. **After S1-C the
  shipped `task_description` and the rendered `ForwardContract` are
  two independent prose channels describing the same tensors**
  (`configs/task_config.yaml:11-14` hardcodes `[B, T]`/`[B, 256, T]`),
  so a profile can contradict itself across channels with nothing
  validating it (2nd-review R2-6). The structured check MUST cover
  description↔contract consistency, not just preset↔tensor;
- resolution and consistency validation MUST run before proposer
  rendering, and MUST fail closed with a typed error;
- the resolved output MUST be a single normalized rank-agnostic
  contract, not a preset label plus loose fields;
- the proposer's rendering seam landed by Step 01 is the intended
  consumer — the later step wires the resolved contract into it and
  does not add a second rendering path.

**Step 01's own obligations under Outcome B** (all testable here):

(a) introduce no new rank/axis assumption into any generic template;
(b) render whatever the declaration says, so a rank-N prose contract
    already flows end-to-end to the LLM boundary (FX-2/FX-5-prose, §9.4);
(c) branch on nothing (§6A.4, N-RANK);
(d) leave the transport untouched, so the later structured contract can
    replace the prose source without a second proposer migration.

### 6A.6 Transitional absent-contract semantics

- **Regime A (legacy/TIDMAD adapter, unchanged by this step).**
  Un-migrated callers that omit the extracted profile keep exactly
  today's TIDMAD prompt bytes — that IS the Stage-A parity contract
  (§8): the shipped `configs/task_config.yaml` remains the default
  source, so nothing about legacy behaviour changes.
- **What fails closed TODAY (pre-existing, not new):**
  `ForwardContract` is `extra="forbid"`, so a MISTYPED YAML key raises
  a `ValidationError` rather than rendering empty; the loader rejects a
  missing/empty `task_description`.
- **What does NOT fail closed today (2nd-review R2-9 — stated so the
  bullet above is not read as completeness):** every `ForwardContract`
  field has a default, so an OMITTED key validates fine and renders an
  empty shape; and a downstream consumer silently substitutes a
  TIDMAD-ish rank-3 default —
  `ml_model_implementor.py:980`
  (`output_shape = inp.forward_contract.output_shape or "[B, C, T] float32"`).
  Both are outside 6-P (the implementor is step 03/04 territory) and
  Step 01 must not touch them; recorded here with owners so the
  "no silent TIDMAD inheritance" claim stays honest. §6.2 rule 6's
  fail-closed requirement covers only the proposer's own surfaces.
- **What Step 01 adds:** once F1/F3/F5 literals are derived, an
  explicitly declared non-TIDMAD profile can no longer inherit TIDMAD
  shape/class/loss prose — the derived text tracks the profile, and
  N11/N-RESIDUE (§15) assert zero `TIDMAD`/`SQUID`/`[B, 256, T]`
  residue under a contrast profile. That is a real, enforced
  anti-silent-default property at the prompt layer.
- **What remains for Step 12:** universal fail-closed on a MISSING
  declaration (regime B). Step 01 must not invent the composition root
  to get there early.

### 6A.7 Prompt responsibility — the six required answers

1. **Which authority produces the text?** `configs/task_config.yaml` →
   `load_task_config()` → `ForwardContract` → `render_forward_contract`
   for shapes/classes/notes; `CLASSIFICATION_LOSSES`/`REGRESSION_LOSSES`
   (`ml_models/models_format_sandbox.py:368,371`) for loss legality;
   the shipped `task_description` string for the task block.
2. **Structured fields or already-rendered prose?** Step 01 renders
   from the EXISTING typed fields (it calls the existing renderer and
   the existing frozensets). It does not define new structured fields;
   when step 02/03 introduces the normalized contract, it substitutes
   the SOURCE behind the same seam.
3. **Same resolved block in commit prompt and pipeline stages?** Yes —
   one renderer feeding both surfaces is the design (§8.2); today the
   commit prompt has ZERO placeholders and the stages have their own,
   which is exactly the duplication being removed.
4. **How does TIDMAD stay byte-exact?** The extraction commits are
   byte-parity commits: PB-0/PB-3/PB-4 goldens must stay unchanged
   (§8.1/§13), with the single deliberate JOIN regeneration in S1-C.
5. **Does any parser/schema hop drop it?** No — audited in §3.5: the
   contract travels as `ProposalInput.forward_contract` and is rendered
   into prompt text; the proposal PARSE side is independent
   (`ProposalOutput`), so nothing to drop. This is also why no
   transport change is required (§2 non-goal).
6. **Who owns the real contract semantics?** Step 02 (dataset/topology)
   and Step 03 (model I/O). Step 01 owns rendering only, and says so in
   §5's ownership map.

## 7. PR decomposition decision — PARENT + TWO CHILD PRs (operator-frozen 2026-08-12)

**The earlier ONE-PR freeze is SUPERSEDED by operator decision.** The
audited work contains two materially different behavioural units, and
the operator's splitting standard (independent final effect, independent
validation boundary, different risk) is met:

| | PR 01a — contract-derived prompt extraction | PR 01b — task-description JOIN |
|---|---|---|
| Design | [`step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md`](./step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md) | [`step_01_proposer_hypothesis_space/pr_01b_task_description_join.md`](./step_01_proposer_hypothesis_space/pr_01b_task_description_join.md) |
| Central claim | final TIDMAD prompt bytes **UNCHANGED** | the production proposer **now consumes the declared task description** — an intentional behaviour change |
| Commits | S1-A0, S1-A, S1-B, contract/rank/loss half of S1-D, PB-4 boundary re-target | S1-C (JOIN, all 3 stages), FX-1/13.4-A contrast, S1-E budget cleanup, closeout |
| Golden regeneration | **NONE** (any byte change is a defect) | the declared R2 set only |
| Checkpoints closed | 0, A, D (own head) | B, C, D (own head), E |
| Roadmap A-cell | satisfied exactly | the declared OD-S1-8 exception |
| Risk profile | behaviour-preserving refactor | changes what the LLM sees on every production proposal |

**Why they must not share a PR.** A reviewer of a mixed diff cannot
separate "byte-identical extraction" from "we deliberately changed the
prompt": the extraction's entire acceptance claim is *zero golden
diff*, while the JOIN's is *these specific goldens changed on
purpose*. Merging them destroys the strongest available review signal.
The split also isolates the roadmap-A-cell exception (§2 iron law:
exact string equality for TIDMAD) into one small, clearly-labelled PR.

**Child criteria, checked (the operator's seven):** (1) independent
final effects — see the table; (2) master usable after either merge —
01a is behaviour-preserving; 01b is self-contained and additive;
(3) own parity evidence — 01a's is zero-diff on the whole Stage-A
golden set, 01b's is the declared R2 diff plus FX-1; (4) live consumer
each — 01a's renderers are consumed by the production commit/pipeline
render calls, 01b's JOIN is consumed by the three stage templates and
proven at the production entry; (5) independent validation boundaries
— 01a needs no chain evidence, 01b closes Checkpoint C pre-merge;
(6) no half-enabled sibling state — 01a leaves the pre-existing dead
key exactly as it found it (a pre-existing condition, first-review
F8), and 01b starts from merged 01a; (7) real risk isolation — see
the risk row.

**Dependency DAG (strict):**

```text
Step 00 (merged, e80da078)
        ↓
PR 01a  contract-derived prompt extraction   [Checkpoints 0, A]
        ↓  (must MERGE first — never parallel)
PR 01b  task-description JOIN                [Checkpoints B, C, E]
        ↓
Step 01 COMPLETE  → step 02 unblocked
```

The parent Step is COMPLETE only when BOTH children merge and the
aggregate Checkpoint E (roadmap §15.1 row sync) closes.

## 8. Stage A — TIDMAD extraction parity (exact Step-00 baseline IDs)

Criterion (roadmap §2 row 1 + 6-P matrix row A): rendered proposer
prompts EXACT string equality for the TIDMAD profile, all surfaces;
plus the boundary-capture invariant (labels/components) unchanged.

**Declared exception to that criterion (adversarial finding F14 —
requires operator authorization, OD-S1-8).** The JOIN commit (§8.3)
deliberately CHANGES the rendered TIDMAD bytes of the stage system
prompts. The roadmap's A-cell for 6-P says "rendered proposer prompts
(all 3 stages incl. commit) EXACT-equal for TIDMAD", so the design
does not get to redefine A quietly — it states the exception, names
the authorities that permit it, and asks the operator to authorize it:

- *Permitting*: Step-00 §15.2's last row assigns the
  shipped-description→proposer JOIN to Step 01 **as its own A-work**
  (the later, more specific authority); roadmap §0 rule 8 requires
  Stage-A seams to land WITH their first consumer and names this exact
  dead key as an instance of the repository's most-repeated defect;
  roadmap §17 Checkpoint C forbids a consumer-less seam surviving the
  PR; roadmap fixture 13.4-A demands "zero SQUID residue in the
  description-derived blocks", which is unsatisfiable on the pipeline
  path while no description-derived block exists; roadmap §13.2
  defines genericization as "MORE placeholders/blocks per node, each
  landed with its consuming template in the same PR".
- *Excepted text*: roadmap §2 row 1 (exact equality) and the §15.1
  6-P A-cell, for the JOIN commit only; and the A-cell's companion
  phrase "TIDMAD proposals unchanged", which this design reads as
  "unchanged by the EXTRACTION; deliberately better-informed by the
  JOIN" — a narrowing that is now named rather than assumed
  (finding F12).
- *Containment*: every OTHER commit is byte-exact; the exception is
  one commit, one declared golden set, §13-governed, with diffs
  attached.

Everything below assumes this exception is granted; if OD-S1-8 is
refused, the JOIN moves out of Step 01 and §1's effect 2, fixture
13.4-A/F1 and Checkpoint C all have to be re-planned (recorded so the
consequence of refusal is visible).

### 8.1 Baseline map (every claim names a landed Step-00 ID)

| Step-00 baseline (status at 71f6b31f) | What it pins | Stage-A use in Step 01 |
|---|---|---|
| **PB-3** (9 goldens: 3 stage system prompts × explore/exploit + 3 mode-invariant user prompts; + label-sequence pin) — landed, green | the PRODUCTION pipeline render through real `run()` under a pinned environment with a TEST-OWNED ForwardContract/description fixture | regenerated in S1-A0 (fixture completion, §8.1a) and again in S1-C (JOIN, system prompts only); extraction commits S1-A/S1-B must keep all 9 byte-identical against the S1-A0 set, label sequence unchanged; the three `pb3_*_user.txt` goldens never change |
| **PB-4** (2 goldens: commit system constant + commit user render) — landed, green | the legacy commit surface | S1-A: golden BYTES unchanged; the system-side assert moves constant→render (§11.1) |
| **PB-0** (the 4 pre-existing goldens registered by Step-00 §13:699; the proposer member is `goldens/reasoning_prompt_structured_evidence.txt`) — landed (REG), green | **CORRECTED (adversarial finding F6a, main-auditor verified)**: its owning test is `test_health_prompt_parity.py:27,:36`, which asserts `_build_reasoning_prompt(inp) == GOLDEN` — the legacy **USER** prompt. The legacy **SYSTEM** prompt (`_build_reasoning_system_prompt`, the `{TASK_BACKGROUND}` path at :423-435) has **NO full-string golden anywhere** | untouched by S1-A..D. **Gap consequence**: OD-S1-2's cleanup at `PROPOSAL_REASONING_PROMPT:284` would edit a surface with NO parity oracle — so S1-E, if approved, must FIRST capture a Step-01 baseline of the legacy reasoning SYSTEM render (a new golden, captured pre-edit, §13 rule 5) and only then make the edit |
| **WF-3** proposer half (component-key-set golden `wf3_proposer_components_key_sets.json` + per-surface label asserts + `components is not None`) — landed, green | label=/components= crossing `generate`/`generate_text` at the proposer sites | "same kwargs reach LLMBridge": key sets and labels unchanged by extraction; JOIN renders into `system_prompt` (an EXISTING component key) so the key-set golden stays valid — any key-set change is a design failure, not a regeneration |
| **CFG-1** (resolved shipped task-config dict), **CFG-2** (2 rendered task strings) — landed, green | the shipped authority content Step 01 renders FROM | untouched (Step 01 never edits YAML/loader); they anchor the JOIN's "shipped description" claim |
| **CFG-3a/3b** (lit-review duplicate + semantics) — landed, green | the duplicate-description channel | untouched guard (N11) |

Dependency status: **VERIFIED ON MASTER 2026-08-12.** Step 00 merged
(PR #198 → `e80da078`; post-merge sync `47fdf6e5`) and this branch is
synchronized onto it. Every row above was re-verified as an actually
committed artifact on master — `git ls-tree master` shows the 9 PB-3
goldens, the 2 PB-4 goldens, PB-0's
`reasoning_prompt_structured_evidence.txt`, WF-3's
`wf3_proposer_components_key_sets.json`, and CFG-1/2/3b's four
goldens — and the consuming suites run green here (proposer package +
CFG task-config baselines: **526 passed, 2.3 s**). No row is claimed
from the Step-00 design text alone.

### 8.1a PB-3 fixture upgrade is a PREREQUISITE, not an option (adversarial finding F6b — main-auditor verified)

The landed PB-3 fixture builds its contract as `ForwardContract(
input_shape="[B, T] int64", input_description="per-timestep ADC class
indices", output_shape="[B, 256, T] float32",
output_description="per-timestep logits over 256 classes")`
(`tests/unit/agent/ml_model_proposal_agent/
test_step00_prompt_goldens.py:153-166`) — i.e. **`num_classes`
defaults to 0** (`agent/schemas/task_config.py:69`), `task_type` is
empty, and the description differs from the shipped one ("256 classes"
vs "256 **denoising** classes").

Consequence: any `num_classes`-derived token renders `0` under this
fixture, so §14.2's "all 9 PB-3 goldens unmodified" is UNACHIEVABLE as
originally written — the goldens would go red for a FIXTURE-ROT reason
(§17 triage class 3), not a production reason.

Resolution (chosen; alternatives recorded):

- **CHOSEN — commit S1-A0 (new, first in the sequence)**: upgrade the
  PB-3 fixture contract to a complete, self-consistent TEST-OWNED
  declaration (populated `num_classes` + `task_type` + descriptions
  matching the tokens the templates actually carry) BEFORE any
  extraction. Because fixture inputs change, the affected PB-3 goldens
  are regenerated — a **second §13-governed regeneration event,
  declared here in advance** with its own provenance message and
  attached diffs. It is a TEST-ONLY commit with zero production diff,
  and after it every later byte-parity claim is meaningful.
- Rejected A: derive only from fields the current fixture populates —
  leaves `num_classes`, the headline 6-P fact, permanently un-derived.
- Rejected B: special-case the renderer when `num_classes == 0` — a
  conditional semantic rule, banned by §6.2 rule 1.

Scope note absorbed from the review: under OD-S1-3(a) the JOIN touches
the **6** `pb3_*_system.txt` goldens, not 9 — the three
`pb3_*_user.txt` goldens are USER prompts and must stay byte-identical
through every commit; a JOIN that reds a user golden is a scope leak
(§17 case 2).

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
- Asserts: (1) `_ALT_TD` appears in the task-background block of
  **every stage system prompt the JOIN targets** — three stages under
  OD-S1-3(a), the proposing stage alone under (b). *(Adversarial
  finding F13: the original wording presupposed outcome (a); the
  fixture is now written against whatever OD-S1-3 decides, and §18.2
  risk 1's golden count follows the same outcome.)*; (2) ZERO SQUID
  residue in the
  description-DERIVED blocks — `"SQUID"`, `"dark-matter"`,
  `"magnetometry"` absent from the task-background block (NOT from
  the whole prompt: contract prose legitimately still says
  "denoising classes" because the CONTRACT is TIDMAD's — axis
  isolation, roadmap §13.3(b) honesty rule); (3) contract-derived
  tokens byte-identical to the TIDMAD variant of the same render.
- Proves: the description channel flows and carries no hidden
  description-derived hardcode.

### 9.2 Fixture 13.4-B — declared ForwardContract only (PROSE rendering only)

**Two rungs on ONE axis (adversarial finding F7 — the single-fixture
form silently fused two incompatible contract profiles).** A regressor
contract has `num_classes = 0` **by schema contract**
(`agent/schemas/task_config.py:69-73`: "Set to 0 for regressor or
hybrid tasks"), so it cannot exercise a classifier-form token; the two
must be separate fixtures on the same axis:

- **B-i (the roadmap's named 13.4-B)** — the in-tree regressor
  precedent `tests/unit/workflows/test_task_config.py:267-289`
  (`test_custom_non_squid_shapes_replace_defaults`: regressor shapes,
  `num_classes=0`, `task_type="regression"`, already asserting
  `"[B, 256, T]" not in rendered` and `"256-class" not in rendered`).
  `task_description` = SHIPPED TIDMAD string UNCHANGED.
- **B-ii (num_classes rung)** — a 16-class CLASSIFIER contract, same
  description held fixed. This is the rung that exercises the
  `num_classes`-derived token and the contrast half of the re-targeted
  contract-reassertion pins (§11.1 row 1).

- Asserts (both rungs): (1) derived contract tokens track the
  declaration — declared input/output shape strings render; `256`
  absent from every contract-DERIVED token; on B-ii the
  num_classes-derived token shows `16`; (2) loss-legality prose
  UNCHANGED (frozensets are not the varied axis); (3) the TIDMAD
  description renders unchanged in the task-background block.
- Proves: shapes/classes/task_type prose derives from the declaration;
  no shadow literal survives.
- Scope honesty (roadmap matrix B cell: "PROSE-rendering only"): this
  fixture proves PROMPT rendering tracks the declaration. It claims
  NOTHING about training/validation executing such a contract — that
  is steps 02/03.

### 9.3 Ladder note

The roadmap B cell for 6-P names exactly 13.4-A + 13.4-B; B is landed
as its two same-axis rungs B-i/B-ii (§9.2) plus the operator's FX-2/FX-5
prose rungs (§9.4) — every fixture varies exactly one axis, and the
count of fixtures is not the same thing as the count of axes.
Loss-family variation is NOT a fixture axis (the frozensets are
production authorities, not per-task profiles yet — step 03);
authority-tracking is proven by mutations M-5/M-8 instead (§15).

### 9.4 Flexible-input contrast rungs F1-F5 (operator ladder, 2026-08-12)

Mapped onto what Step 01 can honestly land given §6A.1/§6A.5. Each rung
is ATOMIC — exactly one axis varies per fixture; no fixture changes
description AND rank AND dtype together.

| Rung | Varies | Step-01 disposition | Evidence / owner |
|---|---|---|---|
| **FX-1** — task description only | description text; TIDMAD contract untouched | **LANDS** — it IS fixture 13.4-A (§9.1) | asserts the JOIN carries the profile text and nothing else moves |
| **FX-2** — explicit rank/axes only | one contract declaration with rank-4 NEUTRAL axis names (e.g. `[B, S, F1, F2] float32`) and an unfamiliar `task_type` (e.g. `operator_defined_xyz`, proving §6A.4's opaque-label rule); description untouched, no preset | **LANDS as a PROSE contrast** (extends 13.4-B, §9.2) | proves no generic template re-asserts rank. **Residue assertion is SCOPED (2nd-review R2-1)**: zero `[B, 256, T]`/`[B, T]`/"amplitude bins"/"256 denoising" inside the CONTRACT-DERIVED blocks only — see §9.5's whitelist of three literal survivors that this rung must NOT attempt to remove. Neutral axis names so the test does not merely swap one domain's assumptions for another's |
| **FX-3** — preset resolution only | a semantic preset resolving over a fixed explicit contract | **DEFERRED — prerequisite for step 02/03** | no preset mechanism exists (§6A.1); the rung becomes the contract owner's Stage-B requirement, recorded here so it is not lost |
| **FX-4** — mismatch rejection (typed failure before the LLM boundary; no prompt capture fires) | preset vs explicit contract conflict | **DEFERRED — binding dependency, §6A.5** | Step 01 cannot fail closed on a conflict it cannot represent; the contract owner MUST land this rung with its structured contract |
| **FX-5** — multi-channel time series (proves "time series" ≠ scalar `[B,T]`) | a multi-channel temporal declaration | **LANDS as a PROSE contrast** (one extra profile alongside F2); STRUCTURAL form deferred with F3 | at the prompt layer the property is real and testable today: a `[B, C, T]`-style declaration must render verbatim with no scalar-`[B,T]` residue |

Honesty clause: FX-2/FX-5 as landed here prove **template
rank-agnosticism at the prompt layer**, not structured
arbitrary-tensor support. The design claims nothing else, and §6A.2's
"not yet end-to-end compatible" wording governs every statement about
them.

Naming note (2nd-review R2-12): the rungs are `FX-n` precisely because
§4's task-fact IDs are already `F1..F20` — an implementer reading
"F2" must not confuse the rank rung with §4's int8-encoding row.

Deliberate-artefact note (2nd-review R2-6): fixtures 13.4-B/FX-2/FX-5
vary the contract while PINNING the TIDMAD description, so the
captured prompt intentionally carries two disagreeing shape prose
channels. That is a bounded TEST artefact proving the derived blocks
track the declaration — it is NOT a supported profile, and §6A.5
records the missing cross-channel validation as the contract owner's
FX-4 obligation.

### 9.5 Literal survivors — the residue whitelist (2nd-review R2-1, BLOCKER)

The FX-2/FX-5 residue assertions would be UNSATISFIABLE if written
against the whole prompt, because three sources of the forbidden
tokens survive Step 01 **by this design's own decisions**. Each is
listed here with its owner so no implementer "fixes" a scope
violation to make a test green:

| Survivor | Evidence | Why it survives Step 01 | Owner |
|---|---|---|---|
| The shipped `task_description` itself contains `[B, T]` and `[B, 256, T]` | `configs/task_config.yaml:11-14` ("map a noisy `[B, T]` integer signal to a clean `[B, 256, T]` reconstruction") | FX-2/FX-5 hold the description axis FIXED (one-axis rule); after S1-C the JOIN renders that exact string into the stage system prompts | the task profile itself — editing shipped YAML is out of Step-01 scope (and would regenerate CFG-1/CFG-2) |
| The two-output-form catalogue `[B, 256, T]` / `[B, T]` | `proposing_stage.md:69-71`; commit `:330`, `:365-373` | §6.2 rule 2 + §4.1 tier (iii): NO declared regressor form exists in `ForwardContract`, so it is not renderable — it stays literal | step 03 (DQ-3) |
| `render_forward_contract`'s `(per-timestep {N}-class)` descriptor | `workflows/task_config.py:206-212`; shipped in golden `cfg2_forward_contract_block.txt` | production renderer output, byte-pinned by CFG-2 — see §4 row F21 | step 02/03 (§4 row F21) |

Consequently the assertion form is: **derived-block residue == 0**,
plus a POSITIVE assertion that the declared rank-4 text is present.
A whole-prompt residue assertion is explicitly forbidden by this
design.

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
   **Coverage limit (adversarial finding F11, verified)**: the dump
   hook writes ONLY the proposing-stage system prompt
   (`ml_model_proposal_agent.py:1897-1901`). Under OD-S1-3(a) it
   therefore evidences 1 of the 3 JOIN surfaces. This is ACCEPTED
   rather than fixed (adding a dump hook for stages 1-2 is production
   scope creep); the other two surfaces are covered by item 2's
   workflow-tier capture (which records every stage's system prompt at
   the bridge boundary) and by the S1-C unit goldens. The chain
   evidence is a production-entry smoke, not the primary oracle —
   stated so no reviewer over-reads it.

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
| `test_step00_prompt_goldens.py::TestPB4LegacyCommit::test_commit_system_constant` (golden `pb4_legacy_commit_system.txt`) | Step-00 baseline of the commit SYSTEM surface — captured as the raw constant because today constant == render (zero substitution) | legacy | **RETARGET, GOLDEN BYTES UNCHANGED (HARD GATE on content)**: the assert target becomes the RENDERED commit system prompt under the shipped TIDMAD profile; the golden FILE is byte-identical (that is the Stage-A parity claim itself). The sibling `test_commit_user_render` already rendered-layer — KEEP. **CAPTURE LAYER IS MANDATORY (2nd-review R2-4)**: the re-targeted system assert MUST capture at the LLM boundary through the legacy `run()` path (`BoundaryRecorderBridge`, label `proposer.legacy_commit`), NOT by calling a new render helper directly. Source reason: today `test_commit_system_constant` asserts the module constant and `test_commit_user_render` calls `_build_commit_prompt(...)` directly (`test_step00_prompt_goldens.py:381-393`) — the legacy commit surface has NO boundary capture at all, and WF-3's golden covers only the three PIPELINE labels. A direct-helper re-target would leave deletion of the render call at `ml_model_proposal_agent.py:1385` GREEN while a template full of unrendered `{...}` reaches the LLM (hazard §17.5) | The golden IS the parity oracle; keeping it aimed at the constant would force the constant to stay literal forever, defeating the step; re-aiming preserves every byte as the acceptance criterion | M-2: change one rendered token (e.g. ForwardContract.output_shape) → red with a unified diff naming the golden; M-1: delete the placeholder consumer (render call) → red (constant ≠ golden once placeholders exist unrendered) |
| `test_prompt_ceiling_policy.py` — 2 of 7 (`test_vram_limit_requirement_retained` :65-68, `test_capacity_constraints_require_justification_language` :72-81 — presence pins on the CONSTANT via `_all_template_texts()`) | VRAM-mandate language never silently dropped | legacy + templates | **KEEP with capture-layer widening**: these two sentences are proposer-owned FRAMEWORK prose (not task facts — §5 map) and STAY LITERAL in the template, so the pins stay green as-is; if the implementation moves any pinned sentence into a rendered block (not planned), the pin follows to the render in the same commit. The 3 absence pins (mandate regexes, `<10 GB VRAM`) and the rendered-layer twin KEEP unchanged — they are anti-hardcode template pins (roadmap §13.3(b)) | The pinned sentences are budget-DISCIPLINE prose deferring to [HARDWARE CONTEXT], not extractable task facts | n/a (no move planned); if moved: same-commit pin move, M-4 guards reintroduction |
| `tests/unit/agent/test_output_contract_end_to_end.py::test_json_skeletons_request_output_type` (`'"output_type"' in PROPOSAL_COMMIT_PROMPT` + in raw proposing_stage.md) | Both JSON skeletons REQUEST output_type (V21 PR A reachability) | both | **KEEP, layer-verified**: the `"output_type"` key is JSON-skeleton STRUCTURE (proposer-owned framework content), planned to stay literal in both templates; pin stays green. If the skeleton line gains placeholders around it, the token itself remains literal | Skeleton structure is not a task fact; PR A's reachability intent is untouched | n/a; the PR-A allow-list source-count pin (`:287-294`) independently guards the parse side |

### 11.2 Step-00 baselines consumed as HARD GATES (green UNMODIFIED through extraction; §13's R1/R2/R3 govern every declared regeneration)

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
| 3. STAGE-B CONTRAST | the NEW 13.4-A/13.4-B proposer contrast fixtures + (per OD-S1-6(a)) the FX-2/FX-5 rank-agnosticism prose rungs (§9.4) (the owning child PR's own tests — land inside `tests/unit/agent/ml_model_proposal_agent/`) | expected O(seconds) (same fixture machinery as PB-3) | ≤ 1 min |
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
2. **Planned regeneration events — exactly THREE, all declared in
   advance (corrected after adversarial findings F6a/F6b/F13; the
   original "exactly ONE" was contradicted by §8.1a and §14.5 and is
   restated here):**

   | # | Commit | What regenerates | Why it is not silent drift |
   |---|---|---|---|
   | R1 | **S1-A0** (test-only, first) | the affected `pb3_*` goldens, because the PB-3 FIXTURE contract is completed (§8.1a) | fixture-input change declared before any extraction; zero production diff; provenance message + diffs attached |
   | R2 | **S1-C** (the JOIN) | the `pb3_*_system.txt` goldens the JOIN targets (6 under OD-S1-3(a), 1 under (b)); the WF-3 component-key-set golden ONLY IF a new component key appears (it should not — §8.1 WF-3 row) | the sole intentional rendered-byte change, authorized by OD-S1-8 |
   | R3 | **S1-E** (optional, only if OD-S1-2 approves) | a NEW Step-01 golden for the legacy reasoning SYSTEM render must first be CAPTURED (no oracle exists today — §8.1 PB-0 row), then regenerated by the literal deletion in the same commit | otherwise the cleanup edits an unpinned surface; capture-then-edit makes the change reviewable |

   No other golden changes anywhere in the PR. For R2 the commit
   message records
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
## 14. Implementation phases — delegated to the child PR designs

The per-commit 8-section checklists live in the child designs, one PR
per document (operator standard: ONE PR = ONE DOC):

| Child | Commits | Document |
|---|---|---|
| PR 01a | S1-A0 · S1-A · S1-B · 01a-D (contract/rank/loss contrasts + mutations) | [`pr_01a_contract_derived_prompt_extraction.md`](./step_01_proposer_hypothesis_space/pr_01a_contract_derived_prompt_extraction.md) |
| PR 01b | S1-C (JOIN) · FX-1/13.4-A contrast · S1-E budget cleanup · closeout | [`pr_01b_task_description_join.md`](./step_01_proposer_hypothesis_space/pr_01b_task_description_join.md) |

Standing implementation rules (§18.1) apply to both children
unchanged. The shared material each child references rather than
duplicates: the source audit (§3-§5), the target flow (§6), the
flexible-input boundary (§6A), the Stage-A baseline map (§8), the
contrast catalogue (§9), the test-disposition inventory (§11), the
acceptance packs (§12), the golden-update policy (§13) and the
mutation catalogue (§15).

## 15. Validation and mutation plan

Executed as recorded evidence during implementation (mutation applied
locally, red observed, reverted, green re-verified; mutation-proof
hygiene rules apply). Battery (directive-mandated cases instantiated):

| # | Mutation | Expected RED |
|---|---|---|
| M-1 | delete a NEW placeholder consumer: remove `{task_description}` from one stage template (post-JOIN) | JOIN test + the regenerated PB-3 golden for that stage |
| M-1b (2nd-review R2-4) | delete the commit-prompt RENDER CALL at `ml_model_proposal_agent.py:1385` so the placeholder-bearing template is passed verbatim | the re-targeted PB-4 system assert, captured at the legacy `run()` boundary, goes RED (unrendered `{...}` ≠ golden). **This mutation is the acceptance proof that the capture layer was implemented as specified** — if it stays green, the test was wired to a helper instead of the boundary |
| M-2 | change one TIDMAD rendered token: perturb one ForwardContract-derived token in the renderer (e.g. drop the dtype suffix) | PB-4-retargeted golden (S1-A) / PB-3 goldens (S1-B) with unified diff naming the surface |
| M-3 | parser/transport-loss analog: make the loss-legality renderer read an empty iterable (authority disconnected pre-render) | re-targeted contract-reassertion legality pins + rendered legality golden |
| M-4 | reintroduce a hardcoded task fact: paste a literal `256`-token line into the template beside the placeholder | 13.4-B contrast fixture (literal survives the contrast profile) + template-layer absence pin (S1-B) |
| M-5 | one-sided template/profile update: edit a derived-block line in the template without regenerating goldens | PB-3/PB-4 parity golden |
| M-6 | transport loss at the workflow boundary: comment out `propose_input.task_description = …` (model_exploration.py:2290) | workflow-tier JOIN assert (§10.2) |
| M-8 | render-order nondeterminism: shuffle/reverse the source used by the loss-legality renderer (and run the goldens twice in separate processes) | the legality goldens go red on the shuffled source and are byte-identical across two fresh processes on the unshuffled one (§6.2 rule 5) |
| M-9 | empty-contract fail-closed: construct the legacy input with no `forward_contract` (the node-CLI shape) and render the commit prompt | the fail-closed guard raises; a silent empty render is a RED test (§6.2 rule 6) |
| M-7 | alternate-task SQUID-residue check: run 13.4-A and grep the description-derived block for SQUID tokens | 13.4-A itself (this is its steady-state assertion, executed as a mutation-class check once with a deliberately SQUID-contaminated renderer to prove the assert can fire) |

Negative controls: (NC-1) changing a `label=` string reds WF-3 label
asserts, NOT the prompt goldens (separation stays real); (NC-2) an
unrelated template_vars value change (e.g. minimum_boldness fixture
value) does not red the contract goldens; (NC-3) the extraction
commits re-run PB-3/PB-4 twice with byte-identical verdicts.

### 15.1 Flexible-input mutations (added 2026-08-12)

| ID | Mutation | Expected |
|---|---|---|
| **N-RANK** | add a rank/axis branch to any Step-01 renderer (e.g. `if "T]" in fc.output_shape:` or a `task_type == "classification"` code path selecting different prose) | **named failing assertion** (2nd-review R2-7): the FX-2 rung's POSITIVE assertion — "the declared rank-4 text and the unfamiliar `task_type` label render verbatim" — goes RED, because any such branch emits the non-declared alternative for a contract it does not recognise. If a candidate branch can be added WITHOUT reddening FX-2, that proves the rung is too weak and the rung must be strengthened, not the mutation excused |
| **N-RESIDUE** | after extraction, reintroduce one hardcoded `[B, 256, T]` (or "256 amplitude bins") into a generic template while the contrast profile is active | FX-2/FX-5 contrast fixtures go red on the residue assertion (scoped to the derived blocks, §9.5); the TIDMAD golden stays green — proving the fixtures catch shadow literals that parity alone cannot |
| **N-OPAQUE** | make a renderer read `task_type` to choose a branch instead of rendering it as an opaque label | violates the field's own schema docstring (`agent/schemas/task_config.py:86-92`, "consumers should treat unknown values as opaque labels") and §6A.4; RED on FX-2, whose profile now explicitly carries an unfamiliar `task_type` that must render verbatim (§9.4) |

## 16. Checkpoints instantiated (roadmap §17)

| Checkpoint | Owner (child PR) | Instantiation | Status |
|---|---|---|---|
| 0 BASELINE AVAILABLE | **PR 01a** | PB-0/PB-3/PB-4, WF-3, CFG-1/2/3a/3b landed on MASTER (PR #198) and green in this worktree (526 passed, 2.3 s); PB-0's true surface corrected per §8.1 | **MET** |
| A EXTRACTION PARITY (exact — the OD-S1-8 exception now lives in PR 01b, NOT here) | **PR 01a** | §8: every extraction commit leaves all named goldens byte-identical; the three regeneration events are declared in advance (§13 R1/R2/R3) and no other golden moves; boundary kwargs (labels/components) unchanged | design |
| B GENERIC CONTRAST | **PR 01a** (contract/rank/loss rungs) + **PR 01b** (FX-1 description rung) | §9: the roadmap rungs 13.4-A + 13.4-B (landed as same-axis B-i/B-ii) plus the operator's FX-2/FX-5 prose rungs — one axis per fixture; FX-3/FX-4 DEFERRED with a named owner | design |
| C LIVE INTEGRATION | **PR 01b** (PRE-MERGE, on its final head) | §10: real production pipeline path in-PR (unit + pseudo workflow tier) + the bounded pseudo chain iteration (OD-S1-4), which runs **PRE-MERGE on PR 01b's final executable head**, never post-merge; the :1597 seam is WIRED — no consumer-less seam survives | design |
| D REGRESSION | **each child on its own final head** | §12 pack 5 at the final head from a clean tree + §15 battery dossier + CI green on the exact head | design |
| E ROADMAP SYNC | **PR 01b** (aggregate) | roadmap §15.1 row 6-P updated in the same PR or an immediately-merged docs follow-up BEFORE the step-02 PR opens; folder README row + this doc's Status updated | design |


**Split consequence (operator decision 2026-08-12).** Checkpoint A is
closed by PR 01a with ZERO golden diff — the roadmap A-cell is
satisfied exactly there. The A-cell exception (OD-S1-8) applies ONLY
to PR 01b, whose declared regeneration is its acceptance evidence.
Nothing in PR 01a may regenerate a golden.

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
4. **Step-00 dependency risk — CLOSED 2026-08-12**: Step 00 merged
   (`e80da078`) and this branch is synchronized onto that master;
   §8.1's map was re-verified artifact-by-artifact on master and the
   consuming suites re-run green here. No open dependency remains.
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

## 19. Operator decisions — FINAL STATES (operator, 2026-08-12)

All eight are now decided except OD-S1-5 (freeze), which awaits this
reconciliation. The original option analyses are preserved below the
verdict table.

| ID | Operator verdict |
|---|---|
| OD-S1-1 | **APPROVED (a)** — forbidden-pattern extraction DEFERRED to step 04 / 6-M with the validator surfaces. |
| OD-S1-2 | **APPROVED** — delete the stale "~100M" / "10 GB" literals, but in **PR 01b** as an isolated capture-first semantic commit. |
| OD-S1-3 | **APPROVED (a)** — the task background reaches ALL THREE pipeline stages. |
| OD-S1-4 | **APPROVED (a) WITH CORRECTION** — bounded `--is_pseudo_llm` production-entry iteration, and it is **PRE-MERGE on PR 01b's final executable head**, required before READY FOR OPERATOR REVIEW. Every "post-merge chain evidence" formulation is superseded. |
| OD-S1-5 | **APPROVED (2026-08-12)** — design FROZEN; **PR 01a implementation authorized**. PR 01b stays blocked on PR 01a merge. Implementation branch: `feat/generic-framework-step-01a-contract-derived-prompt-extraction`, cut from master `9400ec73`. |
| OD-S1-6 | **APPROVED (a)** — flexible-input Outcome B; FX-2/FX-5 prose rungs land in **PR 01a**; FX-3/FX-4 remain binding dependencies on step 02/03. |
| OD-S1-7 | **APPROVED (a)** — reject inventing a dtype-stripping formatting rule in Step 01; tier-(ii) literals stay and route to step 03. |
| OD-S1-8 | **AUTHORIZED, ISOLATED** — the JOIN's A-cell exception is granted, but confined to **PR 01b**; PR 01a remains exact-parity. |

### 19.1 Original option analyses (preserved)

| ID | Question | Options | Recommendation |
|---|---|---|---|

| ID | Question | Options | Recommendation |
|---|---|---|---|
| OD-S1-1 | **Forbidden-pattern lists**: the frozen roadmap's step-1 line names them, but the source audit shows the surface is validator-owned end-to-end (`forbidden_pattern_skill.py`; consumers `ml_code_validator_agent.py:51,:534`; ZERO proposer prose; the proposer's [DISALLOWED PATTERNS] block already renders from `ARCHITECTURAL_PATTERNS` — a live, correct seam) | (a) DEFER to 6-M step 04 with the validator surfaces (roadmap line recorded as pre-audit assumption); (b) extract the skill's list to config now with the validator as consumer (crosses into 6-M scope) | **(a) DEFER** — extracting a validator-consumed list is 6-M work by the roadmap's own 6-P/6-M split; doing it here would broaden 6-P exactly the way the directive forbids |
| OD-S1-2 | **Stale budget literals** ("~100M" PROPOSAL_REASONING_PROMPT:284; "10 GB" causal_reasoning_stage.md:146): roadmap §14 already RESOLVED the semantics (derive from [HARDWARE CONTEXT]; delete stale literals) but proposer templates have NO later owner (step 04's prompt scope excludes proposer surfaces) | (a) include optional commit S1-E (isolated, golden-regenerating, clearly labeled); (b) defer and accept an ownership gap | **(a) INCLUDE S1-E** — otherwise the two literals become permanently unowned; the commit is isolated and skippable |
| OD-S1-3 | **JOIN placement**: which stage system prompts render the task-background block | (a) all three stages (comparison/causal currently task-blind — they choose the architecture family); (b) proposing stage only (minimal byte change) | **(a) all three** — the step's final effect is about the HYPOTHESIS SPACE, which is formed in stages 1-2; (b) would satisfy the letter of the JOIN while leaving the deciding stages task-blind |
| OD-S1-4 | **Checkpoint-C chain evidence form** (roadmap C cell says "a real chain iteration"; §17 exempts prompt extractions from real Gates) | (a) bounded `--is_pseudo_llm` production-entry iteration with prompt dump, log attached (no API cost); (b) one real-LLM bounded iteration; (c) unit+pseudo-workflow evidence only | **(a)** — exercises the production entry + real renders at zero API cost; (b) adds LLM nondeterminism and cost without adding parity evidence |
| OD-S1-5 | **Design freeze** after Step-00 merge + re-sync: confirm the §8.1 baseline map against master and authorize implementation | — | freeze only after the §Status preconditions are all TRUE |
| OD-S1-6 | **Flexible-input scope (new, operator requirement 2026-08-12)**: §6A.1 proves the contract is prose-only end-to-end and §6A.5 freezes Outcome B (preset/tensor validation belongs to step 02/03) | (a) accept Outcome B and land the FX-2/FX-5 PROSE contrast rungs in commit S1-D (they are the only tests that actually prove template rank-agnosticism, and cost one extra profile fixture each); (b) accept Outcome B but land no flexible-input rungs (13.4-A/B only); (c) reject Outcome B and require a structured tensor contract inside Step 01 | **(a)** — Outcome B is source-forced (nothing structured exists to validate; building it seizes step-02/03 ownership), and the two prose rungs are cheap, atomic and are the difference between *claiming* rank-agnosticism and *proving* it. (c) would make Step 01 the Dataset/Model-contract owner, contradicting the frozen 6-P/6-M split |
| OD-S1-7 | **Tier-(ii) shape formatting rule (adversarial finding F4)**: the commit prompt and proposing template state the output shape in dtype-stripped/backticked forms that `output_shape` cannot produce by verbatim insertion | (a) REJECT for Step 01 — those sites stay literal, recorded as step-03 convergence candidates; (b) APPROVE one explicit, unit-tested formatting rule ("drop the trailing dtype word") and extract them too | **(a) REJECT** — the rule is a decision about the contract's surface forms, which §5 owns; §4.1 already names and routes every retained literal, so nothing goes unexamined |
| OD-S1-8 | **A-cell exception for the JOIN (adversarial finding F14)**: the roadmap A-cell says all three proposer stages render EXACT-equal for TIDMAD, and the JOIN deliberately changes those bytes | (a) AUTHORIZE the declared, contained exception (§8 header: one commit, declared golden set, §13-governed, diffs attached), on the authority of Step-00 §15.2's JOIN assignment + roadmap §0 rule 8 / §13.2 / §17-C; (b) REFUSE — move the JOIN out of Step 01 (then §1 effect 2, fixture 13.4-A/F1 and Checkpoint C must be re-planned) | **(a) AUTHORIZE** — Step-00 §15.2 is the later, more specific authority and explicitly calls the JOIN "step 01's own A-work"; without it 13.4-A is unsatisfiable and the named dead seam survives the step meant to fix it. It must nonetheless be an explicit operator grant, not a design-side reinterpretation |

## 19A. Adversarial design review record (2026-08-12)

A fresh read-only reviewer attacked the draft (`fd9bfea6`) against the
frozen roadmap, the merged Step-00 design and the actual source, with
source re-opened per criticism; **every load-bearing finding was
independently re-verified by the main auditor before reconciliation**
(frozenset order measured across three fresh interpreter processes;
PB-3 fixture read at `test_step00_prompt_goldens.py:153-166`; PB-0's
owner read at `test_health_prompt_parity.py:27,:36`; the node CLI's
input construction read at `ml_model_proposal_agent.py:2163-2170`).

| # | Finding | Verdict | Reconciliation |
|---|---|---|---|
| F1 | §3.4's per-template placeholder inventory was wrong and contradicted §4 | CONFIRMED | §3.4 rewritten from grep (committed earlier as `ac5581b4`) |
| F4 | §4 said EXTRACT-RENDER for commit `:330/:332/:365-370` while §6.2 said the two-output catalogue stays literal — the same bytes; and ≥4 incompatible surface forms make verbatim insertion impossible; no declared regressor form exists | CONFIRMED (most serious) | new **§4.1** per-site tier split (i/ii/iii); §1 scope honesty paragraph; **OD-S1-7** raised |
| F4b | §6.2 authorised "membership listing" from frozensets with no ordering rule — iteration order varies per process, which would make every legality golden flaky | CONFIRMED (verified: 3 processes, 3 orders) | **§6.2 rule 5** (sorted() for legality, `Literal.__args__` for the alphabet, both pinned) + mutation **M-8**; byte-parity consequence recorded |
| F6a | PB-0 misidentified: its proposer member pins the legacy **USER** prompt; the legacy SYSTEM prompt has NO golden, so S1-E would edit an unpinned surface | CONFIRMED | §8.1 PB-0 row corrected; §13 **R3** = capture-then-edit; §14.5 plan gains the capture step |
| F6b | The landed PB-3 fixture leaves `num_classes=0` / `task_type` empty, so S1-B's "9 goldens unmodified" was unachievable | CONFIRMED | new **§8.1a** + new prerequisite commit **S1-A0** (test-only) + regeneration **R1**; S1-B goal/criteria rewritten |
| F7 | §9.2 fused a regressor contract (`num_classes=0` by schema) with a 16-class classifier into one "fixture" — a multi-axis conflation | CONFIRMED | §9.2 split into same-axis rungs **B-i** (roadmap's named regressor fixture) and **B-ii** (16-class classifier); §9.3 ladder note reconciled |
| F8 | §7 criterion 6 was fallacious (a pre-existing dead key is not a state the split creates) | CONFIRMED | criterion 6 restated as evidence-locality; explicit counter-argument recorded that the JOIN IS an independently reviewable unit |
| F9 | After extraction, an empty ForwardContract would silently strip the I/O contract from the commit prompt on the production-reachable node-CLI path | CONFIRMED | **§6.2 rule 6** fail-closed requirement + mutation **M-9**; recorded as a behavioral change, not "regime-A parity" |
| F11 | The chain-evidence dump hook covers only the proposing stage — 1 of 3 JOIN surfaces under OD-S1-3(a) | CONFIRMED | §10.3 coverage-limit paragraph: accepted, not fixed; workflow-tier capture covers the rest |
| F12 | N10 forbids prompt-wording changes while S1-E performs one; and the A-cell's "TIDMAD proposals unchanged" was silently re-read | CONFIRMED | N10 gains a single declared carve-out; §8 header names the narrowing explicitly |
| F13 | Four bad citations; §13 rule 2 ("exactly ONE regeneration") contradicted by §8.1a/§14.5; §14.3's "ONLY commit" claim; §9.1 presupposed OD-S1-3(a) | CONFIRMED | all four citations fixed; §13 rule 2 replaced by the **three-declared-events table (R1/R2/R3)**; §14.3 boundary scoped to "mandatory scope"; §9.1 made outcome-conditional |
| F14 | The JOIN breaks the A-cell's EXACT-equality text and no OD asked the operator to authorize the deviation | CONFIRMED | §8 header now states the exception, cites permitting vs excepted authorities, and **OD-S1-8** raises it for explicit grant |
| 1,2,3,5,10,11,12 (partial) | production-path audit, authorities, runtime-state discipline, seam wiring, pack sizes, live-integration machinery, no step-02/04 smuggling | CLEARED (with the nits folded in above) | pack-1 count re-measured 861/861; `--is_pseudo_llm`, the dump hook and all pack-4 targets verified present |

Reviewer's own scope note: the review ran against the pre-sync draft,
so its §Status/§8.1 dependency observations were already superseded by
the post-merge sync (`f30ef9be`); its source-grounded findings above
are unaffected and were reconciled in full. No finding was dismissed
without source evidence, and no finding was manufactured.

## 19B. Second adversarial review record (post-sync, 2026-08-12)

A SECOND fresh read-only reviewer ran against the post-sync document
(including the new §6A/§9.4 material, which the first review never
saw). Because it started while the first agent's own reconciliation
pass was still landing, four of its findings were already fixed in the
tree when it reported; the main agent re-verified every finding
against source at the CURRENT head before accepting or rejecting it.

| # | Finding | Verdict (main-agent source check) | Reconciliation |
|---|---|---|---|
| R2-1 | **BLOCKER** — the FX-2/FX-5 "zero residue" assertions are unsatisfiable as written: the shipped `task_description` itself contains `[B, T]`/`[B, 256, T]`, the two-output catalogue stays literal by §6.2 rule 2, and the renderer emits `per-timestep` | **CONFIRMED** (`configs/task_config.yaml:11-14` read directly) | assertions rescoped to CONTRACT-DERIVED blocks; new **§9.5 whitelist** of the three survivors with owners; §1 item 5 over-claim corrected; §14.4 checklist rewritten |
| R2-2 | **MAJOR** — `render_forward_contract` emits `(per-timestep {N}-class)`: a temporal assertion from PRODUCTION CODE branching on a structured field; no §4/§5 row covered it | **CONFIRMED** (`workflows/task_config.py:206-212`; golden `cfg2_forward_contract_block.txt` ends "Task type: classification (per-timestep 256-class).") | new §4 row **F21** (KEEP byte-identical, whitelisted, routed to step 02/03 as defect-not-blessed); §6A.1's "Consequence" corrected; §6A.4 grandfathers the pre-existing `if fc.num_classes:` branch explicitly |
| R2-3 | MAJOR — §4 row F1/F3 says EXTRACT-RENDER for a family §6.2 keeps literal | **REJECTED — already fixed** before the review reported: the row reads "**SPLIT PER SITE** — see §4.1" (first review's F4) | none needed |
| R2-4 | **MAJOR** — the PB-4 re-target's capture layer is unspecified, so the natural implementation leaves the `:1385` render call unguarded while M-1 still reports green | **CONFIRMED** (`test_step00_prompt_goldens.py:381-393`: constant assert + direct helper call; no boundary capture; WF-3 covers pipeline labels only) | §11.1 PB-4 row now MANDATES boundary capture through the legacy `run()` path; new mutation **M-1b** makes that the acceptance proof |
| R2-5 | MAJOR — the JOIN breaks the A-cell without an operator grant | **REJECTED — already fixed**: **OD-S1-8** exists and asks exactly that (first review's F14) | none needed |
| R2-6 | **MAJOR** — the JOIN opens a second, unvalidated shape-prose channel (description vs contract), which §6A.5's own rule forbids | **CONFIRMED** | §6A.5's binding dependency now names description↔contract consistency as part of the contract owner's FX-4 obligation; §9.4 records the fixtures' contradiction as a bounded, deliberate test artefact |
| R2-7 | MINOR — N-RANK/N-OPAQUE had no real expected-RED ("the reviewer must catch it"); FX-2 never specified the unfamiliar `task_type` the N-OPAQUE claim relies on | **CONFIRMED** | FX-2's profile now carries an unfamiliar `task_type` with a verbatim-render assertion; both mutations restated against named failing assertions, with the "if it stays green, strengthen the rung" rule |
| R2-8 | MINOR — 13.4-B fuses a regressor contract with `num_classes=16` | **REJECTED — already fixed**: §9.2 is split into same-axis rungs B-i/B-ii (first review's F7) | none needed |
| R2-9 | MINOR — §6A.6's "what fails closed today" reads as completeness | **CONFIRMED** (omitted keys validate via defaults; `ml_model_implementor.py:980` silently substitutes `"[B, C, T] float32"`) | §6A.6 gains an explicit "what does NOT fail closed" bullet with owners |
| R2-10 | MINOR — post-merge staleness (Checkpoint 0, risk 4) | **PARTIALLY CONFIRMED**: Checkpoint 0 already read MET; risk 4 was still stale | risk 4 converted to CLOSED with the merge SHA |
| R2-11 | MINOR — S1-E's plan is "[ ] per inspection" | **REJECTED — already fixed**: S1-E carries a CAPTURE-FIRST plan (first review's F6a) | none needed |
| R2-12 | MINOR — `F1..F5` rung IDs collide with §4's `F1..F20` fact IDs | **CONFIRMED** | rungs renamed **FX-1..FX-5** throughout §9.4/§14.4/§15.1 with a naming note |
| R2-13 | NIT — cross-reference hygiene (§10.2, §0.8, `run_one_iteration.py` path, OD ordering, F19 gap) | ACCEPTED as editorial | folded into this pass where unambiguous; the F19 gap is external audit numbering and is left, now explained here |

Cleared by the second review with source evidence: no Step-04
smuggling; no roadmap line silently dropped; **no code anywhere parses
a shape string** (independently re-verified); no premature tensor
schema; presets role-based and non-API; every cited Step-00 baseline
present on master and green (526 passed); pack-1 re-measured at
861 tests / 3.0 s; no consumer-less seam; no half-enabled commit state.

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
