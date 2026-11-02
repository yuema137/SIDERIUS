# Vocabulary integration fixture contract

`test_vocab_accumulation.py` exercises interpretation-to-proposal vocabulary
transport, candidate promotion, versioned prediction accuracy and confirmed
vocabulary links using supplied summaries and finite recording bridges.

Each previous-proposal fixture that expects a comparable outcome explicitly
supplies `observed_prediction_reference`, constructed with the public
`ObservedPredictionReference` schema and the fixture metric's id and direction.
The scenarios declare proposal-time observations of 5.576, or 6.1 for the third
promotion iteration. These are fixture evidence, not scientific measurements.
They are supplied independently of the authored prediction's `current_value`.
The imported legacy proposal is copied before adding the stamp; other consumers'
legacy fixtures are not mutated.

The production owner is `nodes.result_interpretation_agent.prediction`:
`read_observed_prediction_reference` accepts only stamped evidence with matching
metric identity. An unstamped proposal remains unevaluated. These integration
fixtures must not monkeypatch that rule or derive observational evidence from
an LLM-authored field. Existing unit witnesses cover the unstamped refusal.

The proposal-prompt test explicitly requests `synthetic_dataset_profile` from
`tests/conftest.py`; profile-dependent rendering has no ambient dataset default.
Its module-scoped context is restored by fixture teardown. The other scenarios
do not require dataset binding.

Validation keeps all outcome, monotonic-growth, promotion, versioned-accuracy,
link and prompt assertions. The default invocation uses recording bridges;
real-provider modes require separate authorization and are not fixture-repair
validation. This opt-in integration module is not added to CI selection.
