# Standard single-iteration launch resolution

The standard CLI, configuration inspection and execution share these owners:

| Boundary | Owner | Contract |
| --- | --- | --- |
| CLI options and normalization | `workflows.standard_cli` | `build_parser`, `normalize_args`; declared defaults and aliases |
| Advice bytes and identity | `workflows.advice` | One observed artifact provides content and digest |
| Launch identity | `workflows.launch_identity` | Existing topology, retention, experiment label and advice identity resolution |
| Standard LLM routing | `workflows.llm_config.resolve_standard_llm_config` | Explicit JSON wins; otherwise preserve legacy CLI routing and reflector fallback |
| Launch carrier projection | `workflows.standard_launch.build_standard_launch_config` | The exact `WorkflowLaunchConfig` supplied to `run_workflow` |
| Execution lifecycle | `workflows.run_one_iteration` | Composition, restoration, invariants, environment, directories and invocation |

The runner re-exports moved identity and output-type functions for existing
callers. There is no second default table in the projection. Its 89 explicit
keywords preserve the prior inline construction, including `0` to `None`
normalization where the CLI uses zero to disable a bound.

## Preconditions and effects

The projection accepts launch-ready arguments. Before calling it, the caller
must run CLI normalization, resolve the physical dataset directory, resolve
watchdog settings back onto the arguments, and supply the resolved identity,
restored source paths and validated fixed candidate plan. It does not perform
those lifecycle operations. `WorkflowLaunchConfig` remains a frozen transit
dataclass; downstream Pydantic schemas own their validation.

Importing the shared modules does not import the effectful runner, read dotenv,
create providers, modify environment variables or create run directories.
Calling identity resolution still lazily imports `model_exploration` through
the existing literature-config owner. That call is not an inert or sandboxed
inspection boundary. Explicit JSON/advice/literature configuration reads also
remain reads of caller-selected files.

LLM routing resolution does not instantiate clients. Missing node blocks still
use their existing downstream owners; a serialized `WorkflowLLMConfig` alone
is not a complete report of effective node settings. Likewise, `None` in a
launch carrier can mean a later configured or agent-owned choice. Inspection
must identify that owner and constraints rather than inventing a final value.

## Verification and remaining scope

Tests verify effect-free imports, standard routing precedence, reachable
keyword transport and the actual `main` path passing the shared projection's
same object to `run_workflow`. Structural censuses follow the projection only
when the runner passes it as `launch`; an unused builder does not count.

This extraction changes no training or scientific policy and does not implement
the complete #585 setup-review lifecycle. Full effective node settings,
deterministic review, optional semantic review with an explicit recorded skip,
HTML, input-staleness enforcement and reviewed launch binding remain separate
work. Initial lifecycle support targets a fresh workspace and one standard
iteration; existing chains are not thereby claimed to be review-integrated.
