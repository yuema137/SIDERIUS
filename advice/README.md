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
(`scripts/run_exploration.py`, `sdsc_submission_scripts/run_chain.sh`).

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
