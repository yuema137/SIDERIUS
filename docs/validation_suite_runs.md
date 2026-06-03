# §10 End-to-end validation suite — run log

Dated record of every §10 validation-suite run. The suite specification
lives in [`external_agents_for_proposer.md` §10](external_agents_for_proposer.md#§10-end-to-end-validation-suite);
this file is its companion log, where each run produces one dated section.

The suite is a **permanent acceptance gate**, not a one-time checkpoint —
it re-runs across commits on the locked 7-paper corpus (§10.2) so results
are comparable over time. See `commit_plan_ml_literature_review.md` for
the schedule of expected runs:

| Trigger | Phase coverage | Source commit |
|---|---|---|
| §10 Phase 1 partial run | Phase 1 only (Step 1a + 1b) | Commit 2c-c (closes 2c) |
| First FULL run | Phases 1 + 2 | Commit 2d (closes Commit-2 family) |
| Prerequisite re-run | Phases 1 + 2 | Before Checkpoint D / Commit 6 |

## How to add a run

1. The pilot script (`tests/integration/nodes/test_ml_literature_review_phase1_pilot.py`)
   writes its rendered report to
   `reference_data/lit_review_pilot_cache/phase1_pilot_report.md`
   (gitignored). Future suite runs produce analogous artifacts via their
   own scripts.
2. Review the artifact against the §10.5 acceptance criteria.
3. Copy the artifact into a new dated section below, using the heading
   format `## YYYY-MM-DD — <run name>` (e.g.
   `## 2026-05-30 — §10 Phase 1 partial run`).
4. Add a short prose paragraph under the heading recording: which commit
   produced the artifact, which acceptance criteria were checked, which
   passed / failed, and the Checkpoint sign-off status (if applicable).
5. Commit the doc edit separately from any code change.

## Runs

### 2026-06-02 — §10 Phase 2 partial run + Checkpoint G sign-off

**Run type:** §10 Phase 2 partial — synthesis-only spot-check on the locked
§10.2 corpus. `dynamic_search.enabled=False`, root papers only. Resolve +
compress reused from the 2c-c.2 Phase-1 cache; only synthesis is fresh.

**Source commits (Commit 2d family):**
- `e9efddf` — 2d synthesis prompt + per-paper block + locked
  Mechanism-vs-Adaptation placement rule.
- `7a5c093` — Phase-2 pilot script for Checkpoint G.
- `c51c231` — pilot artifact-first reorder (artifact now written before
  structural assertions so a failing run still surfaces a reviewable file).
- `ce67cd2` — two-layer cite-id-mismatch fix (prompt labeled-id line +
  node-side `_validate_content_paper_id` hook).
- `7d466b2` — Phase-2 pilot floor (≥2) + LaTeX-regex tuning.

**Synthesis LLM:** `deepseek` / `deepseek-v4-pro` (one call, ~$0.50, 1:56
wall time).

**Interpretation seed:** 2 bottlenecks (`training instability when a new
inductive bias conflicts with the dilated causal convolution backbone`,
`model under-converges at low data volume — strong data sensitivity`),
2 key findings, take-home message about widening receptive field / spectral
coverage without breaking WaveNet causality.

**Findings emitted:** 3 (above the ≥2 pilot floor; the §10.5 full-suite
bar of ≥4 of 7 papers does not apply to this narrower spot-check). All
three correctly cite the paper they describe — zero TADA/FreLE-style
cite-id-vs-content mismatches.

| # | source_ref | Paper | Confidence | Mechanism content (one-line) |
|---|---|---|---|---|
| 1 | `arxiv:2312.00752` | Mamba | 0.70 | Selective SSM `$$h_t = Ā h_{t-1} + B̄ x_t$$` lifted verbatim from source |
| 2 | `arxiv:2501.04967` | TADA | 0.90 | Logistic rescaling `$$ω = 1/(1+exp(-20(R_i-τ)))$$` + variance-match formula lifted verbatim |
| 3 | `arxiv:2510.25800` | FreLE | 0.85 | Composite frequency loss `$$\min_θ δL^f + (1-δ)L^t$$` lifted verbatim |

**Checkpoint G acceptance sub-criteria (all PASS):**

- (a) Tier-1 findings carry the equation verbatim inside **Mechanism** —
  ✅ all three.
- (b) Tier-1 pseudocode reproduced where the algorithm IS the mechanism —
  ✅ N/A this run (none of the three cited papers' algorithms were *the*
  mechanism; equations were).
- (c) Tier-2 paraphrased + flagged — ✅ N/A (SNRAware not cited this run).
- (d) Abstract-only papers carry no equation — ✅ N/A (no abstract-only
  papers cited).
- (e) Implementability bar — ✅ each Adaptation names concrete steps
  ("Use a Mamba encoder ... decode to [B,256,T] with a linear or
  convolutional head"; "Extend the final layer to output 256 channels";
  "Apply this loss directly to the SQUID denoising model, using the clean
  signal's Fourier magnitudes as target").
- (f) Measurable improvement vs pre-2d — ✅ first-ever Phase-2 artifact;
  the comparison baseline is the implementation gap of the pre-2d
  synthesis prompt that didn't see `key_equations_md`. Equation quoting +
  placement rule both held end-to-end.

**Confidence calibration check:** 0.90 (TADA, on-domain 1-D denoising) >
0.85 (FreLE, on-domain frequency loss) > 0.70 (Mamba, cross-domain
sequence modeling) — ordering matches the rubric's evidence ladder.

**Placement rule held:** all three findings have equations in Mechanism,
none in Adaptation (regex check `_LATEX_DELIMITER_RE` matched Mechanism on
all three, Adaptation on zero of three).

**Cite-id-mismatch fix validated:** zero `content_paper_id != source_ref`
drops, zero unmatched-source_ref soft-drops in the run log. The two-layer
fix (labeled `source_ref / content_paper_id` per-paper line + node-side
hard-validation hook) eliminated the TADA-as-FreLE hallucination
observed on the pre-`ce67cd2` first real_run.

**Sign-off:** Checkpoint G ✅ signed off 2026-06-02. Commit 2d closed
(see status board in `commit_plan_ml_literature_review.md`).

**Artifact:** the full per-finding rendered Markdown lives at
`reference_data/lit_review_pilot_cache/phase2_pilot_report.md`
(gitignored). Excerpts above are the canonical record.

**Known limitations of this run** (informational, do not block sign-off):
- 3 findings is below the §10.5 full-suite bar of "≥4 of 7 papers
  produce at least one finding". This pilot was a synthesis-prompt
  spot-check (`dynamic_search.enabled=False`, 2-bottleneck seed); the
  finding-count levers are documented in
  `nodes/ml_literature_review.md` §"Parameter Reference". The first
  FULL §10 suite run lands when the workflow integration (Commit 6)
  drives a richer seed end-to-end.
- DeepSeek transliterated the source's `$$...$$` display delimiters to
  `\(...\)` inline form in some of the surrounding equation context on
  Finding 1 — the canonical quoted equations are in `$$...$$` form, but
  inline references use `\(...\)`. Equation content is verbatim; the
  pilot's broadened `_LATEX_DELIMITER_RE` accepts both forms (correct
  per Decision B in commit `7d466b2`).
