# RNN — LSTM Encoder-Decoder (Seq2Seq)

## Overview

A sequence-to-sequence LSTM encoder-decoder. The encoder reads the full input
sequence and produces a final hidden state; the decoder uses that hidden state
(and the input sequence via teacher forcing) to produce per-timestep logits.

**Forward contract:** `[B, T] int64 → [B, 256, T] float32`

---

## Architecture

### 1. Encoder

An LSTM that processes the full ADC token sequence:

$$e_t = \text{Embedding}(x_t) \in \mathbb{R}^{d_\text{emb}}$$

$$h_t, c_t = \text{LSTM}(e_t,\ h_{t-1},\ c_{t-1})$$

with $L = \texttt{num\_layers}$ stacked LSTM layers. The encoder discards all
intermediate outputs and retains only the final hidden and cell states:

$$(h^*, c^*) = (h_T, c_T) \in \mathbb{R}^{L \times B \times d_h}$$

where $d_h = \texttt{hidden\_dim}$.

### 2. Decoder

The decoder takes the same input sequence $x$ (teacher forcing — uses ground-truth
tokens at every step) and processes it with the encoder's final state as the initial state:

$$\hat{h}_t = \text{LSTM}(\text{Embedding}(x_t),\ h^*,\ c^*)$$

All decoder hidden states are projected to 256 logits:

$$\hat{y}_t = \text{Linear}_{d_h \to 256}(\hat{h}_t) \in \mathbb{R}^{256}$$

$$\hat{y} = [\hat{y}_1, \ldots, \hat{y}_T]^\top \in \mathbb{R}^{B \times 256 \times T}$$

### 3. Teacher Forcing

During training, the decoder always receives the true $x_t$ as input regardless of
its previous output. This avoids exposure bias during training but means inference
behaviour (autoregressive decoding) is never practised.

---

## Key Configuration Parameters

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `embedding_dim` | 128 | 8–512 | Embedding size for ADC tokens in both encoder and decoder |
| `hidden_dim` | 256 | 8–1024 | LSTM hidden state size — primary capacity parameter |
| `num_layers` | 2 | 1–6 | Stacked LSTM depth in both encoder and decoder |
| `dropout` | 0.1 | 0–0.5 | Applied between LSTM layers (ignored if `num_layers=1`) |
| `segmentation_size` | 40000 | ≥ 1000 | Input sequence length |

---

## Known Characteristics

- Sequential processing: LSTM hidden state carries information across the entire sequence — effective receptive field is the full $T$ timesteps
- Teacher forcing means training is stable, but the model never learns to recover from its own prediction errors
- Memory cost is $O(T)$ — much lower than Transformer's $O(T^2)$, making it viable for longer sequences
- Vanishing gradients can limit learning of very long-range dependencies despite the theoretically full receptive field
- Increasing `hidden_dim` is the most direct way to add capacity; increasing `num_layers` helps with hierarchical features
