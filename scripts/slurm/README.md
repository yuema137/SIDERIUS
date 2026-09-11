# `scripts/slurm/`

The portable one-iteration Slurm wrapper. Site resource settings are supplied
by `sbatch`; pass `--siderius-checkout /absolute/path`, `--workspace`,
`--iteration`, and one or more `--source_paths`/`--seed_paths` values. The
wrapper validates that checkout's own `.venv` before probing or running; it
does not support cold-start runs. #431 probe transport remains a documented
limitation.
