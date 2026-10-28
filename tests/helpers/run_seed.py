"""The literal run seed tuner-driving unit tests supply (issue #983).

The tuner refuses a missing ``HyperparamTuningInput.run_seed``; an entry
boundary resolves it in production. Tests pass this literal so their derived
attempt seeds stay reproducible.
"""

TEST_RUN_SEED = 20261027
