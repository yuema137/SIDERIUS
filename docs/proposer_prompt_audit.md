# Checkpoint P — Proposer pipeline-mode prompt audit (2026-06-18)

Self-contained artifact produced by `scripts/render_proposer_prompts_for_audit.py`. The rendered prompts below are the exact strings the proposer's LLM would see in a production pipeline-mode run, captured with the LLM bridge mocked (zero LLM calls). See `docs/commit_plan_ml_literature_review.md` § "Behavioral Checkpoint P" for the 9 sub-criteria.

## Source commits

- P-a (cite_id → source_ref) — `0c280ba`
- P-b (trust_level + source_type/source_id) — `a629e4a`
- P-c (multi-source synthesis prompt) — `69e7234`
- P-d (pipeline-mode fixes + position bias) — `aeb4d9f`
- P-e (doc closure + status board) — `6348ece`

## Synthetic input shape

- `inp.agent_cards`: 1 lit-review card (`trust_level=soft_prior`) supplied by caller; 1 `human` card (`trust_level=strong_prior`) appended by the protocol's `human_advice` wrap path.
- `inp.expert_context`: 1 lit-review finding (`source_ref=arxiv:2312.00752`) supplied by caller; 1 wrapped human directive (`source_ref=human:human_advice`) appended by the same protocol path.
- `inp.constraints`: `['VRAM < 10 GB', 'params < 50M']`.
- `inp.hardware_context`: synthetic RTX 3090 manifest, `device_available=True`, PHYSICAL regime (no operator budget).
- `inp.human_advice`: realistic operator directive about low-freq targeting.
- `reasoning_pipeline`: standard 2-stage (`comparison` + `causal_reasoning`) + the implicit proposing stage, `exploration_mode=explore`.

## Pre-check verdicts (automated)

- **S6 — causal_reasoning_stage.md has the new MANDATORY Multi-source synthesis block** — ✅ PASS
  - Header literal `## MANDATORY — Multi-source synthesis` present.
- **S6 — causal_reasoning_stage.md Rule 1 is Evidence-backed (two sources)** — ✅ PASS
  - Rule 1 header `**Evidence-backed**` + both ModelComparison and ExpertContextItem mentions + trust_level gate.
- **S6 — no hardcoded `Literature agents:` / `Physics agents:` / `Human directives: always take precedence` phrases in any base proposal prompt** — ✅ PASS
  - Hardcoded trust-hierarchy strings absent from the 3 base prompts.
- **S7 — no `expert_advice` field-name reference in rendered USER prompts (system prompts retain it as the ProposalOutput field for the LLM to emit)** — ✅ PASS
  - User-prompt assembly carries no inp.expert_advice (it was hard-removed in P-d).
- **S7 — no `cite_id` literal in rendered prompts** — ✅ PASS
  - Pure rename — every `cite_id` became `source_ref` in P-a.
- **S8 — comparison_stage.md Rule 4 allows external signals with provenance** — ✅ PASS
  - Rule 4 contains the no-promotion-on-external-evidence guard + explicit provenance language + arxiv: example.
- **S8 — no hardcoded trust-hierarchy phrases in any of the 6 *_explore.md/*_exploit.md files** — ✅ PASS
  - Checked 6 files.
- **S8 — every mode file's Operating Mode block references `trust_level`-weighted findings (not 'Advice JSON')** — ✅ PASS
  - All 6 files mention `trust_level` and contain no `Advice JSON` reference (P-c rewrite + P-c extra sweep).
- **S9 — rendered user prompts contain literal `Trust Level: soft_prior` (lit-review card)** — ✅ PASS
  - Substring search across every captured user prompt.
- **S9 — rendered user prompts contain literal `Trust Level: strong_prior` (synthesized human card)** — ✅ PASS
  - Substring search across every captured user prompt.

## Rendered prompts (1 entry per LLM call)

### Call 1 — `proposer.comparison`

**System prompt** (7492 chars):

```
# Stage 1: Comparative Analysis

You are a senior ML research scientist conducting a systematic review of all
previously tested model architectures.

## Your task

Analyze each candidate model and produce a structured comparison. You are NOT
proposing anything yet — you are gathering evidence. Your output feeds into the
next stage (causal reasoning), which will form a hypothesis.

## What you receive

- **Candidate models**: pre-filtered list of past models with their scores,
  configs, file_vectors, architecture descriptions, AND **source code**. Read
  the source code carefully — it is the ground truth of what each model does.
  The description may be imprecise; the code is exact.
- **Vocabulary**: the current feature/capability vocabulary (canonical + candidates).
  Use these terms consistently when referring to architectural building blocks.
- **Expert context**: upstream findings, human directives, and strategy reports.
- **Contributors** (when present): external agents contributing findings this round.
  Read the Contributors section before the Expert Context. Each contributor's
  `Trust Level` field in the Contributors block is the authoritative
  calibration. The full multi-source synthesis rules live in the
  causal-reasoning stage prompt and govern how findings combine with
  experiment data; here at the comparison stage, treat external findings
  as candidate vocabulary signals — record provenance in each
  `proposed_vocab_link.evidence` (see Rule 4 below).

## How to analyze each model

For each candidate, you MUST:
1. **Read the source code** and identify which vocabulary features it actually
   uses. Do not guess from the description — verify in the code.
2. **Map code patterns to vocabulary features** explicitly. Reference
   specific lines or patterns you found in the source.
3. **Note implementation details** that are critical for the implementor —
   any architectural patterns that are NOT obvious from the description alone.
   The implementor will receive the reference code, but may miss subtle
   wiring details unless you call them out explicitly.

## What you produce

A JSON object with these fields:

```json
{
  "comparisons": [
    {
      "model_type": "wavenet",
      "source": "seed",
      "best_score": 5.57,
      "key_mechanism": "One sentence: what makes this model tick. Must reference a specific feature from the vocabulary, e.g. 'dilated_causal_conv provides exponential receptive field growth.'",
      "strengths": ["Tied to file_vector evidence, e.g. 'strong on files 10-19 (high freq)'"],
      "weaknesses": ["Tied to file_vector evidence, e.g. 'near-zero on files 0-4 (low freq)'"],
      "lesson_for_next_proposal": "What to inherit or avoid from this model."
    }
  ],
  "proposed_vocab_links": [
    {
      "feature": "dilated_causal_conv",
      "capability": "receptive_field",
      "evidence": "Wavenet uses dilated_causal_conv and scores 5.57 on high-freq files. Models without this feature score below 2.0 on the same files.",
      "status": "proposed"
    }
  ],
  "proposed_vocab_candidates": [
    {
      "name": "log_spaced_fno_gates",
      "kind": "feature",
      "description": "Gated FNO with log-spaced frequency bins — observed in 2 of top 3 models."
    }
  ],
  "sota_model_type": "wavenet",
  "sota_score": 5.57,
  "sota_mechanism": "Why the SOTA works — reference specific features and their measured effects."
}
```

## Rules

1. **One ModelComparison per candidate model.** Do not skip any model in the
   candidate list. If a model has insufficient data, say so in the
   key_mechanism field.

2. **Use vocabulary terms.** When referring to architectural building blocks,
   use the canonical feature names from the vocabulary (e.g. `dilated_causal_conv`,
   not "dilated convolutions" or "causal conv layers"). This consistency is what
   allows the system to track patterns across rounds.

3. **Tie claims to evidence.** Every strength and weakness must reference
   specific file_vector indices, scores, or config values. "Good architecture"
   is not a strength. "Scores 8.2 on files 15-19 (highest freq)" is.

4. **Propose feature-capability links as hypotheses.** When you notice a
   pattern between a feature and a capability, propose it as a
   `proposed_vocab_link`. These are HYPOTHESES, not facts — they will be
   tested in the next experiment. Cite specific model results as evidence.
   Confirmation of a link requires data from THIS project — only experiment
   results count as confirmation. Literature signals or other external
   findings may *suggest* a link worth testing; when they do, record the
   provenance explicitly in the link's `evidence` field (e.g. "Suggested by
   `arxiv:2312.00752`; not yet confirmed by this project's experiments").
   Do not promote a link to confirmed status on external evidence alone.

5. **Propose new vocabulary candidates.** If you see a pattern across models
   that doesn't fit any existing vocabulary entry, propose it as a candidate
   with a name, kind (feature or capability), and description.

6. **Suggest ablation experiments.** For the SOTA model's key features,
   note which ones could be ablated to test their isolated contribution.
   E.g. "Removing dilated_causal_conv from wavenet and replacing with
   standard convolutions would test whether the dilation pattern is
   the actual driver of the high-freq performance."

# Comparison Stage — EXPLORE Mode

## Contract Hierarchy

The trust hierarchy and multi-source synthesis rules are defined in the
base prompt (see the *Multi-source synthesis* MANDATORY block). Apply them
as written; this block governs exploration/exploitation posture only.

## Operating Mode

You are operating in **EXPLORE** mode. 0 agent-proposed
models tested so far. Your strategic posture for this iteration comes from
(a) the Contributors block's `trust_level`-weighted findings, (b) the
experiment history's `take_home_message`, and (c) any `mindset` override
that replaced this block (when none is set, the default EXPLORE/EXPLOIT
posture applies). **EXPLORE posture**: prioritize unexplored mechanisms —
`soft_prior` findings that suggest directions experiment history has not
yet tried are first-class motivators, not side notes.

## Methodology — source-code reading

- Read the SOTA's source code carefully. Map every architectural pattern you
  can identify to vocabulary features (canonical or candidate). Cite features
  by their registry names.
- For each feature you observe, note which capability it likely provides — but
  only as a hypothesis. With limited evidence, frame these as questions:
  "I hypothesize that feature_X enables capability_Y based on this score, but
  this has NOT been experimentally confirmed."
- Surface implementation-critical details the implementor must know:
  non-obvious wiring, unused paths, initialization requirements you find in
  the reference code.

## Methodology — honest uncertainty

- Be explicit about what is not yet known. If the mechanism behind a score is
  unclear, say so: "the mechanism is unclear — this needs a controlled
  experiment."
- The comparison should surface candidate gaps. Whether to act on a gap,
  and in which direction, is governed by the Contributors block's
  `trust_level`-weighted findings together with experiment history — not
  by template defaults.


## Output format

Return a single JSON object matching the schema above. No preamble,
no markdown fences, no commentary outside the JSON.
```

**User prompt** (18792 chars):

```
[HARDWARE CONTEXT]
Device:            NVIDIA RTX 3090
Total VRAM:        24.00 GB
Usable cap (80%):  19.20 GB
Host:              checkpoint-p-audit-host
Regime:            PHYSICAL — no operator budget set; cap = 19.20 GB.

Your baseline_config must fit within the **effective cap** shown above. The VRAM engine will reject any architecture whose predicted peak exceeds this ceiling; a rejection consumes a tuner attempt with no scored round. Size your baseline to stay comfortably below the cap (target ≤ 80% of the effective cap at baseline) so the tuner has headroom to vary batch_size and segmentation_size upward.

## Constraints
Existing model type keys (your `model_name` must NOT be any of these): ['punet', 'wavenet']
  - VRAM < 10 GB
  - params < 50M

## External Contributors

Read each contributor's trust level and trust guidance before reading their findings.

### ml_literature_review
  Trust Level: soft_prior
  Role: Surface ML denoising literature relevant to the current iteration.
  Expertise Domain: ML denoising architectures; Semantic Scholar corpus.
  Coverage: ArXiv/S2 results any year; local PDFs in reference_data/.
  Limitations: Cannot run experiments; cannot judge SQUID-specific applicability without empirical confirmation.
  Trust Guidance: Treat findings as inspirational priors — experiment runs are required to confirm applicability before adoption.

### human
  Trust Level: strong_prior
  Role: Human operator providing direct guidance for this iteration.
  Expertise Domain: Task-specific operational knowledge and strategic intent.
  Coverage: This iteration only — human_advice is per-run, not accumulated across iterations.
  Limitations: May not have full visibility into all past experiment results.
  Trust Guidance: Human directives carry strong_prior weight — treat them comparably to experiment data. Override only with explicit justification.


## Expert Context

[HUMAN DIRECTIVE] (from human, source_ref=human:human_advice)
  Prioritize low-frequency recovery; tolerate up to 12 GB VRAM if the extra capacity directly improves files 0-3. Avoid frequency-split training — keep the full-spectrum setting locked.

[LITERATURE REFERENCE] (from ml_literature_review, confidence=0.85, source_ref=arxiv:2312.00752)
  **Implication:** A frequency-aware composite loss may widen wavenet's effective spectral coverage on low-freq files (bottleneck 1).

**Mechanism:** Composite loss $\min_\theta \delta L^f + (1-\delta) L^t$ (FreLE), where $L^f$ is the Fourier-magnitude loss and $L^t$ is the time-domain reconstruction loss; $\delta \in [0, 1]$ trades off the two. Lifted verbatim from the source paper's Eq. 4.

**Adaptation:** Apply the composite loss directly to the wavenet decoder with the clean signal's Fourier magnitudes as the spectral target. Keep wavenet's dilated_causal_conv backbone unchanged.


## Candidate Models — detailed view

### Candidate: wavenet

_Score table unavailable._

#### Source Code
```python
class CausalConv1d(nn.Module):
    """Causal convolution — no future information leakage."""

    def __init__(self, in_channels, out_channels, kernel_size, dilation=1):
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels, kernel_size, padding=self.padding, dilation=dilation
        )

    def forward(self, x):
        x = self.conv(x)
        if self.padding > 0:
            x = x[:, :, : -self.padding]
        return x



class WaveNetBlock(nn.Module):
    """Single WaveNet residual block with dilated causal convolution."""

    def __init__(self, residual_channels, gate_channels, skip_channels, kernel_size, dilation):
        super().__init__()
        self.causal_conv = CausalConv1d(residual_channels, gate_channels, kernel_size, dilation)
        half = gate_channels // 2
        self.gate_conv = nn.Conv1d(half, half, 1)
        self.filter_conv = nn.Conv1d(half, half, 1)
        self.residual_conv = nn.Conv1d(half, residual_channels, 1)
        self.skip_conv = nn.Conv1d(half, skip_channels, 1)

    def forward(self, x):
        residual = x
        x = self.causal_conv(x)
        filter_part, gate_part = torch.chunk(x, 2, dim=1)
        x = torch.tanh(self.filter_conv(filter_part)) * torch.sigmoid(self.gate_conv(gate_part))
        skip = self.skip_conv(x)
        res_out = self.residual_conv(x)
        if res_out.size(-1) != residual.size(-1):
            residual = residual[:, :, : res_out.size(-1)]
        return residual + res_out, skip



class SimpleWaveNet(nn.Module):
    """
    WaveNet-style model for ADC denoising.
    Input:  [B, T]  — integer ADC values (0-255)
    Output: [B, 256, T] — class logits per time step
    """

    def __init__(self, config: WaveNetConfig):
        super().__init__()
        self.embedding = nn.Embedding(256, config.input_channels)
        self.input_conv = nn.Conv1d(config.input_channels, config.residual_channels, 1)
        self.blocks = nn.ModuleList(
            [
                WaveNetBlock(
                    config.residual_channels,
                    config.gate_channels,
                    config.skip_channels,
                    config.kernel_size,
                    2**i,
                )
                for i in range(config.num_blocks)
            ]
        )
        self.output_conv1 = nn.Conv1d(config.skip_channels, config.skip_channels, 1)
        self.output_conv2 = nn.Conv1d(config.skip_channels, 256, 1)

    def forward(self, x):
        x = self.embedding(x.long())  # [B, T, input_channels]
        x = x.transpose(1, 2)  # [B, input_channels, T]
        x = self.input_conv(x)
        # WaveNetConfig.num_blocks is constrained ``ge=1`` by Pydantic, so
        # self.blocks is guaranteed non-empty. Seed skip_sum from the first
        # block's skip output (instead of None + an in-loop branch) so the
        # accumulator is unambiguously a Tensor — no Optional, no assert,
        # identical end state to the previous None-initialised pattern.
        first_block, *rest_blocks = self.blocks
        x, skip_sum = first_block(x)
        for block in rest_blocks:
            x, skip = block(x)
            min_len = min(skip_sum.size(-1), skip.size(-1))
            skip_sum = skip_sum[:, :, :min_len] + skip[:, :, :min_len]
        x = F.relu(skip_sum)
        x = F.relu(self.output_conv1(x))
        return self.output_conv2(x)  # [B, 256, T]


# ==========================================
# RNNSeq2Seq
# ==========================================


```

---

### Candidate: punet

_Score table unavailable._

#### Source Code
```python
class PositionalUNet(nn.Module):
    """
    Dynamic Positional U-Net for Agent Sandbox.

    The architecture scales automatically based on the 'depth' parameter.
    Agent can optimize: multi, depth, bilinear, pe_factor, etc.
    """

    def __init__(self, config: PUNetConfig):
        super().__init__()

        # visit properties directly, as the input was valudated by pydantic
        self.multi = config.multi
        self.depth = config.depth
        self.bilinear = config.bilinear
        self.seg_size = config.segmentation_size
        self.pe_factor = config.pe_factor
        self.kernel_size = config.kernel_size
        self.padding = int((self.kernel_size - 1) / 2)

        adc_channel = 256
        emb_dim = config.embedding_dim

        # 1. Input layers
        self.embedding = nn.Embedding(adc_channel, emb_dim, scale_grad_by_freq=True)
        self.pe_in = PositionalEncoding(emb_dim, max_len=self.seg_size, factor=self.pe_factor)
        self.inc = DoubleConv(
            emb_dim, self.multi, kernel_size=self.kernel_size, padding=self.padding
        )
        self.pe_inc = PositionalEncoding(self.multi, max_len=self.seg_size, factor=self.pe_factor)

        # 2. Downward Path (Encoder)
        self.downs = nn.ModuleList()
        self.pe_downs = nn.ModuleList()

        curr_ch = self.multi
        for i in range(self.depth):
            out_ch = curr_ch * 2
            # different calculation for bilinear case
            if i == self.depth - 1:
                factor = 2 if self.bilinear else 1
                out_ch = out_ch // factor

            self.downs.append(
                Down(curr_ch, out_ch, kernel_size=self.kernel_size, padding=self.padding)
            )
            self.pe_downs.append(
                PositionalEncoding(out_ch, max_len=self.seg_size, factor=self.pe_factor)
            )
            curr_ch = out_ch

        # 3. Upward Path (Decoder)
        self.ups = nn.ModuleList()
        self.pe_ups = nn.ModuleList()

        # Up: reversal of down
        for i in range(self.depth):
            up_in_ch = curr_ch * 2
            up_out_ch = curr_ch // 2
            # align the top layer output
            if i == self.depth - 1:
                up_out_ch = self.multi // (2 if self.bilinear else 1)

            self.ups.append(
                Up(
                    up_in_ch,
                    up_out_ch,
                    self.bilinear,
                    kernel_size=self.kernel_size,
                    padding=self.padding,
                )
            )
            self.pe_ups.append(
                PositionalEncoding(up_out_ch, max_len=self.seg_size, factor=self.pe_factor)
            )
            curr_ch = up_out_ch

        # 4. Output layer
        self.outc = OutConv(curr_ch, adc_channel)

    def forward(self, x):
        x = self.embedding(x).transpose(-1, -2)
        x = self.pe_in(x)

        # 1. Input layer and first skip
        x1 = self.pe_inc(self.inc(x))
        # store intermediate result for Skip Connection
        skip_outputs = [x1]

        # 2. Downward path
        curr_x = x1
        for i in range(self.depth - 1):  # Only store until the second to last layer
            curr_x = self.downs[i](curr_x)
            curr_x = self.pe_downs[i](curr_x)
            skip_outputs.append(curr_x)

        # 3. Bottom layer (no skip storage)
        curr_x = self.downs[-1](curr_x)
        curr_x = self.pe_downs[-1](curr_x)

        # 4. Upward path
        for i in range(self.depth):
            skip_x = skip_outputs.pop()
            curr_x = self.ups[i](curr_x, skip_x)
            curr_x = self.pe_ups[i](curr_x)

        return self.outc(curr_x)



class DoubleConv(nn.Module):
    """
    A foundational building block consisting of two consecutive 1D convolutional layers,
    each followed by Batch Normalization and LeakyReLU activation.

    Agent-Adjustable Parameters:
    - kernel_size: Defines the receptive field. Larger values capture broader wave features.
    - padding: Maintains the temporal resolution. Must be tuned with kernel_size to avoid shape mismatch.
    - bias: Toggles the additive bias. Typically False when used with BatchNorm.
    """

    def __init__(
        self, in_channels, out_channels, mid_channels=None, kernel_size=9, padding=4, bias=False
    ):
        super().__init__()
        if not mid_channels:
            mid_channels = out_channels
        self.double_conv = nn.Sequential(
            nn.Conv1d(
                in_channels, mid_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
            nn.BatchNorm1d(mid_channels),
            nn.LeakyReLU(inplace=True),
            nn.Conv1d(
                mid_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
            nn.BatchNorm1d(out_channels),
            nn.LeakyReLU(inplace=True),
        )

    def forward(self, x):
        return self.double_conv(x)



class Down(nn.Module):
    """
    Adjustable parameters for the Agent:
    - stride: The downsampling factor (default 4).
             Larger stride saves memory but may lose signal resolution.
    - kernel_size, padding, bias: Passed to DoubleConv to define feature extraction.
    """

    def __init__(self, in_channels, out_channels, stride=4, kernel_size=9, padding=4, bias=False):
        super().__init__()
        # pass stride to MaxPool1d,pass kernel size and padding to DoubleConv
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool1d(kernel_size=stride, stride=stride),
            DoubleConv(
                in_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
        )

    def forward(self, x):
        return self.maxpool_conv(x)



class Up(nn.Module):
    """
    Upsampling block that increases temporal resolution.

    Agent-Adjustable Parameters:
    - bilinear: If True, uses Upsample (linear mode). If False, uses ConvTranspose1d.
    - stride: The upsampling factor (default 4).
    - kernel_size: Parameters passed to the DoubleConv layer.
    """

    def __init__(
        self,
        in_channels,
        out_channels,
        bilinear=True,
        stride=4,
        kernel_size=9,
        padding=4,
        bias=False,
    ):
        super().__init__()

        # Calculate padding to maintain sequence length: p = (k-1)/2
        padding = (kernel_size - 1) // 2

        if bilinear:
            # For bilinear, we use nn.Upsample which doesn't change channels.
            # The channel reduction happens inside DoubleConv's mid_channels.
            self.up = nn.Upsample(scale_factor=stride, mode="linear", align_corners=True)
            self.conv = DoubleConv(
                in_channels,
                out_channels,
                in_channels // 2,
                kernel_size=kernel_size,
                padding=padding,
                bias=bias,
            )
        else:
            # For ConvTranspose1d, it reduces channels by half during the upsampling step.
            self.up = nn.ConvTranspose1d(
                in_channels, in_channels // 2, kernel_size=stride, stride=stride
            )
            # After concatenation with skip connection, the input to DoubleConv returns to in_channels logic
            self.conv = DoubleConv(
                in_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            )

    def forward(self, x1, x2):
        # x1: incoming feature map from the lower layer
        # x2: skip connection feature map from the downward path
        x1 = self.up(x1)

        # Temporal alignment (handling odd lengths or stride mismatches)
        # x.size() -> [Batch, Channel, Length]
        diff = x2.size()[2] - x1.size()[2]
        if diff != 0:
            x1 = F.pad(x1, [diff // 2, diff - diff // 2])

        # Concatenate along the channel dimension
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)



class OutConv(nn.Module):
    """
    Final output layer that maps feature channels to the physical ADC channel space (256).

    Agent-Adjustable Parameters:
    - bias: Toggles the additive bias for the final projection.
    """

    def __init__(self, in_channels, out_channels, bias=True):
        super().__init__()
        # We keep kernel_size=1 to perform point-wise classification across channels
        self.conv = nn.Sequential(
            torch.nn.Conv1d(in_channels, out_channels, kernel_size=1, bias=bias),
        )

    def forward(self, x):
        return self.conv(x)



class PositionalEncoding(nn.Module):
    """
    Injects temporal position information into the latent space.
    Crucial for phase-coherent dark matter signals.

    Agent-Adjustable Parameters:
    - max_len: Must match the current 'segmentation_size'. Defines the temporal buffer.
    - factor: The strength of positional information.
    - dropout: Regularization strength to prevent the model from over-relying on position.
    """

    def __init__(self, d_model, max_len, start=0, dropout=0.1, factor=1.0):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        self.factor = factor
        self.start = start

        # Generate the sinusoid positional encoding matrix up to max_len
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)

        # Reshape to (1, d_model, max_len) to match Conv1d input format [Batch, Channel, Time]
        pe = pe.unsqueeze(0).transpose(1, 2)

        # Register as buffer (fixed during training, moved with model to GPU)
        self.register_buffer("pe", pe)

    def forward(self, x):
        """
        Adds positional encoding to the input tensor.
        x shape: [Batch, d_model, Length]
        """
        # Slice the pre-computed pe buffer to match the input length. The
        # `cast` is a no-op at runtime; it tells pyright that `self.pe` (which
        # PyTorch's stub returns as `Module` from `register_buffer` lookup) is
        # actually the Tensor we registered above, so `[:, :, ...]` is valid.
        x = (
            x
            + self.factor * cast(torch.Tensor, self.pe)[:, :, self.start : (self.start + x.size(2))]
        )
        x = self.dropout(x)
        return x


```

---

## Accumulated context

```json
{
  "candidates": [
    {
      "model_type": "wavenet",
      "best_score": 5.57,
      "worst_score": 2.1,
      "model_params": null,
      "description": "Dilated causal convolutional network \u2014 current SOTA.",
      "training_segments": null,
      "source": "seed"
    },
    {
      "model_type": "punet",
      "best_score": 1.2,
      "worst_score": 0.4,
      "model_params": null,
      "description": "U-Net baseline for 1-D signal denoising.",
      "training_segments": null,
      "source": "seed"
    }
  ],
  "non_candidates_overview": [],
  "interpretation_summary": {
    "model_types": [
      "punet",
      "wavenet"
    ],
    "total_experiments": 2,
    "best_denoising_score": 5.57,
    "worst_denoising_score": 0.4,
    "key_findings": [
      "wavenet's dilated_causal_conv stack drives high-freq performance.",
      "punet plateaus at depth=6; deeper variants saw no lift."
    ],
    "bottlenecks": [
      "Low-frequency files (0-3) remain weak across all models.",
      "Wavenet's receptive field saturates before low-freq capture."
    ],
    "take_home_message": "Next iteration: target low-freq recovery via a richer frequency-aware mechanism while inheriting wavenet's high-freq strength.",
    "per_model_best": {
      "punet": 1.2,
      "wavenet": 5.57
    },
    "per_model_worst": {
      "punet": 0.4,
      "wavenet": 2.1
    },
    "cumulative_information_gain": 0.0,
    "prediction_outcomes_history": {
      "confirmed": 0,
      "partial": 0,
      "refuted": 0
    }
  },
  "existing_model_types": [
    "punet",
    "wavenet"
  ],
  "previous_failures": []
}
```
```

---

### Call 2 — `proposer.causal_reasoning`

**System prompt** (9902 chars):

```
# Stage 2: Causal Reasoning

You are a senior ML research scientist. You have just reviewed a systematic
comparison of all candidate models (Stage 1 output). Now form a CAUSAL
HYPOTHESIS about what to try next.

## Your task

Based on the comparisons, propose what to try next and articulate WHY it
should improve performance. Your output is the core of the DiscoveryMemo —
it must be falsifiable, comparative, and architecturally concrete.

## What you receive

- **Stage 1 output**: the list of ModelComparisons, SOTA identification,
  proposed vocab links, and ablation suggestions.
- **Vocabulary**: current features/capabilities with any confirmed links.
- **Expert context**: upstream findings, human directives, strategy reports.
- **Contributors** (when present): external agents contributing findings this round.
  Read the Contributors section before the Expert Context. Each contributor's
  `Trust Level` field in the Contributors block is the authoritative calibration.
  Apply the synthesis rules in the *Multi-source synthesis* MANDATORY block
  below based on that field — do not pattern-match agent names.
- **Previous Failed Proposals** (when present): may include one or more
  `[PHYSICAL REJECTION]` blocks emitted by the tuner's VRAM engine. Each
  block names the rejected `model_type`, the dominant layer that caused
  the OOM, the effective cap, the predicted peak, and the overshoot
  multiplier. These are evidence from the physical device — not opinions.
- **[HARDWARE CONTEXT]** block (always present when a live GPU manifest is
  available): reports the active device, total VRAM, and the "Effective cap"
  (the hard ceiling any proposal must fit under).

## MANDATORY — Integrated reasoning (science + engineering)

You are both a scientist and an engineer. Your design session is governed
by two constraint systems that must be satisfied *simultaneously*, not
sequentially:

  (a) the **scientific goals** from the Stage 1 comparisons and upstream
      interpretation (e.g. "improve frequency resolution", "capture
      long-range dependencies"), AND
  (b) the **physical constraints** from any `[PHYSICAL REJECTION]` blocks
      under *Previous Failed Proposals* together with the "Effective cap"
      in the `[HARDWARE CONTEXT]` block.

If one or more `[PHYSICAL REJECTION]` blocks are present in the user
message, you MUST treat the previous failure as a **design constraint to
be solved alongside the scientific bottlenecks** — not a historical
footnote. Your `causal_hypothesis` must be a single integrated paragraph
that:

  - names the scientific bottleneck you are addressing (from the Stage 1
    comparisons), AND
  - names the physical failure that defeated the previous proposal — cite
    the rejected `model_type`, the dominant layer that caused the OOM,
    and the overshoot evidence (Effective cap vs Predicted peak), AND
  - explains how your new architecture achieves the desired scientific
    improvement *while remaining strictly within the "Effective cap"* that
    defeated the previous proposal — i.e. the structural choice must do
    both jobs at once.

A `causal_hypothesis` that addresses only the scientific bottleneck with
no mention of the physical rejection, OR one that addresses only the VRAM
cap with no scientific rationale, is incomplete. Cite the previous failure
as a design constraint to be solved alongside the scientific bottlenecks.

## MANDATORY — Multi-source synthesis

Before forming your hypothesis, synthesize all available evidence channels:

1. **Experiment history** (the ModelComparisons from Stage 1) — your primary
   evidence base. What has been tried; what worked; what failed.
2. **Expert context items** (the Expert Context block) — weight each item by
   its contributor's `trust_level` (visible in the Contributors block):
   - `hard_limit`: non-negotiable constraint. Your hypothesis MUST NOT
     violate it.
   - `strong_prior`: weight comparably to experiment data. Override only
     with explicit justification citing why the experimental evidence
     outweighs it.
   - `soft_prior`: inspirational prior. Experiment data takes precedence
     on conflict; you may use it to motivate exploration beyond what
     experiment history has tried.

A finding from any source at `trust_level=strong_prior` or higher may
directly motivate your `proposed_change`, not just inform it. Record its
`source_ref` in `source_refs` when it materially changes your hypothesis.

This rule is generic over `trust_level` values, not over agent type names.
The proposer reads `Trust Level` off the card; it does not pattern-match
"Literature agents" or "Physics agents" or any other prose label.

## What you produce

A JSON object with these fields:

```json
{
  "proposed_change": "What the new model tries. Can be a targeted delta on the SOTA ('add Z', 'replace X with Y') or a novel architecture ('design from scratch using mechanism M'). Be specific and architecturally concrete.",
  "causal_hypothesis": "WHY this should improve the score. Must reference: (a) the bottleneck being addressed, (b) the mechanism that addresses it, (c) why existing models fail to address it. Max 600 chars.",
  "falsifiable_prediction": {
    "metric": "What to measure, e.g. 'mean(file_vector[0:5])' or 'denoising_score'",
    "current_value": 1.5,
    "predicted_value": 2.5,
    "threshold_for_refutation": 1.2,
    "rationale": "Why this specific predicted value."
  },
  "predicted_failure_modes": [
    "At least one way the proposal could fail. E.g. 'FNO layer may exceed VRAM budget at segmentation_size > 20000'.",
    "A second failure mode (optional but encouraged)."
  ],
  "inherited_components": [
    {
      "component": "dilated_causal_conv",
      "source_type": "experiment",
      "source_id": "wavenet",
      "contribution_evidence": "Core mechanism of wavenet's 5.57 SOTA score."
    }
  ]
}
```

## Rules — the four structural teeth

1. **Evidence-backed**: every claim in `causal_hypothesis` must reference
   either (a) a specific ModelComparison from Stage 1, or (b) an
   ExpertContextItem whose contributor's `trust_level` is `strong_prior`
   or `hard_limit`. Cite the `source_ref` explicitly in either case
   (model_type for ModelComparisons, the item's `source_ref` for expert
   context). A claim with no source from either lens is rejected as
   unsupported.

2. **Falsifiable**: your `falsifiable_prediction` must commit to a SPECIFIC
   NUMERICAL OUTCOME. The boldness (abs(predicted - current) / abs(current))
   must be at least 0.05. Timid predictions (boldness < 0.05)
   are rejected as uninformative. Be ambitious — a confirmed bold prediction
   is worth more than 10 confirmed timid ones.

3. **Devil's advocate**: name at least one realistic failure mode. "It might
   not work" is not a failure mode. "The FNO layer doubles memory usage and
   may exceed the 10 GB VRAM budget" is.

4. **Architecturally tethered**: the `proposed_change` must be concrete
   enough for the proposing stage (Stage 3) to implement it unambiguously.
   If Stage 3 diverges from your description, it must document the deviation.

## Additional rules

5. **Inherit explicitly.** Every architectural primitive or technique you
   carry over from any source — past experiment, external agent finding,
   or human directive — must appear in `inherited_components` with the
   appropriate `source_type` (`experiment` / `external_agent` / `human`)
   and `source_id`. Do not silently reuse a feature without attribution.

6. **Cite sparingly.** If expert context items influenced your hypothesis,
   list their `source_ref` values. Cite ONLY items that materially changed your
   reasoning. Maximum 5 citations.

# Causal Reasoning Stage — EXPLORE Mode

## Contract Hierarchy

The trust hierarchy and multi-source synthesis rules are defined in the
base prompt (see the *Multi-source synthesis* MANDATORY block). Apply them
as written; this block governs exploration/exploitation posture only.

## Operating Mode

You are operating in **EXPLORE** mode. Your strategic posture for this
iteration comes from (a) the Contributors block's `trust_level`-weighted
findings, (b) the experiment history's `take_home_message`, and (c) any
`mindset` override that replaced this block (when none is set, the default
EXPLORE/EXPLOIT posture applies). **EXPLORE posture**: prioritize
unexplored mechanisms — `soft_prior` findings that suggest directions
experiment history has not yet tried are first-class motivators, not
side notes.

## Methodology — causal_hypothesis structure

A `causal_hypothesis` should explicitly link three things:

1. The bottleneck you believe is limiting current performance — cite evidence
   (per-file gap, score plateau, missing capability) by exp_id, iteration, or
   per-file score where available.
2. The mechanism by which your `proposed_change` addresses that bottleneck.
3. Why this mechanism is expected to work, given the data properties and the
   architecture's cost profile.

Cite vocabulary features and capabilities by their registry names. Cite prior
runs from `evolution_log.jsonl` by exp_id or iteration when referencing past
evidence; do not paraphrase results without a citation.

## Methodology — falsifiable_prediction

A `falsifiable_prediction` must be measurable from the trial-round output:

- Predict a specific score outcome (numerical delta, per-file claim, or
  capability-level signal) that the trial round can confirm or refute.
- A prediction that cannot be wrong is not a hypothesis — restate it more
  sharply, or weaken the boldness with explicit reasoning.
- The Contributors block + Expert Context may identify specific files or
  metric aggregates worth targeting; if so, respect that targeting in the
  prediction.


## Output format

Return a single JSON object matching the schema above. No preamble,
no markdown fences, no commentary outside the JSON.
```

**User prompt** (19888 chars):

```
[HARDWARE CONTEXT]
Device:            NVIDIA RTX 3090
Total VRAM:        24.00 GB
Usable cap (80%):  19.20 GB
Host:              checkpoint-p-audit-host
Regime:            PHYSICAL — no operator budget set; cap = 19.20 GB.

Your baseline_config must fit within the **effective cap** shown above. The VRAM engine will reject any architecture whose predicted peak exceeds this ceiling; a rejection consumes a tuner attempt with no scored round. Size your baseline to stay comfortably below the cap (target ≤ 80% of the effective cap at baseline) so the tuner has headroom to vary batch_size and segmentation_size upward.

## Constraints
Existing model type keys (your `model_name` must NOT be any of these): ['punet', 'wavenet']
  - VRAM < 10 GB
  - params < 50M

## External Contributors

Read each contributor's trust level and trust guidance before reading their findings.

### ml_literature_review
  Trust Level: soft_prior
  Role: Surface ML denoising literature relevant to the current iteration.
  Expertise Domain: ML denoising architectures; Semantic Scholar corpus.
  Coverage: ArXiv/S2 results any year; local PDFs in reference_data/.
  Limitations: Cannot run experiments; cannot judge SQUID-specific applicability without empirical confirmation.
  Trust Guidance: Treat findings as inspirational priors — experiment runs are required to confirm applicability before adoption.

### human
  Trust Level: strong_prior
  Role: Human operator providing direct guidance for this iteration.
  Expertise Domain: Task-specific operational knowledge and strategic intent.
  Coverage: This iteration only — human_advice is per-run, not accumulated across iterations.
  Limitations: May not have full visibility into all past experiment results.
  Trust Guidance: Human directives carry strong_prior weight — treat them comparably to experiment data. Override only with explicit justification.


## Expert Context

[HUMAN DIRECTIVE] (from human, source_ref=human:human_advice)
  Prioritize low-frequency recovery; tolerate up to 12 GB VRAM if the extra capacity directly improves files 0-3. Avoid frequency-split training — keep the full-spectrum setting locked.

[LITERATURE REFERENCE] (from ml_literature_review, confidence=0.85, source_ref=arxiv:2312.00752)
  **Implication:** A frequency-aware composite loss may widen wavenet's effective spectral coverage on low-freq files (bottleneck 1).

**Mechanism:** Composite loss $\min_\theta \delta L^f + (1-\delta) L^t$ (FreLE), where $L^f$ is the Fourier-magnitude loss and $L^t$ is the time-domain reconstruction loss; $\delta \in [0, 1]$ trades off the two. Lifted verbatim from the source paper's Eq. 4.

**Adaptation:** Apply the composite loss directly to the wavenet decoder with the clean signal's Fourier magnitudes as the spectral target. Keep wavenet's dilated_causal_conv backbone unchanged.


## Candidate Models — detailed view

### Candidate: wavenet

_Score table unavailable._

#### Source Code
```python
class CausalConv1d(nn.Module):
    """Causal convolution — no future information leakage."""

    def __init__(self, in_channels, out_channels, kernel_size, dilation=1):
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels, kernel_size, padding=self.padding, dilation=dilation
        )

    def forward(self, x):
        x = self.conv(x)
        if self.padding > 0:
            x = x[:, :, : -self.padding]
        return x



class WaveNetBlock(nn.Module):
    """Single WaveNet residual block with dilated causal convolution."""

    def __init__(self, residual_channels, gate_channels, skip_channels, kernel_size, dilation):
        super().__init__()
        self.causal_conv = CausalConv1d(residual_channels, gate_channels, kernel_size, dilation)
        half = gate_channels // 2
        self.gate_conv = nn.Conv1d(half, half, 1)
        self.filter_conv = nn.Conv1d(half, half, 1)
        self.residual_conv = nn.Conv1d(half, residual_channels, 1)
        self.skip_conv = nn.Conv1d(half, skip_channels, 1)

    def forward(self, x):
        residual = x
        x = self.causal_conv(x)
        filter_part, gate_part = torch.chunk(x, 2, dim=1)
        x = torch.tanh(self.filter_conv(filter_part)) * torch.sigmoid(self.gate_conv(gate_part))
        skip = self.skip_conv(x)
        res_out = self.residual_conv(x)
        if res_out.size(-1) != residual.size(-1):
            residual = residual[:, :, : res_out.size(-1)]
        return residual + res_out, skip



class SimpleWaveNet(nn.Module):
    """
    WaveNet-style model for ADC denoising.
    Input:  [B, T]  — integer ADC values (0-255)
    Output: [B, 256, T] — class logits per time step
    """

    def __init__(self, config: WaveNetConfig):
        super().__init__()
        self.embedding = nn.Embedding(256, config.input_channels)
        self.input_conv = nn.Conv1d(config.input_channels, config.residual_channels, 1)
        self.blocks = nn.ModuleList(
            [
                WaveNetBlock(
                    config.residual_channels,
                    config.gate_channels,
                    config.skip_channels,
                    config.kernel_size,
                    2**i,
                )
                for i in range(config.num_blocks)
            ]
        )
        self.output_conv1 = nn.Conv1d(config.skip_channels, config.skip_channels, 1)
        self.output_conv2 = nn.Conv1d(config.skip_channels, 256, 1)

    def forward(self, x):
        x = self.embedding(x.long())  # [B, T, input_channels]
        x = x.transpose(1, 2)  # [B, input_channels, T]
        x = self.input_conv(x)
        # WaveNetConfig.num_blocks is constrained ``ge=1`` by Pydantic, so
        # self.blocks is guaranteed non-empty. Seed skip_sum from the first
        # block's skip output (instead of None + an in-loop branch) so the
        # accumulator is unambiguously a Tensor — no Optional, no assert,
        # identical end state to the previous None-initialised pattern.
        first_block, *rest_blocks = self.blocks
        x, skip_sum = first_block(x)
        for block in rest_blocks:
            x, skip = block(x)
            min_len = min(skip_sum.size(-1), skip.size(-1))
            skip_sum = skip_sum[:, :, :min_len] + skip[:, :, :min_len]
        x = F.relu(skip_sum)
        x = F.relu(self.output_conv1(x))
        return self.output_conv2(x)  # [B, 256, T]


# ==========================================
# RNNSeq2Seq
# ==========================================


```

---

### Candidate: punet

_Score table unavailable._

#### Source Code
```python
class PositionalUNet(nn.Module):
    """
    Dynamic Positional U-Net for Agent Sandbox.

    The architecture scales automatically based on the 'depth' parameter.
    Agent can optimize: multi, depth, bilinear, pe_factor, etc.
    """

    def __init__(self, config: PUNetConfig):
        super().__init__()

        # visit properties directly, as the input was valudated by pydantic
        self.multi = config.multi
        self.depth = config.depth
        self.bilinear = config.bilinear
        self.seg_size = config.segmentation_size
        self.pe_factor = config.pe_factor
        self.kernel_size = config.kernel_size
        self.padding = int((self.kernel_size - 1) / 2)

        adc_channel = 256
        emb_dim = config.embedding_dim

        # 1. Input layers
        self.embedding = nn.Embedding(adc_channel, emb_dim, scale_grad_by_freq=True)
        self.pe_in = PositionalEncoding(emb_dim, max_len=self.seg_size, factor=self.pe_factor)
        self.inc = DoubleConv(
            emb_dim, self.multi, kernel_size=self.kernel_size, padding=self.padding
        )
        self.pe_inc = PositionalEncoding(self.multi, max_len=self.seg_size, factor=self.pe_factor)

        # 2. Downward Path (Encoder)
        self.downs = nn.ModuleList()
        self.pe_downs = nn.ModuleList()

        curr_ch = self.multi
        for i in range(self.depth):
            out_ch = curr_ch * 2
            # different calculation for bilinear case
            if i == self.depth - 1:
                factor = 2 if self.bilinear else 1
                out_ch = out_ch // factor

            self.downs.append(
                Down(curr_ch, out_ch, kernel_size=self.kernel_size, padding=self.padding)
            )
            self.pe_downs.append(
                PositionalEncoding(out_ch, max_len=self.seg_size, factor=self.pe_factor)
            )
            curr_ch = out_ch

        # 3. Upward Path (Decoder)
        self.ups = nn.ModuleList()
        self.pe_ups = nn.ModuleList()

        # Up: reversal of down
        for i in range(self.depth):
            up_in_ch = curr_ch * 2
            up_out_ch = curr_ch // 2
            # align the top layer output
            if i == self.depth - 1:
                up_out_ch = self.multi // (2 if self.bilinear else 1)

            self.ups.append(
                Up(
                    up_in_ch,
                    up_out_ch,
                    self.bilinear,
                    kernel_size=self.kernel_size,
                    padding=self.padding,
                )
            )
            self.pe_ups.append(
                PositionalEncoding(up_out_ch, max_len=self.seg_size, factor=self.pe_factor)
            )
            curr_ch = up_out_ch

        # 4. Output layer
        self.outc = OutConv(curr_ch, adc_channel)

    def forward(self, x):
        x = self.embedding(x).transpose(-1, -2)
        x = self.pe_in(x)

        # 1. Input layer and first skip
        x1 = self.pe_inc(self.inc(x))
        # store intermediate result for Skip Connection
        skip_outputs = [x1]

        # 2. Downward path
        curr_x = x1
        for i in range(self.depth - 1):  # Only store until the second to last layer
            curr_x = self.downs[i](curr_x)
            curr_x = self.pe_downs[i](curr_x)
            skip_outputs.append(curr_x)

        # 3. Bottom layer (no skip storage)
        curr_x = self.downs[-1](curr_x)
        curr_x = self.pe_downs[-1](curr_x)

        # 4. Upward path
        for i in range(self.depth):
            skip_x = skip_outputs.pop()
            curr_x = self.ups[i](curr_x, skip_x)
            curr_x = self.pe_ups[i](curr_x)

        return self.outc(curr_x)



class DoubleConv(nn.Module):
    """
    A foundational building block consisting of two consecutive 1D convolutional layers,
    each followed by Batch Normalization and LeakyReLU activation.

    Agent-Adjustable Parameters:
    - kernel_size: Defines the receptive field. Larger values capture broader wave features.
    - padding: Maintains the temporal resolution. Must be tuned with kernel_size to avoid shape mismatch.
    - bias: Toggles the additive bias. Typically False when used with BatchNorm.
    """

    def __init__(
        self, in_channels, out_channels, mid_channels=None, kernel_size=9, padding=4, bias=False
    ):
        super().__init__()
        if not mid_channels:
            mid_channels = out_channels
        self.double_conv = nn.Sequential(
            nn.Conv1d(
                in_channels, mid_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
            nn.BatchNorm1d(mid_channels),
            nn.LeakyReLU(inplace=True),
            nn.Conv1d(
                mid_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
            nn.BatchNorm1d(out_channels),
            nn.LeakyReLU(inplace=True),
        )

    def forward(self, x):
        return self.double_conv(x)



class Down(nn.Module):
    """
    Adjustable parameters for the Agent:
    - stride: The downsampling factor (default 4).
             Larger stride saves memory but may lose signal resolution.
    - kernel_size, padding, bias: Passed to DoubleConv to define feature extraction.
    """

    def __init__(self, in_channels, out_channels, stride=4, kernel_size=9, padding=4, bias=False):
        super().__init__()
        # pass stride to MaxPool1d,pass kernel size and padding to DoubleConv
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool1d(kernel_size=stride, stride=stride),
            DoubleConv(
                in_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
        )

    def forward(self, x):
        return self.maxpool_conv(x)



class Up(nn.Module):
    """
    Upsampling block that increases temporal resolution.

    Agent-Adjustable Parameters:
    - bilinear: If True, uses Upsample (linear mode). If False, uses ConvTranspose1d.
    - stride: The upsampling factor (default 4).
    - kernel_size: Parameters passed to the DoubleConv layer.
    """

    def __init__(
        self,
        in_channels,
        out_channels,
        bilinear=True,
        stride=4,
        kernel_size=9,
        padding=4,
        bias=False,
    ):
        super().__init__()

        # Calculate padding to maintain sequence length: p = (k-1)/2
        padding = (kernel_size - 1) // 2

        if bilinear:
            # For bilinear, we use nn.Upsample which doesn't change channels.
            # The channel reduction happens inside DoubleConv's mid_channels.
            self.up = nn.Upsample(scale_factor=stride, mode="linear", align_corners=True)
            self.conv = DoubleConv(
                in_channels,
                out_channels,
                in_channels // 2,
                kernel_size=kernel_size,
                padding=padding,
                bias=bias,
            )
        else:
            # For ConvTranspose1d, it reduces channels by half during the upsampling step.
            self.up = nn.ConvTranspose1d(
                in_channels, in_channels // 2, kernel_size=stride, stride=stride
            )
            # After concatenation with skip connection, the input to DoubleConv returns to in_channels logic
            self.conv = DoubleConv(
                in_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            )

    def forward(self, x1, x2):
        # x1: incoming feature map from the lower layer
        # x2: skip connection feature map from the downward path
        x1 = self.up(x1)

        # Temporal alignment (handling odd lengths or stride mismatches)
        # x.size() -> [Batch, Channel, Length]
        diff = x2.size()[2] - x1.size()[2]
        if diff != 0:
            x1 = F.pad(x1, [diff // 2, diff - diff // 2])

        # Concatenate along the channel dimension
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)



class OutConv(nn.Module):
    """
    Final output layer that maps feature channels to the physical ADC channel space (256).

    Agent-Adjustable Parameters:
    - bias: Toggles the additive bias for the final projection.
    """

    def __init__(self, in_channels, out_channels, bias=True):
        super().__init__()
        # We keep kernel_size=1 to perform point-wise classification across channels
        self.conv = nn.Sequential(
            torch.nn.Conv1d(in_channels, out_channels, kernel_size=1, bias=bias),
        )

    def forward(self, x):
        return self.conv(x)



class PositionalEncoding(nn.Module):
    """
    Injects temporal position information into the latent space.
    Crucial for phase-coherent dark matter signals.

    Agent-Adjustable Parameters:
    - max_len: Must match the current 'segmentation_size'. Defines the temporal buffer.
    - factor: The strength of positional information.
    - dropout: Regularization strength to prevent the model from over-relying on position.
    """

    def __init__(self, d_model, max_len, start=0, dropout=0.1, factor=1.0):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        self.factor = factor
        self.start = start

        # Generate the sinusoid positional encoding matrix up to max_len
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)

        # Reshape to (1, d_model, max_len) to match Conv1d input format [Batch, Channel, Time]
        pe = pe.unsqueeze(0).transpose(1, 2)

        # Register as buffer (fixed during training, moved with model to GPU)
        self.register_buffer("pe", pe)

    def forward(self, x):
        """
        Adds positional encoding to the input tensor.
        x shape: [Batch, d_model, Length]
        """
        # Slice the pre-computed pe buffer to match the input length. The
        # `cast` is a no-op at runtime; it tells pyright that `self.pe` (which
        # PyTorch's stub returns as `Module` from `register_buffer` lookup) is
        # actually the Tensor we registered above, so `[:, :, ...]` is valid.
        x = (
            x
            + self.factor * cast(torch.Tensor, self.pe)[:, :, self.start : (self.start + x.size(2))]
        )
        x = self.dropout(x)
        return x


```

---

## Accumulated context

```json
{
  "candidates": [
    {
      "model_type": "wavenet",
      "best_score": 5.57,
      "worst_score": 2.1,
      "model_params": null,
      "description": "Dilated causal convolutional network \u2014 current SOTA.",
      "training_segments": null,
      "source": "seed"
    },
    {
      "model_type": "punet",
      "best_score": 1.2,
      "worst_score": 0.4,
      "model_params": null,
      "description": "U-Net baseline for 1-D signal denoising.",
      "training_segments": null,
      "source": "seed"
    }
  ],
  "non_candidates_overview": [],
  "interpretation_summary": {
    "model_types": [
      "punet",
      "wavenet"
    ],
    "total_experiments": 2,
    "best_denoising_score": 5.57,
    "worst_denoising_score": 0.4,
    "key_findings": [
      "wavenet's dilated_causal_conv stack drives high-freq performance.",
      "punet plateaus at depth=6; deeper variants saw no lift."
    ],
    "bottlenecks": [
      "Low-frequency files (0-3) remain weak across all models.",
      "Wavenet's receptive field saturates before low-freq capture."
    ],
    "take_home_message": "Next iteration: target low-freq recovery via a richer frequency-aware mechanism while inheriting wavenet's high-freq strength.",
    "per_model_best": {
      "punet": 1.2,
      "wavenet": 5.57
    },
    "per_model_worst": {
      "punet": 0.4,
      "wavenet": 2.1
    },
    "cumulative_information_gain": 0.0,
    "prediction_outcomes_history": {
      "confirmed": 0,
      "partial": 0,
      "refuted": 0
    }
  },
  "existing_model_types": [
    "punet",
    "wavenet"
  ],
  "previous_failures": [],
  "comparison": {
    "comparisons": [
      {
        "model_type": "wavenet",
        "source": "seed",
        "best_score": 5.57,
        "key_mechanism": "dilated_causal_conv stack \u2014 exponential receptive field growth.",
        "strengths": [
          "scores 8.2 on files 15-19 (high-freq)"
        ],
        "weaknesses": [
          "near-zero on files 0-3 (low-freq)"
        ],
        "lesson_for_next_proposal": "Inherit dilated_causal_conv; augment for low-freq."
      },
      {
        "model_type": "punet",
        "source": "seed",
        "best_score": 1.2,
        "key_mechanism": "U-Net encoder/decoder with skip connections.",
        "strengths": [
          "compact"
        ],
        "weaknesses": [
          "plateaus at depth=6"
        ],
        "lesson_for_next_proposal": "Skip if wavenet inheritance is preferred."
      }
    ],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "wavenet",
    "sota_score": 5.57,
    "sota_mechanism": "dilated_causal_conv provides exponential receptive field growth."
  }
}
```
```

---

### Call 3 — `proposer.proposing`

**System prompt** (7242 chars):

```
# Stage 3: Architecture Design

You are a senior ML architect. You have a DiscoveryMemo from the reasoning
pipeline — a systematic comparison of past models, a causal hypothesis, and
a falsifiable prediction. Now commit to a SPECIFIC architecture.

## Your task

Design a concrete model architecture that implements the DiscoveryMemo's
`proposed_change`. You are structurally tethered to the memo — every
architectural choice must trace back to the comparisons and reasoning.

## What you receive

- **DiscoveryMemo**: the full output of Stages 1+2 — comparisons, SOTA
  analysis, causal hypothesis, inherited components, falsifiable prediction.
- **Vocabulary**: features/capabilities with confirmed links.
- **Expert context**: upstream findings, human directives.
- **Existing model types**: names you must NOT reuse.

## What you produce

A JSON object with these fields:

```json
{
  "model_name": "short_snake_case_key (must NOT be any existing model type)",
  "model_description": "One paragraph describing the architecture and why it addresses the DiscoveryMemo's hypothesis.",
  "mathematical_definition": "Abstract architectural framework: key computational stages, mathematical operations, data flow. Do NOT include concrete dimensions — those belong in baseline_config.",
  "motivation": "Why this architecture addresses the bottleneck identified in the DiscoveryMemo. Must reference proposed_change and causal_hypothesis verbatim.",
  "expert_advice": {
    "focus_areas": ["What to prioritize during hyperparameter tuning"],
    "constraints": ["At least one VRAM limit and one parameter count limit"],
    "known_failures": ["Based on the DiscoveryMemo's predicted_failure_modes"],
    "suggested_directions": ["Concrete first experiments", "Trial strategy guidance"],
    "rationale": "Why this guidance is appropriate for this architecture."
  },
  "baseline_config": {
    "model_config": {},
    "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1, "optimizer_type": "adamw", "weight_decay": 1e-5, "device": "cuda"},
    "loss_config": {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0, "reduction": "mean"}
  },
  "parameter_count_estimate": 1234567,
  "memo_consistency_notes": []
}
```



## SYSTEM-ENFORCED DATASET CONSTRAINTS

Your `baseline_config` will be machine-validated against the dataset rules below.
A violation rejects the proposal and re-prompts you with the error — burning one
of your retry attempts. Pick valid values now.

  segmentation_size — must EXACTLY divide psd_segment_length (10,000,000).
                      Valid values: [100, 125, 128, 160, 200, 250, 320, 400, 500, 625, 640, 800, 1000, 1250, 1600, 2000, 2500, 3125, 3200, 4000, 5000, 6250, 8000, 10000, 12500, 15625, 16000, 20000, 25000, 31250, 40000, 50000, 62500, 78125, 80000, 100000].
                      Powers of 2 such as 16384, 8192, 4096 are INVALID
                      because they do not divide 10,000,000. Use a divisor from
                      the list above (16000 is the nearest valid neighbor of 16384).


## Rules

1. **Tethered to the memo.** Your `motivation` must reference the
   DiscoveryMemo's `proposed_change` and `causal_hypothesis`. If your
   architecture deviates from the memo's plan, document EVERY deviation
   in `memo_consistency_notes` with a justification. A high deviation
   count is a red flag.

2. **Inherited components checklist.** Every entry in the DiscoveryMemo's
   `inherited_components` must appear in your `model_config` or
   `mathematical_definition`. If you drop an inherited component,
   explain why in `memo_consistency_notes`.

3. **Name uniqueness.** Your `model_name` must NOT be any of the existing
   model types: punet, wavenet. Use snake_case: lowercase letters,
   digits, and underscores only.

4. **Forward contract.** The model MUST satisfy:



   This is non-negotiable.

5. **Conservative baseline.** The `baseline_config` must fit in <10 GB VRAM.
   `expert_advice.constraints` must include at least one VRAM limit and one
   parameter count limit.

6. **Cite sparingly.** If expert context items influenced your design, they
   should already be cited in the DiscoveryMemo. Do not add new citations
   here — the memo is the citation record.

7. **Consistency notes.** If you notice that the DiscoveryMemo's hypothesis
   cannot be physically implemented as described (e.g. a mathematical
   impossibility, an incompatible layer combination), document it in
   `memo_consistency_notes`. This is a flag for the validator, not a
   reason to abandon the proposal.

8. **Parameter count estimate.** You MUST supply `parameter_count_estimate`
   as a positive integer — your best estimate of the total trainable
   parameter count at the `baseline_config`. This drives the proposer-side
   pre-flight cost gate: the static cost model multiplies your estimate by
   the active `segmentation_size` and training steps to predict wall-time.
   An order-of-magnitude estimate is sufficient — be realistic about
   multi-head attention, state dimensions, dilated convolution stacks, and
   bidirectional layers. If your estimate exceeds the active time budget,
   the gate will reject the draft and ask you to revise toward a simpler
   or lighter architectural class.

# Proposing Stage — EXPLORE Mode

## Contract Hierarchy

The trust hierarchy and multi-source synthesis rules are defined in the
base prompt (see the *Multi-source synthesis* MANDATORY block). Apply them
as written; this block governs exploration/exploitation posture only.

## Operating Mode

You are operating in **EXPLORE** mode. Your strategic posture for this
iteration comes from (a) the Contributors block's `trust_level`-weighted
findings, (b) the experiment history's `take_home_message`, and (c) any
`mindset` override that replaced this block (when none is set, the default
EXPLORE/EXPLOIT posture applies). **EXPLORE posture**: prioritize
unexplored mechanisms — `soft_prior` findings that suggest directions
experiment history has not yet tried are first-class motivators, not
side notes.

## Methodology — proposal completeness

- Every proposal must include: `causal_hypothesis`, `proposed_change`,
  `falsifiable_prediction`, `inherited_components`, `baseline_config`, and
  `proposed_vocab_candidates` if introducing new mechanism names.
- The `baseline_config` must respect the resource budget stated in
  `[HARDWARE CONTEXT]` (when present) and in any `## Constraints` block.
  If the budget is infeasible for the architecture you have in mind,
  surface that conflict explicitly in `causal_hypothesis` rather than
  silently shrinking the architecture.
- Name new mechanisms in `proposed_vocab_candidates` with `kind="feature"` or
  `kind="capability"` and link them to existing canonical entries via
  `related_to` when a relationship is plausible.
- `inherited_components` should reflect the components the synthesis rules
  call out — past-experiment building blocks from Stage 1 ModelComparisons,
  and any `strong_prior` / `hard_limit` findings that motivated structural
  choices. Length and contents are mode-driven, not fixed.


## Output format

Return a single JSON object matching the schema above. No preamble,
no markdown fences, no commentary outside the JSON.
```

**User prompt** (20958 chars):

```
[HARDWARE CONTEXT]
Device:            NVIDIA RTX 3090
Total VRAM:        24.00 GB
Usable cap (80%):  19.20 GB
Host:              checkpoint-p-audit-host
Regime:            PHYSICAL — no operator budget set; cap = 19.20 GB.

Your baseline_config must fit within the **effective cap** shown above. The VRAM engine will reject any architecture whose predicted peak exceeds this ceiling; a rejection consumes a tuner attempt with no scored round. Size your baseline to stay comfortably below the cap (target ≤ 80% of the effective cap at baseline) so the tuner has headroom to vary batch_size and segmentation_size upward.

## Constraints
Existing model type keys (your `model_name` must NOT be any of these): ['punet', 'wavenet']
  - VRAM < 10 GB
  - params < 50M

## External Contributors

Read each contributor's trust level and trust guidance before reading their findings.

### ml_literature_review
  Trust Level: soft_prior
  Role: Surface ML denoising literature relevant to the current iteration.
  Expertise Domain: ML denoising architectures; Semantic Scholar corpus.
  Coverage: ArXiv/S2 results any year; local PDFs in reference_data/.
  Limitations: Cannot run experiments; cannot judge SQUID-specific applicability without empirical confirmation.
  Trust Guidance: Treat findings as inspirational priors — experiment runs are required to confirm applicability before adoption.

### human
  Trust Level: strong_prior
  Role: Human operator providing direct guidance for this iteration.
  Expertise Domain: Task-specific operational knowledge and strategic intent.
  Coverage: This iteration only — human_advice is per-run, not accumulated across iterations.
  Limitations: May not have full visibility into all past experiment results.
  Trust Guidance: Human directives carry strong_prior weight — treat them comparably to experiment data. Override only with explicit justification.


## Expert Context

[HUMAN DIRECTIVE] (from human, source_ref=human:human_advice)
  Prioritize low-frequency recovery; tolerate up to 12 GB VRAM if the extra capacity directly improves files 0-3. Avoid frequency-split training — keep the full-spectrum setting locked.

[LITERATURE REFERENCE] (from ml_literature_review, confidence=0.85, source_ref=arxiv:2312.00752)
  **Implication:** A frequency-aware composite loss may widen wavenet's effective spectral coverage on low-freq files (bottleneck 1).

**Mechanism:** Composite loss $\min_\theta \delta L^f + (1-\delta) L^t$ (FreLE), where $L^f$ is the Fourier-magnitude loss and $L^t$ is the time-domain reconstruction loss; $\delta \in [0, 1]$ trades off the two. Lifted verbatim from the source paper's Eq. 4.

**Adaptation:** Apply the composite loss directly to the wavenet decoder with the clean signal's Fourier magnitudes as the spectral target. Keep wavenet's dilated_causal_conv backbone unchanged.


## Candidate Models — detailed view

### Candidate: wavenet

_Score table unavailable._

#### Source Code
```python
class CausalConv1d(nn.Module):
    """Causal convolution — no future information leakage."""

    def __init__(self, in_channels, out_channels, kernel_size, dilation=1):
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels, kernel_size, padding=self.padding, dilation=dilation
        )

    def forward(self, x):
        x = self.conv(x)
        if self.padding > 0:
            x = x[:, :, : -self.padding]
        return x



class WaveNetBlock(nn.Module):
    """Single WaveNet residual block with dilated causal convolution."""

    def __init__(self, residual_channels, gate_channels, skip_channels, kernel_size, dilation):
        super().__init__()
        self.causal_conv = CausalConv1d(residual_channels, gate_channels, kernel_size, dilation)
        half = gate_channels // 2
        self.gate_conv = nn.Conv1d(half, half, 1)
        self.filter_conv = nn.Conv1d(half, half, 1)
        self.residual_conv = nn.Conv1d(half, residual_channels, 1)
        self.skip_conv = nn.Conv1d(half, skip_channels, 1)

    def forward(self, x):
        residual = x
        x = self.causal_conv(x)
        filter_part, gate_part = torch.chunk(x, 2, dim=1)
        x = torch.tanh(self.filter_conv(filter_part)) * torch.sigmoid(self.gate_conv(gate_part))
        skip = self.skip_conv(x)
        res_out = self.residual_conv(x)
        if res_out.size(-1) != residual.size(-1):
            residual = residual[:, :, : res_out.size(-1)]
        return residual + res_out, skip



class SimpleWaveNet(nn.Module):
    """
    WaveNet-style model for ADC denoising.
    Input:  [B, T]  — integer ADC values (0-255)
    Output: [B, 256, T] — class logits per time step
    """

    def __init__(self, config: WaveNetConfig):
        super().__init__()
        self.embedding = nn.Embedding(256, config.input_channels)
        self.input_conv = nn.Conv1d(config.input_channels, config.residual_channels, 1)
        self.blocks = nn.ModuleList(
            [
                WaveNetBlock(
                    config.residual_channels,
                    config.gate_channels,
                    config.skip_channels,
                    config.kernel_size,
                    2**i,
                )
                for i in range(config.num_blocks)
            ]
        )
        self.output_conv1 = nn.Conv1d(config.skip_channels, config.skip_channels, 1)
        self.output_conv2 = nn.Conv1d(config.skip_channels, 256, 1)

    def forward(self, x):
        x = self.embedding(x.long())  # [B, T, input_channels]
        x = x.transpose(1, 2)  # [B, input_channels, T]
        x = self.input_conv(x)
        # WaveNetConfig.num_blocks is constrained ``ge=1`` by Pydantic, so
        # self.blocks is guaranteed non-empty. Seed skip_sum from the first
        # block's skip output (instead of None + an in-loop branch) so the
        # accumulator is unambiguously a Tensor — no Optional, no assert,
        # identical end state to the previous None-initialised pattern.
        first_block, *rest_blocks = self.blocks
        x, skip_sum = first_block(x)
        for block in rest_blocks:
            x, skip = block(x)
            min_len = min(skip_sum.size(-1), skip.size(-1))
            skip_sum = skip_sum[:, :, :min_len] + skip[:, :, :min_len]
        x = F.relu(skip_sum)
        x = F.relu(self.output_conv1(x))
        return self.output_conv2(x)  # [B, 256, T]


# ==========================================
# RNNSeq2Seq
# ==========================================


```

---

### Candidate: punet

_Score table unavailable._

#### Source Code
```python
class PositionalUNet(nn.Module):
    """
    Dynamic Positional U-Net for Agent Sandbox.

    The architecture scales automatically based on the 'depth' parameter.
    Agent can optimize: multi, depth, bilinear, pe_factor, etc.
    """

    def __init__(self, config: PUNetConfig):
        super().__init__()

        # visit properties directly, as the input was valudated by pydantic
        self.multi = config.multi
        self.depth = config.depth
        self.bilinear = config.bilinear
        self.seg_size = config.segmentation_size
        self.pe_factor = config.pe_factor
        self.kernel_size = config.kernel_size
        self.padding = int((self.kernel_size - 1) / 2)

        adc_channel = 256
        emb_dim = config.embedding_dim

        # 1. Input layers
        self.embedding = nn.Embedding(adc_channel, emb_dim, scale_grad_by_freq=True)
        self.pe_in = PositionalEncoding(emb_dim, max_len=self.seg_size, factor=self.pe_factor)
        self.inc = DoubleConv(
            emb_dim, self.multi, kernel_size=self.kernel_size, padding=self.padding
        )
        self.pe_inc = PositionalEncoding(self.multi, max_len=self.seg_size, factor=self.pe_factor)

        # 2. Downward Path (Encoder)
        self.downs = nn.ModuleList()
        self.pe_downs = nn.ModuleList()

        curr_ch = self.multi
        for i in range(self.depth):
            out_ch = curr_ch * 2
            # different calculation for bilinear case
            if i == self.depth - 1:
                factor = 2 if self.bilinear else 1
                out_ch = out_ch // factor

            self.downs.append(
                Down(curr_ch, out_ch, kernel_size=self.kernel_size, padding=self.padding)
            )
            self.pe_downs.append(
                PositionalEncoding(out_ch, max_len=self.seg_size, factor=self.pe_factor)
            )
            curr_ch = out_ch

        # 3. Upward Path (Decoder)
        self.ups = nn.ModuleList()
        self.pe_ups = nn.ModuleList()

        # Up: reversal of down
        for i in range(self.depth):
            up_in_ch = curr_ch * 2
            up_out_ch = curr_ch // 2
            # align the top layer output
            if i == self.depth - 1:
                up_out_ch = self.multi // (2 if self.bilinear else 1)

            self.ups.append(
                Up(
                    up_in_ch,
                    up_out_ch,
                    self.bilinear,
                    kernel_size=self.kernel_size,
                    padding=self.padding,
                )
            )
            self.pe_ups.append(
                PositionalEncoding(up_out_ch, max_len=self.seg_size, factor=self.pe_factor)
            )
            curr_ch = up_out_ch

        # 4. Output layer
        self.outc = OutConv(curr_ch, adc_channel)

    def forward(self, x):
        x = self.embedding(x).transpose(-1, -2)
        x = self.pe_in(x)

        # 1. Input layer and first skip
        x1 = self.pe_inc(self.inc(x))
        # store intermediate result for Skip Connection
        skip_outputs = [x1]

        # 2. Downward path
        curr_x = x1
        for i in range(self.depth - 1):  # Only store until the second to last layer
            curr_x = self.downs[i](curr_x)
            curr_x = self.pe_downs[i](curr_x)
            skip_outputs.append(curr_x)

        # 3. Bottom layer (no skip storage)
        curr_x = self.downs[-1](curr_x)
        curr_x = self.pe_downs[-1](curr_x)

        # 4. Upward path
        for i in range(self.depth):
            skip_x = skip_outputs.pop()
            curr_x = self.ups[i](curr_x, skip_x)
            curr_x = self.pe_ups[i](curr_x)

        return self.outc(curr_x)



class DoubleConv(nn.Module):
    """
    A foundational building block consisting of two consecutive 1D convolutional layers,
    each followed by Batch Normalization and LeakyReLU activation.

    Agent-Adjustable Parameters:
    - kernel_size: Defines the receptive field. Larger values capture broader wave features.
    - padding: Maintains the temporal resolution. Must be tuned with kernel_size to avoid shape mismatch.
    - bias: Toggles the additive bias. Typically False when used with BatchNorm.
    """

    def __init__(
        self, in_channels, out_channels, mid_channels=None, kernel_size=9, padding=4, bias=False
    ):
        super().__init__()
        if not mid_channels:
            mid_channels = out_channels
        self.double_conv = nn.Sequential(
            nn.Conv1d(
                in_channels, mid_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
            nn.BatchNorm1d(mid_channels),
            nn.LeakyReLU(inplace=True),
            nn.Conv1d(
                mid_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
            nn.BatchNorm1d(out_channels),
            nn.LeakyReLU(inplace=True),
        )

    def forward(self, x):
        return self.double_conv(x)



class Down(nn.Module):
    """
    Adjustable parameters for the Agent:
    - stride: The downsampling factor (default 4).
             Larger stride saves memory but may lose signal resolution.
    - kernel_size, padding, bias: Passed to DoubleConv to define feature extraction.
    """

    def __init__(self, in_channels, out_channels, stride=4, kernel_size=9, padding=4, bias=False):
        super().__init__()
        # pass stride to MaxPool1d,pass kernel size and padding to DoubleConv
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool1d(kernel_size=stride, stride=stride),
            DoubleConv(
                in_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            ),
        )

    def forward(self, x):
        return self.maxpool_conv(x)



class Up(nn.Module):
    """
    Upsampling block that increases temporal resolution.

    Agent-Adjustable Parameters:
    - bilinear: If True, uses Upsample (linear mode). If False, uses ConvTranspose1d.
    - stride: The upsampling factor (default 4).
    - kernel_size: Parameters passed to the DoubleConv layer.
    """

    def __init__(
        self,
        in_channels,
        out_channels,
        bilinear=True,
        stride=4,
        kernel_size=9,
        padding=4,
        bias=False,
    ):
        super().__init__()

        # Calculate padding to maintain sequence length: p = (k-1)/2
        padding = (kernel_size - 1) // 2

        if bilinear:
            # For bilinear, we use nn.Upsample which doesn't change channels.
            # The channel reduction happens inside DoubleConv's mid_channels.
            self.up = nn.Upsample(scale_factor=stride, mode="linear", align_corners=True)
            self.conv = DoubleConv(
                in_channels,
                out_channels,
                in_channels // 2,
                kernel_size=kernel_size,
                padding=padding,
                bias=bias,
            )
        else:
            # For ConvTranspose1d, it reduces channels by half during the upsampling step.
            self.up = nn.ConvTranspose1d(
                in_channels, in_channels // 2, kernel_size=stride, stride=stride
            )
            # After concatenation with skip connection, the input to DoubleConv returns to in_channels logic
            self.conv = DoubleConv(
                in_channels, out_channels, kernel_size=kernel_size, padding=padding, bias=bias
            )

    def forward(self, x1, x2):
        # x1: incoming feature map from the lower layer
        # x2: skip connection feature map from the downward path
        x1 = self.up(x1)

        # Temporal alignment (handling odd lengths or stride mismatches)
        # x.size() -> [Batch, Channel, Length]
        diff = x2.size()[2] - x1.size()[2]
        if diff != 0:
            x1 = F.pad(x1, [diff // 2, diff - diff // 2])

        # Concatenate along the channel dimension
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)



class OutConv(nn.Module):
    """
    Final output layer that maps feature channels to the physical ADC channel space (256).

    Agent-Adjustable Parameters:
    - bias: Toggles the additive bias for the final projection.
    """

    def __init__(self, in_channels, out_channels, bias=True):
        super().__init__()
        # We keep kernel_size=1 to perform point-wise classification across channels
        self.conv = nn.Sequential(
            torch.nn.Conv1d(in_channels, out_channels, kernel_size=1, bias=bias),
        )

    def forward(self, x):
        return self.conv(x)



class PositionalEncoding(nn.Module):
    """
    Injects temporal position information into the latent space.
    Crucial for phase-coherent dark matter signals.

    Agent-Adjustable Parameters:
    - max_len: Must match the current 'segmentation_size'. Defines the temporal buffer.
    - factor: The strength of positional information.
    - dropout: Regularization strength to prevent the model from over-relying on position.
    """

    def __init__(self, d_model, max_len, start=0, dropout=0.1, factor=1.0):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        self.factor = factor
        self.start = start

        # Generate the sinusoid positional encoding matrix up to max_len
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)

        # Reshape to (1, d_model, max_len) to match Conv1d input format [Batch, Channel, Time]
        pe = pe.unsqueeze(0).transpose(1, 2)

        # Register as buffer (fixed during training, moved with model to GPU)
        self.register_buffer("pe", pe)

    def forward(self, x):
        """
        Adds positional encoding to the input tensor.
        x shape: [Batch, d_model, Length]
        """
        # Slice the pre-computed pe buffer to match the input length. The
        # `cast` is a no-op at runtime; it tells pyright that `self.pe` (which
        # PyTorch's stub returns as `Module` from `register_buffer` lookup) is
        # actually the Tensor we registered above, so `[:, :, ...]` is valid.
        x = (
            x
            + self.factor * cast(torch.Tensor, self.pe)[:, :, self.start : (self.start + x.size(2))]
        )
        x = self.dropout(x)
        return x


```

---

## Accumulated context

```json
{
  "candidates": [
    {
      "model_type": "wavenet",
      "best_score": 5.57,
      "worst_score": 2.1,
      "model_params": null,
      "description": "Dilated causal convolutional network \u2014 current SOTA.",
      "training_segments": null,
      "source": "seed"
    },
    {
      "model_type": "punet",
      "best_score": 1.2,
      "worst_score": 0.4,
      "model_params": null,
      "description": "U-Net baseline for 1-D signal denoising.",
      "training_segments": null,
      "source": "seed"
    }
  ],
  "non_candidates_overview": [],
  "interpretation_summary": {
    "model_types": [
      "punet",
      "wavenet"
    ],
    "total_experiments": 2,
    "best_denoising_score": 5.57,
    "worst_denoising_score": 0.4,
    "key_findings": [
      "wavenet's dilated_causal_conv stack drives high-freq performance.",
      "punet plateaus at depth=6; deeper variants saw no lift."
    ],
    "bottlenecks": [
      "Low-frequency files (0-3) remain weak across all models.",
      "Wavenet's receptive field saturates before low-freq capture."
    ],
    "take_home_message": "Next iteration: target low-freq recovery via a richer frequency-aware mechanism while inheriting wavenet's high-freq strength.",
    "per_model_best": {
      "punet": 1.2,
      "wavenet": 5.57
    },
    "per_model_worst": {
      "punet": 0.4,
      "wavenet": 2.1
    },
    "cumulative_information_gain": 0.0,
    "prediction_outcomes_history": {
      "confirmed": 0,
      "partial": 0,
      "refuted": 0
    }
  },
  "existing_model_types": [
    "punet",
    "wavenet"
  ],
  "previous_failures": [],
  "comparison": {
    "comparisons": [
      {
        "model_type": "wavenet",
        "source": "seed",
        "best_score": 5.57,
        "key_mechanism": "dilated_causal_conv stack \u2014 exponential receptive field growth.",
        "strengths": [
          "scores 8.2 on files 15-19 (high-freq)"
        ],
        "weaknesses": [
          "near-zero on files 0-3 (low-freq)"
        ],
        "lesson_for_next_proposal": "Inherit dilated_causal_conv; augment for low-freq."
      },
      {
        "model_type": "punet",
        "source": "seed",
        "best_score": 1.2,
        "key_mechanism": "U-Net encoder/decoder with skip connections.",
        "strengths": [
          "compact"
        ],
        "weaknesses": [
          "plateaus at depth=6"
        ],
        "lesson_for_next_proposal": "Skip if wavenet inheritance is preferred."
      }
    ],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "wavenet",
    "sota_score": 5.57,
    "sota_mechanism": "dilated_causal_conv provides exponential receptive field growth."
  },
  "causal_reasoning": {
    "proposed_change": "Augment wavenet with a frequency-aware composite loss ($\\delta L^f + (1-\\delta) L^t$) to widen spectral coverage.",
    "causal_hypothesis": "wavenet's dilated_causal_conv (Stage 1 ModelComparison) saturates high-freq but leaves low-freq files weak. A composite frequency loss (source_ref arxiv:2312.00752, trust_level=soft_prior) directly targets the low-freq bottleneck without altering the proven backbone.",
    "falsifiable_prediction": {
      "metric": "mean(file_vector[0:3])",
      "current_value": 0.5,
      "predicted_value": 1.5,
      "threshold_for_refutation": 0.7,
      "rationale": "FreLE's spectral loss is on-domain for 1-D denoising."
    },
    "predicted_failure_modes": [
      "Composite loss may destabilise training in early epochs."
    ],
    "inherited_components": [
      {
        "component": "dilated_causal_conv",
        "source_type": "experiment",
        "source_id": "wavenet",
        "contribution_evidence": "Core mechanism of wavenet's 5.57 SOTA score."
      }
    ]
  }
}
```
```

---

## Human verdict (Checkpoint P sign-off)

Reviewer reads the rendered prompts above and confirms each of the 9 sub-criteria. The automated pre-checks at the top of this artifact cover sub-criteria 6/7/8/9 mechanically; sub-criteria 1-5 (block presence and content quality) require human judgment.

| # | Criterion (short) | Verdict | Notes |
|---|---|---|---|
| S1 | `[HARDWARE CONTEXT]` block at the top of every stage's user prompt | _ | _ |
| S2 | `## Constraints` block right below | _ | _ |
| S3 | `## External Contributors` block next, both Trust Level values visible | _ | _ |
| S4 | `## Expert Context` block next, lit-review + wrapped-human items present | _ | _ |
| S5 | Candidate markdown + accumulated JSON renders below all of the above | _ | _ |
| S6 | causal_reasoning_stage.md system prompt is post-P-c (rule 1 + MANDATORY synthesis; no hardcoded hierarchy) | _ | _ |
| S7 | no `expert_advice` field-name in user prompts; no `cite_id` anywhere | _ | _ |
| S8 | comparison_stage.md weakened Rule 4 + 6 mode files clean of hardcoded hierarchy / Advice JSON | _ | _ |
| S9 | rendered Contributors block contains literal `Trust Level: soft_prior` AND `Trust Level: strong_prior` | _ | _ |

**Sign-off**: a human reviewer fills the Verdict column above (`PASS`/`FAIL`/`N/A`) and commits the artifact alongside ticking Checkpoint P + closing P-e in `docs/commit_plan_ml_literature_review.md`.
