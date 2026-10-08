# Runtime verifier provider contract

## Ownership and scope

`verifier_provider.py` owns discovery, the incremental verifier protocol and source
identity. `session.py` owns actual costs, predictions, admission and persistence.
Production owners retain data selection, optimizer work, validation and artifact
writing. Providers are explicitly selected trusted installed code; they may not
replace execution, budgets or task semantics. Historical implementations and
experiment selections belong to consumer repositories.

## Selection and identity

`--runtime_verifier NAME` selects one `siderius.runtime_verifiers` entry point.
Its zero-argument factory returns `RuntimeVerifierProfile(name, version, create,
sources, qualified_assemblies)`. `sources` maps stable relative labels to concrete
source paths. The profile's `RuntimeVerifierIdentity` contains name, version,
content SHA-256 and qualified assembly SHA-256. The bounded assembly includes the
factory, session, detector, component records, workload, calibration, executor
status and production phase owners. Qualification belongs to the external
provider; installation alone is not qualification.

The normal path omits selection and identity and constructs the existing native
`AdaptiveUnitVerification` directly. No discovery or external factory runs on
that path. Missing or duplicate entry points, mismatched names, unqualified
assemblies, modified provider sources and invalid factory results fail with
explicit errors. There is no fallback to native after a selection is made.

The selected identity resolves before workflow execution, travels through the
immutable workflow carrier and tuner schema, and is compared in the root and
child workspace locks. `RuntimeControlPolicy` serializes selection and resolved
identity into the subprocess JSON. Validation in each actual environment checks
that identity again; session construction, phase construction and consumption of
phase evidence recheck it. A resumed observation cannot change verifier identity
or lose an earlier explicit selection. Old records are read without mutation;
use a new workspace to migrate an old run.

## Factory and verifier interface

The profile's `create` callable receives keyword arguments:

- `unit`: the production phase's existing unit name.
- `config`: validated `AdaptiveVerificationConfig`.
- `prior_expected_unit_ms`: optional prior from the isolated calibration key.
- `completion_policy`: selected versioned admission semantics.

It returns `RuntimeVerifier`: state, terminal flag, failure reason, verification
seconds and workload-completion permission; plus `feed`, `active_interval`,
`finalize`, `measurement` and `prediction`. Before any observation, `measurement`
may be absent; after observations it records the evidence even when verification
fails. The session requests a prediction only for a verified state, which must
yield a valid `RuntimePrediction`. Component measurements pass existing Pydantic
validation.
No caller may treat an insufficient rate as verified solely because work ended.

An external implementation can reject incompatible completion policies during
construction. Adapters own compatibility with their configuration schema and
historical interval semantics. Unknown configuration must not be silently dropped;
any ignored native default needs an explicit documented compatibility rule.
Native interval handling and stopping thresholds remain unchanged.

## Calibration and historical evidence

Native observations retain the existing calibration key format. Selected providers
append their complete validated identity to that key, isolating native, different
providers and changed source or assembly versions. New runs with the same selected
identity can use their own eligible earlier observations. Completion-only evidence
remains ineligible regardless of the provider.

Archived observations without provider identity are not automatically relabeled or
imported as selected-provider priors. Consumer-owned offline replay may explicitly
supply a preserved prior as evidence. This interface does not claim to restore
missing historical inputs or fresh stochastic LLM responses. Prompt-facing
historical projections belong to the consumer, while runtime provenance always
retains the implementation actually selected.
