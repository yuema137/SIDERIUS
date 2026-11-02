# Data Analysis UTF-8 canonical identities

`common.canonical_json_bytes` owns sorted-key, compact, `ensure_ascii=False`
UTF-8 bytes for Data Analysis, generated skills and the judge/rubric consumers.
`canonical_sha256` hashes exactly those bytes. This differs intentionally from
`core.canonical_json`'s ASCII escaping; consumers must not interchange them.

## Numeric encoding and readers

Finite values retain the previous canonical bytes. Models are projected through
`core.record_encoding.model_record_value`, preserving aliases and serializers
while recovering non-finite leaves lost by Pydantic JSON-mode projection.
`core.record_encoding.canonical_value` is the only non-finite encoding owner.
Non-finite documents carry `$siderius_encoding` with version
`siderius.nonfinite/v1` and typed paths. Actual NaN, positive/negative infinity,
null and strings such as `"NaN"` remain distinct. Output uses `allow_nan=False`.
The reserved member cannot be supplied as an ordinary top-level data field.

Data Analysis's `FrozenModel` inherits `core.record_encoding.RecordModel`:
`model_validate_json` and `model_validate` decode the envelope before typed
validation. Decode the whole document, not individual nested fields. This
covers analysis input/report files, result JSONL, worker messages and generated
registry files written by the canonical owner. It does not change arbitrary
`model_dump_json` calls into canonical record writers.

Identity projections admitting arbitrary metadata use `model_record_value`
before hashing: scientific input, generated skill executable/registry bodies,
and generated-skill discovery. Skill-parameter validation uses the same lossless
projection for its worker response and digest, so execution verifies the actual
validated parameters. Report summary byte limits measure the encoded
representation. Finite-only projections retain their existing behavior.

## Historical verification

`replay_json_bytes(value, version=...)` is an explicit archive verification
primitive, never the default writer. `None` reproduces the historical UTF-8 JSON
projection (including bare constants in dictionaries and nulls in model JSON
projections); `siderius.nonfinite/v1` selects the strict writer. Unknown versions
are refused. An encoding version is not authentication: callers must bind the
actual archive bytes to their trusted digest before relying on reconstruction.
Never try both encodings merely to make an untrusted digest match.

Valid legacy finite/null model records remain readable and byte-stable. A
legacy null has no recoverable non-finite meaning. In particular, exact-input
Data Analysis resume refuses a current non-finite input when the stored input
contains null: the new canonical bytes differ. Existing ambiguous/invalid
archives are not repaired or rewritten. Historical dictionary bytes can be
reproduced explicitly using the legacy primitive; they are not new strict JSON.

Judge requests, rubric weights and generated-program numeric declarations
already reject non-finite numeric values. Their finite canonical bytes, prompt
identities and response schemas do not change. Judge replay continues to check
its trusted byte anchor and reconstruct the same canonical evidence. A
non-finite Data Analysis input or result changes its digest and any prompt
containing that digest; generated interfaces with non-finite schema leaves
likewise receive distinct identities. No global legacy-writing mode is added.

## Compatibility and validation

The regression owner is
`tests/unit/agent/data_analysis/test_canonical_encoding.py`: strict parsing,
float/string/null round trips, fixed legacy UTF-8 bytes and digest, production
store/reader round trips, scientific-input and generated/discovery identities.
Existing judge prompt goldens and replay tests protect finite identities.

Historical experiment reproduction must pin the exact archived framework revision
in siderius-exp's `pyproject.toml` SIDERIUS Git dependency and regenerate/retain
the matching `uv.lock`. The affected external configurations include
`siderius-exp/experiments/tidmad/data_analysis_pair/analysis_on.yaml` and
`experiments/tidmad/data_analysis_raw_characterization/analysis_config.yaml`;
these select Data Analysis behavior, but do not provide a framework encoding
switch. The dependency/environment binding must pin the pre-migration revision
when exact historical non-finite identity/prompt bytes are required (this
migration was based on `1c13616cb054daabe977d294c61d587d538dab88`). No external
experiment file or archived evidence is modified by this framework migration.
