# Transformer — Transformer Encoder

## Overview

A standard Transformer encoder that processes ADC token sequences with sinusoidal
positional encoding and projects per-timestep hidden states to 256 denoising logits.
Uses self-attention to capture long-range dependencies across the signal.

**Forward contract:** `[B, T] int64 → [B, 256, T] float32`

**Memory warning:** Attention complexity is $O(T^2)$. Keep `segmentation_size ≤ 20000`
to stay within 10 GB VRAM.

---

## Architecture

### 1. Embedding + Positional Encoding

$$x_\text{emb} = \sqrt{d_\text{emb}} \cdot \text{Embedding}(x) \in \mathbb{R}^{B \times T \times d_\text{emb}}$$

Sinusoidal positional encoding is added (same formula as PUNet, applied once at input):

$$x_\text{pe} = \text{PE}(x_\text{emb}) + \text{Dropout}$$

### 2. Transformer Encoder Stack

$N = \texttt{num\_layers}$ identical encoder layers, each with:

$$\text{MultiHeadAttn}(Q, K, V) = \text{Concat}(\text{head}_1, \ldots, \text{head}_h) W^O$$

$$\text{head}_i = \text{Attention}(x W_i^Q,\ x W_i^K,\ x W_i^V), \quad
  \text{Attention}(Q,K,V) = \text{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V$$

followed by a feed-forward sublayer:

$$\text{FFN}(x) = \text{ReLU}(x W_1 + b_1) W_2 + b_2, \quad W_1 \in \mathbb{R}^{d_\text{emb} \times d_\text{ff}}$$

Both sublayers use residual connections and LayerNorm.

### 3. Output Projection

A linear layer maps each position's hidden state to 256 logits:

$$\hat{y} = \text{Linear}_{d_\text{emb} \to 256}(x_\text{enc})^\top \in \mathbb{R}^{B \times 256 \times T}$$

---

## Key Configuration Parameters

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `embedding_dim` | 32 | 8–256 | Token embedding size — must be divisible by `nhead` |
| `nhead` | 4 | 1–16 | Number of attention heads — `embedding_dim % nhead == 0` required |
| `num_layers` | 2 | 1–10 | Depth of the encoder stack |
| `dim_feedforward` | 128 | 64–1024 | Hidden size of the FFN sublayer |
| `dropout` | 0.1 | 0–0.5 | Dropout in attention and FFN |
| `pe_factor` | 1.0 | 0–10 | Positional encoding strength |
| `segmentation_size` | 20000 | 1000–40000 | Sequence length — **keep ≤ 20000** to avoid OOM |

**Constraint:** `embedding_dim % nhead == 0` (enforced by Pydantic validator).

---

## Known Characteristics

- Self-attention gives global receptive field from layer 1 — can capture long-range signal correlations unavailable to convolutional models
- VRAM grows quadratically with `segmentation_size` — the primary bottleneck
- Shallow stacks (`num_layers=2`) are often competitive with deeper ones due to the global attention already present at layer 1
- Best used when the signal contains long-range phase correlations that local convolutions miss
