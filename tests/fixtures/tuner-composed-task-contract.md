# Symbolic tuner fixture contract

`TunerComposedTask` in `tuner_composed_task.py` supplies the task data path for
`tests/helpers/tuner_composed_fixture.py`. Its 20 partitions each contain eight
symbolic row identities per train/eval leg. Scope construction applies the
requested partition selection, scope portion and scope row ceiling.

`training_dataset` returns a sized planning-only dataset. It counts the transported
training scope, applies `EpochSamplingParams.train_portion` with floor rounding
and a one-row minimum for nonempty scopes, then applies `max_samples`. An empty
scope remains empty. The epoch seed does not affect cardinality. No features or
labels are materialized; indexing raises. Evaluation materialization, prediction
reads and writes remain forbidden. `tuner_composed_effects` guards external effects.

Production `resolve_task_training_rows` and training-batch planning run unchanged.
The data-scope pseudo witnesses cover sampled counts through the real resolver,
refusal of sample reads, scope transport, Health coverage and orchestration.
Other consumers cover runtime forecasts, collapse continuation, invented models,
failed tuning rounds and funnel admission. These fixtures do not qualify scientific
training, resource measurements or paper results. Integration tests remain opt-in;
this contract does not change CI selection.
