# Provenance

All data are generated locally by `plugins/_masked_task.py::generate_shard`
from seed `20260829`. The pack has no downloads, private inputs, scientific
claims, or external repository dependency. Runtime data are materialized into
the caller's workspace and are not committed.

The Health dispersion floor is a demonstration threshold separated by fixed
synthetic constant and varied controls. It is not fitted to scientific data.

## H100 resource qualification

The first bounded TestPod run exposed an invalid plugin metadata token:
`PLUGIN_LOSS_REDUCTION = "mean_over_valid_elements"` computed the intended
objective but was outside the loader's supported comparability vocabulary.
Repository SHA `1acfe3bb` corrected the declaration to `"mean"`; mask semantics
remain in the objective implementation. The fresh qualification then ran two
production isolated preflights on the same H100, candidate, task-valid batch,
loss, and composition fingerprint. A `1.0 GB` cap admitted the measured
`0.229 GB` candidate, while a `0.001 GB` cap refused it as
`MEASURED_PEAK_ABOVE_VRAM_CAP`. The reviewed compact receipt is
`expected/h100_resource_qualification.json`; full transient worker logs remain
in the TestPod qualification workspace and are not packaged as framework
source.
