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

## Key Configuration Parameters and Tuning Guide

| Parameter | Default | Range | Effect | Tuning Strategy |
|---|---|---|---|---|
| `width` | 64 | 16–256 | Hidden channel dimension (latent width). More width = more capacity but more VRAM. | Start small (32), increase if underfitting. |
| `num_layers` | 2 | 1–4 | Number of iterative Gated-FNO blocks. More layers = deeper spectral processing. | 2–3 is usually sufficient. Diminishing returns beyond 4. |
| `num_gates` | 128 | 8–4096 | Granularity of the control vector $V$ across the spectrum. More gates = finer frequency-band control. | 128 is a good default. Increase to 256+ if you need precise frequency targeting. |
| `gate_mapping` | "log" | "linear" or "log" | How gate indices map to FFT frequency bins. **"log"** (default): denser at low frequencies — gate[0] covers ~0.2 kHz, gate[127] covers ~400 kHz. **"linear"**: uniform — each gate covers ~39 kHz. Log is better for TIDMAD because signals are log-spaced in frequency. | Use "log" (default) unless you have reason to prefer uniform spacing. |
| `static_v` | None | List[float], length=num_gates | **THE KEY HYPERPARAMETER.** Fixed gate values controlling which frequency bands the AI processes vs preserves. If None, defaults to all 1s (AI processes everything). | See "How to Tune static_v" below. |

### How to Tune `static_v`

`static_v` is a vector of length `num_gates`, where each element controls a frequency band:
- `v[i] = 1.0`: The AI fully processes this frequency band (denoising enabled).
- `v[i] = 0.0`: The signal in this band passes through unchanged (preserved exactly).
- `v[i] = 0.5`: Half AI processing, half bypass (partial denoising).

The vector maps to the full frequency spectrum (20001 FFT bins for seg=40000):
- With `gate_mapping="log"` (default): gate indices are log-spaced. Gate[0] covers ~DC to 0.2 kHz (1 bin). Gate[127] covers ~4.6–5.0 MHz (1490 bins). This gives fine control at low frequencies where TIDMAD signals are hardest.
- With `gate_mapping="linear"`: gate indices are uniform. Each gate covers ~39 kHz (~156 bins). Simpler but less precise at low frequencies.

**Tuning strategy for `static_v`:**
1. **Start with None** (all 1s) to establish a baseline with full AI processing.
2. **Check the file_vector** from the baseline: files 0-3 are low frequency, files 15-19 are high frequency.
3. **If low-frequency files score poorly** (score < 1.0 for files 0-3): the AI may be distorting the signal at those frequencies. Try setting `v[0:16] = 0.0` (protect low frequencies) while keeping `v[16:] = 1.0` (denoise high frequencies).
4. **If high-frequency files score well**: the model is already good at high frequencies. Focus the gate on protecting the weak bands.
5. **Iterate**: adjust the gate vector based on which files improve or regress after each experiment. The goal is to find the boundary between "AI helps" and "AI hurts" across the frequency spectrum.

**Important constraints:**
- `len(static_v)` MUST equal `num_gates`. If you change `num_gates`, you must also resize `static_v`.
- Values should be between 0.0 and 1.0 (though values outside this range are technically allowed).
- Setting all values to 0.0 makes the model a pure identity — no denoising at all.

---

## Known Characteristics
- **Zero Distortion**: Mathematically guarantees signal preservation in bands where $v_k=0$ within the Fourier path.
- **Global Receptive Field**: Fourier Path captures long-range periodic noise (e.g., 60Hz harmonics).
- **Control Interface**: The `static_v` vector is the primary lever for the Agent to inject physical priors about signal locations.
- **Parameter Count**: Scales as ~width² × (segmentation_size/2) × num_layers. With width=32, layers=3, seg=40000: ~61M params.
