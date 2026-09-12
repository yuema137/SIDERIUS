# `src/agent/utils/`

Small shared helpers used by proposal/tuning callers; this package is neither
a node registry nor a workflow entrypoint. [`architectural_pattern_tagger.py`](architectural_pattern_tagger.py)
classifies a proposal's model type/config into a closed architectural-pattern
vocabulary. [`proposer_preflight.py`](proposer_preflight.py) computes a
CPU-only, static-uncalibrated wall-time estimate for advisory pre-flight; measured
runtime decisions remain owned by the runtime policy.

The callers and schema authorities remain outside this package. Focused checks
are [`test_architectural_pattern_tagger.py`](../../../tests/unit/agent/utils/test_architectural_pattern_tagger.py)
and [`test_proposer_preflight.py`](../../../tests/unit/agent/utils/test_proposer_preflight.py).
