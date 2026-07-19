# V17 Launch Readiness Report — 2026-07-17

- **Status**: launch-readiness PR validated; V17 not launched
- **Verdict**: **READY FOR FINAL OPERATOR AUDIT**
- **Feature branch**: `feat/v17-launch-readiness`
- **Base**: `c1750aa8a3836deb5d7769fc566fb1b45bb71eba`
- **Canonical launch plan**: [`v17_20260717.md`](./v17_20260717.md)

## Completed

- PR #121 merged: PUNet `bilinear=False`, failed-attempt persistence, and
  partial-campaign exit handling.
- PR #122 merged: live Branch B inventory filtering with Branch A and Option C
  preserved.
- Optional `health_checks_config` now propagates from `run_chain.sh` through
  `run_one_iteration.py`, the workflow, and the validation-to-tuner protocol
  into `HyperparamTuningInput`.
- Omitted config paths preserve the existing default; explicit paths are
  echoed in the tuner output and iteration manifest.
- V17 loss and architecture advice files added and validated with the existing
  advice loader.
- V17 and V18 design documents aligned: V17 is observation plus persistence;
  independent stateful stop policies remain deferred to V18.
- The production two-chain command was dry-run for all 20 rendered iterations
  with both V17 advice files and the observe-mode config.

## Deterministic validation

Focused suite:

```text
221 passed, 9 warnings in 7.59s
```

Broader adjacent suite:

```text
1822 passed, 9 warnings in 154.55s
```

Ruff check and Ruff format check passed for all changed Python and relevant
test files. `git diff --check` passed. Pyright could not start because the
locally bundled Pyright JavaScript uses syntax unsupported by the installed
Node runtime (`SyntaxError: Unexpected token =` in `pyright/dist/dist/vendor.js`);
this is an environment limitation, not a reported type-check pass.

## Gate 1

The canonical real-LLM pseudo-training path was exercised with
`llm_configs/openai_tiered_v1.json`.

- Loss advice: full run passed, exit 0. The proposal used Option C, generated
  `balanced_smoothed_ce_confidence_penalty`, passed schema, implementation,
  compilation, dummy-tensor, and gradient validation, and completed pseudo
  tuning.
- Architecture advice: proposal, schema, implementation, compilation, and all
  seven model validation checks passed for `pooled_global_res_tcn`. The broader
  pseudo tuner then selected a one-million-sample segment and was killed during
  the structural resource probe (exit 137). That post-validation LLM/runtime
  choice is outside the advice Gate 1 acceptance boundary; deterministic advice
  tests cover both rendered control-variable contracts.

## Final Gate 2

Workspace:

```text
/tmp/v17_launch_gate2_20260717_190153
```

Seed policy: the single complete post-M9 WaveNet seed was used. The partial
PUNet seed was deliberately not used for this smoke gate.

Result:

```text
elapsed: 859 seconds
exit: 0
iterations: 2/2 completed
tuner rounds: 2/2 in each iteration
token usage: 537,319
```

Both manifests and tuner outputs persist:

```text
health_checks_config: configs/health_checks_baseline_observe_mode.yaml
```

Every one of the four completed rounds contains all six configured gate
results. All per-gate and round-level resolved actions are `continue`, while
the three blocking-style checks preserve
`would_invalidate_under_production_policy=true` for collapsed outputs.

| Iteration | Round | Model | Loss branch / selected loss | Score | Score validity | Blocking checks | Resolved action |
|---:|---:|---|---|---:|---|---|---|
| 1 | 1 | `spectral_film_tcn_unet` | A / CE | `null` | invalid, structured collapse reason | failed / failed / failed | `continue` |
| 1 | 2 | `spectral_film_tcn_unet` | A / focal | `0.6074581238475681` | valid | failed / failed / failed | `continue` |
| 2 | 1 | `gated_multiscale_res_tcn` | C / `ce_entropy_floor` | `null` | invalid, structured collapse reason | failed / failed / failed | `continue` |
| 2 | 2 | `gated_multiscale_res_tcn` | C / `ce_entropy_floor` | `-2.381903303531087` | valid | failed / failed / failed | `continue` |

Option C was exercised end to end in iteration 2: the complete
`custom_loss_spec` produced `ce_entropy_floor`, which passed implementation and
validation, entered the existing registry, and trained through the tuner.
No numeric `5.5762667` value was accepted as a score. Its appearances are only
diagnostic text describing the historical phantom artifact. No persisted Gate
2 artifact names the default `configs/health_checks.yaml` as its effective
configuration.

## Remaining before launch

No code or design blocker remains on this feature branch. The remaining work
is operational and must occur after merge:

1. merge the launch-readiness PR after review;
2. update and verify a clean local `master` against `origin/master`;
3. rerun the focused regression suite from merged master;
4. verify config/advice hashes and seed parsing;
5. inspect the live generated model/loss inventory for stale entries;
6. verify disk space, `nvidia-smi`, and a CUDA tensor allocation;
7. confirm no competing GPU process;
8. repeat the production command dry-run from merged master; and
9. obtain explicit operator approval before launching.

Independent tuner stop policies were reviewed, found technically feasible,
and intentionally deferred to V18. They are not required for V17 launch.

The production command rejects pre-existing timestamped workspaces, logs, exit
markers, and screen session names before creating launch artifacts. Operators
must monitor cumulative token usage per iteration because the final two-iteration
Gate 2 alone consumed 537,319 tokens.

## Final verdict

**READY FOR FINAL OPERATOR AUDIT**
