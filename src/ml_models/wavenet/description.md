# WaveNet — Dilated Causal WaveNet

## Overview

A WaveNet-style architecture using stacked dilated causal convolutions with gated
activations and skip connections. Processes the signal strictly causally — each
timestep sees only past context. Exponentially growing dilations give a large
effective receptive field without quadratic memory cost.

**Forward contract:** `[B, T] int64 → [B, 256, T] float32`

---

## Architecture

### 1. Input

Each ADC token is embedded, then projected to the residual channel width:

$$x_\text{emb} = \text{Embedding}(x) \in \mathbb{R}^{B \times T \times C_\text{in}}$$
$$x_0 = \text{Conv1d}_{1\times1}(x_\text{emb}^\top) \in \mathbb{R}^{B \times C_r \times T}$$

where $C_\text{in} = \texttt{input\_channels}$, $C_r = \texttt{residual\_channels}$.

### 2. Dilated Causal Residual Blocks

$N = \texttt{num\_blocks}$ blocks with dilation $2^i$ for block $i$:

**Causal convolution** (no future leakage via left-padding):
$$h = \text{CausalConv1d}(x_{i-1},\ k=\texttt{kernel\_size},\ d=2^i) \in \mathbb{R}^{B \times C_g \times T}$$

**Gated activation** (split $h$ into two halves):
$$z = \tanh(h_{:C_g/2}) \odot \sigma(h_{C_g/2:}) \in \mathbb{R}^{B \times C_g/2 \times T}$$

**Skip and residual projections:**
$$\text{skip}_i = \text{Conv1d}_{1\times1}(z) \in \mathbb{R}^{B \times C_s \times T}$$
$$x_i = x_{i-1} + \text{Conv1d}_{1\times1}(z) \quad \text{(residual)}$$

where $C_g = \texttt{gate\_channels}$, $C_s = \texttt{skip\_channels}$.

**Effective receptive field:** $\sum_{i=0}^{N-1}(k-1)\cdot 2^i = (k-1)(2^N - 1)$ timesteps.

### 3. Output

Skip connections from all blocks are summed, then projected to 256 logits:

$$\hat{y} = \text{Conv1d}_{1\times1}(\text{ReLU}(\text{Conv1d}_{1\times1}(\text{ReLU}(\textstyle\sum_i \text{skip}_i))))$$
$$\hat{y} \in \mathbb{R}^{B \times 256 \times T}$$

---

## Key Configuration Parameters

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `num_blocks` | 10 | 1–20 | Stack depth — receptive field = $(k-1)(2^N-1)$ timesteps |
| `kernel_size` | 12 | 2–32 | Causal kernel size — wider = larger receptive field per block |
| `residual_channels` | 32 | 8–128 | Channel width through the residual path |
| `gate_channels` | 64 | 8–256 (even) | Must be even — split in half for gated activation |
| `skip_channels` | 32 | 8–128 | Accumulation channel width for skip connections |
| `input_channels` | 16 | 4–64 | Embedding output dimension |

**Constraint:** `gate_channels` must be even (enforced by Pydantic validator).

---

## Known Characteristics

- Strictly causal — no information from future timesteps; natural for autoregressive-style signals
- Receptive field grows exponentially with `num_blocks` at linear memory cost (unlike Transformer's $O(T^2)$)
- With default settings ($k=12$, $N=10$): receptive field $= 11 \times 1023 = 11253$ timesteps
- Gated activations (tanh × sigmoid) are the key nonlinearity — effective at capturing sharp signal transitions
- Skip connections aggregate features from all dilation scales simultaneously
