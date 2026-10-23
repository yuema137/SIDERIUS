# Candidate probe construction and output validation

## Owners and boundaries

`model_io_probe_skill` constructs synthetic inputs. `probe_config_kwargs`
supplies required construction fields and respects fixed temporal extents.
`candidate_probe_extent` reads the instantiated candidate length and refuses a
conflicting fixed temporal contract. Fallback input extent is 64 only when no
concrete length is available; it is never an independent output constraint.
Explicit `batch` and `symbolic` extents must be positive Python integers, excluding
booleans. Floats (including integral-valued floats and nonfinite values), strings
and other non-integer values raise `ProbeConstructionError` before tensor
allocation. Values are not coerced and invalid explicit values never select a
fallback. Omitted/`None` arguments retain the input recipe defaults; fixed
contract dimensions remain authoritative for valid explicit extents.

`model_output_geometry` owns output validation. `validate_model_output` requires
a finite Tensor at an admissible declared output dtype, then checks rank, fixed
extents, batch consistency and symbolic equality against the actual input.
`validate_output_shape` exposes the same shape checks without tensor allocation.
Shared symbols bind from input axes; independent output symbols bind on first
occurrence in the current output. Repeated occurrences must agree. Dynamic axes
are independent. Bindings do not persist between calls, so candidate sizes can
change. Symbolic/dynamic zero extents are legal; fixed extents remain positive.
Explicit fixed batch dimensions remain authoritative.

The candidate's declared output type selects the existing classifier/regressor
projection through `declared_output_tensor`; this repair does not redefine that
projection. Smoke, validator, task-owned fixtures and generated tests use the
same output checker. `model_probe_test` renders generic contract-aware tests;
no-contract legacy tests retain their explicit legacy geometry. Generated tests
also exercise backward propagation, as the validator does.

## Synthetic targets and failures

`resolve_output_shape` derives output geometry only from fixed dimensions and
actual input bindings. `expected_output_shape` first realizes a probe input and
then delegates to that resolver. Neither fills independent output symbols or
dynamic output axes with a probe constant. Unresolved geometry raises
`ProbeConstructionError` with guidance to supply task-owned target samples.
The generic resource probe uses this rule for continuous and class-index target
construction; supplied task input/target samples retain their existing path.
Model outputs must not be used to invent scientific target semantics.

Shape, dtype and finite-output errors are candidate verdicts. Fixture setup
errors retain `ModelProbeSetupError` and escape candidate repair. Input recipe
bindings describe input geometry only; unrelated output symbols do not make a
valid single-symbol input binding ambiguous. Output-only config binding through
`symbolic_extent_config_field` is not supported because that field selects the
fixture input extent, not an output constraint.

## Validation and scientific compatibility

Tests cover independent and shared symbols, repeated names, dynamic axes,
fixed dimensions, batch roles, empty outputs, dtype/finiteness, and production
smoke/validator/generated-test/task-fixture consumers. Resource tests distinguish
resolvable targets from unsupported guessed geometry. These CPU checks establish
structural compatibility and gradient execution, not model quality, resource
admission or bit-exact scientific reproduction. Historical framework pins,
model/configuration artifacts, seeds and environment bindings belong in the
experiment repository; no task-specific compatibility default is added here.

Tasks with constrained input values can supply a
[task-owned candidate input](task_model_probe.md). The provider owns semantic
input validity while the framework owns structural output validation.
