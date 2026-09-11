# PUNet — Positional U-Net

## Overview

A 1D convolutional U-Net with sinusoidal positional encoding injected at every scale.
Designed for per-timestep classification of SQUID ADC signals into 256 denoising classes.

**Forward contract:** `[B, T] int64 → [B, 256, T] float32`

---

## Architecture

### 1. Input Stage

Each integer ADC value (0–255) is first embedded into a continuous vector:

$$x_\text{emb} = \text{Embedding}(x) \in \mathbb{R}^{B \times d_\text{emb} \times T}$$

Sinusoidal positional encoding is added immediately after embedding:

$$\text{PE}(t, 2i)   = \sin\!\left(\frac{t}{10000^{2i/d}}\right), \quad
  \text{PE}(t, 2i+1) = \cos\!\left(\frac{t}{10000^{2i/d}}\right)$$

$$x_1 = \text{PE} \oplus \text{DoubleConv}(x_\text{emb}) \in \mathbb{R}^{B \times C \times T}$$

where $C = \texttt{multi}$ is the base channel width.

### 2. Encoder (Downward Path)

Each encoder level applies MaxPool1d (stride 4) followed by a DoubleConv block and positional encoding:

$$x_{i+1} = \text{PE} \oplus \text{DoubleConv}(\text{MaxPool}_4(x_i)), \quad i = 1, \ldots, \texttt{depth}$$

Channels double at each level: $C, 2C, 4C, \ldots, 2^\texttt{depth} \cdot C$.

The DoubleConv block is: `Conv1d → BN → LeakyReLU → Conv1d → BN → LeakyReLU`.

### 3. Decoder (Upward Path)

Each decoder level upsamples by factor 4 (bilinear or ConvTranspose1d), concatenates the
skip connection from the corresponding encoder level, and applies a DoubleConv block:

$$x'_i = \text{PE} \oplus \text{DoubleConv}(\text{Concat}[\text{Up}_4(x'_{i-1}),\ x_{\texttt{depth}-i}])$$

### 4. Output

A pointwise $1 \times 1$ convolution maps the final feature map to 256 logits:

$$\hat{y} = \text{Conv1d}_{1\times1}(x'_\texttt{depth}) \in \mathbb{R}^{B \times 256 \times T}$$

---

## Key Configuration Parameters

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `multi` | 40 | 16–128 | Base channel width — scales model capacity quadratically |
| `depth` | 4 | 1–5 | Number of encoder/decoder levels — controls receptive field: $4^\texttt{depth}$ timesteps |
| `kernel_size` | 9 | 3–15 (odd) | Convolution kernel — wider = broader local context per layer |
| `embedding_dim` | 32 | 8–256 | Dimension of ADC token embedding |
| `pe_factor` | 1.0 | 0–10 | Positional encoding strength — 0 disables it entirely |
| `bilinear` | True | — | Upsampling mode: bilinear (smoother) vs. ConvTranspose1d (learnable) |
| `segmentation_size` | 40000 | ≥ $4^\texttt{depth}$ | Input sequence length — must be divisible by $4^\texttt{depth}$ |

**Constraint:** `segmentation_size` ≥ $4^\texttt{depth}$ (enforced by Pydantic validator).

---

## Known Characteristics

- Receptive field grows as $\sim 4^\texttt{depth} \times \texttt{kernel\_size}$ timesteps — deep models see long-range context
- Positional encoding is applied at every scale (input, encoder, decoder) — phase-coherent features
- Sensitive to learning rate: empirically, `lr=3e-4` with AdamW is the stable regime
- Performance plateaus around `depth=4`; going to `depth=5` rarely helps without also increasing `multi`
- `kernel_size > 9` tends to hurt generalisation on this dataset despite lower training loss
