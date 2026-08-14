# PR 04b — Task description single source — detailed design (child)

Parent: [`../step_04_candidate_creation_mechanics.md`](../step_04_candidate_creation_mechanics.md)

| Field | Value |
|---|---|
| Design base | **`e7e1cae5`** — current master, i.e. POST-04a (04a merged as `6458dd95`). Re-scoped from that state; the pre-04a draft's base `e802b810` is superseded |
| Depends on | the **§13 task-profile authority**. **Independent of 04a** — re-verified against merged 04a source (§0.2) |
| Status | **IMPLEMENTED — PR [#209](https://github.com/Galileo-Sandbox/SIDERIUS/pull/209) open, READY FOR OPERATOR REVIEW, NOT merged.** Design frozen at `4282112a` (revision 2, re-scoped post-04a); implemented from freeze marker `aa84f24d` in `4c35adfe` + `37806eed`. Implementation ledger: §14. |
| Revision 2 changes | two premises of revision 1 were falsified by source audit (§0.1); scope shrank; per-commit checklists added (§15) |
| Frozen contract | §1 capability (and its explicit NOT-claimed boundary) · §5 Stage-A `pb9_*` exact parity · §6 the single 13.4-A rung · §7 deterministic production-path Checkpoint C · §10 Gate disposition and flip conditions · §12 rollback boundary · §0.4 the static-description deferral |
| NOT frozen | exact Git commit count, helper structure, source line numbers, test-file decomposition (§15) |

---

## 0. Revision-2 source audit (post-04a master `e7e1cae5`)

Revision 1 was written against `e802b810`. Re-auditing at current master
falsified **two** of its premises and shrank the scope. Both are recorded
rather than silently rewritten.

### 0.1 Falsified premises

```text
Previous assumption (rev 1 §2):
  "lit_review_config.yaml:44-47 documents a further fallback to a default
   constant in agent/prompt_templates/literature_review/__init__.py …
   So one task fact currently has up to THREE sources."

Audit evidence:
  workflows/model_exploration.py:607 states verbatim:
    "Post-Commit-F: there is no SIDERIUS_TASK fallback — an empty value
     flows through as '' to the {TASK_DESCRIPTION} prompt placeholder."
  `grep -rn "SIDERIUS_TASK" --include=*.py .` returns exactly that one
  comment. The constant does not exist.

Corrected understanding:
  There are TWO sources, not three. The fallback was already removed.

Implementation consequence:
  Rev 1 scope item 2 ("resolve the fallback-constant precedence") is
  DELETED — there is nothing to resolve. What survives is far smaller: the
  YAML's own comment block still DESCRIBES the removed fallback, so the
  config lies about its own behaviour. That is a comment fix, not a
  precedence design.
```

```text
Previous assumption (rev 1):
  collapsing the duplicate needs a new resolution path for lit review.

Audit evidence:
  workflows/model_exploration.py:2112 ALREADY does exactly this for the
  interpreter:
      task_description=get_task_description(load_task_config())
  (T4b, docs/design/enable_global_task_config.md § Commit T4).
  `_build_lit_review_input` at :613 instead reads
      config.get("task_description", "")
  from the lit-review YAML.

Corrected understanding:
  The single-source accessor already exists, is already imported in this
  very module (:116), and is already used by a sibling consumer. The
  collapse is switching ONE call site onto an established mechanism.

Implementation consequence:
  No new prompt-assembly layer, no new helper, no new schema field.
```

### 0.2 Independence from 04a — re-verified against merged source

04a changed `ImplementorOutput` / `ValidatorInput` (a `model_io_contract`
field), added `agent/skills/model_io_probe_skill.py`, added
`HardwareContext.effective_cap_gb`, and put placeholders in the implementor
and validator prompt templates (04a ledger §17.11.2).

**None of those surfaces is touched by 04b**, whose entire footprint is the
lit-review input construction plus two config files. `ml_models/model_descriptions.py`
remains owned by neither PR. Independence therefore still holds on merged
evidence, not on the pre-04a assumption.

### 0.3 The empty-value failure class is already closed upstream

`workflows/task_config.load_task_config` *"already strips and rejects
empty"* (`workflows/task_config.py`, `get_task_description` docstring), so a
lit review sourced from it cannot silently render a bare
`{TASK_DESCRIPTION}`. The rev-1 warning path at
`model_exploration.py:614-622` becomes unreachable for the canonical loader
and is replaced by that upstream rejection — a strictly stronger guarantee
than a printed warning.

### 0.4 Static builtin model-description task prose — AUDIT SAYS DEFER

Rev 1 made this conditional on *"a live consumer exists in this PR"*.
Audited: `ml_models/model_descriptions.py` is a whole-file loader — it reads
`ml_models/{model_type}/description.md` and returns its text. There is **no
task-block seam** in it and no consumer that would render one, so creating
one in 04b would be a consumer-less seam (roadmap §0 rule 8).

**Disposition: DEFERRED, with the finding recorded.** Two of the six builtin
descriptions (`punet`, `gated_fno`) do contain SQUID/axion task prose; that
remains true and remains duplication, but fixing it needs a consumer that
does not exist yet. 04b does not invent one.

**Consequence: 04b is now a TWO-commit PR** (§15), not three.

---

## 1. Capability / final effect

> There is **ONE canonical runtime declaration** of `task_description`
> — the §13 task profile (`configs/task_config.yaml`) — and the
> **production lit-review node consumes that declaration** instead of
> maintaining a byte-duplicated copy in `configs/lit_review_config.yaml`.

Today the lit-review node reads its own copy, and nothing detects
divergence between the two.

**Deliberately NOT claimed** (the boundary of this PR, frozen):

- **not** "all task-specific prose in the repository is single-sourced";
- **not** that static builtin model descriptions are migrated — the
  `punet` / `gated_fno` SQUID/axion prose in
  `ml_models/{model_type}/description.md` stays **DEFERRED** (§0.4);
- **not** that changing the task *globally* now requires editing one
  file. It requires editing one file for the **runtime** declaration
  every LLM node renders; the deferred static prose is a separate,
  still-duplicated surface.

The honest scope is one authority for one runtime value, with one
consumer migrated onto it.

## 2. Source evidence

`configs/task_config.yaml:10` and `configs/lit_review_config.yaml:48`
each declare a `task_description:` block. Audited at `e802b810`, they
are **byte-identical**:

```text
full-spectrum 1-D time-series denoising of SQUID dark-matter
detector data: map a noisy [B, T] integer signal to a clean
[B, 256, T] reconstruction, trained across the whole frequency
spectrum at once (not split into per-band models).
```

`lit_review_config.yaml:44-47` still *documents* a fallback to a
`SIDERIUS_TASK` constant — **but that constant no longer exists** (§0.1).
So there are **TWO** sources, plus a config comment describing a mechanism
that was already deleted. Roadmap §13.1's phrasing (*"duplicate byte-equal
task description … + stale SIDERIUS_TASK fallback prose"*) is now half
historical: the duplicate is real, the fallback prose survives only as a
stale comment.

## 3. Scope

1. Collapse the duplicate: `lit_review_config.yaml` stops declaring
   `task_description`; `_build_lit_review_input` resolves it from the
   single task profile via the **already-used** accessor
   `get_task_description(load_task_config())` (§0.1).
2. ~~Resolve the fallback-constant precedence~~ — **DELETED in revision 2**;
   the fallback does not exist (§0.1). What remains is deleting the stale
   YAML comment that still describes it.
3. ~~**Static builtin model-description task content**~~ — **DEFERRED in
   revision 2** (§0.4): no live consumer for a task-block seam. Context
   retained below for the deferral record. The checked-in
   `ml_models/{model_type}/description.md` files. Enumerated at design
   time: **6 files** (`wavenet`, `punet`, `rnn`, `transformer`,
   `fcnet`, `gated_fno`), of which **2 carry SQUID/axion task prose**
   (`punet`, `gated_fno`). Those two get a task-block seam **only if a
   live consumer exists in this PR**; a seam without a consumer is
   deferred, not invented.

   **This is NOT the implementor-generated candidate description
   artifact** (`agent_generated/models/{model_name}/description.md`,
   written by `ml_model_implementor.py:1776-1796`) — that surface is
   **04a's**. `ml_models/model_descriptions.py` is the shared *loader*
   and is changed by **neither** PR. Different files, different
   producers: this is why the two-PR split is independent (parent
   §2.3.1).

### Non-goals

- No change to lit-review *format* doctrine, search strategy, or paper
  corpus — those are module-owned, not task-owned.
- No new prompt-assembly layer; extend the existing single-template +
  placeholder mechanism (roadmap §13.2).
- No planner/reflector/interpretation prose (Steps 07a/09).
- Nothing from 04a.

## 4. First production consumer

The production lit-review node, which renders `task_description` into
its search/extract/synthesis prompts.

## 5. Stage-A parity

| Surface | Criterion |
|---|---|
| `pb9_*` lit-review goldens (10) | **EXACT byte equality** |
| kwargs reaching `LLMBridge` | unchanged |

Because the two sources are byte-identical today, collapsing them must
be a **provable no-op** on rendered output. If any `pb9_*` byte moves,
that is a defect in the collapse — not a golden to update.

## 6. Stage-B atomic rung

| Rung | Varies ONLY | Reds when |
|---|---|---|
| **13.4-A (lit-review half)** | the task-description text | the lit-review node still renders the old text from its own config — i.e. the duplicate is still authoritative |

Step 01 landed 13.4-A for the proposer group; this is the remaining
lit-review half. Residue assertions stay **scoped to the
description-derived block** (parent §6) — a whole-prompt absence
assertion is unsatisfiable and would be a test-design error.

## 7. Checkpoint C — deterministic production-path integration

**No real LLM call is required.** Gate 1 and Gate 2 are both NOT REQUIRED
(§10), and requiring a paid chain iteration merely to observe a
byte-neutral single-source refactor would buy no evidence a deterministic
capture cannot give.

Checkpoint C is discharged by driving the **real production path** to a
capture boundary:

```text
canonical §13 task config
  -> real production `_build_lit_review_input`
  -> real lit-review rendering / RecordingLLMBridge capture boundary
  -> captured task-description block
```

Every hop is production code; only the LLM boundary is a recorder.

**The proof uses a distinguishable alternate task-description fixture**:
point the canonical §13 source at a sentinel description and assert the
captured block carries *that* text. Asserting the shipped TIDMAD text
would pass even if the lit-review YAML were still authoritative, since
the two are byte-identical today — the whole defect this PR removes.

Under TIDMAD, all `pb9_*` rendered bytes remain **exact** (§5).

**Flip**: only if implementation unexpectedly moves an LLM-visible byte
or changes `LLMBridge` invocation semantics does the Gate standard's
Gate-1 trigger apply, at which point Checkpoint C is re-planned with it.

## 8. Failure classes

1. Divergence returns silently — a second declaration reappears and
   nothing detects it.
2. **A fallback is re-introduced, or the canonical fail-closed is
   swallowed.** The old `SIDERIUS_TASK` constant no longer exists (§0.1),
   so the live risk is not that constant but the *shape* of it: adding an
   implicit default, an `or "…"`, or a `try/except` around
   `load_task_config`'s empty-rejection would mask a missing canonical
   task description and quietly restore silent-degradation behaviour.
3. A rendered lit-review byte changes (would break `pb9_*` parity).
4. Format doctrine accidentally reclassified as task content.

A guard that fails when a second `task_description` source reappears is
the highest-value test here — it names a defect nothing else catches.

## 9. Test disposition

| Test | Verdict |
|---|---|
| `test_agent_card_task_config.py` | **UPGRADE** to the single source |
| `test_step00_prompt_goldens.py` (pb9) | **KEEP** — the parity oracle |
| pins asserting `lit_review_config.yaml` carries its own description | **REWRITE** — they defend the duplicate |

## 10. Gates

| Gate | Decision |
|---|---|
| **Gate 1** | **NOT REQUIRED** — TIDMAD rendered lit-review bytes and `LLMBridge` invocation semantics both remain **exact**. **Flip**: if either changes, Gate 1 becomes REQUIRED |
| **Gate 2** | **NOT REQUIRED** — the PR changes only the **authority/source** of an already-existing `task_description` value feeding lit-review prompt construction. It does not alter model execution, training, inference, scoring, resource/runtime semantics, or any downstream executable contract. **Flip**: if scope expands into those surfaces |

**Note on the Gate-2 rationale.** An earlier revision said *"no
execution-path change"*, which was inaccurate: 04b **does** change a
production input-construction call site
(`_build_lit_review_input`). The correct reason Gate 2 is not required is
narrower and stated above — what changes is where an existing value comes
from, not what the system then executes with it.

## 11. Validation budget

The `pb9_*` goldens, the 13.4-A rung, the duplicate-source guard, and
exact-head CI. Deliberately small — this PR's risk is concentrated in
one property (rendered bytes unchanged) that an existing oracle already
measures.

## 12. Rollback boundary

| Surface | Change |
|---|---|
| `configs/lit_review_config.yaml` | the `task_description:` declaration is removed; its stale comment block corrected |
| `workflows/model_exploration.py` | `_build_lit_review_input` reads the canonical source |
| directly affected tests / docs | guard + upgraded pins |

**`configs/task_config.yaml` is NOT modified** — it is the unchanged
authority this PR migrates a consumer *onto*. Exactly **one** config file
changes, not two.

Reverting restores the duplicate and nothing else. Independent of 04a.

## 13. Stop conditions

- The fallback-constant precedence turns out to encode a real operator
  behaviour rather than stale prose → surface it, do not silently
  delete.
- The static builtin model-description task content has no live
  consumer → defer it rather than create consumer-less seams.
- Any need to touch `ml_model_implementor.py`'s generated description
  path, or `ml_models/model_descriptions.py` → **STOP**: that would
  break the independence this split rests on (parent §2.3.1).
- Any `pb9_*` byte change that cannot be shown to be a defect in the
  collapse → STOP and surface as an operator decision.

## 13.1 Operator decisions

`OD-S4-2` (TWO PRs, `04a → 04b`) is **APPROVED**, with independence
re-verified against source after the description-surface clarification.
`OD-S4-1`, `OD-S4-3` and `OD-S4-4` do not touch this PR (no `pb5_*`
golden, no plugin corpus, no convergence surface here).

**Remaining operator questions for 04b: NONE.**

## 14. Implementation ledger

**Implementation authorized 2026-08-14.** Branch
`feat/generic-framework-step-04b-task-description-single-source`, cut from the
freeze marker `aa84f24d` (= `origin/master` at kickoff, verified; frozen design
content `4282112a` present in ancestry; tree clean).

### 14.1 Pre-edit source confirmation

Every premise the frozen design rests on was re-verified at `aa84f24d` before
any edit. All held:

| Premise (design §) | Verified at | Result |
|---|---|---|
| `configs/task_config.yaml` declares the canonical description | `:10` | CONFIRMED |
| `configs/lit_review_config.yaml` declares a duplicate | `:48` | CONFIRMED, byte-identical |
| `_build_lit_review_input` reads the duplicate | `model_exploration.py:613` | CONFIRMED |
| the canonical accessor exists and is imported in that module | `:116` | CONFIRMED |
| a sibling production consumer already uses it | `:2112` (interpreter) | CONFIRMED — and three more: `:2297` proposer, `:2397` implementor, `:2668` tuner |
| no `SIDERIUS_TASK` constant exists (§0.1) | `grep` | CONFIRMED — two textual mentions only, both descriptive |
| `load_task_config` rejects empty upstream (§0.3) | `task_config.py:139-145` | CONFIRMED |

Pre-edit baseline: `tests/unit/agent/ml_literature_review tests/unit/workflows`
— **327 passed**, 22.28 s, exit 0.

### 14.2 Deviation D-04b-1 — a second reader the design did not anticipate

```text
Previous assumption (§15 C1 step 5):
  the grep for other readers of the lit-review YAML's task_description
  would come back empty.

Audit evidence:
  scripts/checkpoint_s_runner.py reads it TWICE — at :118, inside a
  `_build_input` helper whose own docstring says it "Mirrors
  workflows.model_exploration._build_lit_review_input but inlined here so
  the script has no workflow dependency", and at :296 in a startup summary
  print.

Corrected understanding:
  Deleting the YAML key without touching this script would have left the
  mirror silently passing "" as the task anchor to real DeepSeek calls —
  precisely the silent-degradation shape of failure class 2 (§8).

Implementation consequence:
  The mirror follows production onto the SAME canonical accessor. This
  introduces no new authority, no fallback and no precedence rule — it is
  the identical `get_task_description(load_task_config())` call the design
  already prescribes. Scope impact is one tracked script, within §12's
  "directly affected" surface.

Validation consequence:
  Covered by the C2 declaration guard (which forbids the key returning) and
  by ruff/pyright over the edited script. The script itself is not
  executable in CI — it needs an operator-specific seed path and real
  DeepSeek + S2 quota — so no test runs it; this is recorded as the reason,
  not hidden.
```

### 14.3 Deviation D-04b-2 — `test_agent_card_task_config.py` needs no upgrade

```text
Previous assumption (§9):
  test_agent_card_task_config.py is UPGRADED to the single source.

Audit evidence:
  Read in full (103 lines). Every test in it asserts properties of the
  static `_AGENT_CARD` object in nodes/ml_literature_review — that T4c
  stripped SQUID/denoising wording from `role`/`expertise_domain`/
  `limitations`, that AgentCard max_length constraints still hold, and that
  the card round-trips through Pydantic. It never loads either YAML, never
  calls the accessor, and never asserts where a description comes from.

Corrected understanding:
  The §9 verdict was assigned from the file's NAME. Its body has no
  coupling to the duplicate, so there is nothing in it to upgrade: it is
  already source-neutral and it still names a defect only it can catch
  (task prose creeping back into the static agent card).

Implementation consequence:
  Verdict corrected to KEEP UNCHANGED. Upgrading it would have meant
  inventing an assertion for it to carry.
```

### 14.4 C1 — collapse the duplicate — COMPLETE

**Production change** (`workflows/model_exploration.py`,
`_build_lit_review_input`): the 10-line YAML read + empty-value `print`
warning is replaced by `task_description = get_task_description(load_task_config())`.
`config` is no longer consulted for this key at all, so a stale operator copy
is structurally ignored rather than deprioritized. The warning is deleted, not
reimplemented — §0.3's upstream rejection makes the state it announced
unreachable, and re-catching it would be the swallowed fail-closed of failure
class 2.

**Config change** (`configs/lit_review_config.yaml`): the `task_description:`
block is deleted. Its comment header is rewritten to state the real behaviour
(this is C2's prose obligation, landed here because deleting the declaration
and leaving a comment describing the deleted `SIDERIUS_TASK` fallback beside
it would ship an actively misleading file for one commit).

**Stage-A parity — PASS.** All 10 `pb9_*` goldens re-render EXACT;
`git status` on the goldens directory is empty. Not regenerated. `LLMBridge`
kwargs and invocation semantics untouched — no call site changed.

**The three tests that failed on collapse were all pins defending the
duplicate**, diagnosed before any edit (test-side, not production defects):

| Test | Diagnosis | Disposition |
|---|---|---|
| `..._lit_review_wiring.py::test_warns_on_empty_task_description` | asserts the deleted warning fires | REWRITE |
| `..._lit_review_wiring.py::test_no_warning_when_task_description_set` | fed `"whale song"` via the YAML and asserted it arrived | REWRITE |
| `test_step00_task_config_baselines.py::test_cfg3a_task_description_duplicate_byte_equal` | `KeyError` — it *required* the duplicate to exist | REWRITE |

The second failure is worth recording as evidence rather than noise: it
demonstrated acceptance criterion 3 in the act of failing — a sentinel placed
in the lit-review config was ignored and the canonical text returned instead.

Rewrites, each stating the defect it catches:
`test_lit_review_yaml_is_no_longer_a_task_description_authority` (sentinel
ignored), `test_task_description_needs_no_key_in_the_lit_review_yaml` (key
optional, not merely ignored), `test_cfg3a_lit_review_declares_no_task_description`
(parsed top-level keys, never a text scan) and
`test_cfg3a_task_config_remains_the_one_declaration` (exactly one source, not
zero).

**Deviation D-04b-3 (choreography, not semantics)**: §15 assigned the pin
rewrites to C2. They landed in C1 because they measure C1's own changed
function, and deferring them would have made C1 a knowingly red commit —
which CLAUDE.md's clean-tree rule and the PR3-L2 preflight guard both forbid.
Frozen semantics, parity criterion, the 13.4-A rung, Checkpoint C and Gate
disposition are all unchanged; only which commit carries the rewrite moved.
§15's "exact Git commit count is NOT frozen" covers this.

**C1 verification** — `tests/unit/agent/ml_literature_review tests/unit/workflows`:
**328 passed**, 21.26 s, exit 0 (read from the log file, not a pipeline exit
status). Goldens directory clean. Blast radius —
`tests/integration/workflows/test_lit_review_wiring_dual_mode.py`,
`tests/unit/sdsc_submission_scripts/test_run_one_iteration.py`,
`tests/unit/scripts`: **602 passed**, 1 failed —
`test_pr3_l2p_preflight.py::test_preflight_all_invariants`, whose
`no_production_file_modified` check named exactly the three files being
edited. That is the guard working as CLAUDE.md documents; resolved by
committing the checkpoint, never by relaxing it.

Committed as `4c35adfe`.

### 14.5 C2 — guard, rung, Checkpoint C, stale prose — COMPLETE

New module `tests/unit/workflows/test_step04b_task_description_single_source.py`
(9 tests) carries all three evidence obligations.

**The declaration guard** parses every `configs/**/*.yaml|yml` and asserts the
set of files declaring a top-level `task_description` is exactly
`{task_config.yaml}`. It reasons over the parsed mapping, never the file text —
`test_the_guard_reads_declarations_not_prose` is the explicit control: it
asserts the lit-review YAML's raw text *does* contain the phrase (the comment
04b itself wrote) while its parsed mapping declares nothing, so a substring
scan would have red on this commit's own documentation.

```text
Deviation D-04b-4 — the guard found a third declaring file on first run.

Audit evidence:
  configs/task_config.example.yaml also declares task_description. Grep for
  every reference: `workflows/task_config.py:56` and `:152` only, both
  remediation strings telling an operator which file to copy. Its own header
  states "the workflow uses configs/task_config.yaml at runtime, never this
  example file".

Corrected understanding:
  It is the copy-me TEMPLATE for the canonical file. It MUST declare the key
  — a template omitting the required field would be broken — and it is not a
  second authority because nothing loads it.

Implementation consequence:
  `*.example.yaml` is excluded, narrowly and with the reasoning recorded in
  the helper's docstring. `test_the_example_template_is_not_counted_but_does
  _declare_the_key` pins the exclusion so it cannot silently widen into a
  blanket suffix skip that would hide a real second authority.
```

**Rung 13.4-A (lit-review half)** varies ONLY the canonical description. The
fixture is built by parsing the shipped `task_config.yaml` and substituting
one key, and the atomicity is **machine-checked**, not asserted in prose:
`test_the_fixture_varies_only_the_description` deletes `task_description` from
both mappings and requires the remainders to be deep-equal. Three cases: the
input follows the canonical text; a stale sentinel in the lit-review config is
not consulted; and the shipped-pairing case runs the real builder against the
YAML parsed from disk, not a synthetic dict.

**Checkpoint C** — discharged deterministically, no real LLM call:

```text
canonical §13 task config (tmp, alternate description)
  -> real production _build_lit_review_input
  -> real MLLiteratureReviewAgent.run()
  -> real search-decision + synthesis renders
  -> BoundaryRecorderBridge capture at the LLM request boundary
```

Every hop is production code; only the boundary is a recorder, whose OpenAI
clients raise on attribute access, so no network call is possible. `run()`
performs the node's own threading (`_task_description = inp.task_description`,
then three render call sites), which is why this is not redundant with the
rung: a regression dropping the field between the input and the renderer
passes 13.4-A and fails here. The recorder is asserted to have fired.

Residue is **block-scoped** per §6: `_task_blocks()` extracts the bodies of the
three markdown sections the placeholder renders under (`The task the research
agent is working on` / `The task the proposer is working on` / `Downstream
task context`) and the `"SQUID" not in block` assertion applies only there —
the surrounding lit-review doctrine legitimately discusses denoising and 1-D
signals, so a whole-prompt absence assertion would be unsatisfiable.

**Mutation evidence.** Caches cleared and site counts asserted before each
mutation; both restored via `git checkout --` and re-verified green.

| # | Mutation | Sites | Expected | Observed |
|---|---|---|---|---|
| 1 | reintroduce `task_description:` into `configs/lit_review_config.yaml` | asserted 1 | guard reds | **3 failed** — the new guard, its prose control, and the rewritten CFG-3a; restored → 15 passed |
| 2 | revert `_build_lit_review_input` to read the YAML | asserted 1 | rung + Checkpoint C red | **6 failed** — both 13.4-A tests, both Checkpoint-C tests, both rewritten wiring tests; restored → green |

Mutation 2's first attempt aborted on its own precondition: the naive pattern
matched **2** sites because `tune_input.task_description = get_task_description(...)`
at `:2674` contains the target string as a substring. Re-targeted on the exact
indented form. Recording this because a mutation applied to the wrong site
would have "proved" reachability for a call site the tests never exercise.

**Stale live prose** (§11 obligation). `SIDERIUS_TASK` now appears in **no**
executable source and **no** live config or runtime documentation — verified
by `grep -rn` across `*.py|*.yaml|*.yml|*.sh|*.json`, which returns nothing.
The surviving mentions are all in `docs/design/` historical and audit records,
including §0.1 of this document; per §15 C2 acceptance those are deliberately
preserved and a repository-wide text ban is explicitly NOT the property.

Two further stale live claims were found and corrected — both described the
warning C1 deleted:

| Surface | Stale claim | Correction |
|---|---|---|
| `nodes/ml_literature_review/ml_literature_review.py:315-319` | "the workflow warns at YAML-load time"; "operator should fill the YAML's `task_description:` key" | states the canonical source and its fail-closed loader; notes an empty value now implies a non-production caller |
| `nodes/ml_literature_review/ml_literature_review.md` (2 rows) | "The workflow emits a warning at YAML-load time"; default `""` (workflow warns) | records the single source and that the production path cannot produce an empty value |

The node doc's pre-existing claim that the value is "Sourced from
`configs/task_config.yaml` by the workflow" was **aspirational and wrong**
before this PR — the workflow read the lit-review YAML. 04b makes the
documentation true.

**Test disposition correction.** §9 assigned `test_agent_card_task_config.py`
an UPGRADE. Read in full, it has no coupling to the duplicate (§14.3) —
verdict corrected to KEEP UNCHANGED, and it is unmodified.

**C2 verification** — `tests/unit/agent/ml_literature_review tests/unit/workflows`:
**337 passed**, 21.71 s, exit 0. `pb9_*` goldens byte-identical (`git status`
on the goldens directory empty) — C2 moved zero rendered bytes, as required.
`ruff check` and `ruff format --check` clean over
`nodes/ml_literature_review/`, `tests/unit/workflows/`, `workflows/`.

Committed as `37806eed`.

### 14.6 Checkpoint D — targeted regression and static

Run from a **clean tree** at the final executable head, per CLAUDE.md's
clean-tree rule (the earlier `no_production_file_modified` red is what makes
this ordering non-optional).

```text
Validation:
  command: .venv/bin/python -m pytest \
             tests/unit/agent/ml_literature_review tests/unit/workflows \
             tests/unit/scripts tests/unit/sdsc_submission_scripts \
             tests/integration/workflows/test_lit_review_wiring_dual_mode.py -q
  purpose: directly affected deterministic tests + lit-review/workflow
           integration + the PR3-L2 preflight invariants
  runtime: 146.71 s
  result:  1429 passed, exit 0 (read from the log file, not a wrapper's
           exit status)
```

`tests/unit/scripts/test_pr3_l2p_preflight.py::test_preflight_all_invariants`,
which red during C1 development on the dirty tree, passes here — confirming
the failure was the guard observing work-in-progress, not a defect.

**Static.** `ruff check .` → *All checks passed*. `ruff format --check .` →
*869 files already formatted*. Both repository-wide, matching CI's invocation.

```text
Limitation — pyright was NOT run locally.

  .venv/bin/pyright exits 1 before analysing anything:
    SyntaxError: Unexpected token =
    at .venv/.../pyright/dist/dist/vendor.js

  Cause: this machine's Node is v10.19.0; pyright's bundled JS requires a
  modern runtime. This is exactly the case CLAUDE.md's "Environment
  assumptions" section names.

  Consequence: no local strict-type claim is made for this PR. CI's
  "Type check — pyright (strict, blocking)" step is the authority, and its
  result on the exact final head is recorded in §14.7.
```

**No local full repository suite** was run — §11's validation budget plans
none by default, and no unique evidence gap appeared that targeted tests plus
exact-head CI cannot cover. Exact-final-head CI is the broad regression
authority.

### 14.7 Closeout

| Item | Value |
|---|---|
| PR | [#209](https://github.com/Galileo-Sandbox/SIDERIUS/pull/209) |
| Branch | `feat/generic-framework-step-04b-task-description-single-source` |
| Base | `aa84f24d` |
| Semantic commits | `4c35adfe` (C1 collapse) · `37806eed` (C2 guard/rung/Checkpoint C) |
| Gate 1 | **NOT REQUIRED** — no flip condition triggered; rendered bytes and invocation semantics exact |
| Gate 2 | **NOT REQUIRED** — authority/source change only; no execution-surface expansion |
| Static builtin model descriptions | **DEFERRED**, intentionally not implemented (§0.4) |

---

## 15. Commit plan — per-commit checklists

**Two commits.** Revision 1 implied three; §0.4 deferred the builtin
model-description seam for want of a live consumer, and §0.1 deleted the
fallback-precedence work.

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**What is frozen once this design is approved**: the capability (§1), the
Stage-A parity criterion (§5), the 13.4-A rung (§6), Gate disposition (§10)
and the stop conditions (§13). **What is NOT frozen**: exact commit count,
helper structure, source line numbers and test-file decomposition — line
references here are reading aids captured at `e7e1cae5`, not contracts.
Re-read the touched source immediately before implementing each commit.

---

### C1 — Collapse the duplicate onto the single task profile

**1. Goal.**
Make `configs/task_config.yaml` the ONLY declaration of the task
description. Today `configs/lit_review_config.yaml` declares a
byte-identical second copy and `_build_lit_review_input` reads it, so
changing the task means editing two files and nothing detects divergence.

*Why this commit and not another*: it is the whole user-visible capability.
C2 is documentation-and-guard work that is only meaningful once the
collapse has actually happened, and mixing them would make the parity
question ("did any rendered byte move?") harder to review in isolation.

**2. Scope.**
- `workflows/model_exploration.py` — `_build_lit_review_input` (≈`:606-637`):
  stop reading `config.get("task_description")`; use
  `get_task_description(load_task_config())`, already imported at `:116`
  and already used by the interpreter at `:2112`.
- `configs/lit_review_config.yaml` — delete the `task_description:` block.
- **Non-goals**: no change to `LiteratureReviewInput`'s schema field; no
  change to the three lit-review prompt templates or their
  `{TASK_DESCRIPTION}` placeholder; no change to search/synthesis/extract
  behaviour, the paper corpus, or format doctrine; nothing in 04a's
  surfaces; `ml_models/model_descriptions.py` untouched.
- Depends on: nothing.

**3. Implementation plan.**
- [x] Re-read `_build_lit_review_input` in full and confirm `:116`'s import
      and the `:2112` precedent are still exactly as audited.
- [x] Replace the YAML read with `get_task_description(load_task_config())`.
- [x] Delete the now-unreachable empty-value `print` warning
      (`:614-622`), because `load_task_config` already rejects empty
      (§0.3) — a warning for a state that cannot occur is dead code.
- [x] Delete `task_description:` from `configs/lit_review_config.yaml`.
- [x] Confirm no other reader of `lit_review_config["task_description"]`
      exists (`grep`), including tests and scripts.

**4. Validation plan.**
- Unit: `_build_lit_review_input` returns the task-profile description
  even when a stale `task_description` is still present in a synthetic
  lit-review config dict — i.e. the YAML key is genuinely no longer
  consulted.
- Integration: the `pb9_*` goldens (10) re-render EXACT.
- Negative: a lit-review config with **no** `task_description` key still
  builds a valid input (proves the key is optional now, not required).
- Backward-compat / default parity: `pb9_*` byte equality IS the parity
  oracle; no new golden is needed.
- Gate: **none** (§10).

**5. Acceptance criteria.**
- [x] All 10 `pb9_*` goldens byte-identical — zero diff, not "close".
- [x] `configs/lit_review_config.yaml` contains no `task_description:` key.
- [x] With a synthetic lit-review config whose `task_description` is set to
      a DISTINGUISHABLE sentinel string, the built
      `LiteratureReviewInput.task_description` equals the **task-profile**
      text and does **not** contain the sentinel. (Asserting only "it is
      non-empty" would pass while the YAML was still authoritative.)
- [x] **Parsed** `configs/lit_review_config.yaml` has **no top-level
      `task_description` key**. Asserted by loading the YAML and checking
      the mapping — *not* by grepping the text, which would also fire on
      the comment block that legitimately explains where the value now
      comes from (and would contradict C2's rule that prose may mention
      the concept).
- [x] No other production reader of the lit-review YAML key remains.

**6. Failure and edge cases.**
- Lit-review YAML still carries the key (operator's stale local copy) →
  it must be **ignored**, not merged or preferred. Silent preference would
  restore the duplicate invisibly.
- `load_task_config` raises on an empty/missing task description → that is
  the desired fail-closed and must propagate, not be caught and warned.
- A caller that builds a lit-review input without going through
  `load_task_config` (test fixtures) → `get_task_description` returns `""`
  for a synthetic dict by documented design; such callers are test-only and
  must not be "fixed" by reintroducing a fallback.
- Any `pb9_*` byte moving → **stop**; that is a defect in the collapse, not
  a golden to regenerate (§5).

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/ml_literature_review tests/unit/workflows -q`
- [x] Record: test count, wall time, and explicit confirmation that the 10
      `pb9_*` goldens were unmodified (`git status` on the goldens dir).

**8. Commit boundary.**
One behaviour change plus its config deletion. Independently revertible —
reverting restores the duplicate and nothing else. No documentation
rewrite, no guard test, no deferred work.

---

### C2 — Guard the single source and delete the stale fallback prose

**1. Goal.**
Prevent the duplicate from silently returning, and stop
`configs/lit_review_config.yaml` documenting a `SIDERIUS_TASK` fallback
that no longer exists (§0.1).

*Why separate from C1*: C1 is a behaviour change measured by byte parity;
this is a regression guard plus comment hygiene. Keeping them apart means a
reviewer reading C1's diff sees only "did rendering change?", and the guard
lands as an explicit, reviewable decision about what must never regress.

**2. Scope.**
- `configs/lit_review_config.yaml` — the comment block at ≈`:40-47`
  describing the removed fallback.
- New/extended test asserting exactly one `task_description` source.
- `tests/unit/agent/ml_literature_review/test_agent_card_task_config.py`
  — **UPGRADE** to the single source (§9).
- Any pin asserting the lit-review YAML carries its own description —
  **REWRITE**; those pins defend the duplicate (§9).
- **Non-goals**: no production behaviour change; no template change.
- Depends on: **C1** (guarding a collapse that has not happened is
  meaningless).

**3. Implementation plan.**
- [x] Re-read the YAML comment block and rewrite it to state the real
      behaviour: the description comes from `configs/task_config.yaml`.
- [x] Add a guard test that fails when a second `task_description`
      **declaration** appears in any tracked config. It must **parse** each
      YAML under `configs/` and inspect top-level keys — never scan raw
      text, since comments and prose may legitimately mention the concept.
- [x] Re-read `test_agent_card_task_config.py` and upgrade it to the single
      source rather than deleting it.
- [x] Search for and rewrite any pin that asserts the lit-review YAML owns
      a description.

**4. Validation plan.**
- Unit: the guard reds when a `task_description:` key is reintroduced into
  `configs/lit_review_config.yaml` (prove by temporary mutation, cache
  cleared, mutation count asserted `== 1`).
- Integration: `pb9_*` still exact (C2 must move zero bytes).
- Negative: the guard must NOT fire on `configs/task_config.yaml` itself —
  that is the legitimate single source, and a guard that forbids it would
  be trivially wrong.
- Backward-compat: none needed; no production path changes.
- Gate: **none**.

**5. Acceptance criteria.**
- [x] Reintroducing `task_description:` into `configs/lit_review_config.yaml`
      makes the guard fail — demonstrated by mutation, with the restored
      tree re-verified green.
- [x] The guard passes with `configs/task_config.yaml` present and
      unmodified (exactly one legitimate source is not an error).
- [x] **No CURRENT LIVE surface describes `SIDERIUS_TASK` as an active
      fallback.** Scoped to live behaviour surfaces: the lit-review config
      comments, current node/runtime documentation, and executable source.
      A repository-wide grep is **not** the acceptance property —
      historical design and audit records (including §0.1 of this very
      document) deliberately preserve the removed mechanism, and rewriting
      them would destroy the audit trail.
- [x] `pb9_*` unchanged by this commit (`git diff` on the goldens dir is
      empty).
- [x] `test_agent_card_task_config.py` asserts the single source and still
      names a defect only it can catch.

**6. Failure and edge cases.**
- Guard written as a whole-file substring scan → would fire on ordinary
  prose mentioning the phrase, including the corrected comment this same
  commit writes. It must parse the YAML and key on a **top-level
  declaration**, never on the words appearing anywhere.
- Guard scans a directory that legitimately contains task text (e.g. a
  design doc) → scope it to `configs/`.
- Someone deletes the guard along with the duplicate in a future PR → the
  guard's own docstring must state the defect it catches, so deleting it
  is a visible decision.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/ml_literature_review tests/unit/workflows -q`
- [x] Record counts, wall time, and the mutation result (expected failure,
      observed failure, restored green).

**8. Commit boundary.**
Guard + documentation only. Contains no production behaviour change, no
deferred work, and no unrelated cleanup. Reviewable as "what must never
regress".

---

### Deferred to a future PR (NOT in 04b)

| Item | Why deferred | Evidence |
|---|---|---|
| Static builtin `ml_models/{model_type}/description.md` task prose (`punet`, `gated_fno`) | no live consumer for a task-block seam; adding one would be a consumer-less seam | §0.4 |

### Explicitly NOT re-opened

04a's merged surfaces (`model_io_contract` transport, the probe-recipe
skill, `HardwareContext.effective_cap_gb`, the implementor/validator prompt
placeholders) are out of scope; touching them would break the independence
this split rests on (§13, parent §2.3.1).
