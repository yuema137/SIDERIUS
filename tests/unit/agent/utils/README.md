# Agent utility tests

Pure helper owners are [`architectural_pattern_tagger.py`](../../../../src/agent/utils/architectural_pattern_tagger.py) and [`proposer_preflight.py`](../../../../src/agent/utils/proposer_preflight.py). `test_proposer_preflight.py` uses synthetic profiles to check six-key output, producer-derived provenance, feasibility verdicts, monotonic budget factors, invalid-input rejection, deterministic default samples, and the no-GPU/no-disk boundary. `test_architectural_pattern_tagger.py` covers source-pattern classification. No model, bridge, or runtime service is invoked.

`.venv/bin/python -m pytest tests/unit/agent/utils/test_proposer_preflight.py -q`
