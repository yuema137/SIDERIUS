# FCNet — Fully Connected AutoEncoder

## Overview

A symmetric fully connected encoder-decoder (AutoEncoder) that compresses the entire
input segment into a low-dimensional latent representation and reconstructs it.
Can operate in two modes: classification (256 logit classes, default) or regression (SmoothL1).

**Forward contract:** `[B, T] int64 → [B, 256, T] float32` (classification mode)

---

## Architecture

### 1. Encoder

A stack of linear layers with ReLU activations that progressively compress the input:

$$h_0 = x \in \mathbb{R}^{B \times T}$$
$$h_i = \text{ReLU}(\text{Linear}_{d_{i-1} \to d_i}(h_{i-1})), \quad i = 1, \ldots, L$$

where $[d_1, d_2, \ldots, d_L] = \texttt{latent\_dims}$ (e.g. `[4000, 400, 40]`).

Optional dropout is applied after each ReLU.

### 2. Decoder

A mirror of the encoder — linear layers in reverse order reconstructing back to input size $T$:

$$\hat{h}_i = \text{ReLU}(\text{Linear}_{d_{L-i+1} \to d_{L-i}}(\hat{h}_{i-1})), \quad i = 1, \ldots, L-1$$
$$\hat{x} = \text{Linear}_{d_1 \to T}(\hat{h}_{L-1}) \in \mathbb{R}^{B \times T}$$

### 3. Output (classification mode)

A pointwise $1 \times 1$ Conv1d lifts the reconstructed sequence to 256 logits:

$$\hat{y} = \text{Conv1d}_{1 \times 1}(\hat{x}.\text{unsqueeze}(1)) \in \mathbb{R}^{B \times 256 \times T}$$

In regression mode (`smooth_l1` loss), the Conv1d is omitted and $\hat{x} \in \mathbb{R}^{B \times T}$ is returned directly.

---

## Key Configuration Parameters

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `latent_dims` | [4000, 400, 40] | 1–6 layers | Encoder depth and bottleneck width — controls compression ratio |
| `dropout` | 0.0 | 0–0.5 | Regularisation between layers |
| `segmentation_size` | 40000 | ≥ 1000 | Input length — directly sets the input/output dimension of all linear layers |
| `batch_size` | 1 | ≥ 1 | Training batch size |

**Note:** FCNet is the only model that supports `smooth_l1` (regression) loss.
All other models require `ce` or `focal` (classification) loss.

---

## Known Characteristics

- Treats each segment as a flat vector — no spatial/temporal inductive bias
- The bottleneck layer $d_L$ (e.g. 40) must represent the full signal structure; too small loses information
- Parameter count scales as $O(T \times d_1)$ — very large for long sequences (e.g. $T=40000$, $d_1=4000$ gives 160M params in the first layer alone)
- No convolution means no receptive field limit, but also no translation equivariance
- Prone to memorising training segments if dropout is too low and the bottleneck is too wide
