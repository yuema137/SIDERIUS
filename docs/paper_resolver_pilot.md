# Paper Resolver Skill — Pilot (Behavioral Checkpoint A)

**Artifact for**: Commit 2 of [`commit_plan_ml_literature_review.md`](commit_plan_ml_literature_review.md),
Behavioral Checkpoint A ("Raw paper resolution output").

**What this decides**: the `PaperExtract` field design and the LLM compression
prompt in Commit 3 — specifically whether to add a structured equation field,
and what noise the compression prompt must be told to ignore.

**Run date**: 2026-05-26 · **Skill**: `agent/skills/paper_resolver_skill/wrapper.py`
· **PDF lib**: `pdfplumber 0.11.9` · **S2 auth**: `S2_API_KEY` set (authenticated pool).

> ⚠️ **ID correction during the pilot.** The plan/spec originally named arxiv
> `2302.09309` as "the TIDMAD paper". That ID actually resolves to an unrelated
> CVPR vision paper (*StyleAdv*, `10.1109/CVPR52729.2023.02354`). The real
> TIDMAD paper is **`2406.04378`** (confirmed against the legacy repo README,
> `/home/tidmad/TIDMAD/README.md:4`). All docs/code/tests were corrected to
> `2406.04378`. This pilot was run against the correct paper.

---

## 1. Resolve-mode pilot — TIDMAD (`arxiv:2406.04378`)

Command (via `load_dotenv()` so `S2_API_KEY` is picked up):

```python
run_skill(None, mode="resolve", source_type="arxiv", identifier="2406.04378", verbosity=2)
run_skill(None, mode="resolve", source_type="arxiv", identifier="2406.04378", verbosity=1)
```

### Envelope output

| Field | verbosity=2 | verbosity=1 |
|---|---|---|
| `status` | `ok` | `ok` |
| `message` | `PDF resolved via arxiv_fallback` | `PDF resolved via arxiv_fallback` |
| `verbosity_achieved` | `2` | `1` |
| `full_text` length | 73,644 chars ≈ **18,411 tokens** | (same text, achieved=1) |

- **title**: *TIDMAD: Time Series Dataset for Discovering Dark Matter with AI Denoising*
- **externalIds**: `{ArXiv: 2406.04378, DBLP: journals/corr/abs-2406-04378, DOI: 10.48550/arXiv.2406.04378, CorpusId: 270357903}`
- **openAccessPdf**: `{'url': '', 'status': None, ...}` — **the S2 `openAccessPdf.url` was empty**, so the skill correctly fell through to the arxiv-PDF fallback (`https://arxiv.org/pdf/2406.04378.pdf`). The `arxiv_fallback` branch is therefore the *de-facto* path for arxiv sources, not an edge case — see finding (F1) below.

### Path taken
`openAccessPdf` present but `url == ""` → falsy → `_arxiv_fallback_url` built `https://arxiv.org/pdf/2406.04378.pdf` → download + extract succeeded. Both fallback and `verbosity_achieved` accounting validated against a real PDF.

---

## 2. Checkpoint A inspection answers

**Q: Is the text readable, or garbled by multi-column layout?**
Readable. NeurIPS single-column body — no column interleaving. **But** there is a
systematic **inter-word space loss**: `Webenchmarkedeightdifferentdenoising...`,
`Darkmattermakesupapproximately85%...`. Words are concatenated, not scrambled —
an LLM can still parse meaning, but exact tokenization is degraded. This is the
dominant quality issue, not garbling.

**Q: Are equations preserved as LaTeX / Unicode / lost?**
**Degraded — not usable as structured LaTeX.** Representative extractions:
- Eq (2): `A≡⟨|Φ |2⟩=g2 ρ G2V2B2` — Unicode `⟨ ⟩ Φ` survive, but super/subscripts are flattened inline.
- Eq (3): `ν =argmax PSD(ν)−(PSD(ν−df)+PSD(ν+df))` with the subscript `0` displaced onto the *next* line; wrapped in `(cid:16)(cid:17)` glyph artifacts.
- Eq (4) (SNR): fragmented across ~6 lines; the summation symbol `∑` is emitted as **`(cid:88)`** (unmapped font glyph).

So: subscripts/superscripts flatten, fractions/sums fragment across lines, and
some math glyphs become `(cid:NN)` artifacts. **Recommendation → prose, no
structured `key_equations` field** (see §4).

**Q: Is section structure identifiable?**
Yes, cleanly. Numbered headers extract intact:
`1 Introduction → 1.1 / 1.2 → 2 Dataset description → 3 Experiments →
4 Evaluation metrics → 4.1 Benchmark1: denoising score → 4.2 Benchmark2:
dark matter limit → 5 Limitations → 6 Conclusions`, plus a Datasheet appendix.
The compression prompt **can** reference section names explicitly.

**Q: What fraction is noise?**
Moderate (~15–25%). Noise sources:
- author affiliations + emails block (header),
- the rotated arxiv margin stamp, extracted garbled as `5202 tcO 82 ]GL.sc[ 3v87340.6042:viXra` (= "arXiv:2406.04378v3 [hep-ex] … Oct 2025"),
- `(cid:NN)` glyph artifacts clustered in equation regions,
- Datasheet-appendix table-of-contents dot leaders (`. . . . .`).
Core scientific prose is intact; noise is bounded and identifiable.

**Q: Which sections would actually help a model proposer?**
**High relevance — this paper is unusually on-point.** §3 *Experiments* gives
explicit architecture descriptions of all 8 benchmarked denoisers, including the
five that map directly onto `MODEL_REGISTRY`:
- **FC net** — autoencoder, per-sample MSE regression;
- **WaveNet** — dilated causal convolutions, residual blocks, gated activations, skip connections; *not* frequency-split (single model handles all freqs);
- **PU net** — UNet + positional encoding, reframed as **256-class semantic segmentation** per timestep;
- **Transformer** — self-attention + positional encoding, same 256-class head;
- **RNN Seq2Seq** — LSTM encoder/decoder, same 256-class head.

Plus concrete training tricks: **Focal Loss** for class-imbalanced segmentation,
**frequency splitting** (multiple specialized models per band, except WaveNet),
and segmentation-due-to-memory. §4 defines the **denoising score** (modified
log-SNR, `DenoisingScore = log Λ`) and Table 1 reports per-model results
(FCNet 6.43/6.55 best, WaveNet 4.99/5.16, …). These are exactly the
architecture / preprocessing / training-trick / ablation signals a proposer wants.

**Q: Token count?**
≈ **18,411 tokens** (73,644 chars ÷ 4). Comfortably fits a single compression
prompt in a modern context window (e.g. gpt-4o-mini 128k); no chunking needed
for v1 root papers of this size.

---

## Key findings — explicit & actionable (F1–F4)

### F1 — `openAccessPdf` is empty for arXiv papers; the arxiv fallback is the de-facto primary path

For the TIDMAD paper, S2 returned `openAccessPdf = {'url': '', 'status': None, ...}`
— an **empty** URL. The skill did **not** download via the S2-advertised
open-access link; it fell through to the arxiv fallback
`https://arxiv.org/pdf/2406.04378.pdf`, which succeeded.

**Implication**: for arXiv-hosted papers the arxiv fallback is **not a safety
net — it is the primary download path**, and must be treated as
production-critical. Commit 3's node error handling and logging should assume
the fallback is the normal route: an empty/missing `openAccessPdf.url` for an
arXiv source is *expected*, not an error or a warning condition.

### F2 — 18.4k tokens fits a single prompt; no chunking needed

The full extracted text is 73,644 chars ≈ **18,400 tokens**, well within a
single context window for any Gemini/GPT-4-class model (128k+).

**Implication (confirmed by the pilot, not assumed)**: Commit 3's compression
can be a **single LLM call over the entire full text** — no chunking, no segment
merging, no multi-pass extraction. Revisit only if a future root paper
materially exceeds the model context; papers of this size do not.

### F3 — Equation degradation rules out a structured `key_equations` field

The extracted math is degraded beyond reliable reconstruction:
- `∑` is emitted as **`(cid:88)`** — a raw font-glyph code, not a readable symbol;
- subscripts, superscripts, and fractions are flattened or split across lines
  (Eq 3's subscript `0` lands on the next line);
- an LLM fed this text **cannot reliably reproduce correct LaTeX** — it would
  emit plausible-looking but likely **wrong** formulas (hallucinated math).

**Decision**: `PaperExtract` will **not** include a `key_equations` field.
Mathematical methods are captured **in prose** (e.g. *"the denoising score is a
weighted log-ratio of signal-band to noise-band PSD"*), not as LaTeX.
**Prompt instruction (Commit 3)**: explicitly tell the LLM to (a) describe
mathematical content in plain language and (b) ignore `(cid:NN)` glyph artifacts.

### F4 — TIDMAD content is dense but carries a high-risk misleading signal (frequency-split vs full-spectrum)

§3 describes all five models in `MODEL_REGISTRY` (FCNet, WaveNet, PUNet,
Transformer, RNN), plus Focal Loss, the frequency-splitting training approach,
the denoising-score formula, and Table 1 results. The architecture
*descriptions* are specific and actionable.

**Critical caveat — do not transfer the performance rankings.** The paper states
verbatim that *"we implemented frequency splitting for all models except
WaveNet."* Therefore:
- 4 of the 5 models (FCNet, PUNet, Transformer, RNN) were trained in a
  **frequency-split** setting — each handles one frequency band independently.
- **WaveNet is the only model trained full-spectrum**, and is the **only
  directly comparable baseline** for SIDERIUS (which trains full-spectrum).
- Table 1 rankings (e.g. "FCNet > WaveNet") are **valid only under
  frequency-split training**. A proposer learning "FCNet beats WaveNet from
  TIDMAD" is learning a frequency-split result that **does not hold — and may
  reverse — under full-spectrum training**.

**High-risk flag**: if Commit 3's compression produces an
`architecture_details`/`key_results` field that ranks these models **without**
the frequency-split qualifier, that extract is **actively harmful**, not merely
incomplete — it steers the proposer toward architectures optimized for the wrong
setting. The qualifier must be injected by the compression prompt (it cannot be
reliably inferred from the paper text); see "Implications for Commit 3" items
6–7.

---

## 3. Representative excerpt — §3 Experiments (architecture descriptions)

First chars of the methods/experiments section, verbatim from the extraction
(despacing preserved to show real input quality):

```
3 Experiments
Webenchmarkedeightdifferentdenoisingalgorithmsincludingthreetraditionalalgorithmsandfive
deep learning models. ...
• FC net: an autoencoder architecture ... Both the encoder and decoder are composed of multiple
  fully-connectedlayersandactivationlayers. FC-Netoutputsasinglefloatingpointnumberateach
  timestep, ... minimizing the meansquareerror ...
• WaveNet: adeepneuralnetwork ... autoregressivelypredictingeachsampleusingdilatedcausal
  convolutions[33]. ... residualblocks ... gatedactivations, andskipconnections ...
• PU net: a deep learning architecture based on the UNet architecture [25]. ... Positional
  encoding layers ... werequirethemodeltooutputa256-classclassificationdecisionateverytime
  step ... redefinesthedenoisingtaskintoasemanticsegmentationtask.
• Transformer: ... self-attentionmechanism ... 256-classclassificationdecisionasPU-Net ...
• RNN Sequence to Sequence Model: ... encoderanddecoderadoptsaLSTMarchitecture ...
  PU-Net,Transformer,WaveNet,andRNNSeq2SeqarealltrainedusingFocalLoss ...
```

Equation region (showing degradation):

```
ν =argmax( PSD_Injected(ν) − (PSD(ν−df)+PSD(ν+df)) )      (3)   ← subscript "0" drops to next line
SNR_i = ( P_sig / P_noise ) = Σ PSD(ν) / Σ PSD(ν)         (4)   ← extracted as (cid:88) for Σ, fragmented
DenoisingScore = log Λ                                    (7)
```

---

## 4. Recommendation for Commit 3 (`PaperExtract` + compression prompt)

1. **No structured equation field.** Equations extract too degraded for a
   reliable `key_equations: str` (LaTeX). Instruct the LLM to **describe key
   equations in prose** within `key_results` / `architecture_summary`.
2. **Compression prompt must explicitly tell the LLM to ignore**: author
   affiliations/emails, the rotated arxiv margin stamp, `(cid:NN)` glyph
   artifacts, and Datasheet-appendix TOC dot-leaders.
3. **Tolerate despacing.** Add an instruction that words may be concatenated
   (missing spaces) and the model should read through it.
4. **Reference section names.** Section structure is clean — the prompt may
   instruct the LLM to prioritize Experiments / Methods / Evaluation sections
   and down-weight Introduction/References.
5. **Single-prompt sizing is fine** for root papers (~18k tokens); revisit
   chunking only if a future paper exceeds the model context.
6. (Future, non-blocking) The despacing may be reducible via pdfplumber
   `extract_text(x_tolerance=...)` tuning — deferred; the prose-tolerant prompt
   covers v1.

**Verdict**: extraction quality is **sufficient to proceed to Commit 3**. The
text is not garbled, sections are clean, and the proposer-relevant content
(architectures, training tricks, results table) is fully present. The only hard
limitation is equation fidelity, which the prose recommendation handles.

---

## 5. Search-mode pilot (sanity)

```python
run_skill(None, mode="search",
          query="superconducting quantum interference device denoising",
          limit=5, verbosity=0)
```

- **status**: `ok` · **message**: `search returned 5 result(s)` · **total**: 9,449 hits.
- All 5 returned results carry `openAccessPdf=yes`.
- Topical relevance (titles):
  1. (2025) Advances of magnetocardiography in application of adult and fetal cardiac diseases
  2. (2023) One New Designed Wiener Filter Method for SQUID Magnetogastrogram Detection
  3. (2025) Approaching optimal microwave–acoustic transduction … using SQUID arrays
  4. (2024) Direct Measurement of a sin(2φ) Current Phase Relation in a Graphene SQUID
  5. (2023) Highly Sensitive Tunable Magnetometer Based on SQUID

All five are genuinely SQUID/sensing-related; result (2) (Wiener-filter SQUID
denoising) is directly on-task. The endpoint, envelope unwrapping, per-paper
mapping, filter-free query, and metadata-only (no per-result PDF fetch) behavior
are confirmed working. Commit 4's dynamic-search loop will exercise it for real.

**Search-direction note (domain).** Future dynamic-search queries should actively
seek **full-spectrum** denoising architectures, not frequency-split ones. The
TIDMAD model zoo (FCNet/PUNet/Transformer/RNN under frequency splitting) is a
**negative example** of what to search for — re-discovering frequency-split-
optimized architectures would mislead the proposer. Queries should target
architectures evaluated on broadband / full-spectrum 1-D signal denoising.
(Commit 4's search-loop prompt should encode this preference.)

---

## 6. Rate-limit behavior (incidental)

The pilot issued 3 S2 requests (2 resolve metadata + 1 search) plus 2 arxiv PDF
downloads. No 429s; the `_throttle_s2` 1-req/s pacing ran silently. PDF downloads
hit `arxiv.org` and were (correctly) not S2-throttled.

---

## Implications for Commit 3

Consolidated, concrete instructions for whoever implements Commit 3:

1. **Single LLM call over the full text — no chunking** (F2). ~18k-token root
   papers fit one prompt.
2. **No `key_equations` field** — describe mathematical methods in prose only (F3).
3. **Compression prompt must explicitly instruct the LLM to**: ignore `(cid:NN)`
   glyph artifacts; ignore margin stamps and author affiliations/emails; tolerate
   run-together words (the despacing artifact) (F3 + §2 noise findings).
4. **Treat the arxiv fallback as the primary download path** in the node's error
   handling and logging — an empty `openAccessPdf.url` for an arXiv source is
   normal, not an error (F1).
5. **`architecture_details` should ask specifically for**: model type, layer
   structure, key design choices, and how the approach compares to alternatives
   described in the paper (F4).
6. **Inject the frequency-split incompatibility into the compression prompt**
   (domain knowledge the LLM cannot infer from the paper). Required instruction:
   > *"The TIDMAD paper benchmarks models under a frequency-split training
   > setting. SIDERIUS uses full-spectrum training. When extracting
   > `architecture_details` and `key_results`, you MUST note this
   > incompatibility explicitly. Do NOT present performance rankings from this
   > paper as general conclusions — qualify every comparison with 'under
   > frequency-split training'. WaveNet is the only model in this benchmark
   > trained in a full-spectrum setting."*
7. **Checkpoint B must verify the qualifier is present.** If the produced
   `PaperExtract`'s `architecture_details`/`key_results` rank
   FCNet/PUNet/Transformer/RNN without the frequency-split qualifier, treat the
   compression as **failed** and revise the prompt before proceeding —
   regardless of other quality criteria.

---

## Known limitations

- **pdfplumber layout sensitivity.** Extraction quality depends on PDF layout.
  Single-column PDFs (like TIDMAD) extract with despacing + `(cid:NN)` artifacts
  (§2 / F3). Two-column layouts can interleave columns into the text stream;
  image-only / scanned PDFs yield no extractable text at all. The skill does not
  detect or correct any of this — a poorly-extracted paper feeding the proposer
  is a known risk, partially mitigated by the compression-prompt instructions in
  "Implications for Commit 3". Empty extraction is now handled defensively: an
  image-only PDF resolves to `verbosity_achieved=0` (with a warning log) rather
  than a silent empty success (Commit 2 empty-extraction fix).
- **OpenReview / S2 coverage.** S2 does not reliably index OpenReview forum URLs,
  and there is no OpenReview-API fallback yet. The URL-encoding bug that
  truncated `?id=…` is fixed, so the limiter is genuine S2 coverage. See
  `external_agents_for_proposer.md` §9; the real-API test for `openreview` is
  `xfail` until coverage lands.
