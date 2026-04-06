# GatedFNO — Full-Spectrum Gated Fourier Neural Operator

## Overview
A physics-informed neural operator that performs denoising in the Fourier domain. Unlike standard FNOs that truncate high frequencies, GatedFNO processes the **full spectrum** up to the Nyquist frequency. It introduces a **Manual Attention Gate** $V$, allowing an external controller (Agent) to protect specific frequency bands (e.g., axion signals) from AI distortion.

**Forward contract:** `[B, T] int64 → [B, 256, T] float32`

---

## Architecture

### 1. Full-Spectrum Spectral Convolution
Each layer computes an RFFT of the latent representation $h$. A learnable complex weight $R \in \mathbb{C}^{d \times d \times F}$ is applied to all frequency bins $F$. The final spectral output $\hat{z}$ is a gated mixture:

$$\hat{z}_k = v_k \cdot (R_k \hat{h}_k) + (1 - v_k) \cdot \hat{h}_k$$

- $v_k = 1$: AI full processing (denoising enabled).
- $v_k = 0$: Identity bypass (signal perfectly preserved).

### 2. Dual-Path Iteration
The model stacks $L$ blocks. Each block combines the gated Fourier path with a local temporal path ($1 \times 1$ Conv) and a GELU activation:
$$h_{l+1} = \text{GELU}(W \cdot h_l + \mathcal{F}^{-1}(\hat{z}))$$

---

## Key Configuration Parameters

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `width` | 64 | 16–256 | Hidden channel dimension (latent width). |
| `num_layers` | 2 | 1–4 | Number of iterative Gated-FNO blocks. |
| `num_gates` | 128 | 1–2048 | Granularity of the control vector $V$ across the spectrum. |
| `static_v` | None | List[float] | Fixed gate values. If None, defaults to all 1s (full AI processing). |

---

## Known Characteristics
- **Zero Distortion**: Mathematically guarantees signal preservation in bands where $v_k=0$ within the Fourier path.
- **Global Receptive Field**: Fourier Path captures long-range periodic noise (e.g., 60Hz harmonics).
- **Control Interface**: The `static_v` vector is the primary lever for the Agent to inject physical priors about signal locations.