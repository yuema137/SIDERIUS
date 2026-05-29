# Dynamic search loop pilot — Checkpoint C artifact

**Canonical run**: full-loop moderate-tolerance trace, 2026-05-28
(`/tmp/canonical_trace.py`, `/tmp/canonical_trace_moderate_output.json`).
**Node**: `nodes/ml_literature_review.py` (Commit 4a = `820c548`,
4b-code = `c7860d7`, 4b-docs = `2ec1ae5`, 4b-final pending).
**Seed**: real `InterpretationOutput` from
`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v12_0504/iter_014`.
**Config**: `deepseek-v4-pro` for all three steps; `findings_verbosity=1`
(three-part Markdown); `synthesis_config.transfer_tolerance="moderate"`
(the new default — see §4 Fix 12).
**Status**: signed off 2026-05-28 — see §9.

---

## 1 — Seed summary

`exploration_explore_novel_v12_0504` is the 14-iteration SIDERIUS exploration
that accumulated **80 experiments across 12 spectral/wavelet architectures**
(`band_modulated_dual_spectral_mixer` — best at 5.7039 — through `wavenet`
5.5763, `spectral_gated_pyramid`, `split_band_spectral_skipformer`, ...). The
field is a tight competitive plateau ~0.13 above the WaveNet full-spectrum
baseline, not a clear architectural failure. Three structural bottlenecks
ground every query and finding in this pilot:

- **File-17 under-recovery** — the late heavy-file cluster (17 → 18/19) is the
  top `Impact_Score` lever in every competitive model (file 17 Impact 3.7–4.5).
- **Optimization-to-metric mismatch** — lower CE / focal loss does not reliably
  improve the denoising score and sometimes coincides with amplitude collapse.
- **Tiny-data robustness** — a narrow stable basin under the 200-segment
  screening regime (large trial-to-formal drops, neighboring collapses).

Take-home: *"target improved recovery of file 17 before claiming saturation."*

---

## 2 — Loop trace (canonical, moderate)

`max_rounds=3`, `escalation_allowed=True`, `findings_verbosity=1`,
`transfer_tolerance="moderate"`. Both roots deep-read at v=1 before the loop.

| # | Action | Query / target | Outcome | Reasoning summary |
|---|---|---|---|---|
| pre | RESOLVE | `arxiv:2406.04378` (TIDMAD) v=1 | ok | root paper |
| pre | RESOLVE | `arxiv:2503.18162` (SNRAware) v=1 | ok | root paper |
| 1 | **ESCALATE** | `arxiv:2503.18162` (SNRAware) v=1 | no-op (already v=1) | *"SNRAware directly addresses the optimization-to-metric mismatch ... an SNR-oriented training scheme that could align our loss with the denoising score."* — assessment block fired, identified SNRAware as the top on-bottleneck candidate |
| 2 | search | `"SNR maximization loss denoising"` | 10 hits | *"standard losses (CE, focal) are not aligned with the SNR-based denoising score."* |
| 3 | search | `"sample reweighting loss time series denoising"` | 10 hits | *"models under-recover the hardest segments (file 17) and standard losses do not align ..."* |
| 4 | search | `"spectral loss denoising time series"` | 10 hits | *"the task is full-spectrum and the models are spectral, a loss that operates in the frequency domain could better align ..."* |
| — | terminate | rounds == max_rounds | | hard safety net |

**Net retrieval**: 30 papers (v0=28, v1=2 — both seeded roots).

**Note on SNRAware**: the search-decision LLM made SNRAware its **first action**
(an `ESCALATE`), judging it the single most on-bottleneck candidate. The
synthesis LLM, given the full 30-paper set, did **not** cite SNRAware in this
sample — it selected three other on-bottleneck papers instead. This is
sampling variance between two distinct LLM calls (the search-decision LLM and
the synthesis LLM can disagree on which papers are most relevant); see §5.1 for
a run in which synthesis *did* cite SNRAware, and §7 for the limitation.

---

## 3 — Checkpoint C inspection (per-bullet verdicts)

**3.1 — Queries specific and grounded? (Fix A / Fix C)** — ✅ **Pass.** Three
short keyword phrases (≤6 words), each a specific loss/training mechanism, zero
internal jargon (no "file 17" / "Impact_Score" / architecture names) leaked
into a query. Match the prompt's GOOD pattern.

**3.2 — Query generation uses `key_findings` / `bottlenecks`?** — ✅ **Pass.**
Every iteration's reasoning names a bottleneck verbatim (optimization-metric
mismatch, file-17 hard-segment under-recovery, full-spectrum/spectral framing).

**3.3 — Escalation behavior (assessment block)** — ✅ **Pass (decision); ⚠️ (deep-read outcome).**
The mandatory-assessment block made the LLM's **first action** an `ESCALATE` of
the most on-bottleneck candidate (SNRAware) — strong evidence the block works.
Caveat: that escalation was a no-op (SNRAware was already a v=1 root), so it
produced no *new* deep-read. As in the strict run, escalation of a genuinely
new on-bottleneck paper is gated on PDF availability (Commit 2c motivator).

**3.4 — Termination sensible?** — ✅ **Pass.** Terminated by `max_rounds=3`
after 1 escalate + 3 searches; never emitted a premature `done`.

**3.5 — On-domain hit rate / `MODEL_REGISTRY` overlap** — ✅ **Pass.** Zero of
the 28 search hits duplicate registry models (punet/wavenet/transformer/rnn/
fcnet); retrieval is loss-design / SNR / denoising papers across adjacent 1-D
domains — specific, not generic-task-domain.

**3.6 — Findings grounded in specific bottlenecks?** — ✅ **Pass.** All three
findings open with `**Implication:** Given the [specific bottleneck] ...`; none
is a generic paper summary. See §5.

---

## 4 — Fix iteration history

| # | Fix | What changed | What improved |
|---|---|---|---|
| 0 | *(initial)* | gpt-4o-mini + naïve search prompt | jargon-polluted queries (`file 17`, `Impact_Score`) → 0-hit/off-topic; synthesis recommended FC-Net's frequency-split score (anti-pattern) |
| 1 | **Fix A** (search prompt) ×2 | translate internal jargon → general ML/signal vocabulary | jargon leak reduced on gpt-4o-mini, eliminated on DeepSeek |
| 2 | **Fix B** (synthesis prompt) | full-spectrum guard: never recommend frequency-split; treat as cautionary | no more frequency-split recommendations; correctly cautions regime-specific results |
| 3 | **5-paper × 3-track extract check** | compression validated across main/application/denoising tracks | PASS; anti-noise + regime-qualifier + math-in-prose rules hold across paper types (§6) |
| 4 | **All-DeepSeek routing** | deepseek-v4-pro for all three steps | cleaner queries; richer/more accurate extracts (caught DMF-Net's frequency-split regime gpt-4o-mini missed); honest cross-domain disclaimers |
| 5 | **ConfidenceRubric system** | unified rubric injected via `{CONFIDENCE_RUBRIC}`; `abstract_only_ceiling=0.79` clamp; `render_for_consumer` → `AgentCard.trust_guidance` (400→800) | consistent banded confidences; clamp backstop; proposer reads the legend |
| 6 | **Year override** | `_override_year_from_metadata` from S2 metadata | DeepSeek's blank/wrong `year` no longer surfaces |
| 7 | **Fix C** (search prompt) | short-keyword-phrase guideline + per-round `(query, hits)` feedback with broaden-on-0-hit nudge | verified vs S2 API: bad query form was the variance cause; consistent 10-hit queries after |
| 8 | **Escalation-assessment diagnostic** | captured per-round reasoning | found the LLM never referenced retrieved papers pre-fix — a prompt gap, not rational behavior |
| 9 | **Mandatory escalation-assessment block** | search prompt must assess retrieved papers before each decision | reasoning now evaluates the menu; canonical trace's first action is an on-bottleneck `ESCALATE` |
| 10 | **findings_verbosity + three-part format** | `Literal[0,1]=1`; `{CONTENT_FORMAT_BLOCK}`; V1 = Implication / Mechanism / Adaptation (40/80/50 words) + rationale | findings carry implementable Adaptation recipes, not summaries; 6/6 compliance after normalization |
| 11 | **Heading normalization** | `_normalize_finding_content_headings` (`**Adaption:**` → `**Adaptation:**`) | single DeepSeek typo backstopped; pattern documented |
| 12 | **SynthesisConfig.transfer_tolerance** | `{OMISSION_RULE}` placeholder + strict/moderate/liberal blocks; default **moderate** | strict *omitted* cross-domain-transferable papers (e.g. SNRAware); moderate emits them **with an explicit Adaptation transfer caveat**. Three-way comparison (one synthesis call per level over the same 31 papers): strict consistently omits SNRAware, moderate rescues it at 0.65 with a noise-map caveat, liberal showed no clear advantage + more noise. "他山之石可以攻玉" — a cross-domain finding with an honest caveat beats no finding. |

---

## 5 — Findings quality (canonical, moderate)

Three findings; **3/3 format compliance** (Implication / Mechanism / Adaptation
+ rationale); all bottleneck-grounded; all abstract-only (v0), confidences in
the 0.40–0.59 band; Fix B holds. Two are cross-domain emitted *with* caveats —
the moderate-tolerance behavior strict would have omitted.

### Finding 0 — `doi:10.3390/s21144623` (Raman peak-preserving loss) · `0.45` · v0 · cross-domain + caveat

> **Implication:** Given the optimization-to-metric mismatch (lower CE/focal
> loss does not improve denoising score, amplitude collapse), try a custom loss
> that explicitly penalizes peak amplitude distortion to better align training
> with reconstruction quality.
> **Mechanism:** CNN with a custom loss balancing denoising and peak fidelity,
> penalizing deviations in spectral peak shapes to prevent oversmoothing.
> **Adaptation:** Define a peak-preserving loss for 1-D SQUID data measuring
> amplitude changes in key frequency bands of reconstruction vs. clean,
> targeting the observed amplitude collapse.
> *(rationale: abstract-only, cross-domain (Raman spectra), but the
> peak-preserving loss directly addresses the amplitude collapse.)*

**Judgment.** On-bottleneck (optimization-metric mismatch + amplitude collapse),
concrete mechanism + Adaptation, honest cross-domain caveat. ✅ Good.

### Finding 1 — `arxiv:2501.04967` (TADA adversarial denoising AE) · `0.50` · v0 · on-domain, two bottlenecks

> **Implication:** Given the robustness bottleneck under tiny-data screening
> (narrow stable basin, inference failures), try a targeted adversarial
> denoising autoencoder with covariance rescaling to improve stability while
> keeping the model compact.
> **Mechanism:** TADA uses logistic covariance-targeted adversarial training to
> minimize signal degradation, with a small autoencoder (<400k parameters) that
> surpasses conventional filters and competes with larger networks.
> **Adaptation:** Replace the current encoder-decoder with a similar adversarial
> setup, constraining parameter count to the successful compact range;
> incorporate covariance rescaling to stabilise training and reduce
> formal-trial drops.
> *(rationale: abstract-only, but on-domain (1-D signal denoising) and directly
> addresses robustness and model simplification.)*

**Judgment.** Strongest finding of the run — on-domain 1-D, addresses **two**
bottlenecks (robustness + the seed's "simplification beats parameter growth"
key finding). ✅ Excellent.

### Finding 2 — `arxiv:2510.25800` (FreLE frequency-loss enhancement) · `0.45` · v0 · cross-domain + caveat

> **Implication:** Given the optimization-to-metric mismatch and possible
> spectral bias (under-recovery of specific frequency content), add a frequency
> loss enhancement (FreLE) as an auxiliary loss to regularize frequency learning.
> **Mechanism:** FreLE mitigates the low-frequency spectral bias common in
> neural networks by combining explicit and implicit frequency regularisation,
> as a plug-and-play loss unit.
> **Adaptation:** Apply frequency-domain loss on the reconstruction, balancing
> low- and high-frequency errors to prevent overfitting to one part of the
> spectrum.
> *(rationale: abstract-only, cross-domain (forecasting), but the loss is
> directly applicable to any time-series reconstruction.)*

**Judgment.** Cross-domain (forecasting) but a clean plug-in loss with an honest
caveat — a moderate-tolerance finding. ✅ Good.

### 5.1 — Demonstrated v1-finding-with-caveat (from the isolated moderate comparison)

The full-loop canonical trace above did not cite either v1 root (sampling
variance — §2, §7). **In the isolated three-way tolerance comparison**
(`/tmp/tolerance_compare_output.json`; one synthesis call per level over the
strict run's 31 papers, *not* the full-loop canonical trace), synthesis under
moderate **did** cite the deep-read SNRAware paper:

> **`arxiv:2503.18162` SNRAware** · confidence **0.65** · **v1 (deep-read)**
> **Implication:** Given the optimization-to-metric mismatch bottleneck, try
> augmenting the input with a noise-variance estimate as a second channel so
> the model can learn frequency-varying denoising strength.
> **Mechanism:** The paper concatenates a g-factor map (noise distribution) as
> an extra channel, enabling the network to adapt denoising to local noise
> statistics; all models trained full-image, not per-band.
> **Adaptation:** For 1-D SQUID, create a per-timestep local SNR estimate or a
> learned noise embedding vector and concatenate along the channel dimension
> before the first convolution. **Caveat: SQUID noise is stationary; the
> benefit may be limited, but it's cheap to try.**
> *(rationale: cross-domain MRI denoising but the noise-map mechanism is a
> generic input augmentation that could address the metric mismatch.)*

This is the canonical example of the moderate-tolerance contract: a deep-read,
cross-domain paper (MRI 2-D) whose mechanism is surfaced **with an explicit,
honest MRI→SQUID transfer caveat** in the Adaptation section. Confidence 0.65 is
rubric-appropriate (deep-read with a clear mechanism transfer → 0.60–0.79 band).
Under **strict** the same paper is omitted (its compression `relevance_to_task`
disclaims direct applicability); moderate lets the proposer decide.

---

## 6 — `PaperExtract` quality across paper types

Cross-cutting check on **five papers across three tracks** (main / application /
denoising), re-validated on DeepSeek. Verdict: **PASS** — `architecture_details`
specific, `key_results` regime-qualified, `relevance_to_task` appropriately
graded, no hallucinations.

| Track | Count | Highlight |
|---|---|---|
| Main (benchmark / dataset) | 2 | TIDMAD (`arxiv:2406.04378`): compression preserved the frequency-split-vs-full-spectrum baseline distinction (FCNet 6.43 *under frequency-split* vs WaveNet 4.99 full-spectrum) — regime qualifier carried correctly. |
| Application (adjacent-domain) | 1 | Mechanism preserved + cross-domain caveat surfaced in `relevance_to_task`. |
| Denoising (1-D methods) | 2 | **GW time-frequency denoising (`arxiv:2511.20731`)** — strongest relevance hit: extract correctly identified the amplitude/phase Griffin-Lim mechanism, the 2D-spectrogram caveat, and the limited transfer to 1-D SQUID — the honest disclaimer the omission/tolerance logic relies on. |

**DeepSeek > gpt-4o-mini on compression**: more detailed and more accurate;
notably caught DMF-Net's frequency-split training regime that gpt-4o-mini
missed (a correctness gain on a regime qualifier Fix B depends on).

*(Summary-level: the per-paper extract JSONs from that check live in the
session artifacts, not this repo.)*

---

## 7 — Known limitations / behavioral characteristics

1. **Search variance on a jargon-heavy seed.** This seed is dense with internal
   terms; the per-round `(query, hits)` feedback + broaden-on-0-hit nudge
   (Fix C) is the corrective. No 0-hit queries in the canonical trace.

2. **Search-loop vs. synthesis selection variance.** The search-decision LLM
   and the synthesis LLM are distinct calls and can disagree on which papers
   are most relevant. In the canonical trace the search-decision LLM escalated
   SNRAware *first* (top on-bottleneck candidate), yet synthesis did not cite
   it in that sample, while the isolated comparison's synthesis *did* (§5.1).
   This is expected stochastic behavior, **not a bug** — both judgments are
   defensible; which specific papers get cited is sample-dependent.

3. **Transfer tolerance governs cross-domain omission.** Under **strict**
   tolerance, cross-domain papers with transferable mechanisms were omitted
   entirely (the strict canonical trace dropped SNRAware on its own
   `relevance_to_task` disclaimer). **Moderate** (the new default) instead
   generates a finding with an **explicit transfer caveat** in the Adaptation
   section, letting the proposer decide relevance — see §5.1. Liberal showed no
   clear advantage and more sampling noise.

4. **Escalation fires but rarely produces a *new* v1 finding.** The
   assessment block reliably gets the LLM to escalate on-bottleneck papers, but
   reaching v1 depends on PDF availability: arXiv resolves reliably; DOI-only
   papers without an `openAccessPdf.url` return `partial` and degrade to v0.
   This is the failure mode Commit 2c (three-tier extraction with Tier-2
   `marker`) is designed to fix. Until 2c, new on-bottleneck v1 findings are
   rare in real runs.

5. **The clamp's deep-read branch is unit-test-validated only.** The
   `abstract_only_ceiling=0.79` clamp is exercised in unit tests and is
   structurally correct, but has not been observed firing/not-firing on a
   real-data v1 finding above 0.79. The one real-data v1 finding we have
   (SNRAware, §5.1) sits at 0.65 — below the ceiling — so the clamp is
   irrelevant to it either way. Genuine exercise needs an on-bottleneck v1
   paper scoring >0.79, which compounds with limitation 4 (PDF-gated deep-reads).

6. **DeepSeek synthesis is conservative on abstract-only papers.** 2–6 findings
   from 19–31 retrieved — high omission rate, which is desirable. The
   `ConfidenceRubric` "abstract-only evidence is a valid band" framing
   (0.40–0.59) is what keeps abstract-only findings from being over-omitted
   while preserving omission-beats-weak discipline.

---

## 8 — Configuration summary

| Knob | Value (this run) | Source / default |
|---|---|---|
| LLM (all three steps) | `deepseek-v4-pro` | input |
| `findings_verbosity` | 1 (three-part Markdown) | `LiteratureReviewInput`, default 1 |
| `synthesis_config.transfer_tolerance` | `moderate` | `SynthesisConfig`, default moderate |
| `confidence_rubric` | default (0.80–1.00 / 0.60–0.79 / 0.40–0.59; omit < 0.40; abstract-only ceiling 0.79) | `ConfidenceRubric` |
| `dynamic_search.max_rounds` | 3 | input |
| roots | TIDMAD + SNRAware @ v1 | input |

---

## 9 — Sign-off

**Checkpoint C — signed off 2026-05-28.**

The dynamic search loop behaves correctly and purposefully on a real seed with a
real LLM/S2 round trip. All six inspection bullets pass on behavior. Fix A
(jargon translation), Fix B (full-spectrum guard), Fix C (keyword form +
zero-hit feedback) hold under load; the escalation-assessment block (Fix 9)
closes the diagnosed prompt gap (first action in the canonical trace is an
on-bottleneck `ESCALATE`); the three-part `findings_verbosity=1` format produces
implementable Adaptation recipes (3/3 compliance); and `transfer_tolerance=
moderate` (Fix 12) surfaces transferable cross-domain mechanisms with honest
Adaptation caveats (§5.1) rather than omitting them. Two known caveats
(escalation deep-reads are PDF-gated; the clamp's deep-read branch is
unit-validated only) are upstream of the loop and tracked to Commit 2c.

**Next**: switch the Tier-1 integration test to DeepSeek / `DEEPSEEK_API_KEY`
(remaining 4b-final bullet) → commit 4b-final → PR (Commit 4 close-out) →
Commit 2c (three-tier extraction).
