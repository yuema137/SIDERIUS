# Runtime bootstrap — making a new machine operational

`scripts/runtime_bootstrap.py` answers one question about a machine:

> Can this environment produce **measured** runtime evidence, and is it
> therefore safe to launch on?

It requires no source or JSON editing. Everything it records goes through
the versioned calibration registry.

```bash
# from the repo root, project venv
.venv/bin/python scripts/runtime_bootstrap.py
```

Exit code `0` = READY, `1` = NOT READY, `2` = usage error.

## What it does

| # | Step | Why it is here |
|---|---|---|
| 1 | inspect the accelerator | no device, no measurement |
| 2 | hardware compatibility profile | the identity that decides whose evidence is comparable |
| 3 | execution environment profile | this installation, so cross-machine evidence stays a prior |
| 4 | dataset | a probe without data measures nothing real |
| 5 | contention window | 10 s of pre-probe samples; a busy GPU is refused, not averaged in |
| 6 | probe executors | the real model, built the way production builds it |
| 7 | bounded **training** probe | ms/step |
| 8 | bounded **inference** probe | ms/batch — measured separately, never derived from training |
| 9 | setup + VRAM | the costs a formal estimate must include |
| 10 | record + hash-verified read-back | evidence that cannot be read back is not evidence |
| 11 | launch self-test | the **same** check the launch guard runs |

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--model` | `punet_ce_loss_control_nano` | Registered model to probe. Bootstrap measures the ENVIRONMENT, so small is correct. |
| `--segmentation-size` | `40000` | Model config for the probe. |
| `--batch-size` | `8` | Training batch for the probe. |
| `--data-dir` | canonical `TIDMAD_DATA_DIR` | Override the dataset directory. |
| `--registry-dir` | per-user registry | Isolate the registry (sets `SIDERIUS_CALIBRATION_DIR` for this process). Recommended for a first run. |
| `--max-wall-seconds` | `90` | Hard cap for the probe. |
| `--warmup-steps` | `3` | Discarded before timing. |
| `--timed-train-steps` | `7` | Timed optimizer steps. |
| `--timed-inference-batches` | `5` | Timed inference batches. |
| `--expected-peer-pid` | none | An explicitly registered peer PID (repeatable). Any OTHER process makes the window contended — peers are never inferred from a name. |
| `--dry-run` | off | Report what WOULD run. No probe, no writes. |
| `--json` | off | Machine-readable output. |

## Reading the verdict

```text
====================================================================
  SIDERIUS runtime bootstrap — READY
====================================================================
  [ok  ] inspect accelerator: NVIDIA GeForce RTX 5090 x1, 31.3 GB, torch 2.7.0
  [ok  ] contention window: single_candidate_idle (5 samples)
  [ok  ] bounded training probe: 17.62 ms/step
  [ok  ] bounded inference probe: 8.06 ms/batch
  [ok  ] registry self-validation: generation 3, all records hash-verified
  [ok  ] launch self-test: 8 checks | policy=runtime_decision_policy@1.0.0+…
```

Every `FAIL` line carries a remedy. Common ones:

| Failure | Meaning | Remedy |
|---|---|---|
| `inspect accelerator` | no CUDA-capable torch or no visible device | check `nvidia-smi` and `CUDA_VISIBLE_DEVICES` |
| `dataset` | TIDMAD directory unreadable | pass `--data-dir` or fix the canonical path |
| `contention window` | another process is on the GPU | stop it and re-run — a contended measurement is not a baseline |
| `bounded probe` (oom / wall_cap) | the bootstrap model is too big for this device | pick a smaller `--model` |
| `record observations` | registry not writable | check permissions on the registry directory |
| `launch self-test` | the decision subsystem is not launch-safe on this build | a code problem, not an environment one — report it |

## What bootstrap does NOT do

It proves an environment can bootstrap. It does **not** validate estimator
accuracy across model families, parameter scales and concurrency regimes
— that is the C12 campaign
(`docs/design/runtime_estimation_and_calibration.md` §24).

One clean bootstrap gives you a **candidate** observation per operation,
not calibration. Under the D4 lifecycle a bucket becomes provisional at
two mutually consistent observations and validated at three, so running
bootstrap a few times on an idle machine is the honest path from
"measured once" to "calibrated".

It makes **no LLM calls** and touches no run workspace.
