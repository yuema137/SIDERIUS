# Candidate probe construction

`probe_config_kwargs` supplies only required construction fields and respects a
fixed temporal contract. `candidate_probe_extent` resolves the instantiated
candidate length and refuses a conflicting fixed contract. Implementor and code
validator use this shared extent for model input and expected output; symbolic
alignment does not mean a model must accept arbitrary short inputs.

Fallback geometry is 64 only when no concrete length is available. These CPU
forward/gradient checks establish shape compatibility, not memory admission,
scientific validity or output-quality guarantees. No dataset, task name or
hardware-specific length is selected here. Existing shape realization rejects
ambiguous independent symbolic axes rather than assigning one configured length
to unrelated dimensions.
