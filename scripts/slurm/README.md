# `scripts/slurm/`

The portable one-iteration Slurm wrapper. Site resource settings are supplied
by `sbatch`; the wrapper requires an explicit absolute checkout and validates
that checkout's own `.venv` before probing or running the iteration.
