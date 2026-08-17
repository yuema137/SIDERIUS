# `advice/`

Operator-written JSON advice files passed to SIDERIUS agents at run time.
Two levels exist and the distinction matters — they have different schemas
and different injection points in the graph.

---

## `advice/single_agent/`

JSON with **one top-level key**, naming the single agent the advice
targets. Used when invoking one agent in isolation (typically the tuner
via `scripts/run_comparison.py --human_advice_file …`).

```json
{ "tune": "Aggressively explore the static_v gate vector ..." }
```

Current contents — all `gated_fno`-family tuner explorations targeting
the `static_v` gate spectrum:

| file | target agent |
|---|---|
| `gated_fno_explore_static_v.json` | `tune` |
| `gated_fno_explore_static_v_linear_closed.json` | `tune` |
| `gated_fno_explore_static_v_linear_open.json` | `tune` |
| `gated_fno_explore_static_v_step02.json` | `tune` |
| `gated_fno_freq_band_aware_v1.json` | `tune` |

---

## `advice/workflow/`

JSON with **multiple top-level keys**, one per agent in the 5-agent chain
(`interpret`, `propose`, `implement`, `validate`, `tune`) — plus an optional
`mindset` preamble used by the proposer. Used by chain workflows
(`sdsc_submission_scripts/run_chain.sh`).

```json
{
  "interpret": "...",
  "propose": "...",
  "implement": "...",
  "validate": "...",
  "tune": "..."
}
```

Missing keys default to empty string — partial files are supported
(e.g. `chain_v2_proposer_advice.json` ships only `propose` + `implement`).

Current contents:

| file | shape | purpose |
|---|---|---|
| `human_advice_chain_test.json` | all 5 keys | Smoke-test chain — tiny architectures, < 5 epoch budgets |
| `human_advice_chain_formal.json` | all 5 keys | Real research chain — wavenet-anchored, full budgets |
| `explore_novel_v{1..4}.json` | `mindset`/`propose`/`implement`/`tune` | Exploration lane — paradigm-shift architectures |
| `exploit_cnn_v{1..4}.json` | `mindset`/`propose`/`implement`/`tune` | Exploit lane — hybridize on proven TCN/CNN backbones |
| `exploration_adaptive_v{1,3}.json` | `propose`/`implement`/`tune` | Adaptive proposer (regime-aware) |
| `chain_v2_proposer_advice.json` | `propose`/`implement` | Proposer hints for inheritance-aware chain runs |
| `chain_v3_proposer_advice_time_sens.json` | `propose`/`implement`/`tune` | Time-sensitive proposer hints |

---

## `advice/gate/`

Same 4-key shape as `advice/workflow/` (`mindset`, `propose`, `implement`,
`tune`), but a different **purpose**, and the distinction is the point:

```text
workflow/  advice for a run whose goal is a better model
gate/      advice for a run whose goal is proving the plumbing still works
```

A Gate run is a **capability / wiring validation fixture, not a scientific
campaign**. Its files say so explicitly, because a proposer that is not told
this will do the sensible scientific thing — propose an ambitious model — and
the Gate then spends its attempts on pre-flight VRAM refusals instead of on the
code path under test. The Gate standard names the cost directly:

> **be generous on GPU VRAM, stingy on wall time** — a VRAM-gate rejection
> wastes a whole Gate attempt.

Every `gate/` file therefore carries, at minimum:

* a `mindset` stating that scientific quality is NOT under test — a low score,
  a collapsed model or a failed HealthGate does not make the run wrong;
* a `propose` block bounding model size in the proposer's own terms
  (parameter count AND the VRAM allowance the run actually enforces);
* a `tune` block saying "conservative hyperparameters, this is a wiring
  validation".

**Binding for Gate 1 and Gate 2 (operator decision, 2026-08-16): each model is
limited to 4 GiB of GPU VRAM.** Both halves are required or the constraint is
unreachable — the run enforces it with
`--trial_vram_budget_gb 4 --formal_vram_budget_gb 4`, and the advice states the
same number so the proposer can aim at it rather than discover it by refusal.

| file | purpose |
|---|---|
| `gate_pr_a_classifier_advice.json` | PR A Gate — classifier output contract + built-in loss |
| `gate_pr_a_regressor_advice.json` | PR A Gate — regressor output contract + `smooth_l1` |
| `gate_pr_c_regressor_advice.json` | PR C Gate — regressor lane |
| `gate_07b_structural_refactor_advice.json` | Step 07 PR 07b — tuner structural-decomposition validation; 4 GiB hard allowance, shallow conv denoiser, no novelty |

Passed with `--advice <path>` (which takes precedence over
`--human_advice_file`); see `sdsc_submission_scripts/run_one_iteration.py`
`--advice`, where list-of-lines values are normalised to newline-joined strings.

---

## Adding a new advice file

* If your advice targets **one agent** only, put it in `single_agent/` with
  a single top-level key matching that agent's name (`interpret`, `propose`,
  `implement`, `validate`, or `tune`).
* If it spans **multiple agents in a chain**, put it in `workflow/` with
  one key per agent. Omit keys you don't need.
* File names follow the convention `{purpose}_v{N}.json` for versioned
  experiment lanes, or `{descriptor}.json` for one-off runs.

The CLI flag is `--human_advice_file` (chain workflows) or
`--human_advice_file` (single-agent runs of `scripts/run_comparison.py`).
The file's structure is validated by the receiving agent's input schema —
keys that don't match an expected agent name are silently ignored.
